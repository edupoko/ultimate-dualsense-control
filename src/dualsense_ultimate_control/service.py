"""Estado dos LEDs: guarda as configurações e as aplica a cada DualSense conectado."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from .battery import POWER_ROOT, Battery, read_battery
from .colors import MAX_CUSTOM_COLORS, PRESETS
from .settings import LightSettings, load_settings, save_settings
from . import bluetooth, i18n, theme
from .actions import log_action, log_burst
from .bluetooth import unregistered_dualsense
from .players import PLAYER_COUNT, pattern_for
from .steam import hidraw_held_by_steam
from .sysfs import LEDS_ROOT, Controller, find_controllers

log = logging.getLogger(__name__)

POLL_INTERVAL_MS = 1000
# Cada escrita de LED vira um relatório enviado ao controle. Pelo Bluetooth, uma rajada deles (um
# slider arrastado gera dezenas por segundo) enche o canal do BlueZ, que derruba o controle.
# Por isso o Bluetooth recebe no máximo uma atualização a cada intervalo, sempre com o valor mais recente.
BLUETOOTH_WRITE_INTERVAL_MS = 120
# O Bluetooth é consultado com menos frequência: chamar o BlueZ a cada segundo seria desperdício.
BLUETOOTH_CHECK_EVERY = 5


class LedService(QObject):
    """Fonte única do estado dos LEDs, compartilhada pela bandeja e pela janela."""

    settings_changed = Signal()
    status_changed = Signal(str)
    # A lista de controles conectados ou o controle selecionado mudou.
    controllers_changed = Signal()
    # Mudou o conjunto de controles que a Steam está controlando diretamente.
    steam_changed = Signal()
    # Mudou a lista de DualSense conectados pelo Bluetooth que o sistema não registrou.
    bluetooth_changed = Signal()
    # Mudou a bateria de algum controle (lida do sysfs por `refresh_batteries`).
    battery_changed = Signal()

    def __init__(
        self,
        settings_path: Path,
        leds_root: Path = LEDS_ROOT,
        steam_probe=hidraw_held_by_steam,
        bluetooth_probe=unregistered_dualsense,
        power_root: Path = POWER_ROOT,
    ):
        super().__init__()
        self._power_root = power_root
        self._batteries: dict[str, Battery] = {}
        self._steam_probe = steam_probe
        self._bluetooth_probe = bluetooth_probe
        self._unregistered: list[str] = []
        self._refreshes = 0
        # Controles (pelo nome) cujo dispositivo a Steam mantém aberto.
        self._steam: set[str] = set()
        self._settings_path = settings_path
        self._leds_root = leds_root
        self._store = load_settings(settings_path)
        i18n.set_language(self._store.language)
        self._controllers: dict[str, Controller] = {}
        # Nome (ex.: "input195") do controle que a interface está controlando.
        self._selected: str | None = None
        # Controles que já receberam as configurações; os que falharam são tentados de novo.
        self._applied: set[str] = set()
        # Controles cuja falha já foi registrada, para não repetir o aviso a cada segundo.
        self._failed: set[str] = set()
        # Controles cuja última falha foi falta de permissão (regra udev ausente ou não aplicada).
        self._denied: set[str] = set()
        # A mensagem de status é guardada como chave: o texto sai no idioma atual a cada leitura.
        # Último estado escrito em cada controle: só o que mudou volta a ser escrito.
        self._written: dict[str, dict] = {}
        # Controles Bluetooth com atualização adiada (nome -> timer) e os que ainda têm algo a escrever.
        self._throttle: dict[str, QTimer] = {}
        self._pending: dict[str, bool] = {}
        self._status_key = "status.searching"
        self._status_values: dict = {}
        i18n.hub.changed.connect(lambda: self.status_changed.emit(self.status))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)

    @property
    def settings_path(self) -> Path:
        return self._settings_path

    @property
    def settings(self) -> LightSettings:
        """Estado dos LEDs do controle selecionado (ou o padrão, sem nenhum conectado)."""
        controller = self._controllers.get(self._selected)
        return self._profile_for(controller) if controller else self._store.default

    @property
    def close_to_tray(self) -> bool:
        return self._store.close_to_tray

    def set_close_to_tray(self, enabled: bool) -> None:
        log.info("Manter na bandeja ao fechar: %s", "ligado" if enabled else "desligado")
        self._store.close_to_tray = bool(enabled)
        self._save()
        self.settings_changed.emit()

    @property
    def emulation(self) -> bool:
        """Se algum controle deve ter a emulação de Xbox 360 ligada (a escolha do usuário, salva)."""
        return bool(self._store.emulation)

    def set_emulation(self, enabled: bool) -> None:
        """Liga ou desliga a emulação de todos os controles de uma vez (desligar limpa a escolha salva)."""
        if enabled:
            raise ValueError("a emulação se liga por controle: use set_emulation_for")
        if self._store.emulation:
            self._store.emulation = []
            self._save()
            self.settings_changed.emit()

    def emulation_for(self, uid: str) -> bool:
        return uid.lower() in self._store.emulation

    def set_emulation_for(self, uid: str, enabled: bool) -> None:
        uid = uid.lower()
        if (uid in self._store.emulation) == bool(enabled):
            return
        chosen = set(self._store.emulation)
        chosen.add(uid) if enabled else chosen.discard(uid)
        self._store.emulation = sorted(chosen)
        self._save()
        log_action("emulação de Xbox 360", self.controller_for_uid(uid) or uid, value="ligada" if enabled else "desligada")
        self.settings_changed.emit()

    @property
    def selected_uid(self) -> str | None:
        """Identificador (MAC) do controle selecionado, ou None sem nenhum conectado."""
        controller = self._controllers.get(self._selected)
        return controller.uid if controller else None

    @property
    def default_profile(self) -> str:
        return self._store.default_profile

    def set_default_profile(self, name: str) -> None:
        if self._store.default_profile != name:
            self._store.default_profile = name
            self._save()
            log_action("perfil padrão da emulação", None, value=name or "(sem alterações)")

    @property
    def auto_players(self) -> bool:
        return self._store.auto_players

    def set_auto_players(self, enabled: bool) -> None:
        log.info("Jogadores automáticos: %s", "ligado" if enabled else "desligado")
        self._store.auto_players = bool(enabled)
        self._save()
        self._apply_to(self._controllers.values())
        self.settings_changed.emit()

    @property
    def players_assigned_automatically(self) -> bool:
        """Com 2 ou mais controles (e a opção ligada), o jogador de cada um é escolhido pelo app."""
        return self._store.auto_players and len(self._controllers) >= 2

    @property
    def players(self) -> list[bool]:
        """LEDs de jogador do controle selecionado: o padrão automático ou o escolhido por você."""
        controller = self._controllers.get(self._selected)
        return self._players_for(controller) if controller else list(self.settings.players)

    def _players_for(self, controller: Controller) -> list[bool]:
        if self.players_assigned_automatically:
            # A posição na lista é o número da aba: o controle 1 é o jogador 1, e assim por diante.
            position = list(self._controllers).index(controller.name) + 1
            return pattern_for(min(position, PLAYER_COUNT))
        return list(self._profile_for(controller).players)

    @property
    def custom_colors(self) -> list[tuple[int, int, int]]:
        return self._store.custom_colors

    def gyro_offset(self, uid: str) -> tuple[float, float, float] | None:
        """Correção salva do giroscópio de um controle (`ds5.imu`), ou None."""
        return self._store.gyro_offsets.get(uid)

    def set_gyro_offset(self, uid: str, offset: tuple[float, float, float] | None) -> None:
        if offset is None:
            log_action("correção do giroscópio", self.controller_for_uid(uid) or uid, value="removida")
            self._store.gyro_offsets.pop(uid, None)
        else:
            log_action("correção do giroscópio", self.controller_for_uid(uid) or uid, value="salva", offset=offset)
            self._store.gyro_offsets[uid] = tuple(offset)
        self._save()

    @property
    def controllers(self) -> list[Controller]:
        return list(self._controllers.values())

    @property
    def selected(self) -> str | None:
        return self._selected

    @property
    def can_disconnect(self) -> bool:
        """O controle selecionado está no Bluetooth: só esse dá para desconectar por software."""
        controller = self._controllers.get(self._selected)
        return controller is not None and controller.connection == "Bluetooth"

    def disconnect_selected(self) -> None:
        """Desconecta o controle Bluetooth selecionado; para voltar, aperte o botão PS nele."""
        controller = self._controllers.get(self._selected)
        if controller is None or not self.can_disconnect:
            log.warning("Não há controle Bluetooth selecionado para desconectar")
            return
        log_action("desconectar (Bluetooth)", controller)
        bluetooth.disconnect(controller.uid)

    @property
    def steam_controls_selected(self) -> bool:
        """A Steam está com o controle selecionado aberto e pode sobrescrever os LEDs dele."""
        return self._selected in self._steam

    @property
    def unregistered_bluetooth(self) -> list[str]:
        """Endereços de DualSense conectados pelo Bluetooth que o sistema não registrou."""
        return list(self._unregistered)

    def reapply_selected(self) -> None:
        """Manda de novo o estado salvo para o controle selecionado (depois que a Steam o mudou)."""
        controller = self._controllers.get(self._selected)
        if controller is not None:
            # A Steam (ou outro programa) pode ter mudado os LEDs por fora: reescreve tudo.
            self._apply_to([controller], force=True)

    @property
    def status(self) -> str:
        return i18n.tr(self._status_key, **self._status_values)

    @property
    def language(self) -> str:
        return self._store.language

    def set_language(self, code: str) -> None:
        """Troca o idioma da interface na hora e o guarda para a próxima vez."""
        if code not in i18n.LANGUAGES:
            return
        log.info("Idioma alterado para %s", code)
        self._store.language = code
        self._save()
        i18n.set_language(code)

    @property
    def theme(self) -> str:
        return self._store.theme

    def set_theme(self, name: str) -> None:
        """Guarda o tema visual; ele é aplicado na próxima abertura do app (o do KDE exige isso)."""
        if name not in ("auto", *theme.THEMES):
            return
        log.info("Tema alterado para %s", name)
        self._store.theme = name
        self._save()

    @property
    def window_geometry(self) -> tuple[list[int], bool]:
        """Posição/tamanho salvos da janela principal ([x, y, w, h] ou []) e se estava maximizada."""
        return list(self._store.window_geometry), self._store.window_maximized

    def set_window_geometry(self, geometry: list[int], maximized: bool) -> None:
        if (list(geometry), bool(maximized)) == self.window_geometry:
            return
        self._store.window_geometry = [int(v) for v in geometry]
        self._store.window_maximized = bool(maximized)
        self._save()

    @property
    def needs_permission(self) -> bool:
        return bool(self._denied)

    def start(self) -> None:
        self.refresh()
        self._timer.start(POLL_INTERVAL_MS)

    def retry(self) -> None:
        """Tenta de novo agora (após liberar a permissão), registrando novas falhas."""
        self._failed.clear()
        self.refresh()

    def select_controller(self, name: str) -> None:
        if name in self._controllers and name != self._selected:
            self._selected = name
            self.controllers_changed.emit()
            self.settings_changed.emit()

    def refresh(self) -> None:
        previous = (list(self._controllers), self._selected)
        self._controllers = {c.name: c for c in find_controllers(self._leds_root)}
        if self._selected not in self._controllers:
            self._selected = next(iter(self._controllers), None)
        self._applied = {name for name in self._applied if name in self._controllers}
        self._failed = {name for name in self._failed if name in self._controllers}
        self._denied = {name for name in self._denied if name in self._controllers}
        self._log_controller_changes(previous[0])
        if list(self._controllers) != previous[0]:
            # Entrou ou saiu um controle: os jogadores automáticos mudam de posição, então todos
            # recebem as configurações de novo.
            self._applied.clear()
        self._update_steam()
        if self._refreshes % BLUETOOTH_CHECK_EVERY == 0:
            self._update_bluetooth()
        self._refreshes += 1
        self._apply_to(c for c in self._controllers.values() if c.name not in self._applied)
        self._update_status()
        if previous != (list(self._controllers), self._selected):
            self.controllers_changed.emit()
            if previous[1] != self._selected:
                self.settings_changed.emit()

    def _selected_controller(self) -> Controller | None:
        return self._controllers.get(self._selected)

    def battery_for(self, uid: str) -> Battery | None:
        """Última bateria lida do controle, ou None se o controle não a expõe."""
        return self._batteries.get(uid)

    def refresh_batteries(self) -> None:
        """Relê a bateria de todos os controles conectados; avisa só se algo mudou."""
        current = {}
        for c in self._controllers.values():
            battery = read_battery(c.uid, self._power_root) if c.uid else None
            if battery is not None:
                current[c.uid] = battery
        if current != self._batteries:
            self._batteries = current
            self.battery_changed.emit()

    def controller_for_uid(self, uid: str) -> Controller | None:
        return next((c for c in self._controllers.values() if c.uid == uid), None)

    def _log_selected(self, kind: str, **detail) -> None:
        log_action(kind, self._selected_controller(), **detail)

    def _log_selected_burst(self, key: str, kind: str, **detail) -> None:
        controller = self._selected_controller()
        log_burst(f"{key}:{controller.uid if controller else ''}", kind, controller, **detail)

    def set_color(self, color: tuple[int, int, int]) -> None:
        self.settings.color = tuple(color)
        self._log_selected_burst("cor", "cor", value="#%02X%02X%02X" % self.settings.color)
        self._changed()

    def add_custom_color(self, color: tuple[int, int, int]) -> None:
        """Aplica a cor e a guarda no seletor rápido, se ainda não estiver lá."""
        color = tuple(color)
        custom = self._store.custom_colors
        if color not in PRESETS.values() and color not in custom:
            custom.append(color)
            del custom[:-MAX_CUSTOM_COLORS]
            self._log_selected("cor guardada no seletor rápido", value="#%02X%02X%02X" % color)
        self.set_color(color)

    def set_brightness(self, value: int) -> None:
        self.settings.brightness = max(0, min(255, value))
        self._log_selected_burst("brilho", "brilho", value=self.settings.brightness)
        self._changed()

    def set_player(self, index: int, on: bool) -> None:
        self.settings.players[index] = on
        self._log_selected("LED de jogador", value=f"{index + 1} {'ligado' if on else 'desligado'}")
        self._changed()

    def set_players(self, flags: list[bool]) -> None:
        self.settings.players = list(flags)
        self._log_selected("LEDs de jogador", value=",".join(str(i + 1) for i, on in enumerate(flags) if on) or "nenhum")
        self._changed()

    def set_mute_led(self, on: bool) -> None:
        self.settings.mute_led = bool(on)
        self._log_selected("LED do microfone", value="ligado" if on else "desligado")
        self._changed(write_mute=True)

    def _log_controller_changes(self, before: list[str]) -> None:
        for name in self._controllers:
            if name not in before:
                controller = self._controllers[name]
                log.info(
                    "Controle conectado: %s (%s, %s, %s)",
                    name, controller.connection or "conexão desconhecida", controller.uid, controller.hidraw or "sem hidraw",
                )
        for name in before:
            if name not in self._controllers:
                log.info("Controle desconectado: %s", name)

    def _update_bluetooth(self) -> None:
        unregistered = self._bluetooth_probe(c.uid for c in self._controllers.values())
        if unregistered != self._unregistered:
            if unregistered:
                log.warning("DualSense conectado pelo Bluetooth mas não registrado pelo sistema: %s", ", ".join(unregistered))
            else:
                log.info("Todos os DualSense do Bluetooth estão registrados")
            self._unregistered = unregistered
            self.bluetooth_changed.emit()

    def _update_steam(self) -> None:
        held = self._steam_probe()
        steam = {c.name for c in self._controllers.values() if c.hidraw and c.hidraw in held}
        if steam == self._steam:
            return
        for name in steam - self._steam:
            log.info("A Steam passou a controlar %s", name)
        for name in self._steam - steam:
            log.info("A Steam soltou %s", name)
        # Quando a Steam solta um controle, ele fica com as cores dela: reaplica as do app.
        for name in self._steam - steam:
            self._applied.discard(name)
            self._written.pop(name, None)  # a Steam mexeu nos LEDs: nada do que escrevemos vale mais
        self._steam = steam
        self.steam_changed.emit()

    def _profile_for(self, controller: Controller) -> LightSettings:
        """Estado salvo do controle; um controle novo começa com a última configuração usada."""
        profiles = self._store.controllers
        if controller.uid not in profiles:
            profiles[controller.uid] = self._store.default.copy()
        return profiles[controller.uid]

    def _apply_to(self, controllers, write_mute: bool = False, force: bool = False) -> None:
        for controller in controllers:
            if force:
                self._written.pop(controller.name, None)
            if controller.connection == "Bluetooth":
                self._apply_throttled(controller, write_mute)
            else:
                self._write(controller, write_mute)

    def _apply_throttled(self, controller: Controller, write_mute: bool) -> None:
        """Pelo Bluetooth: escreve já se o canal está livre; senão guarda e escreve ao fim do intervalo."""
        name = controller.name
        timer = self._throttle.get(name)
        if timer is not None:
            self._pending[name] = self._pending.get(name, False) or write_mute
            return
        self._write(controller, write_mute)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(BLUETOOTH_WRITE_INTERVAL_MS)
        timer.timeout.connect(lambda name=name: self._flush_bluetooth(name))
        self._throttle[name] = timer
        timer.start()

    def _flush_bluetooth(self, name: str) -> None:
        timer = self._throttle.get(name)
        controller = self._controllers.get(name)
        if name in self._pending and controller is not None:
            self._write(controller, self._pending.pop(name))
            if timer is not None:
                timer.start()  # mais um intervalo antes de aceitar outra escrita
                return
        self._pending.pop(name, None)
        self._throttle.pop(name, None)
        if timer is not None:
            timer.deleteLater()

    def flush(self) -> None:
        """Escreve agora o que ficou adiado nos controles Bluetooth (usado ao sair e nos testes)."""
        for name in list(self._pending):
            controller = self._controllers.get(name)
            if controller is not None:
                self._write(controller, self._pending.pop(name))
            else:
                self._pending.pop(name, None)

    def _write(self, controller: Controller, write_mute: bool = False) -> None:
        settings = self._profile_for(controller)
        wanted = {
            "color": tuple(settings.color),
            "brightness": settings.brightness,
            "players": tuple(self._players_for(controller)),
        }
        written = self._written.setdefault(controller.name, {})
        try:
            # Só o que mudou: mexer na cor não reescreve brilho nem LEDs de jogador.
            if written.get("color") != wanted["color"]:
                controller.set_color(*wanted["color"])
                written["color"] = wanted["color"]
            if written.get("brightness") != wanted["brightness"]:
                controller.set_brightness(wanted["brightness"])
                written["brightness"] = wanted["brightness"]
            if written.get("players") != wanted["players"]:
                controller.set_players(list(wanted["players"]))
                written["players"] = wanted["players"]
            # O LED de microfone só é escrito quando o usuário o muda ou quando deve ficar aceso:
            # escrever "apagado" sempre brigaria com o botão de microfone, que o acende sozinho.
            if controller.hidraw and (write_mute or settings.mute_led):
                controller.set_mute_led(settings.mute_led)
        except OSError as error:
            self._written.pop(controller.name, None)
            self._applied.discard(controller.name)
            if isinstance(error, PermissionError):
                self._denied.add(controller.name)
            else:
                self._denied.discard(controller.name)
            if controller.name not in self._failed:
                log.warning("Falha ao aplicar LEDs em %s: %s", controller.name, error)
                self._failed.add(controller.name)
        else:
            self._applied.add(controller.name)
            self._failed.discard(controller.name)
            self._denied.discard(controller.name)

    def _changed(self, write_mute: bool = False) -> None:
        controller = self._controllers.get(self._selected)
        if controller is not None:
            self._store.default = self.settings.copy()
        self._save()
        # Só o controle selecionado muda; os outros mantêm o que já têm.
        self._apply_to([controller] if controller else [], write_mute)
        self.settings_changed.emit()
        self._update_status()

    def _save(self) -> None:
        try:
            save_settings(self._settings_path, self._store)
        except OSError as error:
            log.warning("Falha ao salvar configurações: %s", error)

    def _update_status(self) -> None:
        count = len(self._controllers)
        values: dict = {}
        if count == 0:
            key = "status.none"
        elif self._denied:
            key = "status.no_permission"
        elif len(self._applied) < count:
            key = "status.error"
        elif count == 1:
            key = "status.connected"
        else:
            key, values = "status.connected_many", {"count": count}
        if (key, values) != (self._status_key, self._status_values):
            self._status_key, self._status_values = key, values
            self.status_changed.emit(self.status)
