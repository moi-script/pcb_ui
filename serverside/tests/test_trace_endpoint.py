"""The /trace endpoint's board document.

These exercise `build_board_from_strokes` directly rather than through HTTP:
the document shape is the contract every downstream consumer depends on, and
it is worth testing without needing MongoDB up.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from tracer import TraceParams, trace_image


def _two_lines_png() -> bytes:
    img = Image.new("L", (200, 200), 255)
    d = ImageDraw.Draw(img)
    d.line((20, 60, 180, 60), fill=0, width=6)
    d.line((20, 140, 180, 140), fill=0, width=6)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def doc():
    import server
    params = TraceParams(size_mm=50)
    strokes, info = trace_image(_two_lines_png(), params)
    return server.build_board_from_strokes(
        strokes, name="sample", filename="sample.png",
        params=params, info=info)


def test_document_has_every_field_out_board_reads(doc):
    for key in ("name", "filename", "width", "height", "fcu", "bcu", "nets",
                "layer", "gcodeLines", "drawMoves", "travelMoves",
                "penUpBefore", "penUpAfter", "size", "estMinutes", "gcode",
                "strokes"):
        assert key in doc, f"missing {key}"


def test_source_marks_it_as_traced(doc):
    assert doc["source"] == "image"


def test_strokes_are_stored(doc):
    assert len(doc["strokes"]) == 2


def test_no_flattened_tracks_are_stored(doc):
    """Strokes are the only geometry. The preview draws them directly, so a
    two-point-per-segment copy would be dead weight - it was 63% of the
    document on a dense trace."""
    assert "tracks" not in doc


def test_a_thumbnail_copy_is_stored(doc):
    assert doc["thumbStrokes"]
    assert (sum(len(s) for s in doc["thumbStrokes"])
            <= sum(len(s) for s in doc["strokes"]))


def test_gcode_is_a_string_not_a_list(doc):
    assert isinstance(doc["gcode"], str)
    assert "G21" in doc["gcode"]


def test_gcode_line_count_matches_the_string(doc):
    # build_board appends a trailing newline; the count is of real lines
    assert doc["gcodeLines"] == len(doc["gcode"].rstrip("\n").split("\n"))


def test_frame_gcode_never_draws(doc):
    assert "G1 Z" not in doc["frameGcode"]


def test_trace_params_are_kept_for_retracing(doc):
    assert doc["traceParams"]["size_mm"] == 50
    assert doc["traceParams"]["mode"] == "centerline"
    assert doc["traceParams"]["preset"] == "line"


def test_counts_are_honest_for_a_single_layer_job(doc):
    assert doc["fcu"] == len(doc["strokes"])
    assert doc["bcu"] == 0
    assert doc["nets"] == 1
    assert doc["layer"] == "F.Cu"


def test_geometry_starts_at_the_origin(doc):
    xs = [p[0] for s in doc["strokes"] for p in s]
    ys = [p[1] for s in doc["strokes"] for p in s]
    assert min(xs) == pytest.approx(0, abs=0.01)
    assert min(ys) == pytest.approx(0, abs=0.01)


def test_size_string_matches_the_bounds(doc):
    # same format build_board uses, so the UI tile reads identically
    assert doc["size"] == f"{doc['width']} × {doc['height']}"


def test_strokes_are_json_safe_lists(doc):
    """Mongo and JSON both need lists, not tuples."""
    assert isinstance(doc["strokes"], list)
    assert isinstance(doc["strokes"][0], list)
    assert isinstance(doc["strokes"][0][0], list)
