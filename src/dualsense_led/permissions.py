"""Instalação da regra udev que libera os LEDs para o usuário, pedindo a senha pelo polkit."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from .i18n import tr

log = logging.getLogger(__name__)

RULE_NAME = "70-dualsense-led.rules"
RULE_SOURCE = Path(__file__).with_name("data") / RULE_NAME
RULE_TARGET = Path("/etc/udev/rules.d") / RULE_NAME

# Instala a regra e reaplica nos controles já conectados, sem precisar reconectar.
_INSTALL_SCRIPT = (
    'install -m 0644 "$1" "$2"'
    " && udevadm control --reload"
    " && udevadm trigger --action=add --subsystem-match=leds"
    " --sysname-match='input*:rgb:indicator' --sysname-match='input*:white:player-*'"
    " && udevadm settle"
)

# Códigos de saída do pkexec quando a senha é cancelada ou recusada.
_PKEXEC_DENIED = {126, 127}


def rule_installed(target: Path = RULE_TARGET, source: Path = RULE_SOURCE) -> bool:
    """True se a regra instalada existe e é igual à versão do app."""
    try:
        return target.read_bytes() == source.read_bytes()
    except OSError:
        return False


def install_arguments() -> list[str]:
    return ["/bin/sh", "-c", _INSTALL_SCRIPT, "sh", str(RULE_SOURCE), str(RULE_TARGET)]


class RuleInstaller(QObject):
    """Roda a instalação via pkexec: a senha é digitada na janela do sistema, nunca no app."""

    finished = Signal(bool, str)

    def __init__(self, program: str = "pkexec"):
        super().__init__()
        self._program = program
        self._process: QProcess | None = None

    @property
    def running(self) -> bool:
        return self._process is not None

    def start(self) -> None:
        if self.running:
            return
        if shutil.which(self._program) is None:
            self.finished.emit(False, tr("permissions.not_found", program=self._program))
            return
        self._process = QProcess(self)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._process.start(self._program, install_arguments())

    def _on_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        error = process.readAllStandardError().data().decode(errors="replace").strip()
        process.deleteLater()
        if exit_code == 0:
            log.info("Regra udev instalada")
            self.finished.emit(True, tr("permissions.done"))
        elif exit_code in _PKEXEC_DENIED:
            log.info("Instalação da regra udev cancelada (código %s)", exit_code)
            self.finished.emit(False, tr("permissions.denied"))
        else:
            log.warning("Falha ao instalar a regra udev (código %s): %s", exit_code, error)
            self.finished.emit(False, tr("permissions.failed", error=error or tr("permissions.exit_code", code=exit_code)))

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error != QProcess.ProcessError.FailedToStart:
            return
        process, self._process = self._process, None
        if process is not None:
            process.deleteLater()
        self.finished.emit(False, tr("permissions.cannot_run", program=self._program))
