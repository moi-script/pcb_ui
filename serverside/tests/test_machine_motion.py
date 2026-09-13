"""Jog, zero, home, e-stop — against the simulator.

The simulator models the planner queue, so a jog actually moves the reported
position rather than merely being accepted.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import server
from machine import session


@pytest.fixture
def client():
    c = TestClient(server.app)
    c.post("/machine/connect", json={"port": "SIM", "baud": 115200})
    yield c
    session.disconnect()


def settle(client, timeout=5.0):
    """Wait until the machine is idle with nothing of ours outstanding.

    A bare `state == "Idle"` read is not enough right after sending a move.
    GRBL acknowledges a line when it has parsed and QUEUED it, so both the
    cached state and `statusQuiet` can still describe the machine as idle at
    the old position while the move sits in the planner. This waits for
    reports genuinely newer than the moment of the call — the status poll
    runs at 5 Hz, so two fresh reports is a fifth of a second — and for the
    machine to be idle and quiet on one of them.
    """
    deadline = time.time() + timeout
    seq0 = client.get("/machine/state").json()["statusSeq"]
    while time.time() < deadline:
        snap = client.get("/machine/state").json()
        if (
            snap["state"] == "Idle"
            and snap["statusQuiet"]
            and snap["statusSeq"] > seq0 + 1
        ):
            return snap
        time.sleep(0.05)
    raise AssertionError("machine never went Idle")


def test_jog_moves_the_reported_position(client):
    settle(client)
    r = client.post("/machine/jog", json={"axis": "X", "distance": 10.0, "feed": 1000})
    assert r.status_code == 200

    snap = settle(client)
    assert snap["mpos"][0] == pytest.approx(10.0, abs=0.05)


def test_jog_past_the_envelope_is_refused_with_a_useful_message(client):
    settle(client)
    r = client.post("/machine/jog", json={"axis": "X", "distance": 9999.0, "feed": 1000})

    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "X" in detail and "limit" in detail


def test_zero_sets_the_work_offset(client):
    settle(client)
    client.post("/machine/jog", json={"axis": "X", "distance": 10.0, "feed": 1000})
    settle(client)

    assert client.post("/machine/zero", json={"axes": "XY"}).status_code == 200
    snap = settle(client)
    assert snap["wpos"][0] == pytest.approx(0.0, abs=0.05)


def test_z_cannot_be_zeroed(client):
    # grbl_servo_z picks pen up/down from MACHINE Z. A Z work offset shifts
    # every G-code Z without moving that switching point, so after zeroing Z
    # with the pen down the "pen up" height still reads as down and the pen
    # drags between traces.
    settle(client)
    for axes in ("Z", "XYZ"):
        r = client.post("/machine/zero", json={"axes": axes})
        assert r.status_code == 400, axes
        assert "Z" in r.json()["detail"]


def test_a_saved_zero_does_not_survive_reconnecting(client):
    # G10 L20 is stored in the Arduino's EEPROM, but connecting reboots the
    # board and machine position restarts at 0 wherever the pen is. With no
    # homing, the old zero now points at an arbitrary spot: the first move
    # of a plot would travel off to it. A fresh boot must start from the pen.
    settle(client)
    client.post("/machine/jog", json={"axis": "X", "distance": 30.0, "feed": 1000})
    client.post("/machine/jog", json={"axis": "Y", "distance": 20.0, "feed": 1000})
    settle(client, timeout=15.0)
    assert client.post("/machine/zero", json={"axes": "XY"}).status_code == 200
    settle(client)

    session.disconnect()
    assert client.post("/machine/connect",
                       json={"port": "SIM", "baud": 115200}).status_code == 200
    snap = settle(client)
    assert snap["mpos"][:2] == pytest.approx([0.0, 0.0], abs=0.05)
    assert snap["wpos"][:2] == pytest.approx([0.0, 0.0], abs=0.05)


def test_estop_returns_immediately_and_does_not_need_the_queue(client):
    settle(client)
    client.post("/machine/jog", json={"axis": "X", "distance": 50.0, "feed": 200})

    started = time.time()
    assert client.post("/machine/estop").status_code == 200
    assert time.time() - started < 1.0, "e-stop must not wait on the link"


def test_motion_endpoints_are_409_when_disconnected(client):
    client.post("/machine/disconnect")

    for path, body in [
        ("/machine/jog", {"axis": "X", "distance": 1.0}),
        ("/machine/home", None),
        ("/machine/zero", {"axes": "XYZ"}),
        ("/machine/command", {"line": "$$"}),
        ("/machine/estop", None),
    ]:
        r = client.post(path, json=body) if body else client.post(path)
        assert r.status_code == 409, path
