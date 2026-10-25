import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from test_sysfs import make_led, write_uevent  # noqa: F401
from test_testpanel import make_state

from dualsense_led.ds5 import audio, reports, triggers
from dualsense_led.ds5.reports import Touch
from dualsense_led.service import LedService
from dualsense_led.testpanel import sequence
from dualsense_led.testpanel.quicktest import QuickTestDialog


class FakeDevice:
    def __init__(self, connection="USB"):
        self.connection = connection
        self.path = "/dev/hidraw9"
        self.outputs = []
        self.features = []

    def send_output(self, **fields):
        self.outputs.append(fields)

    def set_feature(self, data):
        self.features.append(bytes(data))


class SequenceTest(unittest.TestCase):
    def test_mark_moves_to_next_untested_and_wraps(self):
        seq = sequence.Sequence(("a", "b", "c"))
        seq.start()
        seq.open("b")
        seq.mark(True)
        self.assertEqual(seq.current, "c")
        seq.mark(False)
        self.assertEqual(seq.current, "a")  # deu a volta até o que faltava
        seq.mark(True)
        self.assertIsNone(seq.current)
        self.assertTrue(seq.finished)
        self.assertEqual(seq.summary(), (2, 1, 0))

    def test_skip_and_previous(self):
        seq = sequence.Sequence(("a", "b", "c"))
        seq.start()
        seq.skip()
        self.assertEqual(seq.current, "b")
        seq.previous()
        self.assertEqual(seq.current, "a")
        self.assertEqual(seq.summary(), (0, 0, 3))

    def test_button_edges_and_long_circle(self):
        edges = sequence.ButtonEdges()
        pressed, _ = edges.update(make_state(buttons=frozenset({"square"})), 0.0)
        self.assertEqual(pressed, {"square"})
        pressed, _ = edges.update(make_state(buttons=frozenset({"square"})), 0.1)
        self.assertEqual(pressed, set())  # segurar não repete
        edges.update(make_state(buttons=frozenset({"circle"})), 1.0)
        _, long_press = edges.update(make_state(buttons=frozenset({"circle"})), 2.1)
        self.assertTrue(long_press)
        _, long_press = edges.update(make_state(buttons=frozenset({"circle"})), 3.5)
        self.assertFalse(long_press)  # um toque longo dispara uma vez só


class ChecksTest(unittest.TestCase):
    def test_buttons_need_press_after_opening(self):
        check = sequence.ButtonsCheck()
        check.update(make_state(buttons=frozenset({"square"})))  # já apertado ao abrir
        self.assertFalse(check.checks["square"])
        check.update(make_state(dpad="up_right"))
        self.assertTrue(check.checks["up"] and check.checks["right"])
        for name in sequence.ButtonsCheck.names:
            check.update(make_state())
            check.update(make_state(buttons=frozenset({name}), dpad=name if name in ("up", "down", "left", "right") else None))
        self.assertTrue(check.done)

    def test_sticks_range_and_center(self):
        check = sequence.SticksCheck()
        for x, y in ((0, 0), (255, 255)):
            check.update(make_state(lx=x, ly=y, rx=x, ry=y))
        self.assertTrue(check.checks["left_range"] and check.checks["right_range"])
        self.assertFalse(check.checks["center"])
        for _ in range(check.RECENT):
            check.update(make_state(lx=129))
        self.assertTrue(check.done)

    def test_sticks_center_fails_with_drift(self):
        check = sequence.SticksCheck()
        for _ in range(check.RECENT * 2):
            check.update(make_state(lx=132))
        self.assertFalse(check.checks["center"])
        self.assertEqual(check.drift, 4)

    def test_trackpad(self):
        check = sequence.TrackpadCheck()
        for x in range(0, 800, 100):
            check.update(make_state(touches=(Touch(1, x, 500), None)))
        check.update(make_state(touches=(Touch(1, 0, 0), Touch(2, 10, 10))))
        check.update(make_state(buttons=frozenset({"touchpad"})))
        self.assertTrue(check.done)

    def test_imu_needs_both_directions(self):
        check = sequence.ImuCheck()
        check.update(make_state(gyro=(5000, 0, 0)))
        self.assertFalse(check.checks["pitch"])
        check.update(make_state(gyro=(-5000, 0, 0), accel=(0, 8000, 0)))
        self.assertTrue(check.checks["pitch"])
        self.assertTrue(check.checks["accel_y"])
        self.assertFalse(check.done)


class AudioTest(unittest.TestCase):
    def test_tone_sequence(self):
        device = FakeDevice()
        audio.play_tone(device, "speaker")
        self.assertEqual(device.outputs, [{"speaker_volume": 85, "headphone_volume": 55, "audio_control": 0}])
        self.assertEqual(device.features, [bytes([0x80, 6, 4, 0, 0, 8]), bytes([0x80, 6, 2, 1, 1, 0])])
        audio.stop_tone(device)
        self.assertEqual(device.features[-1], bytes([0x80, 6, 2, 0, 1, 0]))

    def test_output_report_audio_fields(self):
        report = reports.build_output_report("USB", speaker_volume=85, headphone_volume=55, audio_control=0)
        self.assertEqual(report[1], 0x10 | 0x20 | 0x80)
        self.assertEqual((report[5], report[6], report[8]), (55, 85, 0))

    def test_headphone_bit(self):
        data = bytearray(64)
        data[0] = 0x01
        data[1 + reports.IN_STATUS1] = 0x09
        self.assertTrue(reports.parse_input_report(bytes(data)).headphones)
        data[1 + reports.IN_STATUS1] = 0x08
        self.assertFalse(reports.parse_input_report(bytes(data)).headphones)


class DialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        service = LedService(root / "s.json", root / "leds", bluetooth_probe=lambda known: [])
        self.dialog = QuickTestDialog(service)
        self.device = FakeDevice()
        self.dialog.show()
        self.dialog.set_device(self.device)
        self.addCleanup(self.dialog.close)

    def press(self, *buttons):
        self.dialog.on_state(make_state())
        self.dialog.on_state(make_state(buttons=frozenset(buttons)))
        self.dialog.on_state(make_state())

    def test_square_starts_and_marks(self):
        self.press("square")
        self.assertEqual(self.dialog._sequence.current, "usb")
        self.assertTrue(self.dialog._rows["usb"].body.isVisible())
        self.press("square")
        self.assertTrue(self.dialog._sequence.results["usb"])
        self.assertEqual(self.dialog._sequence.current, "buttons")

    def test_buttons_item_captures_navigation(self):
        self.dialog._go(lambda: self.dialog._sequence.open("buttons"))
        self.press("cross")
        self.assertIsNone(self.dialog._sequence.results["buttons"])
        self.assertTrue(self.dialog._checks["buttons"].checks["cross"])

    def test_adaptive_turns_on_and_off(self):
        self.dialog._go(lambda: self.dialog._sequence.open("adaptive"))
        effect = triggers.resistance(0, triggers.MAX_STRENGTH)
        self.assertEqual(self.device.outputs[-1], {"left_trigger": effect, "right_trigger": effect})
        self.press("cross")
        self.assertFalse(self.dialog._sequence.results["adaptive"])
        self.assertEqual(self.device.outputs[-2], {"left_trigger": triggers.OFF, "right_trigger": triggers.OFF})

    def test_speaker_plays_and_stops_when_leaving(self):
        self.dialog._go(lambda: self.dialog._sequence.open("speaker"))
        self.assertIn(bytes([0x80, 6, 2, 1, 1, 0]), self.device.features)
        self.dialog._go(self.dialog._sequence.skip)
        self.assertEqual(self.device.features[-1], bytes([0x80, 6, 2, 0, 1, 0]))

    def test_speaker_not_played_over_bluetooth(self):
        self.dialog.set_device(FakeDevice("Bluetooth"))
        self.dialog._go(lambda: self.dialog._sequence.open("speaker"))
        self.assertFalse(self.dialog._rows["speaker"].action_button.isEnabled())

    def test_close_stops_effects(self):
        self.dialog._go(lambda: self.dialog._sequence.open("haptic"))
        self.dialog.close()
        self.assertEqual(self.device.outputs[-1], {"rumble": (0, 0)})
        self.assertIsNone(self.dialog._sequence.current)

    def test_disconnect_counted_for_usb_item(self):
        self.dialog._go(lambda: self.dialog._sequence.open("usb"))
        self.dialog.note_disconnect()
        self.dialog.set_device(None)
        self.dialog.set_device(self.device)
        self.assertEqual(self.dialog._disconnects, 1)


if __name__ == "__main__":
    unittest.main()
