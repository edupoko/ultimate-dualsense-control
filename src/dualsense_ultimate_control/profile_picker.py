"""Seletor rápido do perfil padrão, na página Controles (a edição dos perfis fica na página própria)."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from . import i18n
from .emulator.config import default_profiles_dir
from .emulator.mapping import ProfileStore
from .i18n import tr
from .service import LedService


class ProfilePicker(QWidget):
    """Lista os perfis criados e grava o escolhido como padrão (o daemon relê o arquivo sozinho).

    Perfis por aplicativo continuam valendo enquanto o programa roda; este é o de quando não há nenhum."""

    def __init__(self, service: LedService, store: ProfileStore | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._store = store or ProfileStore(default_profiles_dir())
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel()
        i18n.bind(label.setText, "profiles.quick")
        i18n.bind(label.setToolTip, "profiles.quick_tip")
        layout.addWidget(label, 1)
        self._combo = QComboBox()
        i18n.bind(self._combo.setToolTip, "profiles.quick_tip")
        self._combo.activated.connect(self._on_chosen)
        layout.addWidget(self._combo)
        service.settings_changed.connect(self.refresh)
        i18n.hub.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """Relê a pasta de perfis (criados, apagados ou renomeados na outra página) e o padrão salvo."""
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItem(tr("profiles.no_changes"), "")
        for profile in self._store.load_all():
            self._combo.addItem(profile.name, profile.name)
        self._combo.setCurrentIndex(max(self._combo.findData(self._service.default_profile), 0))
        self._combo.blockSignals(False)

    def showEvent(self, event) -> None:
        self.refresh()
        super().showEvent(event)

    def _on_chosen(self, index: int) -> None:
        self._service.set_default_profile(self._combo.itemData(index) or "")
