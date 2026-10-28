"""Diálogos do app, conforme a política de janelas (F5.3).

- Faixa na página (`confirm.ConfirmBar`): aviso ou pergunta leve e reversível.
- `ask_irreversible`: diálogo modal para ação que não se desfaz ou que grava no controle
  (gravar a calibração, reiniciar o controle, excluir perfil), com "Cancelar" como padrão.
- `PanelDialog`: janela própria para tarefa longa que pede foco (Teste rápido, calibração dos
  analógicos e do giroscópio), com título traduzido, botão Fechar e Esc para fechar.
A navegação entre páginas continua dentro da janela principal.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import i18n, theme
from .i18n import tr

APP_TITLE = "DualSense Ultimate Control"


def _fit_to_screen(dialog: QDialog, width: int, height: int) -> None:
    screen = dialog.screen().availableGeometry() if dialog.screen() is not None else None
    if screen is not None:
        width, height = min(width, screen.width() - 40), min(height, screen.height() - 60)
    dialog.resize(max(width, dialog.minimumSizeHint().width()), max(height, dialog.minimumSizeHint().height()))


class IrreversibleDialog(QDialog):
    """Pergunta com "Cancelar" (padrão, com o foco) e o botão da ação; Esc cancela."""

    def __init__(self, text: str, action_text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(APP_TITLE)
        self.setModal(True)
        layout = QVBoxLayout(self)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setMinimumWidth(360)
        layout.addWidget(label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.action_button = QPushButton(action_text)
        self.action_button.setAutoDefault(False)
        self.action_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton(tr("confirm.cancel"))
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.action_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self.cancel_button.setFocus()


def ask_irreversible(parent: QWidget | None, text: str, action_text: str) -> bool:
    """Pergunta modal; True só se o usuário escolheu a ação. Os testes substituem esta função."""
    dialog = IrreversibleDialog(text, action_text, parent)
    try:
        return dialog.exec() == QDialog.DialogCode.Accepted
    finally:
        dialog.deleteLater()


class PanelDialog(QDialog):
    """Janela própria de um painel da página de teste; o painel continua pertencendo à página.

    Abre com `open()` (não bloqueia: a página segue lendo o controle e repassando o estado) e é
    modal para a janela principal, então o usuário não troca de página com ela aberta."""

    def __init__(self, title_key: str, content: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        i18n.bind(lambda text: self.setWindowTitle(f"{text} — {APP_TITLE}"), title_key)
        self.content = content
        layout = QVBoxLayout(self)
        layout.addWidget(content, 1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        close = QPushButton()
        i18n.bind(close.setText, "confirm.close")
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        layout.addLayout(footer)
        self._sized = False

    def open(self) -> None:
        if not self._sized:
            self._sized = True
            # Largura pela dica do conteúdo; altura padrão (o conteúdo que sobra rola por dentro).
            _fit_to_screen(self, max(self.sizeHint().width(), theme.DIALOG_DEFAULT_SIZE[0]), theme.DIALOG_DEFAULT_SIZE[1])
        super().open()
