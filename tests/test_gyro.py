import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from test_sysfs import make_led, write_uevent
from test_testpanel import make_state

from dualsense_led.ds5 import imu
from dualsense_led.service import LedService
from dualsense_led.settings import AppSettings, load_settings, save_settings
from dualsense_led.testpanel.gyro import GyroPanel

# Relatório 0x05 lido de um DualSense real (USB).
REAL_CALIBRATION = bytes.fromhex(
    "0500000000030087228eddad2261dd1023f7dc1c021c02562187e1361e5cde32202be0090000000000"
)


def rest_states(gyro=(0, -3, 1), count=imu.BIAS_SAMPLES, noise=1, start=0):
    """Estados com o controle parado: o giroscópio oscila `noise` em volta de `gyro`."""
    states = []
    for i in range(count):
        jitter = noise if i % 2 else -noise
        states.append(make_state(
            gyro=tuple(v + jitter for v in gyro), accel=(-180, 8130, 1336), sensor_time=start + i + 1,
        ))
    return states


class ImuTest(unittest.TestCase):
    def test_parse_real_calibration(self):
        cal = imu.parse_calibration(REAL_CALIBRATION)
        self.assertEqual(cal.gyro_bias, (0, 0, 3))
        self.assertEqual(cal.gyro_plus, (8839, 8877, 8976))
        self.assertEqual(cal.gyro_minus, (-8818, -8863, -8969))
        self.assertEqual((cal.speed_plus, cal.speed_minus), (540, 540))
        self.assertAlmostEqual(cal.gyro_scale()[0], 1080 / (8839 + 8818))

    def test_invalid_calibration(self):
        self.assertIsNone(imu.parse_calibration(b"\x05\x00"))
        self.assertIsNone(imu.parse_calibration(bytes(41)))
        broken = imu.parse_calibration(b"\x05" + bytes(40))
        self.assertEqual(broken.gyro_scale(), (imu.DEFAULT_GYRO_SCALE,) * 3)

    def test_read_calibration_ignores_io_error(self):
        class Broken:
            def get_feature(self, report_id, size):
                raise OSError

        self.assertIsNone(imu.read_calibration(Broken()))

    def test_rest_reading_stable(self):
        reading = imu.measure_rest(rest_states())
        self.assertTrue(reading.stable)
        self.assertEqual(reading.offset, (0.0, -3.0, 1.0))
        self.assertAlmostEqual(reading.gyro_spread[0], 1.0)

    def test_rest_reading_rejects_motion(self):
        self.assertFalse(imu.measure_rest(rest_states(noise=50)).stable)
        self.assertFalse(imu.measure_rest(rest_states(gyro=(0, 500, 0))).stable)
        self.assertFalse(imu.measure_rest(rest_states(count=3)).stable)
        self.assertIsNone(imu.measure_rest([]))

    def test_apply_offset(self):
        self.assertEqual(imu.apply_offset((1, -3, 2), (1.0, -3.0, 0.5)), (0.0, 0.0, 1.5))
        self.assertEqual(imu.apply_offset((1, 2, 3), None), (1.0, 2.0, 3.0))


class SettingsTest(unittest.TestCase):
    def test_offsets_round_trip_and_bad_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            save_settings(path, AppSettings(gyro_offsets={"aa": (0.5, -2.6, 1.0)}))
            self.assertEqual(load_settings(path).gyro_offsets, {"aa": (0.5, -2.6, 1.0)})
            data = json.loads(path.read_text())
            data["gyro_offsets"]["bb"] = [1, 2]
            data["gyro_offsets"]["cc"] = ["x", 0, 0]
            path.write_text(json.dumps(data))
            self.assertEqual(load_settings(path).gyro_offsets, {"aa": (0.5, -2.6, 1.0)})

    def test_old_file_without_offsets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            path.write_text(json.dumps({"color": [1, 2, 3], "brightness": 9, "players": [False] * 5}))
            self.assertEqual(load_settings(path).gyro_offsets, {})


class FakeDevice:
    def __init__(self, path="/dev/hidraw7", connection="USB"):
        self.path = path
        self.connection = connection

    def get_feature(self, report_id, size):
        return REAL_CALIBRATION


class PanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        hid = "0003:054C:0CE6.0007"
        make_led(self.root, "input7:rgb:indicator", hid, ("brightness", "multi_intensity"))
        write_uevent(self.root, hid, "AA:BB:CC:DD:EE:FF", "0003")
        (self.root / "devices" / hid / "hidraw" / "hidraw7").mkdir(parents=True)
        self.service = LedService(self.root / "s.json", self.root / "leds", steam_probe=set, bluetooth_probe=lambda k: [])
        self.service.refresh()
        self.panel = GyroPanel(self.service)
        self.panel.set_device(FakeDevice())

    def feed(self, states):
        for state in states:
            self.panel.on_state(state)

    def test_calibration_saves_and_corrects(self):
        self.feed(rest_states(count=60))
        self.panel.start()
        self.assertTrue(self.panel.collecting)
        self.feed(rest_states(start=1000))
        self.assertFalse(self.panel.collecting)
        self.assertEqual(self.service.gyro_offset("aa:bb:cc:dd:ee:ff"), (0.0, -3.0, 1.0))
        self.assertEqual(self.panel.correct((0, -3, 1)), (0.0, 0.0, 0.0))
        # Persiste entre execuções.
        reloaded = LedService(self.root / "s.json", self.root / "leds", steam_probe=set, bluetooth_probe=lambda k: [])
        self.assertEqual(reloaded.gyro_offset("aa:bb:cc:dd:ee:ff"), (0.0, -3.0, 1.0))

    def test_refuses_to_start_while_moving(self):
        self.feed(rest_states(count=60, noise=50))
        self.panel.start()
        self.assertFalse(self.panel.collecting)

    def test_motion_during_collection_saves_nothing(self):
        self.feed(rest_states(count=60))
        self.panel.start()
        self.feed(rest_states(noise=50, start=1000))
        self.assertFalse(self.panel.collecting)
        self.assertIsNone(self.service.gyro_offset("aa:bb:cc:dd:ee:ff"))

    def test_repeated_report_counts_once(self):
        state = rest_states(count=1)[0]
        self.feed([state] * 5)
        self.assertEqual(len(self.panel._recent), 1)

    def test_clear_and_release(self):
        self.service.set_gyro_offset("aa:bb:cc:dd:ee:ff", (1.0, 2.0, 3.0))
        self.panel.clear()
        self.assertIsNone(self.service.gyro_offset("aa:bb:cc:dd:ee:ff"))
        self.feed(rest_states(count=60))
        self.panel.start()
        self.panel.set_device(None)
        self.assertFalse(self.panel.collecting)
        self.assertEqual(self.panel.correct((1, 2, 3)), (1.0, 2.0, 3.0))


if __name__ == "__main__":
    unittest.main()
