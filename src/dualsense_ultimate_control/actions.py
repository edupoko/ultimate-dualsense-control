"""Registro das ações do usuário no controle (cor, perfil, calibração...), num logger próprio.

Cada ação vira uma linha curta em português: `[Controle bc:c7 · USB] cor → #FF0000`. O logger
(`dualsense_ultimate_control.actions`) deixa o visualizador de logs filtrar só as ações. Sliders
disparam muitas mudanças por segundo; `log_burst` junta a rajada e grava só o último valor.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QCoreApplication, QTimer

LOGGER_NAME = "dualsense_ultimate_control.actions"
BURST_DELAY_MS = 500

log = logging.getLogger(LOGGER_NAME)


def controller_label(controller: Any = None) -> str:
    """`[Controle aa:bb · USB]` com os dois últimos bytes do endereço; `[Geral]` sem controle.

    Aceita um `Controller` (`uid`, `connection`) ou o endereço (texto) do controle."""
    if controller is None or controller == "":
        return "[Geral]"
    uid = controller if isinstance(controller, str) else getattr(controller, "uid", "")
    connection = "" if isinstance(controller, str) else getattr(controller, "connection", "")
    short = ":".join(uid.split(":")[-2:]) if ":" in uid else uid
    text = f"Controle {short}" if short else "Controle"
    return f"[{text} · {connection}]" if connection else f"[{text}]"


def format_action(kind: str, controller: Any = None, **detail: Any) -> str:
    """`value` vira ` → valor`; os demais campos entram entre parênteses como `chave=valor`."""
    text = f"{controller_label(controller)} {kind}"
    if "value" in detail:
        text += f" → {detail.pop('value')}"
    if detail:
        text += " (" + ", ".join(f"{key}={value}" for key, value in detail.items()) + ")"
    return text


def log_action(kind: str, controller: Any = None, **detail: Any) -> None:
    log.info(format_action(kind, controller, **detail))


class _Burst:
    """Junta mudanças seguidas de uma mesma chave: grava só depois de `delay_ms` sem mudança."""

    def __init__(self) -> None:
        self._pending: dict[str, tuple[QTimer, str]] = {}

    def push(self, key: str, message: str, delay_ms: int) -> None:
        if QCoreApplication.instance() is None:  # sem event loop (testes, scripts): grava na hora
            log.info(message)
            return
        entry = self._pending.get(key)
        timer = entry[0] if entry else QTimer()
        if entry is None:
            timer.setSingleShot(True)
            timer.timeout.connect(lambda key=key: self.flush(key))
        self._pending[key] = (timer, message)
        timer.start(delay_ms)

    def flush(self, key: str | None = None) -> None:
        """Grava já o que está esperando (todas as chaves, ou só `key`)."""
        for name in [key] if key is not None else list(self._pending):
            entry = self._pending.pop(name, None)
            if entry is not None:
                entry[0].stop()
                log.info(entry[1])


_burst = _Burst()


def log_burst(key: str, kind: str, controller: Any = None, delay_ms: int = BURST_DELAY_MS, **detail: Any) -> None:
    """Como `log_action`, mas para sliders: uma linha por rajada, com o último valor.

    `key` separa rajadas independentes (ex.: `"cor:" + uid`); pede um event loop do Qt rodando."""
    _burst.push(key, format_action(kind, controller, **detail), delay_ms)


def flush_bursts() -> None:
    """Grava as rajadas pendentes agora; chamar antes de encerrar o app."""
    _burst.flush()
