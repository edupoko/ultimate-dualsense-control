"""Migração do nome antigo (`dualsense-led`): traz configurações, perfis, histórico, log e início automático.

Roda uma vez por início, antes de qualquer outra coisa ler essas pastas. É idempotente e nunca sobrescreve
o que já existe na pasta nova.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

OLD_NAME = "dualsense-led"
NEW_NAME = "dualsense-ultimate-control"

log = logging.getLogger(__name__)


def migrate_legacy(config_base: Path | None = None, state_base: Path | None = None) -> None:
    config = config_base or Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    state = state_base or Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    for step in (
        lambda: _move_tree(config / OLD_NAME, config / NEW_NAME),
        lambda: _move_tree(state / OLD_NAME, state / NEW_NAME),
        lambda: _rename_logs(state / NEW_NAME),
        lambda: _migrate_autostart(config / "autostart"),
    ):
        try:
            step()
        except OSError as error:
            log.warning("Migração do nome antigo incompleta: %s", error)


def _move_tree(old: Path, new: Path) -> None:
    """Move a pasta antiga; se a nova já existe, só leva o que ela ainda não tem."""
    if not old.is_dir():
        return
    if not new.exists():
        shutil.move(str(old), str(new))
        log.info("Pasta %s movida para %s", old, new)
        return
    for entry in old.iterdir():
        if not (new / entry.name).exists():
            shutil.move(str(entry), str(new / entry.name))
    try:
        old.rmdir()  # só some se esvaziou; o que a pasta nova já tinha fica para trás
    except OSError:
        pass


def _rename_logs(directory: Path) -> None:
    """dualsense-led.log (e as rotações .1, .2, ...) passam a ter o nome novo."""
    if not directory.is_dir():
        return
    for path in directory.glob(f"{OLD_NAME}.log*"):
        target = directory / path.name.replace(OLD_NAME, NEW_NAME, 1)
        if not target.exists():
            path.rename(target)


def _migrate_autostart(directory: Path) -> None:
    from . import autostart

    old = directory / f"{OLD_NAME}.desktop"
    if not old.is_file():
        return
    enabled = autostart.is_enabled(old)
    new = directory / autostart.FILE_NAME
    old.unlink()
    if enabled and not new.exists():
        autostart.set_enabled(True, new)  # Exec e ícone novos, apontando para este ambiente
