"""Machine setup: bed size, start corner, reversed axes — and a fast restart.

grbl_servo_z ignores Grbl's `$3` direction mask (its stepper ISR drives the
coils from the planner's raw direction bits), so reversal is rewritten at
the wire. These run against the simulator end to end.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import server
from grbl.axes import AxisMap, origin_offset, place_program
from grbl.limits import LimitError, check_jog, check_program, envelope
from grbl.profile import DEFAULT_PROFILE, with_setup
from machine import Session, make_transport, session


# --- the wire rewrite ------------------------------------------------------

def test_identity_map_leaves_lines_alone():
    m = AxisMap()
    assert m.outbound("G1 X10 Y-5 F500") == "G1 X10 Y-5 F500"
    assert m.inbound("<Idle|MPos:1.000,2.000,0.000|FS:0,0>") == (
        "<Idle|MPos:1.000,2.000,0.000|FS:0,0>"
    )


def test_reversed_x_negates_x_out_and_back():
    m = AxisMap(invert_x=True)
    assert m.outbound("G1 X10 Y-5 F500") == "G1 X-10 Y-5 F500"
    assert m.outbound("$J=G91 G21 X-1.5 F500") == "$J=G91 G21 X1.5 F500"
    assert m.inbound("<Run|MPos:-10.000,-5.000,0.000|WCO:-2.000,1.000,0.000>") == (
        "<Run|MPos:10,-5.000,0.000|WCO:2,1.000,0.000>"
    )


def test_settings_lines_pass_untouched():
    m = AxisMap(invert_x=True, invert_y=True)
    assert m.outbound("$$") == "$$"
    assert m.outbound("$X") == "$X"
    assert m.outbound("$100=250") == "$100=250"


def test_one_reversed_axis_mirrors_arcs():
    m = AxisMap(invert_y=True)
    assert m.outbound("G2 X1 Y1 I0.5 J0.5") == "G3 X1 Y-1 I0.5 J-0.5"
    # Both reversed is a rotation, not a mirror: arcs keep their sense.
    assert AxisMap(True, True).outbound("G2 X1 Y1") == "G2 X-1 Y-1"


# --- start corner ----------------------------------------------------------

PROGRAM = ["G21 G90", "G0 X0 Y0 F500", "G1 X40 Y-30 F500", "G1 X10 Y-5"]


@pytest.mark.parametrize("origin, dx, dy", [
    ("top-left", 0, 0),
    ("top-right", -40, 0),
    ("bottom-left", 0, 30),
    ("bottom-right", -40, 30),
])
def test_origin_offset_puts_that_corner_on_zero(origin, dx, dy):
    assert origin_offset(origin, (0, 40, -30, 0)) == (dx, dy)


@pytest.mark.parametrize("origin", ["top-left", "top-right", "bottom-left", "bottom-right"])
def test_a_placed_program_fits_its_corner_envelope(origin):
    profile = with_setup(DEFAULT_PROFILE, origin=origin)
    from grbl.limits import program_extents

    placed = place_program(PROGRAM, *origin_offset(origin, program_extents(PROGRAM)))
    check_program(profile, placed)  # raises if it leaves the bed


def test_placing_keeps_the_drawing_upright():
    placed = place_program(PROGRAM, 0, 30)
    assert placed[2] == "G1 X40 Y0 F500"
    assert placed[3] == "G1 X10 Y25"


def test_jog_envelope_follows_the_corner():
    bottom_right = with_setup(DEFAULT_PROFILE, origin="bottom-right")
    assert envelope(bottom_right, "X") == (-100.0, 0.0)
    assert envelope(bottom_right, "Y") == (0.0, 100.0)
    check_jog(bottom_right, (0, 0, 0), "Y", 50)
    with pytest.raises(LimitError):
        check_jog(bottom_right, (0, 0, 0), "X", 5)


# --- bed size --------------------------------------------------------------

def test_bed_may_shrink_but_not_grow_past_100mm():
    small = with_setup(DEFAULT_PROFILE, travel_x=60, travel_y=40)
    assert (small.travel_x, small.travel_y) == (60, 40)
    with pytest.raises(ValueError):
        with_setup(DEFAULT_PROFILE, travel_x=120)
    with pytest.raises(ValueError):
        with_setup(DEFAULT_PROFILE, origin="middle")


def test_setup_persists_across_sessions(tmp_path):
    path = tmp_path / "machine_setup.json"
    Session(path).update_setup(travel_x=80, origin="bottom-left", invert_y=True)

    again = Session(path)
    assert again.profile.travel_x == 80
    assert again.profile.origin == "bottom-left"
    assert again.profile.invert_y is True


# --- against the simulator -------------------------------------------------

@pytest.fixture
def sim_session():
    s = Session()
    s.connect(make_transport("SIM", 115200), "SIM", 115200)
    yield s
    s.disconnect()


def _wait(pred, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_reversed_x_moves_the_motor_the_other_way(sim_session):
    sim_session.update_setup(invert_x=True)
    board = sim_session.streamer.transport

    sim_session.streamer.send_line("$J=G91 G21 X5 F500")

    assert _wait(lambda: abs(board.pos[0] + 5) < 0.01), board.pos
    # ...while the app, and the operator, still read +5.
    assert _wait(lambda: abs(sim_session.state.mpos[0] - 5) < 0.01)


def test_setup_cannot_change_mid_plot(sim_session):
    from fastapi import HTTPException

    lines = ["G21 G90"] + [f"G1 X{i % 50} Y-{i % 30} F500" for i in range(100)]
    sim_session.start_job(lines, check=False, name="busy")
    with pytest.raises(HTTPException) as exc:
        sim_session.update_setup(invert_x=True)
    assert exc.value.status_code == 409


def test_restart_does_not_wait_for_the_queue_to_drain(sim_session):
    """Long traverses at the machine's real feed: draining would take a minute."""
    lines = ["G21 G90", "G1 Z0.5 F200"] + [
        f"G1 X{90 if i % 2 else 0} Y-{i % 80} F500" for i in range(60)
    ]
    first = sim_session.start_job(lines, check=False, name="long")
    assert _wait(lambda: first.acked >= 5, 15)
    wco_before = list(sim_session.state.wco)

    started = time.time()
    again = sim_session.restart_job()
    took = time.time() - started

    assert took < 3.0, f"restart blocked for {took:.1f}s"
    assert first.state == "stopped"
    assert again.state == "running"
    assert list(sim_session.state.wco) == wco_before
    # A reset from a completed hold is not an alarm: the new job moves.
    assert _wait(lambda: again.acked >= 3, 10)
    assert _wait(lambda: sim_session.state.state in ("Run", "Idle"), 2)
    assert again.error is None


# --- the API ---------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "_setup_path", tmp_path / "machine_setup.json")
    saved = session.profile
    c = TestClient(server.app)
    c.post("/machine/connect", json={"port": "SIM", "baud": 115200})
    yield c
    session.disconnect()
    session.profile = saved
    session.state.set_profile(saved)


def test_setup_round_trips_through_the_api(client):
    r = client.put("/machine/setup", json={"travel_x": 70, "origin": "top-right",
                                           "invert_x": True})
    assert r.status_code == 200, r.text
    got = client.get("/machine/setup").json()
    assert got["travelX"] == 70 and got["origin"] == "top-right" and got["invertX"]
    assert client.get("/machine/state").json()["conn"]["setup"]["origin"] == "top-right"


def test_setup_rejects_a_bed_larger_than_the_machine(client):
    r = client.put("/machine/setup", json={"travel_y": 150})
    assert r.status_code == 400
    assert "100" in r.json()["detail"]


def test_disconnect_mid_plot_is_refused_unless_forced(client):
    lines = ["G21 G90"] + [f"G1 X{i % 50} Y-{i % 30} F500" for i in range(100)]
    session.start_job(lines, check=False, name="busy")

    assert client.post("/machine/disconnect").status_code == 409
    assert session.streamer is not None
    assert client.post("/machine/disconnect?force=true").status_code == 200


def test_connect_releases_a_dropped_link_before_opening(client):
    old = session.streamer
    old._drop("test: link gone")
    assert old.transport._closed, "a dropped link must let go of the port"

    r = client.post("/machine/connect", json={"port": "SIM", "baud": 115200})
    assert r.status_code == 200
    assert session.streamer is not old
