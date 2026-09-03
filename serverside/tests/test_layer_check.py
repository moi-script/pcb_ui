"""Only single-layer boards can be plotted.

A pen plotter draws one face of the work. A double-sided board cannot be
plotted faithfully: half its copper is on the other side, and the connectivity
depends on crossings the pen cannot make. Before this check the router quietly
plotted F.Cu and dropped the rest, so a board could come back looking fine and
be missing most of itself.

So the upload is rejected, and the message says what was found.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import server
from pcb_read import extract_wiring


def track(layer: str, x: float = 0.0) -> dict:
    return {
        "type": "track",
        "net": "N",
        "layer": layer,
        "start": (x, 0.0),
        "end": (x + 5.0, 3.0),
        "width_mm": 0.25,
    }


def via(x: float = 1.0) -> dict:
    return {
        "type": "via",
        "net": "N",
        "position": (x, 1.0),
        "drill_mm": 0.4,
        "size_mm": 0.8,
    }


def build(wiring: list) -> dict:
    return server.build_board(wiring, name="b", filename="b.kicad_pcb")


class TestSingleLayerIsAccepted:
    def test_front_copper_only(self):
        board = build([track("F.Cu"), track("F.Cu", 10)])
        assert board["fcu"] == 2
        assert board["bcu"] == 0

    def test_back_copper_only_plots_the_back(self):
        # A board routed entirely on B.Cu is still single-layer. build_board
        # already falls back to the layer that has copper.
        board = build([track("B.Cu"), track("B.Cu", 10)])
        assert board["bcu"] == 2
        assert board["layer"] == "B.Cu"
        assert "G1 X" in board["gcode"], "a back-only board must still route"

    def test_a_single_layer_board_needs_no_override(self):
        board = build([track("F.Cu")])
        assert board["gcode"]


class TestTwoLayersAreRejected:
    def test_copper_on_both_layers(self):
        with pytest.raises(HTTPException) as e:
            build([track("F.Cu"), track("B.Cu")])
        assert e.value.status_code == 400

    def test_a_via_rejects_even_a_single_layer_board(self):
        # A via exists to cross layers; a pen cannot follow it.
        with pytest.raises(HTTPException) as e:
            build([track("F.Cu"), via()])
        assert e.value.status_code == 400

    def test_one_stray_back_track_is_still_two_layers(self):
        with pytest.raises(HTTPException) as e:
            build([track("F.Cu") for _ in range(50)] + [track("B.Cu")])
        assert e.value.status_code == 400


class TestTheMessageIsUseful:
    def test_it_reports_the_count_on_each_layer(self):
        with pytest.raises(HTTPException) as e:
            build([track("F.Cu"), track("F.Cu", 6), track("B.Cu")])
        detail = e.value.detail
        assert "2" in detail and "1" in detail
        assert "F.Cu" in detail and "B.Cu" in detail

    def test_it_reports_vias_when_that_is_the_reason(self):
        with pytest.raises(HTTPException) as e:
            build([track("F.Cu"), via(), via(2)])
        assert "via" in e.value.detail.lower()

    def test_it_says_what_to_do_about_it(self):
        with pytest.raises(HTTPException) as e:
            build([track("F.Cu"), track("B.Cu")])
        assert "single" in e.value.detail.lower()

    def test_an_empty_file_still_reports_no_copper(self):
        with pytest.raises(HTTPException) as e:
            build([])
        assert "no copper" in e.value.detail.lower()


class TestAgainstTheRealSampleBoards:
    @pytest.mark.parametrize("path", [
        "labExam.kicad_pcb",
        "newProject.kicad_pcb",
        "lab3/lab3.kicad_pcb",
    ])
    def test_the_shipped_boards_are_double_sided_and_rejected(self, path):
        """Every sample board in this repo is 2-layer, so all are refused.

        Pinned deliberately: if a genuinely single-layer sample is added later,
        this test should be updated rather than the check loosened.
        """
        with open(path, encoding="utf-8", errors="replace") as f:
            wiring = extract_wiring(f.read())
        with pytest.raises(HTTPException) as e:
            build(wiring)
        assert e.value.status_code == 400
