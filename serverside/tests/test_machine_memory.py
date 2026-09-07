"""Remembering the last port.

A convenience crumb, not an identity: it cannot make a port exist, and
connecting never requires it. These tests need MongoDB running.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from db import machines
from machine import session

EMAIL = "porttest@example.com"


@pytest.fixture
def client():
    machines.delete_many({"user_email": EMAIL})
    c = TestClient(server.app)
    yield c
    session.disconnect()
    machines.delete_many({"user_email": EMAIL})


def test_last_is_null_before_any_connection(client):
    assert client.get(f"/machine/last?email={EMAIL}").json() is None


def test_connecting_with_an_email_remembers_the_port(client):
    client.post("/machine/connect",
                json={"port": "SIM", "baud": 115200, "email": EMAIL})

    body = client.get(f"/machine/last?email={EMAIL}").json()
    assert body == {"port": "SIM", "baud": 115200}


def test_connecting_without_an_email_remembers_nothing(client):
    client.post("/machine/connect", json={"port": "SIM", "baud": 115200})

    assert client.get(f"/machine/last?email={EMAIL}").json() is None
