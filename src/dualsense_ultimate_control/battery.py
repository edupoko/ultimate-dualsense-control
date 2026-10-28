"""Bateria do DualSense pelo sysfs (`power_supply/ps-controller-battery-<MAC>`), sem abrir o hidraw."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

POWER_ROOT = Path("/sys/class/power_supply")
LOW_PERCENT = 20  # abaixo disso, sem carregar, a linha fica em alerta
# O hid-playstation publica "Not charging" quando o controle acusa erro de carga (tensão/temperatura).
_STATUSES = {"charging": "charging", "full": "full", "discharging": "discharging", "not charging": "error"}


@dataclass(frozen=True)
class Battery:
    percent: int
    status: str  # "charging", "full", "discharging" ou "error"

    @property
    def low(self) -> bool:
        return self.status == "discharging" and self.percent < LOW_PERCENT


def read_battery(uid: str, root: Path = POWER_ROOT) -> Battery | None:
    """Bateria do controle de endereço `uid`; None se o driver não expõe (driver antigo) ou a leitura falha."""
    if not uid:
        return None
    directory = root / f"ps-controller-battery-{uid.lower()}"
    try:
        percent = int((directory / "capacity").read_text().strip())
        status = (directory / "status").read_text().strip().lower()
    except (OSError, ValueError):
        return None
    return Battery(max(0, min(100, percent)), _STATUSES.get(status, "discharging"))


def level_icon(battery: Battery) -> str:
    """Símbolo curto do estado, para títulos de aba e dica da bandeja."""
    if battery.status == "charging":
        return "⚡"
    if battery.status == "full":
        return "🔋"
    if battery.status == "error":
        return "⚠"
    return "🪫" if battery.low else "🔋"


def describe(battery: Battery) -> str:
    """Texto no idioma atual: "Bateria 85%", "Carregando 40%" ou "Bateria cheia"."""
    from .i18n import tr

    return tr(f"test.battery.{battery.status}", percent=battery.percent)


@dataclass(frozen=True)
class ChargeEstimate:
    """Estimativa a partir dos degraus de 10 % (o controle não informa corrente nem tensão)."""

    intervals_min: tuple[float, ...]  # minutos entre degraus completos, do mais antigo ao mais novo
    rate_per_min: float | None  # % por minuto, com ≥ 2 degraus observados
    remaining_min: float | None  # até 100 %, com a mesma condição


class ChargeTracker:
    """Guarda (instante, %) a cada degrau de subida enquanto carrega; recomeça ao parar de carregar.

    O primeiro registro é o início da observação, no meio de um degrau: só os intervalos entre
    duas subidas contam como tempo de um degrau inteiro."""

    def __init__(self) -> None:
        self._marks: list[tuple[float, int]] = []

    def update(self, now: float, battery: Battery | None) -> None:
        if battery is None or battery.status != "charging":
            self._marks.clear()
            return
        if not self._marks or battery.percent < self._marks[-1][1]:
            self._marks = [(now, battery.percent)]
        elif battery.percent > self._marks[-1][1]:
            self._marks.append((now, battery.percent))

    @property
    def steps(self) -> int:
        """Subidas observadas desde o início da carga."""
        return max(0, len(self._marks) - 1)

    def estimate(self) -> ChargeEstimate:
        rises = self._marks[1:]
        intervals = tuple((b[0] - a[0]) / 60 for a, b in zip(rises, rises[1:]))
        rate = remaining = None
        if len(rises) >= 2:
            minutes = (rises[-1][0] - rises[0][0]) / 60
            if minutes > 0:
                rate = (rises[-1][1] - rises[0][1]) / minutes
                remaining = max(0.0, (100 - rises[-1][1]) / rate) if rate > 0 else None
        return ChargeEstimate(intervals, rate, remaining)


def usb_max_power(hidraw: str, sys_class: Path = Path("/sys/class/hidraw")) -> str | None:
    """`bMaxPower` do descritor USB do controle (ex.: "500mA"): teto pedido à porta, não o consumo."""
    if not hidraw:
        return None
    try:
        node = (sys_class / Path(hidraw).name / "device").resolve()
    except OSError:
        return None
    for parent in (node, *node.parents):
        try:
            return (parent / "bMaxPower").read_text().strip() or None
        except OSError:
            continue
    return None
