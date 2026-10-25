import math
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dualsense_ultimate_control.ds5.reports import InputState, Touch
from dualsense_ultimate_control.testpanel.model import ImuHistory, peak_level, RangeTracker, normalize_stick, stick_point
from dualsense_ultimate_control.testpanel.widgets import ControllerView, ImuPlot, StickView, TouchpadView


def make_state(**overrides) -> InputState:
    fields = dict(
        connection="USB", sequence=0, lx=128, ly=128, rx=128, ry=128, l2=0, r2=0, dpad=None,
        buttons=frozenset(), gyro=(0, 0, 0), accel=(0, 0, 0), sensor_time=0,
        touches=(None, None), battery_percent=50, battery_status="discharging",
    )
    fields.update(overrides)
    return InputState(**fields)


class ModelTest(unittest.TestCase):
    def test_normalize_stick_ends_and_center(self):
        self.assertEqual(normalize_stick(128), 0)
        self.assertEqual(normalize_stick(255), 1)
        self.assertAlmostEqual(normalize_stick(0), -1)

    def test_stick_point_y_up(self):
        self.assertEqual(stick_point(128, 0)[1], 1)

    def test_range_tracker_keeps_max_per_direction(self):
        tracker = RangeTracker(bins=4)
        tracker.add(0.5, 0.0)
        tracker.add(0.9, 0.0)
        tracker.add(0.01, 0.0)  # perto do centro é ignorado
        self.assertEqual(tracker.radii, [0.9, 0.0, 0.0, 0.0])
        tracker.reset()
        self.assertEqual(tracker.radii, [0.0] * 4)

    def test_circularity_error(self):
        tracker = RangeTracker()
        self.assertIsNone(tracker.circularity_error())
        for i in range(10):  # 10 direções ainda não bastam
            angle = (i + 0.5) / len(tracker.radii) * math.tau
            tracker.add(math.cos(angle), math.sin(angle))
        self.assertIsNone(tracker.circularity_error())
        for i in range(len(tracker.radii)):
            angle = (i + 0.5) / len(tracker.radii) * math.tau
            tracker.add(math.cos(angle), math.sin(angle))
        self.assertAlmostEqual(tracker.circularity_error(), 0.0, places=6)
        # metade das direções com raio 0,9 e metade com 1,1 → RMS de 10 %
        tracker.radii = [0.9, 1.1] * (len(tracker.radii) // 2)
        self.assertAlmostEqual(tracker.circularity_error(), 10.0)
        # direções quase sem movimento (≤ 0,2) ficam fora da média
        tracker.radii[0] = 0.1
        self.assertAlmostEqual(tracker.circularity_error(), 10.0, delta=0.15)

    def test_imu_history_is_bounded(self):
        history = ImuHistory(size=3)
        for i in range(5):
            history.add((i, -i, 0))
        self.assertEqual(history.axis(0), [2, 3, 4])


class PeakLevelTest(unittest.TestCase):
    def test_int16_peak(self):
        import struct

        self.assertAlmostEqual(peak_level(struct.pack("<hhh", 0, -16384, 100)), 0.5)
        self.assertEqual(peak_level(b""), 0.0)
        self.assertEqual(peak_level(b"\x01"), 0.0)

    def test_float_peak_is_clamped(self):
        import struct

        self.assertEqual(peak_level(struct.pack("<ff", 0.25, -2.0), float_samples=True), 1.0)


class WidgetsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_widgets_paint_without_errors(self):
        state = make_state(buttons=frozenset({"cross", "l1", "l3"}), dpad="up_right", l2=200,
                           touches=(Touch(1, 100, 100), None))
        view = ControllerView()
        view.set_state(state)
        stick = StickView()
        stick.set_position(255, 128)
        touchpad = TouchpadView()
        touchpad.set_touches(state.touches)
        plot = ImuPlot()
        for i in range(5):
            plot.add((i * 1000, 0, -i * 1000))
        for widget in (view, stick, touchpad, plot):
            widget.resize(300, 200)
            widget.grab()
        self.assertEqual(stick.tracker.radii.index(max(stick.tracker.radii)), 0)


if __name__ == "__main__":
    unittest.main()
