"""Acha DualSense que o Bluetooth diz estar conectados, mas que o sistema não registrou.

Às vezes o BlueZ mantém a ligação Bluetooth com o controle, mas perde a sessão de controle
(HID): o controle continua "conectado" nas configurações, porém o kernel não tem nenhum
dispositivo nem LED para ele, então nem o app nem os jogos o enxergam. Só reconectar resolve.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from collections.abc import Callable, Iterable

log = logging.getLogger(__name__)

# Produtos Sony tratados como DualSense: o comum e o Edge.
DUALSENSE_PRODUCTS = ("0ce6", "0df2")

_LIST_DEVICES = [
    "busctl", "--system", "--json=short", "call",
    "org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
]


def _bluez_devices(run: Callable = subprocess.run) -> list[dict]:
    try:
        output = run(_LIST_DEVICES, capture_output=True, text=True, timeout=3).stdout
        objects = json.loads(output)["data"][0]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError):
        return []
    return [interfaces["org.bluez.Device1"] for interfaces in objects.values() if "org.bluez.Device1" in interfaces]


def unregistered_dualsense(known: Iterable[str], run: Callable = subprocess.run) -> list[str]:
    """Endereços (minúsculos) de DualSense conectados pelo Bluetooth que não estão em `known`."""
    known = {address.lower() for address in known}
    missing = []
    for device in _bluez_devices(run):
        modalias = str(device.get("Modalias", {}).get("data", "")).lower()
        if not any(f"v054cp{product}" in modalias for product in DUALSENSE_PRODUCTS):
            continue
        address = str(device.get("Address", {}).get("data", "")).lower()
        if device.get("Connected", {}).get("data") and address and address not in known:
            missing.append(address)
    return missing


def disconnect(address: str) -> None:
    """Desliga a ligação Bluetooth do controle; ele volta ao apertar o botão PS."""
    try:
        process = subprocess.Popen(
            ["bluetoothctl", "disconnect", address], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
    except OSError as error:
        log.warning("Não foi possível executar o bluetoothctl: %s", error)
        return
    # O resultado chega depois; uma thread o registra sem travar a interface.
    threading.Thread(target=_log_disconnect_result, args=(address, process), daemon=True).start()


def _log_disconnect_result(address: str, process: subprocess.Popen) -> None:
    try:
        output, _ = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        log.warning("Tempo esgotado ao desconectar %s", address)
        return
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    detail = lines[-1] if lines else ""
    if process.returncode == 0:
        log.info("Desconexão de %s: %s", address, detail or "concluída")
    else:
        log.warning("Falha ao desconectar %s (código %s): %s", address, process.returncode, detail)
