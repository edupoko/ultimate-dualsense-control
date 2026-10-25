"""Janela principal com todos os controles dos LEDs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import i18n
from .i18n import tr
from .emulation import EmulationProcess
from .logview import LogWindow
from .permissions import RuleInstaller
from .profiles_dialog import ProfilesDialog
from .service import LedService
from .testpanel.window import TestWindow
from .widgets import (
    AutoPlayersRow,
    AutostartRow,
    CloseToTrayRow,
    ColorPalette,
    EmulationRow,
    ColorSliders,
    ControllerTabs,
    DisconnectRow,
    LanguageRow,
    LogsRow,
    MuteLedRow,
    PlayerRow,
    pick_color,
    show_bluetooth_help,
    show_steam_help,
)

ICON_PATH = Path(__file__).with_name("icons") / "dualsense-ultimate-control.svg"

def app_icon() -> QIcon:
    return QIcon(str(ICON_PATH))


class MainWindow(QWidget):
    """Janela com todos os controles, aberta pelo menu de aplicativos ou pela bandeja."""

    # A janela foi fechada pelo "X" e o app continua na bandeja.
    hidden_to_tray = Signal()

    def __init__(
        self,
        service: LedService,
        tray_available: bool,
        installer: RuleInstaller | None = None,
        quit_app: Callable[[], None] = QApplication.quit,
        emulation: EmulationProcess | None = None,
    ):
        super().__init__()
        self._service = service
        self._tray_available = tray_available
        self._quit_app = quit_app
        self._log_window: LogWindow | None = None
        self._test_window: TestWindow | None = None
        self._profiles_dialog: ProfilesDialog | None = None
        self._installer = installer or RuleInstaller()
        self._installer.finished.connect(self._on_installed)
        # Pergunta automaticamente só uma vez a cada perda de permissão; depois fica o botão.
        self._asked_permission = False
        self.setWindowTitle("DualSense Ultimate Control")
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        self._status = QLabel()
        self._status.setWordWrap(True)
        font = self._status.font()
        font.setBold(True)
        self._status.setFont(font)
        layout.addWidget(self._status)
        layout.addWidget(ControllerTabs(service))
        layout.addWidget(self._build_steam_notice())
        layout.addWidget(self._build_bluetooth_notice())

        layout.addWidget(self._build_permission_banner())
        layout.addWidget(self._build_light_group())
        layout.addWidget(self._build_players_group())

        test_button = QPushButton()
        i18n.bind(test_button.setText, "test.open")
        test_button.clicked.connect(self.show_test)
        layout.addWidget(test_button)
        if emulation is not None:
            layout.addWidget(EmulationRow(service, emulation))
            profiles_button = QPushButton()
            i18n.bind(profiles_button.setText, "profiles.open")
            profiles_button.clicked.connect(self.show_profiles)
            layout.addWidget(profiles_button)

        general = QGroupBox()
        i18n.bind(general.setTitle, "window.general")
        general_layout = QVBoxLayout(general)
        general_layout.addWidget(LanguageRow(service))
        general_layout.addWidget(AutostartRow())
        general_layout.addWidget(AutoPlayersRow(service))
        close_to_tray = CloseToTrayRow(service)
        # Sem bandeja não há para onde mandar o app: fechar sempre encerra.
        close_to_tray.setEnabled(tray_available)
        general_layout.addWidget(close_to_tray)
        general_layout.addWidget(LogsRow(self.show_logs))
        layout.addWidget(general)

        footer = QHBoxLayout()
        footer.addStretch(1)
        quit_button = QPushButton()
        i18n.bind(quit_button.setText, "window.close")
        quit_button.clicked.connect(lambda: self._quit_app())
        footer.addWidget(quit_button)
        layout.addLayout(footer)

        service.settings_changed.connect(self._sync)
        service.status_changed.connect(self._on_status)
        self._sync()
        self._on_status(service.status)

    def _build_steam_notice(self) -> QFrame:
        self._steam_notice = QFrame()
        self._steam_notice.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(self._steam_notice)
        text = QLabel()
        i18n.bind(text.setText, "window.steam_notice")
        text.setWordWrap(True)
        layout.addWidget(text, 1)
        help_button = QPushButton()
        i18n.bind(help_button.setText, "window.how_to_fix")
        help_button.clicked.connect(lambda: show_steam_help(self._service, self))
        layout.addWidget(help_button)
        self._service.steam_changed.connect(self._sync_steam)
        self._service.controllers_changed.connect(self._sync_steam)
        self._sync_steam()
        return self._steam_notice

    def _build_bluetooth_notice(self) -> QFrame:
        self._bluetooth_notice = QFrame()
        self._bluetooth_notice.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(self._bluetooth_notice)
        text = QLabel()
        i18n.bind(text.setText, "window.bluetooth_notice")
        text.setWordWrap(True)
        layout.addWidget(text, 1)
        help_button = QPushButton()
        i18n.bind(help_button.setText, "window.how_to_fix")
        help_button.clicked.connect(lambda: show_bluetooth_help(self._service, self))
        layout.addWidget(help_button)
        self._service.bluetooth_changed.connect(self._sync_bluetooth)
        self._sync_bluetooth()
        return self._bluetooth_notice

    def _sync_bluetooth(self) -> None:
        self._bluetooth_notice.setVisible(bool(self._service.unregistered_bluetooth))

    def _sync_steam(self) -> None:
        self._steam_notice.setVisible(self._service.steam_controls_selected)

    def _build_permission_banner(self) -> QFrame:
        self._banner = QFrame()
        self._banner.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(self._banner)
        texts = QVBoxLayout()
        explanation = QLabel()
        i18n.bind(explanation.setText, "window.permission_banner")
        explanation.setWordWrap(True)
        texts.addWidget(explanation)
        self._banner_detail = QLabel()
        self._banner_detail.setWordWrap(True)
        self._banner_detail.setEnabled(False)
        self._banner_detail.hide()
        texts.addWidget(self._banner_detail)
        layout.addLayout(texts, 1)
        self._grant_button = QPushButton()
        self._waiting_for_password = False
        self._update_grant_button()
        i18n.hub.changed.connect(self._update_grant_button)
        self._grant_button.clicked.connect(self._request_permission)
        layout.addWidget(self._grant_button)
        return self._banner

    def _build_light_group(self) -> QGroupBox:
        group = QGroupBox()
        i18n.bind(group.setTitle, "window.light")
        layout = QVBoxLayout(group)

        color_row = QHBoxLayout()
        self._swatch = QFrame()
        self._swatch.setFixedSize(56, 32)
        self._color_label = QLabel()
        choose = QPushButton()
        i18n.bind(choose.setText, "window.choose_color")
        choose.clicked.connect(lambda: pick_color(self._service, self))
        color_row.addWidget(self._swatch)
        color_row.addWidget(self._color_label, 1)
        color_row.addWidget(choose)
        layout.addLayout(color_row)

        layout.addWidget(ColorPalette(self._service))
        layout.addWidget(ColorSliders(self._service))
        return group

    def _build_players_group(self) -> QGroupBox:
        group = QGroupBox()
        i18n.bind(group.setTitle, "window.leds")
        layout = QVBoxLayout(group)
        layout.addWidget(PlayerRow(self._service))
        layout.addWidget(MuteLedRow(self._service))
        layout.addWidget(DisconnectRow(self._service))
        return group

    def _on_status(self, text: str) -> None:
        self._status.setText(text)
        needs_permission = self._service.needs_permission
        self._banner.setVisible(needs_permission)
        if not needs_permission:
            self._asked_permission = False
        elif not self._asked_permission:
            self._asked_permission = True
            QTimer.singleShot(0, self._offer_permission)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._tray_available and self._service.close_to_tray:
            # Só esconde: o app continua na bandeja.
            event.ignore()
            self.hide()
            self.hidden_to_tray.emit()
            return
        super().closeEvent(event)
        # Com a bandeja, fechar a última janela não encerra o app sozinho; aqui a escolha é sair.
        self._quit_app()

    def show_logs(self) -> None:
        if self._log_window is None:
            self._log_window = LogWindow(self)
        self._log_window.show()
        self._log_window.raise_()
        self._log_window.activateWindow()

    def show_profiles(self) -> None:
        if self._profiles_dialog is None:
            self._profiles_dialog = ProfilesDialog(self._service)
        self._profiles_dialog.show()
        self._profiles_dialog.raise_()
        self._profiles_dialog.activateWindow()

    def show_test(self) -> None:
        if self._test_window is None:
            self._test_window = TestWindow(self._service)
        self._test_window.show()
        self._test_window.raise_()
        self._test_window.activateWindow()

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _offer_permission(self) -> None:
        if not self._service.needs_permission or self._installer.running:
            return
        self.show_window()
        answer = QMessageBox.question(self, tr("window.permission_title"), tr("window.permission_text"))
        if answer == QMessageBox.StandardButton.Yes:
            self._request_permission()

    def _request_permission(self) -> None:
        if self._installer.running:
            return
        self._grant_button.setEnabled(False)
        self._waiting_for_password = True
        self._update_grant_button()
        self._installer.start()

    def _update_grant_button(self) -> None:
        self._grant_button.setText(tr("window.waiting_password" if self._waiting_for_password else "window.grant"))

    def _on_installed(self, ok: bool, message: str) -> None:
        self._grant_button.setEnabled(True)
        self._waiting_for_password = False
        self._update_grant_button()
        self._banner_detail.setText(message)
        self._banner_detail.setVisible(not ok)
        if ok:
            self._service.retry()

    def _sync(self) -> None:
        settings = self._service.settings
        red, green, blue = settings.color
        self._swatch.setStyleSheet(
            f"background-color: rgb({red}, {green}, {blue});"
            "border: 1px solid palette(mid); border-radius: 6px;"
        )
        self._color_label.setText(f"#{red:02X}{green:02X}{blue:02X}")
