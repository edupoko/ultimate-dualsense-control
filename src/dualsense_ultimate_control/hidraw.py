"""LED do botão de microfone do DualSense.

O driver do kernel não expõe esse LED pelo sysfs (ele só o acende quando você aperta o botão de
microfone), então o app envia o relatório de saída direto pelo /dev/hidrawN do controle. O
relatório só liga a flag do LED de microfone, sem mexer em cor, LEDs de jogador, vibração ou áudio.
"""

from __future__ import annotations

import itertools
import os

from .ds5.reports import build_output_report

# O número de sequência (4 bits) vai no relatório Bluetooth e dá a volta em 16.
_sequence = itertools.count()


def build_mute_led_report(on: bool, connection: str, sequence: int = 0) -> bytes:
    """Relatório de saída que liga ou desliga só o LED do botão de microfone."""
    return build_output_report(connection, sequence, mute_led=on)


def set_mute_led(hidraw: str, on: bool, connection: str) -> None:
    """Envia o relatório ao controle em `hidraw` (ex.: /dev/hidraw10)."""
    report = build_mute_led_report(on, connection, next(_sequence))
    descriptor = os.open(hidraw, os.O_WRONLY)
    try:
        os.write(descriptor, report)
    finally:
        os.close(descriptor)
