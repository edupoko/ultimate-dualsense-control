import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QToolButton

from dualsense_ultimate_control.service import LedService
from dualsense_ultimate_control.settings import load_settings
from dualsense_ultimate_control.widgets import AutoPlayersRow, PlayerRow, ToggleSwitch
from test_sysfs import make_led, write_uevent


def leds(root: Path, name: str) -> str:
    return "".join("x" if (root / "leds" / f"{name}:white:player-{n}" / "brightness").read_text() == "1" else "-" for n in range(1, 6))


class AutoPlayersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.settings_path = self.root / "settings.json"
        self.service = LedService(self.settings_path, self.root / "leds", steam_probe=set, bluetooth_probe=lambda k: [])

    def connect(self, number: int, bus: str = "0003"):
        device = f"{bus}:054C:0CE6.{number:04d}"
        make_led(self.root, f"input{number}:rgb:indicator", device, ("brightness", "multi_intensity"))
        for n in range(1, 6):
            make_led(self.root, f"input{number}:white:player-{n}", device)
        write_uevent(self.root, device, f"aa:00:00:00:00:{number:02d}", bus)

    def disconnect(self, number: int):
        for path in (self.root / "leds").glob(f"input{number}:*"):
            for child in path.iterdir():
                child.unlink()
            path.rmdir()

    def test_one_controller_keeps_its_own_choice(self):
        self.connect(10)
        self.service.refresh()
        self.assertFalse(self.service.players_assigned_automatically)
        self.service.set_players([True, False, False, False, False])
        self.assertEqual(leds(self.root, "input10"), "x----")

    def test_two_controllers_get_player_1_and_2(self):
        self.connect(10)
        self.connect(20, "0005")
        self.service.refresh()
        self.assertTrue(self.service.players_assigned_automatically)
        self.assertEqual(leds(self.root, "input10"), "--x--")   # jogador 1
        self.assertEqual(leds(self.root, "input20"), "-x-x-")   # jogador 2

    def test_third_controller_gets_player_3_and_order_follows_the_tabs(self):
        for number in (10, 20, 30):
            self.connect(number)
        self.service.refresh()
        self.assertEqual([leds(self.root, f"input{n}") for n in (10, 20, 30)], ["--x--", "-x-x-", "x-x-x"])

    def test_assignment_updates_when_a_controller_joins_or_leaves(self):
        self.connect(10)
        self.service.refresh()
        self.service.set_players([True, False, False, False, False])   # escolha manual com um só
        self.connect(20)
        self.service.refresh()
        self.assertEqual(leds(self.root, "input10"), "--x--")
        self.disconnect(10)
        self.service.refresh()
        # Sobrou um só: sai o modo automático e o controle fica com a sua própria configuração
        # (um controle novo começou com a última escolha manual, o jogador "x----").
        self.assertFalse(self.service.players_assigned_automatically)
        self.assertEqual(leds(self.root, "input20"), "x----")

    def test_manual_choice_comes_back_when_only_one_controller_is_left(self):
        self.connect(10)
        self.service.refresh()
        self.service.set_players([True, False, False, False, False])
        self.connect(20)
        self.service.refresh()
        self.disconnect(20)
        self.service.refresh()
        self.assertEqual(leds(self.root, "input10"), "x----")

    def test_turning_the_option_off_restores_manual_choices(self):
        self.connect(10)
        self.connect(20)
        self.service.refresh()
        self.service.set_auto_players(False)
        self.assertFalse(self.service.players_assigned_automatically)
        self.assertEqual(leds(self.root, "input10"), "-----")
        self.assertEqual(leds(self.root, "input20"), "-----")
        self.assertFalse(load_settings(self.settings_path).auto_players)

    def test_player_row_shows_and_locks_the_automatic_number(self):
        row = PlayerRow(self.service)
        buttons = row.findChildren(QToolButton)
        self.connect(10)
        self.connect(20)
        self.service.refresh()
        self.service.select_controller("input20")
        self.assertFalse(row.isEnabled())
        self.assertEqual([b.text() for b in buttons if b.isChecked()], ["2"])
        self.service.set_auto_players(False)
        self.assertTrue(row.isEnabled())

    def test_switch_in_the_window(self):
        row = AutoPlayersRow(self.service)
        switch = row.findChild(ToggleSwitch)
        self.assertTrue(switch.isChecked())
        switch.click()
        self.assertFalse(self.service.auto_players)


if __name__ == "__main__":
    unittest.main()
