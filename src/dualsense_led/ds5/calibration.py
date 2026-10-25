"""Calibração dos analógicos do DualSense pelos relatórios de feature 0x80–0x83.

Só protocolo e contas, sem Qt: o dispositivo é qualquer objeto com `get_feature` e `set_feature`
(`DualSenseDevice`), o que permite testar sem hardware. Segue o fluxo do dualshock-tools: a
calibração roda com o NVS travado e vale só até o controle reiniciar; `save` grava no NVS
(destrava e trava de novo) e `reboot` descarta o que não foi salvo.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

NVS_REQUEST, NVS_RESPONSE = 0x80, 0x81
CAL_REQUEST, CAL_RESPONSE = 0x82, 0x83
FEATURE_SIZE = 64
IMU_CALIBRATION_ID, IMU_CALIBRATION_SIZE = 0x05, 41

NVS_UNLOCK = (3, 2, 101, 50, 64, 12)
NVS_LOCK = (3, 1)
NVS_STATUS = (3, 3)
# Reinicia o controle (não restaura calibração): descarta o que não foi gravado no NVS.
REBOOT = (1, 1)

NVS_LOCKED = 0x03030201
NVS_UNLOCKED = 0x03030200
NVS_PENDING_REBOOT = 0x15010100

CENTER_BEGIN, CENTER_SAMPLE, CENTER_END = (1, 1, 1), (3, 1, 1), (2, 1, 1)
RANGE_BEGIN, RANGE_END = (1, 1, 2), (2, 1, 2)
_EXPECT = {
    CENTER_BEGIN: 0x83010101, CENTER_SAMPLE: 0x83010101, CENTER_END: 0x83010102,
    RANGE_BEGIN: 0x83010201, RANGE_END: 0x83010202,
}

CENTER_SAMPLES = 5
SAMPLE_DELAY_S = 0.1
STICK_CENTER = 128
# Desvio do centro (em passos de 0..255) a partir do qual a calibração compensa.
DRIFT_NOTICE = 3


class CalibrationError(Exception):
    """Um passo do protocolo falhou; `step` diz qual."""

    def __init__(self, step: str, detail: str = ""):
        super().__init__(f"{step}: {detail}" if detail else step)
        self.step = step


def _word(data: bytes, offset: int) -> int | None:
    return int.from_bytes(data[offset:offset + 4], "big") if len(data) >= offset + 4 else None


def nvs_status(device) -> int | None:
    """Status do NVS; o ioctl devolve o id 0x81 no byte 0, a palavra vem em seguida."""
    device.set_feature(bytes([NVS_REQUEST, *NVS_STATUS]))
    return _word(device.get_feature(NVS_RESPONSE, FEATURE_SIZE), 1)


def _nvs_command(device, command: tuple[int, ...]) -> None:
    device.set_feature(bytes([NVS_REQUEST, *command]))
    device.get_feature(NVS_RESPONSE, FEATURE_SIZE)  # a referência sempre lê a resposta


def nvs_unlock(device) -> None:
    _nvs_command(device, NVS_UNLOCK)
    status = nvs_status(device)
    if status != NVS_UNLOCKED:
        raise CalibrationError("unlock", f"status {status:#x}" if status is not None else "sem resposta")


def nvs_lock(device) -> int | None:
    """Trava o NVS e devolve o status final (travado ou reinício pendente)."""
    _nvs_command(device, NVS_LOCK)
    return nvs_status(device)


def _command(device, command: tuple[int, ...], step: str) -> None:
    device.set_feature(bytes([CAL_REQUEST, *command]))
    reply = device.get_feature(CAL_RESPONSE, FEATURE_SIZE)
    # A palavra esperada já começa pelo id 0x83, que o ioctl põe no byte 0.
    if _word(reply, 0) != _EXPECT[command]:
        raise CalibrationError(step, reply[:6].hex())


def read_imu_backup(device) -> str:
    """Relatório 0x05 (calibração do IMU) em hexa, guardado no histórico como cópia de segurança."""
    try:
        return device.get_feature(IMU_CALIBRATION_ID, IMU_CALIBRATION_SIZE).hex()
    except OSError:
        return ""


def calibrate_center(device, sleep=time.sleep) -> None:
    """begin → amostras com os sticks soltos → end. Aplica até reiniciar; não grava no NVS."""
    _command(device, CENTER_BEGIN, "center_begin")
    for _ in range(CENTER_SAMPLES):
        sleep(SAMPLE_DELAY_S)
        _command(device, CENTER_SAMPLE, "center_sample")
    _command(device, CENTER_END, "center_end")


def range_begin(device) -> None:
    _command(device, RANGE_BEGIN, "range_begin")


def range_end(device) -> None:
    """Fecha a coleta de alcance; como o centro, vale até reiniciar."""
    _command(device, RANGE_END, "range_end")


def save(device) -> int | None:
    """Grava no NVS a calibração aplicada (destrava → trava) e devolve o status final.

    Se o destravamento não confirmar, trava mesmo assim; se o status final não for travado
    nem reinício pendente, levanta `CalibrationError`.
    """
    try:
        nvs_unlock(device)
    except BaseException:
        try:
            nvs_lock(device)
        except OSError:
            pass
        raise
    status = nvs_lock(device)
    if status not in (NVS_LOCKED, NVS_PENDING_REBOOT):
        raise CalibrationError("lock", f"status {status:#x}" if status is not None else "sem resposta")
    return status


def reboot(device) -> None:
    """Reinicia o controle; ele cai durante o comando, então erros de E/S são esperados."""
    try:
        device.set_feature(bytes([NVS_REQUEST, *REBOOT]))
    except OSError:
        pass


# --- contas sobre as leituras dos sticks

@dataclass(frozen=True)
class CenterReading:
    """Média das leituras dos dois sticks com eles soltos."""

    lx: float
    ly: float
    rx: float
    ry: float
    samples: int

    @property
    def drift(self) -> float:
        """Maior desvio, em passos, em relação ao centro ideal (128)."""
        return max(abs(v - STICK_CENTER) for v in (self.lx, self.ly, self.rx, self.ry))

    @property
    def needs_calibration(self) -> bool:
        return self.drift >= DRIFT_NOTICE


def average_center(states) -> CenterReading | None:
    states = list(states)
    if not states:
        return None
    n = len(states)
    return CenterReading(
        sum(s.lx for s in states) / n, sum(s.ly for s in states) / n,
        sum(s.rx for s in states) / n, sum(s.ry for s in states) / n, n,
    )


def range_extremes(points) -> tuple[int, int, int, int]:
    """Menor e maior valor visto em x e y de um stick (xmin, xmax, ymin, ymax)."""
    points = list(points)
    if not points:
        return STICK_CENTER, STICK_CENTER, STICK_CENTER, STICK_CENTER
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), max(xs), min(ys), max(ys)


def range_complete(extremes: tuple[int, int, int, int], margin: int = 20) -> bool:
    """O stick chegou perto dos quatro limites (0 e 255)?"""
    xmin, xmax, ymin, ymax = extremes
    return xmin <= margin and ymin <= margin and xmax >= 255 - margin and ymax >= 255 - margin


# --- histórico local

@dataclass
class HistoryEntry:
    time: str
    controller: str
    action: str  # "center", "range", "save" ou "reboot"
    ok: bool
    before: dict
    detail: str = ""
    imu_backup: str = ""


MAX_HISTORY = 50


def history_path(settings_path: Path) -> Path:
    return settings_path.with_name("calibration-history.json")


def load_history(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text())
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def append_history(path: Path, entry: HistoryEntry) -> None:
    entries = (load_history(path) + [asdict(entry)])[-MAX_HISTORY:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2))
