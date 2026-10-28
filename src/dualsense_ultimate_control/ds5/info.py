"""Informações do DualSense (firmware, serial, placa, cor, endereço), só leitura e sem Qt.

Traduzido do `_getInfo` do dualshock-tools (`js/controllers/ds5-controller.js`): feature 0x20
(data e versões do firmware, modelo do hardware), 0x09 (endereço Bluetooth) e as leituras de
sistema por 0x80 → 0x81 (serial, IDs, códigos de barras). Nenhum comando aqui grava no
controle; `[1, 1]` (reiniciar) nunca é enviado. Por Bluetooth o 0x80 dá EIO, então só sai o
que o 0x20 e o 0x09 entregam. Campo que o controle não devolve fica None, nunca inventado.
"""

from __future__ import annotations

import datetime
import struct
from dataclasses import dataclass, fields

FIRMWARE_ID, FIRMWARE_SIZE = 0x20, 64
PAIRING_ID, PAIRING_SIZE = 0x09, 20
SYSTEM_REQUEST, SYSTEM_RESPONSE, SYSTEM_SIZE = 0x80, 0x81, 64

# (base, número, tamanho, texto?) das leituras de sistema, como no getSystemInfo da referência.
SERIAL = (1, 19, 17, True)
MCU_ID = (1, 9, 9, False)
PCBA_ID = (1, 17, 14, True)
BATTERY_BARCODE = (1, 24, 23, True)
VCM_LEFT = (1, 26, 16, True)
VCM_RIGHT = (1, 28, 16, True)
BD_ADDR = (9, 2)
FINETUNE = (12, 2)

# Cor pelo 5º e 6º caracteres do serial (nomes de produto, sem tradução).
COLORS = {
    "00": "White", "01": "Midnight Black", "02": "Cosmic Red", "03": "Nova Pink",
    "04": "Galactic Purple", "05": "Starlight Blue", "06": "Grey Camouflage", "07": "Volcanic Red",
    "08": "Sterling Silver", "09": "Cobalt Blue", "10": "Chroma Teal", "11": "Chroma Indigo",
    "12": "Chroma Pearl", "13": "HyperPop Techno Red", "14": "HyperPop Remix Green",
    "15": "HyperPop Rhythm Blue", "30": "30th Anniversary", "Z1": "God of War Ragnarok",
    "Z2": "Spider-Man 2", "Z3": "Astro Bot", "Z4": "Fortnite", "Z6": "The Last of Us",
    "ZA": "God of War 20th Anniversary", "ZB": "Icon Blue Limited Edition",
    "ZC": "Ghost of Yōtei Limited Edition", "ZD": "Marathon Limited Edition",
    "ZE": "Genshin Impact Limited Edition", "ZF": "007 First Light Limited Edition",
}
BOARDS = {0x03: "BDM-010", 0x04: "BDM-020", 0x05: "BDM-030", 0x06: "BDM-040", 0x07: "BDM-050",
          0x08: "BDM-050", 0x09: "BDM-060R", 0x11: "BDM-060M", 0x13: "BDM-060X"}


@dataclass(frozen=True)
class ControllerInfo:
    # Software
    build: str | None = None
    fw_type: str | None = None
    fw_series: str | None = None
    fw_version: str | None = None
    fw_update: str | None = None
    sbl_version: str | None = None
    venom_version: str | None = None
    spider_version: str | None = None
    # Hardware
    serial: str | None = None
    mcu_id: str | None = None
    pcba_id: str | None = None
    battery_barcode: str | None = None
    vcm_left: str | None = None
    vcm_right: str | None = None
    color: str | None = None
    board: str | None = None
    hw_model: str | None = None
    # "original", "clone" ou None (não verificado: o teste de clone precisa do 0x80, só por USB)
    device_type: str | None = None
    bd_addr: str | None = None

    def is_empty(self) -> bool:
        return all(getattr(self, f.name) is None for f in fields(self))


def parse_firmware(raw: bytes) -> dict:
    """Campos do relatório 0x20 (o id vem no byte 0); vazio se a resposta não for a esperada."""
    if len(raw) < 60 or raw[0] != FIRMWARE_ID:
        return {}
    date = raw[1:12].decode("ascii", "replace")
    time = raw[12:20].decode("ascii", "replace")
    fw_type, series, hw, version = struct.unpack_from("<HHII", raw, 20)
    update = struct.unpack_from("<H", raw, 44)[0]
    sbl, venom, spider = struct.unpack_from("<III", raw, 48)
    return {
        "build": f"{date} {time}", "build_date": date,
        "fw_type": f"0x{fw_type:04X}", "fw_series": f"0x{series:04X}",
        "hw_model": f"0x{hw:08X}", "board": board_model(hw), "fw_version": f"0x{version:08X}",
        "fw_update": f"0x{update:04X}", "sbl_version": f"0x{sbl:08X}",
        "venom_version": f"0x{venom:08X}", "spider_version": f"0x{spider:08X}",
    }


def board_model(hw: int) -> str | None:
    return BOARDS.get((hw >> 8) & 0xFF)


def color_name(serial: str | None) -> str | None:
    return COLORS.get(serial[4:6]) if serial and len(serial) >= 6 else None


def format_mac(data: bytes) -> str | None:
    """Endereço guardado de trás para frente (byte menos significativo primeiro)."""
    return ":".join(f"{b:02x}" for b in reversed(data)) if len(data) == 6 else None


def parse_pairing(raw: bytes) -> str | None:
    """Endereço do controle no relatório 0x09 (bytes 1–6)."""
    return format_mac(raw[1:7]) if len(raw) >= 7 and raw[0] == PAIRING_ID else None


def parse_system(raw: bytes, base: int, number: int, length: int, text: bool) -> str | None:
    """Resposta 0x81 de uma leitura de sistema: confere base/número/estado 2 e corta o valor."""
    if len(raw) < 4 + length or raw[0] != SYSTEM_RESPONSE or raw[1:4] != bytes([base, number, 2]):
        return None
    value = raw[4:4 + length]
    return value.decode("ascii", "replace").rstrip("\0") if text else value.hex()


def clone_by_date(build_date: str, year: int) -> bool:
    """Firmware compilado num ano futuro não é original (um clone diz "Jan 29 2034")."""
    try:
        return int(build_date.strip()[-4:]) > year
    except ValueError:
        return False


def _system(device, command: tuple[int, ...]) -> bytes | None:
    try:
        device.set_feature(bytes([SYSTEM_REQUEST, *command]))
        return device.get_feature(SYSTEM_RESPONSE, SYSTEM_SIZE)
    except OSError:
        return None


def _read_system(device, spec) -> str | None:
    base, number, length, text = spec
    raw = _system(device, (base, number))
    return parse_system(raw, base, number, length, text) if raw is not None else None


def _finetune_ok(device) -> bool:
    """Todo controle original responde à leitura do ajuste fino dos analógicos (12, 2)."""
    raw = _system(device, FINETUNE)
    return raw is not None and len(raw) >= 4 and raw[0] == SYSTEM_RESPONSE and raw[1] == 12 and raw[2] in (2, 4) and raw[3] == 2


def read_info(device, usb: bool, year: int | None = None) -> ControllerInfo:
    """Lê tudo que o controle entrega; cada campo trata o próprio erro."""
    year = year or datetime.date.today().year
    values: dict = {}
    try:
        values.update(parse_firmware(device.get_feature(FIRMWARE_ID, FIRMWARE_SIZE)))
    except OSError:
        pass
    build_date = values.pop("build_date", None)
    if usb:
        for name, spec in (("serial", SERIAL), ("mcu_id", MCU_ID), ("pcba_id", PCBA_ID),
                           ("battery_barcode", BATTERY_BARCODE), ("vcm_left", VCM_LEFT), ("vcm_right", VCM_RIGHT)):
            values[name] = _read_system(device, spec)
        if values["pcba_id"]:
            values["pcba_id"] = values["pcba_id"][::-1]  # a referência mostra invertido
        raw = _system(device, BD_ADDR)
        values["bd_addr"] = format_mac(raw[4:10]) if raw and len(raw) >= 10 and raw[0] == SYSTEM_RESPONSE else None
    if not values.get("bd_addr"):
        try:
            values["bd_addr"] = parse_pairing(device.get_feature(PAIRING_ID, PAIRING_SIZE))
        except OSError:
            values["bd_addr"] = None
    values["color"] = color_name(values.get("serial"))
    if build_date is not None and clone_by_date(build_date, year):
        values["device_type"] = "clone"
    elif usb and build_date is not None:
        values["device_type"] = "original" if _finetune_ok(device) else "clone"
    return ControllerInfo(**values)
