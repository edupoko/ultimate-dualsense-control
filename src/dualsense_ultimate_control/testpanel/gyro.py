"""Aba de calibração do giroscópio: mede o desvio com o controle parado e salva a correção no app."""

from __future__ import annotations

from collections import deque

from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .. import i18n
from ..actions import log_action
from ..ds5 import imu
from ..ds5.reports import InputState
from ..i18n import tr
from ..service import LedService

# Janela da leitura ao vivo (~1 s com a janela de teste lendo a cada 16 ms).
RECENT_STATES = 60


class GyroPanel(QWidget):
    """Calibra o desvio do giroscópio do controle aberto; a correção vale por USB e Bluetooth."""

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._device = None
        self._uid = ""
        self._calibration: imu.ImuCalibration | None = None
        self._recent: deque[InputState] = deque(maxlen=RECENT_STATES)
        self._collected: list[InputState] | None = None
        self._last_time: int | None = None

        layout = QVBoxLayout(self)
        hint = QLabel()
        hint.setWordWrap(True)
        i18n.bind(hint.setText, "gyro.hint")
        layout.addWidget(hint)
        self._live = QLabel()
        self._saved = QLabel()
        layout.addWidget(self._live)
        layout.addWidget(self._saved)
        self._progress = QProgressBar()
        self._progress.setRange(0, imu.BIAS_SAMPLES)
        layout.addWidget(self._progress)

        buttons = QHBoxLayout()
        self._start_button = QPushButton()
        i18n.bind(self._start_button.setText, "gyro.start")
        self._start_button.clicked.connect(self.start)
        self._clear_button = QPushButton()
        i18n.bind(self._clear_button.setText, "gyro.clear")
        self._clear_button.clicked.connect(self.clear)
        buttons.addWidget(self._start_button)
        buttons.addWidget(self._clear_button)
        layout.addLayout(buttons)
        self._result = QLabel()
        self._result.setWordWrap(True)
        layout.addWidget(self._result)
        layout.addStretch(1)
        self._result_key = ""
        i18n.hub.changed.connect(self._show)
        self._show()

    # --- ligação com a janela de teste

    def set_device(self, device) -> None:
        """Liga ao controle aberto, ou solta (None); soltar no meio da coleta a cancela."""
        self._device = device
        self._collected = None
        self._recent.clear()
        self._last_time = None
        self._result_key = ""
        path = getattr(device, "path", None)
        controller = next((c for c in self._service.controllers if path and c.hidraw == path), None)
        self._uid = controller.uid if controller else ""
        self._calibration = imu.read_calibration(device) if device is not None else None
        self._show()

    @property
    def offset(self) -> imu.Axes | None:
        return self._service.gyro_offset(self._uid) if self._uid else None

    def correct(self, gyro) -> imu.Axes:
        """Leitura do giroscópio com a correção salva deste controle."""
        return imu.apply_offset(gyro, self.offset)

    def on_state(self, state: InputState) -> None:
        # A janela lê o último relatório a cada 16 ms; o mesmo relatório não conta duas vezes.
        if state.sensor_time == self._last_time:
            return
        self._last_time = state.sensor_time
        self._recent.append(state)
        if self._collected is not None:
            self._collected.append(state)
            self._progress.setValue(len(self._collected))
            if len(self._collected) >= imu.BIAS_SAMPLES:
                self._finish()
        self._show()

    @property
    def collecting(self) -> bool:
        return self._collected is not None

    # --- ações

    def start(self) -> None:
        if self._device is None or not self._uid or self.collecting:
            return
        reading = imu.measure_rest(self._recent)
        if reading is None or not reading.stable:
            self._set_result("gyro.not_still")
            log_action("calibração do giroscópio", self._service.controller_for_uid(self._uid) or self._uid, value="recusada (controle em movimento)")
            return
        log_action("calibração do giroscópio", self._service.controller_for_uid(self._uid) or self._uid, value="iniciada")
        self._collected = []
        self._progress.setValue(0)
        self._set_result("gyro.collecting")

    def clear(self) -> None:
        if not self._uid:
            return
        self._service.set_gyro_offset(self._uid, None)
        self._set_result("gyro.cleared")

    def _finish(self) -> None:
        reading = imu.measure_rest(self._collected)
        self._collected = None
        if not reading.stable:
            self._set_result("gyro.moved")
            log_action("calibração do giroscópio", self._service.controller_for_uid(self._uid) or self._uid, value="descartada (houve movimento)")
            return
        self._service.set_gyro_offset(self._uid, reading.offset)
        self._set_result("gyro.done")

    # --- exibição

    def _set_result(self, key: str) -> None:
        self._result_key = key
        self._show()

    def _axes(self, raw: imu.Axes) -> str:
        dps = imu.to_dps(raw, self._calibration)
        return "  ".join(f"{tr(f'gyro.axis{i}')} {v:+.2f}" for i, v in enumerate(dps))

    def _show(self) -> None:
        reading = imu.measure_rest(self._recent)
        if reading is None:
            self._live.setText(tr("gyro.no_data"))
        else:
            key = "gyro.live_still" if reading.stable else "gyro.live_moving"
            self._live.setText(tr(key, axes=self._axes(self.correct(reading.gyro_mean))))
        offset = self.offset
        self._saved.setText(tr("gyro.saved", axes=self._axes(offset)) if offset else tr("gyro.none_saved"))
        if not self.collecting:
            self._progress.setValue(0)
        usable = self._device is not None and bool(self._uid)
        self._start_button.setEnabled(usable and not self.collecting)
        self._clear_button.setEnabled(usable and offset is not None and not self.collecting)
        key = self._result_key or ("" if usable else "gyro.no_device")
        self._result.setText(tr(key) if key else "")
