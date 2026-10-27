"""Faixa de pergunta dentro da própria janela, no lugar de caixas de diálogo."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import i18n
from .i18n import tr


class ConfirmBar(QFrame):
    """Texto com botões Sim/Não (ou só OK), que some ao ser respondido.

    Responde por callbacks, não por valor de retorno: a pergunta não bloqueia a janela."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("ConfirmBar { background: palette(alternate-base); }")
        layout = QHBoxLayout(self)
        self._text = QLabel()
        self._text.setWordWrap(True)
        layout.addWidget(self._text, 1)
        self._yes = QPushButton()
        self._no = QPushButton()
        layout.addWidget(self._yes)
        layout.addWidget(self._no)
        self._on_yes: Callable[[], None] | None = None
        self._on_no: Callable[[], None] | None = None
        self._yes.clicked.connect(lambda: self._answer(True))
        self._no.clicked.connect(lambda: self._answer(False))
        self.hide()

    def ask(self, text: str, on_yes: Callable[[], None], on_no: Callable[[], None] | None = None) -> None:
        """Mostra a pergunta; uma nova pergunta substitui a anterior (que fica sem resposta)."""
        self._show(text, on_yes, on_no, "confirm.yes", "confirm.no")

    def notify(self, text: str) -> None:
        """Mostra um aviso com um único botão OK."""
        self._show(text, None, None, "confirm.ok", None)

    def _show(self, text, on_yes, on_no, yes_key: str, no_key: str | None) -> None:
        self._on_yes, self._on_no = on_yes, on_no
        self._text.setText(text)
        self._yes.setText(tr(yes_key))
        self._no.setText(tr(no_key) if no_key else "")
        self._no.setVisible(no_key is not None)
        self.show()

    def dismiss(self) -> None:
        self._on_yes = self._on_no = None
        self.hide()

    def _answer(self, yes: bool) -> None:
        callback = self._on_yes if yes else self._on_no
        self.dismiss()
        if callback is not None:
            callback()


class HelpPanel(QFrame):
    """Explicação com botões de ação, aberta dentro da página (ex.: "Como resolver…" da Steam)."""

    def __init__(self, title: str, text: str, info: str, actions: list[tuple[str, Callable[[], None]]], parent: QWidget | None = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("HelpPanel { background: palette(alternate-base); }")
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        for body in (text, info):
            label = QLabel(body)
            label.setWordWrap(True)
            layout.addWidget(label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for label, callback in actions:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, callback=callback: self._run(callback))
            buttons.addWidget(button)
        close = QPushButton()
        i18n.bind(close.setText, "confirm.close")
        close.clicked.connect(self.close_panel)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _run(self, callback: Callable[[], None]) -> None:
        self.close_panel()
        callback()

    def close_panel(self) -> None:
        self.hide()
        self.deleteLater()
