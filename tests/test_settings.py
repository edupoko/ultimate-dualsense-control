import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dualsense_led import settings
from dualsense_led.settings import AppSettings, load_settings, save_settings


class SaveSettingsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "cfg" / "settings.json"

    def test_roundtrip_leaves_no_temporary_file(self):
        save_settings(self.path, AppSettings(emulation=["AA:BB"], default_profile="P"))
        loaded = load_settings(self.path)
        self.assertEqual((loaded.emulation, loaded.default_profile), (["aa:bb"], "P"))
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["settings.json"])

    def test_file_is_replaced_at_once(self):
        # Quem lê no meio da gravação (o daemon da emulação) vê o arquivo antigo inteiro, nunca um pedaço.
        save_settings(self.path, AppSettings(emulation=["aa"]))
        seen = []
        real_replace = settings.os.replace

        def replace(source, target):
            seen.append(load_settings(self.path).emulation)
            real_replace(source, target)

        with mock.patch.object(settings.os, "replace", replace):
            save_settings(self.path, AppSettings(emulation=["aa", "bb"]))
        self.assertEqual(seen, [["aa"]])
        self.assertEqual(load_settings(self.path).emulation, ["aa", "bb"])


class StrictLoadTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "settings.json"

    def test_missing_file_is_defaults_even_when_strict(self):
        self.assertEqual(load_settings(self.path, strict=True), AppSettings())

    def test_unreadable_file_raises_only_when_strict(self):
        self.path.write_text("{nope")
        self.assertEqual(load_settings(self.path), AppSettings())
        with self.assertRaises(settings.SettingsError):
            load_settings(self.path, strict=True)


if __name__ == "__main__":
    unittest.main()
