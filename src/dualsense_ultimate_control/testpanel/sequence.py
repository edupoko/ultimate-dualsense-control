"""Teste rápido (sem Qt): ordem dos itens, resultados, navegação pelos botões do controle e as
verificações automáticas de botões, analógicos, touchpad e IMU.

Segue o "Quick test" do dualshock-tools: □ começa / passou, ✕ falhou, △ volta, ○ pula ou fecha.
"""

from __future__ import annotations

import math
from collections import deque

from ..ds5 import calibration
from ..ds5.reports import InputState

TESTS = (
    "usb", "buttons", "sticks", "trackpad", "imu", "adaptive", "haptic", "lights", "speaker", "headphone", "microphone",
)
# O tom de teste usa o relatório de feature 0x80, que só responde por USB.
USB_ONLY = frozenset({"speaker", "headphone"})

NAV_BUTTONS = ("square", "cross", "triangle", "circle")
LONG_PRESS_S = 1.0


class Sequence:
    """Resultado de cada item (None = não testado) e o item aberto."""

    def __init__(self, tests: tuple[str, ...] = TESTS):
        self.tests = tests
        self.results: dict[str, bool | None] = dict.fromkeys(tests)
        self.current: str | None = None

    def start(self) -> None:
        self.results = dict.fromkeys(self.tests)
        self.current = self.tests[0]

    def open(self, test: str) -> None:
        self.current = test

    def mark(self, passed: bool) -> None:
        if self.current is None:
            return
        self.results[self.current] = passed
        self.current = self._next_untested(self.current, include_self=False)

    def skip(self) -> None:
        if self.current is not None:
            self.current = self._next_untested(self.current, include_self=False)

    def previous(self) -> None:
        if self.current is not None:
            index = self.tests.index(self.current)
            self.current = self.tests[max(index - 1, 0)]

    def _next_untested(self, after: str, include_self: bool) -> str | None:
        """Próximo item sem resultado depois de `after`, dando a volta na lista."""
        start = self.tests.index(after)
        for step in range(0 if include_self else 1, len(self.tests)):
            test = self.tests[(start + step) % len(self.tests)]
            if self.results[test] is None:
                return test
        return None

    @property
    def finished(self) -> bool:
        return all(result is not None for result in self.results.values())

    def summary(self) -> tuple[int, int, int]:
        """(passaram, falharam, sem resultado)."""
        values = list(self.results.values())
        return values.count(True), values.count(False), values.count(None)


class ButtonEdges:
    """Botões de navegação recém-apertados e o toque longo em ○ (pular no teste de botões)."""

    def __init__(self):
        self._held: frozenset[str] = frozenset()
        self._circle_since: float | None = None
        self._long_fired = False

    def update(self, state: InputState, now: float) -> tuple[set[str], bool]:
        """(botões que acabaram de descer, ○ completou o toque longo agora)."""
        held = frozenset(b for b in NAV_BUTTONS if b in state.buttons)
        pressed = set(held - self._held)
        self._held = held
        long_press = False
        if "circle" in held:
            if self._circle_since is None:
                self._circle_since, self._long_fired = now, False
            elif not self._long_fired and now - self._circle_since >= LONG_PRESS_S:
                self._long_fired = long_press = True
        else:
            self._circle_since = None
        return pressed, long_press


class Check:
    """Conjunto de verificações automáticas de um item; `checks` vai de nome para feito/não feito."""

    names: tuple[str, ...] = ()

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.checks = dict.fromkeys(self.names, False)

    def update(self, state: InputState) -> None:
        raise NotImplementedError

    @property
    def done(self) -> bool:
        return all(self.checks.values())


_DPAD_PARTS = {
    "up": ("up",), "down": ("down",), "left": ("left",), "right": ("right",),
    "up_right": ("up", "right"), "up_left": ("up", "left"), "down_right": ("down", "right"), "down_left": ("down", "left"),
}


class ButtonsCheck(Check):
    """Cada botão do DualSense comum (sem os extras do Edge) e as 4 direções do direcional."""

    names = (
        "up", "down", "left", "right", "square", "cross", "circle", "triangle",
        "l1", "r1", "l2", "r2", "l3", "r3", "create", "options", "ps", "touchpad", "mute",
    )

    def reset(self) -> None:
        super().reset()
        self._held: frozenset[str] | None = None

    def update(self, state: InputState) -> None:
        # Conta só o que desceu depois de o item abrir: o □ que abriu o item ainda pode estar apertado.
        held = frozenset((*state.buttons, *_DPAD_PARTS.get(state.dpad, ())))
        if self._held is not None:
            for name in held - self._held:
                if name in self.checks:
                    self.checks[name] = True
        self._held = held


class SticksCheck(Check):
    """Alcance dos dois sticks até as bordas e centro estável com eles soltos."""

    names = ("left_range", "right_range", "center")
    RECENT = 30

    def reset(self) -> None:
        super().reset()
        self._left: list[tuple[int, int]] = []
        self._right: list[tuple[int, int]] = []
        self._recent: deque[InputState] = deque(maxlen=self.RECENT)
        self.drift: float | None = None

    def update(self, state: InputState) -> None:
        self._left.append((state.lx, state.ly))
        self._right.append((state.rx, state.ry))
        self._recent.append(state)
        for name, points in (("left_range", self._left), ("right_range", self._right)):
            if not self.checks[name] and calibration.range_complete(calibration.range_extremes(points)):
                self.checks[name] = True
                points.clear()
        reading = calibration.average_center(self._recent)
        self.drift = reading.drift if reading else None
        # Centro: as últimas leituras todas perto de 128 (com o stick solto e sem desvio).
        if len(self._recent) == self.RECENT and all(
            abs(v - calibration.STICK_CENTER) < calibration.DRIFT_NOTICE
            for s in self._recent for v in (s.lx, s.ly, s.rx, s.ry)
        ):
            self.checks["center"] = True


class TrackpadCheck(Check):
    """Arrastar um dedo, tocar com dois e clicar."""

    names = ("move", "two_fingers", "click")
    MOVE_DISTANCE = 600  # em unidades do touchpad (1920 de largura)

    def reset(self) -> None:
        super().reset()
        self._last: tuple[int, int] | None = None
        self._travel = 0.0

    def update(self, state: InputState) -> None:
        first, second = state.touches
        if first is not None and second is not None:
            self.checks["two_fingers"] = True
        finger = first or second
        if finger is None:
            self._last = None
        else:
            if self._last is not None:
                self._travel += math.dist(self._last, (finger.x, finger.y))
            self._last = (finger.x, finger.y)
            if self._travel >= self.MOVE_DISTANCE:
                self.checks["move"] = True
        if "touchpad" in state.buttons:
            self.checks["click"] = True


class ImuCheck(Check):
    """Giro forte nos dois sentidos de cada eixo e a gravidade sentida ao longo de cada eixo do acelerômetro."""

    names = ("pitch", "yaw", "roll", "accel_x", "accel_y", "accel_z")
    GYRO_THRESHOLD = 3000  # bruto; cerca de 180 °/s
    ACCEL_THRESHOLD = 5700  # bruto; cerca de 0,7 g

    def reset(self) -> None:
        super().reset()
        self._signs: dict[str, set[int]] = {name: set() for name in ("pitch", "yaw", "roll")}

    def update(self, state: InputState) -> None:
        for name, value in zip(("pitch", "yaw", "roll"), state.gyro):
            if abs(value) >= self.GYRO_THRESHOLD:
                self._signs[name].add(1 if value > 0 else -1)
                self.checks[name] = len(self._signs[name]) == 2
        for name, value in zip(("accel_x", "accel_y", "accel_z"), state.accel):
            if abs(value) >= self.ACCEL_THRESHOLD:
                self.checks[name] = True


CHECKS = {"buttons": ButtonsCheck, "sticks": SticksCheck, "trackpad": TrackpadCheck, "imu": ImuCheck}
