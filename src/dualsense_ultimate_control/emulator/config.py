"""O que o daemon lê do app: quais controles emular e qual perfil de remapeamento vale.

O app e o daemon são processos diferentes, então a conversa é por arquivos: `settings.json` (controles
marcados e perfil padrão) e a pasta de perfis. O daemon confere os dois a cada varredura e só relê
quando mudam.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..settings import SettingsError, default_settings_path, load_settings
from .mapping import Mapper, Profile, ProfileStore, pick_profile, running_processes

log = logging.getLogger(__name__)

# Varrer /proc tem custo: o perfil por aplicativo é reavaliado com esta frequência (em varreduras).
PROCESS_CHECK_EVERY = 2


def default_profiles_dir() -> Path:
    return default_settings_path().parent / "profiles"


class Config:
    def __init__(self, settings_path: Path | None = None, profiles_dir: Path | None = None, processes=running_processes):
        self.settings_path = settings_path or default_settings_path()
        self.store = ProfileStore(profiles_dir or default_profiles_dir())
        self._processes = processes
        self._stamp: tuple | None = None
        self._profiles: list[Profile] = []
        self._default = Profile()
        self._scans = 0
        self._read_error = ""  # último erro de leitura do settings.json, para não repetir o aviso a cada segundo
        self.uids: frozenset[str] = frozenset()  # controles com a emulação ligada
        self.gyro_offsets: dict[str, tuple[float, float, float]] = {}  # correção do giroscópio (E4) por MAC
        self.profile: Profile = self._default

    def _signature(self) -> tuple:
        try:
            settings = self.settings_path.stat().st_mtime_ns
        except OSError:
            settings = None
        return settings, self.store.signature()

    def refresh(self) -> bool:
        """Relê o que mudou e reavalia o perfil ativo; True se o perfil ativo, os controles ou as correções
        do giroscópio mudaram."""
        stamp = self._signature()
        changed = False
        if stamp != self._stamp:
            try:
                settings = load_settings(self.settings_path, strict=True)
            except SettingsError as error:
                # Ilegível (editado à mão, permissão): manter o que vale em vez de soltar todos os controles.
                # O carimbo não muda, então tenta de novo na próxima varredura.
                if str(error) != self._read_error:
                    log.warning("Não consegui ler %s: %s", self.settings_path, error)
                self._read_error = str(error)
                settings = None
            if settings is not None:
                self._read_error = ""
                self._stamp = stamp
                uids = frozenset(settings.emulation)
                self._profiles = self.store.load_all()
                self._default = next((p for p in self._profiles if p.name == settings.default_profile), Profile())
                offsets = {uid.lower(): offset for uid, offset in settings.gyro_offsets.items()}
                changed = uids != self.uids or offsets != self.gyro_offsets
                self.uids = uids
                self.gyro_offsets = offsets
                self._scans = 0  # perfis novos: reavalia já
        if self._scans % PROCESS_CHECK_EVERY == 0:
            wants_processes = any(p.apps or p.steam_appids for p in self._profiles)
            chosen = pick_profile(self._profiles, self._processes() if wants_processes else [], self._default)
            if chosen.to_dict() != self.profile.to_dict():
                log.info("Perfil ativo: %s", chosen.name or "(sem alterações)")
                changed = True
            self.profile = chosen
        self._scans += 1
        return changed

    def mapper(self) -> Mapper:
        return Mapper(self.profile)
