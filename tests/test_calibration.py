import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from test_sysfs import make_led, write_uevent  # noqa: F401
from test_testpanel import make_state

from dualsense_ultimate_control.ds5 import calibration as cal
from dualsense_ultimate_control.service import LedService
from dualsense_ultimate_control.testpanel.calibration import CalibrationPanel


class FakeController:
    """Simula o NVS e os comandos 0x80/0x82; `fail_on` faz o comando de calibração indicado errar.

    `flashed` conta as gravações (destravar seguido de travar); `rebooted` diz se recebeu o reinício.
    """

    def __init__(self, fail_on=None, connection="USB", path="/dev/hidraw9"):
        self.connection = connection
        self.path = path
        self.locked = True
        self.flashed = 0
        self.rebooted = False
        self.calls = []
        self.fail_on = fail_on
        self._reply = b""

    def set_feature(self, data):
        data = bytes(data)
        self.calls.append(data)
        report, args = data[0], tuple(data[1:])
        if report == cal.NVS_REQUEST:
            if args == cal.NVS_UNLOCK:
                self.locked = False
            elif args == cal.NVS_LOCK:
                self.flashed += not self.locked
                self.locked = True
            elif args == cal.REBOOT:
                self.rebooted = True
            elif args == cal.NVS_STATUS:
                value = cal.NVS_LOCKED if self.locked else cal.NVS_UNLOCKED
                self._reply = bytes([cal.NVS_RESPONSE]) + value.to_bytes(4, "big")
        elif report == cal.CAL_REQUEST:
            value = 0 if args == self.fail_on else cal._EXPECT[args]
            self._reply = value.to_bytes(4, "big") + b"\x00"

    def get_feature(self, report_id, size):
        return self._reply

    def read_state(self):
        return None

    def cal_commands(self):
        return [tuple(c[1:]) for c in self.calls if c[0] == cal.CAL_REQUEST]


class ProtocolTest(unittest.TestCase):
    def test_center_runs_begin_samples_end_without_touching_nvs(self):
        device = FakeController()
        cal.calibrate_center(device, sleep=lambda s: None)
        self.assertEqual(device.cal_commands(), [cal.CENTER_BEGIN] + [cal.CENTER_SAMPLE] * cal.CENTER_SAMPLES + [cal.CENTER_END])
        self.assertFalse(any(c[0] == cal.NVS_REQUEST for c in device.calls))

    def test_failure_in_sample_skips_end(self):
        device = FakeController(fail_on=cal.CENTER_SAMPLE)
        with self.assertRaises(cal.CalibrationError):
            cal.calibrate_center(device, sleep=lambda s: None)
        self.assertNotIn(cal.CENTER_END, device.cal_commands())

    def test_range_begin_and_end(self):
        device = FakeController()
        cal.range_begin(device)
        cal.range_end(device)
        self.assertEqual(device.cal_commands(), [cal.RANGE_BEGIN, cal.RANGE_END])
        self.assertTrue(device.locked)

    def test_save_unlocks_then_locks(self):
        device = FakeController()
        self.assertEqual(cal.save(device), cal.NVS_LOCKED)
        self.assertEqual(device.flashed, 1)
        self.assertTrue(device.locked)

    def test_failed_unlock_still_sends_lock(self):
        device = FakeController()
        original = device.set_feature

        def refuse_unlock(data):
            original(data)
            if tuple(data[1:]) == cal.NVS_UNLOCK:
                device.locked = True  # o controle ignorou o destravamento

        device.set_feature = refuse_unlock
        with self.assertRaises(cal.CalibrationError):
            cal.save(device)
        self.assertIn(bytes([cal.NVS_REQUEST, *cal.NVS_LOCK]), device.calls)

    def test_save_fails_if_still_unlocked(self):
        device = FakeController()
        original = device.set_feature

        def ignore_lock(data):
            if tuple(data[1:]) != cal.NVS_LOCK:
                original(data)

        device.set_feature = ignore_lock
        with self.assertRaises(cal.CalibrationError) as caught:
            cal.save(device)
        self.assertEqual(caught.exception.step, "lock")

    def test_reboot_ignores_disconnect(self):
        device = FakeController()
        device.set_feature = unittest.mock.Mock(side_effect=OSError(5, "EIO"))
        cal.reboot(device)  # não levanta

    def test_reply_word_includes_report_id(self):
        device = FakeController()
        device.get_feature = lambda report_id, size: b"\x83\x01\x01\x01\x00"
        cal._command(device, cal.CENTER_BEGIN, "x")
        device.get_feature = lambda report_id, size: b"\x83\x83\x01\x01\x01"
        with self.assertRaises(cal.CalibrationError):
            cal._command(device, cal.CENTER_BEGIN, "x")


class MathTest(unittest.TestCase):
    def test_average_center_and_drift(self):
        reading = cal.average_center([make_state(lx=130, ly=128), make_state(lx=134, ly=128, rx=120)])
        self.assertEqual((reading.lx, reading.rx), (132, 124))
        self.assertEqual(reading.drift, 4)
        self.assertTrue(reading.needs_calibration)
        self.assertIsNone(cal.average_center([]))

    def test_range_complete(self):
        self.assertTrue(cal.range_complete((0, 255, 3, 250)))
        self.assertFalse(cal.range_complete((0, 200, 0, 255)))
        self.assertFalse(cal.range_complete(cal.range_extremes([])))

    def test_history_keeps_latest_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.json"
            for i in range(cal.MAX_HISTORY + 5):
                cal.append_history(path, cal.HistoryEntry(str(i), "c", "center", True, {}))
            entries = cal.load_history(path)
            self.assertEqual(len(entries), cal.MAX_HISTORY)
            self.assertEqual(entries[-1]["time"], str(cal.MAX_HISTORY + 4))

    def test_history_bad_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.json"
            path.write_text("{")
            self.assertEqual(cal.load_history(path), [])


class PanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        service = LedService(root / "s.json", root / "leds", bluetooth_probe=lambda known: [])
        self.history = root / "h.json"
        self.panel = CalibrationPanel(service, self.history)
        self.answer = True
        self.panel._confirm = lambda key: self.answer
        self.device = FakeController()

    def test_buttons_disabled_without_usb(self):
        self.assertFalse(self.panel._center_button.isEnabled())
        self.panel.set_device(FakeController(connection="Bluetooth"))
        self.assertFalse(self.panel._center_button.isEnabled())
        self.panel.set_device(self.device)
        self.assertTrue(self.panel._center_button.isEnabled())

    def test_declined_confirmation_writes_nothing(self):
        self.panel.set_device(self.device)
        self.answer = False
        self.panel.run_center()
        self.assertEqual(self.device.calls, [])

    def _no_delay(self):
        patcher = unittest.mock.patch.object(cal, "SAMPLE_DELAY_S", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_center_applies_then_save_writes(self):
        self._no_delay()
        self.panel.set_device(self.device)
        self.assertFalse(self.panel._save_button.isEnabled())
        self.panel.run_center()
        self.assertEqual(self.device.flashed, 0)
        self.assertTrue(self.panel._save_button.isEnabled())
        self.panel.run_save()
        self.assertEqual(self.device.flashed, 1)
        self.assertFalse(self.panel._save_button.isEnabled())
        entries = cal.load_history(self.history)
        self.assertEqual([(e["action"], e["ok"]) for e in entries], [("center", True), ("save", True)])

    def test_center_failure_is_recorded_and_not_saved(self):
        self.device.fail_on = cal.CENTER_BEGIN
        self.panel.set_device(self.device)
        self.panel.run_center()
        self.assertFalse(cal.load_history(self.history)[0]["ok"])
        self.assertFalse(self.panel._save_button.isEnabled())
        self.assertEqual(self.device.flashed, 0)

    def test_pending_survives_reopening_same_device(self):
        self._no_delay()
        self.panel.set_device(self.device)
        self.panel.run_center()
        self.panel.set_device(None)
        self.panel.set_device(self.device)
        self.assertTrue(self.panel._save_button.isEnabled())

    def test_range_needs_edges_and_closing_device_discards(self):
        self.panel.set_device(self.device)
        self.panel.start_range()
        self.assertTrue(self.device.locked)
        self.assertFalse(self.panel._range_finish.isEnabled())
        for x, y in ((0, 0), (255, 255)):
            self.panel.on_state(make_state(lx=x, ly=y, rx=x, ry=y))
        self.assertTrue(self.panel._range_finish.isEnabled())
        self.panel.set_device(None)  # fechar a janela no meio
        self.assertEqual(self.device.cal_commands(), [cal.RANGE_BEGIN, cal.RANGE_END])
        self.assertTrue(self.device.rebooted)
        self.assertEqual(self.device.flashed, 0)

    def test_range_finish_applies(self):
        self.panel.set_device(self.device)
        self.panel.start_range()
        for x, y in ((0, 0), (255, 255)):
            self.panel.on_state(make_state(lx=x, ly=y, rx=x, ry=y))
        self.panel.finish_range()
        self.assertEqual(self.device.flashed, 0)
        self.assertTrue(self.panel._save_button.isEnabled())
        self.assertEqual(cal.load_history(self.history)[0]["action"], "range")

    def test_failure_in_the_middle_reboots_to_leave_calibration_mode(self):
        self._no_delay()
        self.device.fail_on = cal.CENTER_SAMPLE
        self.panel.set_device(self.device)
        self.panel.run_center()
        self.assertTrue(self.device.rebooted)
        self.assertFalse(self.panel._save_button.isEnabled())

    def test_failed_range_end_reboots(self):
        self.panel.set_device(self.device)
        self.panel.start_range()
        for x, y in ((0, 0), (255, 255)):
            self.panel.on_state(make_state(lx=x, ly=y, rx=x, ry=y))
        self.device.fail_on = cal.RANGE_END
        self.panel.finish_range()
        self.assertTrue(self.device.rebooted)
        self.assertFalse(self.panel._save_button.isEnabled())
        self.assertFalse(cal.load_history(self.history)[0]["ok"])

    def test_reboot_discards_pending(self):
        self._no_delay()
        self.panel.set_device(self.device)
        self.panel.run_center()
        self.panel.run_reboot()
        self.assertTrue(self.device.rebooted)
        self.assertFalse(self.panel._save_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
