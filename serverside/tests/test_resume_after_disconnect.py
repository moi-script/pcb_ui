"""A plot whose USB link dies picks up where the pen stopped, not from line 1.

The controller keeps drawing the moves it already holds after the link goes,
then stops where the last one ends. Reconnecting reboots it there with
machine position back at 0. Resuming restores the lost plot's work frame
around that spot and carries on from the start of the stroke that was cut.
"""
from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from grbl.streamer import DisconnectedEvent
from job import Job, modal_preamble, pen_position, resume_index
from machine import Session, make_transport

UP, DOWN = "G1 Z0.5 F200", "G1 Z-0.5 F200"


def strokes(n: int) -> list[str]:
    lines = ["G21", "G90", "G17", UP]
    for i in range(n):
        x, y = (i % 10) * 2.0, -(i // 10) * 3.0
        lines += [f"G0 X{x:g} Y{y:g} F500", DOWN, f"G1 X{x + 1.5:g} Y{y:g} F400", UP]
    return lines + ["G0 X0 Y0", "M2"]


# --- reading the file --------------------------------------------------------

def test_pen_position_follows_absolute_and_relative_moves():
    lines = ["G90", "G0 X5 Y-2", "G91", "G1 X1 Y-1", "G10 L20 P1 X0 Y0", "G90"]
    assert pen_position(lines, 2) == (5.0, -2.0)
    assert pen_position(lines, 4) == (6.0, -3.0)
    assert pen_position(lines, 6) == (6.0, -3.0), "G10 is not a move"
    assert pen_position(lines, 0) == (0.0, 0.0)


def test_resume_goes_back_to_the_pen_up_that_opens_the_stroke():
    lines = strokes(3)
    # lines[4..7] is stroke 0: travel, down, draw, up (index 7).
    draw_of_stroke_1 = 10
    assert lines[draw_of_stroke_1].startswith("G1 X")
    assert resume_index(lines, draw_of_stroke_1) == 7
    assert lines[7] == UP
    assert resume_index(lines, 0) == 0
    assert resume_index(lines, 10_000) == len(lines) - 3  # the last pen-up


def test_preamble_restores_modes_and_lifts_the_pen():
    lines = ["G20", "G91", "G1 X1 F321", UP]
    assert modal_preamble(lines, 3, 0.5, 200) == [
        "G20", "G17", "G90", "G1 Z0.5 F200", "G91", "F321",
    ]


# --- the job ------------------------------------------------------------------

class _Wire:
    def __init__(self):
        self._lock = __import__("threading").RLock()
        self.sent: list[str] = []

    def send_line(self, line):
        self.sent.append(line)

    def send_realtime(self, byte):
        pass

    def clear_outbox(self):
        return 0


def test_a_lost_link_counts_the_lines_already_on_the_wire():
    lines = strokes(5)
    job = Job(lines, _Wire(), name="board")
    job.start()
    job.acked = 12
    job.on_streamer_event(DisconnectedEvent("usb gone", unacked=3))
    snap = job.snapshot()
    assert snap["state"] == "error" and snap["resumable"]
    assert job.lines_on_wire == 15
    start, pen = job.resume_plan()
    assert start == resume_index(lines, 15)
    assert pen == pen_position(lines, 15)
    assert snap["resumeFrom"] == start + 1


def test_a_dry_check_is_not_resumable():
    job = Job(strokes(2), _Wire(), check=True)
    job.start()
    job.on_streamer_event(DisconnectedEvent("usb gone"))
    assert not job.resumable


def test_a_resumed_job_starts_part_way_with_its_preamble_first():
    wire = _Wire()
    lines = strokes(4)
    job = Job(lines, wire, start_at=11, preamble=["G21", UP])
    job.start()
    assert wire.sent[:3] == ["G21", UP, lines[11]]
    assert job.snapshot()["acked"] == 11


# --- end to end, on the simulator --------------------------------------------

def _wait(pred, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return False


def _fast(transport, factor=25.0):
    """Run the simulator's clock faster than the wall clock."""
    tick = transport.tick
    transport.tick = lambda dt: tick(dt * factor)
    return transport


def test_reconnecting_resumes_the_plot_in_its_own_frame():
    s = Session()
    s.connect(_fast(make_transport("SIM", 115200)), "SIM", 115200)
    lines = strokes(30)
    s.start_job(lines, check=False, name="board")
    assert _wait(lambda: s.job.acked > len(lines) // 3)

    # The USB link dies, but the board keeps its power: it draws out what
    # it holds and stops. Closing the port must not stop its clock.
    board = s.streamer.transport
    real_close = board.close
    board.close = lambda: None
    s.streamer._drop("usb gone")
    assert s.job.resumable
    assert _wait(lambda: board.state == "Idle" and not board._queue)
    stopped_at = [board.pos[0] - board.wco[0], board.pos[1] - board.wco[1]]
    machine_at = list(board.pos)
    real_close()

    start, pen = s.job.resume_plan()
    assert pen == pytest.approx(tuple(stopped_at), abs=1e-3), (
        "the pen stops where the last line on the wire ends"
    )

    # Reconnect: the board reboots with machine position 0 at the pen.
    s.connect(_fast(make_transport("SIM", 115200)), "SIM", 115200)
    assert s.job is not None and s.job.resumable, "the lost plot is kept"
    assert s.resume_anchor == pytest.approx(pen)

    job = s.resume_interrupted()
    assert job.acked == start and start > 0
    assert _wait(lambda: job.state == "done", timeout=30)

    # Work zero is the original corner again. The reboot put machine 0 at
    # the stop point, `machine_at` from the corner, so the corner now sits
    # at -machine_at: that is the offset Grbl must hold. (The simulator
    # moves in machine coordinates, so its offset is checked, not its pen.)
    board = s.streamer.transport
    assert board.wco[0] == pytest.approx(-machine_at[0], abs=1e-3)
    assert board.wco[1] == pytest.approx(-machine_at[1], abs=1e-3)
    s.disconnect()


def test_nothing_to_resume_is_refused():
    s = Session()
    s.connect(make_transport("SIM", 115200), "SIM", 115200)
    with pytest.raises(HTTPException) as exc:
        s.resume_interrupted()
    assert exc.value.status_code == 409
    s.disconnect()
