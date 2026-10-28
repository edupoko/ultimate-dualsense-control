"""Aba de calibração dos analógicos: centro e alcance (temporários), salvar no controle e reiniciar."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import i18n
from ..actions import log_action
from ..confirm import ConfirmBar
from ..dialogs import ask_irreversible
from ..ds5 import calibration
from ..ds5.reports import InputState
from ..i18n import tr
from ..service import LedService
from .outputs import selected_controller
from .widgets import StickView

log = logging.getLogger(__name__)

ACTION_LABELS = {
    "center": "calibração do centro",
    "range": "calibração do alcance",
    "save": "gravar calibração no controle",
    "reboot": "reiniciar controle (calibração)",
}

RECENT_STATES = 30
# Perguntas que viram diálogo modal (ação que grava no controle ou o reinicia) e o texto do botão.
IRREVERSIBLE = {"cal.confirm_save": "cal.do_save", "cal.confirm_reboot": "cal.do_reboot"}


class CalibrationPanel(QWidget):
    """Assistente de calibração do controle aberto na janela de teste (só por USB)."""

    def __init__(self, service: LedService, history_file: Path | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._history_file = history_file or calibration.history_path(service.settings_path)
        self._device = None
        self._connection = ""
        self._ranging = False
        # Caminhos hidraw com calibração aplicada e ainda não gravada (some quando o controle reinicia).
        self._pending: set[str] = set()
        self._recent: deque[InputState] = deque(maxlen=RECENT_STATES)
        self._range_points: tuple[list, list] = ([], [])
        self._range_before: dict = {}

        layout = QVBoxLayout(self)
        self._bar = ConfirmBar()
        layout.addWidget(self._bar)
        warning = QLabel()
        warning.setWordWrap(True)
        i18n.bind(warning.setText, "cal.warning")
        layout.addWidget(warning)

        sticks = QHBoxLayout()
        self._sticks = (StickView(), StickView())
        for stick in self._sticks:
            sticks.addWidget(stick)
        layout.addLayout(sticks, 1)

        self._drift = QLabel()
        layout.addWidget(self._drift)

        center = QGroupBox()
        i18n.bind(center.setTitle, "cal.center")
        center_layout = QVBoxLayout(center)
        hint = QLabel()
        hint.setWordWrap(True)
        i18n.bind(hint.setText, "cal.center_hint")
        self._center_button = QPushButton()
        i18n.bind(self._center_button.setText, "cal.center_start")
        self._center_button.clicked.connect(self.run_center)
        center_layout.addWidget(hint)
        center_layout.addWidget(self._center_button)
        layout.addWidget(center)

        range_box = QGroupBox()
        i18n.bind(range_box.setTitle, "cal.range")
        range_layout = QVBoxLayout(range_box)
        self._range_hint = QLabel()
        self._range_hint.setWordWrap(True)
        i18n.bind(self._range_hint.setText, "cal.range_hint")
        buttons = QHBoxLayout()
        self._range_button = QPushButton()
        i18n.bind(self._range_button.setText, "cal.range_start")
        self._range_button.clicked.connect(self.start_range)
        self._range_finish = QPushButton()
        i18n.bind(self._range_finish.setText, "cal.range_finish")
        self._range_finish.clicked.connect(self.finish_range)
        self._range_cancel = QPushButton()
        i18n.bind(self._range_cancel.setText, "cal.range_cancel")
        self._range_cancel.clicked.connect(self.cancel_range)
        for button in (self._range_button, self._range_finish, self._range_cancel):
            buttons.addWidget(button)
        range_layout.addWidget(self._range_hint)
        range_layout.addLayout(buttons)
        layout.addWidget(range_box)

        persist = QHBoxLayout()
        self._save_button = QPushButton()
        i18n.bind(self._save_button.setText, "cal.save")
        self._save_button.clicked.connect(self.run_save)
        self._reboot_button = QPushButton()
        i18n.bind(self._reboot_button.setText, "cal.reboot")
        self._reboot_button.clicked.connect(self.run_reboot)
        persist.addWidget(self._save_button)
        persist.addWidget(self._reboot_button)
        layout.addLayout(persist)

        self._result = QLabel()
        self._result.setWordWrap(True)
        layout.addWidget(self._result)
        self._history = QPlainTextEdit()
        self._history.setReadOnly(True)
        self._history.setMinimumHeight(100)
        layout.addWidget(self._history, 1)  # no diálogo, o histórico fica com a altura que sobra
        self._result_key, self._result_values = "", {}
        i18n.hub.changed.connect(self._show_result)
        self._update_buttons()
        self._show_history()

    # --- ligação com a janela de teste

    def set_device(self, device) -> None:
        """Liga ao controle aberto, ou solta (None); soltar no meio do alcance cancela e descarta."""
        if self._ranging:
            self.cancel_range()
        self._device = device
        self._connection = getattr(device, "connection", "")
        self._recent.clear()
        for stick in self._sticks:
            stick.reset_range()
        self._update_buttons()
        self._show_drift()

    def on_state(self, state: InputState) -> None:
        self._recent.append(state)
        self._sticks[0].set_position(state.lx, state.ly)
        self._sticks[1].set_position(state.rx, state.ry)
        if self._ranging:
            self._range_points[0].append((state.lx, state.ly))
            self._range_points[1].append((state.rx, state.ry))
            self._range_finish.setEnabled(self.range_ready)
        self._show_drift()

    @property
    def range_ready(self) -> bool:
        return all(calibration.range_complete(calibration.range_extremes(points)) for points in self._range_points)

    # --- ações

    def run_center(self) -> None:
        if self._ready():
            self._confirm("cal.confirm_center", self._do_center)

    def _do_center(self) -> None:
        before = self._before()
        try:
            calibration.calibrate_center(self._device)
        except (OSError, calibration.CalibrationError) as error:
            self._fail("center", before, error)
        else:
            self._applied("center", before)

    def start_range(self) -> None:
        if self._ready():
            self._confirm("cal.confirm_range", self._do_start_range)

    def _do_start_range(self) -> None:
        before = self._before()
        try:
            calibration.range_begin(self._device)
        except (OSError, calibration.CalibrationError) as error:
            self._fail("range", before, error)
            return
        self._ranging = True
        self._range_before = before
        self._range_points = ([], [])
        for stick in self._sticks:
            stick.reset_range()
        self._update_buttons()

    def finish_range(self) -> None:
        if not self._ranging:
            return
        if self.range_ready:
            self._do_finish_range()
        else:
            self._confirm("cal.confirm_incomplete", self._do_finish_range)

    def _do_finish_range(self) -> None:
        if not self._ranging:
            return
        self._ranging = False
        try:
            calibration.range_end(self._device)
        except (OSError, calibration.CalibrationError) as error:
            self._fail("range", self._range_before, error)
        else:
            self._applied("range", self._range_before)
        self._update_buttons()

    def cancel_range(self) -> None:
        """Fecha a coleta (o controle não sai dela sem o "end") e reinicia para descartar o alcance parcial."""
        if not self._ranging:
            return
        self._ranging = False
        try:
            calibration.range_end(self._device)
        except (OSError, calibration.CalibrationError):
            log.warning("Falha ao encerrar a calibração de alcance cancelada; reiniciando o controle")
        self._discard()
        log_action("calibração do alcance", selected_controller(self._service), value="cancelada")
        self._set_result("cal.cancelled")
        self._update_buttons()

    def run_save(self) -> None:
        if self._ready():
            self._confirm("cal.confirm_save", self._do_save)

    def _do_save(self) -> None:
        before = self._before()
        try:
            status = calibration.save(self._device)
        except (OSError, calibration.CalibrationError) as error:
            log.warning("Gravação da calibração falhou: %s", error)
            self._record("save", False, before, str(error))
            self._set_result("cal.save_failed", error=str(error))
            return
        self._pending.discard(self._device.path)
        self._record("save", True, before, f"nvs={status:#x}" if status is not None else "")
        self._set_result("cal.done_reboot" if status == calibration.NVS_PENDING_REBOOT else "cal.done")
        self._update_buttons()

    def run_reboot(self) -> None:
        if self._ready():
            self._confirm("cal.confirm_reboot", self._do_reboot)

    def _do_reboot(self) -> None:
        self._record("reboot", True, self._before(), "")
        self._discard()
        self._set_result("cal.rebooted")
        self._update_buttons()

    # --- apoio

    def _confirm(self, key: str, proceed: Callable[[], None]) -> None:
        """Pergunta e só então faz `proceed` (que confere de novo se o controle ainda serve); os testes
        substituem este método. Gravar e reiniciar perguntam num diálogo modal com "Cancelar" como
        padrão; centro e alcance (só na RAM) perguntam na faixa do topo."""
        def confirmed() -> None:
            if self._ready() or (self._ranging and self._device is not None):
                proceed()

        if key in IRREVERSIBLE:
            if ask_irreversible(self, tr(key), tr(IRREVERSIBLE[key])):
                confirmed()
            return
        self._bar.ask(tr(key), confirmed)

    def hideEvent(self, event) -> None:
        # O diálogo fechou no meio do alcance: sai da coleta e descarta, como ao soltar o controle.
        super().hideEvent(event)
        if self._ranging:
            self.cancel_range()

    def _ready(self) -> bool:
        return self._device is not None and self._connection == "USB" and not self._ranging

    @property
    def has_pending(self) -> bool:
        return self._device is not None and getattr(self._device, "path", None) in self._pending

    def _discard(self) -> None:
        """Reinicia o controle; a janela de teste o reabre quando ele voltar."""
        self._pending.discard(getattr(self._device, "path", None))
        calibration.reboot(self._device)

    def _before(self) -> dict:
        reading = calibration.average_center(self._recent)
        before = {"center": [round(v, 1) for v in (reading.lx, reading.ly, reading.rx, reading.ry)]} if reading else {}
        return before

    def _applied(self, action: str, before: dict) -> None:
        self._pending.add(self._device.path)
        self._record(action, True, before, "temporária")
        self._set_result("cal.applied")
        self._update_buttons()

    def _fail(self, action: str, before: dict, error: Exception) -> None:
        """Registra a falha e reinicia o controle: parado no meio do begin/end ele ficaria no modo de calibração."""
        log.warning("Calibração (%s) falhou: %s", action, error)
        self._record(action, False, before, str(error))
        self._discard()
        self._set_result("cal.failed", error=str(error))
        self._update_buttons()

    def _record(self, action: str, ok: bool, before: dict, detail: str) -> None:
        controller = selected_controller(self._service)
        label = ACTION_LABELS.get(action, action)
        log_action(label, controller, value="ok" if ok else "falhou", detalhe=detail) if detail else log_action(
            label, controller, value="ok" if ok else "falhou"
        )
        entry = calibration.HistoryEntry(
            datetime.now().isoformat(timespec="seconds"), controller.uid if controller else "", action, ok, before,
            detail, calibration.read_imu_backup(self._device) if self._device is not None else "",
        )
        try:
            calibration.append_history(self._history_file, entry)
        except OSError:
            log.warning("Não foi possível gravar o histórico de calibração")
        self._show_history()

    def _set_result(self, key: str, **values) -> None:
        self._result_key, self._result_values = key, values
        self._show_result()

    def _show_result(self) -> None:
        self._result.setText(tr(self._result_key, **self._result_values) if self._result_key else "")

    def _show_drift(self) -> None:
        reading = calibration.average_center(self._recent)
        if reading is None or self._ranging:
            self._drift.setText("")
            return
        key = "cal.drift_needs" if reading.needs_calibration else "cal.drift_ok"
        self._drift.setText(tr(key, drift=f"{reading.drift:.1f}"))

    def _show_history(self) -> None:
        lines = [
            f"{e.get('time', '')}  {e.get('action', '')}  {'OK' if e.get('ok') else 'ERRO'}  {e.get('detail', '')}"
            for e in reversed(calibration.load_history(self._history_file)[-10:])
        ]
        self._history.setPlainText("\n".join(lines))

    def _update_buttons(self) -> None:
        ranging = self._ranging
        usable = self._device is not None and self._connection == "USB"
        self._center_button.setEnabled(usable and not ranging)
        self._save_button.setEnabled(usable and not ranging and self.has_pending)
        self._reboot_button.setEnabled(usable and not ranging)
        self._range_button.setEnabled(usable and not ranging)
        self._range_finish.setEnabled(ranging and self.range_ready)
        self._range_cancel.setEnabled(ranging)
        if self._device is None:
            self._set_result("cal.no_device")
        elif self._connection != "USB":
            self._set_result("cal.usb_only")
        elif self._result_key in ("cal.no_device", "cal.usb_only"):
            self._set_result("")
