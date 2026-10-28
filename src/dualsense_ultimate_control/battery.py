"""Bateria do DualSense pelo sysfs (`power_supply/ps-controller-battery-<MAC>`), sem abrir o hidraw."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

POWER_ROOT = Path("/sys/class/power_supply")
LOW_PERCENT = 20  # abaixo disso, sem carregar, a linha fica em alerta
_STATUSES = {"charging": "charging", "full": "full", "discharging": "discharging", "not charging": "discharging"}


@dataclass(frozen=True)
class Battery:
    percent: int
    status: str  # "charging", "full" ou "discharging"

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
    return "🪫" if battery.low else "🔋"


def describe(battery: Battery) -> str:
    """Texto no idioma atual: "Bateria 85%", "Carregando 40%" ou "Bateria cheia"."""
    from .i18n import tr

    return tr(f"test.battery.{battery.status}", percent=battery.percent)
