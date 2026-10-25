"""Acesso aos LEDs do DualSense expostos pelo driver hid-playstation do kernel Linux."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import hidraw

LEDS_ROOT = Path("/sys/class/leds")
# DualSense e DualSense Edge (mesmo driver e mesmos LEDs).
DUALSENSE_IDS = ("054C:0CE6", "054C:0DF2")
PLAYER_LED_COUNT = 5

_RGB_LED = re.compile(r"^(input\d+):rgb:indicator$")
_BUSES = {"3": "USB", "5": "Bluetooth"}


@dataclass(frozen=True)
class Controller:
    """Um DualSense conectado e os diretórios sysfs dos seus LEDs."""

    name: str
    rgb_dir: Path
    player_dirs: tuple[Path | None, ...]
    # Identificador do aparelho (endereço do controle), igual em USB e Bluetooth.
    uid: str = ""
    connection: str = ""
    # Nó /dev/hidrawN do controle, usado para saber se outro programa (a Steam) o abriu.
    hidraw: str = ""

    def set_color(self, red: int, green: int, blue: int) -> None:
        _write(self.rgb_dir / "multi_intensity", f"{red} {green} {blue}")

    def set_brightness(self, value: int) -> None:
        _write(self.rgb_dir / "brightness", str(max(0, min(255, value))))

    def set_mute_led(self, on: bool) -> None:
        """LED do botão de microfone; vai pelo /dev/hidrawN porque o kernel não o expõe."""
        hidraw.set_mute_led(self.hidraw, on, self.connection)

    def open_device(self):
        """Abre o hidraw do controle para ler entrada e enviar relatórios (`ds5.device`)."""
        from .ds5.device import DualSenseDevice

        return DualSenseDevice(self.hidraw, self.connection)

    def set_players(self, flags: list[bool]) -> None:
        for led, on in zip(self.player_dirs, flags):
            if led is not None:
                _write(led / "brightness", "1" if on else "0")


def find_controllers(root: Path = LEDS_ROOT) -> list[Controller]:
    """Lista os DualSense conectados (USB ou Bluetooth), na ordem em que o kernel os registrou."""
    if not root.is_dir():
        return []
    controllers = []
    for led in root.iterdir():
        match = _RGB_LED.match(led.name)
        device = (led / "device").resolve()
        if match is None or not any(product in device.name.upper() for product in DUALSENSE_IDS):
            continue
        prefix = match.group(1)
        player_dirs = tuple(
            _existing(root / f"{prefix}:white:player-{n}") for n in range(1, PLAYER_LED_COUNT + 1)
        )
        uid, connection = _device_info(device)
        controllers.append(Controller(prefix, led, player_dirs, uid or prefix, connection, _hidraw(device)))
    return sorted(controllers, key=lambda c: int(c.name.removeprefix("input")))


def _device_info(device: Path) -> tuple[str, str]:
    """Endereço do controle e tipo de conexão, lidos do uevent do dispositivo HID."""
    try:
        lines = (device / "uevent").read_text().splitlines()
    except OSError:
        return "", ""
    info = dict(line.split("=", 1) for line in lines if "=" in line)
    bus = info.get("HID_ID", "").split(":")[0].lstrip("0")
    return info.get("HID_UNIQ", "").lower(), _BUSES.get(bus, "")


def _hidraw(device: Path) -> str:
    try:
        return next(f"/dev/{node.name}" for node in (device / "hidraw").iterdir())
    except (OSError, StopIteration):
        return ""


def _existing(path: Path) -> Path | None:
    return path if path.is_dir() else None


def _write(path: Path, value: str) -> None:
    path.write_text(value)
