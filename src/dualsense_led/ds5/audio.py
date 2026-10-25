"""Tom de teste gerado pelo próprio DualSense no alto-falante ou na saída de fone.

Mesma sequência do dualshock-tools: um relatório de saída liga os volumes e o controle de áudio,
depois dois relatórios de feature 0x80 escolhem a saída e ligam o gerador de tom. Só funciona
por USB (por Bluetooth o 0x80 dá EIO).
"""

from __future__ import annotations

FEATURE = 0x80
SPEAKER_VOLUME = 85
HEADPHONE_VOLUME = 55
_ROUTE = {"speaker": (6, 4, 0, 0, 8), "headphones": (6, 4, 0, 0, 0, 0, 4, 0, 6)}
_TONE_ON = (6, 2, 1, 1, 0)
_TONE_OFF = (6, 2, 0, 1, 0)


def play_tone(device, output: str = "speaker") -> None:
    """Liga o tom contínuo em `output` ("speaker" ou "headphones"); `stop_tone` desliga."""
    device.send_output(speaker_volume=SPEAKER_VOLUME, headphone_volume=HEADPHONE_VOLUME, audio_control=0)
    device.set_feature(bytes([FEATURE, *_ROUTE[output]]))
    device.set_feature(bytes([FEATURE, *_TONE_ON]))


def stop_tone(device) -> None:
    """Desliga o gerador de tom. Não zera o volume como a referência: isso calaria o áudio do sistema."""
    device.set_feature(bytes([FEATURE, *_TONE_OFF]))
