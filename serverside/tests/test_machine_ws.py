"""The live-state socket."""
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


def test_socket_opens_with_a_snapshot_then_a_console_backlog(client):
    with client.websocket_connect("/machine/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot"
        assert "conn" in first["data"]
        assert "job" in first["data"]

        second = ws.receive_json()
        assert second["type"] == "console"
        assert isinstance(second["data"], list)


def test_connecting_a_machine_pushes_a_fresh_snapshot(client):
    with client.websocket_connect("/machine/ws") as ws:
        ws.receive_json()  # snapshot
        ws.receive_json()  # console

        client.post("/machine/connect", json={"port": "SIM", "baud": 115200})

        for _ in range(40):
            frame = ws.receive_json()
            if frame["type"] == "snapshot" and frame["data"]["conn"]["connected"]:
                assert frame["data"]["conn"]["port"] == "SIM"
                return
        raise AssertionError("never saw a connected snapshot")
