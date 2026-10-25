import asyncio
import unittest
from unittest import mock

from evdev import ecodes

from dualsense_led.emulator import core
from dualsense_led.emulator.mapping import BUTTON_SOURCES, XBOX_TARGETS, Mapper, Profile


class ScaleStickTests(unittest.TestCase):
    def test_extremes_and_center(self):
        self.assertEqual(core.scale_stick(128), 0)
        self.assertEqual(core.scale_stick(255), 32767)
        self.assertEqual(core.scale_stick(0), -32768)

    def test_resting_jitter_stays_at_zero(self):
        self.assertEqual(core.scale_stick(127), 0)
        self.assertEqual(core.scale_stick(128), 0)
        self.assertLess(core.scale_stick(126), 0)

    def test_monotonic(self):
        values = [core.scale_stick(v) for v in range(256)]
        self.assertEqual(values, sorted(values))

    def test_out_of_range_is_clamped(self):
        self.assertEqual(core.scale_stick(300), 32767)
        self.assertEqual(core.scale_stick(-5), -32768)


class FakeUInput:
    def __init__(self):
        self.events, self.syncs = [], 0

    def write(self, *event):
        self.events.append(event)

    def syn(self):
        self.syncs += 1


class FakePhysical:
    def __init__(self, keys=(), axes=()):
        self.keys, self.axes = list(keys), list(axes)

    def active_keys(self):
        return self.keys

    def capabilities(self):
        return {ecodes.EV_ABS: [(code, type("Info", (), {"value": value})) for code, value in self.axes]}


class BridgeMappingTests(unittest.TestCase):
    """Eventos do DualSense chegam ao Xbox virtual pelo perfil, com dispositivos falsos."""

    def make(self, profile=None, physical=None):
        bridge = core.Bridge(physical or FakePhysical(), FakeUInput(), Mapper(profile))
        bridge._keyboard = FakeUInput()  # evita criar um teclado de verdade
        bridge.sync()  # como em Bridge.open: o primeiro envio escreve tudo
        bridge.virtual.events.clear()
        return bridge

    @staticmethod
    def event(kind, code, value):
        return core.InputEvent(0, 0, kind, code, value)

    def feed(self, bridge, *events):
        for kind, code, value in events:
            bridge.forward(self.event(kind, code, value))
        bridge.forward(self.event(ecodes.EV_SYN, ecodes.SYN_REPORT, 0))

    def test_face_buttons_follow_physical_position(self):
        # quadrado (BTN_WEST no driver) vira X do Xbox; triângulo (BTN_NORTH) vira Y
        bridge = self.make()
        self.feed(bridge, (ecodes.EV_KEY, ecodes.BTN_WEST, 1), (ecodes.EV_KEY, ecodes.BTN_SOUTH, 1))
        self.assertEqual(
            sorted(e for e in bridge.virtual.events if e[0] == ecodes.EV_KEY),
            sorted([(ecodes.EV_KEY, ecodes.BTN_X, 1), (ecodes.EV_KEY, ecodes.BTN_A, 1)]),
        )

    def test_only_changes_are_written(self):
        bridge = self.make()
        self.feed(bridge, (ecodes.EV_KEY, ecodes.BTN_SOUTH, 1))
        bridge.virtual.events.clear()
        self.feed(bridge, (ecodes.EV_KEY, ecodes.BTN_SOUTH, 1))
        self.assertEqual(bridge.virtual.events, [])

    def test_sticks_are_scaled_and_triggers_pass_through(self):
        bridge = self.make()
        self.feed(bridge, (ecodes.EV_ABS, ecodes.ABS_RX, 255), (ecodes.EV_ABS, ecodes.ABS_Z, 200), (ecodes.EV_ABS, ecodes.ABS_X, 0))
        self.assertIn((ecodes.EV_ABS, ecodes.ABS_RX, 32767), bridge.virtual.events)
        self.assertIn((ecodes.EV_ABS, ecodes.ABS_Z, 200), bridge.virtual.events)
        self.assertIn((ecodes.EV_ABS, ecodes.ABS_X, -32768), bridge.virtual.events)

    def test_hat_becomes_dpad(self):
        bridge = self.make()
        self.feed(bridge, (ecodes.EV_ABS, ecodes.ABS_HAT0Y, -1))
        self.assertIn((ecodes.EV_ABS, ecodes.ABS_HAT0Y, -1), bridge.virtual.events)
        self.feed(bridge, (ecodes.EV_ABS, ecodes.ABS_HAT0Y, 0))
        self.assertIn((ecodes.EV_ABS, ecodes.ABS_HAT0Y, 0), bridge.virtual.events)

    def test_unknown_events_are_ignored(self):
        bridge = self.make()
        self.feed(bridge, (ecodes.EV_MSC, ecodes.MSC_TIMESTAMP, 5), (ecodes.EV_ABS, ecodes.ABS_MISC, 1))
        self.assertEqual(bridge.virtual.events, [])

    def test_profile_remaps_to_a_key_and_releases_it(self):
        bridge = self.make(Profile(remap={"south": "key:KEY_SPACE"}))
        self.feed(bridge, (ecodes.EV_KEY, ecodes.BTN_SOUTH, 1))
        self.assertEqual(bridge._keyboard.events, [(ecodes.EV_KEY, ecodes.KEY_SPACE, 1)])
        self.assertNotIn((ecodes.EV_KEY, ecodes.BTN_A, 1), bridge.virtual.events)
        self.feed(bridge, (ecodes.EV_KEY, ecodes.BTN_SOUTH, 0))
        self.assertEqual(bridge._keyboard.events[-1], (ecodes.EV_KEY, ecodes.KEY_SPACE, 0))

    def test_changing_profile_applies_live_and_releases_old_keys(self):
        bridge = self.make(Profile(remap={"south": "key:KEY_SPACE"}))
        self.feed(bridge, (ecodes.EV_KEY, ecodes.BTN_SOUTH, 1))
        bridge.set_mapper(Mapper(Profile(remap={"south": "b"})))
        self.assertEqual(bridge._keyboard.events[-1], (ecodes.EV_KEY, ecodes.KEY_SPACE, 0))
        self.assertIn((ecodes.EV_KEY, ecodes.BTN_B, 1), bridge.virtual.events)

    def test_sync_copies_physical_state_and_writes_everything(self):
        physical = FakePhysical(keys=[ecodes.BTN_EAST], axes=[(ecodes.ABS_X, 255), (ecodes.ABS_Z, 90), (ecodes.ABS_HAT0X, 1)])
        bridge = self.make(physical=physical)
        bridge.sync()
        events = bridge.virtual.events
        self.assertIn((ecodes.EV_KEY, ecodes.BTN_B, 1), events)
        self.assertIn((ecodes.EV_KEY, ecodes.BTN_A, 0), events)
        self.assertIn((ecodes.EV_ABS, ecodes.ABS_X, 32767), events)
        self.assertIn((ecodes.EV_ABS, ecodes.ABS_Z, 90), events)
        self.assertIn((ecodes.EV_ABS, ecodes.ABS_HAT0X, 1), events)


class CapabilityTests(unittest.TestCase):
    def test_every_mapped_target_is_advertised(self):
        capabilities = core.x360_capabilities()
        for target in core.XBOX_BUTTONS.values():
            self.assertIn(target, capabilities[ecodes.EV_KEY])
        codes = {code for code, _ in capabilities[ecodes.EV_ABS]}
        self.assertEqual(codes, set(core.XBOX_AXES.values()))

    def test_every_profile_target_has_an_output(self):
        for target in XBOX_TARGETS:
            self.assertTrue(target in core.XBOX_BUTTONS or target in ("lt", "rt") or target.startswith("dpad_"), target)
        for source in BUTTON_SOURCES:
            self.assertTrue(source in core.SOURCE_BUTTONS.values() or source in ("l2", "r2") or source.startswith("dpad_"), source)

    def test_rumble_is_advertised(self):
        self.assertEqual(core.x360_capabilities()[ecodes.EV_FF], [ecodes.FF_RUMBLE])

    def test_stick_unit_matches_scale_stick(self):
        self.assertEqual(core.stick_unit(128), 0.0)
        self.assertEqual(core.stick_unit(255), 1.0)
        self.assertEqual(core.stick_unit(0), -1.0)


class ForceFeedbackTests(unittest.TestCase):
    """O Xbox virtual repassa efeitos de vibração ao controle real, usando dispositivos falsos."""

    class Effect:
        def __init__(self, effect_id):
            self.id = effect_id

    class Upload:
        def __init__(self, effect):
            self.effect = effect
            self.retval = None

    class Physical:
        name, uniq, path = "DualSense", None, "/dev/input/fake"

        def __init__(self):
            self.written, self.erased, self.next_id = [], [], 5

        def upload_effect(self, effect):
            if effect.id < 0:
                effect.id = self.next_id
                self.next_id += 1
            return effect.id

        def erase_effect(self, effect_id):
            self.erased.append(effect_id)

        def write(self, *event):
            self.written.append(event)

    class Virtual:
        def __init__(self, effect):
            self.upload = ForceFeedbackTests.Upload(effect)
            self.ended = []

        def begin_upload(self, request):
            return self.upload

        def end_upload(self, upload):
            self.ended.append(upload.retval)

        def begin_erase(self, request):
            class Erase:
                effect_id, retval = 0, None

            return Erase()

        def end_erase(self, erase):
            self.ended.append(erase.retval)

    def make(self, virtual_id=0):
        effect = self.Effect(virtual_id)
        bridge = core.Bridge(self.Physical(), self.Virtual(effect))
        return bridge, effect

    @staticmethod
    def event(kind, code, value):
        return core.InputEvent(0, 0, kind, code, value)

    def test_upload_play_and_erase_use_the_physical_effect_id(self):
        bridge, effect = self.make()
        bridge.handle_force_feedback(self.event(ecodes.EV_UINPUT, ecodes.UI_FF_UPLOAD, 1))
        self.assertEqual(bridge._effects, {0: 5})
        self.assertEqual(effect.id, 0)  # o virtual segue com o id que o jogo conhece
        self.assertEqual(bridge.virtual.ended, [0])
        bridge.handle_force_feedback(self.event(ecodes.EV_FF, 0, 1))
        bridge.handle_force_feedback(self.event(ecodes.EV_FF, ecodes.FF_GAIN, 0x8000))
        self.assertEqual(bridge.physical.written, [(ecodes.EV_FF, 5, 1), (ecodes.EV_FF, ecodes.FF_GAIN, 0x8000)])
        bridge.handle_force_feedback(self.event(ecodes.EV_UINPUT, ecodes.UI_FF_ERASE, 1))
        self.assertEqual(bridge.physical.erased, [5])
        self.assertEqual(bridge._effects, {})

    def test_play_of_unknown_effect_is_ignored(self):
        bridge, _ = self.make()
        bridge.handle_force_feedback(self.event(ecodes.EV_FF, 3, 1))
        self.assertEqual(bridge.physical.written, [])

    def test_reupload_reuses_the_physical_id(self):
        bridge, _ = self.make()
        for _ in range(2):
            bridge.handle_force_feedback(self.event(ecodes.EV_UINPUT, ecodes.UI_FF_UPLOAD, 1))
        self.assertEqual(bridge.physical.next_id, 6)

    def test_rejected_upload_reports_an_error_to_the_game(self):
        bridge, _ = self.make()

        def refuse(effect):
            raise OSError(22, "invalid")

        bridge.physical.upload_effect = refuse
        bridge.handle_force_feedback(self.event(ecodes.EV_UINPUT, ecodes.UI_FF_UPLOAD, 1))
        self.assertEqual(bridge.virtual.ended, [-22])


class FakeConfig:
    def __init__(self, uids=("aa",)):
        self.uids = frozenset(uids)
        self.gyro_offsets = {}

    def refresh(self):
        return False

    def mapper(self):
        return Mapper()


class FakeNode:
    uniq = "AA"

    def __init__(self, *_args):
        self.closed = False

    def close(self):
        self.closed = True


class EmulatorScanTests(unittest.TestCase):
    """Erros ao achar ou assumir um controle não derrubam o daemon nem o recusam para sempre."""

    PATH = "/dev/input/event7"

    def scan(self, emulator, **patches):
        patches.setdefault("list_devices", lambda: [self.PATH])
        patches.setdefault("InputDevice", FakeNode)
        with mock.patch.multiple(core, **patches):
            emulator.scan()

    def test_node_vanishing_while_checked_is_skipped(self):
        emulator = core.Emulator(config=FakeConfig())
        self.scan(emulator, is_gamepad=mock.Mock(side_effect=OSError(19, "No such device")))
        self.assertNotIn(self.PATH, emulator._refused)

    def test_failed_open_is_retried_later(self):
        emulator = core.Emulator(config=FakeConfig())
        opener = mock.Mock(side_effect=OSError(16, "Device or resource busy"))
        clock = mock.Mock(return_value=100.0)
        with mock.patch.object(core.Bridge, "open", opener), mock.patch.object(core.time, "monotonic", clock):
            self.scan(emulator, is_gamepad=lambda device: True)
            self.scan(emulator, is_gamepad=lambda device: True)
            self.assertEqual(opener.call_count, 1)  # espera antes de tentar de novo
            clock.return_value = 100.0 + core.RETRY_AFTER_S + 1
            self.scan(emulator, is_gamepad=lambda device: True)
        self.assertEqual(opener.call_count, 2)

    def test_run_survives_an_unexpected_scan_error(self):
        emulator = core.Emulator(scan_interval=0, config=FakeConfig())
        calls = []

        def scan():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("inesperado")
            raise asyncio.CancelledError

        emulator.scan = scan
        with self.assertLogs(core.log, "ERROR"), self.assertRaises(asyncio.CancelledError):
            asyncio.run(emulator.run())
        self.assertEqual(len(calls), 2)


class BridgeOpenTests(unittest.TestCase):
    def test_failure_after_creating_the_virtual_releases_everything(self):
        class Physical(FakeNode):
            path, name = "/dev/input/event7", "DualSense"

            def grab(self):
                self.grabbed = True

            def ungrab(self):
                self.grabbed = False

            def active_keys(self):
                raise OSError(19, "No such device")  # sumiu logo depois do grab

        physical, virtual = Physical(), FakeNode()
        with mock.patch.multiple(
            core, InputDevice=lambda path: physical, UInput=lambda *a, **k: virtual, sibling_nodes=lambda path: (None, None)
        ):
            with self.assertRaises(OSError):
                core.Bridge.open(physical.path)
        self.assertFalse(physical.grabbed)
        self.assertTrue(physical.closed and virtual.closed)


if __name__ == "__main__":
    unittest.main()
