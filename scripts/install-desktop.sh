#!/bin/sh
# Adiciona o DualSense Ultimate Control ao menu de aplicativos do usuário (não precisa de root).
set -eu

PROJECT_DIR=$(cd "$(dirname "$0")/.." && pwd)
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS_DIR="$DATA_DIR/applications"
ICONS_DIR="$DATA_DIR/icons/hicolor/scalable/apps"
EXECUTABLE="$PROJECT_DIR/.venv/bin/dualsense-led"

if [ ! -x "$EXECUTABLE" ]; then
    uv sync --project "$PROJECT_DIR"
fi

mkdir -p "$APPS_DIR" "$ICONS_DIR"
cp "$PROJECT_DIR/src/dualsense_led/icons/dualsense-led.svg" "$ICONS_DIR/dualsense-led.svg"

cat > "$APPS_DIR/dualsense-led.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DualSense Ultimate Control
GenericName=Controle de LEDs do DualSense
Comment=Altere a cor da barra de luz e os LEDs de jogador do DualSense
Exec="$EXECUTABLE"
Icon=dualsense-led
Terminal=false
Categories=Settings;HardwareSettings;
Keywords=dualsense;ps5;playstation;controle;gamepad;led;
StartupNotify=true
EOF

update-desktop-database "$APPS_DIR" 2>/dev/null || true
kbuildsycoca6 >/dev/null 2>&1 || true

echo "Atalho instalado em $APPS_DIR/dualsense-led.desktop"
