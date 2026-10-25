import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QLabel

from dualsense_ultimate_control.popup import TrayPopup


class TrayPopupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_toggle_shows_and_hides(self):
        popup = TrayPopup()
        popup.add_item("Sair", lambda: None)
        popup.toggle()
        self.assertTrue(popup.isVisible())
        popup.toggle()
        self.assertFalse(popup.isVisible())

    def test_click_hides_before_running_action(self):
        popup = TrayPopup()
        calls = []
        item = popup.add_item("Sair", lambda: calls.append(popup.isVisible()))
        popup.popup()
        item.clicked.emit()
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()
        self.assertEqual(calls, [False])

    def test_click_on_tray_right_after_close_does_not_reopen(self):
        popup = TrayPopup()
        popup.add_item("Sair", lambda: None)
        popup.popup()
        popup.hide()
        popup.toggle()
        self.assertFalse(popup.isVisible())


    def test_expander_shows_content_without_closing_the_menu(self):
        popup = TrayPopup()
        content = QLabel("conteúdo")
        header = popup.add_expander("Cores rápidas", content)
        popup.add_item("Sair", lambda: None)
        popup.popup()
        self.assertFalse(content.isVisible())

        header.clicked.emit()
        self.assertTrue(content.isVisible())
        self.assertTrue(popup.isVisible())

        header.clicked.emit()
        self.assertFalse(content.isVisible())
        self.assertTrue(popup.isVisible())


if __name__ == "__main__":
    unittest.main()
