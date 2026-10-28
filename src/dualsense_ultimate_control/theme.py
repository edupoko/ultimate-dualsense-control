"""Visual próprio do app: paleta clara/escura sobre o Fusion e a barra lateral estilo "Configurações".

Tudo é aplicado uma vez (e de novo só quando o tema do sistema muda): sem sombras, sem animação
e sem reaplicar estilo em widgets soltos. Com o tema do KDE ativo (`kdetheme.enable`) a paleta do
sistema é mantida e só a barra lateral recebe o estilo, calculado a partir dessa paleta. Numa sessão
GNOME (ou com `DUALSENSE_ULTIMATE_THEME=gnome`) o mesmo caminho usa tons e formas inspirados no
libadwaita; sem GTK, sem libadwaita e sem plugin do sistema: só paleta e folha de estilo.
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
ADW_ACCENT = "#3584e4"  # azul padrão do GNOME, quando o portal não publica o destaque
ADW_RADIUS = 8  # cantos dos itens da barra lateral no estilo do GNOME Settings
THEME_ENV = "DUALSENSE_ULTIMATE_THEME"  # auto (padrão), kde, gnome ou own
LEGACY_OWN_ENV = "DUALSENSE_ULTIMATE_NO_KDE_THEME"  # o nome antigo de "own"
THEMES = ("kde", "gnome", "own")

# Tamanhos da janela e das páginas (F5). O mínimo cabe numa tela de 1366×768 com painel.
WINDOW_MIN_SIZE = (720, 520)
WINDOW_DEFAULT_SIZE = (960, 680)
NAV_WIDTH = 200  # barra lateral
# Largura da página (sem a barra lateral) a partir da qual Controles e Entradas usam 2 colunas;
# com a barra de 200 px, corresponde a uma janela de ~820 px.
TWO_COLUMNS_MIN_WIDTH = 600
COLUMN_SPACING = 16
DIALOG_DEFAULT_SIZE = (620, 560)  # Teste rápido e assistentes de calibração


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
# Tons do libadwaita: claro ≈ #fafafa / #ffffff, escuro ≈ #242424 / #1e1e1e.
ADW_DARK = Tokens(window="#242424", base="#1e1e1e", alternate="#2c2c2c", button="#383838", text="#ffffff", muted="#9a9996")
ADW_LIGHT = Tokens(window="#fafafa", base="#ffffff", alternate="#f3f3f3", button="#ebebeb", text="#323232", muted="#77767b")

_style = "own"  # "gnome" quando o visual Adwaita foi aplicado; define o QSS da barra e o interruptor


def style() -> str:
    """Visual em uso: "gnome" (Adwaita) ou "own" (o mesmo da paleta própria e do Breeze)."""
    return _style


def detect(env: dict[str, str] | None = None, preference: str = "auto") -> str:
    """Tema escolhido: "kde", "gnome" ou "own".

    `DUALSENSE_ULTIMATE_THEME` força um deles; a variável antiga `DUALSENSE_ULTIMATE_NO_KDE_THEME`
    vale como "own"; depois vem a escolha salva nas configurações (`preference`). Sem nenhuma, vem
    do desktop (`XDG_CURRENT_DESKTOP`, depois `DESKTOP_SESSION`)."""
    env = os.environ if env is None else env
    forced = env.get(THEME_ENV, "").strip().lower()
    if forced in THEMES:
        return forced
    if env.get(LEGACY_OWN_ENV):
        return "own"
    if preference in THEMES:
        return preference
    desktops = [part.upper() for part in env.get("XDG_CURRENT_DESKTOP", "").split(":") if part]
    if not desktops:
        desktops = [env.get("DESKTOP_SESSION", "").upper()]
    joined = " ".join(desktops)
    if "GNOME" in joined:
        return "gnome"
    if "KDE" in joined or "PLASMA" in joined:
        return "kde"
    return "own"


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
    "settings": (
        '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="7"/>'
        '<path d="M19 12h2.5M5 12H2.5M12 19v2.5M12 5V2.5M16.95 16.95l1.77 1.77M7.05 16.95l-1.77 1.77'
        'M7.05 7.05 5.28 5.28M16.95 7.05l1.77-1.77"/>'
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


def nav_icon(name: str, palette: QPalette, ratio: float = 1.0, visual: str | None = None) -> QIcon:
    """Ícone na cor do texto e, quando o item está selecionado, na cor do texto realçado.

    No visual do GNOME o selecionado é só um fundo suave, então o ícone mantém a cor normal."""
    selected = QPalette.ColorRole.WindowText if (visual or _style) == "gnome" else QPalette.ColorRole.HighlightedText
    icon = QIcon()
    icon.addPixmap(render_icon(name, palette.color(QPalette.ColorRole.WindowText), ratio=ratio), QIcon.Mode.Normal)
    icon.addPixmap(render_icon(name, palette.color(selected), ratio=ratio), QIcon.Mode.Selected)
    return icon


def is_dark(palette: QPalette) -> bool:
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


@dataclass(frozen=True)
class SwitchColors:
    off_track: QColor
    off_outline: QColor
    off_knob: QColor
    on_knob: QColor


def switch_colors(palette: QPalette, visual: str | None = None) -> SwitchColors:
    """Cores do interruptor: no tema escuro, trilho e botão em cinzas escuros em vez do branco puro.

    No visual do GNOME o trilho desligado é um cinza translúcido, sem contorno, e o botão é branco."""
    if (visual or _style) == "gnome":
        track = QColor(palette.color(QPalette.ColorRole.WindowText))
        track.setAlpha(46 if is_dark(palette) else 38)  # ~15% do texto, como o libadwaita
        return SwitchColors(track, QColor(0, 0, 0, 0), QColor("white"), QColor("white"))
    if is_dark(palette):
        return SwitchColors(QColor("#3a3d44"), QColor("#5a5f69"), QColor("#b4b8c0"), QColor("#f2f3f5"))
    text = palette.color(QPalette.ColorRole.WindowText)
    track = QColor(text)
    track.setAlpha(90)  # translúcido: a cor "mid" do tema pode ser igual ao fundo e sumir
    return SwitchColors(track, QColor(0, 0, 0, 0), QColor("white"), QColor("white"))


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
    palette.setColor(QPalette.ColorRole.Link, accent.lighter(130) if tokens in (DARK, ADW_DARK) else accent)
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(tokens.muted))
    return palette


def accent_color(app: QApplication, fallback: str | None = None) -> QColor:
    """Destaque do sistema (Qt 6.6+), ou `fallback`, ou o da paleta atual, ou o roxo padrão."""
    hints = app.styleHints()
    color = hints.accentColor() if hasattr(hints, "accentColor") else QColor()
    if color.isValid():
        return color
    if fallback:
        return QColor(fallback)
    return app.palette().color(QPalette.ColorRole.Highlight) if app.palette().color(QPalette.ColorRole.Highlight).isValid() else QColor(DEFAULT_ACCENT)


def wants_own_theme(kde_active: bool) -> bool:
    """O tema próprio vale quando o do KDE não está ativo e o usuário não escolheu um estilo à mão."""
    return not kde_active and not os.environ.get("QT_STYLE_OVERRIDE")


def apply(app: QApplication, kde_active: bool, name: str = "own") -> bool:
    """Aplica o tema próprio (Fusion + paleta clara/escura do sistema). Devolve se foi aplicado.

    `name` é o tema escolhido por `detect()`: com "gnome" a paleta e a barra lateral seguem o libadwaita."""
    global _style
    _style = "own"
    if not wants_own_theme(kde_active):
        return False
    gnome = name == "gnome"
    _style = "gnome" if gnome else "own"
    accent = accent_color(app, ADW_ACCENT if gnome else None)
    fallback_dark = is_dark(app.palette())
    light, dark_tokens = (ADW_LIGHT, ADW_DARK) if gnome else (LIGHT, DARK)
    app.setStyle("Fusion")

    def refresh() -> None:
        scheme = app.styleHints().colorScheme()
        dark = fallback_dark if scheme == Qt.ColorScheme.Unknown else scheme == Qt.ColorScheme.Dark
        # No GNOME o destaque é relido a cada passada: o portal avisa quando o usuário o troca.
        current = accent_color(app, ADW_ACCENT) if gnome else accent
        app.setPalette(build_palette(dark_tokens if dark else light, current))

    refresh()
    app.styleHints().colorSchemeChanged.connect(lambda _scheme: refresh())
    if gnome and hasattr(app.styleHints(), "accentColorChanged"):
        app.styleHints().accentColorChanged.connect(lambda _color: refresh())
    return True


def sidebar_qss(palette: QPalette, visual: str | None = None) -> str:
    """Folha de estilo da barra lateral, calculada da paleta atual (serve para o Breeze e para o tema próprio).

    No visual do GNOME: cantos de 8 px e o item selecionado num tom suave do texto, não no destaque cheio."""
    gnome = (visual or _style) == "gnome"
    window = palette.color(QPalette.ColorRole.Window)
    if gnome:
        background = window.lighter(125) if is_dark(palette) else window.darker(107)
    else:
        background = window.darker(125 if is_dark(palette) else 104)
    divider = palette.color(QPalette.ColorRole.Mid)
    vertical, horizontal = ITEM_PADDING
    if gnome:
        text = palette.color(QPalette.ColorRole.WindowText)
        hover, selected = QColor(text), QColor(text)
        hover.setAlpha(18)  # ~7%
        selected.setAlpha(36)  # ~14%
        radius, selected_color = ADW_RADIUS, text.name()
    else:
        accent = palette.color(QPalette.ColorRole.Highlight)
        hover, selected = QColor(accent), QColor(accent)
        hover.setAlpha(60)
        radius, selected_color = RADIUS, palette.color(QPalette.ColorRole.HighlightedText).name()
    def rgba(color: QColor) -> str:
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"

    selected_background = rgba(selected) if gnome else selected.name()
    return (
        f"SideNav {{ background: {background.name()}; border: none; border-right: 1px solid {divider.name()}; padding: 6px; }}"
        f"SideNav::item {{ padding: {vertical}px {horizontal}px; margin: {ITEM_MARGIN}px 0; border-radius: {radius}px; }}"
        f"SideNav::item:hover {{ background: {rgba(hover)}; }}"
        f"SideNav::item:selected {{ background: {selected_background}; color: {selected_color}; }}"
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
