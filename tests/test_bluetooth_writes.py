import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from dualsense_led import service as service_module
from dualsense_led.service import BLUETOOTH_WRITE_INTERVAL_MS, LedService
from dualsense_led.sysfs import Controller
from test_sysfs import make_led, write_uevent


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class WriteTrafficTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.counts = {"color": 0, "brightness": 0, "players": 0}
        for name, key in (("set_color", "color"), ("set_brightness", "brightness"), ("set_players", "players")):
            original = getattr(Controller, name)
            patcher = mock.patch.object(Controller, name, self._counting(key, original))
            patcher.start()
            self.addCleanup(patcher.stop)

    def _counting(self, key, original):
        def inner(controller, *args, **kwargs):
            self.counts[key] += 1
            return original(controller, *args, **kwargs)
        return inner

    def controller(self, bus: str) -> LedService:
        device = f"{bus}:054C:0CE6.0001"
        make_led(self.root, "input5:rgb:indicator", device, ("brightness", "multi_intensity"))
        for n in range(1, 6):
            make_led(self.root, f"input5:white:player-{n}", device)
        write_uevent(self.root, device, "aa:bb:cc:dd:ee:01", bus)
        service = LedService(self.root / "settings.json", self.root / "leds", steam_probe=set, bluetooth_probe=lambda k: [])
        service.refresh()
        wait(BLUETOOTH_WRITE_INTERVAL_MS + 60)
        self.counts.update(color=0, brightness=0, players=0)
        return service

    def test_changing_the_color_only_writes_the_color(self):
        service = self.controller("0003")  # USB: sem espera
        service.set_color((255, 0, 0))
        self.assertEqual(self.counts, {"color": 1, "brightness": 0, "players": 0})
        service.set_brightness(100)
        self.assertEqual(self.counts, {"color": 1, "brightness": 1, "players": 0})

    def test_writing_the_same_value_again_sends_nothing(self):
        service = self.controller("0003")
        service.set_color((255, 0, 0))
        service.set_color((255, 0, 0))
        self.assertEqual(self.counts["color"], 1)

    def test_slider_burst_on_bluetooth_is_collapsed_and_ends_on_the_last_value(self):
        service = self.controller("0005")
        for step in range(50):
            service.set_color((step * 5, 0, 255 - step * 5))
        wait(BLUETOOTH_WRITE_INTERVAL_MS * 3)
        # 50 passos, mas só duas escritas de cor: a primeira (canal livre) e a última (valor final).
        self.assertLessEqual(self.counts["color"], 3)
        self.assertEqual(self.counts["brightness"], 0)
        self.assertEqual(self.counts["players"], 0)
        self.assertEqual((self.root / "leds" / "input5:rgb:indicator" / "multi_intensity").read_text(), "245 0 10")

    def test_bluetooth_writes_are_spaced_by_the_interval(self):
        service = self.controller("0005")
        service.set_color((1, 0, 0))     # canal livre: escreve já
        service.set_color((2, 0, 0))     # canal ocupado: espera
        self.assertEqual(self.counts["color"], 1)
        wait(BLUETOOTH_WRITE_INTERVAL_MS + 80)
        self.assertEqual(self.counts["color"], 2)

    def test_flush_writes_what_is_waiting(self):
        service = self.controller("0005")
        service.set_color((1, 0, 0))
        service.set_color((9, 9, 9))
        service.flush()
        self.assertEqual((self.root / "leds" / "input5:rgb:indicator" / "multi_intensity").read_text(), "9 9 9")

    def test_usb_is_never_delayed(self):
        service = self.controller("0003")
        for step in range(5):
            service.set_color((step + 1, 0, 0))
        self.assertEqual(self.counts["color"], 5)

    def test_reapply_after_steam_rewrites_everything(self):
        service = self.controller("0003")
        service.reapply_selected()
        self.assertEqual(self.counts, {"color": 1, "brightness": 1, "players": 1})


if __name__ == "__main__":
    unittest.main()
