import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

import dualsense_led.__main__ as entry
from dualsense_led.i18n import tr
from dualsense_led.service import LedService
from dualsense_led.tray import TrayIcon
from dualsense_led.window import MainWindow


class CloseButtonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.service = LedService(root / "settings.json", root / "leds", steam_probe=set, bluetooth_probe=lambda k: [])

    def test_close_button_runs_the_full_quit(self):
        quits = []
        window = MainWindow(self.service, tray_available=True, quit_app=lambda: quits.append(True))
        button = next(b for b in window.findChildren(QPushButton) if b.text() == tr("window.close"))
        button.click()
        self.assertEqual(quits, [True])

    def test_x_button_quits_too_when_staying_in_the_tray_is_off(self):
        self.service.set_close_to_tray(False)
        quits = []
        window = MainWindow(self.service, tray_available=True, quit_app=lambda: quits.append(True))
        window.show()
        window.close()
        self.assertEqual(quits, [True])

    def test_x_button_only_hides_when_staying_in_the_tray_is_on(self):
        quits = []
        window = MainWindow(self.service, tray_available=True, quit_app=lambda: quits.append(True))
        window.show()
        window.close()
        self.assertEqual(quits, [])
        self.assertFalse(window.isVisible())

    def test_tray_hide_removes_icon_and_menu(self):
        tray = TrayIcon(self.service, lambda: None, lambda: None)
        tray.popup.popup()
        tray.hide()
        self.assertFalse(tray.popup.isVisible())


class WatchdogTest(unittest.TestCase):
    def test_forces_the_process_to_end_if_cleanup_hangs(self):
        with mock.patch.object(os, "_exit") as force:
            timer = entry._arm_exit_watchdog(7, seconds=0.05)
            timer.join(timeout=2)
        force.assert_called_once_with(7)

    def test_can_be_cancelled_when_cleanup_finishes(self):
        with mock.patch.object(os, "_exit") as force:
            timer = entry._arm_exit_watchdog(0, seconds=0.2)
            timer.cancel()
            timer.join(timeout=1)
        force.assert_not_called()


class QuitCommandTest(unittest.TestCase):
    def test_quit_command_ends_a_running_instance_and_reports_it(self):
        env = dict(
            os.environ,
            DUALSENSE_LED_INSTANCE="dsled-quit-test",
            XDG_RUNTIME_DIR=tempfile.mkdtemp(),
            XDG_CONFIG_HOME=tempfile.mkdtemp(),
            XDG_STATE_HOME=tempfile.mkdtemp(),
            QT_QPA_PLATFORM="offscreen",
        )
        app = subprocess.Popen([sys.executable, "-m", "dualsense_led", "--tray"], env=env, stderr=subprocess.DEVNULL)
        self.addCleanup(app.kill)
        # Espera a instância principal estar de pé (o socket existe).
        socket_file = Path(env["XDG_RUNTIME_DIR"]) / "dsled-quit-test"
        for _ in range(100):
            if socket_file.exists():
                break
            threading.Event().wait(0.1)
        result = subprocess.run(
            [sys.executable, "-m", "dualsense_led", "--quit"], env=env, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("encerrado", result.stdout)
        self.assertEqual(app.wait(timeout=15), 0)

    def test_quit_without_a_running_instance_says_so(self):
        env = dict(os.environ, DUALSENSE_LED_INSTANCE="dsled-quit-none", XDG_RUNTIME_DIR=tempfile.mkdtemp(),
                   XDG_STATE_HOME=tempfile.mkdtemp(), QT_QPA_PLATFORM="offscreen")
        result = subprocess.run(
            [sys.executable, "-m", "dualsense_led", "--quit"], env=env, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("não está aberto", result.stdout)


if __name__ == "__main__":
    unittest.main()
