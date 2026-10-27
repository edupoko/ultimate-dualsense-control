import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QLabel

from dualsense_ultimate_control import theme


class ThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        style, palette = self.app.style().objectName(), QPalette(self.app.palette())
        self.addCleanup(lambda: (self.app.setStyle(style), self.app.setPalette(palette)))

    def test_palettes_are_dark_and_light_with_the_given_accent(self):
        accent = QColor("#7b61c9")
        dark, light = theme.build_palette(theme.DARK, accent), theme.build_palette(theme.LIGHT, accent)
        self.assertTrue(theme.is_dark(dark))
        self.assertFalse(theme.is_dark(light))
        self.assertEqual(dark.color(QPalette.ColorRole.Highlight), accent)
        self.assertEqual(light.color(QPalette.ColorRole.Highlight), accent)

    def test_own_theme_is_skipped_with_kde_or_a_manual_style(self):
        self.assertFalse(theme.apply(self.app, kde_active=True))
        with mock.patch.dict(os.environ, {"QT_STYLE_OVERRIDE": "Windows"}):
            self.assertFalse(theme.apply(self.app, kde_active=False))

    def test_own_theme_sets_fusion_and_follows_the_color_scheme(self):
        self.assertTrue(theme.apply(self.app, kde_active=False))
        self.assertEqual(self.app.style().objectName().lower(), "fusion")
        scheme = self.app.styleHints().colorScheme()
        if scheme != theme.Qt.ColorScheme.Unknown:
            self.assertEqual(theme.is_dark(self.app.palette()), scheme == theme.Qt.ColorScheme.Dark)

    def test_sidebar_style_uses_the_palette_accent_and_rounded_items(self):
        palette = theme.build_palette(theme.DARK, QColor("#7b61c9"))
        css = theme.sidebar_qss(palette)
        self.assertIn("SideNav::item:selected { background: #7b61c9", css)
        self.assertIn(f"border-radius: {theme.RADIUS}px", css)

    def test_sidebar_restyles_when_the_palette_changes(self):
        nav = theme.SideNav()
        before = nav.styleSheet()
        self.app.setPalette(theme.build_palette(theme.LIGHT, QColor("#cc3300")))
        self.assertNotEqual(nav.styleSheet(), before)
        self.assertIn("#cc3300", nav.styleSheet())

    def test_every_icon_renders_in_the_requested_color(self):
        for name in theme.ICONS:
            image = theme.render_icon(name, QColor("#ff0000")).toImage()
            colors = {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height()) if image.pixelColor(x, y).alpha() > 200}
            self.assertEqual(colors, {"#ff0000"}, name)

    def test_nav_pages_have_icons_that_follow_the_palette(self):
        nav = theme.SideNav()
        for name in theme.ICONS:
            self.assertFalse(nav.add_page(name).icon().isNull())
        icon_image = lambda: nav.item(0).icon().pixmap(20, 20).toImage()  # noqa: E731
        self.app.setPalette(theme.build_palette(theme.DARK, QColor("#7b61c9")))
        dark = icon_image()
        self.app.setPalette(theme.build_palette(theme.LIGHT, QColor("#7b61c9")))
        self.assertNotEqual(icon_image(), dark)  # o traço troca de cor com o tema
        self.app.setPalette(theme.build_palette(theme.DARK, QColor("#7b61c9")))
        self.assertEqual(icon_image(), dark)

    def test_section_has_a_title_and_a_content_layout(self):
        holder, content = theme.section("window.light")
        content.addWidget(QLabel("x"))
        self.assertEqual(holder.findChildren(QLabel)[0].text(), "Barra de luz")
        self.assertEqual(content.count(), 1)


if __name__ == "__main__":
    unittest.main()
