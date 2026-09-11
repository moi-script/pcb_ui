"""The one connection, exercised against the simulator.

No hardware, no COM port: `make_transport("SIM", ...)` hands back a modelled
GRBL 1.1 controller, which is the whole point of porting the simulator.
"""
from __future__ import annotations

import pytest

from machine import Session, make_transport


@pytest.fixture
def session():
    s = Session()
    yield s
    s.disconnect()


def test_sim_port_yields_the_simulator():
    from grbl.sim import GrblSim

    assert isinstance(make_transport("SIM", 115200), GrblSim)


def test_connect_reports_the_firmware_banner(session):
    firmware = session.connect(make_transport("SIM", 115200), "SIM", 115200)

    assert "Grbl" in firmware
    assert session.state.connected is True
    assert session.state.port == "SIM"


def test_require_refuses_when_not_connected(session):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        session.require()
    assert exc.value.status_code == 409


def test_disconnect_clears_the_connection(session):
    session.connect(make_transport("SIM", 115200), "SIM", 115200)
    session.disconnect()

    assert session.state.connected is False
    assert session.streamer is None


def test_the_whole_link_shares_one_lock(session):
    """State, streamer and job are guarded by a single re-entrant lock.

    They call into each other in both directions — the streamer dispatches
    into the job and the state, the job feeds back into the streamer — so
    separate locks get taken in opposite orders by the request thread and
    the streamer thread. One lock per connection is what makes that class
    of deadlock impossible rather than merely unlikely.
    """
    session.connect(make_transport("SIM", 115200), "SIM", 115200)

    assert session.state._lock is session.streamer._lock

    job = session.start_job(["G21 G90", "G0 X1 Y1"], check=False, name="lockcheck")
    assert job._lock is session.streamer._lock


def test_restart_runs_the_same_file_again_from_the_top(session):
    """One press instead of e-stop, re-zero, plot again.

    The point of the endpoint is that work zero survives: a botched plot
    should cost the plot, not the corner that was set by hand.
    """
    import time

    session.connect(make_transport("SIM", 115200), "SIM", 115200)
    # Short moves at a traverse feed: the point is the restart, and a file
    # whose planner takes a minute to drain only tests the clock.
    lines = ["G21 G90", "G1 Z0.5 F500"] + [
        f"G1 X{i % 4} Y{(i * 2) % 3} F3000" for i in range(40)
    ]
    first = session.start_job(lines, check=False, name="restart-me")

    deadline = time.time() + 15
    while first.acked < 5 and time.time() < deadline:
        time.sleep(0.02)
    assert first.acked >= 5, "the job never got going, so restart proves nothing"

    wco_before = list(session.state.wco)
    again = session.restart_job()

    assert again is not first
    assert session.job is again
    assert again.lines == lines
    assert again.name == "restart-me"
    assert again.check is False
    assert again.acked < first.acked
    assert first.state == "stopped"
    # Work zero untouched — the whole reason this exists rather than e-stop.
    assert list(session.state.wco) == wco_before


def test_restart_without_a_job_is_refused(session):
    from fastapi import HTTPException

    session.connect(make_transport("SIM", 115200), "SIM", 115200)
    with pytest.raises(HTTPException) as exc:
        session.restart_job()
    assert exc.value.status_code == 409
