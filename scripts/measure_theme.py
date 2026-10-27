"""Mede o custo de um tema (fora da tela) e salva capturas da janela principal.

Abre a janela principal com os dados de um serviço vazio, aplica o tema escolhido (`own`, `gnome`),
percorre as páginas e imprime CPU e memória; salva um PNG por esquema de cor em --out.

Uso: QT_QPA_PLATFORM=offscreen PYTHONPATH=<pasta src> uv run python scripts/measure_theme.py gnome --out /tmp/capturas
"""

from __future__ import annotations

import argparse
import resource
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from dualsense_ultimate_control import theme
from dualsense_ultimate_control.service import LedService
from dualsense_ultimate_control.window import MainWindow


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", choices=theme.THEMES[1:], help="gnome ou own")
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()))
    args = parser.parse_args()

    app = QApplication([])
    theme.apply(app, kde_active=False, name=args.name)
    root = Path(tempfile.mkdtemp())
    service = LedService(root / "settings.json", root / "leds", bluetooth_probe=lambda known: [])
    start = time.process_time()
    window = MainWindow(service, tray_available=False, emulation=None)
    window.resize(900, 680)
    window.show()
    args.out.mkdir(parents=True, exist_ok=True)
    for scheme in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark):
        app.styleHints().setColorScheme(scheme)
        if app.styleHints().colorScheme() != scheme:  # o backend offscreen não troca o esquema: usa a paleta
            gnome = args.name == "gnome"
            tokens = {Qt.ColorScheme.Light: (theme.ADW_LIGHT if gnome else theme.LIGHT), Qt.ColorScheme.Dark: (theme.ADW_DARK if gnome else theme.DARK)}[scheme]
            app.setPalette(theme.build_palette(tokens, theme.accent_color(app, theme.ADW_ACCENT if gnome else None)))
        for page in ("controls", "settings"):
            window.set_page(page)
            app.processEvents()
            window.grab().save(str(args.out / f"{args.name}-{scheme.name.lower()}-{page}.png"))
    cpu = time.process_time() - start
    print(f"tema {args.name}: {cpu:.3f} s de CPU, memória máxima {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB")
    print(f"capturas em {args.out}")


if __name__ == "__main__":
    main()
