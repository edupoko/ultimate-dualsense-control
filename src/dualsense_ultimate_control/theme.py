"""Visual próprio do app: paleta clara/escura sobre o Fusion e a barra lateral estilo "Configurações".

Tudo é aplicado uma vez (e de novo só quando o tema do sistema muda): sem sombras, sem animação
e sem reaplicar estilo em widgets soltos. Com o tema do KDE ativo (`kdetheme.enable`) a paleta do
sistema é mantida e só a barra lateral recebe o estilo, calculado a partir dessa paleta.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from . import i18n

RADIUS = 6  # cantos dos itens selecionados, em px
ITEM_PADDING = (8, 10)  # vertical, horizontal
ITEM_MARGIN = 2  # espaço vertical entre itens
ICON_SIZE = 20  # px, ícones da barra lateral
DEFAULT_ACCENT = "#7b61c9"  # só quando nem a plataforma nem o estilo informam um destaque


@dataclass(frozen=True)
class Tokens:
    window: str
    base: str
    alternate: str
    button: str
    text: str
    muted: str


DARK = Tokens(window="#1c1e23", base="#14161a", alternate="#23262c", button="#2a2d34", text="#e8eaed", muted="#8b9098")
LIGHT = Tokens(window="#f1f2f4", base="#ffffff", alternate="#e9ebee", button="#e6e8eb", text="#1d1f23", muted="#7a7f87")


# Ícones de traço (grade 24×24), desenhados na cor do texto: um só desenho serve aos dois temas.
ICONS = {
    "controls": (
        '<path d="M6 8h12a4 4 0 0 1 4 4v2a3 3 0 0 1-5.2 2L15 14H9l-1.8 2A3 3 0 0 1 2 14v-2a4 4 0 0 1 4-4z"/>'
        '<path d="M7 10.5v3M5.5 12h3M16 11h.01M18 13h.01"/>'
    ),
    "test": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "profiles": (
        '<path d="M4 6h8M18 6h2M4 12h2M12 12h8M4 18h10M20 18h0"/>'
        '<circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>'
    ),
    "logs": '<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7"/>',
}


def render_icon(name: str, color: QColor, size: int = ICON_SIZE, ratio: float = 1.0) -> QPixmap:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color.name()}" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>'
    )
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def nav_icon(name: str, palette: QPalette, ratio: float = 1.0) -> QIcon:
    """Ícone na cor do texto e, quando o item está selecionado, na cor do texto realçado."""
    icon = QIcon()
    icon.addPixmap(render_icon(name, palette.color(QPalette.ColorRole.WindowText), ratio=ratio), QIcon.Mode.Normal)
    icon.addPixmap(render_icon(name, palette.color(QPalette.ColorRole.HighlightedText), ratio=ratio), QIcon.Mode.Selected)
    return icon


def is_dark(palette: QPalette) -> bool:
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def build_palette(tokens: Tokens, accent: QColor) -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: tokens.window,
        QPalette.ColorRole.WindowText: tokens.text,
        QPalette.ColorRole.Base: tokens.base,
        QPalette.ColorRole.AlternateBase: tokens.alternate,
        QPalette.ColorRole.Text: tokens.text,
        QPalette.ColorRole.Button: tokens.button,
        QPalette.ColorRole.ButtonText: tokens.text,
        QPalette.ColorRole.ToolTipBase: tokens.alternate,
        QPalette.ColorRole.ToolTipText: tokens.text,
        QPalette.ColorRole.PlaceholderText: tokens.muted,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("white" if accent.lightness() < 160 else "black"))
    palette.setColor(QPalette.ColorRole.Link, accent.lighter(130) if tokens is DARK else accent)
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(tokens.muted))
    return palette


def accent_color(app: QApplication) -> QColor:
    """Destaque do sistema (Qt 6.6+), ou o da paleta atual, ou o roxo padrão."""
    hints = app.styleHints()
    color = hints.accentColor() if hasattr(hints, "accentColor") else QColor()
    if color.isValid():
        return color
    return app.palette().color(QPalette.ColorRole.Highlight) if app.palette().color(QPalette.ColorRole.Highlight).isValid() else QColor(DEFAULT_ACCENT)


def wants_own_theme(kde_active: bool) -> bool:
    """O tema próprio vale quando o do KDE não está ativo e o usuário não escolheu um estilo à mão."""
    return not kde_active and not os.environ.get("QT_STYLE_OVERRIDE")


def apply(app: QApplication, kde_active: bool) -> bool:
    """Aplica o tema próprio (Fusion + paleta clara/escura do sistema). Devolve se foi aplicado."""
    if not wants_own_theme(kde_active):
        return False
    accent = accent_color(app)
    fallback_dark = is_dark(app.palette())
    app.setStyle("Fusion")

    def refresh() -> None:
        scheme = app.styleHints().colorScheme()
        dark = fallback_dark if scheme == Qt.ColorScheme.Unknown else scheme == Qt.ColorScheme.Dark
        app.setPalette(build_palette(DARK if dark else LIGHT, accent))

    refresh()
    app.styleHints().colorSchemeChanged.connect(lambda _scheme: refresh())
    return True


def sidebar_qss(palette: QPalette) -> str:
    """Folha de estilo da barra lateral, calculada da paleta atual (serve para o Breeze e para o tema próprio)."""
    window = palette.color(QPalette.ColorRole.Window)
    background = window.darker(125 if is_dark(palette) else 104)
    accent = palette.color(QPalette.ColorRole.Highlight)
    hover = QColor(accent)
    hover.setAlpha(60)
    divider = palette.color(QPalette.ColorRole.Mid)
    vertical, horizontal = ITEM_PADDING
    return (
        f"SideNav {{ background: {background.name()}; border: none; border-right: 1px solid {divider.name()}; padding: 6px; }}"
        f"SideNav::item {{ padding: {vertical}px {horizontal}px; margin: {ITEM_MARGIN}px 0; border-radius: {RADIUS}px; }}"
        f"SideNav::item:hover {{ background: rgba({hover.red()}, {hover.green()}, {hover.blue()}, {hover.alpha()}); }}"
        f"SideNav::item:selected {{ background: {accent.name()}; color: {palette.color(QPalette.ColorRole.HighlightedText).name()}; }}"
    )


class SideNav(QListWidget):
    """Lista lateral de páginas; o estilo acompanha a paleta do aplicativo (reaplicado só quando ela muda).

    Usa a paleta do aplicativo, não a do widget: a folha de estilo altera a paleta do próprio
    widget, o que dispararia o evento de novo e faria o estilo derivar a cada passada."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFrameShape(QListWidget.Shape.NoFrame)
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._icon_names: list[str] = []
        self._restyle()
        # O sinal do app (e não o evento do widget): com folha de estilo própria o evento não chega.
        QApplication.instance().paletteChanged.connect(self._restyle)

    def add_page(self, icon_name: str) -> QListWidgetItem:
        item = QListWidgetItem()
        self._icon_names.append(icon_name)
        self.addItem(item)
        item.setIcon(nav_icon(icon_name, QApplication.palette(), self.devicePixelRatioF()))
        return item

    def _restyle(self, _palette: QPalette | None = None) -> None:
        palette = QApplication.palette()
        css = sidebar_qss(palette)
        if css != self.styleSheet():
            self.setStyleSheet(css)
            for row, name in enumerate(self._icon_names):  # a cor do texto mudou junto com a paleta
                self.item(row).setIcon(nav_icon(name, palette, self.devicePixelRatioF()))


def section(title_key: str) -> tuple[QWidget, QVBoxLayout]:
    """Seção com cabeçalho (título em negrito e uma linha fina) e um layout para o conteúdo."""
    holder = QWidget()
    outer = QVBoxLayout(holder)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(6)
    head = QHBoxLayout()
    head.setSpacing(8)
    title = QLabel()
    font = title.font()
    font.setBold(True)
    title.setFont(font)
    i18n.bind(title.setText, title_key)
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet("background: palette(mid);")
    head.addWidget(title)
    head.addWidget(line, 1, Qt.AlignmentFlag.AlignVCenter)
    outer.addLayout(head)
    content = QVBoxLayout()
    outer.addLayout(content)
    return holder, content
