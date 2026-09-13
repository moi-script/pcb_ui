"""The machine HTTP surface, driven against the simulator.

Uses FastAPI's TestClient. These do not need MongoDB: nothing in the
connection endpoints touches the database.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from machine import session


@pytest.fixture
def client():
    c = TestClient(server.app)
    yield c
    session.disconnect()


def test_ports_lists_the_simulator_when_enabled(client, monkeypatch):
    monkeypatch.setenv("TRACEWORKS_SIM", "1")
    body = client.get("/machine/ports").json()

    assert any(p["device"] == "SIM" for p in body["ports"])
    assert 115200 in body["bauds"]


def test_ports_hides_the_simulator_by_default(client, monkeypatch):
    monkeypatch.delenv("TRACEWORKS_SIM", raising=False)
    body = client.get("/machine/ports").json()

    assert not any(p["device"] == "SIM" for p in body["ports"])


def test_connect_then_state_reports_connected(client):
    r = client.post("/machine/connect", json={"port": "SIM", "baud": 115200})
    assert r.status_code == 200
    assert "Grbl" in r.json()["firmware"]

    snap = client.get("/machine/state").json()
    assert snap["conn"]["connected"] is True
    assert snap["conn"]["port"] == "SIM"


def test_disconnect_reports_disconnected(client):
    client.post("/machine/connect", json={"port": "SIM", "baud": 115200})
    assert client.post("/machine/disconnect").json() == {"ok": True}

    snap = client.get("/machine/state").json()
    assert snap["conn"]["connected"] is False


def test_connect_to_a_missing_port_is_a_502(client):
    r = client.post("/machine/connect", json={"port": "COM_NOPE", "baud": 115200})
    assert r.status_code == 502
    assert "COM_NOPE" in r.json()["detail"]


def test_run_without_a_connection_is_409(client):
    r = client.post("/machine/run", json={"board_id": "0" * 24, "check": False})
    assert r.status_code == 409


def test_pause_without_a_job_is_409(client):
    client.post("/machine/connect", json={"port": "SIM", "baud": 115200})
    assert client.post("/machine/pause").status_code == 409


def test_connecting_again_mid_plot_is_refused_not_a_reset(client):
    # Connect reopens the port, which reboots the Arduino and kills the plot.
    # A Connect button pressed while a board is plotting must not do that.
    from machine import session
    assert client.post("/machine/connect",
                       json={"port": "SIM", "baud": 115200}).status_code == 200
    lines = ["G21 G90"] + [f"G1 X{i % 40} Y-{i % 30} F200" for i in range(200)]
    session.start_job(lines, check=False, name="busy")
    try:
        r = client.post("/machine/connect", json={"port": "SIM", "baud": 115200})
        assert r.status_code == 409
        assert "plot" in r.json()["detail"].lower()
        assert session.job.state == "running"
    finally:
        session.disconnect()
