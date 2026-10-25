"""Giroscópio do DualSense: calibração de fábrica (relatório 0x05) e correção do desvio por software.

O controle não tem comando conhecido para gravar a calibração do IMU: o fluxo 0x80–0x83 do
dualshock-tools só cobre os analógicos, e o hid-playstation usa desvio zero no giroscópio (só aplica
a sensibilidade do 0x05). Por isso o desvio medido com o controle parado fica nas configurações e é
descontado das leituras brutas pelo app (tela de teste e, depois, o emulador). Sem Qt, como
`calibration.py`.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

CALIBRATION_ID, CALIBRATION_SIZE = 0x05, 41

# Sem calibração válida o hid-playstation usa ±2048 °/s em toda a faixa do int16.
DEFAULT_GYRO_SCALE = 2048 / 32767

# Leituras com o controle parado: desvio padrão máximo (unidades brutas) e maior desvio aceito.
# Parado sobre a mesa o giroscópio oscila ~1 unidade e o acelerômetro ~15.
STABLE_GYRO_SPREAD = 4.0
STABLE_ACCEL_SPREAD = 80.0
MAX_GYRO_BIAS = 200  # ~12 °/s: acima disso o controle está girando, não é desvio
BIAS_SAMPLES = 120
MIN_SAMPLES = 10

Axes = tuple[float, float, float]


@dataclass(frozen=True)
class ImuCalibration:
    """Campos do giroscópio no relatório 0x05 (pitch, yaw, roll)."""

    gyro_bias: tuple[int, int, int]
    gyro_plus: tuple[int, int, int]
    gyro_minus: tuple[int, int, int]
    speed_plus: int
    speed_minus: int

    def gyro_scale(self) -> Axes:
        """°/s por unidade bruta em cada eixo, com a mesma conta do hid-playstation."""
        speed_2x = self.speed_plus + self.speed_minus
        scales = []
        for bias, plus, minus in zip(self.gyro_bias, self.gyro_plus, self.gyro_minus):
            denom = abs(plus - bias) + abs(minus - bias)
            scales.append(speed_2x / denom if denom and speed_2x else DEFAULT_GYRO_SCALE)
        return tuple(scales)


def parse_calibration(data: bytes) -> ImuCalibration | None:
    if len(data) < 23 or data[0] != CALIBRATION_ID:
        return None
    (pitch_bias, yaw_bias, roll_bias, pitch_plus, pitch_minus, yaw_plus, yaw_minus,
     roll_plus, roll_minus, speed_plus, speed_minus) = struct.unpack_from("<11h", data, 1)
    return ImuCalibration(
        (pitch_bias, yaw_bias, roll_bias), (pitch_plus, yaw_plus, roll_plus),
        (pitch_minus, yaw_minus, roll_minus), speed_plus, speed_minus,
    )


def read_calibration(device) -> ImuCalibration | None:
    try:
        return parse_calibration(device.get_feature(CALIBRATION_ID, CALIBRATION_SIZE))
    except OSError:
        return None


def to_dps(gyro, calibration: ImuCalibration | None) -> Axes:
    scales = calibration.gyro_scale() if calibration else (DEFAULT_GYRO_SCALE,) * 3
    return tuple(value * scale for value, scale in zip(gyro, scales))


# --- desvio com o controle parado

@dataclass(frozen=True)
class RestReading:
    """Média e espalhamento das leituras brutas de um trecho com o controle (supostamente) parado."""

    gyro_mean: Axes
    gyro_spread: Axes
    accel_spread: Axes
    samples: int

    @property
    def stable(self) -> bool:
        return (
            self.samples >= MIN_SAMPLES
            and max(self.gyro_spread) <= STABLE_GYRO_SPREAD
            and max(self.accel_spread) <= STABLE_ACCEL_SPREAD
            and max(abs(v) for v in self.gyro_mean) <= MAX_GYRO_BIAS
        )

    @property
    def offset(self) -> Axes:
        """Correção a guardar: o desvio médio, arredondado a 0,1 unidade."""
        return tuple(round(v, 1) for v in self.gyro_mean)


def _mean_spread(values) -> tuple[float, float]:
    mean = sum(values) / len(values)
    return mean, math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def measure_rest(states) -> RestReading | None:
    """Lê os estados (`InputState`); devolve None sem amostras."""
    states = list(states)
    if not states:
        return None
    gyro = [_mean_spread([s.gyro[i] for s in states]) for i in range(3)]
    accel = [_mean_spread([s.accel[i] for s in states]) for i in range(3)]
    return RestReading(
        tuple(m for m, _ in gyro), tuple(s for _, s in gyro), tuple(s for _, s in accel), len(states),
    )


def apply_offset(gyro, offset: Axes | None) -> Axes:
    """Leitura bruta menos a correção salva (sem correção, a leitura como veio)."""
    if not offset:
        return tuple(float(v) for v in gyro)
    return tuple(value - bias for value, bias in zip(gyro, offset))
