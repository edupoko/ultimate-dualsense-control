"""Mede o custo do ControllerView (fora da tela): CPU e memória de 300 quadros pintados e de 300
leituras iguais em repouso, como a aba Entradas faz a cada 16 ms.

Uso: QT_QPA_PLATFORM=offscreen PYTHONPATH=<pasta src> uv run python scripts/measure_controller_view.py
"""

from __future__ import annotations

import resource
import time

from PySide6.QtWidgets import QApplication

from dualsense_ultimate_control.ds5.reports import InputState, Touch
from dualsense_ultimate_control.testpanel.widgets import ControllerView

FRAMES = 300


def state(i: int) -> InputState:
    return InputState(
        connection="USB", sequence=i, lx=128 + i % 60, ly=128, rx=128, ry=128 - i % 40, l2=i % 256, r2=0, dpad=None,
        buttons=frozenset({"cross"} if i % 2 else set()), gyro=(0, 0, 0), accel=(0, 0, 0), sensor_time=i,
        touches=(Touch(1, 100 + i, 200), None), battery_percent=50, battery_status="full",
    )


def main() -> None:
    app = QApplication([])  # noqa: F841
    view = ControllerView()
    view.resize(660, 500)
    view.show()
    view.grab()
    start = time.process_time()
    for i in range(FRAMES):
        view.set_state(state(i))
        view.grab()
    moving = time.process_time() - start
    rest = state(0)
    painted = 0
    original = view.paintEvent

    def counting(event):
        nonlocal painted
        painted += 1
        original(event)

    view.paintEvent = counting
    start = time.process_time()
    for _ in range(FRAMES):
        view.set_state(rest)
        app.processEvents()
    idle = time.process_time() - start
    print(f"{FRAMES} quadros mudando: {moving:.3f} s de CPU ({moving / FRAMES * 1000:.2f} ms/quadro)")
    print(f"{FRAMES} leituras iguais em repouso: {idle:.3f} s de CPU, {painted} repinturas")
    print(f"memória máxima: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB")


if __name__ == "__main__":
    main()
