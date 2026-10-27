"""Gera icons/controller-outline.svg: contorno do DualSense de frente, uma peça por id.

Uso: uv run python scripts/controller_outline.py [saida.png]
Com um caminho .png, também renderiza o resultado (fundo claro e escuro) para conferir.

Cores que o app troca em tempo de execução (F3.2):
  OUTER  linhas claras: corpo, costuras, moldura do touchpad e anel dos analógicos
  INNER  traço das peças (mais escuro que OUTER)
  BASE   fundo das peças; acender uma peça = trocar BASE pela cor de destaque
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src/dualsense_ultimate_control/icons/controller-outline.svg"
W, H = 529, 403
CX = W / 2
OUTER, INNER, BASE = "#f4f6f8", "#b9bfc7", "#2b3238"
K = 0.5523  # controle de arco em cúbica

Point = tuple[float, float]
Seg = tuple[Point, Point, Point, Point]


def mirror(p: Point) -> Point:
    return (W - p[0], p[1])


def mirrored(segs: list[Seg]) -> list[Seg]:
    """Espelha e inverte o sentido, para emendar com o original."""
    return [(mirror(p3), mirror(c2), mirror(c1), mirror(p0)) for p0, c1, c2, p3 in reversed(segs)]


def line(a: Point, b: Point) -> Seg:
    return (a, (a[0] + (b[0] - a[0]) / 3, a[1] + (b[1] - a[1]) / 3), (a[0] + 2 * (b[0] - a[0]) / 3, a[1] + 2 * (b[1] - a[1]) / 3), b)


def rounded(points: list[Point], r: float | list[float]) -> list[Seg]:
    """Polígono fechado com cantos arredondados."""
    n = len(points)
    radii = r if isinstance(r, list) else [r] * n
    corners = []
    for i, v in enumerate(points):
        prev, nxt = points[i - 1], points[(i + 1) % n]
        d1, d2 = math.dist(v, prev), math.dist(v, nxt)
        t = min(radii[i], d1 / 2, d2 / 2)
        a = (v[0] + (prev[0] - v[0]) * t / d1, v[1] + (prev[1] - v[1]) * t / d1)
        b = (v[0] + (nxt[0] - v[0]) * t / d2, v[1] + (nxt[1] - v[1]) * t / d2)
        corners.append((a, v, b))
    segs: list[Seg] = []
    for i, (a, v, b) in enumerate(corners):
        segs.append((a, (a[0] + (v[0] - a[0]) * K, a[1] + (v[1] - a[1]) * K), (b[0] + (v[0] - b[0]) * K, b[1] + (v[1] - b[1]) * K), b))
        segs.append(line(b, corners[(i + 1) % n][0]))
    return [s for s in segs if math.dist(s[0], s[3]) > 1e-6]


def rotated(points: list[Point], center: Point, degrees: float) -> list[Point]:
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [(center[0] + x * c - y * s, center[1] + x * s + y * c) for x, y in points]


def fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def d_attr(segs: list[Seg], closed: bool = True) -> str:
    parts = [f"M{fmt(segs[0][0][0])} {fmt(segs[0][0][1])}"]
    for _, c1, c2, p3 in segs:
        parts.append("C" + " ".join(fmt(v) for v in (*c1, *c2, *p3)))
    return "".join(parts) + ("Z" if closed else "")


def stroke(color: str, width: float) -> str:
    return f'stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"'


def light(segs: list[Seg], closed: bool = True) -> str:
    return f'<path d="{d_attr(segs, closed)}" fill="none" {stroke(OUTER, 2.8)}/>'


def part(segs: list[Seg]) -> str:
    return f'<path d="{d_attr(segs)}" fill="{BASE}" {stroke(INNER, 2.6)}/>'


def part_circle(x: float, y: float, r: float) -> str:
    return f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="{fmt(r)}" fill="{BASE}" {stroke(INNER, 2.6)}/>'


def body() -> str:
    left: list[Seg] = [
        ((CX, 81), (220, 80), (185, 82), (160, 86)),
        line((160, 86), (80, 97)),  # linha do ombro, sob o L1
        ((80, 97), (72, 98), (68, 103), (65, 110)),
        ((66, 110), (51, 150), (37, 210), (31, 260)),
        ((31, 260), (27, 300), (26, 340), (34, 362)),
        ((34, 362), (40, 376), (50, 378), (60, 378)),
        ((60, 378), (68, 380), (78, 388), (86, 385)),
        ((86, 385), (92, 382), (93, 378), (95, 372)),
        ((95, 372), (108, 340), (122, 300), (135, 282)),
        ((135, 282), (142, 273), (150, 271), (160, 271)),
        ((160, 271), (200, 272), (240, 274), (CX, 274)),
    ]
    # Costura entre a empunhadura e o miolo: desce rente ao touchpad e vai até a base da empunhadura.
    seam: list[Seg] = [
        ((150, 88), (155, 115), (161, 145), (166, 169)),
        ((166, 169), (158, 180), (148, 190), (140, 200)),
        ((140, 200), (122, 228), (103, 268), (92, 300)),
        ((92, 300), (84, 328), (74, 355), (60, 378)),
    ]
    return light(left + mirrored(left)) + light(seam, closed=False) + light(mirrored(seam), closed=False)


def build() -> str:
    pieces: list[tuple[str, str]] = [("body", body())]

    # Gatilhos (abas altas) e ombros (arco sobre a linha do ombro).
    l2 = rounded([(81, 69), (95, 11), (129, 8), (138, 62)], [4, 17, 17, 4])
    l1: list[Seg] = [((79, 95), (86, 80), (112, 73), (133, 75)), ((133, 75), (143, 76), (146, 82), (147, 87)), line((147, 87), (79, 95))]
    for name, segs in (("l2", l2), ("l1", l1)):
        pieces.append((name, part(segs)))
        pieces.append(("r" + name[1], part(mirrored(segs))))

    # Touchpad: moldura clara aberta (o topo é o próprio corpo) e o painel por dentro.
    frame: list[Seg] = [
        ((158, 88), (162, 120), (166, 150), (169, 168)),
        ((169, 168), (172, 180), (182, 186), (196, 186)),
        line((196, 186), mirror((196, 186))),
    ]
    frame += mirrored(frame[:2])
    pad = rounded([(162, 90), (W - 162, 90), (W - 174, 179), (174, 179)], [8, 8, 16, 16])
    pieces.append(("touchpad", light(frame, closed=False) + part(pad)))

    # 5 LEDs de jogador sob o touchpad.
    for i in range(5):
        x = CX + (i - 2) * 9
        pieces.append((f"led_{i + 1}", f'<circle cx="{fmt(x)}" cy="194.5" r="2.1" fill="{BASE}" {stroke(OUTER, 2.6)}/>'))

    # Create e Options: pílulas inclinadas ao lado do touchpad.
    create = rounded(rotated([(-4, -9), (4, -9), (4, 9), (-4, 9)], (144, 114), 12), 4)
    pieces += [("create", part(create)), ("options", part(mirrored(create)))]

    # Direcional: 4 pétalas com a ponta para o centro.
    arm = [(-13, -36), (13, -36), (12, -20), (0, -7), (-12, -20)]
    for name, ang in (("dpad_up", 0), ("dpad_right", 90), ("dpad_down", 180), ("dpad_left", 270)):
        pieces.append((name, part(rounded(rotated(arm, (108, 161), ang), [7, 7, 8, 4, 8]))))

    # Botões de rosto.
    fx, fy = W - 107, 160
    for name, (x, y) in {"triangle": (fx, fy - 31), "circle": (fx + 32, fy), "cross": (fx, fy + 31), "square": (fx - 32, fy)}.items():
        pieces.append((name, part_circle(x, y, 15)))

    # Analógicos: anel claro e a tampa por dentro (o ponto da posição fica por conta do app).
    for name, x in (("l3", 180), ("r3", W - 180)):
        ring = f'<circle cx="{fmt(x)}" cy="224" r="32" fill="none" {stroke(OUTER, 2.8)}/>'
        pieces.append((name, ring + part_circle(x, 224, 23)))

    # PS entre os analógicos e Mute logo abaixo.
    pieces.append(("ps", part_circle(CX, 224, 12.5)))
    pieces.append(("mute", part(rounded([(CX - 13, 250), (CX + 13, 250), (CX + 13, 257), (CX - 13, 257)], 3.5))))

    groups = "\n".join(f'<g id="{name}">{content}</g>' for name, content in pieces)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">\n'
        "<!-- Gerado por scripts/controller_outline.py; editar lá. -->\n"
        f"{groups}\n</svg>\n"
    )


def main() -> None:
    OUT.write_text(build())
    print(f"{OUT} ({OUT.stat().st_size} bytes)")
    if len(sys.argv) > 1:
        from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer

        app = QGuiApplication([])  # noqa: F841
        renderer = QSvgRenderer(str(OUT))
        for bg, suffix in (("#ffffff", "light"), ("#202327", "dark")):
            image = QImage(W, H, QImage.Format.Format_ARGB32)
            image.fill(QColor(bg))
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter)
            painter.end()
            path = Path(sys.argv[1]).with_stem(Path(sys.argv[1]).stem + "-" + suffix)
            image.save(str(path))
            print(path)


if __name__ == "__main__":
    main()
