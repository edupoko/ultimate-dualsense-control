"""Janela para ler o registro de funcionamento (logs) sem sair do app."""

from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QGuiApplication, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import i18n, logs

REFRESH_MS = 1000
# Mostra só o fim do arquivo: um log grande deixaria a janela lenta.
VIEW_BYTES = 256 * 1024

FILTER_ALL = "all"
FILTER_PROBLEMS = "problems"


class LogHighlighter(QSyntaxHighlighter):
    """Avisos em âmbar e erros em vermelho; o resto fica na cor normal."""

    def __init__(self, document):
        super().__init__(document)
        self._warning = QTextCharFormat()
        self._warning.setForeground(QColor("#d9a23b"))
        self._error = QTextCharFormat()
        self._error.setForeground(QColor("#e5534b"))

    def highlightBlock(self, text: str) -> None:
        if " ERROR " in text[:40] or " CRITICAL " in text[:40]:
            self.setFormat(0, len(text), self._error)
        elif " WARNING " in text[:40]:
            self.setFormat(0, len(text), self._warning)


class LogWindow(QDialog):
    """Mostra o log com atualização automática; permite filtrar, copiar, abrir a pasta e limpar."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        i18n.bind(self.setWindowTitle, "log.title")
        self.resize(820, 480)

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        show = QLabel()
        i18n.bind(show.setText, "log.show")
        top.addWidget(show)
        self._filter = QComboBox()
        self._filter.currentIndexChanged.connect(self.refresh)
        top.addWidget(self._filter)
        top.addStretch(1)
        self._path = QLabel(str(logs.log_path()))
        self._path.setEnabled(False)
        self._path.setTextInteractionFlags(self._path.textInteractionFlags() | self._path.textInteractionFlags().TextSelectableByMouse)
        top.addWidget(self._path)
        layout.addLayout(top)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._highlighter = LogHighlighter(self._view.document())
        layout.addWidget(self._view, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for key, action in (("log.copy", self._copy), ("log.open_folder", self._open_folder), ("log.clear", self._clear)):
            button = QPushButton()
            i18n.bind(button.setText, key)
            button.clicked.connect(action)
            buttons.addWidget(button)
        close = QPushButton()
        i18n.bind(close.setText, "window.close")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self._fill_filter()
        i18n.hub.changed.connect(self._fill_filter)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._shown_text: str | None = None
        self.refresh()

    def _fill_filter(self) -> None:
        current = self._filter.currentData() or FILTER_ALL
        self._filter.blockSignals(True)
        self._filter.clear()
        self._filter.addItem(i18n.tr("log.filter_all"), FILTER_ALL)
        self._filter.addItem(i18n.tr("log.filter_problems"), FILTER_PROBLEMS)
        self._filter.setCurrentIndex(max(0, self._filter.findData(current)))
        self._filter.blockSignals(False)

    def current_text(self) -> str:
        text = logs.read_log(VIEW_BYTES)
        if self._filter.currentData() == FILTER_PROBLEMS:
            text = logs.problems_only(text)
        return text

    def refresh(self) -> None:
        text = self.current_text()
        if text == self._shown_text:
            return
        bar = self._view.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 2
        self._shown_text = text
        self._view.setPlainText(text or i18n.tr("log.empty"))
        if at_end:  # acompanha o fim, como um "tail -f", mas não puxa quem rolou para cima
            bar.setValue(bar.maximum())

    def showEvent(self, event) -> None:
        self._timer.start(REFRESH_MS)
        self._shown_text = None
        self.refresh()
        bar = self._view.verticalScrollBar()
        bar.setValue(bar.maximum())
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.current_text())

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs.log_dir())))

    def _clear(self) -> None:
        logs.clear_log()
        self.refresh()
