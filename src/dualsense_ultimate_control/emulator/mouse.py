"""Giroscópio e touchpad como mouse: só conta, sem dispositivo, como `mapping.py`.

O `Bridge` lê os relatórios do hidraw do controle (o grab do evdev não os bloqueia e eles trazem o
giroscópio bruto, onde vale a correção da E4) e passa cada um a `MouseTracker.update`, que devolve o
movimento, a rolagem e os cliques do mouse virtual. Também acha no sysfs os nós irmãos do gamepad
(hidraw e o evdev do touchpad), que o hid-playstation cria sob o mesmo dispositivo HID.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..ds5.imu import ImuCalibration, apply_offset, to_dps
from ..ds5.reports import TOUCHPAD_WIDTH, InputState as Report
from .mapping import Profile

# sensor_time conta em unidades de 1/3 µs (hid-playstation).
SENSOR_TICKS_PER_SECOND = 3_000_000
SENSOR_TIME_WRAP = 1 << 32
MAX_STEP = 0.05  # s; um intervalo maior (relatórios perdidos, controle voltando) não vira um salto
TOUCH_PIXELS = 0.6  # pixels por unidade do touchpad (1920 de largura) com velocidade 1
SCROLL_STEP = 80  # unidades do touchpad por clique da roda


@dataclass(frozen=True)
class MouseOutput:
    dx: int = 0
    dy: int = 0
    wheel: int = 0  # positivo rola para cima
    hwheel: int = 0  # positivo rola para a direita
    buttons: frozenset[str] = frozenset()  # "left", "right"

    @property
    def moves(self) -> bool:
        return bool(self.dx or self.dy or self.wheel or self.hwheel)


def _whole(value: float) -> tuple[int, float]:
    """Parte inteira (em direção ao zero) e o resto, que fica para o próximo relatório."""
    whole = int(value)
    return whole, value - whole


class MouseTracker:
    """Estado entre relatórios: último tempo do sensor, dedos anteriores e as frações acumuladas."""

    def __init__(self, profile: Profile, gyro_offset=None, calibration: ImuCalibration | None = None):
        self.profile = profile
        self.gyro_offset = gyro_offset
        self.calibration = calibration
        self._time: int | None = None
        self._touches: tuple = ()
        self._click: str | None = None  # botão escolhido ao afundar o touchpad, mantido até soltar
        self._x = self._y = 0.0
        self._scroll_x = self._scroll_y = 0.0

    def gyro_active(self, report: Report, pressed: set[str]) -> bool:
        mode = self.profile.gyro
        if mode == "always":
            return True
        if mode == "button":
            return self.profile.gyro_button in pressed
        if mode == "touch":
            return any(report.touches)
        return False

    def update(self, report: Report, pressed: set[str]) -> MouseOutput:
        """`pressed` são os botões do DualSense (`Mapper.sources`), para o ativador do giroscópio."""
        self._gyro(report, pressed)
        wheel = hwheel = 0
        touches = tuple(touch for touch in report.touches if touch is not None)
        if self.profile.touchpad == "mouse":
            wheel, hwheel = self._touchpad(touches)
            buttons = self._buttons(report, touches)
        else:
            buttons = frozenset()
        self._touches = touches
        dx, self._x = _whole(self._x)
        dy, self._y = _whole(self._y)
        return MouseOutput(dx, dy, wheel, hwheel, buttons)

    def _gyro(self, report: Report, pressed: set[str]) -> None:
        previous, self._time = self._time, report.sensor_time
        if previous is None:
            return
        ticks = (report.sensor_time - previous) % SENSOR_TIME_WRAP
        if not ticks or not self.gyro_active(report, pressed):
            return
        step = min(ticks / SENSOR_TICKS_PER_SECOND, MAX_STEP)
        pitch, yaw, _roll = to_dps(apply_offset(report.gyro, self.gyro_offset), self.calibration)
        speed = self.profile.gyro_speed * step
        # Virar o controle para a esquerda (yaw positivo) leva o cursor para a esquerda; erguer a
        # frente (pitch positivo) o leva para cima, que no mouse é y negativo.
        self._x -= yaw * speed
        self._y += (pitch if self.profile.gyro_invert_y else -pitch) * speed

    def _touchpad(self, touches: tuple) -> tuple[int, int]:
        previous = self._touches
        same_fingers = len(touches) == len(previous) and all(a.id == b.id for a, b in zip(touches, previous))
        if not same_fingers or not touches:
            self._scroll_x = self._scroll_y = 0.0
            return 0, 0
        dx = sum(a.x - b.x for a, b in zip(touches, previous)) / len(touches)
        dy = sum(a.y - b.y for a, b in zip(touches, previous)) / len(touches)
        if len(touches) == 1:
            # Com o giroscópio ativado pelo toque, o dedo é a embreagem da mira, não o ponteiro.
            if self.profile.gyro != "touch":
                factor = TOUCH_PIXELS * self.profile.touchpad_speed
                self._x += dx * factor
                self._y += dy * factor
            return 0, 0
        self._scroll_x += dx * self.profile.touchpad_speed
        self._scroll_y -= dy * self.profile.touchpad_speed  # dedos subindo rolam para cima
        wheel, rest_y = _whole(self._scroll_y / SCROLL_STEP)
        hwheel, rest_x = _whole(self._scroll_x / SCROLL_STEP)
        self._scroll_y, self._scroll_x = rest_y * SCROLL_STEP, rest_x * SCROLL_STEP
        return wheel, hwheel

    def _buttons(self, report: Report, touches: tuple) -> frozenset[str]:
        if "touchpad" not in report.buttons:
            self._click = None
            return frozenset()
        if self._click is None:
            # Metade direita (ou dois dedos) é o botão direito.
            right = len(touches) >= 2 or (touches and touches[0].x >= TOUCHPAD_WIDTH // 2)
            self._click = "right" if right else "left"
        return frozenset({self._click})


def sibling_nodes(event_path: str, sys_root: Path = Path("/sys")) -> tuple[str | None, str | None]:
    """(/dev/hidrawN, /dev/input/eventM do touchpad) do mesmo DualSense que o nó do gamepad."""
    hid = sys_root / "class" / "input" / Path(event_path).name / "device" / "device"
    hidraw = touchpad = None
    try:
        hidraw = next((f"/dev/{node.name}" for node in sorted((hid / "hidraw").iterdir())), None)
    except OSError:
        pass
    try:
        inputs = sorted((hid / "input").iterdir())
    except OSError:
        inputs = []
    for node in inputs:
        try:
            if not (node / "name").read_text().strip().endswith("Touchpad"):
                continue
            touchpad = next((f"/dev/input/{e.name}" for e in sorted(node.iterdir()) if e.name.startswith("event")), None)
        except OSError:
            continue
        if touchpad:
            break
    return hidraw, touchpad
