import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from dualsense_ultimate_control.emulation import EmulationProcess
from dualsense_ultimate_control.logview import LogWindow
from dualsense_ultimate_control.profiles_dialog import ProfilesDialog
from dualsense_ultimate_control.service import LedService
from dualsense_ultimate_control.testpanel.window import TestWindow
from dualsense_ultimate_control.window import MainWindow


class WindowPagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.service = LedService(root / "settings.json", root / "leds", bluetooth_probe=lambda known: [])
        patcher = mock.patch("dualsense_ultimate_control.profiles_dialog.default_profiles_dir", return_value=root / "profiles")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.emulation = EmulationProcess(sys.executable, ["-c", "pass"], service_probe=lambda: False)

    def _window(self, emulation=True) -> MainWindow:
        window = MainWindow(self.service, tray_available=True, emulation=self.emulation if emulation else None)
        self.addCleanup(window.deleteLater)
        window.show()
        return window

    def _visible_windows(self):
        return [widget for widget in QApplication.topLevelWidgets() if widget.isVisible()]

    def test_starts_on_the_controls_page(self):
        window = self._window()
        self.assertEqual(window.current_page(), "controls")
        self.assertIsNone(window.page("logs"))  # criada só na primeira visita

    def test_logs_and_test_open_inside_the_window(self):
        window = self._window()
        before = set(self._visible_windows())
        window.show_logs()
        self.assertEqual(window.current_page(), "logs")
        self.assertIsInstance(window.page("logs"), LogWindow)
        self.assertFalse(window.page("logs").isWindow())
        window.show_test()
        self.assertEqual(window.current_page(), "test")
        self.assertIsInstance(window.page("test"), TestWindow)
        self.assertFalse(window.page("test").isWindow())
        self.assertEqual(set(self._visible_windows()), before)  # nenhuma janela nova

    def test_back_button_of_a_page_goes_back_to_controls(self):
        window = self._window()
        window.show_logs()
        window.page("logs").back_requested.emit()
        self.assertEqual(window.current_page(), "controls")
        window.show_logs()  # volta a aparecer depois de fechada
        self.assertTrue(window.page("logs").isVisible())

    def test_profiles_page_only_with_emulation(self):
        window = self._window(emulation=False)
        self.assertFalse(window.set_page("profiles"))
        self.assertEqual(window._nav.count(), 3)
        window = self._window()
        self.assertEqual(window._nav.count(), 4)
        window.show_profiles()
        self.assertIsInstance(window.page("profiles"), ProfilesDialog)
        self.assertFalse(window.page("profiles").isWindow())
        self.assertTrue(window.page("profiles").can_leave())  # nada editado

    def test_pending_profile_edit_can_keep_the_page(self):
        window = self._window()
        window.show_profiles()
        window.page("profiles")._mark_dirty()
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            window._nav.setCurrentRow(0)
        self.assertEqual(window.current_page(), "profiles")
        self.assertEqual(window._nav.currentRow(), window._page_keys.index("profiles"))
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as question:
            window.page("profiles")._back()
        self.assertEqual(question.call_count, 1)  # o "Voltar" pergunta uma vez só
        self.assertEqual(window.current_page(), "controls")


if __name__ == "__main__":
    unittest.main()
