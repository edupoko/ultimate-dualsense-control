import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from dualsense_ultimate_control import bluetooth, i18n
from dualsense_ultimate_control.service import LedService
from dualsense_ultimate_control.tray import TrayIcon
from dualsense_ultimate_control.widgets import DisconnectRow
from test_sysfs import make_led, write_uevent


class DisconnectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.addCleanup(i18n.set_language, "pt")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.service = LedService(self.root / "settings.json", self.root / "leds", steam_probe=set, bluetooth_probe=lambda k: [])
        patcher = mock.patch.object(bluetooth, "disconnect")
        self.disconnect = patcher.start()
        self.addCleanup(patcher.stop)

    def connect(self, number: int, bus: str):
        device = f"{bus}:054C:0CE6.{number:04d}"
        make_led(self.root, f"input{number}:rgb:indicator", device, ("brightness", "multi_intensity"))
        for n in range(1, 6):
            make_led(self.root, f"input{number}:white:player-{n}", device)
        write_uevent(self.root, device, f"bc:c7:46:32:3c:{number:02d}", bus)

    def test_only_a_bluetooth_controller_can_be_disconnected(self):
        self.connect(10, "0003")   # USB
        self.connect(20, "0005")   # Bluetooth
        self.service.refresh()
        self.assertFalse(self.service.can_disconnect)       # selecionado: o USB
        self.service.select_controller("input20")
        self.assertTrue(self.service.can_disconnect)

    def test_disconnect_sends_the_address_of_the_selected_controller(self):
        self.connect(10, "0003")
        self.connect(20, "0005")
        self.service.refresh()
        self.service.select_controller("input20")
        self.service.disconnect_selected()
        self.disconnect.assert_called_once_with("bc:c7:46:32:3c:20")

    def test_usb_or_no_controller_does_nothing(self):
        self.service.disconnect_selected()
        self.connect(10, "0003")
        self.service.refresh()
        self.service.disconnect_selected()
        self.disconnect.assert_not_called()

    def test_window_button_only_shows_for_bluetooth(self):
        self.connect(10, "0003")
        self.connect(20, "0005")
        row = DisconnectRow(self.service)
        self.service.refresh()
        self.assertTrue(row.isHidden())
        self.service.select_controller("input20")
        self.assertFalse(row.isHidden())
        row.findChild(QPushButton).click()
        self.disconnect.assert_called_once_with("bc:c7:46:32:3c:20")

    def test_tray_item_only_shows_for_bluetooth_and_follows_the_language(self):
        self.connect(10, "0003")
        self.connect(20, "0005")
        tray = TrayIcon(self.service, lambda: None, lambda: None)
        tray.popup  # o menu é montado no primeiro uso
        self.service.refresh()
        self.assertTrue(tray._disconnect_item.isHidden())
        self.service.select_controller("input20")
        self.assertFalse(tray._disconnect_item.isHidden())
        self.assertEqual(tray._disconnect_item._text, "Desconectar controle")
        self.service.set_language("en")
        self.assertEqual(tray._disconnect_item._text, "Disconnect controller")
        tray._disconnect_item.clicked.emit()
        self.app.processEvents()


class BluetoothCommandTest(unittest.TestCase):
    def test_runs_bluetoothctl_with_the_address_and_logs_the_result(self):
        process = mock.Mock(returncode=0)
        process.communicate.return_value = ("Attempting to disconnect\nDisconnection successful\n", None)
        with mock.patch.object(subprocess, "Popen", return_value=process) as popen:
            with self.assertLogs("dualsense_ultimate_control.bluetooth", level="INFO") as captured:
                bluetooth.disconnect("bc:c7:46:32:3c:58")
                for thread in __import__("threading").enumerate():
                    if thread is not __import__("threading").current_thread():
                        thread.join(timeout=2)
        self.assertEqual(popen.call_args.args[0], ["bluetoothctl", "disconnect", "bc:c7:46:32:3c:58"])
        self.assertTrue(any("Disconnection successful" in line for line in captured.output))

    def test_missing_bluetoothctl_is_logged_not_raised(self):
        with mock.patch.object(subprocess, "Popen", side_effect=FileNotFoundError("bluetoothctl")):
            with self.assertLogs("dualsense_ultimate_control.bluetooth", level="WARNING"):
                bluetooth.disconnect("bc:c7:46:32:3c:58")


if __name__ == "__main__":
    unittest.main()
