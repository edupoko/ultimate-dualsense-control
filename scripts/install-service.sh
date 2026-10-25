#!/bin/sh
# Instala (ou remove, com --remove) o serviço de usuário que roda a emulação de Xbox 360 no login,
# sem precisar abrir o app. Quem decide quais controles são emulados é o settings.json do app.
set -eu

PROJECT_DIR=$(cd "$(dirname "$0")/.." && pwd)
UNIT=dualsense-led-emulator.service
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
PYTHON="$PROJECT_DIR/.venv/bin/python"

if [ "${1:-}" = "--remove" ]; then
    systemctl --user disable --now "$UNIT" 2>/dev/null || true
    rm -f "$UNIT_DIR/$UNIT"
    systemctl --user daemon-reload
    echo "Serviço removido."
    exit 0
fi

if [ ! -x "$PYTHON" ]; then
    uv sync --project "$PROJECT_DIR"
fi

mkdir -p "$UNIT_DIR"
sed -e "s|@PROJECT_DIR@|$PROJECT_DIR|g" -e "s|@PYTHON@|$PYTHON|g" \
    "$PROJECT_DIR/src/dualsense_led/data/$UNIT" > "$UNIT_DIR/$UNIT"
systemctl --user daemon-reload
systemctl --user enable --now "$UNIT"
echo "Serviço instalado em $UNIT_DIR/$UNIT e ligado."
echo "Marque os controles a emular no app (interruptor 'Emular Xbox 360'); o serviço relê a escolha sozinho."
