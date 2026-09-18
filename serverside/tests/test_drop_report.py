"""A plot that loses the machine leaves a report behind, not just an error."""
from __future__ import annotations

import time

import pytest

from grbl.trace import KIND_LABEL, LOOKBACK
from machine import Session, make_transport

# A square drawn over and over: pen moves (Z) and draws (X/Y) both in play.
LINES = ["G21", "G90"] + [
    line
    for i in range(60)
    for line in (
        "G1 Z-0.5 F2000", f"G1 X{10 + i % 3} Y0 F3000", f"G1 X{10 + i % 3} Y10",
        "G1 X0 Y10", "G1 X0 Y0", "G1 Z0.5 F2000",
    )
]


@pytest.fixture
def session(tmp_path):
    s = Session(drops_path=tmp_path / "disconnects.json")
    s.connect(make_transport("SIM", 115200), "SIM", 115200)
    yield s
    s.disconnect()


def _plot_until_moving(session):
    job = session.start_job(LINES, check=False, name="square")
    deadline = time.time() + 5
    while time.time() < deadline:
        if session.state.status_at is not None and job.acked >= 5 \
                and session.state.state == "Run":
            return job
        time.sleep(0.02)
    pytest.fail(f"plot never got going: acked={job.acked} state={session.state.state}")


def test_a_dropped_link_reports_the_line_the_pen_was_on(session, tmp_path):
    job = _plot_until_moving(session)
    session.streamer._drop("cable pulled")

    report = job.snapshot()["disconnect"]
    assert report is not None
    assert report["cause"] == "link_lost"
    assert report["reason"] == "cable pulled"
    assert report["kind"] in KIND_LABEL
    assert report["pos"] is not None
    assert report["statusAge"] is not None and report["statusAge"] < 2
    if report["line"] is not None:
        assert report["acked"] - LOOKBACK <= report["line"] <= report["acked"]
        assert LINES[report["line"] - 1] == report["code"]
        assert any(c["role"] == "match" for c in report["context"])

    history = session.drops.snapshot()
    assert history["reports"][0]["headline"] == report["headline"]
    assert sum(history["tally"].values()) == 1
    # Kept on disk for the next run of the backend.
    assert Session(drops_path=tmp_path / "disconnects.json").drops.snapshot() == history


def test_a_controller_restart_is_reported_as_a_reset(session):
    job = _plot_until_moving(session)
    with session.streamer._lock:
        session.streamer._dispatch("Grbl 1.1f ['$' for help]")

    report = job.snapshot()["disconnect"]
    assert report["cause"] == "controller_reset"
    assert report["headline"].startswith("The controller restarted")


def test_pressing_disconnect_is_not_a_drop(session):
    """Only a lost machine is reported; the operator's own Disconnect is not."""
    job = _plot_until_moving(session)
    session.disconnect()

    assert job.disconnect is None
    assert session.drops.snapshot()["reports"] == []


def test_a_g_code_error_is_not_a_drop(session):
    job = session.start_job(["G21", "$H"], check=False, name="bad")
    deadline = time.time() + 3
    while job.state == "running" and time.time() < deadline:
        time.sleep(0.02)

    assert job.state == "error"
    assert job.disconnect is None
    assert session.drops.snapshot()["reports"] == []
