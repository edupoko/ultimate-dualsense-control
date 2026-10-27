"""Visual próprio do app: paleta clara/escura sobre o Fusion e a barra lateral estilo "Configurações".

Tudo é aplicado uma vez (e de novo só quando o tema do sistema muda): sem sombras, sem animação
e sem reaplicar estilo em widgets soltos. Com o tema do KDE ativo (`kdetheme.enable`) a paleta do
sistema é mantida e só a barra lateral recebe o estilo, calculado a partir dessa paleta.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QListWidget, QWidget

RADIUS = 6  # cantos dos itens selecionados, em px
ITEM_PADDING = (8, 10)  # vertical, horizontal
ITEM_MARGIN = 2  # espaço vertical entre itens
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
        self._restyle()
        # O sinal do app (e não o evento do widget): com folha de estilo própria o evento não chega.
        QApplication.instance().paletteChanged.connect(self._restyle)

    def _restyle(self, _palette: QPalette | None = None) -> None:
        css = sidebar_qss(QApplication.palette())
        if css != self.styleSheet():
            self.setStyleSheet(css)
