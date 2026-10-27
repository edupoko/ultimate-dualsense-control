import importlib.util
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "src/dualsense_ultimate_control/icons/controller-outline.svg"
PIECES = (
    "touchpad l1 r1 l2 r2 dpad_up dpad_down dpad_left dpad_right triangle circle cross square "
    "l3 r3 create options ps mute led_1 led_2 led_3 led_4 led_5"
).split()


def _generator():
    spec = importlib.util.spec_from_file_location("controller_outline", ROOT / "scripts/controller_outline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ControllerOutlineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        cls.text = SVG.read_text()
        cls.renderer = QSvgRenderer(str(SVG))

    def test_file_matches_the_generator(self):
        self.assertEqual(self.text, _generator().build())

    def test_app_swaps_the_same_literal_colors(self):
        from dualsense_ultimate_control.testpanel import widgets

        gen = _generator()
        self.assertEqual((widgets._SVG_OUTER, widgets._SVG_INNER, widgets._SVG_BASE), (gen.OUTER, gen.INNER, gen.BASE))
        self.assertEqual((widgets._SVG_W, widgets._SVG_H), (gen.W, gen.H))

    def test_is_small_and_valid(self):
        self.assertLess(SVG.stat().st_size, 16 * 1024)
        self.assertTrue(self.renderer.isValid())
        self.assertEqual(self.renderer.viewBoxF(), QRectF(0, 0, 529, 403))

    def test_every_piece_has_an_id_inside_the_view_box(self):
        box = self.renderer.viewBoxF()
        for name in ("body", *PIECES):
            with self.subTest(name=name):
                self.assertTrue(self.renderer.elementExists(name))
                bounds = self.renderer.boundsOnElement(name)
                self.assertFalse(bounds.isEmpty())
                self.assertTrue(box.contains(bounds))

    def test_pieces_do_not_overlap(self):
        # Pinta cada peça sozinha e procura pixel tocado por duas (os retângulos podem se cruzar, as peças não).
        owner: dict[tuple[int, int], str] = {}
        for name in PIECES:
            image = QImage(529, 403, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            self.renderer.render(painter, name, self.renderer.boundsOnElement(name))
            painter.end()
            box = self.renderer.boundsOnElement(name).toAlignedRect().adjusted(-2, -2, 2, 2)
            for x in range(max(box.left(), 0), min(box.right(), 528) + 1):
                for y in range(max(box.top(), 0), min(box.bottom(), 402) + 1):
                    if image.pixelColor(x, y).alpha() > 128:
                        other = owner.setdefault((x, y), name)
                        self.assertEqual(other, name, f"{name} encosta em {other} em {x},{y}")

    def test_lighting_a_piece_swaps_its_base_color(self):
        gen = _generator()
        self.assertEqual(self.text.count(f'fill="{gen.BASE}"'), len(PIECES))
        lit = QSvgRenderer(QByteArray(self.text.replace(f'fill="{gen.BASE}"', 'fill="#ff0000"').encode()))
        center = self.renderer.boundsOnElement("cross").center()
        for renderer, expected in ((self.renderer, QColor(gen.BASE)), (lit, QColor("#ff0000"))):
            image = QImage(529, 403, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            renderer.render(painter)
            painter.end()
            with self.subTest(color=expected.name()):
                self.assertEqual(image.pixelColor(int(center.x()), int(center.y())), expected)

if __name__ == "__main__":
    unittest.main()
