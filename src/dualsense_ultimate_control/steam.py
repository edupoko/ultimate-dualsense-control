"""Detecta quando a Steam está controlando um DualSense diretamente.

Com o Steam Input ativo, a Steam abre o dispositivo /dev/hidrawN do controle e envia as
próprias cores e LEDs de jogador, passando por cima do driver do kernel. O que o app escreve
pelo sysfs vale até a próxima vez que a Steam mandar o estado dela, então as mudanças parecem
"voltar sozinhas". Não dá para ler o estado real do LED, mas dá para saber se a Steam está com
o dispositivo aberto.
"""

from __future__ import annotations

import os
from pathlib import Path

PROC = Path("/proc")
# Nome do processo do cliente da Steam (ubuntu12_32/steam), que é quem abre os controles.
STEAM_PROCESS = "steam"


def hidraw_held_by_steam(proc: Path = PROC) -> set[str]:
    """Caminhos /dev/hidrawN que algum processo da Steam mantém abertos."""
    held: set[str] = set()
    try:
        entries = list(proc.iterdir())
    except OSError:
        return held
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "comm").read_text().strip() != STEAM_PROCESS:
                continue
            descriptors = list((entry / "fd").iterdir())
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor)
            except OSError:
                continue
            if target.startswith("/dev/hidraw"):
                held.add(target)
    return held
