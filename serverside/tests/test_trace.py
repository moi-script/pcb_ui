"""The drop report: which line the pen was on, and what that points to."""
from __future__ import annotations

import json

from grbl.trace import DropHistory, build_report, classify, locate, replay

# What pcb_gcode.py emits for two traces: pen-up is Z0.5, pen-down Z-0.5.
FILE = [
    "G21",              # 1
    "G90",              # 2
    "G1 Z0.5 F200",     # 3  pen up (already up: moves nothing)
    "G0 X10 Y10 F500",  # 4  travel
    "G1 Z-0.5 F200",    # 5  pen down
    "G1 X30 Y10 F500",  # 6  draw
    "G1 Z0.5 F200",     # 7  pen up
    "G0 X30 Y40 F500",  # 8  travel
    "G1 Z-0.5 F200",    # 9  pen down
    "G1 X50 Y40 F500",  # 10 draw
    "G1 Z0.5 F200",     # 11 pen up
]
START = (0.0, 0.0, 0.5)


def test_replay_tracks_position_and_moving_axes():
    moves = replay(FILE, START)
    assert moves[2].axes == ""                     # already at Z0.5
    assert moves[3].axes == "XY"
    assert moves[3].end == (10.0, 10.0, 0.5)
    assert moves[4].axes == "Z"
    assert moves[5].start == (10.0, 10.0, -0.5)
    assert moves[5].end == (30.0, 10.0, -0.5)


def test_replay_handles_relative_and_inches():
    moves = replay(["G91", "G0 X1 Y2", "G0 X1", "G20", "G90", "G0 X1"])
    assert moves[1].end == (1.0, 2.0, 0.0)
    assert moves[2].end == (2.0, 2.0, 0.0)
    assert moves[5].end == (25.4, 2.0, 0.0)


def test_replay_ignores_dwell_and_offset_numbers():
    moves = replay(["G0 X5", "G4 P1", "G10 L20 P1 X0", "$J=G91 X3 F100"])
    assert [m.axes for m in moves] == ["X", "", "", ""]
    assert moves[3].end == (5.0, 0.0, 0.0)


def test_a_point_mid_trace_is_an_exact_match_on_that_line():
    moves = replay(FILE, START)
    move, candidates, confidence = locate(moves, (20.0, 10.0, -0.5), 0, 10)
    assert move.index + 1 == 6
    assert confidence == "exact"
    assert candidates == [5]


def test_a_point_mid_pen_drop_is_a_z_move():
    moves = replay(FILE, START)
    move, _, confidence = locate(moves, (10.0, 10.0, 0.0), 0, 10)
    assert move.index + 1 == 5
    assert confidence == "exact"
    assert classify(move, "Run") == "z_down"


def test_a_corner_matches_both_lines_and_picks_the_newer():
    moves = replay(FILE, START)
    # (30,10,-0.5) is where the draw on line 6 ends and the lift on 7 starts.
    move, candidates, confidence = locate(moves, (30.0, 10.0, -0.5), 0, 10)
    assert candidates == [5, 6]
    assert move.index + 1 == 7
    assert confidence == "likely"


def test_search_stays_inside_the_window():
    moves = replay(FILE, START)
    # Line 10 draws through (40,40); the window stops at line 8.
    move, _, confidence = locate(moves, (40.0, 40.0, -0.5), 0, 7)
    assert move is None
    assert confidence == "none"


def test_classify_names_each_kind_of_motion():
    moves = replay(FILE, START)
    assert classify(moves[3], "Run") == "travel"
    assert classify(moves[5], "Run") == "draw"
    assert classify(moves[6], "Run") == "z_up"
    assert classify(moves[5], "Idle") == "idle"
    assert classify(moves[5], "Hold:0") == "idle"
    assert classify(None, "Run") == "unknown"


def _report(**over):
    args = dict(
        lines=FILE, acked=11, sent=11, job_name="board", cause="link_lost",
        reason="PermissionError", pos=[10.0, 10.0, 0.0], machine_state="Run",
        status_age=0.2, origin=START,
    )
    args.update(over)
    return build_report(**args)


def test_report_names_the_line_the_axis_and_why():
    r = _report()
    assert r["line"] == 5
    assert r["code"] == "G1 Z-0.5 F200"
    assert r["axes"] == "Z"
    assert r["kind"] == "z_down"
    assert "line 5" in r["headline"]
    assert "servo" in r["explanation"]
    roles = {c["n"]: c["role"] for c in r["context"]}
    assert roles[5] == "match"
    assert roles[4] == "before"
    assert roles[6] == "queued"


def test_report_marks_lines_that_were_sent_but_not_accepted():
    r = _report(acked=6, sent=8, pos=[20.0, 10.0, -0.5])
    roles = {c["n"]: c["role"] for c in r["context"]}
    assert r["line"] == 6 and r["kind"] == "draw"
    assert roles[7] == "queued"      # sent, still waiting for its ok
    assert roles[9] == "unsent"


def test_report_without_a_position_says_so():
    r = _report(pos=None, machine_state="Run", status_age=None)
    assert r["kind"] == "unknown"
    assert r["line"] is None
    assert r["confidence"] == "none"
    assert "No position report" in r["explanation"]


def test_a_stale_position_is_called_out():
    r = _report(status_age=3.0)
    assert "3.0 s old" in r["explanation"]


def test_a_controller_restart_reads_as_power():
    r = _report(cause="controller_reset")
    assert r["headline"].startswith("The controller restarted")
    assert "power" in r["explanation"]


def test_history_keeps_the_newest_and_counts_kinds(tmp_path):
    path = tmp_path / "drops.json"
    history = DropHistory(path)
    for i in range(DropHistory.LIMIT + 3):
        history.add({"kind": "z_down" if i % 2 else "draw", "n": i})
    snap = history.snapshot()
    assert len(snap["reports"]) == DropHistory.LIMIT
    assert snap["reports"][0]["n"] == DropHistory.LIMIT + 2   # newest first
    assert snap["tally"]["z_down"] + snap["tally"]["draw"] == DropHistory.LIMIT

    again = DropHistory(path)
    assert again.snapshot() == snap
    again.clear()
    assert json.loads(path.read_text()) == []
    assert DropHistory(path).snapshot()["reports"] == []


def test_history_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "drops.json"
    path.write_text("{not json")
    assert DropHistory(path).snapshot()["reports"] == []
