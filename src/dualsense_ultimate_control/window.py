"""Janela principal com todos os controles dos LEDs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import i18n
from .i18n import tr
from .confirm import ConfirmBar
from .emulation import EmulationProcess
from .logview import LogWindow
from .permissions import RuleInstaller
from .profile_picker import ProfilePicker
from .profiles_dialog import ProfilesDialog
from .service import LedService
from . import theme
from .responsive import Columns, stack
from .theme import SideNav, section
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
    ThemeRow,
    LogsRow,
    MuteLedRow,
    PlayerRow,
    bluetooth_help_panel,
    steam_help_panel,
)

ICON_PATH = Path(__file__).with_name("icons") / "dualsense-ultimate-control.svg"

# Título de cada página na lista lateral.
PAGE_TITLES = {"controls": "nav.controls", "test": "test.title", "profiles": "profiles.title", "logs": "log.title", "settings": "nav.settings"}
# Páginas que rolam inteiras; as outras cuidam da própria rolagem (uma barra por página, nunca aninhada).
SCROLLED_PAGES = ("controls", "settings")


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
        self._installer = installer or RuleInstaller()
        self._installer.finished.connect(self._on_installed)
        # Pergunta automaticamente só uma vez a cada perda de permissão; depois fica o botão.
        self._asked_permission = False
        self.setWindowTitle("DualSense Ultimate Control")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(*theme.WINDOW_MIN_SIZE)
        self.resize(*theme.WINDOW_DEFAULT_SIZE)

        # Tudo abre dentro desta janela: a lista à esquerda troca a página da direita.
        root = QHBoxLayout(self)
        self._nav = SideNav()
        self._nav.setFixedWidth(theme.NAV_WIDTH)
        root.addWidget(self._nav)
        column = QVBoxLayout()
        root.addLayout(column, 1)
        # Perguntas e avisos de qualquer página (ex.: permissão) aparecem aqui, sem caixa de diálogo.
        self._bar = ConfirmBar()
        column.addWidget(self._bar)
        self._stack = QStackedWidget()
        column.addWidget(self._stack, 1)

        # Páginas criadas só na primeira visita; a ordem é a da lista.
        self._page_keys = ["controls", "test"] + (["profiles"] if emulation is not None else []) + ["logs", "settings"]
        self._pages: dict[str, QWidget] = {}
        self._holders: dict[str, QWidget] = {}  # o que o stack mostra: a página ou a área que a rola
        self._current: str | None = None
        self._help_slots: dict[str, QVBoxLayout] = {}
        for key in self._page_keys:
            item = self._nav.add_page(key)
            i18n.bind(lambda text, item=item: item.setText(text), PAGE_TITLES[key])
        self._nav.currentRowChanged.connect(self._on_nav)

        controls = QWidget()
        layout = QVBoxLayout(controls)

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
        # Janela larga: luz à esquerda; LEDs, emulação e perfil à direita.
        right = [self._build_players_group()]
        if emulation is not None:
            right += [EmulationRow(service, emulation), ProfilePicker(service)]
        right_column = stack(*right, QWidget(), stretch=(0,) * len(right) + (1,))
        self._columns = Columns(stack(self._build_light_group(), QWidget(), stretch=(0, 1)), right_column)
        layout.addWidget(self._columns)

        layout.addStretch(1)
        self._add_page("controls", controls)
        self.set_page("controls")

        footer = QHBoxLayout()
        footer.addStretch(1)
        self._quit_button = QPushButton()
        # Passa pelo closeEvent: esconde na bandeja ou sai, conforme a opção.
        self._quit_button.clicked.connect(self.close)
        footer.addWidget(self._quit_button)
        column.addLayout(footer)

        service.settings_changed.connect(self._sync_quit_label)
        i18n.hub.changed.connect(self._sync_quit_label)
        self._sync_quit_label()
        service.settings_changed.connect(self._sync)
        service.status_changed.connect(self._on_status)
        self._sync()
        self._on_status(service.status)
        self._restore_geometry()

    # --- tamanho lembrado (F5.4)

    def _restore_geometry(self) -> None:
        """Volta ao tamanho e posição da última vez, sem passar do mínimo nem da tela disponível."""
        saved, maximized = self._service.window_geometry
        if saved:
            x, y, width, height = saved
            screen = QGuiApplication.screenAt(QPoint(x + width // 2, y + height // 2))
            area = (screen or QGuiApplication.primaryScreen()).availableGeometry()
            width = max(self.minimumWidth(), min(width, area.width()))
            height = max(self.minimumHeight(), min(height, area.height()))
            if screen is not None:  # a tela onde ela estava ainda existe: mantém a posição, dentro dela
                x = min(max(x, area.left()), area.right() - width + 1)
                y = min(max(y, area.top()), area.bottom() - height + 1)
                self.setGeometry(QRect(x, y, width, height))
            else:
                self.resize(width, height)
        if maximized:
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def _save_geometry(self) -> None:
        maximized = self.isMaximized()
        rect = self.normalGeometry() if maximized else self.geometry()
        if rect.isValid():
            self._service.set_window_geometry([rect.x(), rect.y(), rect.width(), rect.height()], maximized)

    def hideEvent(self, event) -> None:
        # Chega ao ir para a bandeja e ao sair do app (que esconde as janelas antes de encerrar).
        self._save_geometry()
        super().hideEvent(event)

    def _build_notice(self, text_key: str, kind: str) -> tuple[QFrame, QWidget]:
        """Aviso com "Como resolver…"; a explicação abre logo abaixo dele, dentro da página."""
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(frame)
        text = QLabel()
        i18n.bind(text.setText, text_key)
        text.setWordWrap(True)
        layout.addWidget(text, 1)
        help_button = QPushButton()
        i18n.bind(help_button.setText, "window.how_to_fix")
        help_button.clicked.connect(lambda: self._open_help(kind))
        layout.addWidget(help_button)
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addWidget(frame)
        slot = QVBoxLayout()
        holder_layout.addLayout(slot)
        self._help_slots[kind] = slot
        return frame, holder

    def _build_steam_notice(self) -> QWidget:
        self._steam_notice, holder = self._build_notice("window.steam_notice", "steam")
        self._service.steam_changed.connect(self._sync_steam)
        self._service.controllers_changed.connect(self._sync_steam)
        self._sync_steam()
        return holder

    def _build_bluetooth_notice(self) -> QWidget:
        self._bluetooth_notice, holder = self._build_notice("window.bluetooth_notice", "bluetooth")
        self._service.bluetooth_changed.connect(self._sync_bluetooth)
        self._sync_bluetooth()
        return holder

    def _close_help(self, kind: str) -> None:
        slot = self._help_slots[kind]
        while slot.count():
            item = slot.takeAt(0)
            if item.widget() is not None:
                item.widget().close_panel()

    def _open_help(self, kind: str) -> None:
        self._close_help(kind)
        panel = steam_help_panel(self._service) if kind == "steam" else bluetooth_help_panel(self._service)
        self._help_slots[kind].addWidget(panel)

    def show_help(self, kind: str) -> None:
        """Abre a explicação da Steam ou do Bluetooth na página dos controles (usado pela bandeja)."""
        self.show_window()
        if self.set_page("controls"):
            self._open_help(kind)

    def show_notice(self, text: str) -> None:
        self.show_window()
        self._bar.notify(text)

    def _sync_bluetooth(self) -> None:
        visible = bool(self._service.unregistered_bluetooth)
        self._bluetooth_notice.setVisible(visible)
        if not visible:
            self._close_help("bluetooth")

    def _sync_steam(self) -> None:
        visible = self._service.steam_controls_selected
        self._steam_notice.setVisible(visible)
        if not visible:
            self._close_help("steam")

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

    def _build_light_group(self) -> QWidget:
        group, layout = section("window.light")

        color_row = QHBoxLayout()
        self._swatch = QFrame()
        self._swatch.setFixedSize(56, 32)
        self._color_label = QLabel()
        color_row.addWidget(self._swatch)
        color_row.addWidget(self._color_label, 1)
        layout.addLayout(color_row)

        layout.addWidget(ColorPalette(self._service))
        layout.addWidget(ColorSliders(self._service))
        return group

    def _build_players_group(self) -> QWidget:
        group, layout = section("window.leds")
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

    def _stays_in_tray(self) -> bool:
        return self._tray_available and self._service.close_to_tray

    def _sync_quit_label(self) -> None:
        self._quit_button.setText(i18n.tr("window.close" if self._stays_in_tray() else "window.quit"))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._stays_in_tray():
            # Só esconde: o app continua na bandeja.
            event.ignore()
            self.hide()
            self.hidden_to_tray.emit()
            return
        super().closeEvent(event)
        # Com a bandeja, fechar a última janela não encerra o app sozinho; aqui a escolha é sair.
        self._quit_app()

    def show_logs(self) -> None:
        self.set_page("logs")
        self.show_window()

    def show_profiles(self) -> None:
        self.set_page("profiles")
        self.show_window()

    def show_test(self) -> None:
        self.set_page("test")
        self.show_window()

    def current_page(self) -> str:
        return self._current

    def page(self, key: str) -> QWidget | None:
        return self._pages.get(key)

    def set_page(self, key: str, force: bool = False) -> bool:
        """Mostra a página `key`; devolve False se a página atual recusou a saída.

        `force` pula a pergunta da página atual (ela mesma já perguntou ao ser fechada)."""
        if key not in self._page_keys:
            return False
        if not force and self._current not in (None, key) and not self._can_leave(self._current, key):
            self._select_nav(self._current)
            return False
        if key not in self._pages:
            self._add_page(key, self._create_page(key))
        self._current = key
        self._pages[key].show()  # o "Fechar" da própria página pode tê-la escondido
        self._stack.setCurrentWidget(self._holders[key])
        self._select_nav(key)
        return True

    def _select_nav(self, key: str) -> None:
        self._nav.blockSignals(True)
        self._nav.setCurrentRow(self._page_keys.index(key))
        self._nav.blockSignals(False)

    def _build_settings_page(self) -> QWidget:
        """Opções de funcionamento do app (o antigo grupo "Geral" da página Controles)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        general, general_layout = section("window.general")
        general_layout.addWidget(LanguageRow(self._service))
        general_layout.addWidget(ThemeRow(self._service))
        general_layout.addWidget(AutostartRow())
        general_layout.addWidget(AutoPlayersRow(self._service))
        close_to_tray = CloseToTrayRow(self._service)
        # Sem bandeja não há para onde mandar o app: fechar sempre encerra.
        close_to_tray.setEnabled(self._tray_available)
        general_layout.addWidget(close_to_tray)
        general_layout.addWidget(LogsRow(self.show_logs))
        layout.addWidget(general)
        layout.addStretch(1)
        return page

    def _create_page(self, key: str) -> QWidget:
        if key == "settings":
            return self._build_settings_page()
        if key == "test":
            return TestWindow(self._service)
        if key == "profiles":
            page = ProfilesDialog(self._service)
        else:
            page = LogWindow()
        # O "Voltar" desses painéis só leva de volta à página dos controles.
        page.back_requested.connect(lambda: self.set_page("controls", force=True))
        return page

    def _add_page(self, key: str, page: QWidget) -> None:
        page.setWindowFlags(Qt.WindowType.Widget)  # deixa de ser janela própria
        holder = page
        if key in SCROLLED_PAGES:
            holder = QScrollArea()
            holder.setWidgetResizable(True)
            holder.setFrameShape(QFrame.Shape.NoFrame)
            holder.setWidget(page)
        self._pages[key] = page
        self._holders[key] = holder
        self._stack.addWidget(holder)

    def _can_leave(self, key: str, target: str) -> bool:
        """Se a página tem edição pendente, ela pergunta (na própria página) e segue para `target` se o usuário aceitar."""
        page = self._pages.get(key)
        if isinstance(page, ProfilesDialog):
            return page.can_leave(lambda: self.set_page(target, force=True))
        return True

    def _on_nav(self, row: int) -> None:
        # Se a página atual recusar a saída, set_page devolve a seleção para ela.
        if row >= 0:
            self.set_page(self._page_keys[row])

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _offer_permission(self) -> None:
        if not self._service.needs_permission or self._installer.running:
            return
        self.show_window()
        self._bar.ask(tr("window.permission_text"), self._accept_permission)

    def _accept_permission(self) -> None:
        if self._service.needs_permission:  # pode ter sido liberada pelo botão do aviso enquanto a pergunta esperava
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
