"""Image bytes in, strokes in millimetres out."""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from tracer import emit
from tracer.pipeline import TraceError, TraceParams, trace_image


def _png(draw_fn, size=(200, 200), bg=255) -> bytes:
    img = Image.new("L", size, bg)
    draw_fn(ImageDraw.Draw(img))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _line_png() -> bytes:
    return _png(lambda d: d.line((20, 100, 180, 100), fill=0, width=6))


def _two_lines_png() -> bytes:
    def go(d):
        d.line((20, 60, 180, 60), fill=0, width=6)
        d.line((20, 140, 180, 140), fill=0, width=6)
    return _png(go)


def _disc_png() -> bytes:
    return _png(lambda d: d.ellipse((60, 60, 140, 140), fill=0))


def _bar_png() -> bytes:
    """A filled bar: 120 x 30 px, so its medial axis is a real line.

    A disc is the wrong subject for a centreline test - its medial axis is a
    single point, so thinning yields one pixel and no polyline at all.
    """
    return _png(lambda d: d.rectangle((40, 85, 160, 115), fill=0))


def _dark_bars_png() -> bytes:
    """Bars covering ~half the sheet: mostly dark, but still traceable."""
    def go(d):
        for top in range(10, 200, 24):
            d.rectangle((0, top, 199, top + 12), fill=0)
    return _png(go)


def _total_length(strokes) -> float:
    return sum(
        sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            for a, b in zip(s, s[1:]))
        for s in strokes
    )


def test_a_single_line_traces_to_one_stroke():
    strokes, _ = trace_image(_line_png(), TraceParams(size_mm=50))
    assert len(strokes) == 1


def test_size_mm_sets_the_longest_edge():
    strokes, _ = trace_image(_line_png(), TraceParams(size_mm=50))
    minx, miny, maxx, maxy = emit.bounds(strokes)
    assert max(maxx - minx, maxy - miny) == pytest.approx(50, abs=3.0)


def test_size_scales_linearly():
    a, _ = trace_image(_line_png(), TraceParams(size_mm=50))
    b, _ = trace_image(_line_png(), TraceParams(size_mm=100))
    wa = emit.bounds(a)[2] - emit.bounds(a)[0]
    wb = emit.bounds(b)[2] - emit.bounds(b)[0]
    assert wb == pytest.approx(wa * 2, rel=0.05)


def test_size_zero_fits_the_bed():
    strokes, _ = trace_image(
        _line_png(), TraceParams(size_mm=0, bed=(300.0, 200.0), margin=10.0))
    minx, miny, maxx, maxy = emit.bounds(strokes)
    assert maxx - minx <= 300.0 - 2 * 10.0 + 0.01
    assert maxy - miny <= 200.0 - 2 * 10.0 + 0.01


def test_two_lines_trace_to_two_strokes():
    strokes, _ = trace_image(_two_lines_png(), TraceParams(size_mm=50))
    assert len(strokes) == 2


def test_centerline_of_a_bar_runs_down_its_middle():
    """A 120 x 30 px bar at 50 mm is 50 x 12.5 mm. Its medial axis is one line
    along the long dimension, so the trace is roughly its length - nowhere
    near the ~125 mm it would take to go around the outside."""
    strokes, _ = trace_image(_bar_png(), TraceParams(size_mm=50))
    assert _total_length(strokes) < 60.0


def test_outline_of_a_bar_is_much_longer_than_its_centerline():
    """The mode difference, made concrete: around versus along."""
    inner, _ = trace_image(_bar_png(), TraceParams(size_mm=50))
    outer, _ = trace_image(_bar_png(), TraceParams(size_mm=50, mode="outline"))
    assert _total_length(outer) > _total_length(inner) * 2


def test_a_filled_disc_has_no_centerline():
    """The documented limitation, pinned so it cannot regress into silence.

    A perfect disc's medial axis is its centre point, so thinning leaves a
    single pixel and there is no path to walk. The user gets a readable error,
    not an empty plot.
    """
    with pytest.raises(TraceError):
        trace_image(_disc_png(), TraceParams(size_mm=50))


def test_outline_of_a_disc_is_a_closed_loop():
    strokes, _ = trace_image(
        _disc_png(), TraceParams(size_mm=50, mode="outline"))
    assert strokes
    first, last = strokes[0][0], strokes[0][-1]
    assert first[0] == pytest.approx(last[0], abs=0.01)
    assert first[1] == pytest.approx(last[1], abs=0.01)


def test_geometry_starts_at_the_origin():
    strokes, _ = trace_image(_two_lines_png(), TraceParams(size_mm=50))
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    assert min(xs) == pytest.approx(0, abs=0.01)
    assert min(ys) == pytest.approx(0, abs=0.01)


def test_blank_image_is_a_readable_error():
    with pytest.raises(TraceError) as e:
        trace_image(_png(lambda d: None), TraceParams(size_mm=50))
    msg = str(e.value).lower()
    assert "invert" in msg or "threshold" in msg


def test_not_an_image_is_a_readable_error():
    with pytest.raises(TraceError):
        trace_image(b"this is not an image", TraceParams(size_mm=50))


def test_unknown_mode_is_rejected():
    with pytest.raises(TraceError):
        trace_image(_line_png(), TraceParams(size_mm=50, mode="nonsense"))


def test_unknown_preset_is_rejected():
    with pytest.raises(TraceError):
        trace_image(_line_png(), TraceParams(size_mm=50, preset="nonsense"))


def test_info_reports_coverage_and_count():
    strokes, info = trace_image(_two_lines_png(), TraceParams(size_mm=50))
    assert info["strokeCount"] == len(strokes)
    assert 0.0 <= info["inkCoverage"] <= 1.0
    assert isinstance(info["warnings"], list)


def test_mostly_dark_image_warns():
    """Heavy art still traces, but the polarity is worth flagging."""
    _strokes, info = trace_image(_dark_bars_png(), TraceParams(size_mm=50))
    assert info["inkCoverage"] > 0.35
    assert any("dark" in w.lower() for w in info["warnings"])


def test_pcb_preset_runs():
    strokes, _ = trace_image(
        _two_lines_png(), TraceParams(size_mm=50, preset="pcb"))
    assert strokes


# --- fill mode -------------------------------------------------------------

def _solid_square_png() -> bytes:
    return _png(lambda d: d.rectangle((50, 50, 150, 150), fill=0))


def test_fill_covers_far_more_than_outline():
    outline, _ = trace_image(
        _solid_square_png(), TraceParams(size_mm=50, mode="outline"))
    filled, _ = trace_image(
        _solid_square_png(),
        TraceParams(size_mm=50, mode="fill", hatch_spacing_mm=0.5))
    assert _total_length(filled) > _total_length(outline) * 5


def test_fill_length_matches_area_over_spacing():
    """The square is 50 mm on a side once fitted, so ~2500 mm^2 at 0.5 mm
    spacing is ~5000 mm of hatch, plus 200 mm of outline."""
    filled, _ = trace_image(
        _solid_square_png(),
        TraceParams(size_mm=50, mode="fill", hatch_spacing_mm=0.5))
    assert _total_length(filled) == pytest.approx(5000 + 200, rel=0.15)


def test_fill_spacing_is_honoured_at_any_size():
    """The regression that matters: hatching before the fit and scaling after
    would multiply the spacing by the scale factor."""
    for size in (25, 50, 100):
        filled, _ = trace_image(
            _solid_square_png(),
            TraceParams(size_mm=size, mode="fill", hatch_spacing_mm=0.5))
        area = size * size
        assert _total_length(filled) == pytest.approx(
            area / 0.5 + 4 * size, rel=0.15), f"spacing drifted at {size} mm"


def test_fill_includes_the_outline():
    filled, _ = trace_image(
        _solid_square_png(),
        TraceParams(size_mm=50, mode="fill", hatch_spacing_mm=0.5))
    closed = [s for s in filled if s[0] == s[-1]]
    assert closed, "the silhouette should still be drawn"


def test_cross_hatch_is_denser_than_single():
    one, _ = trace_image(_solid_square_png(), TraceParams(
        size_mm=50, mode="fill", hatch_spacing_mm=0.8))
    two, _ = trace_image(_solid_square_png(), TraceParams(
        size_mm=50, mode="fill", hatch_spacing_mm=0.8, hatch_cross=True))
    assert _total_length(two) > _total_length(one) * 1.6


def test_a_disc_can_be_filled_even_though_it_has_no_centerline():
    """The case that motivated this: a solid shape has no medial axis to draw,
    but it can absolutely be covered."""
    with pytest.raises(TraceError):
        trace_image(_disc_png(), TraceParams(size_mm=50))
    filled, _ = trace_image(
        _disc_png(), TraceParams(size_mm=50, mode="fill", hatch_spacing_mm=0.5))
    assert _total_length(filled) > 100


def test_impossible_spacing_is_a_readable_error():
    with pytest.raises(TraceError) as e:
        trace_image(_solid_square_png(), TraceParams(
            size_mm=5, mode="fill", hatch_spacing_mm=0.001))
    assert "spacing" in str(e.value).lower()


def test_zero_spacing_is_refused():
    with pytest.raises(TraceError):
        trace_image(_solid_square_png(), TraceParams(
            size_mm=50, mode="fill", hatch_spacing_mm=0))
