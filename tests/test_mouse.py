import tempfile
import unittest
from pathlib import Path

from evdev import ecodes

from dualsense_led.ds5.imu import DEFAULT_GYRO_SCALE
from dualsense_led.ds5.reports import InputState as Report, Touch
from dualsense_led.emulator import core
from dualsense_led.emulator.mapping import Mapper, Profile
from dualsense_led.emulator.mouse import SCROLL_STEP, SENSOR_TICKS_PER_SECOND, TOUCH_PIXELS, MouseTracker, sibling_nodes

TICKS_10MS = SENSOR_TICKS_PER_SECOND // 100


def report(time=0, gyro=(0, 0, 0), touches=(None, None), buttons=()):
    return Report(
        connection="USB", sequence=0, lx=128, ly=128, rx=128, ry=128, l2=0, r2=0, dpad=None,
        buttons=frozenset(buttons), gyro=gyro, accel=(0, 0, 0), sensor_time=time,
        touches=tuple(touches), battery_percent=100, battery_status="full",
    )  # fmt: skip


def finger(x, y, id=1):
    return Touch(id, x, y)


class GyroTests(unittest.TestCase):
    def test_off_by_default(self):
        tracker = MouseTracker(Profile())
        tracker.update(report(0), set())
        self.assertEqual(tracker.update(report(TICKS_10MS, gyro=(1000, 1000, 0)), set()).dx, 0)

    def test_always_turns_yaw_and_pitch_into_motion(self):
        tracker = MouseTracker(Profile(gyro="always", gyro_speed=10))
        tracker.update(report(0), set())
        # yaw de 100 °/s por 10 ms = 1° -> 10 pixels para a esquerda; pitch igual -> 10 para cima
        raw = round(100 / DEFAULT_GYRO_SCALE)
        out = tracker.update(report(TICKS_10MS, gyro=(raw, raw, 0)), set())
        self.assertEqual((out.dx, out.dy), (-10, -10))

    def test_invert_y(self):
        tracker = MouseTracker(Profile(gyro="always", gyro_speed=10, gyro_invert_y=True))
        tracker.update(report(0), set())
        raw = round(100 / DEFAULT_GYRO_SCALE)
        self.assertEqual(tracker.update(report(TICKS_10MS, gyro=(raw, 0, 0)), set()).dy, 10)

    def test_offset_is_subtracted(self):
        tracker = MouseTracker(Profile(gyro="always", gyro_speed=100), gyro_offset=(0, 50, 0))
        tracker.update(report(0, gyro=(0, 50, 0)), set())
        for step in range(1, 20):
            self.assertEqual(tracker.update(report(step * TICKS_10MS, gyro=(0, 50, 0)), set()).dx, 0)

    def test_fractions_accumulate(self):
        tracker = MouseTracker(Profile(gyro="always", gyro_speed=1))
        tracker.update(report(0), set())
        raw = round(30 / DEFAULT_GYRO_SCALE)  # 30 °/s × 10 ms × 1 px/° = 0,3 px por relatório
        total = sum(tracker.update(report(step * TICKS_10MS, gyro=(0, raw, 0)), set()).dx for step in range(1, 11))
        self.assertEqual(total, -3)

    def test_button_activator(self):
        tracker = MouseTracker(Profile(gyro="button", gyro_button="l2", gyro_speed=10))
        raw = round(100 / DEFAULT_GYRO_SCALE)
        tracker.update(report(0), set())
        self.assertEqual(tracker.update(report(TICKS_10MS, gyro=(0, raw, 0)), set()).dx, 0)
        self.assertEqual(tracker.update(report(2 * TICKS_10MS, gyro=(0, raw, 0)), {"l2"}).dx, -10)

    def test_touch_activator(self):
        tracker = MouseTracker(Profile(gyro="touch", gyro_speed=10))
        raw = round(100 / DEFAULT_GYRO_SCALE)
        tracker.update(report(0), set())
        self.assertEqual(tracker.update(report(TICKS_10MS, gyro=(0, raw, 0)), set()).dx, 0)
        out = tracker.update(report(2 * TICKS_10MS, gyro=(0, raw, 0), touches=(finger(100, 100), None)), set())
        self.assertEqual(out.dx, -10)

    def test_repeated_time_and_long_gap(self):
        tracker = MouseTracker(Profile(gyro="always", gyro_speed=10))
        raw = round(100 / DEFAULT_GYRO_SCALE)
        tracker.update(report(5), set())
        self.assertEqual(tracker.update(report(5, gyro=(0, raw, 0)), set()).dx, 0)  # relatório repetido
        # 1 s sem relatórios conta como no máximo 50 ms
        self.assertEqual(tracker.update(report(5 + SENSOR_TICKS_PER_SECOND, gyro=(0, raw, 0)), set()).dx, -50)

    def test_sensor_time_wraps(self):
        tracker = MouseTracker(Profile(gyro="always", gyro_speed=10))
        raw = round(100 / DEFAULT_GYRO_SCALE)
        tracker.update(report((1 << 32) - TICKS_10MS // 2), set())
        self.assertEqual(tracker.update(report(TICKS_10MS // 2, gyro=(0, raw, 0)), set()).dx, -10)


class TouchpadTests(unittest.TestCase):
    def test_system_mode_ignores_touchpad(self):
        tracker = MouseTracker(Profile())
        tracker.update(report(touches=(finger(0, 0), None)), set())
        out = tracker.update(report(touches=(finger(500, 0), None), buttons={"touchpad"}), set())
        self.assertEqual((out.dx, out.buttons), (0, frozenset()))

    def test_one_finger_moves(self):
        tracker = MouseTracker(Profile(touchpad="mouse"))
        self.assertEqual(tracker.update(report(touches=(finger(100, 100), None)), set()).dx, 0)  # pousou
        out = tracker.update(report(touches=(finger(200, 150), None)), set())
        self.assertEqual((out.dx, out.dy), (int(100 * TOUCH_PIXELS), int(50 * TOUCH_PIXELS)))

    def test_new_finger_does_not_jump(self):
        tracker = MouseTracker(Profile(touchpad="mouse"))
        tracker.update(report(touches=(finger(100, 100, id=1), None)), set())
        self.assertEqual(tracker.update(report(touches=(finger(1800, 900, id=2), None)), set()).dx, 0)

    def test_two_fingers_scroll(self):
        tracker = MouseTracker(Profile(touchpad="mouse"))
        tracker.update(report(touches=(finger(500, 600, 1), finger(700, 600, 2))), set())
        out = tracker.update(report(touches=(finger(500, 600 - SCROLL_STEP, 1), finger(700, 600 - SCROLL_STEP, 2))), set())
        self.assertEqual((out.wheel, out.dx, out.dy), (1, 0, 0))  # subir rola para cima, sem mover o ponteiro

    def test_click_by_half_and_kept_while_held(self):
        tracker = MouseTracker(Profile(touchpad="mouse"))
        out = tracker.update(report(touches=(finger(1500, 500), None), buttons={"touchpad"}), set())
        self.assertEqual(out.buttons, {"right"})
        out = tracker.update(report(touches=(finger(200, 500), None), buttons={"touchpad"}), set())
        self.assertEqual(out.buttons, {"right"})  # escorregar para a esquerda não troca o botão
        self.assertEqual(tracker.update(report(touches=(finger(200, 500), None)), set()).buttons, frozenset())
        out = tracker.update(report(touches=(finger(200, 500), None), buttons={"touchpad"}), set())
        self.assertEqual(out.buttons, {"left"})

    def test_touch_gyro_mode_does_not_move_pointer(self):
        tracker = MouseTracker(Profile(touchpad="mouse", gyro="touch"))
        tracker.update(report(touches=(finger(100, 100), None)), set())
        self.assertEqual(tracker.update(report(touches=(finger(400, 100), None)), set()).dx, 0)


class ProfileTests(unittest.TestCase):
    def test_round_trip_and_validation(self):
        profile = Profile(touchpad="mouse", touchpad_speed=2.0, gyro="button", gyro_button="r1", gyro_speed=30, gyro_invert_y=True)
        self.assertEqual(Profile.from_dict(profile.to_dict()), profile)
        bad = Profile.from_dict({"touchpad": "x", "gyro": "y", "gyro_button": "nope", "gyro_speed": 1e9, "touchpad_speed": "a"})
        self.assertEqual((bad.touchpad, bad.gyro, bad.gyro_button, bad.gyro_speed, bad.touchpad_speed), ("system", "off", "l2", 100.0, 1.0))
        self.assertFalse(Profile().uses_mouse)
        self.assertTrue(Profile(gyro="always").uses_mouse)

    def test_sources_include_triggers(self):
        mapper = Mapper(Profile(trigger_threshold=0.5))
        state = core.InputState(pressed={"south"})
        state.axes["l2"] = 0.6
        self.assertEqual(mapper.sources(state), {"south", "l2"})


class SiblingTests(unittest.TestCase):
    def test_finds_hidraw_and_touchpad(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            hid = root / "devices" / "hid0"
            (hid / "hidraw" / "hidraw9").mkdir(parents=True)
            for number, name in ((15, "DualSense Wireless Controller"), (17, "DualSense Wireless Controller Touchpad")):
                node = hid / "input" / f"input{number}"
                (node / f"event{number}").mkdir(parents=True)
                (node / "name").write_text(name + "\n")
            event = root / "class" / "input" / "event15"
            event.mkdir(parents=True)
            (event / "device").symlink_to(hid / "input" / "input15")
            (hid / "input" / "input15" / "device").symlink_to(hid)
            self.assertEqual(sibling_nodes("/dev/input/event15", root), ("/dev/hidraw9", "/dev/input/event17"))
            self.assertEqual(sibling_nodes("/dev/input/event99", root), (None, None))


class FakeUInput:
    def __init__(self):
        self.events, self.syncs = [], 0

    def write(self, *event):
        self.events.append(event)

    def syn(self):
        self.syncs += 1


class FakePhysical:
    def active_keys(self):
        return []

    def capabilities(self):
        return {}


class BridgeMouseTests(unittest.TestCase):
    def make(self, profile):
        bridge = core.Bridge(FakePhysical(), FakeUInput(), Mapper(profile))
        bridge._mouse = FakeUInput()
        bridge._tracker = MouseTracker(profile)  # sem hidraw: os relatórios entram por feed_report
        return bridge

    def test_reports_reach_virtual_mouse(self):
        bridge = self.make(Profile(touchpad="mouse"))
        bridge.feed_report(report(touches=(finger(100, 100), None)))
        self.assertEqual(bridge._mouse.events, [])  # nada mudou: nada escrito
        bridge.feed_report(report(touches=(finger(200, 100), None), buttons={"touchpad"}))
        self.assertEqual(
            bridge._mouse.events,
            [(ecodes.EV_REL, ecodes.REL_X, int(100 * TOUCH_PIXELS)), (ecodes.EV_KEY, ecodes.BTN_LEFT, 1)],
        )
        bridge._mouse.events.clear()
        bridge.feed_report(report(touches=(finger(200, 100), None)))
        self.assertEqual(bridge._mouse.events, [(ecodes.EV_KEY, ecodes.BTN_LEFT, 0)])

    def test_gyro_button_uses_mapper_sources(self):
        bridge = self.make(Profile(gyro="button", gyro_button="r2", gyro_speed=10))
        raw = round(100 / DEFAULT_GYRO_SCALE)
        bridge.feed_report(report(0))
        bridge._state.axes["r2"] = 1.0
        bridge.feed_report(report(TICKS_10MS, gyro=(0, raw, 0)))
        self.assertEqual(bridge._mouse.events, [(ecodes.EV_REL, ecodes.REL_X, -10)])

    def test_profile_without_mouse_releases_click(self):
        bridge = self.make(Profile(touchpad="mouse"))
        bridge.feed_report(report(touches=(finger(100, 100), None), buttons={"touchpad"}))
        bridge._mouse.events.clear()
        bridge.set_mapper(Mapper(Profile()))
        self.assertEqual(bridge._mouse.events, [(ecodes.EV_KEY, ecodes.BTN_LEFT, 0)])
        self.assertIsNone(bridge._tracker)


if __name__ == "__main__":
    unittest.main()
