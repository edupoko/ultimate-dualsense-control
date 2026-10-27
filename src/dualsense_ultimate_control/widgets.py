"""Peças de interface compartilhadas pela bandeja e pela janela."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFontMetrics, QGuiApplication, QLinearGradient, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QPushButton,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QTabBar,
    QToolButton,
    QWidget,
)

import logging

from . import autostart, bluetooth, i18n
from .confirm import HelpPanel
from .colors import PRESETS
from .i18n import tr
from .translations import STRINGS
from .players import NO_PLAYER, PLAYER_COUNT, pattern_for, player_number
from .service import LedService

TRAY_MARGIN = 8

HUE_MAX = 359

# Margens das linhas com widgets no menu. A esquerda inclui a coluna de ícones que o estilo
# reserva nos itens de texto, para rótulos e textos começarem no mesmo ponto.
ROW_MARGINS = (28, 3, 12, 3)


def save_current_color(service: LedService) -> None:
    """Guarda a cor atual (a dos sliders) no seletor rápido."""
    service.add_custom_color(tuple(service.settings.color))


# Abre a janela de configurações da Steam na página de controles.
STEAM_CONTROLLER_SETTINGS_URL = "steam://open/settings/controller"


def open_steam_controller_settings() -> None:
    QDesktopServices.openUrl(QUrl(STEAM_CONTROLLER_SETTINGS_URL))


def steam_help_panel(service: LedService) -> HelpPanel:
    """Explica a disputa com a Steam e oferece mandar de novo as cores do app."""
    help_text = tr("steam.help")
    uid = service.selected_uid
    if uid is not None and service.emulation_for(uid):
        help_text += tr("steam.emulation_hint")
    return HelpPanel(
        tr("steam.title"),
        tr("steam.text"),
        help_text,
        [(tr("steam.open_settings"), open_steam_controller_settings), (tr("steam.reapply"), service.reapply_selected)],
    )


def bluetooth_help_panel(service: LedService) -> HelpPanel:
    """Explica o controle Bluetooth "conectado" que o sistema não registrou e oferece desconectá-lo."""
    addresses = list(service.unregistered_bluetooth)

    def disconnect() -> None:
        for address in addresses:
            bluetooth.disconnect(address)

    return HelpPanel(
        tr("bluetooth.title"),
        tr("bluetooth.text", addresses=", ".join(a.upper() for a in addresses)),
        tr("bluetooth.help"),
        [(tr("bluetooth.disconnect"), disconnect)],
    )


def tray_corner_position(size: QSize, screen: QRect, available: QRect, margin: int = TRAY_MARGIN) -> QPoint:
    """Canto da área de trabalho junto ao painel do sistema, onde fica a bandeja.

    O painel é a borda em que a área disponível é menor que a tela. A bandeja fica
    no fim do painel: à direita num painel horizontal, embaixo num vertical.
    """
    if available.left() > screen.left():
        x = available.left() + margin
    else:
        x = available.right() + 1 - size.width() - margin
    if available.top() > screen.top():
        y = available.top() + margin
    else:
        y = available.bottom() + 1 - size.height() - margin
    return QPoint(x, y)


def _bound_label(key: str) -> QLabel:
    """Rótulo cujo texto acompanha o idioma."""
    label = QLabel()
    i18n.bind(label.setText, key)
    return label


_label_width: int | None = None


def label_width() -> int:
    """Largura da coluna de rótulos: a do maior texto entre todos os idiomas, para o layout não mudar."""
    global _label_width
    if _label_width is None:
        metrics = QFontMetrics(QGuiApplication.font())
        keys = ("slider.hue", "slider.saturation", "slider.brightness", "players.label")
        _label_width = 6 + max(metrics.horizontalAdvance(STRINGS[k][code]) for k in keys for code in i18n.LANGUAGES)
    return _label_width


def hsv_color(hue: int, saturation: int, value: int = 255) -> tuple[int, int, int]:
    """Cor a partir do matiz (0–359), da saturação em % (0–100) e do valor (0–255)."""
    color = QColor.fromHsv(hue, round(saturation * 255 / 100), value)
    return color.red(), color.green(), color.blue()


def hue_color(hue: int) -> tuple[int, int, int]:
    return hsv_color(hue, 100)


class GradientSlider(QSlider):
    """Slider horizontal moderno: trilha em gradiente e botão redondo na cor do valor atual."""

    TRACK_HEIGHT = 6
    # Indicador em pílula vertical: estreito e alto, com as pontas totalmente arredondadas.
    HANDLE_WIDTH = 11
    HANDLE_HEIGHT = 22

    def __init__(self, handle_color: Callable[[int], QColor], parent: QWidget | None = None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._handle_color = handle_color
        self._stops: list[tuple[float, QColor]] = [(0.0, QColor("#888")), (1.0, QColor("#888"))]
        self.setFixedHeight(self.HANDLE_HEIGHT + 4)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_stops(self, stops: list[tuple[float, QColor]]) -> None:
        self._stops = stops
        self.update()

    def _ratio(self) -> float:
        span = self.maximum() - self.minimum()
        return (self.value() - self.minimum()) / span if span else 0.0

    def _value_at(self, x: float) -> int:
        radius = self.HANDLE_WIDTH / 2
        ratio = min(1.0, max(0.0, (x - radius) / max(1.0, self.width() - 2 * radius)))
        return self.minimum() + round(ratio * (self.maximum() - self.minimum()))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self.setValue(self._value_at(event.position().x()))
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.isSliderDown():
            self.setValue(self._value_at(event.position().x()))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = self.HANDLE_WIDTH / 2
        middle = self.height() / 2

        # A trilha vai de ponta a ponta; só o centro do botão fica entre os raios, assim não
        # sobra um vão vazio entre o fim da trilha e o que vem depois dela.
        track = QRectF(0.5, middle - self.TRACK_HEIGHT / 2, self.width() - 1, self.TRACK_HEIGHT)
        gradient = QLinearGradient(track.left(), 0, track.right(), 0)
        for position, color in self._stops:
            gradient.setColorAt(position, color)
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(0, 0, 0, 45), 1))
        painter.drawRoundedRect(track, self.TRACK_HEIGHT / 2, self.TRACK_HEIGHT / 2)

        center_x = radius + self._ratio() * (self.width() - 2 * radius)
        half_height = self.HANDLE_HEIGHT / 2
        outer = QRectF(center_x - radius, middle - half_height, self.HANDLE_WIDTH, self.HANDLE_HEIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 55))
        painter.drawRoundedRect(outer.translated(0, 1.5), radius, radius)
        painter.setBrush(QColor("white"))
        painter.drawRoundedRect(outer, radius, radius)
        inner = outer.adjusted(2.5, 2.5, -2.5, -2.5)
        painter.setBrush(self._handle_color(self.value()))
        painter.drawRoundedRect(inner, inner.width() / 2, inner.width() / 2)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self.palette().highlight().color(), 2))
            ring = outer.adjusted(-1, -1, 1, 1)
            painter.drawRoundedRect(ring, ring.width() / 2, ring.width() / 2)


class ColorSliders(QWidget):
    """Sliders de cor (matiz), saturação e brilho, sempre em sincronia com o serviço."""

    COLUMN_SPACING = 8

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(self.COLUMN_SPACING)
        layout.setVerticalSpacing(2)
        layout.setColumnMinimumWidth(0, label_width())
        layout.setColumnStretch(1, 1)

        self._hue = GradientSlider(lambda hue: QColor.fromHsv(hue, self._saturation_byte(), 255))
        self._hue.setRange(0, HUE_MAX)
        self._hue.setMinimumWidth(170)
        i18n.bind(self._hue.setAccessibleName, "slider.hue")
        self._hue.valueChanged.connect(self._on_color_slider)
        layout.addWidget(_bound_label("slider.hue"), 0, 0)
        layout.addWidget(self._hue, 0, 1, 1, 2)

        self._saturation = GradientSlider(lambda percent: QColor.fromHsv(self._hue.value(), round(percent * 255 / 100), 255))
        self._saturation.setRange(0, 100)
        i18n.bind(self._saturation.setAccessibleName, "slider.saturation")
        self._saturation.valueChanged.connect(self._on_color_slider)
        self._saturation_label = self._percent_label()
        layout.addWidget(_bound_label("slider.saturation"), 1, 0)
        layout.addWidget(self._saturation, 1, 1)
        layout.addWidget(self._saturation_label, 1, 2)

        self._brightness = GradientSlider(self._brightness_handle_color)
        self._brightness.setRange(0, 100)
        i18n.bind(self._brightness.setAccessibleName, "slider.brightness")
        self._brightness.valueChanged.connect(
            lambda percent: service.set_brightness(round(percent * 255 / 100))
        )
        self._brightness_label = self._percent_label()
        layout.addWidget(_bound_label("slider.brightness"), 2, 0)
        layout.addWidget(self._brightness, 2, 1)
        layout.addWidget(self._brightness_label, 2, 2)

        service.settings_changed.connect(self._sync)
        self._sync()

    @staticmethod
    def _percent_label() -> QLabel:
        label = QLabel()
        # Largura de "100%", com o texto alinhado à esquerda: o valor fica sempre à mesma
        # distância da barra, tenha ele um, dois ou três dígitos.
        label.setFixedWidth(label.fontMetrics().horizontalAdvance("100%"))
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return label

    def _saturation_byte(self) -> int:
        return round(self._saturation.value() * 255 / 100)

    def _value_channel(self) -> int:
        """Claridade (V) da cor atual; mantida ao mexer em matiz e saturação. Cor preta vira 255."""
        return QColor(*self._service.settings.color).value() or 255

    def _on_color_slider(self, _value: int = 0) -> None:
        self._service.set_color(hsv_color(self._hue.value(), self._saturation.value(), self._value_channel()))
        self._update_tracks()

    def _brightness_handle_color(self, percent: int) -> QColor:
        red, green, blue = self._service.settings.color
        scale = percent / 100
        return QColor(round(red * scale), round(green * scale), round(blue * scale))

    def _update_tracks(self) -> None:
        """Os degradês mostram o efeito do outro slider: o matiz na saturação atual e vice-versa."""
        saturation = self._saturation_byte()
        self._hue.set_stops([
            (i / 6, QColor.fromHsv(round(i / 6 * HUE_MAX), saturation, 255)) for i in range(7)
        ])
        self._saturation.set_stops([
            (0.0, QColor.fromHsv(self._hue.value(), 0, 255)),
            (1.0, QColor.fromHsv(self._hue.value(), 255, 255)),
        ])

    def _sync(self) -> None:
        settings = self._service.settings
        color = QColor(*settings.color)
        self._brightness.set_stops([(0.0, QColor(0, 0, 0)), (1.0, color)])
        # Só reposiciona matiz e saturação se a cor veio de outro lugar (cor pronta, outra aba):
        # fazer isso durante o arraste faria o slider pular por arredondamento. Numa cor sem
        # matiz (branco, cinza) o slider de matiz fica onde está.
        dragging = self._hue.isSliderDown() or self._saturation.isSliderDown()
        from_sliders = hsv_color(self._hue.value(), self._saturation.value(), self._value_channel())
        if not dragging and from_sliders != tuple(settings.color):
            if color.hsvHue() >= 0:
                _set_silently(self._hue, color.hsvHue())
            _set_silently(self._saturation, round(color.hsvSaturation() * 100 / 255))
        self._update_tracks()
        percent = round(settings.brightness * 100 / 255)
        _set_silently(self._brightness, percent)
        self._brightness_label.setText(f"{percent}%")
        self._saturation_label.setText(f"{self._saturation.value()}%")


def _labeled_row(label_key: str | None) -> tuple[QHBoxLayout, QLabel]:
    """Linha com o rótulo na mesma coluna dos sliders, para tudo ficar alinhado."""
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(ColorSliders.COLUMN_SPACING)
    text = _bound_label(label_key) if label_key else QLabel()
    text.setFixedWidth(label_width())
    layout.addWidget(text)
    return layout, text


def _add_spread(layout: QHBoxLayout, buttons: list[QToolButton]) -> None:
    """Distribui os botões em espaços iguais, do início ao fim da área dos sliders."""
    for index, button in enumerate(buttons):
        if index:
            layout.addStretch(1)
        layout.addWidget(button)


class ColorPalette(QWidget):
    """Seletor rápido: cores prontas, as cores criadas pelo usuário e um botão para criar outra."""

    COLUMNS = 8
    SWATCH = 20

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(6)
        for column in range(self.COLUMNS):
            self._grid.setColumnStretch(column, 1)
        self._colors: list[tuple[int, int, int]] | None = None
        self._buttons: dict[tuple[int, int, int], QToolButton] = {}
        service.settings_changed.connect(self._sync)
        # Os nomes das cores (dicas) mudam com o idioma: recria os botões.
        i18n.hub.changed.connect(self._relabel)
        self._sync()

    def _relabel(self) -> None:
        self._colors = None
        self._sync()

    def _rebuild(self, colors: list[tuple[int, int, int]]) -> None:
        while self._grid.count():
            widget = self._grid.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        names = {rgb: tr(f"color.{color_id}") for color_id, rgb in PRESETS.items()}
        self._buttons = {}
        for index, rgb in enumerate(colors):
            button = self._button()
            label = names.get(rgb) or "#{:02X}{:02X}{:02X}".format(*rgb)
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.clicked.connect(lambda _checked=False, rgb=rgb: self._service.set_color(rgb))
            self._grid.addWidget(button, index // self.COLUMNS, index % self.COLUMNS, Qt.AlignmentFlag.AlignCenter)
            self._buttons[rgb] = button

        add = self._button()
        add.setText("+")
        add.setToolTip(tr("color.new"))
        add.setAccessibleName(tr("color.new_name"))
        add.setStyleSheet(
            "QToolButton { background: palette(button); border: 1px dashed palette(mid);"
            f" border-radius: {self.SWATCH // 2}px; font-weight: bold; }}"
            "QToolButton:hover { border: 2px solid palette(highlight); }"
        )
        add.clicked.connect(lambda: save_current_color(self._service))
        index = len(colors)
        self._grid.addWidget(add, index // self.COLUMNS, index % self.COLUMNS, Qt.AlignmentFlag.AlignCenter)

    def _button(self) -> QToolButton:
        button = QToolButton()
        button.setFixedSize(self.SWATCH, self.SWATCH)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _sync(self) -> None:
        settings = self._service.settings
        colors = list(PRESETS.values()) + [tuple(c) for c in self._service.custom_colors]
        if colors != self._colors:
            self._colors = colors
            self._rebuild(colors)
        current = tuple(settings.color)
        radius = self.SWATCH // 2
        for (red, green, blue), button in self._buttons.items():
            border = "2px solid palette(highlight)" if (red, green, blue) == current else "1px solid palette(mid)"
            button.setStyleSheet(
                f"QToolButton {{ background: rgb({red}, {green}, {blue}); border: {border}; border-radius: {radius}px; }}"
                "QToolButton:hover { border: 2px solid palette(highlight); }"
            )


class ControllerTabs(QWidget):
    """Abas para escolher qual controle a interface controla; só aparecem com mais de um."""

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._bar = QTabBar()
        self._bar.setExpanding(True)
        self._bar.setDrawBase(False)
        self._bar.setUsesScrollButtons(False)
        i18n.bind(self._bar.setAccessibleName, "tabs.name")
        self._bar.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._bar)
        service.controllers_changed.connect(self._rebuild)
        i18n.hub.changed.connect(self._rebuild)  # "Controle N" muda com o idioma
        self._rebuild()

    def _rebuild(self) -> None:
        controllers = self._service.controllers
        self._bar.blockSignals(True)
        while self._bar.count():
            self._bar.removeTab(0)
        for number, controller in enumerate(controllers, start=1):
            label = f"{number} · {controller.connection}" if controller.connection else tr("tabs.controller", number=number)
            tab = self._bar.addTab(label)
            self._bar.setTabData(tab, controller.name)
            self._bar.setTabToolTip(tab, controller.uid)
            if controller.name == self._service.selected:
                self._bar.setCurrentIndex(tab)
        self._bar.blockSignals(False)
        self.setVisible(len(controllers) > 1)

    def _on_tab_changed(self, index: int) -> None:
        if index >= 0:
            self._service.select_controller(self._bar.tabData(index))


class PlayerRow(QWidget):
    """Número do jogador (1 a 5): acende o padrão de LEDs que o console usa para ele.

    Clicar no número já escolhido apaga os LEDs de jogador.
    """

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        layout, _ = _labeled_row("players.label")
        self.setLayout(layout)
        self._buttons = []
        for number in range(1, PLAYER_COUNT + 1):
            button = QToolButton()
            button.setCheckable(True)
            button.setFixedSize(22, 22)
            button.setText(str(number))
            i18n.bind(button.setToolTip, "players.tooltip", number=number)
            i18n.bind(button.setAccessibleName, "players.name", number=number)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QToolButton { background: palette(button); color: palette(button-text);"
                " border: 1px solid palette(mid); border-radius: 11px; font-weight: bold; }"
                "QToolButton:checked { background: palette(highlight); color: palette(highlighted-text);"
                " border: 1px solid palette(highlight); }"
                "QToolButton:hover { border: 2px solid palette(highlight); }"
                # Atribuído pelo app: o contorno tracejado mostra que não é uma escolha sua.
                "QToolButton:disabled { border: 1px dashed palette(mid); }"
                "QToolButton:disabled:checked { background: palette(highlight); color: palette(highlighted-text);"
                " border: 1px dashed palette(highlighted-text); }"
            )
            button.clicked.connect(lambda _checked=False, n=number: self._choose(n))
            self._buttons.append(button)
        _add_spread(layout, self._buttons)
        service.settings_changed.connect(self._sync)
        # Com 2 ou mais controles, o jogador de cada um passa a ser automático (ou deixa de ser).
        service.controllers_changed.connect(self._sync)
        i18n.hub.changed.connect(self._sync)  # a dica do modo automático muda com o idioma
        self._sync()

    def _choose(self, number: int) -> None:
        if player_number(self._service.players) == number:
            self._service.set_players(NO_PLAYER)
        else:
            self._service.set_players(pattern_for(number))

    def _sync(self) -> None:
        selected = player_number(self._service.players)
        automatic = self._service.players_assigned_automatically
        self.setEnabled(not automatic)
        self.setToolTip(tr("players.auto_tooltip") if automatic else "")
        for number, button in enumerate(self._buttons, start=1):
            button.setChecked(number == selected)


class ToggleSwitch(QAbstractButton):
    """Interruptor liga/desliga, com as cores do tema (ligado usa a cor de destaque)."""

    WIDTH = 38
    HEIGHT = 22

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self.WIDTH, self.HEIGHT)

    def sizeHint(self) -> QSize:
        return QSize(self.WIDTH, self.HEIGHT)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        on = self.isChecked()
        if on:
            track_color = palette.highlight().color()
        else:
            # Cor de texto translúcida: a cor "mid" do tema pode ser igual ao fundo do menu e sumir.
            track_color = palette.windowText().color()
            track_color.setAlpha(90)
        if not self.isEnabled():
            track_color.setAlpha(min(track_color.alpha(), 110))
        track = QRectF(1, 3, self.width() - 2, self.height() - 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)

        knob = self.height() - 4
        x = self.width() - knob - 2 if on else 2
        painter.setBrush(QColor(0, 0, 0, 50))
        painter.drawEllipse(QRectF(x, 3, knob, knob))
        painter.setBrush(QColor("white"))
        painter.drawEllipse(QRectF(x, 2, knob, knob))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(palette.highlight().color(), 1.5))
            painter.drawRoundedRect(track.adjusted(-1, -2, 1, 2), self.height() / 2, self.height() / 2)


class SwitchRow(QWidget):
    """Texto com um indicador à direita (interruptor por padrão); clicar no texto também alterna.

    `read` diz o estado atual e `write` grava um novo; o indicador sempre volta a mostrar
    o que `read` retorna, então ele nunca fica diferente do que está salvo.
    """

    def __init__(
        self,
        text_key: str,
        tooltip_key: str,
        read: Callable[[], bool],
        write: Callable[[bool], None],
        parent: QWidget | None = None,
        indicator: type[QAbstractButton] = ToggleSwitch,
    ):
        super().__init__(parent)
        self._read = read
        self._write = write
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel()
        i18n.bind(label.setText, text_key)
        i18n.bind(label.setToolTip, tooltip_key)
        layout.addWidget(label, 1)
        self._switch = indicator()
        i18n.bind(self._switch.setAccessibleName, text_key)
        i18n.bind(self._switch.setToolTip, tooltip_key)
        self._switch.clicked.connect(self._on_clicked)
        layout.addWidget(self._switch)
        self._sync()

    def showEvent(self, event) -> None:
        self._sync()
        super().showEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            self.isEnabled()
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self._switch.click()
        else:
            super().mouseReleaseEvent(event)

    def _sync(self) -> None:
        self._switch.setChecked(self._read())

    def _on_clicked(self, checked: bool) -> None:
        try:
            self._write(checked)
        except OSError as error:
            logging.getLogger(__name__).warning("Falha ao salvar a opção: %s", error)
        self._sync()


class LanguageRow(QWidget):
    """Menu de seleção do idioma da interface; a troca vale na hora e fica salva."""

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_bound_label("window.language"), 1)
        self._combo = QComboBox()
        # Cada idioma aparece no próprio idioma, para quem não entende o atual achar o seu.
        for code, name in i18n.LANGUAGES.items():
            self._combo.addItem(name, code)
        i18n.bind(self._combo.setAccessibleName, "window.language")
        self._combo.currentIndexChanged.connect(self._on_changed)
        layout.addWidget(self._combo)
        i18n.hub.changed.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        index = self._combo.findData(self._service.language)
        if index >= 0 and index != self._combo.currentIndex():
            self._combo.blockSignals(True)
            self._combo.setCurrentIndex(index)
            self._combo.blockSignals(False)

    def _on_changed(self, index: int) -> None:
        self._service.set_language(self._combo.itemData(index))


class DisconnectRow(QWidget):
    """Botão para desconectar o controle selecionado; só aparece para controles Bluetooth."""

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        button = QPushButton()
        i18n.bind(button.setText, "controller.disconnect")
        i18n.bind(button.setToolTip, "controller.disconnect_tip")
        button.clicked.connect(service.disconnect_selected)
        layout.addWidget(button)
        service.controllers_changed.connect(self._sync)
        service.settings_changed.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        self.setVisible(self._service.can_disconnect)


class LogsRow(QWidget):
    """Linha do grupo "Geral" que abre a janela de logs."""

    def __init__(self, open_logs: Callable[[], None], parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = _bound_label("log.row")
        i18n.bind(label.setToolTip, "log.row_tip")
        layout.addWidget(label, 1)
        button = QPushButton()
        i18n.bind(button.setText, "log.open")
        button.clicked.connect(lambda: open_logs())
        layout.addWidget(button)


class CompactToggleSwitch(ToggleSwitch):
    """Interruptor menor, para linhas onde o tamanho normal pesaria demais."""

    WIDTH = 30
    HEIGHT = 16


class AutostartRow(SwitchRow):
    """Iniciar com o sistema; o estado é o próprio arquivo em ~/.config/autostart."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "row.autostart",
            "row.autostart_tip",
            autostart.is_enabled,
            autostart.set_enabled,
            parent,
        )


class MuteLedRow(SwitchRow):
    """LED do botão de microfone do controle selecionado, com um interruptor compacto."""

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(
            "row.mute_led",
            "row.mute_led_tip",
            lambda: service.settings.mute_led,
            service.set_mute_led,
            parent,
            indicator=CompactToggleSwitch,
        )
        # Cada controle tem o seu estado; trocar de aba ou aplicar de outro lugar atualiza o interruptor.
        service.settings_changed.connect(self._sync)


class AutoPlayersRow(SwitchRow):
    """Com 2 ou mais controles, cada um acende sozinho o LED de jogador da sua posição."""

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(
            "row.auto_players",
            "row.auto_players_tip",
            lambda: service.auto_players,
            service.set_auto_players,
            parent,
        )


class CloseToTrayRow(SwitchRow):
    """Ligado: fechar a janela a manda para a bandeja. Desligado: fechar encerra o app."""

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(
            "row.close_to_tray",
            "row.close_to_tray_tip",
            lambda: service.close_to_tray,
            service.set_close_to_tray,
            parent,
        )


class EmulationRow(SwitchRow):
    """Liga e desliga a emulação de Xbox 360 para o controle da aba selecionada.

    O processo (ver `emulation.py`) roda enquanto houver algum controle marcado; a escolha de cada
    controle fica salva por MAC no serviço, para o app religá-la ao abrir.
    """

    def __init__(self, service: LedService, emulation, parent: QWidget | None = None, compact: bool = False):
        def read() -> bool:
            uid = service.selected_uid
            return uid is not None and service.emulation_for(uid)

        def write(on: bool) -> None:
            uid = service.selected_uid
            if uid is not None:
                service.set_emulation_for(uid, on)
            emulation.set_running(service.emulation)

        super().__init__(
            "row.emulation",
            "row.emulation_tip",
            read,
            write,
            parent,
            indicator=CompactToggleSwitch if compact else ToggleSwitch,
        )
        # Trocar de aba, o processo cair ou outro lugar mudar a escolha: o interruptor acompanha.
        self._service = service
        for signal in (service.settings_changed, service.controllers_changed, emulation.changed):
            signal.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        service = getattr(self, "_service", None)  # o __init__ do SwitchRow já chama _sync
        if service is not None:
            self.setEnabled(service.selected_uid is not None)  # sem controle conectado não há o que marcar
        super()._sync()


def _set_silently(slider: QSlider, value: int) -> None:
    # Evita que a atualização vinda do serviço volte como um novo comando do slider.
    slider.blockSignals(True)
    slider.setValue(value)
    slider.blockSignals(False)
