"""Widgets desenhados da tela de teste: controle, sticks, touchpad e gráfico do IMU."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..ds5.reports import TOUCHPAD_HEIGHT, TOUCHPAD_WIDTH, InputState
from .model import ImuHistory, RangeTracker, stick_point

AXIS_COLORS = (QColor("#e5484d"), QColor("#30a46c"), QColor("#3e63dd"))
_FACE = {"square": "□", "cross": "✕", "circle": "○", "triangle": "△"}


class _Canvas(QWidget):
    """Base que prepara o pintor e as cores da paleta."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.draw(painter)

    def draw(self, painter: QPainter) -> None:
        raise NotImplementedError

    def _colors(self):
        palette = self.palette()
        return palette.color(palette.ColorRole.Mid), palette.color(palette.ColorRole.Highlight), palette.color(palette.ColorRole.Text)


class ControllerView(_Canvas):
    """Contorno do controle com botões, direcional e ombros acesos conforme o estado."""

    # (nome, x, y) num desenho de 400 × 240
    _FACE_POS = {"triangle": (320, 70), "circle": (350, 100), "cross": (320, 130), "square": (290, 100)}
    _SMALL = {"create": (150, 70), "options": (250, 70), "mute": (200, 130), "ps": (200, 100)}

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.state: InputState | None = None
        self.setMinimumSize(300, 190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_state(self, state: InputState | None) -> None:
        self.state = state
        self.update()

    def draw(self, p: QPainter) -> None:
        mid, active, text = self._colors()
        scale = min(self.width() / 400, self.height() / 240)
        p.translate((self.width() - 400 * scale) / 2, (self.height() - 240 * scale) / 2)
        p.scale(scale, scale)
        pressed = self.state.buttons if self.state else frozenset()
        outline = QPen(mid, 2)

        p.setPen(outline)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(30, 45, 340, 170), 60, 60)

        # Ombros L1/R1 e gatilhos L2/R2 (preenchidos pelo valor analógico).
        for name, x in (("l1", 50), ("r1", 270)):
            p.setBrush(active if name in pressed else Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(x, 25, 80, 14), 6, 6)
        for name, x, value in (("l2", 50, self.state.l2 if self.state else 0), ("r2", 270, self.state.r2 if self.state else 0)):
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(x, 4, 80, 16), 6, 6)
            fill = QColor(active)
            p.setBrush(fill)
            p.drawRoundedRect(QRectF(x, 4, 80 * value / 255, 16), 6, 6)

        # Direcional.
        dpad = self.state.dpad if self.state else None
        arrows = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
        for name, (dx, dy) in arrows.items():
            lit = dpad is not None and name in dpad
            p.setBrush(active if lit else Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(88 + dx * 24 - 10, 100 + dy * 24 - 10, 20, 20), 4, 4)

        # Botões de rosto.
        font = QFont(p.font())
        font.setPointSize(11)
        p.setFont(font)
        for name, (x, y) in self._FACE_POS.items():
            lit = name in pressed
            p.setBrush(active if lit else Qt.BrushStyle.NoBrush)
            p.setPen(outline)
            p.drawEllipse(QPointF(x, y), 15, 15)
            p.setPen(QPen(self.palette().highlightedText().color() if lit else text))
            p.drawText(QRectF(x - 15, y - 15, 30, 30), Qt.AlignmentFlag.AlignCenter, _FACE[name])

        # Create, Options, PS e Mute.
        p.setPen(outline)
        for name, (x, y) in self._SMALL.items():
            p.setBrush(active if name in pressed else Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(x, y), 7, 7) if name in ("ps", "mute") else p.drawRoundedRect(QRectF(x - 6, y - 10, 12, 20), 4, 4)

        # Touchpad (clique) com os dedos.
        p.setBrush(active if "touchpad" in pressed else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(160, 50, 80, 36), 6, 6)
        if self.state:
            p.setBrush(active)
            for touch in self.state.touches:
                if touch is not None:
                    p.drawEllipse(QPointF(160 + 80 * touch.x / TOUCHPAD_WIDTH, 50 + 36 * touch.y / TOUCHPAD_HEIGHT), 4, 4)

        # Sticks (L3/R3 acendem o círculo).
        for name, cx, (x, y) in (
            ("l3", 140, (self.state.lx, self.state.ly) if self.state else (128, 128)),
            ("r3", 260, (self.state.rx, self.state.ry) if self.state else (128, 128)),
        ):
            p.setPen(outline)
            p.setBrush(active if name in pressed else Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, 170), 24, 24)
            px, py = stick_point(x, y)
            p.setBrush(text)
            p.drawEllipse(QPointF(cx + px * 16, 170 - py * 16), 6, 6)


class StickView(_Canvas):
    """Um analógico: círculo com a posição, a trilha do alcance e os valores."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.x, self.y = 128, 128
        self.tracker = RangeTracker()
        self.setMinimumSize(150, 170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_position(self, x: int, y: int) -> None:
        self.x, self.y = x, y
        self.tracker.add(*stick_point(x, y))
        self.update()

    def reset_range(self) -> None:
        self.tracker.reset()
        self.update()

    def draw(self, p: QPainter) -> None:
        mid, active, text = self._colors()
        side = min(self.width(), self.height() - 24)
        radius = side / 2 - 4
        center = QPointF(self.width() / 2, 4 + side / 2)
        p.setPen(QPen(mid, 1.5))
        p.drawEllipse(center, radius, radius)
        p.drawLine(QPointF(center.x() - radius, center.y()), QPointF(center.x() + radius, center.y()))
        p.drawLine(QPointF(center.x(), center.y() - radius), QPointF(center.x(), center.y() + radius))

        # Trilha do alcance: polígono com o maior raio de cada direção (pode passar um pouco do círculo).
        limit = (radius + 3) / radius if radius > 0 else 1.0
        bins = [min(r, limit) for r in self.tracker.radii]
        polygon = QPolygonF(
            [
                QPointF(center.x() + math.cos((i + 0.5) / len(bins) * math.tau) * r * radius,
                        center.y() - math.sin((i + 0.5) / len(bins) * math.tau) * r * radius)
                for i, r in enumerate(bins)
            ]
        )
        fill = QColor(active)
        fill.setAlpha(70)
        p.setPen(QPen(active, 1))
        p.setBrush(fill)
        p.drawPolygon(polygon)

        px, py = stick_point(self.x, self.y)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(active)
        p.drawEllipse(QPointF(center.x() + px * radius, center.y() - py * radius), 6, 6)
        p.setPen(text)
        label = f"X {self.x:3d}  Y {self.y:3d}"
        error = self.tracker.circularity_error()
        if error is not None:
            label += f"  ·  {error:.1f} %"
        p.drawText(QRectF(0, self.height() - 20, self.width(), 20), Qt.AlignmentFlag.AlignCenter, label)


class TouchpadView(_Canvas):
    """Touchpad com até dois dedos, cada um numa cor."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.touches = (None, None)
        self.setMinimumSize(200, 100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_touches(self, touches) -> None:
        self.touches = touches
        self.update()

    def draw(self, p: QPainter) -> None:
        mid, _active, _text = self._colors()
        area = QRectF(2, 2, self.width() - 4, self.height() - 4)
        p.setPen(QPen(mid, 1.5))
        p.drawRoundedRect(area, 8, 8)
        for index, touch in enumerate(self.touches):
            if touch is None:
                continue
            p.setBrush(AXIS_COLORS[index])
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(area.left() + area.width() * touch.x / TOUCHPAD_WIDTH, area.top() + area.height() * touch.y / TOUCHPAD_HEIGHT), 9, 9)


class ImuPlot(_Canvas):
    """Gráfico dos três eixos de um sensor (giroscópio ou acelerômetro)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.history = ImuHistory()
        self.setMinimumSize(200, 90)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def add(self, sample: tuple[int, int, int]) -> None:
        self.history.add(sample)
        self.update()

    def draw(self, p: QPainter) -> None:
        mid, _active, _text = self._colors()
        area = QRectF(2, 2, self.width() - 4, self.height() - 4)
        p.setPen(QPen(mid, 1))
        p.drawRect(area)
        p.drawLine(QPointF(area.left(), area.center().y()), QPointF(area.right(), area.center().y()))
        count = self.history.samples.maxlen or 1
        for index, color in enumerate(AXIS_COLORS):
            values = self.history.axis(index)
            if len(values) < 2:
                continue
            points = QPolygonF(
                [
                    QPointF(area.left() + area.width() * i / (count - 1),
                            area.center().y() - max(-1.0, min(1.0, v / 32768)) * area.height() / 2)
                    for i, v in enumerate(values)
                ]
            )
            p.setPen(QPen(color, 1.5))
            p.drawPolyline(points)
