"""Configurações dos LEDs, salvas em disco e restauradas ao conectar cada controle."""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .colors import MAX_CUSTOM_COLORS
from .sysfs import PLAYER_LED_COUNT


@dataclass
class LightSettings:
    """Estado dos LEDs de um controle."""

    color: tuple[int, int, int] = (0, 0, 255)
    brightness: int = 255
    players: list[bool] = field(default_factory=lambda: [False] * PLAYER_LED_COUNT)
    # LED do botão de microfone aceso (fixo).
    mute_led: bool = False

    def copy(self) -> LightSettings:
        return LightSettings(self.color, self.brightness, list(self.players), self.mute_led)


@dataclass
class AppSettings:
    """Tudo o que fica salvo: o estado de cada controle e as cores criadas pelo usuário."""

    # Usado por um controle visto pela primeira vez; acompanha a última alteração feita.
    default: LightSettings = field(default_factory=LightSettings)
    controllers: dict[str, LightSettings] = field(default_factory=dict)
    custom_colors: list[tuple[int, int, int]] = field(default_factory=list)
    # Fechar a janela só a esconde (app continua na bandeja); False encerra o app.
    close_to_tray: bool = True
    # Com 2 ou mais controles, cada um recebe sozinho o LED de jogador da sua posição (1, 2, ...).
    auto_players: bool = True
    # Idioma da interface: "pt", "en" ou "es".
    language: str = "pt"
    # Correção do giroscópio por controle (uid): desvio bruto (pitch, yaw, roll) medido parado.
    gyro_offsets: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    # Controles (uid, em minúsculas) com a emulação de Xbox 360 ligada: o app a religa ao abrir.
    emulation: list[str] = field(default_factory=list)
    # Perfil de remapeamento usado quando nenhum perfil de aplicativo está ativo ("" = sem alterações).
    default_profile: str = ""
    # Tema visual: "auto" (pelo desktop), "kde", "gnome" ou "own". Vale na próxima abertura do app.
    theme: str = "auto"


def default_settings_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "dualsense-ultimate-control" / "settings.json"


def load_settings(path: Path, strict: bool = False) -> AppSettings:
    """Lê as configurações; arquivo ausente ou inválido volta para os padrões.

    Com `strict`, só o arquivo ausente vira padrão: um ilegível levanta `SettingsError`, para o daemon
    da emulação manter o que já sabia em vez de soltar todos os controles.
    """
    try:
        data = json.loads(path.read_text())
        # Formato antigo: os LEDs ficavam na raiz, sem separar por controle.
        default = _light(data["default"] if "default" in data else data)
        controllers = {}
        for uid, entry in data.get("controllers", {}).items():
            try:
                controllers[str(uid)] = _light(entry)
            except (ValueError, KeyError, TypeError):
                continue
        custom = [_color(value) for value in data.get("custom_colors", [])][-MAX_CUSTOM_COLORS:]
        offsets = {}
        for uid, entry in data.get("gyro_offsets", {}).items():
            try:
                offsets[str(uid)] = _offset(entry)
            except (ValueError, TypeError):
                continue
        return AppSettings(
            default, controllers, custom, bool(data.get("close_to_tray", True)), bool(data.get("auto_players", True)),
            str(data.get("language", "pt")), offsets, _uids(data.get("emulation")), str(data.get("default_profile", "")),
            str(data.get("theme", "auto")),
        )
    except FileNotFoundError:
        return AppSettings()
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        if strict:
            raise SettingsError(str(error)) from error
        return AppSettings()


class SettingsError(Exception):
    """O settings.json existe, mas não deu para lê-lo."""


def write_atomic(path: Path, text: str) -> None:
    """Grava num arquivo ao lado e troca de uma vez: quem lê ao mesmo tempo (o daemon da emulação,
    a cada segundo) nunca vê o arquivo pela metade, e uma falha no meio não destrói o anterior."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text)
    os.replace(temporary, path)


def save_settings(path: Path, settings: AppSettings) -> None:
    # Pegando o arquivo pela metade, o daemon acharia que nenhum controle está marcado e soltaria todos.
    write_atomic(path, json.dumps(asdict(settings), indent=2))


def _light(data) -> LightSettings:
    players = [bool(v) for v in data["players"]]
    if len(players) != PLAYER_LED_COUNT:
        raise ValueError("número de LEDs de jogador inválido")
    return LightSettings(_color(data["color"]), _byte(data["brightness"]), players, bool(data.get("mute_led", False)))


def _uids(value) -> list[str]:
    # Antes era um interruptor único (bool) para todos os controles; esse formato não diz quais eram.
    if not isinstance(value, list):
        return []
    return sorted({str(uid).lower() for uid in value if str(uid)})


def _byte(value) -> int:
    return max(0, min(255, int(value)))


def _color(value) -> tuple[int, int, int]:
    red, green, blue = (_byte(v) for v in value)
    return red, green, blue


def _offset(value) -> tuple[float, float, float]:
    pitch, yaw, roll = (float(v) for v in value)
    if not all(math.isfinite(v) for v in (pitch, yaw, roll)):
        raise ValueError("correção do giroscópio inválida")
    return pitch, yaw, roll
