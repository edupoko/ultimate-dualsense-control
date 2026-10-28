"""Página "Testar controle": mostra ao vivo as entradas do DualSense selecionado."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QHideEvent, QShowEvent
from PySide6.QtWidgets import QFrame, QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget

from .. import i18n
from ..dialogs import PanelDialog
from ..responsive import Columns, stack
from ..ds5.reports import InputState
from ..i18n import tr
from ..service import LedService
from .calibration import CalibrationPanel
from .gyro import GyroPanel
from .outputs import OutputPanel, selected_controller
from .quicktest import QuickTestDialog
from .widgets import ControllerView, ImuPlot, StickView, TouchpadView

POLL_MS = 16


def _scrolled(widget: QWidget) -> QScrollArea:
    """Cada aba rola sozinha: o QTabWidget não herda a altura da aba mais alta."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidget(widget)
    return scroll


class TestWindow(QWidget):
    """Lê o hidraw do controle escolhido só enquanto a página está visível.

    Entradas e Saídas são abas; Teste rápido e as calibrações abrem em diálogos próprios (F5.3),
    mas os painéis continuam desta página: ela abre e solta o controle e repassa o estado."""

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._device = None
        self._error = ""
        self._state: InputState | None = None

        root = QVBoxLayout(self)
        self._info = QLabel()
        font = self._info.font()
        font.setBold(True)
        self._info.setFont(font)
        root.addWidget(self._info)

        self._calibration = CalibrationPanel(service)
        self._gyro_panel = GyroPanel(service)
        self._quick = QuickTestDialog(service)
        self._dialogs: dict[str, PanelDialog] = {}
        self._panels = {"quick": ("quick.title", self._quick), "calibration": ("cal.title", self._calibration),
                        "gyro": ("gyro.title", self._gyro_panel)}
        tools = QHBoxLayout()
        for key, text_key in (("quick", "test.open_quick"), ("calibration", "test.open_calibration"), ("gyro", "test.open_gyro")):
            button = QPushButton()
            i18n.bind(button.setText, text_key)
            button.clicked.connect(lambda _c=False, key=key: self.open_panel(key))
            tools.addWidget(button)
        tools.addStretch(1)
        root.addLayout(tools)

        self._tabs = tabs = QTabWidget()
        root.addWidget(tabs, 1)
        self._outputs = OutputPanel(service)

        self._view = ControllerView()
        sticks_row = QWidget()
        sticks = QHBoxLayout(sticks_row)
        sticks.setContentsMargins(0, 0, 0, 0)
        self._sticks = (StickView(), StickView())
        for stick in self._sticks:
            sticks.addWidget(stick, 1)
        reset = QPushButton()
        i18n.bind(reset.setText, "test.reset_range")
        reset.clicked.connect(lambda: [stick.reset_range() for stick in self._sticks])

        self._touchpad = TouchpadView()
        self._gyro, self._accel = ImuPlot(), ImuPlot()
        groups = {}
        for key, widget in (("test.touchpad", self._touchpad), ("test.gyro", self._gyro), ("test.accel", self._accel)):
            group = QGroupBox()
            i18n.bind(group.setTitle, key)
            QVBoxLayout(group).addWidget(widget)
            groups[key] = group
        # Janela larga: o desenho do controle e o touchpad à esquerda; analógicos e sensores à direita.
        left = stack(self._view, groups["test.touchpad"], stretch=(3, 1))
        right = stack(sticks_row, reset, groups["test.gyro"], groups["test.accel"], stretch=(2, 0, 1, 1))
        inputs = QWidget()
        QVBoxLayout(inputs).addWidget(Columns(left, right, stretch=(3, 2)))

        tabs.addTab(_scrolled(inputs), "")
        tabs.addTab(_scrolled(self._outputs), "")
        i18n.bind(lambda text: tabs.setTabText(0, text), "test.tab_inputs")
        i18n.bind(lambda text: tabs.setTabText(1, text), "test.tab_outputs")

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        service.controllers_changed.connect(self._reopen)
        i18n.hub.changed.connect(self._show_info)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._reopen()

    def hideEvent(self, event: QHideEvent) -> None:
        # Também chega quando a janela principal troca de página ou vai para a bandeja.
        super().hideEvent(event)
        for dialog in self._dialogs.values():
            dialog.reject()  # os painéis desligam os próprios efeitos ao se esconder
        self._close_device()

    def open_panel(self, key: str) -> PanelDialog:
        """Abre o Teste rápido ("quick") ou uma calibração ("calibration", "gyro") num diálogo próprio."""
        dialog = self._dialogs.get(key)
        if dialog is None:
            title_key, panel = self._panels[key]
            dialog = PanelDialog(title_key, panel, self)
            if key == "quick":
                self._quick.back_requested.connect(dialog.reject)
            self._dialogs[key] = dialog
        dialog.open()
        return dialog

    def open_quick_test(self) -> PanelDialog:
        return self.open_panel("quick")

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
        controller = selected_controller(self._service)
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
