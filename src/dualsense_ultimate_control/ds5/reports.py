"""Relatórios HID do DualSense: leitura dos de entrada e montagem dos de saída.

Só bytes e contas, sem abrir dispositivo, para dar para testar sem o controle. Os deslocamentos
seguem a estrutura do driver hid-playstation do kernel (dualsense_input_report e
dualsense_output_report_common).
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

USB_INPUT_ID = 0x01
USB_INPUT_SIZE = 64
BT_INPUT_ID = 0x31
BT_INPUT_SIZE = 78
BT_INPUT_CRC_SEED = 0xA1

USB_OUTPUT_ID = 0x02
USB_OUTPUT_SIZE = 64  # id + 63 bytes
BT_OUTPUT_ID = 0x31
BT_OUTPUT_SIZE = 78
BT_TAG = 0x10
BT_OUTPUT_CRC_SEED = 0xA2

# O bloco de dados do relatório de entrada começa depois do id (USB) ou de id + sequência (Bluetooth).
_USB_DATA = 1
_BT_DATA = 2

# Posições dentro do bloco de dados de entrada.
IN_LX, IN_LY, IN_RX, IN_RY, IN_L2, IN_R2 = 0, 1, 2, 3, 4, 5
IN_SEQ = 6
IN_BUTTONS = 7  # 3 bytes: dpad+rosto, ombros+sticks, PS/touchpad/mute/extras
IN_GYRO = 15  # 3 × int16 little-endian
IN_ACCEL = 21  # 3 × int16 little-endian
IN_SENSOR_TIME = 27  # uint32 little-endian, unidade de 0,333 µs
IN_TOUCH = 32  # 2 pontos de 4 bytes
IN_BATTERY = 52
IN_STATUS1 = 53  # bit 0: fone no conector; bit 1: microfone externo (hid-playstation)

TOUCHPAD_WIDTH = 1920
TOUCHPAD_HEIGHT = 1080

_HAT = {0: "up", 1: "up_right", 2: "right", 3: "down_right", 4: "down", 5: "down_left", 6: "left", 7: "up_left"}

# (byte relativo a IN_BUTTONS, máscara, nome)
_BUTTONS = (
    (0, 0x10, "square"), (0, 0x20, "cross"), (0, 0x40, "circle"), (0, 0x80, "triangle"),
    (1, 0x01, "l1"), (1, 0x02, "r1"), (1, 0x04, "l2"), (1, 0x08, "r2"),
    (1, 0x10, "create"), (1, 0x20, "options"), (1, 0x40, "l3"), (1, 0x80, "r3"),
    (2, 0x01, "ps"), (2, 0x02, "touchpad"), (2, 0x04, "mute"),
    # Só o DualSense Edge; no modelo comum esses bits ficam sempre em zero.
    (2, 0x10, "fn_left"), (2, 0x20, "fn_right"), (2, 0x40, "paddle_left"), (2, 0x80, "paddle_right"),
)
BUTTON_NAMES = tuple(name for _, _, name in _BUTTONS)

_BATTERY_STATUS = {0: "discharging", 1: "charging", 2: "full"}


@dataclass(frozen=True)
class Touch:
    """Um dedo no touchpad (x de 0 a 1919, y de 0 a 1079)."""

    id: int
    x: int
    y: int


@dataclass(frozen=True)
class InputState:
    """Estado do controle num relatório de entrada."""

    connection: str
    sequence: int
    lx: int  # sticks e gatilhos de 0 a 255; 128 é o centro dos sticks
    ly: int
    rx: int
    ry: int
    l2: int
    r2: int
    dpad: str | None  # "up", "up_right", ... ou None com o direcional solto
    buttons: frozenset[str]  # inclui o clique digital de L2/R2 e o direcional fora daqui
    gyro: tuple[int, int, int]  # pitch, yaw, roll brutos
    accel: tuple[int, int, int]
    sensor_time: int
    touches: tuple[Touch | None, Touch | None]
    battery_percent: int
    battery_status: str  # "discharging", "charging", "full" ou "error"
    headphones: bool = False  # algo ligado na saída de fone


def bt_crc(seed: int, report: bytes) -> bytes:
    """CRC32 (4 bytes, little-endian) de `report` precedido do byte `seed`."""
    return (zlib.crc32(bytes([seed]) + report) & 0xFFFFFFFF).to_bytes(4, "little")


def parse_input_report(data: bytes, check_crc: bool = True) -> InputState | None:
    """Lê um relatório de entrada completo; devolve None se não for um (ou o CRC Bluetooth falhar).

    O relatório simples do Bluetooth (0x01 com 10 bytes, antes de o driver ativar o modo completo)
    não traz sensores nem touchpad e é ignorado.
    """
    if len(data) >= USB_INPUT_SIZE and data[0] == USB_INPUT_ID:
        connection, base = "USB", _USB_DATA
    elif len(data) >= BT_INPUT_SIZE and data[0] == BT_INPUT_ID:
        if check_crc and bt_crc(BT_INPUT_CRC_SEED, data[: BT_INPUT_SIZE - 4]) != data[BT_INPUT_SIZE - 4 : BT_INPUT_SIZE]:
            return None
        connection, base = "Bluetooth", _BT_DATA
    else:
        return None

    block = data[base:]
    raw = block[IN_BUTTONS : IN_BUTTONS + 3]
    hat = raw[0] & 0x0F
    buttons = frozenset(name for index, mask, name in _BUTTONS if raw[index] & mask)
    return InputState(
        connection=connection,
        sequence=block[IN_SEQ],
        lx=block[IN_LX], ly=block[IN_LY], rx=block[IN_RX], ry=block[IN_RY],
        l2=block[IN_L2], r2=block[IN_R2],
        dpad=_HAT.get(hat),
        buttons=buttons,
        gyro=_int16s(block, IN_GYRO),
        accel=_int16s(block, IN_ACCEL),
        sensor_time=int.from_bytes(block[IN_SENSOR_TIME : IN_SENSOR_TIME + 4], "little"),
        touches=(_touch(block, IN_TOUCH), _touch(block, IN_TOUCH + 4)),
        **_battery(block[IN_BATTERY]),
        headphones=bool(block[IN_STATUS1] & 0x01),
    )


def _int16s(block: bytes, offset: int) -> tuple[int, int, int]:
    return tuple(int.from_bytes(block[offset + 2 * i : offset + 2 * i + 2], "little", signed=True) for i in range(3))


def _touch(block: bytes, offset: int) -> Touch | None:
    contact, x_low, mixed, y_high = block[offset : offset + 4]
    if contact & 0x80:  # bit 7 aceso significa "sem dedo"
        return None
    return Touch(contact & 0x7F, ((mixed & 0x0F) << 8) | x_low, (y_high << 4) | (mixed >> 4))


def _battery(status: int) -> dict:
    level, state = status & 0x0F, status >> 4
    if state == 2:
        percent = 100
    else:
        percent = min(level * 10 + 5, 100)
    return {"battery_percent": percent, "battery_status": _BATTERY_STATUS.get(state, "error")}


# --- saída -----------------------------------------------------------------------------------------

# Posições no bloco comum de 47 bytes, igual nos dois relatórios.
COMMON_VALID_FLAG0 = 0
COMMON_VALID_FLAG1 = 1
COMMON_MOTOR_RIGHT = 2  # motor leve (alta frequência)
COMMON_MOTOR_LEFT = 3  # motor pesado
COMMON_HEADPHONE_VOLUME = 4
COMMON_SPEAKER_VOLUME = 5
COMMON_AUDIO_CONTROL = 7
COMMON_MUTE_BUTTON_LED = 8
COMMON_RIGHT_TRIGGER = 10  # 11 bytes de efeito
COMMON_LEFT_TRIGGER = 21
COMMON_VALID_FLAG2 = 38
COMMON_SIZE = 47
TRIGGER_EFFECT_SIZE = 11

VALID_FLAG0_COMPATIBLE_VIBRATION = 0x01
VALID_FLAG0_HAPTICS_SELECT = 0x02
VALID_FLAG0_RIGHT_TRIGGER = 0x04
VALID_FLAG0_LEFT_TRIGGER = 0x08
VALID_FLAG0_HEADPHONE_VOLUME = 0x10
VALID_FLAG0_SPEAKER_VOLUME = 0x20
VALID_FLAG0_AUDIO_CONTROL = 0x80
VALID_FLAG1_MIC_MUTE_LED_CONTROL_ENABLE = 0x01
VALID_FLAG2_COMPATIBLE_VIBRATION2 = 0x04

# O número de sequência (4 bits) vai no relatório Bluetooth e dá a volta em 16.
SEQUENCE_MASK = 0x0F


def build_output_report(
    connection: str,
    sequence: int = 0,
    *,
    mute_led: bool | None = None,
    rumble: tuple[int, int] | None = None,
    right_trigger: bytes | None = None,
    left_trigger: bytes | None = None,
    speaker_volume: int | None = None,
    headphone_volume: int | None = None,
    audio_control: int | None = None,
) -> bytes:
    """Relatório de saída que mexe só nos campos informados; os demais ficam como estão no controle.

    `rumble` é (motor pesado, motor leve), de 0 a 255. `right_trigger` e `left_trigger` são os 11
    bytes de efeito do gatilho adaptável. Volumes e `audio_control` (roteamento) vão de 0 a 255.
    """
    bluetooth = connection == "Bluetooth"
    if bluetooth:
        report = bytearray(BT_OUTPUT_SIZE)
        report[0] = BT_OUTPUT_ID
        report[1] = (sequence & SEQUENCE_MASK) << 4
        report[2] = BT_TAG
        common = 3
    else:
        report = bytearray(USB_OUTPUT_SIZE)
        report[0] = USB_OUTPUT_ID
        common = 1

    if mute_led is not None:
        report[common + COMMON_VALID_FLAG1] |= VALID_FLAG1_MIC_MUTE_LED_CONTROL_ENABLE
        report[common + COMMON_MUTE_BUTTON_LED] = 1 if mute_led else 0
    if rumble is not None:
        heavy, light = rumble
        report[common + COMMON_VALID_FLAG0] |= VALID_FLAG0_COMPATIBLE_VIBRATION | VALID_FLAG0_HAPTICS_SELECT
        report[common + COMMON_VALID_FLAG2] |= VALID_FLAG2_COMPATIBLE_VIBRATION2
        report[common + COMMON_MOTOR_LEFT] = _byte(heavy)
        report[common + COMMON_MOTOR_RIGHT] = _byte(light)
    for value, flag, offset in (
        (headphone_volume, VALID_FLAG0_HEADPHONE_VOLUME, COMMON_HEADPHONE_VOLUME),
        (speaker_volume, VALID_FLAG0_SPEAKER_VOLUME, COMMON_SPEAKER_VOLUME),
        (audio_control, VALID_FLAG0_AUDIO_CONTROL, COMMON_AUDIO_CONTROL),
    ):
        if value is not None:
            report[common + COMMON_VALID_FLAG0] |= flag
            report[common + offset] = _byte(value)
    for effect, flag, offset in (
        (right_trigger, VALID_FLAG0_RIGHT_TRIGGER, COMMON_RIGHT_TRIGGER),
        (left_trigger, VALID_FLAG0_LEFT_TRIGGER, COMMON_LEFT_TRIGGER),
    ):
        if effect is not None:
            if len(effect) != TRIGGER_EFFECT_SIZE:
                raise ValueError(f"efeito de gatilho tem {TRIGGER_EFFECT_SIZE} bytes, recebeu {len(effect)}")
            report[common + COMMON_VALID_FLAG0] |= flag
            report[common + offset : common + offset + TRIGGER_EFFECT_SIZE] = effect

    if bluetooth:
        # CRC32 do relatório inteiro (menos os 4 bytes finais), precedido do byte 0xA2.
        report[-4:] = bt_crc(BT_OUTPUT_CRC_SEED, bytes(report[:-4]))
    return bytes(report)


def _byte(value: int) -> int:
    return max(0, min(255, int(value)))
