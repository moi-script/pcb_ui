"""Tests for the centerline tracer.

The property that matters throughout: a drawn line becomes ONE path along
it, not a loop around it.
"""
import math

import numpy as np

from tracer import centerline as cl


def blank(h=40, w=40):
    return np.zeros((h, w), dtype=bool)


def total_length(strokes):
    return sum(math.dist(a, b) for s in strokes for a, b in zip(s, s[1:]))


# --- the core promise -----------------------------------------------------

def test_a_thick_line_traces_to_one_stroke_not_two():
    """A 5px-wide bar is one line of ink, so it must yield one path.

    An outline tracer would return a loop around the bar instead - that is
    the doubling this whole pipeline exists to avoid.
    """
    img = blank()
    img[18:23, 5:35] = True
    strokes = cl.trace(img, mm_per_px=1.0)
    assert len(strokes) == 1


def test_that_stroke_runs_along_the_bar_not_around_it():
    img = blank()
    img[18:23, 5:35] = True
    strokes = cl.trace(img, mm_per_px=1.0)
    # Along is ~30 units; around would be ~70 (twice the length plus the ends).
    assert 25 <= total_length(strokes) <= 35


def test_thickness_never_doubles_the_path():
    """Path length must follow the line's LENGTH, never its perimeter.

    A 30x13 bar has a perimeter of ~86. An outline tracer would return
    something near that; a centerline tracer stays near 30.
    """
    thick = blank()
    thick[14:27, 5:35] = True
    assert total_length(cl.trace(thick, 1.0)) < 40


def test_a_thick_stroke_is_shortened_at_its_ends():
    """Known and accepted: thinning tapers stroke ends inward by roughly
    half the stroke width, so a fat mark traces slightly short."""
    thin, thick = blank(), blank()
    thin[19:21, 5:35] = True          # 2px thick
    thick[14:27, 5:35] = True         # 13px thick
    thin_len = total_length(cl.trace(thin, 1.0))
    thick_len = total_length(cl.trace(thick, 1.0))
    assert thick_len < thin_len                    # shorter, not longer
    assert thick_len > thin_len - 13 - 2           # by about the width


def test_a_ring_stays_a_single_closed_loop():
    """A drawn circle is one closed stroke, not two concentric ones."""
    img = blank(60, 60)
    yy, xx = np.mgrid[0:60, 0:60]
    d = np.hypot(yy - 30, xx - 30)
    img[(d > 18) & (d < 22)] = True          # an annulus: a drawn ring
    strokes = cl.trace(img, mm_per_px=1.0)
    assert len(strokes) == 1
    assert math.dist(strokes[0][0], strokes[0][-1]) < 3.0


# --- topology -------------------------------------------------------------

def test_two_separate_marks_give_two_strokes():
    img = blank()
    img[10, 5:20] = True
    img[30, 5:20] = True
    assert len(cl.trace(img, 1.0)) == 2


def test_a_crossing_is_split_into_strokes_that_meet_at_the_junction():
    img = blank()
    img[20, 5:35] = True
    img[5:35, 20] = True
    strokes = cl.trace(img, mm_per_px=1.0)
    assert len(strokes) >= 4          # four arms out of the centre
    # every arm has an endpoint at the junction
    centre = (20.0, 20.0)
    touching = sum(1 for s in strokes
                   if min(math.dist(centre, s[0]), math.dist(centre, s[-1])) < 3)
    assert touching >= 4


def test_an_empty_image_traces_to_nothing():
    assert cl.trace(blank(), 1.0) == []


# --- orientation ----------------------------------------------------------

def test_image_rows_are_flipped_so_the_top_of_the_picture_is_high_y():
    """Image rows count down, plotter Y counts up."""
    img = blank(40, 40)
    img[5, 5:30] = True               # near the TOP of the image
    strokes = cl.trace(img, mm_per_px=1.0)
    y = strokes[0][0][1]
    assert y > 20                     # ...so it must land HIGH in Y


def test_mm_per_px_scales_the_result():
    img = blank()
    img[20, 5:35] = True
    one = total_length(cl.trace(img, mm_per_px=1.0))
    half = total_length(cl.trace(img, mm_per_px=0.5))
    assert math.isclose(one / 2, half, rel_tol=0.05)


# --- simplification -------------------------------------------------------

def test_a_straight_run_collapses_to_its_two_ends():
    pts = [(float(i), 0.0) for i in range(20)]
    assert cl.simplify([pts], tol=0.1) == [[(0.0, 0.0), (19.0, 0.0)]]


def test_simplification_keeps_a_corner():
    pts = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (10.0, 5.0), (10.0, 10.0)]
    out = cl.simplify([pts], tol=0.1)[0]
    assert (10.0, 0.0) in out


def _dist_to_segment(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.dist(p, (ax + t * dx, ay + t * dy))


def test_simplification_stays_within_tolerance_of_the_original():
    """A simplified curve must not wander off the shape it came from.

    Measured against the output SEGMENTS, not its vertices - a point midway
    along a simplified straight run is far from both ends yet exactly on the
    line.
    """
    pts = [(float(i), math.sin(i / 3) * 5) for i in range(60)]
    tol = 0.2
    out = cl.simplify([pts], tol=tol)[0]
    for p in pts:
        near = min(_dist_to_segment(p, a, b) for a, b in zip(out, out[1:]))
        assert near <= tol + 1e-9
    assert len(out) < len(pts)


def test_zero_tolerance_changes_nothing():
    pts = [(float(i), 0.0) for i in range(5)]
    assert cl.simplify([pts], tol=0.0) == [pts]


# --- noise ----------------------------------------------------------------

def test_specks_are_dropped():
    img = blank()
    img[20, 5:35] = True              # a real line
    img[35, 35] = True                # a speck
    img[2, 2] = True                  # another speck
    assert len(cl.trace(img, mm_per_px=1.0, min_stroke_mm=3.0)) == 1


def test_real_strokes_survive_the_speck_filter():
    img = blank()
    img[20, 5:35] = True
    assert len(cl.trace(img, mm_per_px=1.0, min_stroke_mm=3.0)) == 1


# --- smoothing ------------------------------------------------------------

def test_smoothing_flattens_a_pixel_staircase():
    """The 45-degree steps a skeleton makes on a shallow curve must go."""
    stair = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (2.0, 1.0), (2.0, 2.0),
             (3.0, 2.0), (3.0, 3.0), (4.0, 3.0)]
    out = cl.smooth([stair], passes=4)[0]
    # deviation from the straight run between the ends should shrink
    def wobble(pts):
        a, b = pts[0], pts[-1]
        return max(_dist_to_segment(p, a, b) for p in pts)
    assert wobble(out) < wobble(stair) * 0.6


def test_smoothing_pins_the_endpoints():
    """Strokes meet at junctions; moving their ends would tear the drawing."""
    s = [(0.0, 0.0), (1.0, 5.0), (2.0, 0.0), (3.0, 5.0), (4.0, 0.0)]
    out = cl.smooth([s], passes=3)[0]
    assert out[0] == (0.0, 0.0) and out[-1] == (4.0, 0.0)


def test_smoothing_keeps_a_closed_loop_closed():
    ring = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0)]
    out = cl.smooth([ring], passes=3)[0]
    assert out[0] == out[-1]


def test_smoothing_keeps_the_point_count():
    s = [(float(i), 0.0) for i in range(10)]
    assert len(cl.smooth([s], passes=3)[0]) == 10


def test_smoothing_leaves_a_straight_line_straight():
    s = [(float(i), 0.0) for i in range(10)]
    out = cl.smooth([s], passes=5)[0]
    assert all(abs(y) < 1e-9 for (_, y) in out)


def test_zero_passes_is_a_no_op():
    s = [(0.0, 0.0), (1.0, 3.0), (2.0, 0.0)]
    assert cl.smooth([s], passes=0) == [s]


def test_smoothing_does_not_shift_the_line_off_the_original():
    """It should round corners, not relocate the stroke."""
    s = [(float(i), 0.0) for i in range(20)]
    s[10] = (10.0, 0.4)
    out = cl.smooth([s], passes=3)[0]
    for p in out:
        assert min(_dist_to_segment(p, a, b) for a, b in zip(s, s[1:])) < 0.5


def test_a_traced_curve_is_smoother_with_smoothing_than_without():
    """End to end: the same arc, traced both ways."""
    img = blank(80, 80)
    yy, xx = np.mgrid[0:80, 0:80]
    d = np.hypot(yy - 40, xx - 40)
    img[(d > 28) & (d < 31)] = True

    def max_turn(strokes):
        worst = 0.0
        for s in strokes:
            for a, b, c in zip(s, s[1:], s[2:]):
                v1 = (b[0] - a[0], b[1] - a[1])
                v2 = (c[0] - b[0], c[1] - b[1])
                n1 = math.hypot(*v1); n2 = math.hypot(*v2)
                if n1 and n2:
                    cos = max(-1.0, min(1.0, (v1[0]*v2[0] + v1[1]*v2[1]) / (n1*n2)))
                    worst = max(worst, math.acos(cos))
        return worst

    rough = cl.trace(img, 1.0, simplify_tol=0.05, smooth_passes=0)
    fine = cl.trace(img, 1.0, simplify_tol=0.05, smooth_passes=3)
    assert max_turn(fine) < max_turn(rough)


# --- spline resampling ----------------------------------------------------

def test_spline_passes_through_every_control_point():
    """Curving the path must not move the points the trace found."""
    pts = [(0.0, 0.0), (10.0, 5.0), (20.0, 0.0), (30.0, 5.0)]
    out = cl.splinify([pts], tol=0.01)[0]
    for p in pts:
        assert min(math.dist(p, q) for q in out) < 1e-6


def test_spline_bends_the_path_between_the_points():
    """The whole point: between control points it is a curve, not a chord."""
    pts = [(0.0, 0.0), (10.0, 5.0), (20.0, 0.0), (30.0, 5.0)]
    out = cl.splinify([pts], tol=0.01)[0]
    mid = [p for p in out if 10.0 < p[0] < 20.0]
    off = max(_dist_to_segment(p, (10.0, 5.0), (20.0, 0.0)) for p in mid)
    assert off > 0.05


def test_spline_keeps_a_closed_loop_closed():
    ring = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    out = cl.splinify([ring], tol=0.01)[0]
    assert out[0] == out[-1]


def test_tighter_tolerance_gives_more_points():
    pts = [(0.0, 0.0), (10.0, 5.0), (20.0, 0.0), (30.0, 5.0)]
    assert len(cl.splinify([pts], 0.002)[0]) > len(cl.splinify([pts], 0.05)[0])


def test_spline_leaves_a_straight_line_straight():
    """No wobble invented where the source had none."""
    pts = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0)]
    out = cl.splinify([pts], tol=0.001)[0]
    assert all(abs(y) < 1e-9 for (_, y) in out)


def test_spline_does_not_overshoot_the_original_shape():
    """Catmull-Rom can bulge on sharp corners; it must stay reasonable."""
    pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    out = cl.splinify([pts], tol=0.01)[0]
    xs = [x for (x, _) in out]
    ys = [y for (_, y) in out]
    assert max(xs) < 11.5 and max(ys) < 11.5
    assert min(xs) > -1.5 and min(ys) > -1.5


def test_zero_tolerance_disables_splining():
    pts = [(0.0, 0.0), (10.0, 5.0), (20.0, 0.0)]
    assert cl.splinify([pts], tol=0.0) == [pts]


def test_a_two_point_stroke_is_left_alone():
    """Nothing to curve through."""
    pts = [(0.0, 0.0), (10.0, 0.0)]
    assert cl.splinify([pts], tol=0.001) == [pts]


def test_splining_a_traced_curve_reduces_the_turn_at_each_vertex():
    img = blank(80, 80)
    yy, xx = np.mgrid[0:80, 0:80]
    d = np.hypot(yy - 40, xx - 40)
    img[(d > 28) & (d < 31)] = True

    def max_turn(strokes, min_seg=0.0):
        worst = 0.0
        for s in strokes:
            for a, b, c in zip(s, s[1:], s[2:]):
                v1 = (b[0] - a[0], b[1] - a[1])
                v2 = (c[0] - b[0], c[1] - b[1])
                n1 = math.hypot(*v1); n2 = math.hypot(*v2)
                if n1 > min_seg and n2 > min_seg:   # skip zero-length
                    cos = max(-1.0, min(1.0, (v1[0]*v2[0] + v1[1]*v2[1]) / (n1*n2)))
                    worst = max(worst, math.acos(cos))
        return worst

    plain = cl.trace(img, 1.0, simplify_tol=0.05, spline_tol=0.0)
    curved = cl.trace(img, 1.0, simplify_tol=0.05, spline_tol=0.002)
    assert max_turn(curved) < max_turn(plain)


def test_uneven_control_spacing_does_not_kink_the_curve():
    """A traced skeleton spaces its points very unevenly.

    Uniform Catmull-Rom overshoots and cusps exactly there, which is why the
    centripetal parameterisation is used. A 1mm segment beside an 11mm one
    must still curve smoothly.
    """
    pts = [(0.0, 0.0), (1.0, 0.3), (12.0, 1.0), (13.0, 1.2), (24.0, 2.0)]
    out = cl.splinify([pts], tol=0.002)[0]
    worst = 0.0
    for a, b, c in zip(out, out[1:], out[2:]):
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 and n2:
            cos = max(-1.0, min(1.0, (v1[0]*v2[0] + v1[1]*v2[1]) / (n1*n2)))
            worst = max(worst, math.degrees(math.acos(cos)))
    assert worst < 30.0


def test_the_curve_does_not_bulge_outside_the_control_polygon():
    """Overshoot would push ink outside the traced shape."""
    pts = [(0.0, 0.0), (1.0, 0.0), (12.0, 0.0), (13.0, 5.0)]
    out = cl.splinify([pts], tol=0.002)[0]
    assert min(y for (_, y) in out) > -1.0
