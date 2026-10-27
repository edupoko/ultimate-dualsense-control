"""Gera icons/controller-outline.svg: contorno do DualSense em linha dupla, uma peça por id.

Uso: uv run python scripts/controller_outline.py [saida.png]
Com um caminho .png, também renderiza o resultado para conferir.

Cores que o app troca em tempo de execução (F3.2):
  OUTER  traço externo (mais claro)
  INNER  traço interno (mais escuro)
  FILL   preenchimento das peças acesas; no arquivo vai com fill-opacity="0"
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src/dualsense_ultimate_control/icons/controller-outline.svg"
W, H = 589, 414
CX = W / 2
OUTER, INNER, FILL = "#8ab4f8", "#1a5fd0", "#1a5fd0"
GAP = 4.0  # distância entre as duas linhas
K = 0.5523  # controle de arco de 90° em cúbica

Point = tuple[float, float]
Seg = tuple[Point, Point, Point, Point]


def mirror(p: Point) -> Point:
    return (W - p[0], p[1])


def line(a: Point, b: Point) -> Seg:
    return (a, (a[0] + (b[0] - a[0]) / 3, a[1] + (b[1] - a[1]) / 3), (a[0] + 2 * (b[0] - a[0]) / 3, a[1] + 2 * (b[1] - a[1]) / 3), b)


def rounded(points: list[Point], r: float | list[float]) -> list[Seg]:
    """Polígono fechado com cantos arredondados (tangentes contínuas)."""
    n = len(points)
    radii = r if isinstance(r, list) else [r] * n
    corners = []
    for i, v in enumerate(points):
        prev, nxt = points[i - 1], points[(i + 1) % n]
        d1 = math.dist(v, prev)
        d2 = math.dist(v, nxt)
        t = min(radii[i], d1 / 2, d2 / 2)
        a = (v[0] + (prev[0] - v[0]) * t / d1, v[1] + (prev[1] - v[1]) * t / d1)
        b = (v[0] + (nxt[0] - v[0]) * t / d2, v[1] + (nxt[1] - v[1]) * t / d2)
        corners.append((a, v, b))
    segs: list[Seg] = []
    for i, (a, v, b) in enumerate(corners):
        segs.append((a, (a[0] + (v[0] - a[0]) * K, a[1] + (v[1] - a[1]) * K), (b[0] + (v[0] - b[0]) * K, b[1] + (v[1] - b[1]) * K), b))
        segs.append(line(b, corners[(i + 1) % n][0]))
    return [s for s in segs if math.dist(s[0], s[3]) > 1e-6]


def area(segs: list[Seg]) -> float:
    return sum(s[0][0] * s[3][1] - s[3][0] * s[0][1] for s in segs) / 2


def _normal(a: Point, b: Point) -> Point:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    return (-dy / length, dx / length)


def inset(segs: list[Seg], d: float) -> list[Seg]:
    """Curva paralela por dentro (Tiller–Hanson: desloca cada ponto pela normal da ponta)."""
    sign = 1 if area(segs) > 0 else -1  # y para baixo: área positiva = sentido horário
    out = []
    for p0, c1, c2, p3 in segs:
        n0 = _normal(p0, c1 if math.dist(p0, c1) > 1e-6 else c2)
        n3 = _normal(c2 if math.dist(c2, p3) > 1e-6 else c1, p3)
        k = d * sign
        out.append(
            (
                (p0[0] + n0[0] * k, p0[1] + n0[1] * k),
                (c1[0] + n0[0] * k, c1[1] + n0[1] * k),
                (c2[0] + n3[0] * k, c2[1] + n3[1] * k),
                (p3[0] + n3[0] * k, p3[1] + n3[1] * k),
            )
        )
    return out


def fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def d_attr(segs: list[Seg]) -> str:
    parts = [f"M{fmt(segs[0][0][0])} {fmt(segs[0][0][1])}"]
    for _, c1, c2, p3 in segs:
        parts.append("C" + " ".join(fmt(v) for v in (*c1, *c2, *p3)))
    return "".join(parts) + "Z"


def double(segs: list[Seg], piece: bool = True, gap: float = GAP) -> str:
    fill = f'fill="{FILL}" fill-opacity="0"' if piece else 'fill="none"'
    return (
        f'<path d="{d_attr(segs)}" {fill} stroke="{OUTER}" stroke-width="2.2"/>'
        f'<path d="{d_attr(inset(segs, gap))}" fill="none" stroke="{INNER}" stroke-width="1.6"/>'
    )


def ring(x: float, y: float, r: float, piece: bool = True, gap: float = GAP) -> str:
    fill = f'fill="{FILL}" fill-opacity="0"' if piece else 'fill="none"'
    return (
        f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="{fmt(r)}" {fill} stroke="{OUTER}" stroke-width="2.2"/>'
        f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="{fmt(r - gap)}" fill="none" stroke="{INNER}" stroke-width="1.6"/>'
    )


def glyph(d: str) -> str:
    return f'<path d="{d}" fill="none" stroke="{INNER}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'


def mirrored_segs(segs: list[Seg]) -> list[Seg]:
    return [(mirror(p3), mirror(c2), mirror(c1), mirror(p0)) for p0, c1, c2, p3 in reversed(segs)]


def body() -> list[Seg]:
    left: list[Seg] = [
        ((CX, 78), (240, 78), (200, 72), (152, 72)),
        ((152, 72), (112, 72), (84, 76), (66, 94)),
        ((66, 94), (44, 116), (32, 156), (25, 205)),
        ((25, 205), (16, 272), (10, 330), (26, 372)),
        ((26, 372), (40, 404), (80, 414), (112, 404)),
        ((112, 404), (140, 396), (156, 372), (172, 344)),
        ((172, 344), (188, 318), (210, 302), (240, 300)),
        line((240, 300), (CX, 300)),
    ]
    return left + mirrored_segs(left)


def side_pair(name_l: str, name_r: str, segs: list[Seg]) -> list[tuple[str, str]]:
    return [(name_l, double(segs)), (name_r, double(mirrored_segs(segs)))]


def build() -> str:
    pieces: list[tuple[str, str]] = [("body", double(body(), piece=False, gap=5))]

    # Gatilhos (abas do topo) e ombros.
    l2 = rounded([(116, 44), (124, 10), (190, 10), (198, 44)], [9, 10, 10, 9])
    l1 = rounded([(108, 65), (118, 52), (198, 52), (198, 65)], [12, 6, 6, 6])
    pieces += side_pair("l2", "r2", l2)
    pieces += side_pair("l1", "r1", l1)

    # Touchpad e os 5 LEDs de jogador logo abaixo.
    pieces.append(("touchpad", double(rounded([(203, 86), (386, 86), (377, 180), (212, 180)], [10, 10, 14, 14]))))
    for i in range(5):
        x = CX + (i - 2) * 12
        pieces.append((f"led_{i + 1}", f'<circle cx="{fmt(x)}" cy="194" r="2.6" fill="{FILL}" fill-opacity="0" stroke="{OUTER}" stroke-width="1.4"/>'))

    # Create e Options: pílulas inclinadas nos cantos do touchpad.
    create = rounded([(180, 92), (188, 90), (192, 112), (184, 114)], 4)
    pieces += [("create", double(create, gap=2.5)), ("options", double(mirrored_segs(create), gap=2.5))]

    # Direcional: 4 teclas com a ponta virada para o centro.
    dx, dy = 124, 164
    arm = [(-13, -46), (13, -46), (13, -20), (0, -9), (-13, -20)]
    for name, ang in (("dpad_up", 0), ("dpad_right", 90), ("dpad_down", 180), ("dpad_left", 270)):
        c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        pts = [(dx + x * c - y * s, dy + x * s + y * c) for x, y in arm]
        pieces.append((name, double(rounded(pts, [4, 4, 3, 4, 3]), gap=3)))

    # Botões de rosto com os símbolos.
    fx, fy, off, r = W - 124, 164, 33, 15
    face = {"triangle": (fx, fy - off), "circle": (fx + off, fy), "cross": (fx, fy + off), "square": (fx - off, fy)}
    marks = {
        "triangle": lambda x, y: f"M{fmt(x)} {fmt(y - 6)}L{fmt(x + 6)} {fmt(y + 4)}H{fmt(x - 6)}Z",
        "circle": lambda x, y: f"M{fmt(x - 5.5)} {fmt(y)}a5.5 5.5 0 1 0 11 0a5.5 5.5 0 1 0 -11 0Z",
        "cross": lambda x, y: f"M{fmt(x - 5)} {fmt(y - 5)}L{fmt(x + 5)} {fmt(y + 5)}M{fmt(x + 5)} {fmt(y - 5)}L{fmt(x - 5)} {fmt(y + 5)}",
        "square": lambda x, y: f"M{fmt(x - 5)} {fmt(y - 5)}H{fmt(x + 5)}V{fmt(y + 5)}H{fmt(x - 5)}Z",
    }
    for name, (x, y) in face.items():
        pieces.append((name, ring(x, y, r, gap=3) + glyph(marks[name](x, y))))

    # Analógicos: anel externo + tampa, o ponto da posição fica por conta do app.
    for name, x in (("l3", 206), ("r3", W - 206)):
        pieces.append((name, ring(x, 246, 36) + f'<circle cx="{fmt(x)}" cy="246" r="25" fill="none" stroke="{INNER}" stroke-width="1.2" stroke-dasharray="2 3"/>'))

    # PS (entre os analógicos) e Mute logo abaixo.
    pieces.append(("ps", ring(CX, 240, 12, gap=3)))
    pieces.append(("mute", double(rounded([(CX - 11, 268), (CX + 11, 268), (CX + 11, 276), (CX - 11, 276)], 4), gap=2)))

    groups = "\n".join(f'<g id="{name}">{body_}</g>' for name, body_ in pieces)
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
        for bg, suffix in (("#ffffff", "light"), ("#1e1e1e", "dark")):
            image = QImage(W * 2, H * 2, QImage.Format.Format_ARGB32)
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
