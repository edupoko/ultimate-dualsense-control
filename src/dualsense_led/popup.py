"""Menu da bandeja como janela própria, que some sozinha quando o foco sai do app.

Um QMenu comum é um popup com captura de mouse e teclado. No XWayland essa captura não
é desfeita quando uma janela Wayland ganha o foco (a captura de tela do KDE, por exemplo),
e o menu fica visível por cima de tudo. Uma janela comum recebe o aviso de que perdeu o
foco, então basta escondê-la nesse momento. Os itens são desenhados pelo estilo do sistema
(CE_MenuItem), então o visual continua o de um menu nativo.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QEnterEvent, QKeyEvent, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QApplication,
    QSizePolicy,
    QStyle,
    QStyleOption,
    QStyleOptionFrame,
    QStyleOptionMenuItem,
    QVBoxLayout,
    QWidget,
)

from .widgets import ROW_MARGINS, tray_corner_position

# Depois de fechar por perda de foco, um clique no ícone da bandeja (que foi o que tirou o
# foco) deve só fechar o menu, não abri-lo de novo.
REOPEN_GUARD_SECONDS = 0.35


class MenuItem(QWidget):
    """Item de texto desenhado como um item de menu nativo do estilo atual."""

    clicked = Signal()

    def __init__(self, text: str, enabled: bool = True, expandable: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._text = text
        self._expandable = expandable
        self._hover = False
        self.setEnabled(enabled)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_text(self, text: str) -> None:
        self._text = text
        self.updateGeometry()
        self.update()

    def _option(self) -> QStyleOptionMenuItem:
        option = QStyleOptionMenuItem()
        option.initFrom(self)
        # O tipo de submenu faz o estilo desenhar a seta de "abre mais opções" à direita.
        option.menuItemType = (
            QStyleOptionMenuItem.MenuItemType.SubMenu if self._expandable else QStyleOptionMenuItem.MenuItemType.Normal
        )
        option.checkType = QStyleOptionMenuItem.CheckType.NotCheckable
        option.text = self._text
        option.menuHasCheckableItems = False
        option.maxIconWidth = 0
        option.reservedShortcutWidth = 0
        option.menuRect = self.rect()
        if self._hover and self.isEnabled():
            option.state |= QStyle.StateFlag.State_Selected
        return option

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        content = QSize(metrics.horizontalAdvance(self._text), metrics.height())
        return self.style().sizeFromContents(QStyle.ContentsType.CT_MenuItem, self._option(), content, self)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_MenuItem, self._option(), painter, self)

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class MenuSeparator(QWidget):
    """Linha separadora desenhada pelo estilo, como as dos menus nativos."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _option(self) -> QStyleOptionMenuItem:
        option = QStyleOptionMenuItem()
        option.initFrom(self)
        option.menuItemType = QStyleOptionMenuItem.MenuItemType.Separator
        option.menuRect = self.rect()
        return option

    def sizeHint(self) -> QSize:
        return self.style().sizeFromContents(QStyle.ContentsType.CT_MenuItem, self._option(), QSize(0, 0), self)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_MenuItem, self._option(), painter, self)


class TrayPopup(QWidget):
    """Janela sem moldura, no estilo de um menu, aberta junto à bandeja."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        style = self.style()
        panel = style.pixelMetric(QStyle.PixelMetric.PM_MenuPanelWidth, None, self)
        horizontal = panel + style.pixelMetric(QStyle.PixelMetric.PM_MenuHMargin, None, self)
        vertical = panel + style.pixelMetric(QStyle.PixelMetric.PM_MenuVMargin, None, self)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(horizontal, vertical, horizontal, vertical)
        self._layout.setSpacing(0)
        self._rows: list[QWidget] = []
        self._hidden_at = 0.0

    def add_item(self, text: str, callback: Callable[[], None] | None = None, enabled: bool = True) -> MenuItem:
        item = MenuItem(text, enabled)
        if callback is not None:
            # Fecha antes de agir: a ação pode abrir um diálogo ou encerrar o app.
            item.clicked.connect(lambda: (self.hide(), QTimer.singleShot(0, callback)))
        self._layout.addWidget(item)
        return item

    def add_expander(self, text: str, content: QWidget) -> MenuItem:
        """Item que mostra ou esconde `content` logo abaixo, sem fechar o menu."""
        header = MenuItem(text, expandable=True)
        content.setVisible(False)
        header.clicked.connect(lambda: self._set_expanded(content, not content.isVisible()))
        self._layout.addWidget(header)
        self._rows.append(content)
        self._layout.addWidget(content)
        return header

    def _set_expanded(self, content: QWidget, expanded: bool) -> None:
        content.setVisible(expanded)
        self._refit()

    def add_separator(self) -> None:
        self._layout.addWidget(MenuSeparator())

    def add_row(self, widget: QWidget) -> None:
        self._rows.append(widget)
        self._layout.addWidget(widget)

    def align_rows(self, reference: MenuItem) -> None:
        """Faz rótulos das linhas com widgets começarem onde o texto dos itens começa."""
        _, top, right, bottom = ROW_MARGINS
        indent = self._text_indent(reference)
        for widget in self._rows:
            widget.setContentsMargins(indent, top, right, bottom)

    def _text_indent(self, item: MenuItem) -> int:
        # Cada estilo reserva uma coluna de ícones diferente; medir o item pintado
        # evita fixar um valor que só serve para um tema.
        self.ensurePolished()
        self.adjustSize()
        self._layout.activate()
        image = item.grab().toImage()
        height = image.height()
        background = image.pixelColor(0, height // 2)
        for x in range(1, image.width()):
            for y in range(2, max(2, height - 2)):
                color = image.pixelColor(x, y)
                difference = (
                    abs(color.red() - background.red())
                    + abs(color.green() - background.green())
                    + abs(color.blue() - background.blue())
                    + abs(color.alpha() - background.alpha())
                )
                if difference > 90:
                    return x
        return ROW_MARGINS[0]

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        elif time.monotonic() - self._hidden_at >= REOPEN_GUARD_SECONDS:
            self.popup()

    def popup(self) -> None:
        self._place()
        self.show()
        self.raise_()
        self.activateWindow()

    def _place(self) -> None:
        self.adjustSize()
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        self.move(tray_corner_position(self.size(), screen.geometry(), screen.availableGeometry()))

    def _refit(self) -> None:
        """Reajusta o tamanho e mantém o canto junto à bandeja quando o conteúdo muda."""
        if self.isVisible():
            self._layout.activate()
            self._place()

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.LayoutRequest and self.isVisible():
            QTimer.singleShot(0, self._refit_if_resized)
        return super().event(event)

    def _refit_if_resized(self) -> None:
        if self.isVisible() and self.size() != self.sizeHint():
            self._place()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        style = self.style()
        panel = QStyleOption()
        panel.initFrom(self)
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelMenu, panel, painter, self)
        frame = QStyleOptionFrame()
        frame.initFrom(self)
        frame.lineWidth = style.pixelMetric(QStyle.PixelMetric.PM_MenuPanelWidth, None, self)
        style.drawPrimitive(QStyle.PrimitiveElement.PE_FrameMenu, frame, painter, self)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isVisible() and not self.isActiveWindow():
            QTimer.singleShot(60, self._hide_if_unfocused)

    def _hide_if_unfocused(self) -> None:
        if self.isVisible() and not self.isActiveWindow():
            self.hide()

    def hideEvent(self, event) -> None:
        self._hidden_at = time.monotonic()
        super().hideEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)
