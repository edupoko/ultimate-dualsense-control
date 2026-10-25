"""Janela "Testar controle": mostra ao vivo as entradas do DualSense selecionado."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent, QHideEvent, QShowEvent
from PySide6.QtWidgets import QGroupBox, QTabWidget, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .. import i18n
from ..ds5.reports import InputState
from ..i18n import tr
from ..service import LedService
from .calibration import CalibrationPanel
from .gyro import GyroPanel
from .outputs import OutputPanel
from .quicktest import QuickTestDialog
from .widgets import ControllerView, ImuPlot, StickView, TouchpadView

POLL_MS = 16


class TestWindow(QWidget):
    """Lê o hidraw do controle escolhido só enquanto a janela está visível."""

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._device = None
        self._error = ""
        self._state: InputState | None = None
        i18n.bind(self.setWindowTitle, "test.title")
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        self._info = QLabel()
        font = self._info.font()
        font.setBold(True)
        self._info.setFont(font)
        top = QHBoxLayout()
        top.addWidget(self._info, 1)
        self._quick = QuickTestDialog(service, self)
        quick = QPushButton()
        i18n.bind(quick.setText, "quick.open")
        quick.clicked.connect(self.open_quick_test)
        top.addWidget(quick)
        root.addLayout(top)
        tabs = QTabWidget()
        root.addWidget(tabs)
        inputs = QWidget()
        layout = QVBoxLayout(inputs)
        self._outputs = OutputPanel(service)
        tabs.addTab(inputs, "")
        tabs.addTab(self._outputs, "")
        self._calibration = CalibrationPanel(service)
        tabs.addTab(self._calibration, "")
        self._gyro_panel = GyroPanel(service)
        tabs.addTab(self._gyro_panel, "")
        i18n.bind(lambda text: tabs.setTabText(0, text), "test.tab_inputs")
        i18n.bind(lambda text: tabs.setTabText(1, text), "test.tab_outputs")
        i18n.bind(lambda text: tabs.setTabText(2, text), "cal.tab")
        i18n.bind(lambda text: tabs.setTabText(3, text), "gyro.tab")

        self._view = ControllerView()
        layout.addWidget(self._view, 2)

        sticks = QHBoxLayout()
        self._sticks = (StickView(), StickView())
        self._triggers = (QProgressBar(), QProgressBar())
        for stick, bar, label in zip(self._sticks, self._triggers, ("L", "R")):
            column = QVBoxLayout()
            column.addWidget(stick, 1)
            bar.setRange(0, 255)
            bar.setFormat(f"{label}2  %v")
            column.addWidget(bar)
            sticks.addLayout(column)
        layout.addLayout(sticks, 3)

        reset = QPushButton()
        i18n.bind(reset.setText, "test.reset_range")
        reset.clicked.connect(lambda: [stick.reset_range() for stick in self._sticks])
        layout.addWidget(reset)

        self._touchpad = TouchpadView()
        self._gyro, self._accel = ImuPlot(), ImuPlot()
        for key, widget in (("test.touchpad", self._touchpad), ("test.gyro", self._gyro), ("test.accel", self._accel)):
            group = QGroupBox()
            i18n.bind(group.setTitle, key)
            QVBoxLayout(group).addWidget(widget)
            layout.addWidget(group, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        service.controllers_changed.connect(self._reopen)
        i18n.hub.changed.connect(self._show_info)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._reopen()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._quick.hide()
        self._close_device()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._close_device()
        super().closeEvent(event)

    def open_quick_test(self) -> None:
        self._quick.set_device(self._device)
        self._quick.show()
        self._quick.raise_()
        self._quick.activateWindow()

    def _close_device(self) -> None:
        self._timer.stop()
        self._quick.set_device(None)
        self._gyro_panel.set_device(None)
        self._calibration.set_device(None)  # cancela um alcance em andamento antes de soltar o controle
        self._outputs.set_device(None)  # restaura vibração, gatilhos e LEDs antes de soltar o controle
        if self._device is not None:
            self._device.close()
            self._device = None

    def _reopen(self) -> None:
        """Abre o hidraw do controle selecionado (de novo, se a seleção ou a conexão mudou)."""
        self._close_device()
        self._error = ""
        controller = next((c for c in self._service.controllers if c.name == self._service.selected), None)
        if controller is None or not self.isVisible():
            self._error = "test.no_controller"
        elif not controller.hidraw:
            self._error = "test.no_hidraw"
        else:
            try:
                self._device = controller.open_device()
            except OSError:
                self._error = "test.no_access"
        self._state = None
        for stick in self._sticks:
            stick.reset_range()
        self._view.set_state(None)
        self._show_info()
        if self._device is not None:
            self._outputs.set_device(self._device)
            self._calibration.set_device(self._device)
            self._gyro_panel.set_device(self._device)
            self._quick.set_device(self._device)
            self._timer.start()

    def _poll(self) -> None:
        try:
            state = self._device.read_state()
        except OSError:  # controle desligado ou desconectado
            self._reopen_later()
            return
        if state is not None:
            self._apply(state)

    def _reopen_later(self) -> None:
        self._quick.note_disconnect()
        self._close_device()
        self._error = "test.no_controller"
        self._show_info()

    def _apply(self, state: InputState) -> None:
        self._state = state
        self._view.set_state(state)
        self._sticks[0].set_position(state.lx, state.ly)
        self._sticks[1].set_position(state.rx, state.ry)
        self._triggers[0].setValue(state.l2)
        self._triggers[1].setValue(state.r2)
        self._outputs.mic_meter.set_mute_pressed("mute" in state.buttons)
        self._calibration.on_state(state)
        self._gyro_panel.on_state(state)
        self._quick.on_state(state)
        self._touchpad.set_touches(state.touches)
        self._gyro.add(self._gyro_panel.correct(state.gyro))
        self._accel.add(state.accel)
        self._show_info()

    def _show_info(self) -> None:
        if self._error:
            self._info.setText(tr(self._error))
            return
        state = self._state
        if state is None:
            self._info.setText(tr("test.waiting"))
            return
        battery = tr(f"test.battery.{state.battery_status}", percent=state.battery_percent)
        self._info.setText(f"{state.connection} · {battery}")
