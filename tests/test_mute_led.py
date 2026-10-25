import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dualsense_ultimate_control import hidraw
from dualsense_ultimate_control.service import LedService
from dualsense_ultimate_control.settings import load_settings
from dualsense_ultimate_control.widgets import AutostartRow, CompactToggleSwitch, MuteLedRow, ToggleSwitch
from test_sysfs import make_led, write_uevent


def crc32_le(crc: int, data: bytes) -> int:
    """CRC32 igual ao crc32_le do kernel (bit a bit), para conferir a conta do app."""
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
    return crc


class ReportTest(unittest.TestCase):
    def test_usb_report_only_touches_the_mute_led(self):
        report = hidraw.build_mute_led_report(True, "USB")
        self.assertEqual(len(report), 64)
        self.assertEqual(report[0], 0x02)
        self.assertEqual(report[2], 0x01)   # valid_flag1: controle do LED de microfone
        self.assertEqual(report[9], 1)      # mute_button_led
        # nenhum outro campo (flags 0, vibração, áudio, cor, LEDs de jogador) é ligado
        self.assertEqual({i for i, b in enumerate(report) if b}, {0, 2, 9})

    def test_off_report_clears_the_led_value(self):
        report = hidraw.build_mute_led_report(False, "USB")
        self.assertEqual((report[2], report[9]), (0x01, 0))

    def test_bluetooth_report_layout_and_crc(self):
        report = hidraw.build_mute_led_report(True, "Bluetooth", sequence=5)
        self.assertEqual(len(report), 78)
        self.assertEqual((report[0], report[1], report[2]), (0x31, 0x50, 0x10))
        self.assertEqual(report[3 + 1], 0x01)
        self.assertEqual(report[3 + 8], 1)
        # mesma conta do kernel: crc = ~crc32_le(crc32_le(0xFFFFFFFF, seed), dados)
        crc = crc32_le(0xFFFFFFFF, b"\xa2")
        expected = ~crc32_le(crc, report[:-4]) & 0xFFFFFFFF
        self.assertEqual(int.from_bytes(report[-4:], "little"), expected)

    def test_sequence_wraps_to_four_bits(self):
        self.assertEqual(hidraw.build_mute_led_report(True, "Bluetooth", sequence=17)[1], 0x10)

    def test_set_mute_led_writes_the_report_to_the_device(self):
        with tempfile.NamedTemporaryFile() as node:
            hidraw.set_mute_led(node.name, True, "USB")
            self.assertEqual(Path(node.name).read_bytes()[:10], hidraw.build_mute_led_report(True, "USB")[:10])


class MuteLedServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        device = "0003:054C:0CE6.0001"
        make_led(self.root, "input55:rgb:indicator", device, ("brightness", "multi_intensity"))
        for n in range(1, 6):
            make_led(self.root, f"input55:white:player-{n}", device)
        write_uevent(self.root, device, "aa:bb:cc:dd:ee:01", "0003")
        (self.root / "devices" / device / "hidraw" / "hidraw9").mkdir(parents=True)
        self.settings_path = self.root / "settings.json"
        self.service = LedService(self.settings_path, self.root / "leds", steam_probe=set, bluetooth_probe=lambda k: [])
        patcher = mock.patch.object(hidraw, "set_mute_led")
        self.write = patcher.start()
        self.addCleanup(patcher.stop)

    def test_switch_sends_on_and_off_to_the_controller(self):
        self.service.refresh()
        self.write.reset_mock()
        self.service.set_mute_led(True)
        self.write.assert_called_once_with("/dev/hidraw9", True, "USB")
        self.service.set_mute_led(False)
        self.assertEqual(self.write.call_args.args[1], False)

    def test_other_changes_do_not_touch_the_mute_led_while_it_is_off(self):
        # Apagado não é reescrito: o botão de microfone acende o LED sozinho e não pode ser desfeito.
        self.service.refresh()
        self.service.set_color((255, 0, 0))
        self.service.set_players([True] * 5)
        self.write.assert_not_called()

    def test_lit_led_is_sent_again_on_connect(self):
        self.service.refresh()
        self.service.set_mute_led(True)
        again = LedService(self.settings_path, self.root / "leds", steam_probe=set, bluetooth_probe=lambda k: [])
        self.write.reset_mock()
        again.refresh()
        self.write.assert_called_once_with("/dev/hidraw9", True, "USB")

    def test_state_is_saved_per_controller(self):
        self.service.refresh()
        self.service.set_mute_led(True)
        saved = load_settings(self.settings_path)
        self.assertTrue(saved.controllers["aa:bb:cc:dd:ee:01"].mute_led)

    def test_permission_error_asks_for_access(self):
        self.service.refresh()
        self.write.side_effect = PermissionError("sem acesso")
        self.service.set_mute_led(True)
        self.assertTrue(self.service.needs_permission)

    def test_row_uses_a_compact_switch_smaller_than_the_regular_one(self):
        mute_row, autostart_row = MuteLedRow(self.service), AutostartRow()  # precisam continuar vivos
        compact = mute_row.findChild(CompactToggleSwitch)
        regular = autostart_row.findChild(ToggleSwitch)
        self.assertIsNotNone(compact)
        self.assertLess(compact.width(), regular.width())
        self.assertLess(compact.height(), regular.height())

    def test_switch_row_follows_the_service(self):
        row = MuteLedRow(self.service)
        switch = row.findChild(CompactToggleSwitch)
        self.service.refresh()
        self.assertFalse(switch.isChecked())
        switch.click()
        self.assertTrue(self.service.settings.mute_led)
        self.assertTrue(switch.isChecked())
        self.service.settings.mute_led = False
        self.service.settings_changed.emit()
        self.assertFalse(switch.isChecked())


if __name__ == "__main__":
    unittest.main()
