"""Ícone da bandeja: o contorno de um controle e, ao lado, uma barra vertical na cor dos LEDs."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

CONTROLLER_SVG = Path(__file__).with_name("icons") / "controller.svg"
# Tamanhos que a bandeja costuma pedir; o sistema escolhe o mais próximo.
SIZES = (22, 24, 32, 48, 64)

# Recorte da imagem original, para o controle ocupar quase todo o espaço em vez de ficar pequeno
# no meio de uma área quadrada vazia.
_VIEW_BOX = QRectF(0.1, 2.0, 13.8, 10.0)
# Traço mais fino que o original (1), para um ícone mais delicado; ainda dá cerca de 1 px em 22 px.
_STROKE_WIDTH = "0.8"
# Espessura do contorno da barra de cor, na grade de 64 unidades.
_BAR_OUTLINE = 1.0
# Medidas numa grade de 64 unidades (escalada para o tamanho pedido): controle à esquerda, barra à direita.
GRID = 64
_CONTROLLER_WIDTH = 51.0
_BAR = QRectF(55.5, 12.0, 7.0, 40.0)


def _svg_with_stroke(color: QColor) -> QByteArray:
    svg = CONTROLLER_SVG.read_text()
    svg = svg.replace('stroke="#000000"', f'stroke="{color.name()}"').replace('stroke-width="1"', f'stroke-width="{_STROKE_WIDTH}"')
    return QByteArray(svg.encode())


def render(color: tuple[int, int, int], brightness: int, line: QColor, size: int = 64) -> QPixmap:
    """Desenha o ícone: `line` é a cor do contorno do controle, `color`/`brightness` a da barra."""
    # Desenha direto no tamanho pedido, em vez de reduzir uma imagem grande (que ficaria borrada).
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / GRID, size / GRID)

    renderer = QSvgRenderer(_svg_with_stroke(line))
    renderer.setViewBox(_VIEW_BOX)
    height = _CONTROLLER_WIDTH * _VIEW_BOX.height() / _VIEW_BOX.width()
    renderer.render(painter, QRectF(0, (GRID - height) / 2, _CONTROLLER_WIDTH, height))

    radius = _BAR.width() / 2
    if brightness > 0:
        scale = brightness / 255
        fill = QColor(*(round(channel * scale) for channel in color))
        painter.setBrush(fill)
        outline = QColor(line)
        outline.setAlpha(150)  # mantém a barra visível mesmo quando a cor é escura
        painter.setPen(QPen(outline, _BAR_OUTLINE))
    else:
        painter.setBrush(Qt.BrushStyle.NoBrush)  # LEDs apagados: só o contorno
        faint = QColor(line)
        faint.setAlpha(110)
        painter.setPen(QPen(faint, _BAR_OUTLINE))
    painter.drawRoundedRect(_BAR, radius, radius)
    painter.end()

    return QPixmap.fromImage(image)


def tray_icon(color: tuple[int, int, int], brightness: int, line: QColor) -> QIcon:
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(render(color, brightness, line, size))
    return icon
