import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSlider, QTabBar, QToolButton

from test_sysfs import make_led, write_uevent

from dualsense_led.service import LedService
from dualsense_led.colors import PRESETS
from dualsense_led.widgets import ColorPalette, ColorSliders, ControllerTabs, PlayerRow, hsv_color, hue_color


class ColorSlidersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.service = LedService(root / "settings.json", root / "leds", bluetooth_probe=lambda known: [])
        self.widget = ColorSliders(self.service)
        # Na ordem em que foram criados: cor (matiz), saturação e brilho.
        self.hue, self.saturation, self.brightness = self.widget.findChildren(QSlider)

    def test_hue_slider_sets_color(self):
        self.hue.setValue(120)
        self.assertEqual(self.service.settings.color, (0, 255, 0))

    def test_brightness_slider_sets_brightness(self):
        self.brightness.setValue(50)
        self.assertEqual(self.service.settings.brightness, 128)

    def test_follows_changes_from_elsewhere(self):
        self.service.set_color((255, 0, 0))
        self.service.set_brightness(64)
        self.assertEqual(self.hue.value(), 0)
        self.assertEqual(self.brightness.value(), 25)

    def test_white_keeps_hue_and_color(self):
        self.hue.setValue(200)
        self.service.set_color((255, 255, 255))
        self.assertEqual(self.hue.value(), 200)
        self.assertEqual(self.service.settings.color, (255, 255, 255))

    def test_starts_from_the_current_color(self):
        self.assertEqual((self.hue.value(), self.saturation.value()), (240, 100))

    def test_saturation_slider_washes_the_color_out(self):
        self.hue.setValue(120)
        self.saturation.setValue(0)
        self.assertEqual(self.service.settings.color, (255, 255, 255))
        self.saturation.setValue(50)
        self.assertEqual(self.service.settings.color, hsv_color(120, 50))

    def test_hue_keeps_the_saturation(self):
        self.saturation.setValue(50)
        self.hue.setValue(0)
        self.assertEqual(self.service.settings.color, hsv_color(0, 50))

    def test_hue_survives_a_white_color(self):
        self.hue.setValue(120)
        self.saturation.setValue(0)
        self.saturation.setValue(100)
        self.assertEqual(self.service.settings.color, (0, 255, 0))

    def test_shows_saturation_of_a_color_set_elsewhere(self):
        self.service.set_color((255, 128, 128))
        self.assertEqual(self.hue.value(), 0)
        self.assertEqual(self.saturation.value(), 50)

    def test_keeps_the_value_of_a_dark_color(self):
        self.service.set_color((0, 128, 128))
        self.hue.setValue(120)
        self.assertEqual(self.service.settings.color, hsv_color(120, 100, 128))

    def test_hue_color_is_saturated(self):
        self.assertEqual(hue_color(0), (255, 0, 0))
        self.assertEqual(hue_color(240), (0, 0, 255))


class ColorPaletteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.service = LedService(root / "settings.json", root / "leds", bluetooth_probe=lambda known: [])
        self.palette = ColorPalette(self.service)

    def names(self):
        return [b.accessibleName() for b in self.palette.findChildren(QToolButton)]

    def test_shows_presets_and_new_color_button(self):
        self.assertEqual(len(self.names()), len(PRESETS) + 1)
        self.assertEqual(self.names()[-1], "Nova cor")

    def test_new_color_appears_in_selector(self):
        self.service.add_custom_color((10, 200, 30))
        self.assertEqual(len(self.names()), len(PRESETS) + 2)
        self.assertIn("#0AC81E", self.names())

    def test_clicking_a_swatch_sets_the_color(self):
        self.service.add_custom_color((10, 200, 30))
        button = next(b for b in self.palette.findChildren(QToolButton) if b.accessibleName() == "Vermelho")
        button.click()
        self.assertEqual(self.service.settings.color, (255, 0, 0))


class PlayerRowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.service = LedService(root / "settings.json", root / "leds", bluetooth_probe=lambda known: [])
        self.row = PlayerRow(self.service)
        self.buttons = self.row.findChildren(QToolButton)

    def leds(self):
        return "".join("x" if on else "-" for on in self.service.settings.players)

    def checked(self):
        return [b.text() for b in self.buttons if b.isChecked()]

    def test_number_lights_the_console_pattern(self):
        expected = {"1": "--x--", "2": "-x-x-", "3": "x-x-x", "4": "xx-xx", "5": "xxxxx"}
        for button in self.buttons:
            button.click()
            self.assertEqual(self.leds(), expected[button.text()])
            self.assertEqual(self.checked(), [button.text()])

    def test_only_one_number_is_selected_at_a_time(self):
        self.buttons[2].click()
        self.buttons[0].click()
        self.assertEqual(self.checked(), ["1"])
        self.assertEqual(self.leds(), "--x--")

    def test_clicking_the_selected_number_turns_leds_off(self):
        self.buttons[3].click()
        self.buttons[3].click()
        self.assertEqual(self.leds(), "-----")
        self.assertEqual(self.checked(), [])


class ControllerTabsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.service = LedService(self.root / "settings.json", self.root / "leds", bluetooth_probe=lambda known: [])
        self.tabs = ControllerTabs(self.service)
        self.bar = self.tabs.findChild(QTabBar)

    def connect(self, number: int, device: str):
        make_led(self.root, f"input{number}:rgb:indicator", device, ("brightness", "multi_intensity"))
        for n in range(1, 6):
            make_led(self.root, f"input{number}:white:player-{n}", device)
        write_uevent(self.root, device, f"aa:00:00:00:00:{number:02d}", "0003" if device.startswith("0003") else "0005")

    def test_hidden_with_zero_or_one_controller(self):
        self.service.refresh()
        self.assertTrue(self.tabs.isHidden())
        self.connect(10, "0003:054C:0CE6.0001")
        self.service.refresh()
        self.assertTrue(self.tabs.isHidden())

    def test_shown_with_one_tab_per_controller_and_selects_on_click(self):
        self.connect(10, "0003:054C:0CE6.0001")
        self.connect(20, "0005:054C:0CE6.0002")
        self.service.refresh()

        self.assertFalse(self.tabs.isHidden())
        self.assertEqual([self.bar.tabText(i) for i in range(self.bar.count())], ["1 · USB", "2 · Bluetooth"])
        self.assertEqual(self.bar.currentIndex(), 0)

        self.bar.setCurrentIndex(1)
        self.assertEqual(self.service.selected, "input20")

    def test_follows_selection_made_elsewhere(self):
        self.connect(10, "0003:054C:0CE6.0001")
        self.connect(20, "0005:054C:0CE6.0002")
        self.service.refresh()
        self.service.select_controller("input20")
        self.assertEqual(self.bar.currentIndex(), 1)


if __name__ == "__main__":
    unittest.main()
