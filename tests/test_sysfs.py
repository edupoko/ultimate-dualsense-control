import json
import tempfile
import unittest
from pathlib import Path

from dualsense_ultimate_control.settings import AppSettings, LightSettings, load_settings, save_settings
from dualsense_ultimate_control.sysfs import find_controllers


def make_led(root: Path, name: str, device: str, files=("brightness",)) -> Path:
    devices = root / "devices" / device
    devices.mkdir(parents=True, exist_ok=True)
    led = root / "leds" / name
    led.mkdir(parents=True)
    (led / "device").symlink_to(Path("..", "..", "devices", device))
    for file in files:
        (led / file).write_text("0")
    return led


def write_uevent(root: Path, device: str, uniq: str, bus: str) -> None:
    (root / "devices" / device / "uevent").write_text(
        f"DRIVER=playstation\nHID_ID={bus}:0000054C:00000CE6\nHID_UNIQ={uniq}\n"
    )


class FindControllersTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_finds_dualsense_and_player_leds(self):
        rgb = make_led(self.root, "input55:rgb:indicator", "0003:054C:0CE6.000D",
                       ("brightness", "multi_intensity"))
        for n in range(1, 6):
            make_led(self.root, f"input55:white:player-{n}", "0003:054C:0CE6.000D")

        (controller,) = find_controllers(self.root / "leds")

        self.assertEqual(controller.name, "input55")
        self.assertEqual(controller.rgb_dir, rgb)
        self.assertTrue(all(controller.player_dirs))

    def test_reads_address_and_connection_and_sorts_numerically(self):
        make_led(self.root, "input199:rgb:indicator", "0005:054C:0CE6.0002", ("brightness", "multi_intensity"))
        make_led(self.root, "input21:rgb:indicator", "0003:054C:0CE6.0001", ("brightness", "multi_intensity"))
        write_uevent(self.root, "0005:054C:0CE6.0002", "BC:C7:46:32:3C:58", "0005")
        write_uevent(self.root, "0003:054C:0CE6.0001", "14:3a:9a:74:05:eb", "0003")

        controllers = find_controllers(self.root / "leds")

        self.assertEqual([c.name for c in controllers], ["input21", "input199"])
        self.assertEqual([c.connection for c in controllers], ["USB", "Bluetooth"])
        self.assertEqual([c.uid for c in controllers], ["14:3a:9a:74:05:eb", "bc:c7:46:32:3c:58"])

    def test_without_uevent_falls_back_to_led_name(self):
        make_led(self.root, "input55:rgb:indicator", "0003:054C:0CE6.000D", ("brightness", "multi_intensity"))
        (controller,) = find_controllers(self.root / "leds")
        self.assertEqual((controller.uid, controller.connection), ("input55", ""))

    def test_ignores_other_rgb_devices(self):
        make_led(self.root, "input7:rgb:indicator", "0003:046D:C52B.0001",
                 ("brightness", "multi_intensity"))
        self.assertEqual(find_controllers(self.root / "leds"), [])

    def test_missing_root_returns_empty(self):
        self.assertEqual(find_controllers(self.root / "nope"), [])

    def test_writes_color_brightness_and_players(self):
        rgb = make_led(self.root, "input55:rgb:indicator", "0003:054C:0CE6.000D",
                       ("brightness", "multi_intensity"))
        players = [make_led(self.root, f"input55:white:player-{n}", "0003:054C:0CE6.000D")
                   for n in range(1, 6)]
        (controller,) = find_controllers(self.root / "leds")

        controller.set_color(255, 10, 0)
        controller.set_brightness(300)
        controller.set_players([True, False, True, False, False])

        self.assertEqual((rgb / "multi_intensity").read_text(), "255 10 0")
        self.assertEqual((rgb / "brightness").read_text(), "255")
        self.assertEqual([(p / "brightness").read_text() for p in players],
                         ["1", "0", "1", "0", "0"])


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "cfg" / "settings.json"
        self.addCleanup(self._tmp.cleanup)

    def test_round_trip(self):
        settings = AppSettings(
            default=LightSettings((10, 20, 30), 128, [True, False, False, False, True]),
            controllers={"aa:bb": LightSettings((1, 2, 3), 10, [False] * 5)},
            custom_colors=[(1, 2, 3), (4, 5, 6)],
        )
        save_settings(self.path, settings)
        self.assertEqual(load_settings(self.path), settings)

    def test_old_single_controller_file_becomes_the_default(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(
            {"color": [1, 2, 3], "brightness": 10, "players": [False] * 5, "custom_colors": [[9, 9, 9]]}
        ))
        loaded = load_settings(self.path)
        self.assertEqual(loaded.default.color, (1, 2, 3))
        self.assertEqual(loaded.controllers, {})
        self.assertEqual(loaded.custom_colors, [(9, 9, 9)])

    def test_missing_or_invalid_file_gives_defaults(self):
        self.assertEqual(load_settings(self.path), AppSettings())
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"color": "red"}))
        self.assertEqual(load_settings(self.path), AppSettings())


if __name__ == "__main__":
    unittest.main()
