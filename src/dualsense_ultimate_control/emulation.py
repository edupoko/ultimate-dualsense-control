"""Liga e desliga a emulação de Xbox 360, que roda num processo separado (`dualsense_ultimate_control.emulator`).

Processo à parte porque a emulação não usa o Qt e precisa seguir repassando eventos mesmo com
a interface ocupada; parar o processo solta o grab e some com os controles virtuais.
"""

from __future__ import annotations

import logging
import subprocess
import sys

from PySide6.QtCore import QObject, QProcess, Signal

log = logging.getLogger(__name__)

# Quanto esperar o processo encerrar sozinho (SIGTERM) antes de forçar.
STOP_TIMEOUT_MS = 3000

SERVICE_UNIT = "dualsense-ultimate-control-emulator.service"


def service_active(unit: str = SERVICE_UNIT) -> bool:
    """True se o serviço systemd de usuário da emulação está rodando (ver scripts/install-service.sh)."""
    try:
        result = subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit], timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


class EmulationProcess(QObject):
    """Dono do processo da emulação; `changed` avisa quando ligou ou desligou."""

    changed = Signal()
    # O processo terminou sem ninguém pedir; o texto é a última linha que ele registrou.
    failed = Signal(str)

    def __init__(
        self,
        program: str = sys.executable,
        arguments: list[str] | None = None,
        parent: QObject | None = None,
        service_probe=service_active,
    ):
        super().__init__(parent)
        self._service_probe = service_probe
        self._program = program
        self._arguments = ["-m", "dualsense_ultimate_control.emulator"] if arguments is None else arguments
        self._process: QProcess | None = None
        self._stopping = False
        self._last_line = ""

    @property
    def running(self) -> bool:
        return self._process is not None

    def set_running(self, on: bool) -> None:
        if on:
            self.start()
        else:
            self.stop()

    def start(self) -> None:
        if self._process is not None:
            return
        if self._service_probe():
            # O serviço já assume os controles marcados (relê o settings.json); um segundo daemon só brigaria pelo grab.
            log.info("O serviço %s já está rodando: o app não liga outro emulador", SERVICE_UNIT)
            return
        process = QProcess(self)
        process.setProgram(self._program)
        process.setArguments(self._arguments)
        process.readyReadStandardError.connect(self._read_log)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self._process = process
        self._stopping = False
        self._last_line = ""
        log.info("Ligando a emulação de Xbox 360")
        process.start()
        self.changed.emit()

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        self._stopping = True
        log.info("Desligando a emulação de Xbox 360")
        process.terminate()  # SIGTERM: o emulador solta os controles antes de sair
        if not process.waitForFinished(STOP_TIMEOUT_MS):
            process.kill()
            process.waitForFinished(STOP_TIMEOUT_MS)
        self._forget()

    def _read_log(self) -> None:
        if self._process is None:
            return
        text = bytes(self._process.readAllStandardError()).decode(errors="replace")
        for line in text.splitlines():
            if line.strip():
                self._last_line = line.strip()
                log.info("emulador: %s", self._last_line)

    def _on_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self._read_log()
        if not self._stopping:
            log.warning("A emulação parou sozinha (código %s)", exit_code)
            self.failed.emit(self._last_line)
        self._forget()

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._last_line = self._process.errorString() if self._process is not None else ""
            log.warning("A emulação não iniciou: %s", self._last_line)
            self.failed.emit(self._last_line)
            self._forget()

    def _forget(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        process.deleteLater()
        self.changed.emit()
