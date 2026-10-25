"""Padrões dos LEDs de jogador, os mesmos que o console usa para indicar o número do jogador."""

from __future__ import annotations

from collections.abc import Sequence

from .sysfs import PLAYER_LED_COUNT

# Posição 0 do padrão é o primeiro LED. O console centraliza o número do jogador:
# 1 = "--x--", 2 = "-x-x-", 3 = "x-x-x", 4 = "xx-xx", 5 = "xxxxx".
PLAYER_PATTERNS: tuple[tuple[bool, ...], ...] = (
    (False, False, True, False, False),
    (False, True, False, True, False),
    (True, False, True, False, True),
    (True, True, False, True, True),
    (True, True, True, True, True),
)
PLAYER_COUNT = len(PLAYER_PATTERNS)
NO_PLAYER = [False] * PLAYER_LED_COUNT


def pattern_for(player: int) -> list[bool]:
    """LEDs acesos para o jogador `player` (1 a 5)."""
    return list(PLAYER_PATTERNS[player - 1])


def player_number(leds: Sequence[bool]) -> int | None:
    """Número do jogador (1 a 5) que corresponde aos LEDs acesos, ou None se nenhum bate."""
    pattern = tuple(bool(on) for on in leds)
    for number, candidate in enumerate(PLAYER_PATTERNS, start=1):
        if pattern == candidate:
            return number
    return None
