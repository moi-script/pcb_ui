"""Filling a region with parallel pen strokes.

Centreline tracing draws a line down the middle of a shape and outline
tracing draws its edge. Neither covers a wide copper trace, which is what
etch resist needs — so this fills it.

The load-bearing invariant throughout: for a filled region, the total length
of the hatch is the area divided by the line spacing. It falls straight out of
the geometry and it catches almost every way this can go wrong — wrong
spacing, lines running past the edge, lines missing, double-drawn lines.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from tracer import hatch


MMPP = 0.1  # 0.1 mm per pixel throughout


def _rect(w_px=200, h_px=100, pad=20) -> np.ndarray:
    ink = np.zeros((h_px + 2 * pad, w_px + 2 * pad), dtype=bool)
    ink[pad:pad + h_px, pad:pad + w_px] = True
    return ink


def _ring(outer=60, inner=30, size=200) -> np.ndarray:
    yy, xx = np.mgrid[0:size, 0:size]
    r = np.hypot(yy - size / 2, xx - size / 2)
    return (r <= outer) & (r >= inner)


def _total(strokes) -> float:
    return sum(math.dist(a, b) for s in strokes for a, b in zip(s, s[1:]))


def _area_mm2(ink: np.ndarray, mm_per_px: float) -> float:
    return float(ink.sum()) * mm_per_px * mm_per_px


# --- the invariant ---------------------------------------------------------

@pytest.mark.parametrize("spacing", [0.4, 0.8, 1.5])
@pytest.mark.parametrize("angle", [0.0, 45.0, 90.0, 135.0])
def test_total_length_is_area_over_spacing(spacing, angle):
    ink = _rect()
    strokes = hatch.hatch(ink, MMPP, spacing_mm=spacing, angle_deg=angle)
    expected = _area_mm2(ink, MMPP) / spacing
    assert _total(strokes) == pytest.approx(expected, rel=0.12)


def test_the_invariant_holds_for_a_shape_with_a_hole():
    """A ring is the real test: every scanline crosses it twice, so a filler
    that ignores holes would paint straight across the middle."""
    ink = _ring()
    strokes = hatch.hatch(ink, MMPP, spacing_mm=0.5, angle_deg=0.0)
    expected = _area_mm2(ink, MMPP) / 0.5
    assert _total(strokes) == pytest.approx(expected, rel=0.12)


# --- geometry --------------------------------------------------------------

def test_hatch_stays_inside_the_shape():
    ink = _rect(w_px=200, h_px=100, pad=20)
    strokes = hatch.hatch(ink, MMPP, spacing_mm=0.5, angle_deg=0.0)
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    # the rect spans cols 20..219 and rows 20..119, in mm with Y flipped
    assert min(xs) >= 20 * MMPP - 0.15
    assert max(xs) <= 220 * MMPP + 0.15
    h = ink.shape[0]
    assert min(ys) >= (h - 120) * MMPP - 0.15
    assert max(ys) <= (h - 20) * MMPP + 0.15


def test_a_ring_gives_two_runs_on_a_scanline_through_the_hole():
    ink = _ring()
    strokes = hatch.hatch(ink, MMPP, spacing_mm=0.5, angle_deg=0.0)
    # group by y; a line crossing the hole must arrive as two separate strokes
    from collections import Counter
    rows = Counter(round(s[0][1], 3) for s in strokes)
    assert max(rows.values()) >= 2, "the hole was painted over"


def test_angle_zero_is_horizontal():
    strokes = hatch.hatch(_rect(), MMPP, spacing_mm=1.0, angle_deg=0.0)
    for s in strokes:
        assert s[0][1] == pytest.approx(s[-1][1], abs=1e-6)


def test_angle_ninety_is_vertical():
    strokes = hatch.hatch(_rect(), MMPP, spacing_mm=1.0, angle_deg=90.0)
    for s in strokes:
        assert s[0][0] == pytest.approx(s[-1][0], abs=1e-6)


def test_cross_hatch_roughly_doubles_the_length():
    ink = _rect()
    one = hatch.hatch(ink, MMPP, spacing_mm=0.8, angle_deg=45.0)
    two = hatch.hatch(ink, MMPP, spacing_mm=0.8, angle_deg=45.0, cross=True)
    assert _total(two) == pytest.approx(_total(one) * 2, rel=0.15)


def test_tighter_spacing_means_more_ink():
    ink = _rect()
    coarse = _total(hatch.hatch(ink, MMPP, spacing_mm=1.0, angle_deg=0.0))
    fine = _total(hatch.hatch(ink, MMPP, spacing_mm=0.5, angle_deg=0.0))
    assert fine == pytest.approx(coarse * 2, rel=0.12)


# --- edges -----------------------------------------------------------------

def test_empty_mask_gives_nothing():
    assert hatch.hatch(np.zeros((50, 50), dtype=bool), MMPP,
                       spacing_mm=0.5, angle_deg=0.0) == []


def test_spacing_must_be_positive():
    with pytest.raises(ValueError):
        hatch.hatch(_rect(), MMPP, spacing_mm=0.0, angle_deg=0.0)


def test_sub_pixel_spacing_refines_the_grid_instead_of_refusing():
    """0.05 mm lines on a 0.1 mm grid is a real request — fine resist lines on
    a small print. The mask is refined rather than the request rejected, and
    the area invariant still has to hold."""
    ink = _rect()
    strokes = hatch.hatch(ink, MMPP, spacing_mm=0.05, angle_deg=0.0)
    expected = _area_mm2(ink, MMPP) / 0.05
    assert _total(strokes) == pytest.approx(expected, rel=0.12)


def test_lines_are_not_drawn_twice_at_sub_pixel_spacing():
    """The failure refining guards against: two lines rounding onto the same
    pixel row would double the ink laid down."""
    ink = _rect()
    strokes = hatch.hatch(ink, MMPP, spacing_mm=0.05, angle_deg=0.0)
    ys = sorted(round(s[0][1], 4) for s in strokes)
    assert len(ys) == len(set(ys)), "two hatch lines landed on the same row"


def test_absurdly_fine_spacing_is_still_refused():
    """Refining has a limit; past it, say so rather than allocate forever."""
    with pytest.raises(ValueError):
        hatch.hatch(_rect(), MMPP, spacing_mm=0.0001, angle_deg=0.0)


def test_every_stroke_has_at_least_two_points():
    strokes = hatch.hatch(_rect(), MMPP, spacing_mm=0.5, angle_deg=30.0)
    assert strokes
    assert all(len(s) >= 2 for s in strokes)
