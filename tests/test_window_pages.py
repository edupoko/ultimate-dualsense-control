import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from dualsense_ultimate_control.emulation import EmulationProcess
from dualsense_ultimate_control.logview import LogWindow
from dualsense_ultimate_control.profile_picker import ProfilePicker
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

    def test_controls_page_has_no_buttons_to_other_pages_and_has_the_profile_picker(self):
        window = self._window()
        texts = {button.text() for button in window.page("controls").findChildren(QPushButton)}
        self.assertFalse(texts & {"Testar controle…", "Perfis de emulação…"})
        self.assertIsNotNone(window.page("controls").findChild(ProfilePicker))
        self.assertIsNone(self._window(emulation=False).page("controls").findChild(ProfilePicker))

    def test_general_options_live_in_the_settings_page(self):
        window = self._window()
        controls_rows = {type(w).__name__ for w in window.page("controls").findChildren(QWidget)}
        self.assertFalse({"LanguageRow", "AutostartRow", "CloseToTrayRow", "LogsRow"} & controls_rows)
        self.assertEqual(window._page_keys[-1], "settings")
        self.assertTrue(window.set_page("settings"))
        rows = {type(w).__name__ for w in window.page("settings").findChildren(QWidget)}
        self.assertTrue({"LanguageRow", "AutostartRow", "AutoPlayersRow", "CloseToTrayRow", "LogsRow"} <= rows)
        self.assertFalse(window.page("settings").isWindow())

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
        self.assertEqual(window._nav.count(), 4)
        window = self._window()
        self.assertEqual(window._nav.count(), 5)
        window.show_profiles()
        self.assertIsInstance(window.page("profiles"), ProfilesDialog)
        self.assertFalse(window.page("profiles").isWindow())
        self.assertTrue(window.page("profiles").can_leave())  # nada editado

    def test_quick_test_is_a_tab_of_the_test_page(self):
        window = self._window()
        before = set(self._visible_windows())
        window.show_test()
        test = window.page("test")
        test.open_quick_test()
        self.assertIs(test._tabs.currentWidget(), test._quick)
        self.assertFalse(test._quick.isWindow())
        self.assertTrue(test._quick.isVisible())
        self.assertEqual(set(self._visible_windows()), before)  # nenhuma janela nova
        test._quick.back_requested.emit()
        self.assertEqual(test._tabs.currentIndex(), 0)
        self.assertFalse(test._quick.isVisible())

    def test_test_page_holds_the_controller_only_while_shown(self):
        device = mock.MagicMock(connection="USB")
        device.read_state.return_value = None
        controller = mock.Mock(hidraw="/dev/hidraw9", open_device=mock.Mock(return_value=device))
        with mock.patch("dualsense_ultimate_control.testpanel.window.selected_controller", return_value=controller), \
                mock.patch("dualsense_ultimate_control.testpanel.outputs.selected_controller", return_value=controller):
            window = self._window()
            window.show_test()
            test = window.page("test")
            self.assertIs(test._device, device)
            test.open_quick_test()
            self.assertIs(test._quick._device, device)
            window.set_page("controls")
            self.assertIsNone(test._device)  # trocar de página solta o hidraw
            self.assertIsNone(test._quick._device)
            device.close.assert_called_once()
            window.show_test()
            self.assertIs(test._device, device)  # e voltar abre de novo
            window.hide()  # janela para a bandeja
            self.assertIsNone(test._device)

    def test_pending_profile_edit_asks_inside_the_page(self):
        window = self._window()
        window.show_profiles()
        profiles = window.page("profiles")
        profiles._mark_dirty()
        window._nav.setCurrentRow(0)
        self.assertEqual(window.current_page(), "profiles")  # esperando a resposta
        self.assertEqual(window._nav.currentRow(), window._page_keys.index("profiles"))
        self.assertTrue(profiles._bar.isVisible())
        profiles._bar._no.click()
        self.assertEqual(window.current_page(), "profiles")
        window._nav.setCurrentRow(0)
        profiles._bar._yes.click()  # aceitou descartar: segue para onde queria ir
        self.assertEqual(window.current_page(), "controls")
        self.assertEqual(window._nav.currentRow(), 0)

    def test_back_button_asks_once_then_goes_back(self):
        window = self._window()
        window.show_profiles()
        profiles = window.page("profiles")
        profiles._mark_dirty()
        profiles._back()
        self.assertEqual(window.current_page(), "profiles")
        profiles._bar._yes.click()
        self.assertEqual(window.current_page(), "controls")

    def test_permission_question_uses_the_window_bar(self):
        window = self._window()
        before = set(self._visible_windows())
        with mock.patch.object(type(self.service), "needs_permission", new_callable=mock.PropertyMock, return_value=True), \
                mock.patch.object(window._installer, "start") as start:
            window._offer_permission()
            self.assertTrue(window._bar.isVisible())
            self.assertEqual(set(self._visible_windows()), before)  # sem caixa de diálogo
            window._bar._yes.click()
        start.assert_called_once()
        self.assertFalse(window._bar.isVisible())

    def test_help_opens_inside_the_controls_page(self):
        window = self._window()
        window.show_logs()
        before = set(self._visible_windows())
        window.show_help("steam")
        self.assertEqual(window.current_page(), "controls")
        self.assertEqual(window._help_slots["steam"].count(), 1)
        self.assertEqual(set(self._visible_windows()), before)
        window.show_help("steam")  # abrir de novo não empilha
        self.assertEqual(window._help_slots["steam"].count(), 1)
        window.show_notice("falhou")
        self.assertTrue(window._bar.isVisible())


if __name__ == "__main__":
    unittest.main()
