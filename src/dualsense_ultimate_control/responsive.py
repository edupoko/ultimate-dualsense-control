"""Disposição que se adapta à largura: duas colunas na janela larga, uma sobre a outra na estreita."""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QBoxLayout, QVBoxLayout, QWidget

from . import theme


class Columns(QWidget):
    """`first` à esquerda e `second` à direita a partir de `min_width` px; abaixo disso, empilhados.

    O mínimo informado é o da forma empilhada: assim a janela sempre pode encolher até voltar a
    uma coluna. Quem usa escolhe `min_width` maior que a soma dos mínimos das duas colunas."""

    mode_changed = Signal(bool)  # True = duas colunas

    def __init__(
        self,
        first: QWidget,
        second: QWidget,
        min_width: int = theme.TWO_COLUMNS_MIN_WIDTH,
        stretch: tuple[int, int] = (1, 1),
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._min_width = min_width
        self._first, self._second = first, second
        self._layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(first, stretch[0])
        self._layout.addWidget(second, stretch[1])
        self._wide = False

    @property
    def wide(self) -> bool:
        return self._wide

    def minimumSizeHint(self) -> QSize:
        hint = self._layout.minimumSize()
        narrow = max(self._first.minimumSizeHint().width(), self._first.minimumWidth(),
                     self._second.minimumSizeHint().width(), self._second.minimumWidth())
        return QSize(narrow, hint.height())

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.set_width(event.size().width())
        super().resizeEvent(event)

    def set_width(self, width: int) -> None:
        wide = width >= self._min_width
        if wide == self._wide:
            return
        self._wide = wide
        self._layout.setDirection(QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom)
        self._layout.setSpacing(theme.COLUMN_SPACING if wide else -1)
        self.updateGeometry()
        self.mode_changed.emit(wide)


def stack(*widgets: QWidget, stretch: tuple[int, ...] | None = None) -> QWidget:
    """Junta widgets numa coluna sem margens (para servir de lado de um `Columns`)."""
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, stretch[index] if stretch else 0)
    return holder
