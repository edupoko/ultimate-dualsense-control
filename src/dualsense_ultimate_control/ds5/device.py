"""Acesso a um DualSense pelo /dev/hidrawN: ler entrada, enviar saída e relatórios de feature."""

from __future__ import annotations

import fcntl
import os

from .reports import InputState, build_output_report, parse_input_report

# ioctls do hidraw (linux/hidraw.h): _IOC(READ|WRITE, 'H', número, tamanho).
_IOC_READ_WRITE = 3 << 30
_HID_IOC_TYPE = ord("H") << 8
_SET_FEATURE, _GET_FEATURE = 0x06, 0x07

_MAX_READ = 128


def _ioc(number: int, size: int) -> int:
    return _IOC_READ_WRITE | (size << 16) | _HID_IOC_TYPE | number


class DualSenseDevice:
    """Um controle aberto para leitura e escrita; a leitura não bloqueia."""

    def __init__(self, path: str, connection: str):
        self.path = path
        self.connection = connection
        self._sequence = 0
        self._fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)

    def __enter__(self) -> DualSenseDevice:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def fileno(self) -> int:
        """Descritor para QSocketNotifier ou select."""
        return self._fd

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def read_state(self) -> InputState | None:
        """Último relatório de entrada pendente, ou None se não há nenhum.

        Descarta os intermediários: quem chama quer o estado mais recente, não o histórico.
        """
        latest = None
        while True:
            try:
                data = os.read(self._fd, _MAX_READ)
            except BlockingIOError:
                return latest
            state = parse_input_report(data)
            if state is not None:
                latest = state

    def send_output(self, **fields) -> None:
        """Envia um relatório de saída (campos de `build_output_report`)."""
        report = build_output_report(self.connection, self._sequence, **fields)
        self._sequence = (self._sequence + 1) & 0x0F
        os.write(self._fd, report)

    def get_feature(self, report_id: int, size: int) -> bytes:
        """Lê um relatório de feature; `size` inclui o byte do id."""
        buffer = bytearray(size)
        buffer[0] = report_id
        length = fcntl.ioctl(self._fd, _ioc(_GET_FEATURE, size), buffer)
        return bytes(buffer[:length]) if isinstance(length, int) and length > 0 else bytes(buffer)

    def set_feature(self, data: bytes) -> None:
        """Envia um relatório de feature; o primeiro byte é o id."""
        buffer = bytearray(data)
        fcntl.ioctl(self._fd, _ioc(_SET_FEATURE, len(buffer)), buffer)
