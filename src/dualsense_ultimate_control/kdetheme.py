"""Usa o tema do KDE (Breeze etc.) no PySide6 instalado pelo pip.

O Qt que vem no pacote do pip não carrega os plugins do Plasma instalados no sistema,
então o app cai no estilo Fusion. Quando o Qt do sistema é exatamente da mesma versão,
dá para expor só os plugins de tema e de estilo ao Qt do pip. Com versões diferentes
eles não são compatíveis, então nada é feito e o app segue com o estilo padrão.
"""

from __future__ import annotations

import glob
import os
import re
from pathlib import Path

PLUGIN_DIRS = ("/usr/lib/qt6/plugins", "/usr/lib64/qt6/plugins", "/usr/lib/x86_64-linux-gnu/qt6/plugins")
LIB_DIRS = ("/usr/lib", "/usr/lib64", "/usr/lib/x86_64-linux-gnu")
OPT_OUT = "DUALSENSE_ULTIMATE_NO_KDE_THEME"
_THEME_PLUGIN = "platformthemes/KDEPlasmaPlatformTheme6.so"


def system_qt_version() -> str | None:
    for lib_dir in LIB_DIRS:
        for path in glob.glob(f"{lib_dir}/libQt6Core.so.6.*.*"):
            match = re.search(r"\.so\.(\d+\.\d+\.\d+)$", path)
            if match:
                return match.group(1)
    return None


def system_plugin_dir() -> Path | None:
    for plugin_dir in PLUGIN_DIRS:
        if (Path(plugin_dir) / _THEME_PLUGIN).is_file():
            return Path(plugin_dir)
    return None


def _expose_plugins(source: Path, target: Path) -> None:
    for kind in ("platformthemes", "styles"):
        (target / kind).mkdir(parents=True, exist_ok=True)
        for plugin in (source / kind).glob("*.so"):
            link = target / kind / plugin.name
            if link.is_symlink() and link.resolve() == plugin.resolve():
                continue
            link.unlink(missing_ok=True)
            link.symlink_to(plugin)


def enable(bundled_qt_version: str, cache_dir: Path | None = None) -> bool:
    """Ativa o tema do KDE se for seguro. Deve ser chamado antes de criar o QApplication."""
    if os.environ.get(OPT_OUT) or os.environ.get("QT_QPA_PLATFORMTHEME") or os.environ.get("QT_STYLE_OVERRIDE"):
        return False
    if "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
        return False
    source = system_plugin_dir()
    if source is None or system_qt_version() != bundled_qt_version:
        return False
    cache = cache_dir or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "dualsense-ultimate-control"
    target = cache / "qt-plugins"
    try:
        _expose_plugins(source, target)
    except OSError:
        return False
    existing = os.environ.get("QT_PLUGIN_PATH")
    os.environ["QT_PLUGIN_PATH"] = f"{target}{os.pathsep}{existing}" if existing else str(target)
    os.environ["QT_QPA_PLATFORMTHEME"] = "kde"
    return True
