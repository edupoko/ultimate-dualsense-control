"""Ponto de entrada: python -m dualsense_ultimate_control [--tray]"""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import gc
import logging
import os
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

import shiboken6
from PySide6.QtCore import QCoreApplication, QThread, QTimer, qVersion
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import __version__, kdetheme, logs, theme
from .emulation import EmulationProcess
from .i18n import tr
from .migrate import migrate_legacy
from .service import LedService
from .settings import default_settings_path, load_settings
from .tray import TrayIcon
from .window import MainWindow, app_icon

# Uma única instância: a trava de arquivo decide quem é a instância principal (sem corrida
# entre dois inícios simultâneos), e o socket local é como as outras pedem para ela mostrar
# a janela. DUALSENSE_ULTIMATE_INSTANCE troca o nome, para testes não esbarrarem no app aberto.
INSTANCE_NAME = os.environ.get("DUALSENSE_ULTIMATE_INSTANCE", "dualsense-ultimate-control")
SERVER_NAME = INSTANCE_NAME
# Quanto esperar a instância principal criar o socket, caso ela ainda esteja iniciando.
SIGNAL_TIMEOUT_MS = 5000

# Mantido aberto enquanto o processo vive; o sistema libera a trava quando ele termina.
_instance_lock: int | None = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dualsense-ultimate-control", description="Controle dos LEDs do DualSense.")
    parser.add_argument("--tray", action="store_true", help="inicia só na bandeja, sem abrir a janela")
    parser.add_argument("--logs", action="store_true", help="mostra o caminho e o fim do arquivo de log e sai")
    parser.add_argument("--debug", action="store_true", help="registra também mensagens de depuração")
    parser.add_argument("--quit", action="store_true", help="pede para o app que já está aberto encerrar e sai")
    parser.add_argument("--emulate", action="store_true", help="roda só a emulação de Xbox 360 (sem interface) e sai com Ctrl+C")
    args, qt_args = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    migrate_legacy()
    if args.emulate:
        from .emulator.__main__ import run

        return run()
    if args.logs:
        return _print_logs()
    if args.quit:
        return _quit_running_instance()
    logs.setup_logging(logging.DEBUG if args.debug else logging.INFO)

    if not _acquire_instance_lock():
        # Outra instância já é a principal: só pede para ela mostrar a janela e sai.
        signaller = QCoreApplication([sys.argv[0]])
        if not _signal_running_instance(show=not args.tray, timeout_ms=SIGNAL_TIMEOUT_MS):
            logging.warning("O DualSense Ultimate Control já está em execução, mas não respondeu.")
        logging.info("O DualSense Ultimate Control já está aberto.")
        del signaller
        return 0

    # No Wayland o app não pode posicionar as próprias janelas nem sabe onde está o painel,
    # então o menu da bandeja não teria como abrir junto a ela. Pelo XWayland as duas coisas
    # funcionam. Definir QT_QPA_PLATFORM manualmente ignora esta escolha.
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "xcb"

    # Aparência do KDE (Breeze, cores e fontes do sistema) em vez do estilo genérico do Qt.
    theme_name = theme.detect(preference=load_settings(default_settings_path()).theme)
    kde_active = theme_name == "kde" and kdetheme.enable(qVersion())
    if kde_active:
        logging.info("Usando o tema do KDE.")

    app = QApplication([sys.argv[0], *qt_args])
    if theme.apply(app, kde_active, theme_name):
        logging.info("Usando o tema %s.", "do GNOME (visual Adwaita sobre o Fusion)" if theme.style() == "gnome" else "próprio (Fusion)")
    logging.info("Iniciando %s %s (Qt %s, plataforma %s)", "DualSense Ultimate Control", __version__, qVersion(), app.platformName())
    app.setApplicationName("DualSense Ultimate Control")
    app.setDesktopFileName("dualsense-ultimate-control")
    app.setWindowIcon(app_icon())

    # Uma versão antiga do app (sem a trava) pode estar aberta; nesse caso ela continua sendo a única.
    if _signal_running_instance(show=not args.tray, timeout_ms=300):
        logging.info("O DualSense Ultimate Control já está aberto.")
        return 0

    tray_available = QSystemTrayIcon.isSystemTrayAvailable()
    app.setQuitOnLastWindowClosed(not tray_available)

    service = LedService(default_settings_path())
    emulation = EmulationProcess()
    tray: TrayIcon | None = None

    def quit_app() -> None:
        """Encerra de vez: tudo some na hora (ícone, menu e janelas) e só então o app sai."""
        logging.info("Fechando o app")
        service.flush()
        emulation.stop()  # devolve os controles antes de sair
        if tray is not None:
            tray.hide()
        for widget in QApplication.topLevelWidgets():
            widget.hide()
        app.quit()

    # A janela só é montada quando é aberta pela primeira vez: quem usa só a bandeja (ex.: início
    # automático com --tray) não gasta memória com ela.
    window: MainWindow | None = None

    def ensure_window() -> MainWindow:
        nonlocal window
        if window is None:
            window = MainWindow(service, tray_available, quit_app=quit_app, emulation=emulation)
            if tray is not None:
                window.hidden_to_tray.connect(tray.notify_still_running)
        return window

    def show_window() -> None:
        ensure_window().show_window()

    def on_status(_text: str) -> None:
        # O pedido de permissão vive na janela: sem permissão, ela precisa existir para perguntar.
        if service.needs_permission and window is None:
            ensure_window()

    if tray_available:
        tray = TrayIcon(service, show_window, quit_app, emulation, show_help=lambda kind: ensure_window().show_help(kind))
        tray.show()
    else:
        logging.warning("Bandeja do sistema indisponível; usando só a janela.")

    def on_emulation_failed(detail: str) -> None:
        # Desliga a escolha salva: senão o mesmo erro voltaria a cada vez que o app abre.
        service.set_emulation(False)
        text = tr("emulation.failed", detail=detail)
        if window is not None and window.isVisible():
            window.show_notice(f"{tr('emulation.failed_title')}: {text}")
        elif tray is not None:
            tray.show_message(tr("emulation.failed_title"), text)

    emulation.failed.connect(on_emulation_failed)
    if service.emulation:
        emulation.start()
    service.status_changed.connect(on_status)
    server = _listen(show_window, quit_app)
    service.start()
    if not args.tray or tray is None:
        show_window()
    # Libera de volta ao sistema a memória que a inicialização usou e já não precisa.
    QTimer.singleShot(TRIM_DELAY_MS, _release_free_memory)
    exit_code = app.exec()
    logging.info("Encerrando (código %s)", exit_code)
    _arm_exit_watchdog(exit_code)
    emulation.stop()  # caso o app tenha saído por outro caminho que não o quit_app
    server.close()
    # Janelas primeiro (menu da bandeja e janela principal), depois os objetos de apoio.
    _destroy_qt_objects(tray.built_popup if tray else None, window, tray, server, emulation, service)
    logging.info("Janelas e objetos do Qt apagados")
    return exit_code


TRIM_DELAY_MS = 3000


def _release_free_memory() -> None:
    """Coleta o lixo do Python e devolve ao sistema as páginas livres do malloc (glibc)."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass  # outra libc: não faz mal pular


# Tempo máximo para o app terminar depois de "Fechar"/"Sair"; passado isso, o processo é forçado a acabar.
EXIT_TIMEOUT_SECONDS = 5


def _arm_exit_watchdog(exit_code: int, seconds: float = EXIT_TIMEOUT_SECONDS) -> threading.Timer:
    """Garante que o app termina de verdade: se a limpeza travar, encerra o processo à força."""

    def force_exit() -> None:
        logging.warning("O encerramento passou de %s s; forçando a saída do processo", seconds)
        logging.shutdown()
        os._exit(exit_code)

    timer = threading.Timer(seconds, force_exit)
    timer.daemon = True
    timer.start()
    return timer


def _quit_running_instance(wait_seconds: float = 10.0) -> int:
    """`dualsense-ultimate-control --quit`: pede à instância aberta que encerre e espera ela terminar."""
    signaller = QCoreApplication([sys.argv[0]])
    if _acquire_instance_lock():
        print("O DualSense Ultimate Control não está aberto.")
        return 0
    if not _signal_running_instance(command=b"quit", timeout_ms=SIGNAL_TIMEOUT_MS):
        print("O app está aberto, mas não respondeu ao pedido para encerrar.")
        return 1
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _acquire_instance_lock():  # a trava só fica livre quando o processo termina
            print("DualSense Ultimate Control encerrado.")
            del signaller
            return 0
        time.sleep(0.1)
    print(f"O app recebeu o pedido, mas continuou aberto depois de {wait_seconds:.0f} s.")
    return 1


def _print_logs(lines: int = 40) -> int:
    """`dualsense-ultimate-control --logs`: onde está o log e as últimas linhas, sem abrir a interface."""
    print(f"Log: {logs.log_path()}")
    print(f"Travamentos: {logs.crash_path()}")
    text = logs.read_log()
    if not text:
        print("(ainda não há registros)")
        return 0
    print()
    print("\n".join(text.splitlines()[-lines:]))
    return 0


def _destroy_qt_objects(*objects) -> None:
    """Apaga janelas e objetos do Qt enquanto o QApplication ainda existe.

    Os lambdas ligados aos sinais criam ciclos de referência, então esses objetos só seriam
    coletados na finalização do Python, depois do QApplication, e o app travava ao sair
    (segfault em QObject::~QObject). Apagar tudo aqui, na ordem certa, evita isso.
    """
    # Só objetos criados pelo app: janelas internas do Qt (dicas, menus de contexto) não
    # avisam o Python quando são apagadas, e apagá-las aqui também travaria.
    for obj in objects:
        if obj is not None and shiboken6.isValid(obj):
            shiboken6.delete(obj)
    gc.collect()



def _acquire_instance_lock() -> bool:
    """Tenta virar a instância principal; False se outra já é."""
    global _instance_lock
    folder = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
    descriptor = os.open(folder / f"{INSTANCE_NAME}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(descriptor)
        return False
    _instance_lock = descriptor
    return True


def _signal_running_instance(show: bool = True, timeout_ms: int = 0, command: bytes | None = None) -> bool:
    """Avisa a instância principal; tenta até ela criar o socket ou o tempo acabar."""
    command = command or (b"show" if show else None)
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        socket = QLocalSocket()
        socket.connectToServer(SERVER_NAME)
        if socket.waitForConnected(200):
            if command:
                socket.write(command + b"\n")
                socket.waitForBytesWritten(500)
            socket.disconnectFromServer()
            return True
        if time.monotonic() >= deadline:
            return False
        QThread.msleep(100)


def _listen(on_show: Callable[[], None], on_quit: Callable[[], None] | None = None) -> QLocalServer:
    server = QLocalServer()
    # Nenhuma instância respondeu: um socket que sobrou de um encerramento abrupto pode ser removido.
    QLocalServer.removeServer(SERVER_NAME)
    if not server.listen(SERVER_NAME):
        logging.warning("Não foi possível criar o socket de instância única: %s", server.errorString())

    def handle(socket: QLocalSocket) -> None:
        data = socket.readAll().data()
        if b"quit" in data and on_quit is not None:
            logging.info("Pedido para encerrar recebido (--quit)")
            on_quit()
        elif b"show" in data:
            on_show()

    def on_connection() -> None:
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: handle(s))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                handle(socket)

    server.newConnection.connect(on_connection)
    return server


if __name__ == "__main__":
    raise SystemExit(main())
