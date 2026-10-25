import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dualsense_ultimate_control import autostart
from dualsense_ultimate_control.service import LedService
from dualsense_ultimate_control.widgets import AutostartRow, CloseToTrayRow, ToggleSwitch
from dualsense_ultimate_control.window import MainWindow


class AutostartFileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "autostart" / "dualsense-ultimate-control.desktop"

    def test_enable_writes_entry_that_starts_in_the_tray(self):
        autostart.set_enabled(True, self.path, command="/opt/app/dualsense-ultimate-control --tray")
        self.assertTrue(autostart.is_enabled(self.path))
        self.assertIn("Exec=/opt/app/dualsense-ultimate-control --tray", self.path.read_text())

    def test_disable_removes_entry(self):
        autostart.set_enabled(True, self.path, command="x --tray")
        autostart.set_enabled(False, self.path)
        self.assertFalse(self.path.exists())
        self.assertFalse(autostart.is_enabled(self.path))
        autostart.set_enabled(False, self.path)  # desligar de novo não é erro

    def test_entry_hidden_by_the_desktop_counts_as_disabled(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("[Desktop Entry]\nHidden=true\n")
        self.assertFalse(autostart.is_enabled(self.path))

    def test_launch_command_uses_this_environment(self):
        self.assertTrue(autostart.launch_command().endswith("--tray"))


class AutostartRowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_switch_creates_and_removes_the_autostart_entry(self):
        row = AutostartRow()
        switch = row.findChild(ToggleSwitch)
        self.assertFalse(switch.isChecked())

        switch.click()
        self.assertTrue(autostart.autostart_file().exists())
        self.assertTrue(switch.isChecked())

        switch.click()
        self.assertFalse(autostart.autostart_file().exists())
        self.assertFalse(switch.isChecked())

    def test_switch_shows_existing_state(self):
        autostart.set_enabled(True, command="x --tray")
        row = AutostartRow()
        self.assertTrue(row.findChild(ToggleSwitch).isChecked())


class CloseToTrayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.service = LedService(root / "settings.json", root / "leds", bluetooth_probe=lambda known: [])

    def test_closing_hides_the_window_and_keeps_the_app(self):
        window = MainWindow(self.service, tray_available=True)
        hidden = []
        window.hidden_to_tray.connect(lambda: hidden.append(True))
        window.show()
        self.assertFalse(window.close())  # o fechamento é recusado: a janela só some
        self.assertFalse(window.isVisible())
        self.assertEqual(hidden, [True])

    def test_without_tray_closing_really_closes(self):
        window = MainWindow(self.service, tray_available=False)
        window.show()
        self.assertTrue(window.close())

    def test_choice_off_makes_closing_quit_the_app(self):
        self.service.set_close_to_tray(False)
        window = MainWindow(self.service, tray_available=True)
        quits = []
        self.app.aboutToQuit.connect(lambda: quits.append(True))
        window.show()
        self.assertTrue(window.close())
        self.assertFalse(window.isVisible())

    def test_choice_is_saved_and_loaded(self):
        self.assertTrue(self.service.close_to_tray)  # padrão: ficar na bandeja
        self.service.set_close_to_tray(False)
        root = Path(self._tmp.name)
        again = LedService(root / "settings.json", root / "leds", bluetooth_probe=lambda known: [])
        self.assertFalse(again.close_to_tray)

    def test_switch_changes_the_choice(self):
        row = CloseToTrayRow(self.service)
        switch = row.findChild(ToggleSwitch)
        self.assertTrue(switch.isChecked())
        switch.click()
        self.assertFalse(self.service.close_to_tray)
        switch.click()
        self.assertTrue(self.service.close_to_tray)

    def test_switch_is_disabled_without_a_tray(self):
        window = MainWindow(self.service, tray_available=False)
        row = window.findChild(CloseToTrayRow)
        self.assertFalse(row.isEnabled())


if __name__ == "__main__":
    unittest.main()
