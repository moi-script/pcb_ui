#!/usr/bin/env python
"""Trace a bitmap to single-line polylines — centerline or outline mode.

Centerline mode (default):
  A stroke of ink is thinned to a chain of single pixels down its middle,
  then that skeleton is walked into polylines.  A drawn line becomes one path
  along it.  Best for hand-drawn artwork, diagrams, and text.

Outline mode (--trace-mode outline):
  The pixel boundary of every filled ink region is traced as a closed loop.
  Best for clip-art, logos, and bold filled shapes where you want the pen to
  draw the silhouette edge rather than the medial axis.

The skeleton is a graph: pixels with one neighbour are stroke ends, pixels
with three or more are junctions, and the runs of two-neighbour pixels
between them are the strokes.  Anything left over after every junction has
been visited is a closed loop, and gets walked separately.
"""
from __future__ import annotations

import math

import numpy as np
from skimage.measure import find_contours
from skimage.morphology import skeletonize

Point = tuple[float, float]
Stroke = list[Point]

_OFFSETS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def skeleton_mask(binary: np.ndarray) -> np.ndarray:
    """Thin filled ink down to a one-pixel-wide centreline.

    `binary` is True where there is ink.
    """
    return skeletonize(binary.astype(bool))


def _neighbours(p, pts):
    r, c = p
    return [q for q in ((r + dr, c + dc) for dr, dc in _OFFSETS) if q in pts]


def skeleton_to_polylines(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    """Walk a skeleton into polylines of (row, col) pixels."""
    pts = set(map(tuple, np.argwhere(mask)))
    if not pts:
        return []
    adj = {p: _neighbours(p, pts) for p in pts}
    nodes = {p for p in pts if len(adj[p]) != 2}

    used: set[frozenset] = set()
    polys: list[list[tuple[int, int]]] = []

    def walk(start, first):
        path = [start, first]
        used.add(frozenset((start, first)))
        prev, cur = start, first
        while len(adj[cur]) == 2:
            nxt = [q for q in adj[cur] if q != prev]
            if not nxt:
                break
            q = nxt[0]
            edge = frozenset((cur, q))
            if edge in used:
                break
            used.add(edge)
            prev, cur = cur, q
            path.append(cur)
        return path

    # Strokes running between ends and junctions.
    for n in sorted(nodes):
        for nb in adj[n]:
            if frozenset((n, nb)) not in used:
                polys.append(walk(n, nb))

    # Whatever is left is a closed loop with no junction to start from.
    for p in sorted(pts):
        if len(adj[p]) == 2 and not any(frozenset((p, q)) in used for q in adj[p]):
            path = walk(p, adj[p][0])
            if path[-1] != p:
                path.append(p)          # close it
            polys.append(path)

    return [p for p in polys if len(p) >= 2]


def to_mm(polys, height_px: int, mm_per_px: float) -> list[Stroke]:
    """Pixel (row, col) to plotter (x, y) mm.

    Image rows count downward and plotter Y counts up, so the row axis is
    inverted here - this is the only place orientation is decided.
    """
    return [[(c * mm_per_px, (height_px - r) * mm_per_px) for (r, c) in poly]
            for poly in polys]


def smooth(strokes: list[Stroke], passes: int) -> list[Stroke]:
    """Round off the pixel staircase before simplifying.

    A skeleton is a chain of whole pixels, so a shallow curve comes out as
    little 45-degree steps. Simplifying that faithfully just preserves the
    steps; tightening the tolerance preserves them harder. Averaging each
    point with its neighbours pulls the chain onto the curve the pixels were
    approximating, and then a modest tolerance keeps it smooth.

    Endpoints are pinned so strokes keep meeting at junctions. Closed loops
    wrap around instead, so they stay closed.
    """
    if passes <= 0:
        return strokes
    out = []
    for s in strokes:
        pts = list(s)
        closed = len(pts) > 3 and pts[0] == pts[-1]
        for _ in range(passes):
            if len(pts) < 3:
                break
            if closed:
                ring = pts[:-1]
                n = len(ring)
                pts = [((ring[i - 1][0] + 2 * ring[i][0] + ring[(i + 1) % n][0]) / 4,
                        (ring[i - 1][1] + 2 * ring[i][1] + ring[(i + 1) % n][1]) / 4)
                       for i in range(n)]
                pts.append(pts[0])
            else:
                mid = [((pts[i - 1][0] + 2 * pts[i][0] + pts[i + 1][0]) / 4,
                        (pts[i - 1][1] + 2 * pts[i][1] + pts[i + 1][1]) / 4)
                       for i in range(1, len(pts) - 1)]
                pts = [pts[0]] + mid + [pts[-1]]
        out.append(pts)
    return out


def _rdp(pts: list[Point], tol: float) -> list[Point]:
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    span = (dx * dx + dy * dy) ** 0.5
    best_i, best_d = 0, -1.0
    for i, (x, y) in enumerate(pts[1:-1], 1):
        if span == 0:
            d = ((x - ax) ** 2 + (y - ay) ** 2) ** 0.5
        else:
            d = abs(dy * x - dx * y + bx * ay - by * ax) / span
        if d > best_d:
            best_i, best_d = i, d
    if best_d <= tol:
        return [a, b]
    return _rdp(pts[:best_i + 1], tol)[:-1] + _rdp(pts[best_i:], tol)


def simplify(strokes: list[Stroke], tol: float) -> list[Stroke]:
    """Drop points that sit within `tol` mm of the line they lie on.

    A raw skeleton has one point per pixel, which makes for a huge file and
    a plotter that stutters through what should be a smooth curve.
    """
    if tol <= 0:
        return strokes
    out = []
    for s in strokes:
        r = _rdp(s, tol)
        if len(r) >= 2:
            out.append(r)
    return out


def drop_short(strokes: list[Stroke], min_len: float) -> list[Stroke]:
    """Remove specks too small to be meaningful ink."""
    def length(s):
        return sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
                   for a, b in zip(s, s[1:]))
    return [s for s in strokes if length(s) >= min_len]


# ---------------------------------------------------------------------------
# Outline tracing
# ---------------------------------------------------------------------------

def outline_to_polylines(binary: np.ndarray) -> list[list[tuple[float, float]]]:
    """Trace the pixel boundary of every filled ink region.

    `binary` is True where there is ink.  Uses marching-squares contour
    finding (skimage.measure.find_contours) which returns sub-pixel accurate
    (row, col) paths.  Each contour is closed: its last point is identical to
    its first.  Tiny islands produced by JPEG noise are not filtered here;
    use --min-stroke or --min-blob upstream to suppress them.
    """
    contours = find_contours(binary.astype(np.float32), 0.5)
    polys: list[list[tuple[float, float]]] = []
    for c in contours:
        if len(c) < 2:
            continue
        pts = [(float(r), float(col)) for r, col in c]
        # Ensure the contour is explicitly closed
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        polys.append(pts)
    return polys


def trace(binary: np.ndarray, mm_per_px: float, simplify_tol: float = 0.05,
          min_stroke_mm: float = 0.6, smooth_passes: int = 3,
          spline_tol: float = 0.0, mode: str = "centerline") -> list[Stroke]:
    """Bitmap (True = ink) to single-line strokes in mm.

    mode='centerline' (default):
        Skeletonises the ink and walks the medial-axis graph into polylines.
        Best for hand-drawn artwork, diagrams, and text.

    mode='outline':
        Traces the pixel boundary of every filled region.  The result is a
        closed loop around each shape — one line around each silhouette edge.
        Best for bold clip-art, logos, and solid filled shapes.

    Order matters: thin / contour → round off pixel staircase → reduce to
    control points → curve through those points.  Splining before simplifying
    would just have the simplifier throw the curve away again.
    """
    if mode == "outline":
        polys = outline_to_polylines(binary)
    else:
        mask = skeleton_mask(binary)
        polys = skeleton_to_polylines(mask)
    strokes = to_mm(polys, binary.shape[0], mm_per_px)
    strokes = smooth(strokes, smooth_passes)
    strokes = simplify(strokes, simplify_tol)
    strokes = splinify(strokes, spline_tol)
    return drop_short(strokes, min_stroke_mm)


# --- spline resampling ----------------------------------------------------
#
# Simplification leaves control points on a POLYLINE, so the path between
# them is dead straight and a tighter tolerance only adds more straight bits.
# Fitting a curve through those points and sampling it gives genuinely
# sub-pixel geometry: the curve is smooth between the points, not merely
# sampled more often.

def _cr(p0, p1, p2, p3, u, alpha=0.5):
    """Centripetal Catmull-Rom, evaluated between p1 and p2 for u in [0,1].

    The uniform version of this curve kinks and overshoots badly wherever
    adjacent control points are unevenly spaced - and a traced skeleton is
    very unevenly spaced, with 1 mm segments next to 11 mm ones. Spacing the
    knots by the square root of the distance (alpha=0.5) is the standard fix
    and provably avoids cusps and self-intersections.
    """
    def knot(t, a, b):
        d = math.dist(a, b)
        return t + (d ** alpha if d > 0 else 1e-9)

    t0 = 0.0
    t1 = knot(t0, p0, p1)
    t2 = knot(t1, p1, p2)
    t3 = knot(t2, p2, p3)
    t = t1 + (t2 - t1) * u

    def lerp(a, b, ta, tb):
        if tb == ta:
            return a
        f = (t - ta) / (tb - ta)
        return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)

    a1 = lerp(p0, p1, t0, t1)
    a2 = lerp(p1, p2, t1, t2)
    a3 = lerp(p2, p3, t2, t3)
    b1 = lerp(a1, a2, t0, t2)
    b2 = lerp(a2, a3, t1, t3)
    return lerp(b1, b2, t1, t2)


def _sag(m, a, b):
    """How far the curve's midpoint sits off the straight chord."""
    (mx, my), (ax, ay), (bx, by) = m, a, b
    dx, dy = bx - ax, by - ay
    span = (dx * dx + dy * dy) ** 0.5
    if span == 0:
        return ((mx - ax) ** 2 + (my - ay) ** 2) ** 0.5
    return abs(dy * mx - dx * my + bx * ay - by * ax) / span


def _span(p0, p1, p2, p3, tol, t0=0.0, t1=1.0, depth=0):
    """Emit points along one span, splitting until the chord is within tol.

    Flatness is measured at three interior points, not just the midpoint. An
    S-shaped span crosses its own chord at the middle, so a midpoint-only
    test reads it as perfectly flat and skips the curve entirely.
    """
    a, b = _cr(p0, p1, p2, p3, t0), _cr(p0, p1, p2, p3, t1)
    tm = (t0 + t1) / 2
    if depth >= 8:
        return [b]
    worst = max(_sag(_cr(p0, p1, p2, p3, t0 + (t1 - t0) * f), a, b)
                for f in (0.25, 0.5, 0.75))
    if worst <= tol:
        return [b]
    return (_span(p0, p1, p2, p3, tol, t0, tm, depth + 1)
            + _span(p0, p1, p2, p3, tol, tm, t1, depth + 1))


def splinify(strokes: list[Stroke], tol: float) -> list[Stroke]:
    """Replace each polyline with a smooth curve sampled to `tol` mm.

    Every original point is still passed through exactly, so the drawing
    does not drift - only the path between the points changes, from a
    straight chord to a curve.
    """
    if tol <= 0:
        return strokes
    out = []
    for s in strokes:
        if len(s) < 3:
            out.append(s)
            continue
        closed = s[0] == s[-1]
        pts = s[:-1] if closed else s
        n = len(pts)
        if n < 3:
            out.append(s)
            continue
        curve = [pts[0]]
        for i in range(n - 1 if not closed else n):
            if closed:
                p0, p1, p2, p3 = (pts[(i - 1) % n], pts[i],
                                  pts[(i + 1) % n], pts[(i + 2) % n])
            else:
                p0 = pts[max(i - 1, 0)]
                p1, p2 = pts[i], pts[i + 1]
                p3 = pts[min(i + 2, n - 1)]
            curve += _span(p0, p1, p2, p3, tol)
        if closed and curve[-1] != curve[0]:
            curve.append(curve[0])
        out.append(_drop_dust(curve, tol * 5))
    return out


def _drop_dust(curve: Stroke, min_seg: float) -> Stroke:
    """Discard points closer together than min_seg.

    Adaptive subdivision can emit points microns apart where two spans meet.
    They cost a gcode line each, are far below anything a pen can render,
    and make the path look kinked to any angle-based measurement.
    """
    if len(curve) < 3:
        return curve
    out = [curve[0]]
    for p in curve[1:-1]:
        if math.dist(out[-1], p) >= min_seg:
            out.append(p)
    out.append(curve[-1])
    return out
