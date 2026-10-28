"""Registro de funcionamento (logs): arquivo com rotação, erros do Python e do Qt, e travamentos.

O arquivo fica em ~/.local/state/dualsense-ultimate-control/ (ou em $XDG_STATE_HOME). Assim os logs existem
também quando o app abre pelo menu ou no início do sistema, onde não há terminal para vê-los.
"""

from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import os
import re
import sys
from pathlib import Path

APP_DIR = "dualsense-ultimate-control"
ACTIONS_LOGGER = "dualsense_ultimate_control.actions"  # igual a `actions.LOGGER_NAME`; repetido para não importar o Qt aqui
LOG_NAME = "dualsense-ultimate-control.log"
CRASH_NAME = "crash.log"
MAX_BYTES = 512 * 1024
BACKUPS = 3
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Um registro começa com a data; o que vem depois (ex.: traceback) pertence ao registro anterior.
_ENTRY_START = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ")
_PROBLEM = re.compile(r"^\S+ \S+ (WARNING|ERROR|CRITICAL) ")
_ACTION = re.compile(r"^\S+ \S+ \S+ " + re.escape(ACTIONS_LOGGER) + ": ")

_HANDLER_TAG = "_dualsense_ultimate_control_handler"
_crash_file = None  # mantido aberto enquanto o processo vive


def log_dir() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / APP_DIR


def log_path() -> Path:
    return log_dir() / LOG_NAME


def crash_path() -> Path:
    return log_dir() / CRASH_NAME


def setup_logging(level: int = logging.INFO, install_hooks: bool = True) -> Path:
    """Liga o registro em arquivo (e no terminal). Pode ser chamado de novo sem duplicar linhas."""
    global _crash_file
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_TAG, False):
            root.removeHandler(handler)
            handler.close()
    formatter = logging.Formatter(FORMAT, DATE_FORMAT)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path(), maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
    )
    stream_handler = logging.StreamHandler()
    for handler in (file_handler, stream_handler):
        handler.setFormatter(formatter)
        setattr(handler, _HANDLER_TAG, True)
        root.addHandler(handler)
    root.setLevel(level)

    if install_hooks:
        sys.excepthook = _log_uncaught_exception
        _install_qt_handler()
        # Travamentos nativos (segfault) não passam pelo logging: o Python escreve o rastro aqui.
        if _crash_file is None:
            _crash_file = open(crash_path(), "a", encoding="utf-8")
            faulthandler.enable(_crash_file)
    return log_path()


def _log_uncaught_exception(kind, value, traceback) -> None:
    if issubclass(kind, KeyboardInterrupt):
        sys.__excepthook__(kind, value, traceback)
        return
    logging.getLogger("dualsense_ultimate_control").critical("Erro não tratado", exc_info=(kind, value, traceback))


# Avisos do Qt que aparecem por causa de misturar o Qt do pip com os plugins do KDE do sistema
# (veja kdetheme.py). Não indicam problema, então não devem poluir o filtro "avisos e erros".
_HARMLESS_QT_WARNINGS = ("Could not find any platform plugin", 'Icon theme "gnome" not found')


def qt_level(message_type, message: str) -> int:
    """Nível do `logging` para uma mensagem do Qt."""
    from PySide6.QtCore import QtMsgType

    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }
    level = levels.get(message_type, logging.WARNING)
    if level == logging.WARNING and any(text in message for text in _HARMLESS_QT_WARNINGS):
        return logging.DEBUG
    return level


def _install_qt_handler() -> None:
    from PySide6.QtCore import qInstallMessageHandler

    def handler(kind, context, message) -> None:
        # A categoria do Qt (ex.: "qt.qpa.plugin") vira parte do nome, para saber de onde veio.
        category = getattr(context, "category", None)
        name = "qt" if not category or category == "default" else f"qt.{category}".replace("qt.qt.", "qt.")
        logging.getLogger(name).log(qt_level(kind, message), message)

    qInstallMessageHandler(handler)


def read_log(max_bytes: int = 256 * 1024, path: Path | None = None) -> str:
    """O fim do arquivo de log (até `max_bytes`), começando numa linha inteira."""
    path = path or log_path()
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - max_bytes))
            data = stream.read()
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    if size > max_bytes and "\n" in text:
        text = text.split("\n", 1)[1]  # a primeira linha foi cortada no meio
    return text


def problems_only(text: str) -> str:
    """Só os registros de aviso e erro (com os traceback deles); o resto é descartado."""
    kept: list[str] = []
    keep = False
    for line in text.splitlines():
        if _ENTRY_START.match(line):
            keep = bool(_PROBLEM.match(line))
        if keep:
            kept.append(line)
    return "\n".join(kept) + ("\n" if kept else "")


def is_action_line(line: str) -> bool:
    return bool(_ACTION.match(line))


def actions_only(text: str) -> str:
    """Só as ações do usuário no controle (logger `...actions`); o resto é descartado."""
    kept = [line for line in text.splitlines() if is_action_line(line)]
    return "\n".join(kept) + ("\n" if kept else "")


def clear_log(path: Path | None = None) -> None:
    """Esvazia o arquivo atual (os arquivos antigos da rotação ficam)."""
    (path or log_path()).write_text("", encoding="utf-8")
