"""Fill a region with parallel pen strokes — hatching for etch resist.

Centreline tracing draws one line down the middle of a shape; outline tracing
draws its edge. Neither covers a wide copper trace, so neither protects it in
an etch bath. Hatching walks the pen back and forth across the region until it
is covered.

The region is scanned in a rotated basis rather than by rotating the bitmap.
Any point on hatch line `o` is `o * n + t * d`, where `d` is the line direction
and `n` its normal, so the original mask is sampled directly and there is no
resampling blur to widen or break the fill.

This is a new module rather than an addition to `centerline.py`, which is
vendored verbatim from the reference tracer and is kept diffable against it.
"""
from __future__ import annotations

import math

import numpy as np

Point = tuple[float, float]
Stroke = list[Point]

# Sample the mask at least this many pixels apart, or adjacent hatch lines
# round onto the same pixels and get drawn twice.
_MIN_SPACING_PX = 1.5
# How far the mask may be refined to honour a fine spacing. Eight squares the
# memory sixty-four-fold; past that the request is not really about this image.
_MAX_UPSAMPLE = 8


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous True runs in a 1-D boolean array, as (first, last) indices."""
    if not flags.any():
        return []
    padded = np.concatenate(([False], flags, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(a), int(b) - 1) for a, b in zip(edges[::2], edges[1::2])]


def _one_angle(ink: np.ndarray, mm_per_px: float, spacing_px: float,
               angle_deg: float) -> list[Stroke]:
    height = ink.shape[0]
    theta = math.radians(angle_deg)
    dx, dy = math.cos(theta), math.sin(theta)      # along the line
    nx, ny = -math.sin(theta), math.cos(theta)     # between lines

    ys, xs = np.nonzero(ink)
    if xs.size == 0:
        return []

    offs = xs * nx + ys * ny
    alongs = xs * dx + ys * dy
    o_lo, o_hi = float(offs.min()), float(offs.max())
    t_lo, t_hi = float(alongs.min()), float(alongs.max())

    # Sample one point per pixel along each line, and offset the first line by
    # half a step so the fill sits inside the shape rather than on its edge.
    t = np.arange(t_lo - 1.0, t_hi + 1.0, 1.0)
    if t.size < 2:
        return []

    out: list[Stroke] = []
    flip = False
    o = o_lo + spacing_px / 2.0
    while o <= o_hi:
        px = o * nx + t * dx
        py = o * ny + t * dy
        cols = np.rint(px).astype(np.int64)
        rows = np.rint(py).astype(np.int64)
        inside = ((cols >= 0) & (cols < ink.shape[1])
                  & (rows >= 0) & (rows < height))
        hit = np.zeros(t.size, dtype=bool)
        if inside.any():
            hit[inside] = ink[rows[inside], cols[inside]]

        for first, last in _runs(hit):
            # A run of k samples covers k pixels, not k-1: extend by half a
            # sample at each end, or every run reads one pixel short and the
            # fill quietly under-covers.
            ta, tb = t[first] - 0.5, t[last] + 0.5
            ax, ay = o * nx + ta * dx, o * ny + ta * dy
            bx, by = o * nx + tb * dx, o * ny + tb * dy
            seg: Stroke = [(ax * mm_per_px, (height - ay) * mm_per_px),
                           (bx * mm_per_px, (height - by) * mm_per_px)]
            out.append(seg[::-1] if flip else seg)

        flip = not flip
        o += spacing_px

    return out


def hatch(ink: np.ndarray, mm_per_px: float, spacing_mm: float,
          angle_deg: float = 45.0, cross: bool = False) -> list[Stroke]:
    """Parallel fill strokes covering the ink in `ink` (True = ink).

    `spacing_mm` is the gap between line centres. To actually cover the copper
    it must be no wider than the pen, and a little narrower is safer — the
    caller decides, because only they know what is in the pen holder.

    `cross` adds a second pass at 90 degrees. It costs twice the plotting time
    and covers far more reliably on anything but a perfectly behaved pen.
    """
    if spacing_mm <= 0:
        raise ValueError("hatch spacing must be greater than zero")
    spacing_px = spacing_mm / mm_per_px

    # Lines closer together than the sampling grid would round onto the same
    # pixels and be drawn twice. That is a limit of how the mask is sampled,
    # not of the geometry — 0.4 mm resist lines on a 25 mm print are entirely
    # reasonable — so refine the grid instead of refusing. Nearest-neighbour
    # upsampling preserves the region exactly: each pixel becomes an n x n
    # block while the millimetres it represents shrink by the same n.
    if spacing_px < _MIN_SPACING_PX:
        up = math.ceil(_MIN_SPACING_PX / spacing_px)
        if up > _MAX_UPSAMPLE:
            raise ValueError(
                f"hatch spacing of {spacing_mm} mm is far finer than this "
                f"image can describe ({mm_per_px:.4f} mm per pixel). Trace "
                f"larger, or space the lines at least "
                f"{mm_per_px * _MIN_SPACING_PX / _MAX_UPSAMPLE:.3f} mm apart.")
        ink = np.kron(ink, np.ones((up, up), dtype=bool))
        mm_per_px = mm_per_px / up
        spacing_px = spacing_px * up

    strokes = _one_angle(ink, mm_per_px, spacing_px, angle_deg)
    if cross:
        strokes += _one_angle(ink, mm_per_px, spacing_px, angle_deg + 90.0)
    return strokes
