"""Painel de saídas da tela de teste: vibração, gatilhos adaptáveis, LEDs e microfone."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .. import i18n
from ..actions import log_action, log_burst
from ..ds5 import triggers
from ..i18n import tr
from ..service import LedService
from .model import peak_level

log = logging.getLogger(__name__)

PULSE_MS = 400
SEQUENCE_STEP_MS = 450
MIC_NAMES = ("dualsense", "wireless controller")


def selected_controller(service: LedService):
    return next((c for c in service.controllers if c.name == service.selected), None)


def restore_leds(service: LedService) -> None:
    """Devolve barra de luz, jogadores e LED do mute ao que está salvo nas configurações."""
    controller = selected_controller(service)
    service.reapply_selected()
    if controller is not None and controller.hidraw:
        try:
            controller.set_mute_led(service.settings.mute_led)
        except OSError:
            pass


def led_steps(controller) -> list:
    """Passos da sequência de teste: cores da barra, jogadores de 1 a 5 e o LED do mute."""
    steps = [lambda c=color: controller.set_color(*c) for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    steps += [lambda n=n: controller.set_players([i < n for i in range(5)]) for n in range(1, 6)]
    steps += [lambda: controller.set_mute_led(True), lambda: controller.set_mute_led(False)]
    return steps


def _slider(low: int, high: int, value: int) -> QSlider:
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(low, high)
    slider.setValue(value)
    return slider


class TriggerRow(QGroupBox):
    """Efeito, posição e força de um gatilho; cada mudança é enviada ao controle."""

    def __init__(self, title_key: str, send, parent: QWidget | None = None):
        super().__init__(parent)
        i18n.bind(self.setTitle, title_key)
        self._send = send
        layout = QVBoxLayout(self)
        self._effect = QComboBox()
        self._fill_effects()
        i18n.hub.changed.connect(self._fill_effects)
        self._position = _slider(0, triggers.ZONES - 1, 2)
        self._strength = _slider(1, triggers.MAX_STRENGTH, 5)
        layout.addWidget(self._effect)
        for key, slider in (("out.position", self._position), ("out.strength", self._strength)):
            row = QHBoxLayout()
            label = QLabel()
            i18n.bind(label.setText, key)
            row.addWidget(label)
            row.addWidget(slider, 1)
            layout.addLayout(row)
        self._effect.currentIndexChanged.connect(self.emit)
        self._position.valueChanged.connect(self.emit)
        self._strength.valueChanged.connect(self.emit)

    def _fill_effects(self) -> None:
        current = self._effect.currentIndex()
        self._effect.blockSignals(True)
        self._effect.clear()
        for key in triggers.EFFECTS:
            self._effect.addItem(tr(key), key)
        self._effect.setCurrentIndex(max(current, 0))
        self._effect.blockSignals(False)

    def describe(self) -> str:
        return f"{tr(self._effect.currentData())}, posição {self._position.value()}, força {self._strength.value()}"

    def effect(self) -> bytes:
        make = triggers.EFFECTS[self._effect.currentData()]
        return make(self._position.value(), self._strength.value())

    def emit(self) -> None:
        self._send(self.effect())

    def reset(self) -> None:
        self._effect.blockSignals(True)
        self._effect.setCurrentIndex(0)
        self._effect.blockSignals(False)


class MicMeter(QWidget):
    """Nível do microfone do controle, se o sistema o expõe como entrada de áudio."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._label = QLabel()
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)
        layout.addWidget(self._label)
        layout.addWidget(self._bar)
        self._source: QAudioSource | None = None
        self._io = None
        self._float = False
        self._mute = QLabel()
        layout.addWidget(self._mute)

    def start(self) -> None:
        self.stop()
        device = next(
            (d for d in QMediaDevices.audioInputs() if any(n in d.description().lower() for n in MIC_NAMES)),
            None,
        )
        if device is None:
            self._label.setText(tr("out.mic_missing"))
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(48000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
        self._float = fmt.sampleFormat() == QAudioFormat.SampleFormat.Float
        if fmt.sampleFormat() not in (QAudioFormat.SampleFormat.Int16, QAudioFormat.SampleFormat.Float):
            self._label.setText(tr("out.mic_missing"))
            return
        self._source = QAudioSource(device, fmt, self)
        self._io = self._source.start()
        if self._io is None:
            self.stop()
            self._label.setText(tr("out.mic_missing"))
            return
        self._io.readyRead.connect(self._read)
        self._label.setText(tr("out.mic_device", name=device.description()))

    def stop(self) -> None:
        if self._io is not None:
            self._io.readyRead.disconnect(self._read)
        if self._source is not None:
            self._source.stop()
            self._source.deleteLater()
            self._source = self._io = None
        self._bar.setValue(0)

    def _read(self) -> None:
        if self._io is None:  # leitura enfileirada antes de parar
            return
        data = bytes(self._io.readAll())
        if data:
            self._bar.setValue(round(peak_level(data, self._float) * 100))

    def set_mute_pressed(self, pressed: bool) -> None:
        self._mute.setText(tr("out.mute_pressed") if pressed else "")


class OutputPanel(QWidget):
    """Aciona as saídas do controle aberto; `restore` devolve tudo ao normal."""

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._device = None
        self._dirty = False
        self._sequence: list = []
        self._sequence_timer = QTimer(self)
        self._sequence_timer.setInterval(SEQUENCE_STEP_MS)
        self._sequence_timer.timeout.connect(self._sequence_step)
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setSingleShot(True)
        self._pulse_timer.setInterval(PULSE_MS)
        self._pulse_timer.timeout.connect(lambda: self._rumble(0, 0))

        layout = QVBoxLayout(self)

        rumble = QGroupBox()
        i18n.bind(rumble.setTitle, "out.rumble")
        rumble_layout = QVBoxLayout(rumble)
        self._heavy = _slider(0, 255, 0)
        self._light = _slider(0, 255, 0)
        for key, slider in (("out.heavy", self._heavy), ("out.light", self._light)):
            row = QHBoxLayout()
            label = QLabel()
            i18n.bind(label.setText, key)
            row.addWidget(label)
            row.addWidget(slider, 1)
            rumble_layout.addLayout(row)
            slider.valueChanged.connect(lambda _v: self._rumble(self._heavy.value(), self._light.value(), sliders=True))
        pulse = QPushButton()
        i18n.bind(pulse.setText, "out.pulse")
        pulse.clicked.connect(self._pulse)
        rumble_layout.addWidget(pulse)
        layout.addWidget(rumble)

        row = QHBoxLayout()
        self._left = TriggerRow("out.left_trigger", lambda effect: self._trigger("esquerdo", self._left, left_trigger=effect))
        self._right = TriggerRow("out.right_trigger", lambda effect: self._trigger("direito", self._right, right_trigger=effect))
        row.addWidget(self._left)
        row.addWidget(self._right)
        layout.addLayout(row)

        leds = QGroupBox()
        i18n.bind(leds.setTitle, "out.leds")
        leds_layout = QVBoxLayout(leds)
        sequence = QPushButton()
        i18n.bind(sequence.setText, "out.sequence")
        sequence.clicked.connect(self.run_sequence)
        leds_layout.addWidget(sequence)
        layout.addWidget(leds)

        mic = QGroupBox()
        i18n.bind(mic.setTitle, "out.mic")
        self.mic_meter = MicMeter()
        QVBoxLayout(mic).addWidget(self.mic_meter)
        layout.addWidget(mic)
        layout.addStretch(1)

    # --- dispositivo

    def set_device(self, device) -> None:
        """Passa o controle aberto (ou None ao fechar); ao soltar o controle, restaura as saídas."""
        changed = device is not self._device
        if changed:
            self.restore()
        self._device = device
        if device is None:
            self.mic_meter.stop()
        elif changed:
            self.mic_meter.start()

    def _send(self, **fields) -> None:
        if self._device is None:
            return
        try:
            self._device.send_output(**fields)
            self._dirty = True
        except OSError as error:
            log.warning("Falha ao enviar saída ao controle: %s", error)

    # --- vibração

    def _rumble(self, heavy: int, light: int, sliders: bool = False) -> None:
        if not sliders:
            for slider, value in ((self._heavy, heavy), (self._light, light)):
                slider.blockSignals(True)
                slider.setValue(value)
                slider.blockSignals(False)
        self._send(rumble=(heavy, light))
        if sliders:
            self._log_burst("vibração", "teste de vibração", value=f"pesado {heavy}, leve {light}")

    def _trigger(self, side: str, row: TriggerRow, **fields) -> None:
        self._send(**fields)
        self._log_burst(f"gatilho {side}", f"teste do gatilho {side}", value=row.describe())

    def _log_burst(self, key: str, kind: str, **detail) -> None:
        if self._device is None:
            return
        controller = self._controller()
        log_burst(f"{key}:{controller.uid if controller else ''}", kind, controller, **detail)

    def _pulse(self) -> None:
        if self._device is not None:
            log_action("pulso de vibração", self._controller())
        self._rumble(255, 255)
        self._pulse_timer.start()

    # --- LEDs

    def run_sequence(self) -> None:
        controller = self._controller()
        if controller is None or self._sequence_timer.isActive():
            return
        log_action("teste da sequência de LEDs", controller)
        steps = led_steps(controller)
        steps.append(self._restore_leds)
        self._sequence = steps
        self._sequence_timer.start()
        self._sequence_step()

    def _sequence_step(self) -> None:
        if not self._sequence:
            self._sequence_timer.stop()
            return
        try:
            self._sequence.pop(0)()
        except OSError as error:
            log.warning("Falha na sequência de LEDs: %s", error)
            self._sequence.clear()
            self._restore_leds()

    def _controller(self):
        return selected_controller(self._service)

    def _restore_leds(self) -> None:
        restore_leds(self._service)

    # --- restauração

    def restore(self) -> None:
        """Para vibração, gatilhos e sequência de LEDs e devolve os LEDs ao estado salvo."""
        self._pulse_timer.stop()
        if self._sequence_timer.isActive() or self._sequence:
            self._sequence_timer.stop()
            self._sequence.clear()
            self._restore_leds()
        if self._dirty and self._device is not None:
            try:
                self._device.send_output(rumble=(0, 0), left_trigger=triggers.OFF, right_trigger=triggers.OFF)
            except OSError:
                pass
        self._dirty = False
        for slider in (self._heavy, self._light):
            slider.blockSignals(True)
            slider.setValue(0)
            slider.blockSignals(False)
        self._left.reset()
        self._right.reset()
