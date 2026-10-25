import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dualsense_ultimate_control.colors import MAX_CUSTOM_COLORS
from dualsense_ultimate_control.service import LedService
from dualsense_ultimate_control.settings import load_settings
from test_sysfs import make_led, write_uevent

DEVICE = "0003:054C:0CE6.000D"


class LedServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.rgb = make_led(self.root, "input55:rgb:indicator", DEVICE, ("brightness", "multi_intensity"))
        self.players = [make_led(self.root, f"input55:white:player-{n}", DEVICE) for n in range(1, 6)]
        self.settings_path = self.root / "cfg" / "settings.json"
        self.service = LedService(self.settings_path, self.root / "leds", bluetooth_probe=lambda known: [])

    def test_applies_saved_settings_on_connect(self):
        self.service.refresh()
        self.assertEqual((self.rgb / "multi_intensity").read_text(), "0 0 255")
        self.assertEqual(self.service.status, "DualSense conectado")

    def test_changes_are_applied_and_saved(self):
        self.service.refresh()
        self.service.set_color((255, 0, 0))
        self.service.set_brightness(128)
        self.service.set_players([False, True, False, True, False])

        self.assertEqual((self.rgb / "multi_intensity").read_text(), "255 0 0")
        self.assertEqual((self.rgb / "brightness").read_text(), "128")
        self.assertEqual([(p / "brightness").read_text() for p in self.players], ["0", "1", "0", "1", "0"])
        saved = load_settings(self.settings_path)
        self.assertEqual((saved.default.color, saved.default.brightness), ((255, 0, 0), 128))

    def test_reports_missing_permission(self):
        (self.rgb / "multi_intensity").chmod(0o444)
        self.service.refresh()
        self.assertIn("permissão", self.service.status)
        self.assertTrue(self.service.needs_permission)

        (self.rgb / "multi_intensity").chmod(0o644)
        self.service.retry()
        self.assertFalse(self.service.needs_permission)
        self.assertEqual(self.service.status, "DualSense conectado")

    def test_new_color_is_applied_saved_and_listed_once(self):
        self.service.refresh()
        self.service.add_custom_color((10, 200, 30))
        self.service.add_custom_color((10, 200, 30))
        self.service.add_custom_color((255, 0, 0))  # igual a uma cor pronta: não duplica

        self.assertEqual(self.service.custom_colors, [(10, 200, 30)])
        self.assertEqual(self.service.settings.color, (255, 0, 0))
        self.assertEqual(load_settings(self.settings_path).custom_colors, [(10, 200, 30)])

    def test_oldest_custom_colors_are_dropped(self):
        for n in range(MAX_CUSTOM_COLORS + 3):
            self.service.add_custom_color((1, 2, n + 10))
        custom = self.service.custom_colors
        self.assertEqual(len(custom), MAX_CUSTOM_COLORS)
        self.assertEqual(custom[0], (1, 2, 13))

    def add_second_controller(self):
        device = "0005:054C:0CE6.0002"
        self.rgb2 = make_led(self.root, "input60:rgb:indicator", device, ("brightness", "multi_intensity"))
        self.players2 = [make_led(self.root, f"input60:white:player-{n}", device) for n in range(1, 6)]
        write_uevent(self.root, DEVICE, "aa:aa:aa:aa:aa:01", "0003")
        write_uevent(self.root, device, "bb:bb:bb:bb:bb:02", "0005")

    def test_changes_only_affect_the_selected_controller(self):
        self.add_second_controller()
        self.service.refresh()
        self.assertEqual(self.service.selected, "input55")

        self.service.set_color((255, 0, 0))
        self.service.select_controller("input60")
        self.service.set_color((0, 255, 0))
        self.service.flush()  # o Bluetooth recebe as escritas com um pequeno atraso

        self.assertEqual((self.rgb / "multi_intensity").read_text(), "255 0 0")
        self.assertEqual((self.rgb2 / "multi_intensity").read_text(), "0 255 0")

    def test_each_controller_keeps_its_own_state_in_the_ui(self):
        self.add_second_controller()
        self.service.refresh()
        self.service.set_players([True] * 5)
        self.service.select_controller("input60")
        self.assertEqual(self.service.settings.players, [False] * 5)
        self.service.select_controller("input55")
        self.assertEqual(self.service.settings.players, [True] * 5)

    def test_state_is_saved_per_controller_address(self):
        self.add_second_controller()
        self.service.refresh()
        self.service.set_color((255, 0, 0))
        self.service.select_controller("input60")
        self.service.set_color((0, 0, 255))

        saved = load_settings(self.settings_path)
        self.assertEqual(saved.controllers["aa:aa:aa:aa:aa:01"].color, (255, 0, 0))
        self.assertEqual(saved.controllers["bb:bb:bb:bb:bb:02"].color, (0, 0, 255))

    def test_signals_when_controllers_or_selection_change(self):
        events = []
        self.service.controllers_changed.connect(lambda: events.append("controllers"))
        self.service.refresh()
        self.add_second_controller()
        self.service.refresh()
        self.service.select_controller("input60")
        self.assertEqual(events, ["controllers", "controllers", "controllers"])

    def test_selection_moves_when_the_selected_controller_disconnects(self):
        self.add_second_controller()
        self.service.refresh()
        self.service.select_controller("input60")
        for path in (self.root / "leds").glob("input60:*"):
            for child in path.iterdir():
                child.unlink() if not child.is_symlink() else child.unlink()
            path.rmdir()
        self.service.refresh()
        self.assertEqual(self.service.selected, "input55")

    def test_detects_steam_and_reapplies_when_it_lets_go(self):
        held = {"/dev/hidraw7"}
        (self.root / "devices" / DEVICE / "hidraw" / "hidraw7").mkdir(parents=True)
        service = LedService(self.settings_path, self.root / "leds", steam_probe=lambda: set(held), bluetooth_probe=lambda known: [])
        events = []
        service.steam_changed.connect(lambda: events.append("steam"))

        service.refresh()
        self.assertTrue(service.steam_controls_selected)

        # A Steam muda a cor por conta própria; ao soltar o controle, o app reaplica a dele.
        (self.rgb / "multi_intensity").write_text("1 2 3")
        held.clear()
        service.refresh()
        self.assertFalse(service.steam_controls_selected)
        self.assertEqual((self.rgb / "multi_intensity").read_text(), "0 0 255")
        self.assertEqual(events, ["steam", "steam"])

    def test_reapply_sends_saved_state_again(self):
        self.service.refresh()
        (self.rgb / "multi_intensity").write_text("1 2 3")
        self.service.reapply_selected()
        self.assertEqual((self.rgb / "multi_intensity").read_text(), "0 0 255")

    def test_no_controller(self):
        service = LedService(self.settings_path, self.root / "vazio", bluetooth_probe=lambda known: [])
        service.refresh()
        self.assertEqual(service.status, "Nenhum DualSense conectado")


if __name__ == "__main__":
    unittest.main()
