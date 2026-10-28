"""Janela "Teste rápido": checklist guiado item a item, navegável pelos botões do controle."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import i18n
from ..actions import log_action
from ..ds5 import audio, triggers
from ..ds5.reports import InputState
from ..i18n import tr
from ..service import LedService
from . import sequence
from .outputs import MicMeter, led_steps, restore_leds, selected_controller
from .widgets import StickView, TouchpadView

log = logging.getLogger(__name__)

AUTO_PASS_MS = 600
HAPTIC_STEP_MS = 500
LIGHTS_STEP_MS = 450
SPEAKER_TONE_MS = 1000
HEADPHONE_TONE_MS = 700

PASSED_COLOR, FAILED_COLOR, UNTESTED_COLOR = "#2e7d32", "#c62828", "#616161"

# Nomes dos botões como aparecem no controle; não se traduzem.
BUTTON_LABELS = {
    "up": "↑", "down": "↓", "left": "←", "right": "→", "square": "□", "cross": "✕", "circle": "○", "triangle": "△",
    "l1": "L1", "r1": "R1", "l2": "L2", "r2": "R2", "l3": "L3", "r3": "R3",
    "create": "Create", "options": "Options", "ps": "PS", "touchpad": "Touchpad", "mute": "Mute",
}


class ChecksView(QWidget):
    """Grade com as verificações automáticas de um item: cinza até cumprir, verde depois."""

    def __init__(self, names: tuple[str, ...], columns: int, translate: bool, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._labels: dict[str, QLabel] = {}
        self._translate = translate
        for index, name in enumerate(names):
            label = QLabel()
            layout.addWidget(label, index // columns, index % columns)
            self._labels[name] = label
        self.update_checks(dict.fromkeys(names, False))
        i18n.hub.changed.connect(lambda: self.update_checks(self._last))

    def update_checks(self, checks: dict[str, bool]) -> None:
        self._last = dict(checks)
        for name, done in checks.items():
            text = tr(f"quick.check.{name}") if self._translate else BUTTON_LABELS.get(name, name)
            label = self._labels[name]
            label.setText(f"{'✓' if done else '•'} {text}")
            label.setStyleSheet(f"color: {PASSED_COLOR}; font-weight: bold;" if done else "")


class ItemRow(QFrame):
    """Um item do checklist: cabeçalho com o resultado e, aberto, as instruções e os botões."""

    def __init__(self, test: str, extra: QWidget | None, action_key: str | None, parent: QWidget | None = None):
        super().__init__(parent)
        self.test = test
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.title = QPushButton()
        self.title.setFlat(True)
        self.title.setStyleSheet("text-align: left; font-weight: bold;")
        i18n.bind(self.title.setText, f"quick.{test}")
        self.badge = QLabel()
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        header.addWidget(self.title, 1)
        header.addWidget(self.badge)
        layout.addLayout(header)

        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(8, 0, 8, 4)
        description = QLabel()
        description.setWordWrap(True)
        i18n.bind(description.setText, f"quick.{test}_desc")
        body.addWidget(description)
        self.note = QLabel()
        self.note.setWordWrap(True)
        body.addWidget(self.note)
        if extra is not None:
            body.addWidget(extra)
        buttons = QHBoxLayout()
        self.pass_button = QPushButton()
        i18n.bind(self.pass_button.setText, "quick.pass")
        self.fail_button = QPushButton()
        i18n.bind(self.fail_button.setText, "quick.fail")
        buttons.addWidget(self.pass_button)
        buttons.addWidget(self.fail_button)
        self.action_button = None
        if action_key:
            self.action_button = QPushButton()
            i18n.bind(self.action_button.setText, action_key)
            buttons.addWidget(self.action_button)
        buttons.addStretch(1)
        body.addLayout(buttons)
        layout.addWidget(self.body)
        self.body.hide()
        self.set_result(None)

    def set_result(self, result: bool | None) -> None:
        key, color = {True: ("quick.passed", PASSED_COLOR), False: ("quick.failed", FAILED_COLOR)}.get(
            result, ("quick.untested", UNTESTED_COLOR)
        )
        self.badge.setText(tr(key))
        self.badge.setStyleSheet(
            f"background: {color}; color: white; border-radius: 4px; padding: 2px 8px; font-weight: bold;"
        )


class QuickTestDialog(QWidget):
    """Aba que roda a sequência sobre o controle aberto pelo painel de teste, que repassa o dispositivo e o estado.

    Só funciona enquanto está visível: sair da aba (ou da página) para a sequência e desliga os efeitos."""

    # ○ com a sequência parada: o diálogo do teste rápido fecha.
    back_requested = Signal()

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._device = None
        self._connection = ""
        self._sequence = sequence.Sequence()
        self._edges = sequence.ButtonEdges()
        self._checks = {test: make() for test, make in sequence.CHECKS.items()}
        self._auto_pass_pending = False
        self._disconnects = 0
        self._active: str | None = None  # item cujos efeitos (vibração, luzes, tom...) estão ligados
        self._script: list = []
        self._script_loop: list = []
        self._script_timer = QTimer(self)
        self._script_timer.timeout.connect(self._script_step)

        root = QVBoxLayout(self)
        self._banner = QLabel()
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet("padding: 8px; border-radius: 4px; background: palette(alternate-base); font-weight: bold;")
        root.addWidget(self._banner)

        self._stick_views = (StickView(), StickView())
        sticks = QWidget()
        sticks_layout = QVBoxLayout(sticks)
        sticks_layout.setContentsMargins(0, 0, 0, 0)
        views = QHBoxLayout()
        for view in self._stick_views:
            view.setMinimumHeight(140)
            views.addWidget(view)
        sticks_layout.addLayout(views)
        self._drift = QLabel()
        sticks_layout.addWidget(self._drift)
        self._touchpad = TouchpadView()
        self._touchpad.setMinimumHeight(120)
        self._mic = MicMeter()
        self._jack = QLabel()

        self._views: dict[str, ChecksView] = {}
        extras: dict[str, QWidget] = {"microphone": self._mic, "headphone": self._jack}
        for test, check in self._checks.items():
            translate = test != "buttons"
            view = ChecksView(check.names, 7 if test == "buttons" else 3, translate)
            self._views[test] = view
            holder = QWidget()
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            if test == "sticks":
                holder_layout.addWidget(sticks)
            elif test == "trackpad":
                holder_layout.addWidget(self._touchpad)
            holder_layout.addWidget(view)
            extras[test] = holder
        actions = {
            "haptic": "quick.repeat", "lights": "quick.repeat", "speaker": "quick.repeat",
            "headphone": "quick.play_headphone", "buttons": "quick.restart", "sticks": "quick.restart",
            "trackpad": "quick.restart", "imu": "quick.restart",
        }

        self._rows: dict[str, ItemRow] = {}
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        for test in sequence.TESTS:
            row = ItemRow(test, extras.get(test), actions.get(test))
            row.title.clicked.connect(lambda _c=False, t=test: self._go(lambda: self._sequence.open(t)))
            row.pass_button.clicked.connect(lambda: self._mark(True))
            row.fail_button.clicked.connect(lambda: self._mark(False))
            if row.action_button is not None:
                row.action_button.clicked.connect(lambda _c=False, t=test: self._action(t))
            self._rows[test] = row
            list_layout.addWidget(row)
        list_layout.addStretch(1)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(list_widget)
        root.addWidget(self._scroll, 1)

        bottom = QHBoxLayout()
        self._summary = QLabel()
        bottom.addWidget(self._summary, 1)
        self._start_button = QPushButton()  # o texto ("Começar"/"Recomeçar") vem de _refresh
        self._start_button.clicked.connect(self._start)
        bottom.addWidget(self._start_button)  # fechar fica com o diálogo (botão Fechar e Esc)
        root.addLayout(bottom)

        i18n.hub.changed.connect(self._refresh)
        self._refresh()

    # --- ligação com a janela de teste

    def set_device(self, device) -> None:
        """Troca o controle sem perder o item aberto; os efeitos dele voltam a ligar no novo."""
        if device is self._device:
            return
        self._deactivate()
        self._device = device
        self._connection = getattr(device, "connection", "")
        if device is not None and self.isVisible():
            self._activate(fresh=False)
        self._refresh()

    def note_disconnect(self) -> None:
        """A leitura do controle falhou (cabo mexido, controle desligado): conta para o teste do conector."""
        if self.isVisible():
            self._disconnects += 1
            self._refresh()

    def on_state(self, state: InputState) -> None:
        if not self.isVisible():
            return
        self._connection = state.connection
        current = self._sequence.current
        check = self._checks.get(current)
        if check is not None:
            check.update(state)
            self._views[current].update_checks(check.checks)
            if check.done and self._sequence.results[current] is None and not self._auto_pass_pending:
                self._auto_pass_pending = True
                QTimer.singleShot(AUTO_PASS_MS, lambda t=current: self._auto_pass(t))
        if current == "sticks":
            self._stick_views[0].set_position(state.lx, state.ly)
            self._stick_views[1].set_position(state.rx, state.ry)
            drift = self._checks["sticks"].drift
            self._drift.setText(tr("quick.drift", drift=f"{drift:.1f}") if drift is not None else "")
        elif current == "trackpad":
            self._touchpad.set_touches(state.touches)
        elif current == "headphone":
            self._jack.setText(tr("quick.jack", state=tr("quick.yes" if state.headphones else "quick.no")))
        elif current == "usb":
            self._show_usb_note()
        self._navigate(state)

    def _navigate(self, state: InputState) -> None:
        """□ começa/passou, ✕ falhou, △ volta, ○ pula ou fecha; no teste de botões só o ○ longo pula."""
        pressed, long_press = self._edges.update(state, time.monotonic())
        current = self._sequence.current
        if current == "buttons":
            if long_press:
                self._skip()
            return
        if "square" in pressed:
            self._start() if current is None else self._mark(True)
        elif "cross" in pressed and current is not None:
            self._mark(False)
        elif "triangle" in pressed:
            self._go(self._sequence.previous)
        elif "circle" in pressed:
            if current is None:
                self.back_requested.emit()
            else:
                self._skip()

    # --- navegação

    def _start(self) -> None:
        log_action("teste rápido", selected_controller(self._service), value="iniciado")
        self._go(self._sequence.start)

    def _mark(self, passed: bool) -> None:
        """Dá o resultado ao item aberto (passou/falhou) e segue; só registra se havia item aberto."""
        current = self._sequence.current
        if current is not None:
            log_action(f"teste rápido: {current}", selected_controller(self._service), value="passou" if passed else "falhou")
        self._go(lambda: self._sequence.mark(passed))
        if current is not None and self._sequence.finished:
            done, failed, _ = self._sequence.summary()
            log_action("teste rápido", selected_controller(self._service), value="concluído", passou=done, falhou=failed)

    def _skip(self) -> None:
        current = self._sequence.current
        if current is not None:
            log_action(f"teste rápido: {current}", selected_controller(self._service), value="pulado")
        self._go(self._sequence.skip)

    def _go(self, change) -> None:
        """Aplica uma mudança na sequência e, se o item aberto mudou, troca os efeitos ligados."""
        before = self._sequence.current
        change()
        if self._sequence.current != before or self._active != self._sequence.current:
            self._deactivate()
            self._activate(fresh=True)
        self._refresh()

    def _auto_pass(self, test: str) -> None:
        self._auto_pass_pending = False
        check = self._checks[test]
        if self._sequence.current == test and check.done and self._sequence.results[test] is None:
            self._mark(True)

    def _activate(self, fresh: bool) -> None:
        """Liga os efeitos do item aberto; `fresh` (item recém-aberto) também zera as verificações."""
        test = self._sequence.current
        self._active = test
        self._auto_pass_pending = False
        if test is None:
            return
        if fresh:
            self._disconnects = 0
            if test in self._checks:
                self._action(test)
        if self._device is None:
            return
        if test == "adaptive":
            effect = triggers.resistance(0, triggers.MAX_STRENGTH)
            self._send(left_trigger=effect, right_trigger=effect)
        elif test in ("haptic", "lights", "speaker"):
            self._action(test)
        elif test == "microphone":
            self._mic.start()

    def _deactivate(self) -> None:
        """Desliga o que o item aberto ligou: gatilhos, vibração, luzes, tom e microfone."""
        test, self._active = self._active, None
        self._script_timer.stop()
        self._script, self._script_loop = [], []
        if test == "adaptive":
            self._send(left_trigger=triggers.OFF, right_trigger=triggers.OFF)
        elif test == "haptic":
            self._send(rumble=(0, 0))
        elif test == "lights":
            restore_leds(self._service)
        elif test in ("speaker", "headphone"):
            self._tone(None)
        elif test == "microphone":
            self._mic.stop()

    # --- efeitos de cada item

    def _action(self, test: str) -> None:
        """Botão extra do item: reinicia as verificações ou repete o efeito."""
        if test in self._checks:
            self._checks[test].reset()
            self._views[test].update_checks(self._checks[test].checks)
            for view in self._stick_views:
                view.reset_range()
        elif test == "haptic":
            self._run_script(HAPTIC_STEP_MS, [
                lambda: self._send(rumble=(255, 0)), lambda: self._send(rumble=(0, 255)), lambda: self._send(rumble=(0, 0)),
            ])
        elif test == "lights":
            controller = selected_controller(self._service)
            if controller is not None:
                self._run_script(LIGHTS_STEP_MS, led_steps(controller), loop=True)
        elif test == "speaker":
            self._run_script(SPEAKER_TONE_MS, [lambda: self._tone("speaker"), lambda: self._tone(None)])
        elif test == "headphone":
            self._run_script(HEADPHONE_TONE_MS, [lambda: self._tone("headphones"), lambda: self._tone(None)])

    def _run_script(self, interval: int, steps: list, loop: bool = False) -> None:
        """Executa um passo agora e os demais a cada `interval` ms (repetindo tudo, se `loop`)."""
        self._script = list(steps)
        self._script_loop = list(steps) if loop else []
        self._script_timer.setInterval(interval)
        self._script_timer.start()
        self._script_step()

    def _script_step(self) -> None:
        if not self._script and self._script_loop:
            self._script = list(self._script_loop)
        if not self._script:
            self._script_timer.stop()
            return
        try:
            self._script.pop(0)()
        except OSError as error:
            log.warning("Falha no teste rápido: %s", error)
            self._script_timer.stop()
            self._script, self._script_loop = [], []

    def _send(self, **fields) -> None:
        if self._device is None:
            return
        try:
            self._device.send_output(**fields)
        except OSError as error:
            log.warning("Falha ao enviar saída no teste rápido: %s", error)

    def _tone(self, output: str | None) -> None:
        """Liga o tom em `output` ou desliga (None); só por USB."""
        if self._device is None or self._connection != "USB":
            return
        try:
            if output is None:
                audio.stop_tone(self._device)
            else:
                audio.play_tone(self._device, output)
        except OSError as error:
            log.warning("Falha no tom de teste: %s", error)

    # --- tela

    def _show_usb_note(self) -> None:
        self._rows["usb"].note.setText(
            tr("quick.usb_state", connection=self._connection or "—", count=self._disconnects)
        )

    def _refresh(self) -> None:
        current = self._sequence.current
        for test, row in self._rows.items():
            row.set_result(self._sequence.results[test])
            row.body.setVisible(test == current)
            row.title.setStyleSheet(
                "text-align: left; font-weight: bold;" + (" color: palette(highlight);" if test == current else "")
            )
            usb_only = test in sequence.USB_ONLY and self._connection != "USB"
            row.note.setText(tr("quick.usb_only") if usb_only else "")
            if row.action_button is not None and test in sequence.USB_ONLY:
                row.action_button.setEnabled(not usb_only)
        if current == "usb":
            self._show_usb_note()
        if current is not None:
            self._scroll.ensureWidgetVisible(self._rows[current])
        if self._device is None:
            banner = "quick.no_device"
        elif current == "buttons":
            banner = "quick.banner_buttons"
        elif current is not None:
            banner = "quick.banner_running"
        else:
            banner = "quick.banner_idle"
        self._banner.setText(tr(banner))
        passed, failed, untested = self._sequence.summary()
        tested = passed + failed
        self._summary.setText(tr("quick.summary", passed=passed, failed=failed, untested=untested) if tested else "")
        self._start_button.setText(tr("quick.restart_all" if tested else "quick.start"))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh()

    def hideEvent(self, event) -> None:
        self._stop()
        super().hideEvent(event)

    def _stop(self) -> None:
        self._deactivate()
        self._sequence.current = None
        self._refresh()
