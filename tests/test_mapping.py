import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dualsense_ultimate_control.emulator import mapping
from dualsense_ultimate_control.emulator.config import Config
from dualsense_ultimate_control.emulator.mapping import InputState, Mapper, Profile, ProcessInfo, ProfileStore
from dualsense_ultimate_control.settings import AppSettings, save_settings


def state(pressed=(), **axes):
    result = InputState(pressed=set(pressed))
    result.axes.update(axes)
    return result


def axes(output):
    return dict(output.axes)


class DefaultMappingTests(unittest.TestCase):
    def test_default_is_identity(self):
        output = Mapper().apply(state({"south", "l1", "dpad_up"}, left_x=1.0, left_y=-1.0, l2=0.5))
        self.assertEqual(output.buttons, {"a", "lb"})
        self.assertEqual(axes(output)["left_x"], 32767)
        self.assertEqual(axes(output)["left_y"], -32768)
        self.assertEqual(axes(output)["lt"], 128)
        self.assertEqual(axes(output)["hat_y"], -1)
        self.assertEqual(output.keys, frozenset())

    def test_stick_values_are_exact_without_a_profile(self):
        for value in (-1.0, -0.5, 0.0, 0.25, 1.0):
            self.assertEqual(axes(Mapper().apply(state(left_x=value)))["left_x"], round(value * (32767 if value >= 0 else 32768)))

    def test_digital_l2_r2_do_nothing_by_default(self):
        self.assertEqual(Mapper().apply(state(l2=1.0, r2=1.0)).buttons, frozenset())


class RemapTests(unittest.TestCase):
    def test_swap_a_and_b(self):
        output = Mapper(Profile(remap={"south": "b", "east": "a"})).apply(state({"south"}))
        self.assertEqual(output.buttons, {"b"})

    def test_button_to_key_and_none(self):
        profile = Profile(remap={"south": "key:KEY_SPACE", "east": "none"})
        output = Mapper(profile).apply(state({"south", "east"}))
        self.assertEqual(output.keys, {"KEY_SPACE"})
        self.assertEqual(output.buttons, frozenset())

    def test_button_to_trigger_axis(self):
        output = Mapper(Profile(remap={"l1": "lt"})).apply(state({"l1"}))
        self.assertEqual(axes(output)["lt"], 255)

    def test_dpad_to_stick_buttons_and_hat_directions(self):
        output = Mapper(Profile(remap={"south": "dpad_left"})).apply(state({"south", "dpad_right"}))
        self.assertEqual(axes(output)["hat_x"], 0)  # esquerda e direita se anulam

    def test_two_sources_to_one_target(self):
        output = Mapper(Profile(remap={"east": "a"})).apply(state({"east"}))
        self.assertEqual(output.buttons, {"a"})

    def test_trigger_as_button_when_analog_is_off(self):
        profile = Profile(triggers={"l2": "off", "r2": "analog"}, remap={"l2": "lb"})
        output = Mapper(profile).apply(state(l2=0.9))
        self.assertEqual(output.buttons, {"lb"})
        self.assertEqual(axes(output)["lt"], 0)


class StickTests(unittest.TestCase):
    def test_swap_and_invert(self):
        profile = Profile(swap_sticks=True, invert=["right_y"])
        output = axes(Mapper(profile).apply(state(left_x=1.0, right_y=0.0, left_y=0.5)))
        self.assertEqual(output["right_x"], 32767)
        self.assertEqual(output["right_y"], -round(0.5 * 32767))

    def test_deadzone_is_radial_and_rescaled(self):
        self.assertEqual(mapping.shape_stick(0.1, 0.1, 0.2, 1.0), (0.0, 0.0))
        x, y = mapping.shape_stick(0.6, 0.0, 0.2, 1.0)
        self.assertAlmostEqual(x, 0.5)
        self.assertEqual(y, 0.0)
        self.assertEqual(mapping.shape_stick(1.0, 0.0, 0.2, 1.0), (1.0, 0.0))

    def test_curve_softens_the_center(self):
        soft = mapping.shape_stick(0.5, 0.0, 0.0, 2.0)[0]
        sharp = mapping.shape_stick(0.5, 0.0, 0.0, 0.5)[0]
        self.assertLess(soft, 0.5)
        self.assertGreater(sharp, 0.5)
        self.assertAlmostEqual(mapping.shape_stick(1.0, 0.0, 0.0, 2.0)[0], 1.0)

    def test_deadzone_keeps_direction(self):
        x, y = mapping.shape_stick(0.6, 0.8, 0.2, 1.0)
        self.assertAlmostEqual(x / y, 0.75)


class TriggerTests(unittest.TestCase):
    def test_digital_mode_snaps_to_full_at_threshold(self):
        mapper = Mapper(Profile(triggers={"l2": "digital", "r2": "analog"}, trigger_threshold=0.5))
        self.assertEqual(axes(mapper.apply(state(l2=0.4)))["lt"], 0)
        self.assertEqual(axes(mapper.apply(state(l2=0.5)))["lt"], 255)

    def test_off_mode_silences_axis(self):
        mapper = Mapper(Profile(triggers={"l2": "analog", "r2": "off"}))
        self.assertEqual(axes(mapper.apply(state(r2=1.0)))["rt"], 0)


class ProfileDataTests(unittest.TestCase):
    def test_roundtrip(self):
        profile = Profile("Jogo", {"south": "key:KEY_A"}, True, ["left_y"], {"left": 0.1, "right": 0.2}, {"left": 1.5, "right": 1.0},
                          {"l2": "digital", "r2": "analog"}, 0.6, ["game.exe"], [123])  # fmt: skip
        self.assertEqual(Profile.from_dict(profile.to_dict()), profile)

    def test_trigger_effect_roundtrip_and_clamping(self):
        profile = Profile("T", trigger_effect={"l2": "off", "r2": "weapon"}, trigger_position={"l2": 2, "r2": 4},
                          trigger_strength={"l2": 5, "r2": 7})  # fmt: skip
        self.assertEqual(Profile.from_dict(profile.to_dict()), profile)
        self.assertTrue(profile.uses_trigger_effects)
        self.assertFalse(Profile().uses_trigger_effects)
        bad = Profile.from_dict({"trigger_effect": {"l2": "weird", "r2": "bow"},
                                 "trigger_position": {"l2": 99, "r2": "x"}, "trigger_strength": {"l2": 0}})  # fmt: skip
        self.assertEqual(bad.trigger_effect, {"l2": "off", "r2": "bow"})
        self.assertEqual(bad.trigger_position, {"l2": mapping.EFFECT_POSITION_RANGE[1], "r2": mapping.DEFAULT_EFFECT_POSITION})
        self.assertEqual(bad.trigger_strength["l2"], mapping.EFFECT_STRENGTH_RANGE[0])

    def test_invalid_data_is_dropped_not_fatal(self):
        profile = Profile.from_dict({
            "name": " X ", "remap": {"south": "key:nope", "bogus": "a", "east": "a"}, "invert": ["left_x", "zzz"],
            "deadzone": {"left": 5, "right": "abc"}, "curve": {"left": -1}, "triggers": {"l2": "weird"},
            "trigger_threshold": "x", "apps": ["a.exe", ""], "steam_appids": ["12", "y"],
        })  # fmt: skip
        self.assertEqual(profile.name, "X")
        self.assertEqual(profile.remap, {"east": "a"})
        self.assertEqual(profile.invert, ["left_x"])
        self.assertEqual(profile.deadzone, {"left": mapping.MAX_DEADZONE, "right": 0.0})
        self.assertEqual(profile.curve["left"], mapping.CURVE_RANGE[0])
        self.assertEqual(profile.triggers["l2"], "analog")
        self.assertEqual(profile.trigger_threshold, 0.5)
        self.assertEqual(profile.apps, ["a.exe"])
        self.assertEqual(profile.steam_appids, [12])

    def test_non_dict_is_rejected(self):
        with self.assertRaises(ValueError):
            Profile.from_dict([1])

    def test_valid_target(self):
        for target in ("a", "none", "key:KEY_F1", "lt"):
            self.assertTrue(mapping.valid_target(target), target)
        for target in ("key:space", "key:", "zzz", "KEY_A"):
            self.assertFalse(mapping.valid_target(target), target)


class ProcessMatchingTests(unittest.TestCase):
    def test_from_proc_reads_name_basenames_and_appid(self):
        info = ProcessInfo.from_proc("reaper\n", b"reaper\0SteamLaunch\0AppId=1245620\0--\0Z:\\games\\Elden Ring\\eldenring.exe\0")
        self.assertIn("eldenring.exe", info.names)
        self.assertIn("reaper", info.names)
        self.assertEqual(info.app_id, 1245620)

    def test_profile_matches_by_name_or_appid(self):
        procs = [ProcessInfo(frozenset({"bash"})), ProcessInfo(frozenset({"game.exe"}), 99)]
        self.assertTrue(Profile(apps=["GAME.exe"]).matches(procs))
        self.assertTrue(Profile(steam_appids=[99]).matches(procs))
        self.assertFalse(Profile(apps=["other"]).matches(procs))
        self.assertFalse(Profile().matches(procs))

    def test_pick_first_match_else_default(self):
        default = Profile("padrão")
        first, second = Profile("a", apps=["x"]), Profile("b", apps=["y"])
        procs = [ProcessInfo(frozenset({"y"})), ProcessInfo(frozenset({"x"}))]
        self.assertIs(mapping.pick_profile([first, second], procs, default), first)
        self.assertIs(mapping.pick_profile([first, second], [], default), default)
        self.assertIs(mapping.pick_profile([Profile("sem", apps=[])], procs, default), default)

    def test_running_processes_reads_proc_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            (proc / "10").mkdir()
            (proc / "10" / "comm").write_text("game\n")
            (proc / "10" / "cmdline").write_bytes(b"/usr/bin/game\0--fast\0")
            (proc / "11").mkdir()  # sem arquivos: terminou durante a leitura
            (proc / "self").mkdir()
            found = mapping.running_processes(proc)
        self.assertEqual(len(found), 1)
        self.assertIn("game", found[0].names)


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = ProfileStore(Path(tmp.name) / "profiles")
        self.tmp = Path(tmp.name)

    def test_save_load_sorted_and_delete(self):
        self.store.save(Profile("Zeta"))
        self.store.save(Profile("alfa", remap={"south": "b"}))
        self.assertEqual([p.name for p in self.store.load_all()], ["alfa", "Zeta"])
        self.assertEqual(self.store.get("alfa").remap, {"south": "b"})
        self.store.delete("Zeta")
        self.assertEqual([p.name for p in self.store.load_all()], ["alfa"])

    def test_import_does_not_overwrite_without_asking(self):
        self.store.save(Profile("Jogo 1", swap_sticks=True))
        path = self.tmp / "outro.json"
        self.store.export_file(Profile("jogo-1"), path)  # mesmo arquivo que "Jogo 1"
        with self.assertRaises(mapping.ProfileExists) as caught:
            self.store.import_file(path)
        self.assertEqual(caught.exception.existing, "Jogo 1")
        self.assertTrue(self.store.get("Jogo 1").swap_sticks)
        self.store.import_file(path, overwrite=True)
        self.assertEqual([p.name for p in self.store.load_all()], ["jogo-1"])

    def test_failed_rename_keeps_the_old_profile(self):
        self.store.save(Profile("velho"))
        with mock.patch.object(mapping, "write_atomic", side_effect=OSError("disco cheio")):
            with self.assertRaises(OSError):
                self.store.save(Profile("novo"), previous_name="velho")
        self.assertEqual([p.name for p in self.store.load_all()], ["velho"])

    def test_save_leaves_no_temporary_file(self):
        self.store.save(Profile("A"))
        self.store.save(Profile("A", swap_sticks=True))
        self.assertEqual([p.name for p in self.store.directory.iterdir()], ["a.json"])

    def test_rename_removes_old_file(self):
        self.store.save(Profile("velho"))
        self.store.save(Profile("novo"), previous_name="velho")
        self.assertEqual([p.name for p in self.store.load_all()], ["novo"])

    def test_unnamed_is_refused_and_bad_files_ignored(self):
        with self.assertRaises(ValueError):
            self.store.save(Profile(""))
        self.store.directory.mkdir(parents=True)
        (self.store.directory / "lixo.json").write_text("{nope")
        (self.store.directory / "sem-nome.json").write_text("{}")
        self.assertEqual(self.store.load_all(), [])

    def test_import_export(self):
        profile = Profile("Meu", remap={"east": "key:KEY_E"})
        path = self.tmp / "meu.json"
        self.store.export_file(profile, path)
        imported = self.store.import_file(path)
        self.assertEqual(imported, profile)
        (self.tmp / "sem.json").write_text(json.dumps({"swap_sticks": True}))
        self.assertEqual(self.store.import_file(self.tmp / "sem.json").name, "sem")

    def test_signature_changes_with_files(self):
        before = self.store.signature()
        self.store.save(Profile("a"))
        self.assertNotEqual(self.store.signature(), before)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.running = []
        self.config = Config(self.tmp / "settings.json", self.tmp / "profiles", processes=lambda: self.running)

    def write(self, **fields):
        settings = AppSettings()
        for name, value in fields.items():
            setattr(settings, name, value)
        save_settings(self.tmp / "settings.json", settings)

    def test_missing_files_mean_nothing_enabled(self):
        self.config.refresh()
        self.assertEqual(self.config.uids, frozenset())
        self.assertEqual(self.config.profile, Profile())

    def test_unreadable_settings_keep_what_was_known(self):
        self.write(emulation=["aa:bb"])
        self.config.refresh()
        (self.tmp / "settings.json").write_text("{nope")
        self.config.refresh()
        self.assertEqual(self.config.uids, {"aa:bb"})  # não solta os controles por um arquivo ilegível
        self.write(emulation=[])
        self.assertTrue(self.config.refresh())
        self.assertEqual(self.config.uids, frozenset())

    def test_reads_controllers_and_default_profile(self):
        self.config.store.save(Profile("Padrão meu", swap_sticks=True))
        self.write(emulation=["aa:bb"], default_profile="Padrão meu")
        self.assertTrue(self.config.refresh())
        self.assertEqual(self.config.uids, {"aa:bb"})
        self.assertTrue(self.config.profile.swap_sticks)
        self.assertFalse(self.config.refresh())  # nada mudou

    def test_app_profile_overrides_default_while_running(self):
        self.config.store.save(Profile("Jogo", apps=["game.exe"], invert=["left_y"]))
        self.write(emulation=["aa:bb"])
        self.config.refresh()
        self.assertEqual(self.config.profile.name, "")
        self.running = [ProcessInfo(frozenset({"game.exe"}))]
        for _ in range(3):  # o /proc é consultado a cada PROCESS_CHECK_EVERY varreduras
            self.config.refresh()
        self.assertEqual(self.config.profile.name, "Jogo")
        self.running = []
        for _ in range(3):
            self.config.refresh()
        self.assertEqual(self.config.profile.name, "")

    def test_edited_profile_is_reloaded(self):
        self.config.store.save(Profile("P"))
        self.write(default_profile="P")
        self.config.refresh()
        self.assertFalse(self.config.profile.swap_sticks)
        self.config.store.save(Profile("P", swap_sticks=True))
        self.assertTrue(self.config.refresh())
        self.assertTrue(self.config.profile.swap_sticks)


if __name__ == "__main__":
    unittest.main()
