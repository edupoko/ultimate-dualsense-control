import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dualsense_ultimate_control.emulator.mapping import Profile, ProfileStore
from dualsense_ultimate_control.profiles_dialog import ProfilesDialog, parse_list, target_from_text
from dualsense_ultimate_control.service import LedService


class ProfilesDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.service = LedService(self.root / "settings.json", self.root / "leds", steam_probe=set, bluetooth_probe=lambda k: [])
        self.store = ProfileStore(self.root / "profiles")
        self.dialog = ProfilesDialog(self.service, self.store)
        self.addCleanup(self.dialog.deleteLater)

    def test_helpers(self):
        self.assertEqual(parse_list("a.exe, b.exe\nc"), ["a.exe", "b.exe", "c"])
        self.assertEqual(target_from_text(" KEY_F5 "), "key:KEY_F5")
        self.assertEqual(target_from_text("a"), "a")

    def test_new_profile_is_saved_and_listed(self):
        self.dialog._new()
        editor = self.dialog._editor
        editor._name.setText("Meu jogo")
        editor._apps.setText("game.exe")
        editor._appids.setText("123")
        editor._swap.setChecked(True)
        editor._invert["left_y"].setChecked(True)
        editor._combos["south"].set_target("b")
        editor._combos["east"].setEditText("KEY_SPACE")
        editor._modes["l2"].setCurrentIndex(editor._modes["l2"].findData("digital"))
        self.dialog._save()
        saved = self.store.get("Meu jogo")
        self.assertEqual(saved.apps, ["game.exe"])
        self.assertEqual(saved.steam_appids, [123])
        self.assertTrue(saved.swap_sticks)
        self.assertEqual(saved.invert, ["left_y"])
        self.assertEqual(saved.remap, {"south": "b", "east": "key:KEY_SPACE"})
        self.assertEqual(saved.triggers["l2"], "digital")
        self.assertEqual(self.dialog._list.count(), 1)
        self.assertFalse(self.dialog._dirty)

    def test_load_roundtrip_through_the_form(self):
        profile = Profile("P", {"north": "key:KEY_A", "l1": "none"}, True, ["right_x"], {"left": 0.2, "right": 0.1}, {"left": 2.0, "right": 0.5},
                          {"l2": "off", "r2": "digital"}, 0.7, ["x"], [5])  # fmt: skip
        self.dialog._editor.load(profile)
        self.assertEqual(self.dialog._editor.profile(), profile)

    def test_trigger_effect_fields_roundtrip_and_enable(self):
        editor = self.dialog._editor
        profile = Profile("E", trigger_effect={"l2": "off", "r2": "machine"}, trigger_position={"l2": 2, "r2": 6},
                          trigger_strength={"l2": 5, "r2": 3})  # fmt: skip
        editor.load(profile)
        self.assertEqual(editor.profile(), profile)
        self.assertTrue(editor._effect_position["r2"].isEnabled())
        self.assertFalse(editor._effect_position["l2"].isEnabled())

    def test_mouse_fields_roundtrip_and_enable(self):
        editor = self.dialog._editor
        profile = Profile("M", touchpad="mouse", touchpad_speed=2.5, gyro="button", gyro_button="r1", gyro_speed=40, gyro_invert_y=True)
        editor.load(profile)
        self.assertEqual(editor.profile(), profile)
        self.assertTrue(editor._gyro_button.isEnabled())
        editor.load(Profile("N"))
        self.assertFalse(editor._gyro_button.isEnabled())
        self.assertFalse(editor._touchpad_speed.isEnabled())

    def test_invalid_input_is_reported_and_not_saved(self):
        self.dialog._new()
        editor = self.dialog._editor
        editor._combos["south"].setEditText("banana")
        self.dialog._save()
        self.assertIn("banana", self.dialog._status.text())
        self.assertEqual(self.store.load_all(), [])
        editor._combos["south"].set_target("")
        editor._appids.setText("12x")
        self.dialog._save()
        self.assertIn("12x", self.dialog._status.text())
        editor._appids.setText("")
        editor._name.setText("")
        self.dialog._save()
        self.assertEqual(self.store.load_all(), [])

    def test_duplicate_names_are_refused(self):
        self.store.save(Profile("Jogo"))
        self.dialog._reload()
        self.dialog._new()
        self.dialog._editor._name.setText("jogo")
        self.dialog._save()
        self.assertEqual([p.name for p in self.store.load_all()], ["Jogo"])

    def test_rename_keeps_default_profile(self):
        self.store.save(Profile("Velho"))
        self.service.set_default_profile("Velho")
        self.dialog._reload()
        self.dialog._list.setCurrentRow(0)
        self.dialog._editor._name.setText("Novo")
        self.dialog._save()
        self.assertEqual([p.name for p in self.store.load_all()], ["Novo"])
        self.assertEqual(self.service.default_profile, "Novo")

    def test_delete_clears_default(self):
        self.store.save(Profile("A"))
        self.service.set_default_profile("A")
        self.dialog._reload()
        self.dialog._list.setCurrentRow(0)
        self.dialog._delete()
        self.assertFalse(self.dialog._bar.isHidden())  # pergunta na faixa
        self.assertEqual(len(self.store.load_all()), 1)  # nada apagado antes da resposta
        self.dialog._bar._yes.click()
        self.assertEqual(self.store.load_all(), [])
        self.assertEqual(self.service.default_profile, "")

    def test_default_combo_saves_choice(self):
        self.store.save(Profile("A"))
        self.dialog._reload()
        self.dialog._default.setCurrentIndex(1)
        self.dialog._on_default_chosen(1)
        self.assertEqual(self.service.default_profile, "A")

    def test_duplicate_gets_free_name_without_apps(self):
        self.store.save(Profile("A", apps=["x"]))
        self.dialog._reload()
        self.dialog._list.setCurrentRow(0)
        self.dialog._duplicate()
        profile = self.dialog._editor.profile()
        self.assertEqual(profile.name, "A 2")
        self.assertEqual(profile.apps, [])

    def test_unsaved_changes_ask_before_switching(self):
        self.store.save(Profile("A"))
        self.store.save(Profile("B"))
        self.dialog._reload()
        self.dialog._list.setCurrentRow(0)
        self.dialog._editor._swap.setChecked(True)
        self.dialog._list.setCurrentRow(1)
        self.dialog._bar._no.click()
        self.assertEqual(self.dialog._current, "A")
        self.assertEqual(self.dialog._list.currentItem().text(), "A")
        self.assertTrue(self.dialog._editor._swap.isChecked())
        self.dialog._list.setCurrentRow(1)
        self.dialog._bar._yes.click()
        self.assertEqual(self.dialog._current, "B")
        self.assertEqual(self.dialog._list.currentItem().text(), "B")
        self.assertFalse(self.dialog._editor._swap.isChecked())


if __name__ == "__main__":
    unittest.main()
