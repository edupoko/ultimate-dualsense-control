"""Iniciar com o sistema: um atalho em ~/.config/autostart, que o KDE (e o GNOME) abrem no login."""

from __future__ import annotations

import logging
import os
import shlex
import sys
from pathlib import Path

FILE_NAME = "dualsense-ultimate-control.desktop"

log = logging.getLogger(__name__)


def autostart_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autostart" / FILE_NAME


def launch_command() -> str:
    """Comando que abre este app só na bandeja, a partir do ambiente em que ele está rodando."""
    script = Path(sys.executable).parent / "dualsense-ultimate-control"
    if script.is_file():
        return f"{shlex.quote(str(script))} --tray"
    return f"{shlex.quote(sys.executable)} -m dualsense_ultimate_control --tray"


def is_enabled(path: Path | None = None) -> bool:
    path = path or autostart_file()
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return False
    return "Hidden=true" not in lines and "X-GNOME-Autostart-enabled=false" not in lines


def set_enabled(enabled: bool, path: Path | None = None, command: str | None = None) -> None:
    path = path or autostart_file()
    log.info("Início com o sistema: %s (%s)", "ligado" if enabled else "desligado", path)
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=DualSense Ultimate Control\n"
        "Comment=Aplica as cores do DualSense e fica na bandeja\n"
        "Comment[en]=Applies the DualSense colors and stays in the tray\n"
        "Comment[es]=Aplica los colores del DualSense y se queda en la bandeja\n"
        f"Exec={command or launch_command()}\n"
        "Icon=dualsense-ultimate-control\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
