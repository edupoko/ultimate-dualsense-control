"""Núcleo do emulador: traduz os eventos do DualSense (hid-playstation) para um Xbox 360 virtual.

A conta (`scale_stick`, `mapping.Mapper`) é separada do dispositivo, para dar para testar sem o
controle. `Bridge` liga um DualSense real a um gamepad virtual criado por uinput; `Emulator`
cuida de achar os controles, reconectar e encerrar limpo.
"""

from __future__ import annotations

import asyncio
import errno
import logging
from dataclasses import dataclass, field

from evdev import AbsInfo, InputDevice, InputEvent, UInput, ecodes, list_devices
from evdev.uinput import UInputError

from ..ds5 import imu
from ..ds5.device import DualSenseDevice
from .config import Config
from .mapping import BUTTON_SOURCES, XBOX_TARGETS, InputState, Mapper, Output
from .mouse import MouseOutput, MouseTracker, sibling_nodes

log = logging.getLogger(__name__)

SONY_VENDOR = 0x054C
DUALSENSE_PRODUCTS = (0x0CE6, 0x0DF2)  # DualSense e DualSense Edge

# Identidade do Xbox 360 com fio, que o SDL, o XInput do Proton e o xpad reconhecem.
X360_NAME = "Microsoft X-Box 360 pad"
X360_VENDOR, X360_PRODUCT, X360_VERSION = 0x045E, 0x028E, 0x0110

STICK_MIN, STICK_MAX = -32768, 32767
_STICK_ABS = (ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_RX, ecodes.ABS_RY)
_TRIGGER_ABS = (ecodes.ABS_Z, ecodes.ABS_RZ)
_HAT_ABS = (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y)

# Botões pela posição física. O driver usa os nomes "cardinais" do evdev (BTN_WEST = quadrado,
# BTN_NORTH = triângulo), que no código numérico são BTN_Y e BTN_X do Xbox: sem trocar, quadrado
# viraria Y e triângulo X. L2/R2 entram pelo eixo analógico (ver `Mapper`), não por BTN_TL2/TR2.
SOURCE_BUTTONS = {
    ecodes.BTN_SOUTH: "south",
    ecodes.BTN_EAST: "east",
    ecodes.BTN_WEST: "west",
    ecodes.BTN_NORTH: "north",
    ecodes.BTN_TL: "l1",
    ecodes.BTN_TR: "r1",
    ecodes.BTN_SELECT: "select",
    ecodes.BTN_START: "start",
    ecodes.BTN_MODE: "mode",
    ecodes.BTN_THUMBL: "l3",
    ecodes.BTN_THUMBR: "r3",
}
# Eixo do DualSense -> entrada do mapeador.
SOURCE_AXES = {
    ecodes.ABS_X: "left_x",
    ecodes.ABS_Y: "left_y",
    ecodes.ABS_RX: "right_x",
    ecodes.ABS_RY: "right_y",
    ecodes.ABS_Z: "l2",
    ecodes.ABS_RZ: "r2",
}
# Botão do Xbox virtual por destino do perfil.
XBOX_BUTTONS = {
    "a": ecodes.BTN_A,
    "b": ecodes.BTN_B,
    "x": ecodes.BTN_X,
    "y": ecodes.BTN_Y,
    "lb": ecodes.BTN_TL,
    "rb": ecodes.BTN_TR,
    "back": ecodes.BTN_SELECT,
    "start": ecodes.BTN_START,
    "guide": ecodes.BTN_MODE,
    "ls": ecodes.BTN_THUMBL,
    "rs": ecodes.BTN_THUMBR,
}
XBOX_AXES = {
    "left_x": ecodes.ABS_X,
    "left_y": ecodes.ABS_Y,
    "right_x": ecodes.ABS_RX,
    "right_y": ecodes.ABS_RY,
    "lt": ecodes.ABS_Z,
    "rt": ecodes.ABS_RZ,
    "hat_x": ecodes.ABS_HAT0X,
    "hat_y": ecodes.ABS_HAT0Y,
}
KEYBOARD_NAME = "DualSense Ultimate Control keyboard"
KEYBOARD_KEYS = sorted({code for name, code in ecodes.ecodes.items() if name.startswith("KEY_") and code < 0x100})
MOUSE_NAME = "DualSense Ultimate Control mouse"
MOUSE_BUTTONS = {"left": ecodes.BTN_LEFT, "right": ecodes.BTN_RIGHT}


def mouse_capabilities() -> dict:
    return {
        ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE],
        ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL, ecodes.REL_HWHEEL],
    }


def x360_capabilities() -> dict:
    """Eventos que o gamepad virtual anuncia (mesmos eixos e botões do xpad)."""
    stick = AbsInfo(0, STICK_MIN, STICK_MAX, 16, 128, 0)
    trigger = AbsInfo(0, 0, 255, 0, 0, 0)
    hat = AbsInfo(0, -1, 1, 0, 0, 0)
    return {
        ecodes.EV_KEY: sorted(XBOX_BUTTONS.values()),
        ecodes.EV_ABS: [(code, stick) for code in _STICK_ABS]
        + [(code, trigger) for code in _TRIGGER_ABS]
        + [(code, hat) for code in _HAT_ABS],
        ecodes.EV_FF: [ecodes.FF_RUMBLE],
    }


def scale_stick(value: int) -> int:
    """Eixo do analógico do DualSense (0–255, centro 128) para o do Xbox (−32768–32767, centro 0)."""
    value = max(0, min(255, value))
    if value == 127:
        return 0  # o repouso oscila entre 127 e 128; sem isso cada piscada vira um salto de 256 no eixo virtual
    if value >= 128:
        return (value - 128) * STICK_MAX // 127
    return (value - 128) * -STICK_MIN // 128


def stick_unit(value: int) -> float:
    """Eixo do analógico do DualSense (0–255) em -1..1, com o mesmo centro de `scale_stick`."""
    scaled = scale_stick(value)
    return scaled / STICK_MAX if scaled >= 0 else scaled / -STICK_MIN


def is_gamepad(device: InputDevice) -> bool:
    """O nó de gamepad de um DualSense (não os de sensores de movimento, touchpad ou fone)."""
    info = device.info
    if info.vendor != SONY_VENDOR or info.product not in DUALSENSE_PRODUCTS:
        return False
    capabilities = device.capabilities()
    return ecodes.EV_ABS in capabilities and ecodes.EV_KEY in capabilities and ecodes.BTN_SOUTH in capabilities[ecodes.EV_KEY]


@dataclass
class Bridge:
    """Um DualSense real (exclusivo, via grab) ligado a um Xbox 360 virtual."""

    physical: InputDevice
    virtual: UInput
    mapper: Mapper = field(default_factory=Mapper)
    _effects: dict[int, int] = field(default_factory=dict)  # id do efeito no virtual -> id no físico
    _state: InputState = field(default_factory=InputState)
    _sent: Output | None = None  # o que o virtual mostra agora
    _keyboard: UInput | None = None  # criado só quando um perfil manda uma tecla
    _keyboard_failed: bool = False
    # Giroscópio e touchpad como mouse (ver `mouse.py`): nós irmãos do mesmo controle.
    gyro_offset: tuple[float, float, float] | None = None
    hidraw_path: str | None = None
    touchpad_path: str | None = None
    _reports: DualSenseDevice | None = None  # hidraw aberto enquanto o perfil usa o mouse
    _calibration: imu.ImuCalibration | None = None
    _tracker: MouseTracker | None = None
    _touchpad: InputDevice | None = None  # nó do touchpad sob grab (fora do libinput)
    _mouse: UInput | None = None
    _mouse_failed: bool = False
    _mouse_buttons: frozenset[str] = frozenset()

    @classmethod
    def open(cls, path: str, mapper: Mapper | None = None, gyro_offset=None) -> Bridge:
        physical = InputDevice(path)
        try:
            physical.grab()  # some para os outros programas; só o virtual fica visível
            virtual = UInput(
                x360_capabilities(),
                name=X360_NAME,
                vendor=X360_VENDOR,
                product=X360_PRODUCT,
                version=X360_VERSION,
                bustype=ecodes.BUS_USB,
                phys=f"dualsense-led/{physical.uniq or physical.path}",  # distingue os virtuais entre si
            )
        except BaseException:
            physical.close()
            raise
        bridge = cls(physical, virtual, mapper or Mapper(), gyro_offset=gyro_offset)
        bridge.hidraw_path, bridge.touchpad_path = sibling_nodes(path)
        bridge.sync()
        bridge.configure_mouse()
        return bridge

    @property
    def name(self) -> str:
        return f"{self.physical.name} ({self.physical.uniq or self.physical.path})"

    def sync(self) -> None:
        """Copia o estado atual do físico (início, ou depois de eventos perdidos pelo SYN_DROPPED)."""
        state = InputState()
        pressed = set(self.physical.active_keys())
        state.pressed = {name for code, name in SOURCE_BUTTONS.items() if code in pressed}
        for code, info in self.physical.capabilities().get(ecodes.EV_ABS, []):
            self._read_axis(state, code, info.value)
        self._state = state
        self._emit(force=True)

    def set_mapper(self, mapper: Mapper) -> None:
        """Troca o perfil na hora; teclas e botões que deixam de valer são soltos."""
        self.mapper = mapper
        self._emit()
        self.configure_mouse()

    # --- giroscópio e touchpad como mouse

    def configure_mouse(self) -> None:
        """Abre ou fecha o hidraw e o grab do touchpad conforme o perfil atual (e zera o rastreio)."""
        profile = self.mapper.profile
        if profile.uses_mouse and self.hidraw_path:
            self._open_reports()
        else:
            self._close_reports()
        self._tracker = MouseTracker(profile, self.gyro_offset, self._calibration) if self._reports else None
        if profile.touchpad != "system" and self.touchpad_path:
            self._grab_touchpad()
        else:
            self._release_touchpad()
        if self._tracker is None or profile.touchpad != "mouse":
            self._emit_mouse(MouseOutput())  # solta um clique que estivesse apertado

    def _open_reports(self) -> None:
        if self._reports is not None:
            return
        try:
            self._reports = DualSenseDevice(self.hidraw_path, "")  # só leitura e relatórios de feature
        except OSError as error:
            log.warning("Sem giroscópio/touchpad para %s: %s", self.name, error)
            self.hidraw_path = None  # não insiste a cada troca de perfil
            return
        if self._calibration is None:
            self._calibration = imu.read_calibration(self._reports)
        try:
            asyncio.get_running_loop().add_reader(self._reports.fileno(), self._read_reports)
        except RuntimeError:
            pass  # sem loop (testes): quem chama entrega os relatórios por `feed_report`

    def _close_reports(self) -> None:
        if self._reports is None:
            return
        try:
            asyncio.get_running_loop().remove_reader(self._reports.fileno())
        except RuntimeError:
            pass
        self._reports.close()
        self._reports = None

    def _read_reports(self) -> None:
        try:
            report = self._reports.read_state()
        except OSError as error:
            if error.errno != errno.ENODEV:
                log.warning("Erro lendo o hidraw de %s: %s", self.name, error)
            self._close_reports()
            self._tracker = None
            return
        if report is not None:
            self.feed_report(report)

    def feed_report(self, report) -> None:
        """Um relatório do hidraw (`ds5.reports.InputState`) vira movimento/clique do mouse virtual."""
        if self._tracker is not None:
            self._emit_mouse(self._tracker.update(report, self.mapper.sources(self._state)))

    def _grab_touchpad(self) -> None:
        if self._touchpad is not None:
            return
        try:
            device = InputDevice(self.touchpad_path)
        except OSError as error:
            log.warning("Não consegui abrir o touchpad de %s: %s", self.name, error)
            self.touchpad_path = None
            return
        try:
            device.grab()
        except OSError as error:
            log.warning("Não consegui esconder o touchpad de %s: %s", self.name, error)
            device.close()
            self.touchpad_path = None
            return
        self._touchpad = device

    def _release_touchpad(self) -> None:
        if self._touchpad is None:
            return
        try:
            self._touchpad.ungrab()
        except OSError:
            pass
        self._touchpad.close()
        self._touchpad = None

    def _emit_mouse(self, output: MouseOutput) -> None:
        if not output.moves and output.buttons == self._mouse_buttons:
            return
        mouse = self._ensure_mouse()
        if mouse is None:
            return
        for code, value in (
            (ecodes.REL_X, output.dx),
            (ecodes.REL_Y, output.dy),
            (ecodes.REL_WHEEL, output.wheel),
            (ecodes.REL_HWHEEL, output.hwheel),
        ):
            if value:
                mouse.write(ecodes.EV_REL, code, value)
        for name, code in MOUSE_BUTTONS.items():
            if (name in output.buttons) != (name in self._mouse_buttons):
                mouse.write(ecodes.EV_KEY, code, int(name in output.buttons))
        mouse.syn()
        self._mouse_buttons = output.buttons

    def _ensure_mouse(self) -> UInput | None:
        if self._mouse is None and not self._mouse_failed:
            try:
                self._mouse = UInput(mouse_capabilities(), name=MOUSE_NAME)
            except (OSError, UInputError) as error:
                log.warning("Não consegui criar o mouse virtual: %s", error)
                self._mouse_failed = True
        return self._mouse

    def forward(self, event: InputEvent) -> None:
        if event.type == ecodes.EV_SYN:
            if event.code == ecodes.SYN_DROPPED:
                self.sync()
            elif event.code == ecodes.SYN_REPORT:
                self._emit()
        elif event.type == ecodes.EV_KEY:
            name = SOURCE_BUTTONS.get(event.code)
            if name is not None:
                (self._state.pressed.add if event.value else self._state.pressed.discard)(name)
        elif event.type == ecodes.EV_ABS:
            self._read_axis(self._state, event.code, event.value)

    @staticmethod
    def _read_axis(state: InputState, code: int, value: int) -> None:
        axis = SOURCE_AXES.get(code)
        if axis is not None:
            state.axes[axis] = value / 255 if axis in ("l2", "r2") else stick_unit(value)
        elif code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
            horizontal = code == ecodes.ABS_HAT0X
            for name, active in zip(
                ("dpad_left", "dpad_right") if horizontal else ("dpad_up", "dpad_down"), (value < 0, value > 0)
            ):
                (state.pressed.add if active else state.pressed.discard)(name)

    def _emit(self, force: bool = False) -> None:
        """Escreve no Xbox (e no teclado) só o que mudou desde o último envio."""
        output = self.mapper.apply(self._state)
        sent = None if force else self._sent
        old_buttons = sent.buttons if sent else frozenset()
        old_axes = dict(sent.axes) if sent else {}
        for target, code in XBOX_BUTTONS.items():
            if force or (target in output.buttons) != (target in old_buttons):
                self.virtual.write(ecodes.EV_KEY, code, int(target in output.buttons))
        for name, value in output.axes:
            if force or old_axes.get(name) != value:
                self.virtual.write(ecodes.EV_ABS, XBOX_AXES[name], value)
        self.virtual.syn()
        self._emit_keys(output.keys, self._sent.keys if self._sent else frozenset())
        self._sent = output

    def _emit_keys(self, keys: frozenset[str], old: frozenset[str]) -> None:
        if keys == old:
            return
        keyboard = self._ensure_keyboard() if keys else self._keyboard
        if keyboard is None:
            return
        for name in sorted(old - keys) + sorted(keys - old):
            code = ecodes.ecodes.get(name)
            if code is not None:
                keyboard.write(ecodes.EV_KEY, code, int(name in keys))
        keyboard.syn()

    def _ensure_keyboard(self) -> UInput | None:
        if self._keyboard is None and not self._keyboard_failed:
            try:
                self._keyboard = UInput({ecodes.EV_KEY: KEYBOARD_KEYS}, name=KEYBOARD_NAME)
            except (OSError, UInputError) as error:
                log.warning("Não consegui criar o teclado virtual: %s", error)
                self._keyboard_failed = True
        return self._keyboard

    def handle_force_feedback(self, event: InputEvent) -> None:
        """Repete no controle real o que o jogo pediu ao Xbox virtual (efeitos, volume e disparo).

        O hid-playstation já traduz FF_RUMBLE para os motores, então basta espelhar os efeitos no
        evdev físico; o grab não impede quem o fez de enviar efeitos.
        """
        if event.type == ecodes.EV_UINPUT:
            if event.code == ecodes.UI_FF_UPLOAD:
                self._upload(event.value)
            elif event.code == ecodes.UI_FF_ERASE:
                self._erase(event.value)
        elif event.type == ecodes.EV_FF:
            if event.code == ecodes.FF_GAIN:
                self.physical.write(ecodes.EV_FF, ecodes.FF_GAIN, event.value)
            elif event.code in self._effects:
                self.physical.write(ecodes.EV_FF, self._effects[event.code], event.value)

    def _upload(self, request: int) -> None:
        upload = self.virtual.begin_upload(request)
        effect = upload.effect
        virtual_id = effect.id
        try:
            effect.id = self._effects.get(virtual_id, -1)
            upload.retval = 0
            try:
                self._effects[virtual_id] = self.physical.upload_effect(effect)
            except OSError as error:
                log.warning("Efeito de vibração recusado por %s: %s", self.name, error)
                upload.retval = -(error.errno or errno.EIO)
        finally:
            effect.id = virtual_id
            self.virtual.end_upload(upload)

    def _erase(self, request: int) -> None:
        erase = self.virtual.begin_erase(request)
        erase.retval = 0
        try:
            physical_id = self._effects.pop(erase.effect_id, None)
            if physical_id is not None:
                self.physical.erase_effect(physical_id)
        except OSError:
            pass
        finally:
            self.virtual.end_erase(erase)

    async def _pump_force_feedback(self) -> None:
        async for event in self.virtual.async_read_loop():
            try:
                self.handle_force_feedback(event)
            except OSError as error:
                if error.errno == errno.ENODEV:
                    raise
                log.warning("Vibração: %s", error)

    async def run(self) -> None:
        """Repassa eventos até o controle sumir (OSError ENODEV) ou a tarefa ser cancelada."""
        feedback = asyncio.create_task(self._pump_force_feedback())
        try:
            async for event in self.physical.async_read_loop():
                self.forward(event)
        finally:
            feedback.cancel()

    def close(self) -> None:
        try:
            self.physical.ungrab()
        except OSError:
            pass  # o controle já foi desconectado
        for device in (self.physical, self.virtual):
            try:
                asyncio.get_running_loop().remove_reader(device.fd)  # senão o loop lê um fd fechado
            except RuntimeError:
                pass  # sem loop rodando
        for physical_id in self._effects.values():
            try:
                self.physical.erase_effect(physical_id)
            except OSError:
                pass
        self._close_reports()
        self._release_touchpad()
        self.physical.close()
        self.virtual.close()
        for extra in (self._keyboard, self._mouse):
            if extra is not None:
                extra.close()


class Emulator:
    """Procura DualSense, liga os marcados a um Xbox 360 virtual cada e reconecta quando voltam."""

    def __init__(self, scan_interval: float = 1.0, config: Config | None = None):
        self.scan_interval = scan_interval
        self.config = config or Config()
        self._tasks: dict[str, asyncio.Task] = {}
        self._bridges: dict[str, Bridge] = {}
        self._uids: dict[str, str] = {}  # caminho -> MAC, dos controles em uso
        self._idle: dict[str, str] = {}  # caminho -> MAC, dos DualSense que o usuário não marcou
        self._refused: set[str] = set()  # nós que falharam ao abrir; só tenta de novo se sumirem e voltarem

    def scan(self) -> None:
        """Abre os controles marcados; os que sumiram já se removem sozinhos (fim da tarefa)."""
        changed = self.config.refresh()
        if changed:
            mapper = self.config.mapper()
            for path, bridge in self._bridges.items():
                bridge.gyro_offset = self.config.gyro_offsets.get(self._uids[path])
                bridge.set_mapper(mapper)
        for path, uid in list(self._uids.items()):
            if uid not in self.config.uids:  # desmarcado: devolve o controle ao sistema
                log.info("Emulação desligada para %s", uid)
                self._idle[path] = uid
                self._tasks[path].cancel()
        paths = set(list_devices())
        self._refused &= paths
        for path in set(self._idle) - paths:
            del self._idle[path]
        for path in paths - self._tasks.keys() - self._refused:
            uid = self._idle.get(path)
            if uid is None:
                try:
                    device = InputDevice(path)
                except OSError:
                    continue
                try:
                    accepted = is_gamepad(device)
                    uid = (device.uniq or "").lower()
                finally:
                    device.close()
                if not accepted:
                    self._refused.add(path)
                    continue
            if uid not in self.config.uids:
                self._idle[path] = uid
                continue
            try:
                bridge = Bridge.open(path, self.config.mapper(), self.config.gyro_offsets.get(uid))
            except (OSError, UInputError) as error:
                log.warning("Não consegui assumir %s: %s", path, error)
                self._refused.add(path)
                continue
            log.info("Emulando Xbox 360 para %s", bridge.name)
            self._idle.pop(path, None)
            self._uids[path] = uid
            self._bridges[path] = bridge
            self._tasks[path] = asyncio.create_task(self._pump(path, bridge))

    async def _pump(self, path: str, bridge: Bridge) -> None:
        try:
            await bridge.run()
        except OSError as error:
            if error.errno != errno.ENODEV:
                log.warning("Erro lendo %s: %s", bridge.name, error)
            else:
                log.info("Controle desconectado: %s", bridge.name)
        finally:
            bridge.close()
            self._tasks.pop(path, None)
            self._bridges.pop(path, None)
            self._uids.pop(path, None)

    async def run(self) -> None:
        try:
            while True:
                self.scan()
                await asyncio.sleep(self.scan_interval)
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
