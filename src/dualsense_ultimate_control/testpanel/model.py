"""Contas da tela de teste (sem Qt): normalização dos eixos, alcance dos sticks e histórico do IMU."""

from __future__ import annotations

import math
from collections import deque

STICK_CENTER = 128
ANGLE_BINS = 48  # mesmo número de direções do teste de circularidade do dualshock-tools
IMU_HISTORY = 200


def normalize_stick(value: int) -> float:
    """0..255 (centro 128) para -1..1."""
    return max(-1.0, min(1.0, (value - STICK_CENTER) / 127))


def stick_point(x: int, y: int) -> tuple[float, float]:
    """Posição do stick em -1..1 com y positivo para cima (o hardware manda y crescendo para baixo)."""
    return normalize_stick(x), -normalize_stick(y)


class RangeTracker:
    """Maior raio que o stick alcançou em cada direção: mostra o alcance real ao girar o stick."""

    def __init__(self, bins: int = ANGLE_BINS):
        self.radii = [0.0] * bins

    def add(self, x: float, y: float) -> None:
        radius = math.hypot(x, y)
        if radius < 0.05:
            return
        index = int((math.atan2(y, x) % math.tau) / math.tau * len(self.radii)) % len(self.radii)
        # Sem limitar a 1: passar do círculo (cantos quadrados) também conta como erro.
        self.radii[index] = max(self.radii[index], radius)

    def reset(self) -> None:
        self.radii = [0.0] * len(self.radii)

    def circularity_error(self) -> float | None:
        """Erro médio de circularidade em % (RMS do desvio do raio ideal 1), como o dualshock-tools.

        Só conta direções com raio > 0,2 e devolve None até haver mais de 10 direções acima de 0,3.
        """
        if sum(r > 0.3 for r in self.radii) <= 10:
            return None
        valid = [r for r in self.radii if r > 0.2]
        return math.sqrt(sum((r - 1) ** 2 for r in valid) / len(valid)) * 100


class ImuHistory:
    """Últimas amostras de um sensor de 3 eixos para o gráfico."""

    def __init__(self, size: int = IMU_HISTORY):
        self.samples: deque[tuple[int, int, int]] = deque(maxlen=size)

    def add(self, sample: tuple[int, int, int]) -> None:
        self.samples.append(sample)

    def axis(self, index: int) -> list[int]:
        return [sample[index] for sample in self.samples]


def peak_level(samples: bytes, float_samples: bool = False) -> float:
    """Pico (0 a 1) de um bloco de áudio PCM de 16 bits com sinal, ou float de 32 bits."""
    from array import array

    values = array("f" if float_samples else "h")
    usable = len(samples) - len(samples) % values.itemsize
    values.frombytes(samples[:usable])
    if not values:
        return 0.0
    peak = max(max(values), -min(values))
    return min(1.0, peak if float_samples else peak / 32768)
