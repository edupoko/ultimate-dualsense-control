import os
import socket
import tempfile
import unittest

from dualsense_led.ds5 import reports
from dualsense_led.ds5.device import DualSenseDevice
from dualsense_led.ds5.reports import BT_INPUT_CRC_SEED, BT_INPUT_SIZE, USB_INPUT_SIZE, bt_crc, build_output_report, parse_input_report


def make_block(**fields) -> bytearray:
    """Bloco de dados de entrada (sem id) com sticks no centro e tudo solto."""
    block = bytearray(reports.USB_INPUT_SIZE - 1)
    block[reports.IN_LX : reports.IN_RY + 1] = bytes([128] * 4)
    block[reports.IN_BUTTONS] = 0x08  # direcional solto
    block[reports.IN_TOUCH] = block[reports.IN_TOUCH + 4] = 0x80  # sem dedos
    for offset, value in fields.items():
        block[int(offset.removeprefix("at"))] = value
    return block


def usb_report(block: bytearray) -> bytes:
    return bytes([0x01]) + bytes(block)


def bt_report(block: bytearray, seq_tag: int = 0, valid_crc: bool = True) -> bytes:
    body = bytearray([0x31, seq_tag]) + block
    body = body[: BT_INPUT_SIZE - 4].ljust(BT_INPUT_SIZE - 4, b"\0")
    crc = bt_crc(BT_INPUT_CRC_SEED, bytes(body))
    return bytes(body) + (crc if valid_crc else b"\0\0\0\0")


class InputParseTest(unittest.TestCase):
    def test_idle_usb_report(self):
        state = parse_input_report(usb_report(make_block()))
        self.assertEqual(state.connection, "USB")
        self.assertEqual((state.lx, state.ly, state.rx, state.ry), (128, 128, 128, 128))
        self.assertEqual((state.l2, state.r2), (0, 0))
        self.assertIsNone(state.dpad)
        self.assertEqual(state.buttons, frozenset())
        self.assertEqual(state.touches, (None, None))

    def test_sticks_and_triggers(self):
        block = make_block()
        block[0:6] = bytes([1, 2, 3, 4, 200, 255])
        state = parse_input_report(usb_report(block))
        self.assertEqual((state.lx, state.ly, state.rx, state.ry, state.l2, state.r2), (1, 2, 3, 4, 200, 255))

    def test_buttons_and_dpad(self):
        block = make_block()
        block[reports.IN_BUTTONS] = 0x20 | 0x80 | 0x03   # cross, triangle, direcional para baixo-direita
        block[reports.IN_BUTTONS + 1] = 0x01 | 0x40 | 0x20  # l1, l3, options
        block[reports.IN_BUTTONS + 2] = 0x01 | 0x02 | 0x04  # ps, touchpad, mute
        state = parse_input_report(usb_report(block))
        self.assertEqual(state.dpad, "down_right")
        self.assertEqual(state.buttons, {"cross", "triangle", "l1", "l3", "options", "ps", "touchpad", "mute"})

    def test_every_dpad_direction(self):
        names = ["up", "up_right", "right", "down_right", "down", "down_left", "left", "up_left"]
        for hat, name in enumerate(names):
            block = make_block()
            block[reports.IN_BUTTONS] = hat
            self.assertEqual(parse_input_report(usb_report(block)).dpad, name)

    def test_imu_is_signed_little_endian(self):
        block = make_block()
        block[reports.IN_GYRO : reports.IN_GYRO + 6] = (-2).to_bytes(2, "little", signed=True) + (300).to_bytes(2, "little") + bytes([0xFF, 0x7F])
        block[reports.IN_ACCEL : reports.IN_ACCEL + 6] = (8192).to_bytes(2, "little") + bytes(4)
        block[reports.IN_SENSOR_TIME : reports.IN_SENSOR_TIME + 4] = (123456).to_bytes(4, "little")
        state = parse_input_report(usb_report(block))
        self.assertEqual(state.gyro, (-2, 300, 32767))
        self.assertEqual(state.accel, (8192, 0, 0))
        self.assertEqual(state.sensor_time, 123456)

    def test_touchpad_points(self):
        block = make_block()
        x, y = 1500, 900
        block[reports.IN_TOUCH : reports.IN_TOUCH + 4] = bytes([0x05, x & 0xFF, (x >> 8) | ((y & 0x0F) << 4), y >> 4])
        state = parse_input_report(usb_report(block))
        self.assertEqual(state.touches[0], reports.Touch(5, x, y))
        self.assertIsNone(state.touches[1])

    def test_battery(self):
        cases = {0x07: (75, "discharging"), 0x1A: (100, "charging"), 0x20: (100, "full"), 0xF3: (35, "error")}
        for raw, expected in cases.items():
            block = make_block()
            block[reports.IN_BATTERY] = raw
            state = parse_input_report(usb_report(block))
            self.assertEqual((state.battery_percent, state.battery_status), expected, hex(raw))

    def test_bluetooth_report_is_offset_by_one_and_checked(self):
        block = make_block()
        block[0] = 77
        block[reports.IN_BUTTONS + 1] = 0x02  # r1
        state = parse_input_report(bt_report(block))
        self.assertEqual(state.connection, "Bluetooth")
        self.assertEqual(state.lx, 77)
        self.assertEqual(state.buttons, {"r1"})

    def test_bluetooth_report_with_bad_crc_is_dropped(self):
        report = bt_report(make_block(), valid_crc=False)
        self.assertIsNone(parse_input_report(report))
        self.assertIsNotNone(parse_input_report(report, check_crc=False))

    def test_unknown_or_short_reports_are_ignored(self):
        self.assertIsNone(parse_input_report(b""))
        self.assertIsNone(parse_input_report(bytes([0x01]) + bytes(9)))  # relatório simples do Bluetooth
        self.assertIsNone(parse_input_report(bytes([0x09]) + bytes(USB_INPUT_SIZE)))


class OutputBuildTest(unittest.TestCase):
    def test_empty_report_changes_nothing(self):
        report = build_output_report("USB")
        self.assertEqual({i for i, b in enumerate(report) if b}, {0})

    def test_rumble_sets_motors_and_flags_only(self):
        report = build_output_report("USB", rumble=(200, 50))
        self.assertEqual(report[1] & 0x03, 0x03)
        self.assertEqual((report[1 + reports.COMMON_MOTOR_LEFT], report[1 + reports.COMMON_MOTOR_RIGHT]), (200, 50))
        self.assertEqual(report[1 + reports.COMMON_VALID_FLAG1], 0)

    def test_rumble_is_clamped(self):
        report = build_output_report("USB", rumble=(999, -4))
        self.assertEqual((report[1 + reports.COMMON_MOTOR_LEFT], report[1 + reports.COMMON_MOTOR_RIGHT]), (255, 0))

    def test_trigger_effects(self):
        effect = bytes(range(1, 12))
        report = build_output_report("USB", right_trigger=effect)
        self.assertEqual(report[1 + reports.COMMON_VALID_FLAG0], reports.VALID_FLAG0_RIGHT_TRIGGER)
        self.assertEqual(report[11:22], effect)
        left = build_output_report("USB", left_trigger=effect)
        self.assertEqual(left[1 + reports.COMMON_VALID_FLAG0], reports.VALID_FLAG0_LEFT_TRIGGER)
        self.assertEqual(left[22:33], effect)

    def test_trigger_effect_must_have_11_bytes(self):
        with self.assertRaises(ValueError):
            build_output_report("USB", right_trigger=b"\0" * 3)

    def test_bluetooth_has_valid_crc(self):
        report = build_output_report("Bluetooth", 3, rumble=(10, 20))
        self.assertEqual(len(report), reports.BT_OUTPUT_SIZE)
        self.assertEqual(report[1], 0x30)
        self.assertEqual(report[-4:], bt_crc(reports.BT_OUTPUT_CRC_SEED, report[:-4]))


class DeviceTest(unittest.TestCase):
    def test_read_state_returns_latest_and_none_when_empty(self):
        # SEQPACKET preserva os limites dos relatórios, como o hidraw (um relatório por read).
        reader, writer = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.addCleanup(writer.close)
        read_fd = os.dup(reader.fileno())
        reader.close()
        device = DualSenseDevice.__new__(DualSenseDevice)
        device._fd, device._sequence, device.connection = read_fd, 0, "USB"
        self.addCleanup(device.close)
        os.set_blocking(read_fd, False)
        self.assertIsNone(device.read_state())
        for lx in (10, 20):
            block = make_block()
            block[0] = lx
            writer.send(usb_report(block))
        self.assertEqual(device.read_state().lx, 20)
        self.assertIsNone(device.read_state())

    def test_send_output_writes_report_and_advances_sequence(self):
        with tempfile.NamedTemporaryFile() as node:
            with DualSenseDevice(node.name, "Bluetooth") as device:
                device.send_output(mute_led=True)
                device.send_output(mute_led=False)
            data = open(node.name, "rb").read()
        first, second = data[: reports.BT_OUTPUT_SIZE], data[reports.BT_OUTPUT_SIZE :]
        self.assertEqual((first[1], second[1]), (0x00, 0x10))
        self.assertEqual(first[3 + reports.COMMON_MUTE_BUTTON_LED], 1)


if __name__ == "__main__":
    unittest.main()
