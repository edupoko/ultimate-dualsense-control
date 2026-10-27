"""Ícone na bandeja do sistema com o menu rápido dos LEDs."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import i18n
from .i18n import tr
from .emulation import EmulationProcess
from .popup import TrayPopup
from .service import LedService
from .trayicon import tray_icon
from .widgets import (
    ColorPalette,
    ColorSliders,
    ControllerTabs,
    EmulationRow,
    MuteLedRow,
    PlayerRow,
)


class TrayIcon(QObject):
    """Ícone com a cor atual; qualquer clique abre o menu compacto junto à bandeja.

    O menu é desenhado pelo próprio app (e não entregue à bandeja do sistema) porque
    o menu nativo do Plasma só mostra itens de texto, sem os sliders de cor e brilho.
    """

    def __init__(
        self,
        service: LedService,
        show_window: Callable[[], None],
        quit_app: Callable[[], None],
        emulation: EmulationProcess | None = None,
        show_help: Callable[[str], None] | None = None,
    ):
        super().__init__()
        self._service = service
        self._emulation = emulation
        self._show_window = show_window
        # Ajuda ("steam"/"bluetooth") abre dentro da janela principal; sem ela, só mostra a janela.
        self._show_help = show_help or (lambda _kind: show_window())
        self._quit_app = quit_app
        self._notified = False
        # O menu só é montado quando alguém o abre pela primeira vez: quem deixa o app só na
        # bandeja não gasta memória com sliders, paleta e abas que talvez nunca veja.
        self._popup: TrayPopup | None = None

        self._tray = QSystemTrayIcon(self)
        self._tray.activated.connect(self._on_activated)

        service.settings_changed.connect(self._sync)
        service.status_changed.connect(self._on_status)
        service.steam_changed.connect(self._sync_steam)
        service.controllers_changed.connect(self._sync_steam)
        service.bluetooth_changed.connect(self._sync_bluetooth)
        service.controllers_changed.connect(self._sync_disconnect)
        service.settings_changed.connect(self._sync_disconnect)
        self._sync()
        self._on_status(service.status)

    def _build_popup(self) -> TrayPopup:
        service = self._service
        popup = TrayPopup()
        self._popup = popup
        self._status = popup.add_item(service.status, enabled=False)
        # Só aparece com mais de um DualSense conectado.
        popup.add_row(ControllerTabs(service))
        # Só aparece quando a Steam está controlando o controle selecionado.
        self._steam_item = popup.add_item("", lambda: self._show_help("steam"))
        i18n.bind(self._steam_item.set_text, "tray.steam_item")
        # Só aparece quando o Bluetooth tem um DualSense "conectado" que o sistema não registrou.
        self._bluetooth_item = popup.add_item("", lambda: self._show_help("bluetooth"))
        i18n.bind(self._bluetooth_item.set_text, "tray.bluetooth_item")
        popup.add_separator()

        popup.add_row(ColorSliders(service))
        quick_colors = popup.add_expander("", ColorPalette(service))
        i18n.bind(quick_colors.set_text, "tray.quick_colors")
        popup.add_separator()

        popup.add_row(PlayerRow(service))
        popup.add_row(MuteLedRow(service, compact=True))
        popup.add_separator()

        if self._emulation is not None:
            popup.add_row(EmulationRow(service, self._emulation, compact=True))
            popup.add_separator()

        # Só aparece quando o controle selecionado está no Bluetooth.
        self._disconnect_item = popup.add_item("", service.disconnect_selected)
        i18n.bind(self._disconnect_item.set_text, "controller.disconnect")
        expand_item = popup.add_item("", self._show_window)
        i18n.bind(expand_item.set_text, "tray.expand")
        quit_item = popup.add_item("", self._quit_app)
        i18n.bind(quit_item.set_text, "tray.quit")
        popup.align_rows(quit_item)

        self._on_status(service.status)
        self._sync_steam()
        self._sync_bluetooth()
        self._sync_disconnect()
        return popup

    def notify_still_running(self) -> None:
        """Na primeira vez que a janela é fechada, avisa que o app continua na bandeja."""
        if self._notified:
            return
        self._notified = True
        self._tray.showMessage(
            "DualSense Ultimate Control",
            tr("tray.still_running"),
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

    def show_message(self, title: str, text: str) -> None:
        self._tray.showMessage(title, text, QSystemTrayIcon.MessageIcon.Warning, 6000)

    @property
    def popup(self) -> TrayPopup:
        """O menu da bandeja; é montado na primeira vez que alguém o pede."""
        return self._popup or self._build_popup()

    @property
    def built_popup(self) -> TrayPopup | None:
        """O menu, se já foi montado (sem montar só para olhar)."""
        return self._popup

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        """Tira o ícone da bandeja e fecha o menu; usado ao encerrar, para sumirem na hora."""
        if self._popup is not None:
            self._popup.hide()
        self._tray.hide()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.Context):
            self.popup.toggle()

    def _sync(self) -> None:
        settings = self._service.settings
        # O contorno usa a cor de texto do tema, para aparecer tanto em painel claro quanto escuro.
        line = QApplication.palette().color(QPalette.ColorRole.WindowText)
        self._tray.setIcon(tray_icon(settings.color, settings.brightness, line))

    def _sync_steam(self) -> None:
        if self._popup is not None:
            self._steam_item.setVisible(self._service.steam_controls_selected)

    def _sync_disconnect(self) -> None:
        if self._popup is not None:
            self._disconnect_item.setVisible(self._service.can_disconnect)

    def _sync_bluetooth(self) -> None:
        if self._popup is not None:
            self._bluetooth_item.setVisible(bool(self._service.unregistered_bluetooth))

    def _on_status(self, text: str) -> None:
        if self._popup is not None:
            self._status.set_text(text)
        self._tray.setToolTip(f"DualSense Ultimate Control: {text}")
