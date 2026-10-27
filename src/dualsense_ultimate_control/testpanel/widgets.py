"""Widgets desenhados da tela de teste: controle, sticks, touchpad e gráfico do IMU."""

from __future__ import annotations

import math
import re

from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..ds5.reports import TOUCHPAD_HEIGHT, TOUCHPAD_WIDTH, InputState
from .model import ImuHistory, RangeTracker, lit_parts, stick_point, trigger_percent

AXIS_COLORS = (QColor("#e5484d"), QColor("#30a46c"), QColor("#3e63dd"))
_SVG = Path(__file__).resolve().parent.parent / "icons" / "controller-outline.svg"
_SVG_W, _SVG_H = 529, 403
# Cores literais do arquivo (as mesmas de scripts/controller_outline.py), trocadas pelas do tema.
_SVG_OUTER, _SVG_INNER, _SVG_BASE = "#f4f6f8", "#b9bfc7", "#2b3238"


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
    """Desenho do controle (SVG com um id por peça): peças acesas conforme o estado.

    O contorno fica num pixmap em cache, refeito só ao redimensionar ou trocar a paleta;
    por quadro só se pintam as peças acesas, os analógicos e os dedos.
    """

    _STICKS = {"l3": (180.0, 224.0), "r3": (_SVG_W - 180.0, 224.0)}
    _STICK_TRAVEL = 12.0
    _PAD = QRectF(176, 92, _SVG_W - 352, 86)  # área útil do touchpad no desenho
    # Barra vertical de cada gatilho, ao lado da aba (x do lado esquerdo; o direito é o espelho).
    _BAR = QRectF(52, 12, 9, 52)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.state: InputState | None = None
        self._shown: tuple | None = None
        self._cache_key: tuple | None = None
        self._cache: QPixmap | None = None
        self._lit_renderer: QSvgRenderer | None = None
        self._colors_key: tuple | None = None
        self.setMinimumSize(320, 244)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_state(self, state: InputState | None) -> None:
        self.state = state
        if state is not None:
            self.setAccessibleDescription(f"L2 {trigger_percent(state.l2)}%, R2 {trigger_percent(state.r2)}%")
        shown = _shown_key(state)
        if shown != self._shown:  # só repinta quando algo visível mudou
            self._shown = shown
            self.update()

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self._colors_key = None
            self._cache_key = None
        super().changeEvent(event)

    def _renderers(self) -> tuple[QSvgRenderer, QSvgRenderer, QColor]:
        """Renderizadores com as cores do tema: o do contorno e o das peças acesas."""
        palette = self.palette()
        role = palette.ColorRole
        text, window, accent = palette.color(role.Text), palette.color(role.Window), palette.color(role.Highlight)
        key = (text.rgba(), window.rgba(), accent.rgba())
        if key != self._colors_key:
            outer = text
            inner = _mix(text, window, 0.35)
            base = _mix(window, text, 0.10)
            self._static_renderer = _themed(_SVG_OUTER, outer, _SVG_INNER, inner, _SVG_BASE, base)
            self._lit_renderer = _themed(_SVG_OUTER, outer, _SVG_INNER, inner, _SVG_BASE, accent)
            self._dot, self._track, self._accent = text, inner, accent
            self._colors_key = key
        return self._static_renderer, self._lit_renderer, self._dot

    def _layer(self, renderer: QSvgRenderer, size: QSize, ratio: float) -> QPixmap:
        key = (size.width(), size.height(), ratio, self._colors_key)
        if key != self._cache_key or self._cache is None:
            pixmap = QPixmap(size * ratio)
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter, QRectF(self._target(size)))
            painter.end()
            self._cache, self._cache_key = pixmap, key
        return self._cache

    @staticmethod
    def _target(size: QSize) -> QRectF:
        scale = min(size.width() / _SVG_W, size.height() / _SVG_H)
        w, h = _SVG_W * scale, _SVG_H * scale
        return QRectF((size.width() - w) / 2, (size.height() - h) / 2, w, h)

    def draw(self, p: QPainter) -> None:
        static, lit, dot = self._renderers()
        p.drawPixmap(0, 0, self._layer(static, self.size(), self.devicePixelRatioF()))
        target = self._target(self.size())
        scale = target.width() / _SVG_W
        p.translate(target.topLeft())
        p.scale(scale, scale)
        state = self.state
        triggers = {"l2": state.l2 if state else 0, "r2": state.r2 if state else 0}
        pressed = lit_parts(state)
        for name in pressed - triggers.keys():
            lit.render(p, name, static.boundsOnElement(name))
        for name, value in triggers.items():
            # Acende na proporção da pressão; o clique digital (100%) acende por inteiro.
            p.setOpacity(1.0 if name in pressed else value / 255)
            if p.opacity() > 0:
                lit.render(p, name, static.boundsOnElement(name))
        p.setOpacity(1.0)
        self._draw_trigger_bars(p, triggers)

        p.setPen(Qt.PenStyle.NoPen)
        for name, (cx, cy) in self._STICKS.items():
            x, y = (state.lx, state.ly) if name == "l3" and state else (state.rx, state.ry) if state else (128, 128)
            px, py = stick_point(x, y)
            p.setBrush(dot)
            p.drawEllipse(QPointF(cx + px * self._STICK_TRAVEL, cy - py * self._STICK_TRAVEL), 5, 5)
        if state:
            p.setBrush(dot)  # na cor do texto: continua visível com o touchpad aceso
            for touch in state.touches:
                if touch is not None:
                    x = self._PAD.left() + self._PAD.width() * touch.x / TOUCHPAD_WIDTH
                    y = self._PAD.top() + self._PAD.height() * touch.y / TOUCHPAD_HEIGHT
                    p.drawEllipse(QPointF(x, y), 5, 5)

    def _draw_trigger_bars(self, p: QPainter, triggers: dict[str, int]) -> None:
        """Barra vertical e porcentagem de cada gatilho, ao lado da aba (largura fixa: o texto não tremer)."""
        font = QFont(p.font())
        font.setPixelSize(13)
        p.setFont(font)
        for name, value in triggers.items():
            bar = QRectF(self._BAR)
            if name == "r2":
                bar.moveLeft(_SVG_W - self._BAR.right())
            p.setPen(QPen(self._track, 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(bar, 4, 4)
            fill = QRectF(bar.left(), bar.bottom() - bar.height() * value / 255, bar.width(), bar.height() * value / 255)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._accent)
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(bar, 4, 4)
            p.setClipPath(clip)
            p.drawRect(fill)
            p.restore()
            p.setPen(self._dot)
            p.drawText(QRectF(bar.center().x() - 24, bar.bottom() + 3, 48, 16), Qt.AlignmentFlag.AlignCenter, f"{trigger_percent(value)}%")


def _shown_key(state: InputState | None) -> tuple | None:
    """O que o desenho mostra do estado: se for igual, não há por que repintar."""
    if state is None:
        return None
    return (lit_parts(state), state.l2, state.r2, state.lx, state.ly, state.rx, state.ry, state.touches)


def _themed(*pairs) -> QSvgRenderer:
    """O SVG com cada cor literal (par 0, 2, 4…) trocada pela seguinte, numa passada só."""
    mapping = {pairs[i]: pairs[i + 1].name() for i in range(0, len(pairs), 2)}
    svg = re.sub("|".join(map(re.escape, mapping)), lambda m: mapping[m.group()], _SVG.read_text())
    return QSvgRenderer(QByteArray(svg.encode()))


def _mix(a: QColor, b: QColor, amount: float) -> QColor:
    """`a` com `amount` de `b` misturado."""
    return QColor(*(round(x * (1 - amount) + y * amount) for x, y in zip(a.getRgb()[:3], b.getRgb()[:3])))


class StickView(_Canvas):
    """Um analógico: círculo com a posição, a trilha do alcance e os valores."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.x, self.y = 128, 128
        self.tracker = RangeTracker()
        self.setMinimumSize(100, 110)
        self.setMaximumHeight(150)
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
