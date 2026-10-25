"""Efeitos dos gatilhos adaptáveis (11 bytes cada), no formato que o DualSense espera.

Os modos e a codificação das zonas (10 zonas de 0 a 9, 3 bits de força por zona) seguem o
dualsensectl e o pydualsense. Só bytes, sem abrir dispositivo.
"""

from __future__ import annotations

from collections.abc import Callable

from .reports import TRIGGER_EFFECT_SIZE

ZONES = 10  # posições do curso do gatilho
MAX_STRENGTH = 8

MODE_OFF = 0x05
MODE_FEEDBACK = 0x21
MODE_BOW = 0x22
MODE_VIBRATION = 0x26
MODE_MACHINE = 0x27
MODE_WEAPON = 0x25

OFF = bytes([MODE_OFF]) + bytes(TRIGGER_EFFECT_SIZE - 1)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _zones_mask(*zones: int) -> int:
    mask = 0
    for zone in zones:
        mask |= 1 << zone
    return mask


def _effect(*head: int) -> bytes:
    return bytes(head).ljust(TRIGGER_EFFECT_SIZE, b"\x00")


def _strengths(position: int, strength: int) -> tuple[int, int]:
    """(zonas ativas, força por zona) com a mesma força da posição até o fim do curso."""
    active = strength_bits = 0
    for zone in range(position, ZONES):
        active |= 1 << zone
        strength_bits |= ((strength - 1) & 7) << (3 * zone)
    return active, strength_bits


def resistance(position: int, strength: int) -> bytes:
    """Resistência contínua a partir de `position` (0 a 9) com força de 1 a 8."""
    position, strength = _clamp(position, 0, ZONES - 1), _clamp(strength, 1, MAX_STRENGTH)
    active, bits = _strengths(position, strength)
    return _effect(MODE_FEEDBACK, active & 0xFF, active >> 8, *bits.to_bytes(4, "little"))


def weapon(position: int, strength: int) -> bytes:
    """Gatilho de arma: resiste até o ponto de disparo, que "estala" e solta."""
    start = _clamp(position, 2, 7)
    zones = _zones_mask(start, start + 1)
    return _effect(MODE_WEAPON, zones & 0xFF, zones >> 8, _clamp(strength, 1, MAX_STRENGTH) - 1)


def bow(position: int, strength: int) -> bytes:
    """Arco: força crescente entre `position` e a zona seguinte, depois o soltar."""
    start = _clamp(position, 0, ZONES - 2)
    zones = _zones_mask(start, start + 1)
    force = _clamp(strength, 1, MAX_STRENGTH) - 1
    bits = (force & 7) | ((force & 7) << 3)
    return _effect(MODE_BOW, zones & 0xFF, zones >> 8, bits & 0xFF, bits >> 8)


def machine(position: int, strength: int) -> bytes:
    """Máquina (arma automática): pulsos entre `position` e o fim do curso."""
    start = _clamp(position, 0, ZONES - 2)
    zones = _zones_mask(start, ZONES - 1)
    force = _clamp(strength, 1, MAX_STRENGTH) - 1
    bits = (force & 7) | ((force & 7) << 3)
    return _effect(MODE_MACHINE, zones & 0xFF, zones >> 8, bits & 0xFF, 20, 4)


def vibration(position: int, strength: int) -> bytes:
    """Vibração do gatilho a partir de `position`; a amplitude é a força (1 a 8)."""
    position, strength = _clamp(position, 0, ZONES - 1), _clamp(strength, 1, MAX_STRENGTH)
    active, bits = _strengths(position, strength)
    return _effect(MODE_VIBRATION, active & 0xFF, active >> 8, *bits.to_bytes(4, "little"), 0, 0, 30)


def off(position: int = 0, strength: int = 0) -> bytes:
    return OFF


# Chave de tradução do nome → gerador (posição, força).
EFFECTS: dict[str, Callable[[int, int], bytes]] = {
    "trigger.off": off,
    "trigger.resistance": resistance,
    "trigger.weapon": weapon,
    "trigger.bow": bow,
    "trigger.machine": machine,
    "trigger.vibration": vibration,
}
