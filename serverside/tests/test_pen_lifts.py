"""The pen lifts only where there is a gap to cross.

A trace with corners arrives from KiCad as several segments laid end to end.
Lifting after every one of them means a lift, a travel of zero millimetres
and a drop at every corner: slow, hard on the servo, and a chance for the
pen to land a hair off the line. Where the next segment starts where the
last one ended, the pen stays down. Where it does not, it must lift: a pen
dragged across a gap draws a line the board does not have.
"""
from __future__ import annotations

import pcb_gcode

UP = f"G1 Z{pcb_gcode.CONFIG['pen_up_z']:g}"
DOWN = f"G1 Z{pcb_gcode.CONFIG['pen_down_z']:g}"


def track(a, b):
    return {"type": "track", "layer": "F.Cu", "start": a, "end": b}


def lifts(lines):
    # The first line of the file raises the pen before anything moves; that
    # is a precaution, not a lift between strokes.
    return sum(1 for l in lines if l.startswith(DOWN))


def test_an_l_shaped_trace_is_one_stroke():
    lines = pcb_gcode.generate_gcode([
        track((0, 0), (10, 0)),
        track((10, 0), (10, 10)),
    ])
    assert lifts(lines) == 1
    body = lines[lines.index(next(l for l in lines if l.startswith(DOWN))):]
    draws = [l for l in body if l.startswith("G1 X")]
    assert len(draws) == 2          # both legs drawn without lifting between


def test_a_trace_is_one_stroke_whichever_way_its_segments_are_stored():
    # KiCad does not promise segment direction: the second leg is stored
    # end-first, and the optimiser flips it to continue the stroke.
    lines = pcb_gcode.generate_gcode([
        track((0, 0), (10, 0)),
        track((10, 10), (10, 0)),
        track((10, 10), (20, 10)),
    ])
    assert lifts(lines) == 1


def test_separate_traces_still_lift_between_them():
    lines = pcb_gcode.generate_gcode([
        track((0, 0), (10, 0)),
        track((0, 5), (10, 5)),
    ])
    assert lifts(lines) == 2


def test_a_small_gap_still_lifts_the_pen():
    """0.1 mm is a gap on the board; drawing across it would bridge it."""
    lines = pcb_gcode.generate_gcode([
        track((0, 0), (10, 0)),
        track((10.1, 0), (20, 0)),
    ])
    assert lifts(lines) == 2


def test_rounding_noise_is_not_a_gap():
    lines = pcb_gcode.generate_gcode([
        track((0, 0), (10, 0)),
        track((10.0004, 0), (20, 0)),
    ])
    assert lifts(lines) == 1


def test_every_drop_has_a_lift_and_the_pen_ends_up():
    lines = pcb_gcode.generate_gcode([
        track((0, 0), (10, 0)),
        track((10, 0), (10, 10)),
        track((30, 30), (40, 30)),
    ])
    z = [l for l in lines if l.startswith((UP, DOWN))]
    # up (start), then down/up pairs, one per stroke.
    assert z[0].startswith(UP)
    assert [l.startswith(DOWN) for l in z[1:]] == [True, False, True, False]
    assert lifts(lines) == 2

