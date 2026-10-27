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

    def test_is_small_and_valid(self):
        self.assertLess(SVG.stat().st_size, 16 * 1024)
        self.assertTrue(self.renderer.isValid())
        self.assertEqual(self.renderer.viewBoxF(), QRectF(0, 0, 589, 414))

    def test_every_piece_has_an_id_inside_the_view_box(self):
        box = self.renderer.viewBoxF()
        for name in ("body", *PIECES):
            with self.subTest(name=name):
                self.assertTrue(self.renderer.elementExists(name))
                bounds = self.renderer.boundsOnElement(name)
                self.assertFalse(bounds.isEmpty())
                self.assertTrue(box.contains(bounds))

    def test_pieces_do_not_overlap(self):
        bounds = {name: self.renderer.boundsOnElement(name) for name in PIECES}
        for i, a in enumerate(PIECES):
            for b in PIECES[i + 1 :]:
                if a.startswith("dpad_") and b.startswith("dpad_"):
                    continue  # as pontas se encaixam no centro: os retângulos se cruzam, as teclas não
                with self.subTest(a=a, b=b):
                    self.assertFalse(bounds[a].intersects(bounds[b]))

    def test_pieces_are_transparent_until_lit(self):
        gen = _generator()
        self.assertEqual(self.text.count('fill-opacity="0"'), len(PIECES))
        lit = QSvgRenderer(QByteArray(self.text.replace('fill-opacity="0"', 'fill-opacity="1"').encode()))
        center = self.renderer.boundsOnElement("cross").center()
        for renderer, expected in ((self.renderer, False), (lit, True)):
            image = QImage(589, 414, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            renderer.render(painter)
            painter.end()
            # Entre o centro do botão e o símbolo ✕ há um ponto só de preenchimento.
            color = image.pixelColor(int(center.x()), int(center.y() - 9))
            with self.subTest(lit=expected):
                self.assertEqual(color == QColor(gen.FILL), expected)


if __name__ == "__main__":
    unittest.main()
