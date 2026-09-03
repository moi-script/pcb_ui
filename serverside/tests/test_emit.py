"""Strokes in, pen G-code out."""
from __future__ import annotations

import pytest

from tracer import emit


SQUARE = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]]
TWO = [[(0.0, 0.0), (5.0, 0.0)], [(20.0, 20.0), (25.0, 20.0)]]


def _pen_downs(lines: list[str]) -> int:
    """How many times the pen goes down. One per stroke, or the job is wrong."""
    return sum(1 for ln in lines if ln.startswith("G1 Z"))


def test_one_stroke_is_one_pen_down():
    assert _pen_downs(emit.generate_from_strokes(SQUARE)) == 1


def test_two_strokes_are_two_pen_downs():
    assert _pen_downs(emit.generate_from_strokes(TWO)) == 2


def test_every_point_is_emitted_in_order():
    lines = emit.generate_from_strokes(SQUARE)
    draws = [ln for ln in lines if ln.startswith("G1 X")]
    # the first point is the rapid; the remaining two are drawn
    assert len(draws) == 2
    assert "X10" in draws[0] and "Y0" in draws[0]
    assert "X10" in draws[1] and "Y10" in draws[1]


def test_job_ends_pen_up():
    lines = emit.generate_from_strokes(SQUARE)
    zs = [ln for ln in lines if ln.startswith(("G0 Z", "G1 Z"))]
    assert zs, "no Z motion at all"
    # the last Z move must be a retract, never a plunge
    assert zs[-1].startswith("G0 Z")


def test_returns_to_origin():
    lines = emit.generate_from_strokes(SQUARE)
    assert any(ln.startswith("G0 X0 Y0") for ln in lines)


def test_units_and_absolute_mode_are_set():
    lines = emit.generate_from_strokes(SQUARE)
    assert "G21" in lines      # millimetres
    assert "G90" in lines      # absolute


def test_ordering_flips_a_stroke_when_its_far_end_is_nearer():
    # the pen starts at the origin; this stroke runs away from it, so entering
    # at its tail is shorter than travelling to its head
    away = [[(10.0, 0.0), (1.0, 0.0)]]
    ordered = emit.order_strokes(away, start=(0.0, 0.0))
    assert ordered[0][0] == (1.0, 0.0)


def test_ordering_visits_the_near_stroke_first():
    far = [(50.0, 50.0), (55.0, 50.0)]
    near = [(1.0, 1.0), (5.0, 1.0)]
    ordered = emit.order_strokes([far, near], start=(0.0, 0.0))
    assert ordered[0][0] == (1.0, 1.0)


def test_ordering_keeps_every_stroke():
    assert len(emit.order_strokes(TWO, start=(0.0, 0.0))) == len(TWO)


def test_ordering_does_not_split_a_stroke():
    ordered = emit.order_strokes(SQUARE, start=(0.0, 0.0))
    assert len(ordered) == 1
    assert len(ordered[0]) == len(SQUARE[0])


def test_bounds():
    assert emit.bounds(TWO) == (0.0, 0.0, 25.0, 20.0)


def test_frame_traces_the_bbox_pen_up():
    lines = emit.emit_frame(emit.bounds(TWO))
    assert not any(ln.startswith("G1 Z") for ln in lines), "frame must not draw"
    xs = [ln for ln in lines if ln.startswith("G0 X")]
    assert len(xs) >= 5, "a closed rectangle needs 4 corners plus the return"


def test_report_counts_moves():
    rep = emit.stroke_report(TWO)
    assert rep["drawMoves"] == 2       # one drawn segment per stroke
    assert rep["travelMoves"] == 2     # one rapid per stroke
    assert rep["drawLength"] == pytest.approx(10.0)
    assert rep["estMinutes"] >= 0


def test_report_travel_never_worsens_with_ordering():
    rep = emit.stroke_report(TWO)
    assert rep["penUpAfter"] <= rep["penUpBefore"]


def test_empty_strokes_raise():
    with pytest.raises(ValueError):
        emit.generate_from_strokes([])


def test_bounds_of_nothing_raises():
    with pytest.raises(ValueError):
        emit.bounds([])


def test_thumbnail_strokes_pass_small_input_through():
    assert emit.thumbnail_strokes(TWO, max_points=100) == TWO


def test_thumbnail_strokes_decimate_dense_input():
    dense = [[(float(i), float(i % 7)) for i in range(4000)]]
    thumb = emit.thumbnail_strokes(dense, max_points=500)
    assert sum(len(s) for s in thumb) <= 520


def test_thumbnail_strokes_keep_both_endpoints():
    dense = [[(float(i), 0.0) for i in range(4000)]]
    thumb = emit.thumbnail_strokes(dense, max_points=200)
    assert thumb[0][0] == (0.0, 0.0)
    assert thumb[0][-1] == (3999.0, 0.0)


def test_thumbnail_strokes_keep_every_stroke():
    dense = [[(float(i), float(k)) for i in range(600)] for k in range(30)]
    thumb = emit.thumbnail_strokes(dense, max_points=300)
    assert len(thumb) == len(dense)
    assert all(len(s) >= 2 for s in thumb)
