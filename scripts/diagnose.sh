#!/bin/sh
# Mostra, de uma vez, o que o sistema e o app enxergam do DualSense. Rode quando o controle
# "conectar mas não aparecer", e mande a saída (ou cole no chat) para achar a causa.
cd "$(dirname "$0")/.." || exit 1

echo "== kernel e boot"
uname -r
uptime -s

echo
echo "== Bluetooth: conectados e pareados"
bluetoothctl devices Connected
bluetoothctl devices Paired | grep -i -E "dualsense|wireless controller"

echo
echo "== o sistema registrou os controles? (precisa aparecer um 0005 para cada Bluetooth)"
ls /sys/bus/hid/devices | grep -i 054C || echo "(nenhum controle registrado)"

echo
echo "== LEDs que o kernel criou (6 por controle)"
ls /sys/class/leds | grep -E "input[0-9]+:(rgb|white)" | sed 's/:.*//' | sort | uniq -c

echo
echo "== o app enxerga?"
.venv/bin/python -c "
from dualsense_led.sysfs import find_controllers
cs = find_controllers()
print(len(cs), 'controle(s)')
for c in cs: print(' ', c.name, c.connection, c.uid, c.hidraw)
" 2>/dev/null

echo
echo "== quem está com o controle aberto (Steam, outro programa)"
for h in /dev/hidraw*; do
    for p in /proc/[0-9]*; do
        ls -l "$p/fd" 2>/dev/null | grep -q -- "$h\$" && echo "$h <- $(tr '\0' ' ' < "$p/cmdline" | cut -c1-80)"
    done
done 2>/dev/null

echo
echo "== emulação de Xbox 360: /dev/uinput, serviço e daemon"
ls -l /dev/uinput 2>/dev/null || echo "(sem /dev/uinput: rode 'sudo modprobe uinput')"
if [ -r /dev/uinput ] && [ -w /dev/uinput ]; then echo "acesso ao uinput: ok"; else echo "acesso ao uinput: SEM permissão (grupo input?)"; fi
id -nG | tr ' ' '\n' | grep -qx input && echo "usuário no grupo input: sim" || echo "usuário no grupo input: não"
systemctl --user is-active dualsense-led-emulator.service 2>/dev/null | sed 's/^/serviço dualsense-led-emulator: /'
pgrep -af "[d]ualsense_led.emulator" | cut -c1-120 || echo "(nenhum daemon da emulação rodando)"
echo "Xbox virtuais:"
grep -B1 -A4 "X-Box 360" /proc/bus/input/devices 2>/dev/null | grep -E "Name=|Handlers=" || echo "  (nenhum)"
echo "DualSense físico (o grab não aparece aqui; confira com evtest, que deve dar \"Device or resource busy\"):"
grep -A5 "Name=\"\(DualSense\|Wireless Controller\)" /proc/bus/input/devices 2>/dev/null | grep -E "Name=|Handlers=" || echo "  (nenhum)"

echo
echo "== Bluetooth/kernel: últimos eventos dos controles"
journalctl -b --no-pager 2>/dev/null | grep -i -E "bluetoothd|playstation|uhid|hidp" \
    | grep -v -i -E "JBL|a2dp|QCY|sep[0-9]" | tail -15 | cut -c1-190

echo
echo "== log do app (avisos e erros de hoje)"
grep -E "WARNING|ERROR|CRITICAL" "${XDG_STATE_HOME:-$HOME/.local/state}/dualsense-led/dualsense-led.log" 2>/dev/null | tail -10 | cut -c1-170
