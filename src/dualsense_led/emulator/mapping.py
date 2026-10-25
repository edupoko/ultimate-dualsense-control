"""Perfis de remapeamento do emulador: só conta, sem dispositivo, para testar sem o controle.

O `Bridge` junta o estado do DualSense num `InputState` (botões por posição física, analógicos
de -1 a 1, gatilhos de 0 a 1); `Mapper.apply` aplica o perfil e devolve o que o Xbox 360 virtual
(e o teclado virtual) deve mostrar. O perfil padrão não altera nada.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

# Botões do DualSense pela posição física (o driver os chama de "cardinais", ver core.BUTTON_MAP).
BUTTON_SOURCES = (
    "south", "east", "west", "north", "l1", "r1", "l2", "r2",
    "select", "start", "mode", "l3", "r3",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
)  # fmt: skip
# Destinos no Xbox 360 virtual; "lt"/"rt" empurram o gatilho até o fim.
XBOX_TARGETS = (
    "a", "b", "x", "y", "lb", "rb", "back", "start", "guide", "ls", "rs",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right", "lt", "rt",
)  # fmt: skip
NO_TARGET = "none"
KEY_PREFIX = "key:"

# O que cada botão faz sem perfil: o Xbox na mesma posição. L2/R2 só valem pelo eixo analógico.
DEFAULT_REMAP = {
    "south": "a", "east": "b", "west": "x", "north": "y",
    "l1": "lb", "r1": "rb", "select": "back", "start": "start", "mode": "guide",
    "l3": "ls", "r3": "rs",
    "dpad_up": "dpad_up", "dpad_down": "dpad_down", "dpad_left": "dpad_left", "dpad_right": "dpad_right",
}  # fmt: skip

STICKS = ("left", "right")
STICK_AXES = ("left_x", "left_y", "right_x", "right_y")
TRIGGERS = ("l2", "r2")
TRIGGER_MODES = ("analog", "digital", "off")
STICK_MAX, STICK_MIN = 32767, -32768
TRIGGER_MAX = 255
MAX_DEADZONE = 0.9
CURVE_RANGE = (0.3, 3.0)
DEFAULT_THRESHOLD = 0.5
# Touchpad: "system" deixa o nó com o sistema (o libinput já o usa como touchpad), "mouse" o assume
# como ponteiro/rolagem/clique do mouse virtual e "off" só o esconde.
TOUCHPAD_MODES = ("system", "mouse", "off")
# Giroscópio como mira do mouse: desligado, sempre, enquanto segura `gyro_button` ou com dedo no touchpad.
GYRO_MODES = ("off", "always", "button", "touch")
TOUCHPAD_SPEED_RANGE = (0.1, 5.0)
GYRO_SPEED_RANGE = (1.0, 100.0)  # pixels por grau
DEFAULT_GYRO_SPEED = 15.0

_KEY_NAME = re.compile(r"KEY_[A-Z0-9_]+")
_APP_ID = re.compile(r"AppId=(\d+)")


def valid_target(target: str) -> bool:
    if target == NO_TARGET or target in XBOX_TARGETS:
        return True
    return target.startswith(KEY_PREFIX) and bool(_KEY_NAME.fullmatch(target[len(KEY_PREFIX) :]))


@dataclass
class Profile:
    """Um conjunto de ajustes; `name` vazio é o perfil sem alterações."""

    name: str = ""
    # Botão (BUTTON_SOURCES) -> destino (XBOX_TARGETS, "none" ou "key:KEY_X"); o que falta segue o padrão.
    remap: dict[str, str] = field(default_factory=dict)
    swap_sticks: bool = False
    invert: list[str] = field(default_factory=list)  # entre STICK_AXES
    deadzone: dict[str, float] = field(default_factory=lambda: {"left": 0.0, "right": 0.0})
    # Expoente da resposta: 1 é linear, acima de 1 suaviza perto do centro, abaixo de 1 acelera.
    curve: dict[str, float] = field(default_factory=lambda: {"left": 1.0, "right": 1.0})
    triggers: dict[str, str] = field(default_factory=lambda: {"l2": "analog", "r2": "analog"})
    trigger_threshold: float = DEFAULT_THRESHOLD
    # Processos (nome do executável) e AppIDs da Steam que ativam este perfil.
    apps: list[str] = field(default_factory=list)
    steam_appids: list[int] = field(default_factory=list)
    touchpad: str = "system"
    touchpad_speed: float = 1.0
    gyro: str = "off"
    gyro_button: str = "l2"  # entre BUTTON_SOURCES, para gyro == "button"
    gyro_speed: float = DEFAULT_GYRO_SPEED
    gyro_invert_y: bool = False

    @property
    def uses_mouse(self) -> bool:
        """O perfil precisa dos relatórios do hidraw (touchpad como mouse ou giroscópio ligado)."""
        return self.touchpad == "mouse" or self.gyro != "off"

    @classmethod
    def from_dict(cls, data) -> Profile:
        """Lê um perfil descartando o que for inválido, para um arquivo editado à mão não derrubar o daemon."""
        if not isinstance(data, dict):
            raise ValueError("perfil inválido")
        profile = cls(name=str(data.get("name", "")).strip())
        remap = data.get("remap", {})
        if isinstance(remap, dict):
            profile.remap = {
                str(source): str(target)
                for source, target in remap.items()
                if source in BUTTON_SOURCES and valid_target(str(target))
            }
        profile.swap_sticks = bool(data.get("swap_sticks", False))
        invert = data.get("invert", [])
        profile.invert = [axis for axis in STICK_AXES if isinstance(invert, list) and axis in invert]
        for key, field_name, low, high in (
            ("deadzone", "deadzone", 0.0, MAX_DEADZONE),
            ("curve", "curve", *CURVE_RANGE),
        ):
            values = data.get(key, {})
            for stick in STICKS:
                try:
                    number = float(values[stick])
                except (KeyError, TypeError, ValueError):
                    continue
                if math.isfinite(number):
                    getattr(profile, field_name)[stick] = max(low, min(high, number))
        modes = data.get("triggers", {})
        for trigger in TRIGGERS:
            if isinstance(modes, dict) and modes.get(trigger) in TRIGGER_MODES:
                profile.triggers[trigger] = modes[trigger]
        try:
            threshold = float(data.get("trigger_threshold", DEFAULT_THRESHOLD))
            if math.isfinite(threshold):
                profile.trigger_threshold = max(0.05, min(0.95, threshold))
        except (TypeError, ValueError):
            pass
        if data.get("touchpad") in TOUCHPAD_MODES:
            profile.touchpad = data["touchpad"]
        if data.get("gyro") in GYRO_MODES:
            profile.gyro = data["gyro"]
        if data.get("gyro_button") in BUTTON_SOURCES:
            profile.gyro_button = data["gyro_button"]
        profile.gyro_invert_y = bool(data.get("gyro_invert_y", False))
        for key, (low, high) in (("touchpad_speed", TOUCHPAD_SPEED_RANGE), ("gyro_speed", GYRO_SPEED_RANGE)):
            try:
                number = float(data.get(key, getattr(profile, key)))
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                setattr(profile, key, max(low, min(high, number)))
        apps = data.get("apps", [])
        profile.apps = [str(app).strip() for app in apps if str(app).strip()] if isinstance(apps, list) else []
        appids = data.get("steam_appids", [])
        profile.steam_appids = []
        for value in appids if isinstance(appids, list) else []:
            try:
                profile.steam_appids.append(int(value))
            except (TypeError, ValueError):
                continue
        return profile

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "remap": dict(self.remap),
            "swap_sticks": self.swap_sticks,
            "invert": list(self.invert),
            "deadzone": dict(self.deadzone),
            "curve": dict(self.curve),
            "triggers": dict(self.triggers),
            "trigger_threshold": self.trigger_threshold,
            "apps": list(self.apps),
            "steam_appids": list(self.steam_appids),
            "touchpad": self.touchpad,
            "touchpad_speed": self.touchpad_speed,
            "gyro": self.gyro,
            "gyro_button": self.gyro_button,
            "gyro_speed": self.gyro_speed,
            "gyro_invert_y": self.gyro_invert_y,
        }

    def copy(self) -> Profile:
        return Profile.from_dict(self.to_dict())

    def matches(self, processes: list[ProcessInfo]) -> bool:
        """Algum processo em execução é um dos aplicativos deste perfil (ou tem um dos AppIDs)."""
        wanted = {app.lower() for app in self.apps}
        for process in processes:
            if wanted & process.names:
                return True
            if process.app_id is not None and process.app_id in self.steam_appids:
                return True
        return False


@dataclass(frozen=True)
class ProcessInfo:
    """O que identifica um processo: nome (comm) e nome-base de cada argumento, em minúsculas."""

    names: frozenset[str]
    app_id: int | None = None

    @classmethod
    def from_proc(cls, comm: str, cmdline: bytes) -> ProcessInfo:
        arguments = [part.decode(errors="replace") for part in cmdline.split(b"\0") if part]
        names = {comm.strip().lower()}
        for argument in arguments:
            names.add(re.split(r"[\\/]", argument)[-1].lower())  # caminhos do Linux e do Windows (Proton)
        found = _APP_ID.search(" ".join(arguments))
        return cls(frozenset(names - {""}), int(found.group(1)) if found else None)


def running_processes(proc: Path = Path("/proc")) -> list[ProcessInfo]:
    processes = []
    try:
        entries = list(proc.iterdir())
    except OSError:
        return processes
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            processes.append(ProcessInfo.from_proc((entry / "comm").read_text(), (entry / "cmdline").read_bytes()))
        except OSError:
            continue  # o processo terminou no meio da leitura
    return processes


def pick_profile(profiles: list[Profile], processes: list[ProcessInfo], default: Profile) -> Profile:
    """O primeiro perfil (em ordem) cujo aplicativo está rodando; senão o padrão."""
    for profile in profiles:
        if (profile.apps or profile.steam_appids) and profile.matches(processes):
            return profile
    return default


@dataclass
class InputState:
    """O DualSense já reduzido ao que o mapeador usa."""

    pressed: set[str] = field(default_factory=set)  # entre BUTTON_SOURCES (sem l2/r2, que vêm do gatilho)
    axes: dict[str, float] = field(default_factory=lambda: dict.fromkeys((*STICK_AXES, *TRIGGERS), 0.0))


@dataclass(frozen=True)
class Output:
    """O que o Xbox virtual (e o teclado virtual) devem mostrar."""

    buttons: frozenset[str] = frozenset()  # entre XBOX_TARGETS que são botões
    keys: frozenset[str] = frozenset()  # KEY_*
    # left_x, left_y, right_x, right_y (-32768..32767), lt, rt (0..255), hat_x, hat_y (-1..1)
    axes: tuple[tuple[str, int], ...] = ()


def shape_stick(x: float, y: float, deadzone: float, curve: float) -> tuple[float, float]:
    """Zona morta radial e curva de resposta; sem ajuste devolve a entrada intacta."""
    if deadzone <= 0 and curve == 1.0:
        return x, y
    magnitude = math.hypot(x, y)
    if magnitude <= deadzone or magnitude == 0:
        return 0.0, 0.0
    scaled = min(1.0, (magnitude - deadzone) / (1.0 - deadzone))
    factor = scaled**curve / magnitude
    return x * factor, y * factor


def _stick_int(value: float) -> int:
    value = max(-1.0, min(1.0, value))
    return round(value * STICK_MAX) if value >= 0 else round(value * -STICK_MIN)


class Mapper:
    def __init__(self, profile: Profile | None = None):
        self.profile = profile or Profile()
        remap = {**DEFAULT_REMAP, **self.profile.remap}
        self._remap = {source: target for source, target in remap.items() if target != NO_TARGET}

    def sources(self, state: InputState) -> set[str]:
        """Botões do DualSense apertados, com L2/R2 contando a partir do limiar do perfil."""
        pressed = set(state.pressed)
        for trigger in TRIGGERS:
            if state.axes[trigger] >= self.profile.trigger_threshold:
                pressed.add(trigger)
        return pressed

    def apply(self, state: InputState) -> Output:
        profile = self.profile
        axes = state.axes
        left = (axes["left_x"], axes["left_y"])
        right = (axes["right_x"], axes["right_y"])
        if profile.swap_sticks:
            left, right = right, left
        sticks = {}
        for stick, (x, y) in zip(STICKS, (left, right)):
            x, y = shape_stick(x, y, profile.deadzone[stick], profile.curve[stick])
            sticks[f"{stick}_x"], sticks[f"{stick}_y"] = x, y
        for axis in profile.invert:
            sticks[axis] = -sticks[axis]

        threshold = profile.trigger_threshold
        triggers = {}
        pressed = self.sources(state)
        for trigger in TRIGGERS:
            value = axes[trigger]
            mode = profile.triggers[trigger]
            triggers[trigger] = value if mode == "analog" else (1.0 if mode == "digital" and value >= threshold else 0.0)

        buttons, keys = set(), set()
        for source in pressed:
            target = self._remap.get(source)
            if target is None:
                continue
            if target.startswith(KEY_PREFIX):
                keys.add(target[len(KEY_PREFIX) :])
            elif target in ("lt", "rt"):
                triggers["l2" if target == "lt" else "r2"] = 1.0
            else:
                buttons.add(target)
        hat_x = int("dpad_right" in buttons) - int("dpad_left" in buttons)
        hat_y = int("dpad_down" in buttons) - int("dpad_up" in buttons)
        buttons -= {"dpad_up", "dpad_down", "dpad_left", "dpad_right"}
        return Output(
            frozenset(buttons),
            frozenset(keys),
            (
                *((name, _stick_int(value)) for name, value in sticks.items()),
                ("lt", round(triggers["l2"] * TRIGGER_MAX)),
                ("rt", round(triggers["r2"] * TRIGGER_MAX)),
                ("hat_x", hat_x),
                ("hat_y", hat_y),
            ),
        )


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "perfil"


class ProfileStore:
    """Perfis como arquivos JSON numa pasta (um por perfil), editáveis à mão e fáceis de compartilhar."""

    def __init__(self, directory: Path):
        self.directory = directory

    def load_all(self) -> list[Profile]:
        """Perfis em ordem alfabética do nome; arquivos ilegíveis são ignorados."""
        profiles = []
        try:
            files = sorted(self.directory.glob("*.json"))
        except OSError:
            return profiles
        for path in files:
            try:
                profile = Profile.from_dict(json.loads(path.read_text()))
            except (OSError, ValueError):
                continue
            if profile.name:
                profiles.append(profile)
        return sorted(profiles, key=lambda profile: profile.name.lower())

    def get(self, name: str) -> Profile | None:
        return next((profile for profile in self.load_all() if profile.name == name), None)

    def signature(self) -> tuple:
        """Muda quando algum perfil é criado, alterado ou removido (para o daemon recarregar)."""
        try:
            return tuple((path.name, path.stat().st_mtime_ns) for path in sorted(self.directory.glob("*.json")))
        except OSError:
            return ()

    def save(self, profile: Profile, previous_name: str | None = None) -> None:
        """Grava o perfil; com `previous_name` diferente do atual, renomeia (remove o arquivo antigo)."""
        if not profile.name:
            raise ValueError("o perfil precisa de um nome")
        self.directory.mkdir(parents=True, exist_ok=True)
        if previous_name and previous_name != profile.name:
            self.delete(previous_name)
        self._path_for(profile.name).write_text(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False))

    def delete(self, name: str) -> None:
        self._path_for(name).unlink(missing_ok=True)

    def import_file(self, path: Path) -> Profile:
        profile = Profile.from_dict(json.loads(path.read_text()))
        if not profile.name:
            profile.name = path.stem
        self.save(profile)
        return profile

    def export_file(self, profile: Profile, path: Path) -> None:
        path.write_text(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False))

    def _path_for(self, name: str) -> Path:
        return self.directory / f"{slug(name)}.json"
