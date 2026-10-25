import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QGuiApplication

from PySide6.QtSvg import QSvgRenderer

from dualsense_led import trayicon
from dualsense_led.window import ICON_PATH, app_icon

LINE = QColor(240, 240, 240)


def center_of_bar(image, size):
    # A barra fica à direita; o ponto central dela, na escala do tamanho pedido.
    scale = size / trayicon.GRID
    bar = trayicon._BAR
    return int((bar.x() + bar.width() / 2) * scale), int((bar.y() + bar.height() / 2) * scale)


class TrayIconTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_bar_shows_the_color_scaled_by_brightness(self):
        image = trayicon.render((200, 100, 0), 255, LINE, 64).toImage()
        x, y = center_of_bar(image, 64)
        pixel = image.pixelColor(x, y)
        self.assertEqual((pixel.red(), pixel.green(), pixel.blue()), (200, 100, 0))

        dimmed = trayicon.render((200, 100, 0), 128, LINE, 64).toImage()
        pixel = dimmed.pixelColor(x, y)
        self.assertEqual((pixel.red(), pixel.green(), pixel.blue()), (100, 50, 0))

    def test_bar_is_empty_when_leds_are_off(self):
        image = trayicon.render((200, 100, 0), 0, LINE, 64).toImage()
        x, y = center_of_bar(image, 64)
        self.assertEqual(image.pixelColor(x, y).alpha(), 0)

    def test_controller_is_drawn_with_the_line_color_and_background_is_transparent(self):
        image = trayicon.render((0, 0, 255), 255, LINE, 64).toImage()
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        drawn = [
            image.pixelColor(x, y)
            for x in range(0, 50) for y in range(0, 64)
            if image.pixelColor(x, y).alpha() > 200
        ]
        self.assertTrue(drawn)
        self.assertTrue(all(abs(c.red() - 240) <= 2 for c in drawn))

    def test_icon_has_the_sizes_the_tray_asks_for(self):
        icon = trayicon.tray_icon((0, 0, 255), 255, LINE)
        self.assertEqual({size.width() for size in icon.availableSizes()}, set(trayicon.SIZES))


class AppIconTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_app_icon_is_the_controller_with_the_color_bar(self):
        text = ICON_PATH.read_text()
        self.assertTrue(QSvgRenderer(str(ICON_PATH)).isValid())
        # Mesmo desenho do ícone da bandeja: os traços do controle e a barra de cor com gradiente.
        self.assertIn("M4.40024 5.01929v2.31089", text)
        self.assertIn("linearGradient", text)

    def test_window_icon_loads(self):
        self.assertFalse(app_icon().isNull())


if __name__ == "__main__":
    unittest.main()
