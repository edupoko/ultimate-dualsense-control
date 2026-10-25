import tempfile
import unittest
from pathlib import Path

from dualsense_ultimate_control import autostart
from dualsense_ultimate_control.migrate import migrate_legacy


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config = Path(self._tmp.name) / "config"
        self.state = Path(self._tmp.name) / "state"

    def _write(self, path: Path, text: str = "x"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_moves_settings_profiles_history_and_log(self):
        self._write(self.config / "dualsense-led" / "settings.json", "{}")
        self._write(self.config / "dualsense-led" / "profiles" / "a.json", "p")
        self._write(self.state / "dualsense-led" / "dualsense-led.log", "l")
        self._write(self.state / "dualsense-led" / "dualsense-led.log.1", "l1")
        migrate_legacy(self.config, self.state)
        self.assertEqual((self.config / "dualsense-ultimate-control" / "profiles" / "a.json").read_text(), "p")
        self.assertTrue((self.config / "dualsense-ultimate-control" / "settings.json").exists())
        self.assertFalse((self.config / "dualsense-led").exists())
        new_state = self.state / "dualsense-ultimate-control"
        self.assertEqual((new_state / "dualsense-ultimate-control.log").read_text(), "l")
        self.assertTrue((new_state / "dualsense-ultimate-control.log.1").exists())

    def test_does_not_overwrite_new_folder(self):
        self._write(self.config / "dualsense-led" / "settings.json", "old")
        self._write(self.config / "dualsense-led" / "calibration-history.json", "hist")
        self._write(self.config / "dualsense-ultimate-control" / "settings.json", "new")
        migrate_legacy(self.config, self.state)
        new = self.config / "dualsense-ultimate-control"
        self.assertEqual((new / "settings.json").read_text(), "new")
        self.assertEqual((new / "calibration-history.json").read_text(), "hist")

    def test_autostart_enabled_is_recreated_and_old_removed(self):
        old = self.config / "autostart" / "dualsense-led.desktop"
        self._write(old, "[Desktop Entry]\nExec=/x/dualsense-led --tray\n")
        migrate_legacy(self.config, self.state)
        self.assertFalse(old.exists())
        new = self.config / "autostart" / autostart.FILE_NAME
        self.assertTrue(autostart.is_enabled(new))
        self.assertNotIn("dualsense-led", new.read_text())

    def test_autostart_disabled_stays_off(self):
        old = self.config / "autostart" / "dualsense-led.desktop"
        self._write(old, "[Desktop Entry]\nHidden=true\n")
        migrate_legacy(self.config, self.state)
        self.assertFalse(old.exists())
        self.assertFalse((self.config / "autostart" / autostart.FILE_NAME).exists())

    def test_nothing_to_migrate_is_a_noop_and_repeatable(self):
        migrate_legacy(self.config, self.state)
        migrate_legacy(self.config, self.state)
        self.assertFalse(self.config.exists())


if __name__ == "__main__":
    unittest.main()
