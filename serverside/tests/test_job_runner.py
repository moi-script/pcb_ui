"""Streaming a whole file: progress, pause, stop, and honest failure.

Every test runs against the simulator, which withholds `ok` under
backpressure — the only way to prove flow control works rather than
accidentally appearing to.
"""
from __future__ import annotations

import time

import pytest

from grbl.sim import GrblSim
from grbl.streamer import Streamer
from job import Job, load_lines

SQUARE = """
G21 G90
G0 Z2.0
G0 X0 Y0
G1 Z0 F500      ; pen down
G1 X10 Y0 F1200
G1 X10 Y10
G1 X0 Y10
G1 X0 Y0
G0 Z2.0         ; pen up
"""


# Simulated seconds per loop, advanced by hand rather than read off the
# wall clock. A real plot of a few hundred moves takes minutes; driving the
# model's clock directly keeps these tests to a wall-clock second while
# still filling the planner between ticks, which is what produces the
# backpressure they exist to exercise.
SIM_DT = 0.02


def step(sim, streamer, n=1):
    for _ in range(n):
        sim.tick(SIM_DT)
        streamer.pump()


def run_to_completion(job, streamer, sim, max_steps=200_000):
    for _ in range(max_steps):
        step(sim, streamer)
        if job.state in ("done", "error", "stopped"):
            return job.snapshot()
    raise AssertionError(f"job never finished; state={job.state}")


@pytest.fixture
def rig():
    """A simulator, a streamer, and a late-bound event hook.

    Streamer takes its callback at construction and stores it privately, but
    a Job needs its Streamer to exist first. Session breaks that circle by
    forwarding from a method that reads `self.job` at call time; this
    mirrors it, so a test can assign `streamer.on_event` after the fact.
    """
    sim = GrblSim()
    streamer = Streamer(
        sim,
        rx_buffer=128,
        on_event=lambda e: (streamer.on_event(e) if streamer.on_event else None),
    )
    streamer.on_event = None
    yield sim, streamer
    streamer.stop()


def test_load_lines_strips_comments_and_blanks():
    assert load_lines(SQUARE) == [
        "G21 G90", "G0 Z2.0", "G0 X0 Y0", "G1 Z0 F500",
        "G1 X10 Y0 F1200", "G1 X10 Y10", "G1 X0 Y10", "G1 X0 Y0", "G0 Z2.0",
    ]


def test_a_whole_job_streams_and_every_line_is_acknowledged(rig):
    sim, streamer = rig
    lines = load_lines(SQUARE)
    job = Job(lines, streamer, name="square")
    streamer.on_event = job.on_streamer_event
    job.start()

    snap = run_to_completion(job, streamer, sim)
    assert snap["state"] == "done"
    assert snap["acked"] == snap["total"] == len(lines)
    assert snap["error"] is None


def test_the_rx_budget_is_never_oversent(rig):
    """The simulator complains if the host oversends; a long file proves it."""
    sim, streamer = rig
    lines = [f"G1 X{i % 50} Y{i % 30} F1200" for i in range(400)]
    job = Job(lines, streamer)
    streamer.on_event = job.on_streamer_event
    job.start()

    for _ in range(200_000):
        step(sim, streamer)
        assert streamer.pending_bytes <= streamer.rx_buffer
        if job.state != "running":
            break

    assert job.snapshot()["state"] == "done"


def test_pause_stops_feeding_and_resume_continues(rig):
    sim, streamer = rig
    lines = [f"G1 X{i % 50} F1200" for i in range(200)]
    job = Job(lines, streamer)
    streamer.on_event = job.on_streamer_event
    job.start()

    step(sim, streamer, 20)
    job.pause()
    sent_at_pause = job.snapshot()["sent"]

    step(sim, streamer, 30)
    assert job.snapshot()["sent"] == sent_at_pause, "paused job kept feeding"
    assert job.state == "paused"

    job.resume()
    snap = run_to_completion(job, streamer, sim)
    assert snap["state"] == "done"
    assert snap["acked"] == len(lines)


def test_stop_mid_job_ends_it_as_stopped(rig):
    sim, streamer = rig
    lines = [f"G1 X{i % 50} F1200" for i in range(200)]
    job = Job(lines, streamer)
    streamer.on_event = job.on_streamer_event
    job.start()

    step(sim, streamer, 10)
    job.stop()

    snap = job.snapshot()
    assert snap["state"] == "stopped"
    assert snap["sent"] < snap["total"]


def test_an_error_reply_aborts_and_names_the_line(rig):
    sim, streamer = rig
    lines = ["G21 G90", "G1 X10 F600", "G1 Q999", "G1 X20 F600"]
    job = Job(lines, streamer)
    streamer.on_event = job.on_streamer_event
    job.start()

    snap = run_to_completion(job, streamer, sim)
    assert snap["state"] == "error"
    assert snap["errorLine"] == 3
    assert "Q999" in snap["error"]


def test_check_mode_brackets_the_job_with_dollar_C(rig):
    sim, streamer = rig
    job = Job(load_lines(SQUARE), streamer, check=True)
    streamer.on_event = job.on_streamer_event
    job.start()

    snap = run_to_completion(job, streamer, sim)
    assert snap["state"] == "done"
    assert snap["check"] is True
    step(sim, streamer, 20)      # let the closing $C reach the controller
    assert sim.check_mode is False, "check mode must be toggled back off"


def test_check_mode_is_left_off_even_when_the_job_errors(rig):
    """$C is a toggle, not a flag. Leaking it on makes the NEXT job silently
    validate instead of plotting, which looks like a machine that ignores
    you."""
    sim, streamer = rig
    job = Job(["G21 G90", "G1 Q999", "G1 X10 F600"], streamer, check=True)
    streamer.on_event = job.on_streamer_event
    job.start()

    snap = run_to_completion(job, streamer, sim)
    assert snap["state"] == "error"
    step(sim, streamer, 20)
    assert sim.check_mode is False


def test_a_disconnect_mid_job_fails_the_job_visibly(rig):
    sim, streamer = rig
    lines = [f"G1 X{i % 50} F1200" for i in range(200)]
    job = Job(lines, streamer)
    streamer.on_event = job.on_streamer_event
    job.start()

    step(sim, streamer, 10)
    streamer._drop("cable pulled")

    snap = run_to_completion(job, streamer, sim)
    assert snap["state"] == "error"
    assert "cable pulled" in snap["error"]


def test_a_stopped_job_leaves_the_machine_able_to_run_the_next_one(rig):
    """Stop feed-holds to halt promptly, then releases.

    A controller left held has a queue it can never finish, and the next job
    feeds into a machine that never moves — which looks exactly like a dead
    machine, from a button labelled Stop.
    """
    sim, streamer = rig
    lines = [f"G1 X{(i % 40) + 1} F1200" for i in range(200)]

    first = Job(lines, streamer, name="one")
    streamer.on_event = first.on_streamer_event
    first.start()
    step(sim, streamer, 10)
    first.stop()
    step(sim, streamer, 400)

    assert sim.state != "Hold", "stop left the controller feed-held"

    second = Job(lines[:20], streamer, name="two")
    streamer.on_event = second.on_streamer_event
    second.start()
    snap = run_to_completion(second, streamer, sim)
    assert snap["state"] == "done"
    assert snap["acked"] == 20
