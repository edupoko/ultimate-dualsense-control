import os
import re
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton

from dualsense_ultimate_control import i18n
from dualsense_ultimate_control.colors import PRESETS
from dualsense_ultimate_control.service import LedService
from dualsense_ultimate_control.settings import load_settings
from dualsense_ultimate_control.translations import STRINGS
from dualsense_ultimate_control.tray import TrayIcon
from dualsense_ultimate_control.widgets import LanguageRow
from dualsense_ultimate_control.window import MainWindow

SOURCE = Path(__file__).resolve().parent.parent / "src" / "dualsense_ultimate_control"


class CatalogTest(unittest.TestCase):
    def test_every_text_exists_in_all_languages(self):
        for key, entry in STRINGS.items():
            self.assertEqual(set(entry), set(i18n.LANGUAGES), key)
            self.assertTrue(all(text.strip() for text in entry.values()), key)

    def test_placeholders_match_across_languages(self):
        for key, entry in STRINGS.items():
            fields = {code: set(re.findall(r"{(\w+)}", text)) for code, text in entry.items()}
            self.assertEqual(len({frozenset(f) for f in fields.values()}), 1, f"{key}: {fields}")

    def test_every_key_used_in_the_code_exists(self):
        used = set()
        for path in SOURCE.glob("*.py"):
            if path.name == "translations.py":
                continue
            text = path.read_text()
            used |= set(re.findall(r'\btr\(\s*f?"([a-z_]+\.[a-z_.{}]+)"', text))
            used |= set(re.findall(r'bind\([^,]+,\s*"([a-z_]+\.[a-z_]+)"', text))
            used |= set(re.findall(r'_bound_label\(\s*"([a-z_]+\.[a-z_]+)"', text))
            used |= set(re.findall(r'_labeled_row\(\s*"([a-z_]+\.[a-z_]+)"', text))
            used |= set(re.findall(r'"((?:row|status)\.[a-z_]+)"', text))
        used = {key for key in used if "{" not in key}
        self.assertEqual({key for key in used if key not in STRINGS}, set())
        for color_id in PRESETS:
            self.assertIn(f"color.{color_id}", STRINGS)

    def test_unknown_key_returns_the_key_itself(self):
        self.assertEqual(i18n.tr("nao.existe"), "nao.existe")


class LanguageSwitchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.addCleanup(i18n.set_language, "pt")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.settings_path = self.root / "settings.json"
        self.service = LedService(self.settings_path, self.root / "leds", steam_probe=set, bluetooth_probe=lambda k: [])

    def texts(self, widget):
        return {w.text() for w in widget.findChildren(QLabel)} | {w.text() for w in widget.findChildren(QPushButton)}

    def test_default_is_portuguese(self):
        self.assertEqual(i18n.language(), "pt")
        self.assertEqual(self.service.status, "Procurando DualSense…")
        self.service.refresh()
        self.assertEqual(self.service.status, "Nenhum DualSense conectado")

    def test_status_follows_the_language(self):
        self.service.refresh()
        seen = []
        self.service.status_changed.connect(seen.append)
        self.service.set_language("en")
        self.assertEqual(self.service.status, "No DualSense connected")
        self.service.set_language("es")
        self.assertEqual(self.service.status, "Ningún DualSense conectado")
        self.assertEqual(seen, ["No DualSense connected", "Ningún DualSense conectado"])

    def test_window_texts_change_live(self):
        window = MainWindow(self.service, tray_available=True)
        self.assertIn("Brilho", self.texts(window))
        self.service.set_language("en")
        self.assertIn("Brightness", self.texts(window))
        self.assertNotIn("Brilho", self.texts(window))
        self.assertIn("Close", self.texts(window))
        self.service.set_language("es")
        self.assertIn("Brillo", self.texts(window))
        self.assertIn("Cerrar", self.texts(window))
        self.service.set_language("pt")
        self.assertIn("Fechar", self.texts(window))

    def test_tray_menu_changes_live(self):
        tray = TrayIcon(self.service, lambda: None, lambda: None)
        labels = lambda: {w.text() for w in tray.popup.findChildren(QLabel)}
        self.service.set_language("en")
        self.assertIn("Brightness", labels())
        items = {item._text for item in tray.popup.findChildren(type(tray._status))}
        self.assertIn("Quit", items)
        self.assertIn("Expand", items)

    def test_color_names_are_translated(self):
        from PySide6.QtWidgets import QToolButton
        from dualsense_ultimate_control.widgets import ColorPalette
        palette = ColorPalette(self.service)
        names = lambda: {b.accessibleName() for b in palette.findChildren(QToolButton)}
        self.assertIn("Vermelho", names())
        self.service.set_language("en")
        self.assertIn("Red", names())
        self.service.set_language("es")
        self.assertIn("Rojo", names())

    def test_selector_lists_the_three_languages_and_applies_the_choice(self):
        row = LanguageRow(self.service)
        combo = row.findChild(QComboBox)
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], ["Português", "English", "Español"])
        combo.setCurrentIndex(combo.findData("es"))
        self.assertEqual(i18n.language(), "es")
        self.assertEqual(self.service.language, "es")

    def test_selector_follows_a_change_made_elsewhere(self):
        row = LanguageRow(self.service)
        combo = row.findChild(QComboBox)
        self.service.set_language("en")
        self.assertEqual(combo.currentData(), "en")

    def test_choice_is_saved_and_restored_on_start(self):
        self.service.set_language("es")
        self.assertEqual(load_settings(self.settings_path).language, "es")
        i18n.set_language("pt")
        again = LedService(self.settings_path, self.root / "leds", steam_probe=set, bluetooth_probe=lambda k: [])
        self.assertEqual(i18n.language(), "es")
        self.assertEqual(again.status, "Buscando DualSense…")

    def test_invalid_language_is_ignored(self):
        self.service.set_language("xx")
        self.assertEqual(i18n.language(), "pt")

    def test_deleted_widgets_do_not_break_a_language_change(self):
        import shiboken6
        label = QLabel()
        i18n.bind(label.setText, "window.close")
        shiboken6.delete(label)
        i18n.set_language("en")  # não deve levantar erro


if __name__ == "__main__":
    unittest.main()
