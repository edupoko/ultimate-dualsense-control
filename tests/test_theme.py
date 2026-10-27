import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QLabel

from dualsense_ultimate_control import theme


class DetectTest(unittest.TestCase):
    def test_desktop_picks_the_theme(self):
        cases = {
            "KDE": "kde", "GNOME": "gnome", "ubuntu:GNOME": "gnome", "GNOME-Classic:GNOME": "gnome",
            "X-Cinnamon": "own", "XFCE": "own", "": "own",
        }
        for desktop, expected in cases.items():
            self.assertEqual(theme.detect({"XDG_CURRENT_DESKTOP": desktop}), expected, desktop)

    def test_desktop_session_is_used_without_xdg_current_desktop(self):
        self.assertEqual(theme.detect({"DESKTOP_SESSION": "gnome-xorg"}), "gnome")
        self.assertEqual(theme.detect({"DESKTOP_SESSION": "plasma"}), "kde")

    def test_the_variable_forces_a_theme_over_the_desktop(self):
        for forced in ("kde", "gnome", "own", "GNOME"):
            env = {"XDG_CURRENT_DESKTOP": "KDE", theme.THEME_ENV: forced}
            self.assertEqual(theme.detect(env), forced.lower())

    def test_auto_and_unknown_values_fall_back_to_the_desktop(self):
        for value in ("auto", "", "xyz"):
            self.assertEqual(theme.detect({"XDG_CURRENT_DESKTOP": "GNOME", theme.THEME_ENV: value}), "gnome")

    def test_the_old_opt_out_means_own_unless_a_theme_is_forced(self):
        self.assertEqual(theme.detect({"XDG_CURRENT_DESKTOP": "KDE", theme.LEGACY_OWN_ENV: "1"}), "own")
        self.assertEqual(theme.detect({"XDG_CURRENT_DESKTOP": "GNOME", theme.LEGACY_OWN_ENV: "1"}), "own")
        self.assertEqual(theme.detect({theme.LEGACY_OWN_ENV: "1", theme.THEME_ENV: "gnome"}), "gnome")

    def test_saved_preference_beats_the_desktop_but_not_the_variables(self):
        env = {"XDG_CURRENT_DESKTOP": "KDE"}
        self.assertEqual(theme.detect(env, preference="gnome"), "gnome")
        self.assertEqual(theme.detect(env, preference="auto"), "kde")
        self.assertEqual(theme.detect(env, preference="lixo"), "kde")
        self.assertEqual(theme.detect({**env, theme.THEME_ENV: "own"}, preference="gnome"), "own")
        self.assertEqual(theme.detect({**env, theme.LEGACY_OWN_ENV: "1"}, preference="gnome"), "own")

    def test_reads_the_process_environment_by_default(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}, clear=True):
            self.assertEqual(theme.detect(), "gnome")


class ThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        style, palette = self.app.style().objectName(), QPalette(self.app.palette())
        self.addCleanup(lambda: (self.app.setStyle(style), self.app.setPalette(palette), setattr(theme, "_style", "own")))

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

    def test_switch_colors_follow_the_dark_and_light_themes(self):
        dark = theme.switch_colors(theme.build_palette(theme.DARK, QColor("#7b61c9")))
        light = theme.switch_colors(theme.build_palette(theme.LIGHT, QColor("#7b61c9")))
        self.assertLess(dark.off_track.lightness(), 100)  # trilho escuro, não o branco do tema claro
        self.assertNotEqual(dark.off_knob.name(), "#ffffff")
        self.assertEqual(light.off_knob.name(), "#ffffff")
        self.assertEqual(light.off_outline.alpha(), 0)


class GnomeThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        style, palette = self.app.style().objectName(), QPalette(self.app.palette())
        self.addCleanup(lambda: (self.app.setStyle(style), self.app.setPalette(palette), setattr(theme, "_style", "own")))
        self.blue = QColor(theme.ADW_ACCENT)

    def test_adwaita_palettes_follow_the_libadwaita_tones(self):
        light = theme.build_palette(theme.ADW_LIGHT, self.blue)
        dark = theme.build_palette(theme.ADW_DARK, self.blue)
        self.assertEqual(light.color(QPalette.ColorRole.Window).name(), "#fafafa")
        self.assertEqual(light.color(QPalette.ColorRole.Base).name(), "#ffffff")
        self.assertEqual(dark.color(QPalette.ColorRole.Window).name(), "#242424")
        self.assertEqual(dark.color(QPalette.ColorRole.Base).name(), "#1e1e1e")
        self.assertFalse(theme.is_dark(light))
        self.assertTrue(theme.is_dark(dark))
        self.assertEqual(dark.color(QPalette.ColorRole.Link), self.blue.lighter(130))

    def test_apply_with_gnome_uses_fusion_and_the_adwaita_tones(self):
        with mock.patch.object(theme, "accent_color", return_value=self.blue):
            self.assertTrue(theme.apply(self.app, kde_active=False, name="gnome"))
        self.assertEqual(theme.style(), "gnome")
        self.assertEqual(self.app.style().objectName().lower(), "fusion")
        window = self.app.palette().color(QPalette.ColorRole.Window).name()
        self.assertIn(window, (theme.ADW_LIGHT.window, theme.ADW_DARK.window))
        self.assertEqual(self.app.palette().color(QPalette.ColorRole.Highlight), self.blue)

    def test_the_accent_falls_back_to_the_gnome_blue(self):
        hints = self.app.styleHints()
        with mock.patch.object(type(hints), "accentColor", create=True, return_value=QColor()):
            self.assertEqual(theme.accent_color(self.app, theme.ADW_ACCENT).name(), theme.ADW_ACCENT)

    def test_own_and_kde_do_not_switch_to_the_gnome_visual(self):
        with mock.patch.object(theme, "accent_color", return_value=self.blue):
            theme.apply(self.app, kde_active=False, name="gnome")
            self.assertEqual(theme.style(), "gnome")
            self.assertTrue(theme.apply(self.app, kde_active=False, name="own"))
            self.assertEqual(theme.style(), "own")
            theme.apply(self.app, kde_active=False, name="gnome")
            self.assertFalse(theme.apply(self.app, kde_active=True, name="gnome"))
            self.assertEqual(theme.style(), "own")

    def test_sidebar_selection_is_a_soft_tint_of_the_text_not_the_accent(self):
        for tokens in (theme.ADW_LIGHT, theme.ADW_DARK):
            palette = theme.build_palette(tokens, self.blue)
            css = theme.sidebar_qss(palette, "gnome")
            self.assertIn(f"border-radius: {theme.ADW_RADIUS}px", css)
            selected = css.split("SideNav::item:selected")[1]
            self.assertNotIn(self.blue.name(), selected)
            self.assertIn(f"color: {tokens.text}", selected)
            self.assertIn("rgba(", selected)
            self.assertIn("rgba(", css.split("SideNav::item:hover")[1])

    def test_default_sidebar_style_is_unchanged_without_the_gnome_visual(self):
        palette = theme.build_palette(theme.DARK, QColor("#7b61c9"))
        self.assertEqual(theme.sidebar_qss(palette), theme.sidebar_qss(palette, "own"))
        self.assertIn(f"border-radius: {theme.RADIUS}px", theme.sidebar_qss(palette))

    def test_selected_icon_keeps_the_normal_color_in_the_gnome_visual(self):
        palette = theme.build_palette(theme.ADW_DARK, self.blue)
        def selected_pixels(visual):
            image = theme.nav_icon("logs", palette, visual=visual).pixmap(20, 20, theme.QIcon.Mode.Selected).toImage()
            return {image.pixelColor(x, y).name() for x in range(20) for y in range(20) if image.pixelColor(x, y).alpha() > 200}
        self.assertEqual(selected_pixels("gnome"), {palette.color(QPalette.ColorRole.WindowText).name()})
        self.assertEqual(selected_pixels("own"), {palette.color(QPalette.ColorRole.HighlightedText).name()})

    def test_switch_colors_in_the_gnome_visual(self):
        for tokens in (theme.ADW_LIGHT, theme.ADW_DARK):
            colors = theme.switch_colors(theme.build_palette(tokens, self.blue), "gnome")
            self.assertEqual(colors.off_knob.name(), "#ffffff")
            self.assertEqual(colors.on_knob.name(), "#ffffff")
            self.assertEqual(colors.off_outline.alpha(), 0)
            self.assertLess(colors.off_track.alpha(), 80)  # trilho translúcido, sem contorno
        light = theme.switch_colors(theme.build_palette(theme.LIGHT, self.blue))
        self.assertEqual(light, theme.switch_colors(theme.build_palette(theme.LIGHT, self.blue), "own"))

    def test_switch_widget_uses_the_gnome_colors_once_applied(self):
        from dualsense_ultimate_control.widgets import ToggleSwitch
        with mock.patch.object(theme, "accent_color", return_value=self.blue):
            theme.apply(self.app, kde_active=False, name="gnome")
        switch = ToggleSwitch()
        switch.setChecked(True)
        switch.resize(switch.sizeHint())
        image = switch.grab().toImage()
        self.assertEqual(image.pixelColor(image.width() // 4, image.height() // 2).name(), self.app.palette().highlight().color().name())

    def test_main_window_renders_with_the_gnome_visual_in_both_schemes(self):
        import tempfile
        from pathlib import Path
        from dualsense_ultimate_control.service import LedService
        from dualsense_ultimate_control.window import MainWindow
        with mock.patch.object(theme, "accent_color", return_value=self.blue):
            theme.apply(self.app, kde_active=False, name="gnome")
        with tempfile.TemporaryDirectory() as tmp:
            service = LedService(Path(tmp) / "settings.json", Path(tmp) / "leds", bluetooth_probe=lambda known: [])
            window = MainWindow(service, tray_available=False, emulation=None)
            self.addCleanup(window.deleteLater)
            window.show()
            for tokens in (theme.ADW_LIGHT, theme.ADW_DARK):
                self.app.setPalette(theme.build_palette(tokens, self.blue))
                self.assertFalse(window.grab().isNull())
                nav = window.findChildren(theme.SideNav)[0]
                self.assertIn(f"border-radius: {theme.ADW_RADIUS}px", nav.styleSheet())


if __name__ == "__main__":
    unittest.main()
