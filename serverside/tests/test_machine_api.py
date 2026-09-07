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
