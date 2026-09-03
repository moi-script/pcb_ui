"""Traced strokes to pen-plotter G-code.

A stroke is one continuous pen-down path: `[(x, y), ...]` in mm. That is the
whole reason this module exists instead of reusing `pcb_gcode.generate_gcode`,
which takes two-point track pairs. Splitting a splined polyline into segments
and reordering them greedily would be O(n^2) over thousands of items, and its
correctness would rest on the accident that consecutive segments sit zero
distance apart. Ordering belongs at stroke level: hundreds of items, and
pen-down continuity is structural rather than emergent.
"""
from __future__ import annotations

import math

from pcb_gcode import CONFIG

Point = tuple[float, float]
Stroke = list[Point]


def _f(v: float) -> str:
    """Trim trailing zeros so the file stays small and readable."""
    return f"{v:.3f}".rstrip("0").rstrip(".") or "0"


def bounds(strokes: list[Stroke]) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) over every point."""
    if not strokes:
        raise ValueError("no strokes")
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    return (min(xs), min(ys), max(xs), max(ys))


def _length(s: Stroke) -> float:
    return sum(math.dist(a, b) for a, b in zip(s, s[1:]))


def order_strokes(strokes: list[Stroke], start: Point = (0.0, 0.0)) -> list[Stroke]:
    """Greedy nearest-neighbour over stroke endpoints, with flipping.

    Mirrors `pcb_gcode.optimize_order`'s behaviour, but a whole stroke is the
    unit: either end may be the entry point, so a stroke that runs away from
    the pen is reversed rather than travelled to.
    """
    remaining = [list(s) for s in strokes]
    out: list[Stroke] = []
    cur = start
    while remaining:
        best_i, best_rev, best_d = 0, False, math.inf
        for i, s in enumerate(remaining):
            d_head = math.dist(cur, s[0])
            if d_head < best_d:
                best_i, best_rev, best_d = i, False, d_head
            d_tail = math.dist(cur, s[-1])
            if d_tail < best_d:
                best_i, best_rev, best_d = i, True, d_tail
        s = remaining.pop(best_i)
        if best_rev:
            s = s[::-1]
        out.append(s)
        cur = s[-1]
    return out


def generate_from_strokes(strokes: list[Stroke], cfg: dict = CONFIG,
                          label: str = "traced") -> list[str]:
    """Pen G-code for a set of traced strokes."""
    if not strokes:
        raise ValueError("no strokes to plot")

    up = cfg["pen_up_z"]
    down = cfg["pen_down_z"]
    travel_feed = cfg["travel_feed"]
    draw_feed = cfg["draw_feed"]
    z_feed = cfg.get("z_feed", 500)

    minx, miny, maxx, maxy = bounds(strokes)
    out = [
        f"; {label} - traced centreline pen plot",
        f"; extent: {_f(maxx - minx)} x {_f(maxy - miny)} mm",
        f"; strokes: {len(strokes)}",
        "; Set zero before run: G10 L20 P1 X0 Y0 Z0",
        "G21",   # millimetres
        "G90",   # absolute
        "G17",   # XY plane
        f"G0 Z{_f(up)}",
    ]

    for s in order_strokes(strokes):
        x0, y0 = s[0]
        out.append(f"G0 X{_f(x0)} Y{_f(y0)} F{_f(travel_feed)}")
        out.append(f"G1 Z{_f(down)} F{_f(z_feed)}")
        for (x, y) in s[1:]:
            out.append(f"G1 X{_f(x)} Y{_f(y)} F{_f(draw_feed)}")
        out.append(f"G0 Z{_f(up)}")

    out.append("G0 X0 Y0")
    out.append("M2")
    return out


def emit_frame(bbox: tuple[float, float, float, float],
               cfg: dict = CONFIG) -> list[str]:
    """Trace the bounding box with the pen up.

    Run this before the job. It costs nothing and it is the cheapest way to
    find out that the drawing runs off the edge of the work.
    """
    minx, miny, maxx, maxy = bbox
    corners = [(minx, miny), (maxx, miny), (maxx, maxy),
               (minx, maxy), (minx, miny)]
    out = [
        "; alignment frame - pen stays up",
        "G21", "G90", "G17",
        f"G0 Z{_f(cfg['pen_up_z'])}",
    ]
    out += [f"G0 X{_f(x)} Y{_f(y)} F{_f(cfg['travel_feed'])}" for x, y in corners]
    out.append("G0 X0 Y0")
    out.append("M2")
    return out


def thumbnail_strokes(strokes: list[Stroke],
                      max_points: int = 1000) -> list[Stroke]:
    """A decimated copy cheap enough to ship in a list of boards.

    A traced board can carry twenty thousand points. At thumbnail size that is
    far below what a screen can show, but it is megabytes on the wire when a
    grid of boards each sends its own geometry. Sampling every Nth point keeps
    the shape recognisable at a fraction of the size.

    Every stroke survives, and so do both of its endpoints — dropping either
    would visibly shorten strokes rather than simplify them.
    """
    total = sum(len(s) for s in strokes)
    if total <= max_points:
        return strokes
    step = max(2, math.ceil(total / max_points))

    out: list[Stroke] = []
    for s in strokes:
        if len(s) <= 2:
            out.append(s)
            continue
        thin = s[::step]
        if thin[-1] != s[-1]:
            thin.append(s[-1])
        out.append(thin if len(thin) >= 2 else [s[0], s[-1]])
    return out


def stroke_report(strokes: list[Stroke], cfg: dict = CONFIG) -> dict:
    """Counts and estimates for the board summary tiles."""
    if not strokes:
        raise ValueError("no strokes")

    ordered = order_strokes(strokes)
    draw_moves = sum(len(s) - 1 for s in strokes)
    draw_length = sum(_length(s) for s in strokes)

    def travel(seq: list[Stroke]) -> float:
        cur: Point = (0.0, 0.0)
        total = 0.0
        for s in seq:
            total += math.dist(cur, s[0])
            cur = s[-1]
        return total

    before = travel([list(s) for s in strokes])
    after = travel(ordered)

    # draw time + travel time + ~1.8 s per pen lift, the same rule pcb_gcode uses
    minutes = (draw_length / cfg["draw_feed"]
               + after / cfg["travel_feed"]
               + len(strokes) * 1.8 / 60.0)

    return {
        "drawMoves": draw_moves,
        "travelMoves": len(strokes),
        "penUpBefore": round(before),
        "penUpAfter": round(after),
        "drawLength": round(draw_length, 2),
        "estMinutes": max(1, round(minutes)),
    }
