import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dualsense_ultimate_control.emulator.mapping import Profile, ProfileStore
from dualsense_ultimate_control.profile_picker import ProfilePicker
from dualsense_ultimate_control.service import LedService


class ProfilePickerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.service = LedService(root / "s.json", root / "leds", bluetooth_probe=lambda known: [])
        self.store = ProfileStore(root / "profiles")
        self.store.save(Profile("Jogo A"))
        self.store.save(Profile("Jogo B"))
        self.picker = ProfilePicker(self.service, self.store)

    def names(self):
        return [self.picker._combo.itemText(i) for i in range(self.picker._combo.count())]

    def test_lists_no_change_option_and_every_created_profile(self):
        self.assertEqual(self.names(), ["(sem alterações)", "Jogo A", "Jogo B"])
        self.assertEqual(self.picker._combo.currentIndex(), 0)

    def test_choosing_a_profile_saves_it_as_the_default(self):
        self.picker._combo.setCurrentIndex(2)
        self.picker._on_chosen(2)
        self.assertEqual(self.service.default_profile, "Jogo B")
        self.picker._on_chosen(0)
        self.assertEqual(self.service.default_profile, "")

    def test_refresh_follows_new_profiles_and_the_saved_default(self):
        self.store.save(Profile("Jogo C"))
        self.service.set_default_profile("Jogo C")
        self.picker.show()  # voltar à página Controles (showEvent) relê a pasta e o padrão salvo
        self.assertEqual(self.names()[-1], "Jogo C")
        self.assertEqual(self.picker._combo.currentText(), "Jogo C")


if __name__ == "__main__":
    unittest.main()
