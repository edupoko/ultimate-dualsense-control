"""Daemon da emulação: python -m dualsense_led.emulator (ou dualsense-led --emulate)."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from .core import Emulator

UINPUT = "/dev/uinput"


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not os.access(UINPUT, os.R_OK | os.W_OK):
        logging.error("Sem permissão para usar %s (o usuário precisa estar no grupo input)", UINPUT)
        return 1
    asyncio.run(_main())
    return 0


async def _main() -> None:
    task = asyncio.create_task(Emulator().run())
    loop = asyncio.get_running_loop()
    for number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(number, task.cancel)  # o finally do Emulator solta o grab
    try:
        await task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    raise SystemExit(run())
