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
