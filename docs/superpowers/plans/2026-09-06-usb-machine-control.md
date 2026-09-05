# USB Serial Machine Control — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the paired-ESP32-over-WiFi print path with a direct USB serial connection owned by the FastAPI backend — plug an Arduino running GRBL into the PC, pick the port, connect, jog, zero, and plot, the way Universal Gcode Sender works.

**Architecture:** The backend runs on the same machine as the browser, so it owns the COM port; the frontend only ever speaks HTTP and WebSocket. A tested GRBL 1.1 stack (protocol codec, port-owning streamer thread with character-counting flow control, machine state, and a GRBL simulator) is ported out of the sibling `machine-control-slice-1/server/` worktree app into a new `serverside/grbl/` package, wrapped in a process-wide `Session` singleton in `serverside/machine.py`. The one thing slice-1 lacks — a G-code job runner — is written fresh on top of it.

**Tech Stack:** Python 3, FastAPI, pyserial, pymongo, pytest (backend); Next.js 15 App Router, React 19, TypeScript, Tailwind v4, three.js (frontend).

**Spec:** `docs/superpowers/specs/2026-09-06-usb-machine-control-design.md`

## Global Constraints

- **Source of the ported code:** `machine-control-slice-1/server/`. It lives in the same repository on a separate worktree branch, but its files are present on disk at that path. **Copy files out of it; never modify anything inside `machine-control-slice-1/`.**
- **Import style in `serverside/` is flat.** `serverside/` is the working directory (`uvicorn server:app --reload --port 8000`), and existing tests import as `from tracer import emit`. So the ported package imports as `from grbl import ports`, `from grbl.protocol import parse_status`. Slice-1's absolute imports (`from server.store.db import Profile`) and relative imports (`from .grbl import Realtime`) must both be rewritten.
- **One process-wide session, not one per account.** `serverside/machine.py` exposes a module-level `session` singleton. Never key a connection by user email.
- **The module rename is `grbl_serial/grbl.py` → `grbl/protocol.py`**, to avoid `grbl.grbl`. Every other ported filename keeps its stem.
- **Never send a realtime byte through `send_line`.** Realtime bytes (`?`, `!`, `~`, `\x18`, `\x85`) bypass GRBL's line parser, get no `ok`, and must never be counted against the RX buffer. `Streamer.send_realtime(byte: bytes)` is the only path for them.
- **`serverside/pcb_send.py` is not modified and not imported by the API.** It stays as a documented standalone CLI.
- **`serverside/firmware/` is left on disk, unused.** Do not delete it. Task 13 adds one line to its README.
- **Endpoint prefix is `/machine/`.** Slice-1 uses `/api/`; every ported route is renamed.
- **Simulator env var:** `TRACEWORKS_SIM=1`. Sentinel port device string: `SIM`.
- **Default baud: 115200. Default RX buffer: 128 bytes.**
- **Run backend tests from `serverside/`:** `cd serverside && python -m pytest`.
- **Commit after every task.** Use `feat:` / `test:` / `refactor:` / `docs:` prefixes matching the repo's existing history style (`git log --oneline`).

---

### Task 1: Port the GRBL package

Copy the proven serial stack across and get its tests green in the new home. No behaviour changes — this task is a lift, a rename, and an import rewrite. The one real decision: slice-1 reads its `Profile` out of sqlite, and `serverside` has no sqlite, so the profile becomes a plain dataclass with defaults.

**Files:**
- Create: `serverside/grbl/__init__.py`
- Create: `serverside/grbl/profile.py`
- Create: `serverside/grbl/ports.py` (from `machine-control-slice-1/server/grbl_serial/ports.py`)
- Create: `serverside/grbl/protocol.py` (from `machine-control-slice-1/server/grbl_serial/grbl.py`)
- Create: `serverside/grbl/streamer.py` (from `machine-control-slice-1/server/grbl_serial/streamer.py`)
- Create: `serverside/grbl/limits.py` (from `machine-control-slice-1/server/machine/limits.py`)
- Create: `serverside/grbl/state.py` (from `machine-control-slice-1/server/machine/state.py`)
- Create: `serverside/grbl/sim.py` (from `machine-control-slice-1/server/sim/grbl_sim.py`)
- Test: `serverside/tests/test_grbl_ports.py` (from `.../tests/test_ports.py`)
- Test: `serverside/tests/test_grbl_status.py` (from `.../tests/test_grbl_status.py`)
- Test: `serverside/tests/test_grbl_commands.py` (from `.../tests/test_grbl_commands.py`)
- Test: `serverside/tests/test_grbl_sim.py` (from `.../tests/test_grbl_sim.py`)
- Test: `serverside/tests/test_grbl_streamer_flow.py` (from `.../tests/test_streamer_flow.py`)
- Test: `serverside/tests/test_grbl_streamer_events.py` (from `.../tests/test_streamer_events.py`)
- Test: `serverside/tests/test_grbl_state.py` (from `.../tests/test_state.py`)
- Test: `serverside/tests/test_grbl_limits.py` (from `.../tests/test_limits.py`)
- Modify: `serverside/requirements.txt`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `grbl.profile.Profile` — frozen dataclass with fields `name: str`, `controller: str`, `baud: int`, `rx_buffer: int`, `pen_mode: str`, `travel_x/y/z: float`, `pen_up_z: float`, `pen_down_z: float`, `servo_up: int`, `servo_down: int`, `travel_feed: float`, `draw_feed: float`, `z_feed: float`, `jog_feed: float`; and `DEFAULT_PROFILE: Profile`.
  - `grbl.ports.PortInfo(device, description, vid, pid, likely_controller, chip)`, `grbl.ports.list_ports() -> list[PortInfo]`, `grbl.ports.autoselect(ports) -> str | None`, `grbl.ports.BAUD_RATES: list[int]`.
  - `grbl.protocol.State` (str Enum), `Status`, `Reply(kind, code, text)`, `Realtime` (namespace of `bytes` constants: `STATUS`, `FEED_HOLD`, `RESUME`, `SOFT_RESET`, `JOG_CANCEL`, …), `parse_status(line) -> Status | None`, `parse_reply(line) -> Reply | None`, `resolve_positions(status, cached_wco)`, `encode_jog(axis, distance, feed) -> str`, `encode_zero(axes) -> str`, `fmt(value) -> str`.
  - `grbl.streamer.Transport` (Protocol: `write(bytes)`, `read_available() -> bytes`, `close()`), `Streamer(transport, rx_buffer=128, on_event=None)` with `send_line(str)`, `send_realtime(bytes)`, `pump()`, `start(poll_hz=5.0)`, `stop()`, properties `pending_bytes`, `quiet`, `connected`; events `StatusEvent(status, quiet)`, `ReplyEvent(reply)`, `SentEvent(line)`, `DisconnectedEvent(reason)`.
  - `grbl.state.MachineState(profile)` with `apply(event)`, `snapshot() -> dict`, `console_tail(n) -> list[dict]`, `console_head_seq() -> int`, `status_seq() -> int`, `set_connection(port, baud, firmware)`, and attributes `state: str`, `mpos`, `wpos`, `wco`, `firmware`, `connected`.
  - `grbl.limits.check_jog(profile, mpos, axis, distance) -> None`, `grbl.limits.LimitError`.
  - `grbl.sim.GrblSim` — a `Transport` implementation modelling a GRBL 1.1 controller.

- [ ] **Step 1: Copy the files into place**

```bash
cd /c/pcb_ui/serverside
mkdir -p grbl
: > grbl/__init__.py
cp ../machine-control-slice-1/server/grbl_serial/ports.py      grbl/ports.py
cp ../machine-control-slice-1/server/grbl_serial/grbl.py       grbl/protocol.py
cp ../machine-control-slice-1/server/grbl_serial/streamer.py   grbl/streamer.py
cp ../machine-control-slice-1/server/machine/limits.py         grbl/limits.py
cp ../machine-control-slice-1/server/machine/state.py          grbl/state.py
cp ../machine-control-slice-1/server/sim/grbl_sim.py           grbl/sim.py

cp ../machine-control-slice-1/server/tests/test_ports.py            tests/test_grbl_ports.py
cp ../machine-control-slice-1/server/tests/test_grbl_status.py      tests/test_grbl_status.py
cp ../machine-control-slice-1/server/tests/test_grbl_commands.py    tests/test_grbl_commands.py
cp ../machine-control-slice-1/server/tests/test_grbl_sim.py         tests/test_grbl_sim.py
cp ../machine-control-slice-1/server/tests/test_streamer_flow.py    tests/test_grbl_streamer_flow.py
cp ../machine-control-slice-1/server/tests/test_streamer_events.py  tests/test_grbl_streamer_events.py
cp ../machine-control-slice-1/server/tests/test_state.py            tests/test_grbl_state.py
cp ../machine-control-slice-1/server/tests/test_limits.py           tests/test_grbl_limits.py
```

- [ ] **Step 2: Write `grbl/profile.py`**

Slice-1 loads this out of sqlite (`server/store/db.py`). There is no sqlite in `serverside`, and a machine profile is a handful of constants, so it becomes a frozen dataclass. The defaults are copied verbatim from slice-1's `_SCHEMA` column defaults.

```python
"""The machine's fixed characteristics: travel envelope, feeds, pen geometry.

Slice-1 kept this in sqlite behind a profile editor. Here it is a constant:
there is one machine, its envelope does not change between requests, and a
frozen dataclass is honest about that. If per-user machine profiles are ever
wanted, this is the seam to widen — everything downstream takes a Profile.
"""
from __future__ import annotations

from dataclasses import dataclass

PEN_MODES = ("z-axis", "servo-pwm")


@dataclass(frozen=True)
class Profile:
    name: str = "Default"
    controller: str = "grbl"
    baud: int = 115200
    rx_buffer: int = 128
    pen_mode: str = "servo-pwm"
    travel_x: float = 300.0
    travel_y: float = 200.0
    travel_z: float = 5.0
    pen_up_z: float = 2.0
    pen_down_z: float = 0.0
    servo_up: int = 0
    servo_down: int = 255
    travel_feed: float = 3000.0
    draw_feed: float = 1200.0
    z_feed: float = 500.0
    jog_feed: float = 1000.0


DEFAULT_PROFILE = Profile()
```

- [ ] **Step 3: Rewrite the imports in the copied modules**

Every copied file uses slice-1's package layout. Fix each by hand (do not blanket-sed the whole tree — `state.py` and `limits.py` import from two different old locations):

| File | Old import | New import |
|---|---|---|
| `grbl/streamer.py` | `from .grbl import Realtime, Reply, Status, parse_reply, parse_status` | `from grbl.protocol import Realtime, Reply, Status, parse_reply, parse_status` |
| `grbl/limits.py` | `from server.store.db import Profile` | `from grbl.profile import Profile` |
| `grbl/state.py` | `from server.store.db import Profile` and `from server.grbl_serial.grbl import ...` and `from server.grbl_serial.streamer import ...` | `from grbl.profile import Profile`, `from grbl.protocol import ...`, `from grbl.streamer import ...` |
| `grbl/sim.py` | any `from server...` | `from grbl...` |
| every `tests/test_grbl_*.py` | `from server.grbl_serial.grbl import ...` | `from grbl.protocol import ...` |
| every `tests/test_grbl_*.py` | `from server.grbl_serial.ports import ...` / `.streamer` | `from grbl.ports import ...` / `from grbl.streamer import ...` |
| every `tests/test_grbl_*.py` | `from server.machine.state import ...` / `.limits` | `from grbl.state import ...` / `from grbl.limits import ...` |
| every `tests/test_grbl_*.py` | `from server.sim.grbl_sim import ...` | `from grbl.sim import ...` |
| `tests/test_grbl_state.py`, `tests/test_grbl_limits.py` | `from server.store.db import Profile` | `from grbl.profile import Profile` |

Find every remaining stale import with:

```bash
cd /c/pcb_ui/serverside && grep -rn "server\.\|from \.grbl\|grbl_serial" grbl/ tests/test_grbl_*.py
```

Expected after the rewrite: no output.

- [ ] **Step 4: Fix the Profile construction in the ported tests**

Slice-1's tests build a `Profile` positionally with an `id` and `name` first (`Profile(1, "test", "grbl", 115200, ...)`), because its dataclass has an `id` column. `grbl.profile.Profile` has no `id` and every field has a default. Replace each such construction with keyword arguments naming only the fields the test cares about, e.g.:

```python
# was: Profile(1, "test", "grbl", 115200, 128, "z-axis", 300.0, 200.0, 5.0, ...)
profile = Profile(travel_x=300.0, travel_y=200.0, travel_z=5.0)
```

- [ ] **Step 5: Run the ported tests**

```bash
cd /c/pcb_ui/serverside && python -m pytest tests/test_grbl_ports.py tests/test_grbl_status.py tests/test_grbl_commands.py tests/test_grbl_sim.py tests/test_grbl_streamer_flow.py tests/test_grbl_streamer_events.py tests/test_grbl_state.py tests/test_grbl_limits.py -v
```

Expected: all PASS. If a test fails, it is an import or a `Profile` construction that was missed — the logic itself is unchanged and was green in slice-1.

- [ ] **Step 6: Write a test proving the profile defaults are sane**

Add to `serverside/tests/test_grbl_limits.py`:

```python
def test_default_profile_has_a_real_envelope():
    """A zero-travel default would refuse every jog with a confusing message."""
    from grbl.profile import DEFAULT_PROFILE

    assert DEFAULT_PROFILE.travel_x > 0
    assert DEFAULT_PROFILE.travel_y > 0
    assert DEFAULT_PROFILE.travel_z > 0
    assert DEFAULT_PROFILE.rx_buffer == 128
    assert DEFAULT_PROFILE.baud == 115200
```

- [ ] **Step 7: Run it**

```bash
cd /c/pcb_ui/serverside && python -m pytest tests/test_grbl_limits.py -v
```

Expected: PASS.

- [ ] **Step 8: Run the whole existing suite to prove nothing regressed**

```bash
cd /c/pcb_ui/serverside && python -m pytest
```

Expected: all PASS, including the pre-existing tracer/pipeline tests.

- [ ] **Step 9: Commit**

```bash
cd /c/pcb_ui
git add serverside/grbl serverside/tests/test_grbl_*.py
git commit -m "feat: port the GRBL 1.1 serial stack into serverside/grbl

Protocol codec, port enumeration, the flow-controlled streamer, machine
state, and the GRBL simulator, lifted from machine-control-slice-1 with
its tests. The sqlite-backed Profile becomes a frozen dataclass: there is
one machine and its envelope does not change between requests."
```

---

### Task 2: The session singleton

The object that owns the one connection. Ported from slice-1's `Session` class, minus its sqlite profile store, plus the simulator transport.

**Files:**
- Create: `serverside/machine.py`
- Test: `serverside/tests/test_machine_session.py`
- Modify: `serverside/requirements.txt` (confirm `pyserial` is present — it already is)

**Interfaces:**
- Consumes: everything from Task 1.
- Produces:
  - `machine.SerialTransport(port: str, baud: int)` — a `Transport` over pyserial.
  - `machine.SIM_PORT = "SIM"` — the sentinel device string for the simulator.
  - `machine.make_transport(port: str, baud: int) -> Transport` — returns `grbl.sim.GrblSim()` when `port == "SIM"`, else `SerialTransport`.
  - `machine.PositionUncertain(Exception)`.
  - `machine.Session` with `state: MachineState`, `streamer: Streamer | None`, `profile: Profile`, and methods `require() -> Streamer`, `connect(transport, port, baud) -> str` (returns the firmware banner), `disconnect() -> None`, `clear_planned()`, `taint_planned()`, `taint_and_resync(streamer)`, `settle(snap, streamer_quiet)`, `reserve_jog(...)`.
  - `machine.session` — the module-level singleton.

- [ ] **Step 1: Write the failing test**

`serverside/tests/test_machine_session.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /c/pcb_ui/serverside && python -m pytest tests/test_machine_session.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'machine'`.

- [ ] **Step 3: Write `serverside/machine.py`**

Copy slice-1's `main.py` lines 46–534 — `_Tainted`, `PositionUncertain`, `SerialTransport`, and the whole `Session` class — into the new module, then make these four changes:

1. Delete `self._db_lock`, `self.conn = init_db()`, and both `with self._db_lock: self.profile = get_active_profile(self.conn)` blocks. Replace with `self.profile = DEFAULT_PROFILE` in `__init__` and drop the profile re-read at the top of `connect()`. Remove the sqlite paragraph from the class docstring.
2. Add `make_transport`, replacing slice-1's `_make_transport` (which read a factory off `app.state`):

```python
SIM_PORT = "SIM"


def make_transport(port: str, baud: int) -> Transport:
    """The transport for a port name. `SIM` is the simulator, not a device.

    Routing the simulator through the same factory the real port uses means
    every layer above this line — session, endpoints, job runner, the UI —
    is exercised identically with and without hardware. A separate "sim
    mode" flag threaded through those layers would leave them untested in
    the configuration that ships.
    """
    if port == SIM_PORT:
        from grbl.sim import GrblSim

        return GrblSim()
    return SerialTransport(port, baud)
```

3. The module header:

```python
"""Owns the one serial connection to the one machine.

A module-level singleton, not a per-account object: there is one physical
plotter on the PC running this server. Keying the connection by user would
model a fleet that does not exist and would let two browser tabs each
believe they own the port.
"""
from __future__ import annotations

import threading
import time

from fastapi import HTTPException

from grbl.limits import LimitError, check_jog
from grbl.profile import DEFAULT_PROFILE, Profile
from grbl.protocol import Realtime
from grbl.state import MachineState
from grbl.streamer import Streamer, Transport

BANNER_TIMEOUT = 3.0
```

4. At the bottom of the file:

```python
session = Session()
```

Keep `Session.connect()`'s banner handshake exactly as slice-1 has it, comments included — the DTR-reset window, the status-poll fallback, the `$I` / `$$` queries, and the 502 when the controller never identifies itself.

- [ ] **Step 4: Run the tests**

```bash
cd /c/pcb_ui/serverside && python -m pytest tests/test_machine_session.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /c/pcb_ui
git add serverside/machine.py serverside/tests/test_machine_session.py
git commit -m "feat: the process-wide machine session

One physical plotter, one connection, one singleton. The simulator is
reached through the same transport factory as a real port, so every layer
above it is exercised identically with and without hardware."
```

---

### Task 3: Connection endpoints

Ports, connect, disconnect, state. After this task you can plug in an Arduino, hit `/machine/ports`, and connect to it — the first point where the feature is real.

**Files:**
- Modify: `serverside/server.py` (add a machine section; nothing removed yet — the ESP32 teardown is Task 7, so this task's changes are purely additive and independently reviewable)
- Test: `serverside/tests/test_machine_api.py`

**Interfaces:**
- Consumes: `machine.session`, `machine.make_transport`, `grbl.ports.list_ports`, `grbl.ports.autoselect`, `grbl.ports.BAUD_RATES`.
- Produces the JSON contract the frontend depends on:
  - `GET /machine/ports` → `{"ports": [{"device": str, "description": str, "chip": str | null, "likely_controller": bool}], "suggested": str | null, "bauds": [int]}`
  - `POST /machine/connect` `{port, baud}` → `{"ok": true, "firmware": str}`
  - `POST /machine/disconnect` → `{"ok": true}`
  - `GET /machine/state` → `MachineState.snapshot()`

- [ ] **Step 1: Write the failing test**

`serverside/tests/test_machine_api.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /c/pcb_ui/serverside && python -m pytest tests/test_machine_api.py -v
```

Expected: FAIL — 404 on every `/machine/*` route.

- [ ] **Step 3: Add the endpoints to `serverside/server.py`**

Add the imports near the existing ones at the top:

```python
from grbl import ports as grbl_ports
from machine import SIM_PORT, make_transport, session
```

Add the request models beside the existing Pydantic models (near `class PrintJob`):

```python
class ConnectRequest(BaseModel):
    port: str
    baud: int = 115200
```

Add a new section at the end of the endpoint list:

```python
# ------------------------------------------------------------------- machine
#
# The backend runs on the same PC as the browser, so it — not the tab — owns
# the serial port. Everything here drives the one `machine.session`.

@app.get("/machine/ports")
def machine_ports():
    """Serial ports, controller-looking ones first.

    `suggested` is filled only when exactly one candidate is present:
    guessing between two plausible boards is worse than asking, and picking
    the wrong one moves a machine.
    """
    found = grbl_ports.list_ports()
    payload = [
        {
            "device": p.device,
            "description": p.description,
            "chip": p.chip,
            "likely_controller": p.likely_controller,
        }
        for p in found
    ]
    suggested = grbl_ports.autoselect(found)

    if os.environ.get("TRACEWORKS_SIM") == "1":
        payload.append({
            "device": SIM_PORT,
            "description": "Simulator (GRBL 1.1) — no hardware",
            "chip": None,
            "likely_controller": False,
        })
        if suggested is None:
            suggested = SIM_PORT

    return {"ports": payload, "suggested": suggested,
            "bauds": grbl_ports.BAUD_RATES}


@app.post("/machine/connect")
def machine_connect(body: ConnectRequest):
    try:
        transport = make_transport(body.port, body.baud)
    except Exception as exc:
        raise HTTPException(502, f"Could not open {body.port}: {exc}") from exc
    firmware = session.connect(transport, body.port, body.baud)
    return {"ok": True, "firmware": firmware}


@app.post("/machine/disconnect")
def machine_disconnect():
    session.disconnect()
    return {"ok": True}


@app.get("/machine/state")
def machine_state():
    return session.state.snapshot()
```

`os` is already imported in `server.py`; confirm with `grep -n "^import os" serverside/server.py`.

- [ ] **Step 4: Run the tests**

```bash
cd /c/pcb_ui/serverside && python -m pytest tests/test_machine_api.py -v
```

Expected: PASS.

- [ ] **Step 5: Try it against the simulator by hand**

```bash
cd /c/pcb_ui/serverside && TRACEWORKS_SIM=1 uvicorn server:app --port 8000
# in another terminal:
curl -s localhost:8000/machine/ports
curl -s -X POST localhost:8000/machine/connect -H 'Content-Type: application/json' -d '{"port":"SIM","baud":115200}'
curl -s localhost:8000/machine/state
```

Expected: the ports list includes `SIM`; connect returns a `Grbl 1.1h` firmware string; state reports `"connected": true`.

- [ ] **Step 6: Commit**

```bash
cd /c/pcb_ui
git add serverside/server.py serverside/tests/test_machine_api.py
git commit -m "feat: /machine/ports, connect, disconnect, state

Port enumeration names the chip (COM5 - CH340) and pre-selects only when
exactly one candidate is present. TRACEWORKS_SIM=1 adds a SIM port so the
whole path runs with nothing plugged in."
```

---

### Task 4: Motion endpoints

Jog, home, unlock, zero, raw command, E-stop. Without these you cannot set a work origin, and without a work origin you cannot place a drawing on a board.

**Files:**
- Modify: `serverside/server.py` (extend the machine section)
- Test: `serverside/tests/test_machine_motion.py`

**Interfaces:**
- Consumes: `machine.session` (`require`, `reserve_jog`, `clear_planned`, `taint_planned`, `taint_and_resync`, `settle`), `grbl.protocol.Realtime`, `grbl.protocol.encode_jog`, `grbl.protocol.encode_zero`, `grbl.limits.LimitError`.
- Produces:
  - `POST /machine/jog` `{axis: "X"|"Y"|"Z", distance: float, feed: float = 1000.0}` → `{"ok": true}`; `409` when not connected or in Alarm; `400` on `LimitError` with the axis and overshoot in the message.
  - `POST /machine/jog/cancel`, `POST /machine/home`, `POST /machine/unlock`, `POST /machine/estop` → `{"ok": true}`
  - `POST /machine/zero` `{axes: str}` → `{"ok": true}`
  - `POST /machine/command` `{line: str}` → `{"ok": true}`

- [ ] **Step 1: Write the failing test**

`serverside/tests/test_machine_motion.py`:

```python
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
    """Wait until the simulated machine reports Idle."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = client.get("/machine/state").json()
        if snap["state"] == "Idle":
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

    assert client.post("/machine/zero", json={"axes": "XYZ"}).status_code == 200
    snap = settle(client)
    assert snap["wpos"][0] == pytest.approx(0.0, abs=0.05)


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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /c/pcb_ui/serverside && python -m pytest tests/test_machine_motion.py -v
```

Expected: FAIL — 404 on `/machine/jog`.

- [ ] **Step 3: Port the handlers**

Copy slice-1's `main.py` handlers for `/api/jog` (lines 591–672), `/api/jog/cancel`, `/api/home`, `/api/unlock`, `/api/zero`, `/api/command`, and `/api/estop` into `server.py`'s machine section. For each:

- rename the route `/api/x` → `/machine/x`;
- rename the function `jog` → `machine_jog`, `home` → `machine_home`, etc., so nothing collides with existing names in `server.py`;
- replace `Body(..., embed=True)` parameter style with Pydantic models to match the surrounding file's convention:

```python
class JogRequest(BaseModel):
    axis: str
    distance: float
    feed: float = 1000.0


class ZeroRequest(BaseModel):
    axes: str


class CommandRequest(BaseModel):
    line: str
```

- keep the bodies otherwise **byte-identical**, comments included. The jog handler's single atomic `session.state.snapshot()` read before the safety decision, the `PositionUncertain` handling, and the `LimitError` → `HTTPException(400, str(exc))` mapping are all load-bearing and were reasoned about at length in slice-1.

The E-stop handler in particular keeps its exact shape:

```python
@app.post("/machine/estop")
def machine_estop():
    """Soft reset, immediately. No feed hold, no queue, no confirmation."""
    streamer = session.require()
    streamer.send_realtime(Realtime.SOFT_RESET)
    # Taint, do NOT clear: a soft reset aborts motion mid-move, so the
    # machine stops at a point nobody knows and live mpos has certainly not
    # caught up. Deliberately not taint_and_resync — e-stop must return
    # instantly and must never wait on the link.
    session.taint_planned()
    return {"ok": True}
```

- [ ] **Step 4: Run the tests**

```bash
cd /c/pcb_ui/serverside && python -m pytest tests/test_machine_motion.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the whole suite**

```bash
cd /c/pcb_ui/serverside && python -m pytest
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd /c/pcb_ui
git add serverside/server.py serverside/tests/test_machine_motion.py
git commit -m "feat: jog, home, unlock, zero, command and e-stop endpoints

Envelope checks refuse an out-of-range jog before the bytes leave, because
an alarm costs the operator a reset and their zero and does not say which
axis. E-stop goes out as a realtime soft reset, bypassing the queue."
```

---

### Task 5: The job runner

The new code. Feed a board's stored G-code through the streamer under flow control, with progress, pause, resume, stop, and honest failure.

**Files:**
- Create: `serverside/job.py`
- Modify: `serverside/machine.py` (the session holds the current job)
- Modify: `serverside/grbl/state.py` (the `job` field in `snapshot()`)
- Modify: `serverside/server.py` (run/pause/resume/stop endpoints)
- Test: `serverside/tests/test_job_runner.py`

**Interfaces:**
- Consumes: `grbl.streamer.Streamer`, `grbl.protocol.Realtime`, `machine.session`.
- Produces:
  - `job.load_lines(text: str) -> list[str]` — strips `;` comments and blanks.
  - `job.Job(lines: list[str], streamer: Streamer, check: bool = False, name: str = "")` with `start()`, `pause()`, `resume()`, `stop()`, `on_streamer_event(event)`, `snapshot() -> dict`, and attribute `state: str`.
  - `Job.snapshot()` → `{"name": str, "state": "running"|"paused"|"done"|"error"|"stopped", "sent": int, "acked": int, "total": int, "check": bool, "error": str | null, "errorLine": int | null}`.
  - `machine.Session.job: Job | None`, `Session.start_job(lines, check, name) -> Job` (409 if one is already running).
  - `POST /machine/run` `{board_id: str, check: bool}` → `{"ok": true, "total": int, "check": bool}`
  - `POST /machine/pause` / `POST /machine/resume` / `POST /machine/stop` → `{"ok": true}`

- [ ] **Step 1: Write the failing test**

`serverside/tests/test_job_runner.py`:

```python
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


def run_to_completion(job, streamer, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        streamer.pump()
        if job.state in ("done", "error", "stopped"):
            return job.snapshot()
        time.sleep(0.005)
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

    snap = run_to_completion(job, streamer)
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

    while job.state == "running":
        streamer.pump()
        assert streamer.pending_bytes <= streamer.rx_buffer
        time.sleep(0.002)

    assert job.snapshot()["state"] == "done"


def test_pause_stops_feeding_and_resume_continues(rig):
    sim, streamer = rig
    lines = [f"G1 X{i % 50} F1200" for i in range(200)]
    job = Job(lines, streamer)
    streamer.on_event = job.on_streamer_event
    job.start()

    for _ in range(20):
        streamer.pump()
        time.sleep(0.005)
    job.pause()
    sent_at_pause = job.snapshot()["sent"]

    for _ in range(30):
        streamer.pump()
        time.sleep(0.005)
    assert job.snapshot()["sent"] == sent_at_pause, "paused job kept feeding"
    assert job.state == "paused"

    job.resume()
    snap = run_to_completion(job, streamer)
    assert snap["state"] == "done"
    assert snap["acked"] == len(lines)


def test_stop_mid_job_ends_it_as_stopped(rig):
    sim, streamer = rig
    lines = [f"G1 X{i % 50} F1200" for i in range(200)]
    job = Job(lines, streamer)
    streamer.on_event = job.on_streamer_event
    job.start()

    for _ in range(10):
        streamer.pump()
        time.sleep(0.005)
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

    snap = run_to_completion(job, streamer)
    assert snap["state"] == "error"
    assert snap["errorLine"] == 3
    assert "Q999" in snap["error"]


def test_check_mode_brackets_the_job_with_dollar_C(rig):
    sim, streamer = rig
    job = Job(load_lines(SQUARE), streamer, check=True)
    streamer.on_event = job.on_streamer_event
    job.start()

    snap = run_to_completion(job, streamer)
    assert snap["state"] == "done"
    assert snap["check"] is True
    assert sim.check_mode is False, "check mode must be toggled back off"


def test_check_mode_is_left_off_even_when_the_job_errors(rig):
    """$C is a toggle, not a flag. Leaking it on makes the NEXT job silently
    validate instead of plotting, which looks like a machine that ignores
    you."""
    sim, streamer = rig
    job = Job(["G21 G90", "G1 Q999", "G1 X10 F600"], streamer, check=True)
    streamer.on_event = job.on_streamer_event
    job.start()

    snap = run_to_completion(job, streamer)
    assert snap["state"] == "error"
    assert sim.check_mode is False


def test_a_disconnect_mid_job_fails_the_job_visibly(rig):
    sim, streamer = rig
    lines = [f"G1 X{i % 50} F1200" for i in range(200)]
    job = Job(lines, streamer)
    streamer.on_event = job.on_streamer_event
    job.start()

    for _ in range(10):
        streamer.pump()
        time.sleep(0.005)
    streamer._drop("cable pulled")

    snap = run_to_completion(job, streamer)
    assert snap["state"] == "error"
    assert "cable pulled" in snap["error"]
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /c/pcb_ui/serverside && python -m pytest tests/test_job_runner.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'job'`.

- [ ] **Step 3: Write `serverside/job.py`**

```python
"""Streams one G-code file to the controller.

The streamer already handles flow control — how many bytes may be in flight.
This handles the file: which line is next, how far along we are, and what
"stop" means when a hundred moves are already queued in the controller.

Progress is counted in acknowledged lines, not sent lines. GRBL returns `ok`
when it has PARSED AND QUEUED a line, not when it has executed it, so `sent`
runs well ahead of the pen and `acked` runs a little ahead. Neither is the
pen's position; the status report's WPos is. Both numbers are exposed and
named for what they are rather than blended into one dishonest percentage.
"""
from __future__ import annotations

import threading

from grbl.protocol import Realtime
from grbl.streamer import DisconnectedEvent, ReplyEvent, Streamer


def load_lines(text: str) -> list[str]:
    """Cleaned G-code lines: `;` comments and blank lines removed.

    Same rule as pcb_send.load_lines, which is what the CLI has always sent.
    Comments cost RX budget and buy nothing.
    """
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if line:
            out.append(line)
    return out


class Job:
    """One file, streaming. Not thread-safe to construct twice concurrently —
    the session enforces one at a time."""

    def __init__(
        self,
        lines: list[str],
        streamer: Streamer,
        check: bool = False,
        name: str = "",
    ) -> None:
        self.lines = lines
        self.streamer = streamer
        self.check = check
        self.name = name

        self._lock = threading.RLock()
        self.state = "idle"          # idle|running|paused|done|error|stopped
        self.sent = 0
        self.acked = 0
        self.error: str | None = None
        self.error_line: int | None = None
        self._check_on = False

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self.state == "running":
                return
            self.state = "running"
            if self.check:
                # $C is a toggle, not a mode flag: it must be sent once here
                # and once at the end, and the end must happen on every exit
                # path or the next job silently validates instead of plotting.
                self.streamer.send_line("$C")
                self._check_on = True
            self._feed()

    def pause(self) -> None:
        """Stop feeding and feed-hold what is already queued.

        Both halves are needed. Feeding stops immediately, but the controller
        may hold a hundred queued moves; without the hold the machine keeps
        drawing for seconds after the button was pressed.
        """
        with self._lock:
            if self.state != "running":
                return
            self.state = "paused"
        self.streamer.send_realtime(Realtime.FEED_HOLD)

    def resume(self) -> None:
        with self._lock:
            if self.state != "paused":
                return
            self.state = "running"
        self.streamer.send_realtime(Realtime.RESUME)
        with self._lock:
            self._feed()

    def stop(self) -> None:
        """Hold, then abandon the rest of the file.

        A soft reset would be faster but costs the operator their work zero,
        which they set by hand and would have to set again. Holding and
        dropping the remaining lines leaves the machine parked and zeroed;
        the queued moves already in the controller still play out, which is
        why this is 'stop', not 'e-stop'. E-stop is its own endpoint.
        """
        with self._lock:
            if self.state in ("done", "error", "stopped"):
                return
            self.state = "stopped"
        self.streamer.send_realtime(Realtime.FEED_HOLD)
        self._end_check_mode()

    # --- feeding -----------------------------------------------------------

    def _feed(self) -> None:
        """Hand every remaining line to the streamer.

        Deliberately unbatched: `Streamer.send_line` queues into its outbox
        and writes only what the RX budget allows, so handing it the whole
        file is correct and there is no second scheduler here to get wrong.
        Called with `self._lock` held.
        """
        if self.state != "running":
            return
        while self.sent < len(self.lines):
            self.streamer.send_line(self.lines[self.sent])
            self.sent += 1

    def _end_check_mode(self) -> None:
        if self._check_on:
            self.streamer.send_line("$C")
            self._check_on = False

    # --- inbound -----------------------------------------------------------

    def on_streamer_event(self, event: object) -> None:
        """Count acknowledgements; fail loudly on error or a dropped link."""
        if isinstance(event, DisconnectedEvent):
            with self._lock:
                if self.state in ("running", "paused"):
                    self.state = "error"
                    self.error = f"link lost: {event.reason}"
            return

        if not isinstance(event, ReplyEvent):
            return

        reply = event.reply
        with self._lock:
            if self.state not in ("running", "paused"):
                return
            if reply.kind == "ok":
                self.acked += 1
                if self.acked >= len(self.lines):
                    self.state = "done"
                    self._end_check_mode()
            elif reply.kind in ("error", "alarm"):
                self.error_line = self.acked + 1
                offending = (
                    self.lines[self.error_line - 1]
                    if self.error_line <= len(self.lines)
                    else "?"
                )
                self.error = f"line {self.error_line}: {offending} -> {reply.text}"
                self.state = "error"
                self._end_check_mode()

    # --- reporting ---------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "state": self.state,
                "sent": self.sent,
                "acked": self.acked,
                "total": len(self.lines),
                "check": self.check,
                "error": self.error,
                "errorLine": self.error_line,
            }
```

- [ ] **Step 4: Wire the job into the session**

In `serverside/machine.py`, add to `Session.__init__`:

```python
        self.job: Job | None = None
```

with `from job import Job` at the top. Add these methods to `Session`:

```python
    def start_job(self, lines: list[str], check: bool, name: str) -> Job:
        """Begin streaming a file. One at a time, deliberately.

        Two concurrent jobs on one machine is not a feature with a sensible
        meaning — it is two files interleaved into one nonsense toolpath.
        """
        streamer = self.require()
        if self.job is not None and self.job.state in ("running", "paused"):
            raise HTTPException(409, "A job is already running.")
        job = Job(lines, streamer, check=check, name=name)
        self.job = job
        job.start()
        return job

    def require_job(self) -> Job:
        if self.job is None:
            raise HTTPException(409, "No job is running.")
        return self.job
```

In `Session._on_streamer_event`, forward every event to the job as the **first** thing it does, before `MachineState.apply`:

```python
        job = self.job
        if job is not None:
            job.on_streamer_event(event)
```

In `Session.disconnect()`, before clearing the streamer, fail any live job so a pulled cable does not leave a job reading "running" forever:

```python
        if self.job is not None and self.job.state in ("running", "paused"):
            self.job.state = "error"
            self.job.error = "disconnected"
```

- [ ] **Step 5: Expose the job in the state snapshot**

`grbl/state.py`'s `snapshot()` currently has the literal `"job": None,  # file streaming arrives in the next slice`. That slice is this one. Give `MachineState` a `job_snapshot` hook so it stays free of any import from `job.py` (state is the lower layer):

In `MachineState.__init__`:

```python
        # Filled in by machine.Session with the live job's snapshot function.
        # A callable rather than the Job itself: MachineState sits below the
        # job in the stack and must not import it.
        self.job_source: Callable[[], dict | None] | None = None
```

with `from typing import Callable` at the top. Replace the `"job": None,` line in `snapshot()` with:

```python
                "job": self.job_source() if self.job_source else None,
```

Note this call happens with `MachineState._lock` held, and `Job.snapshot()` takes only `Job._lock` — a leaf — so the existing `Streamer._lock` → `MachineState._lock` → leaf ordering is preserved.

In `Session.start_job`, after creating the job, add:

```python
        self.state.job_source = job.snapshot
```

and in `Session.connect()`, right after building the new `MachineState`, add:

```python
        self.job = None
        self.state.job_source = None
```

- [ ] **Step 6: Run the job runner tests**

```bash
cd /c/pcb_ui/serverside && python -m pytest tests/test_job_runner.py -v
```

Expected: PASS. Two likely snags:
- `GrblSim` may not expose `check_mode` as a public attribute; check `grbl/sim.py` and use whatever name it has, or add the attribute if `$C` is handled without recording state.
- `Streamer._drop` is private; if the ported streamer names it differently, use the real name.

- [ ] **Step 7: Add the run endpoints to `serverside/server.py`**

```python
class RunRequest(BaseModel):
    board_id: str
    check: bool = False


@app.post("/machine/run")
def machine_run(body: RunRequest):
    """Stream a stored board's G-code to the connected machine.

    `check` brackets the job with GRBL's $C: every line is parsed and
    validated, no motor moves. It is the cheapest way to find out the file
    is acceptable before it is also expensive to be wrong about.
    """
    try:
        oid = ObjectId(body.board_id)
    except InvalidId:
        raise HTTPException(404, "Board not found.")
    board = db.boards.find_one({"_id": oid})
    if not board:
        raise HTTPException(404, "Board not found.")
    gcode = board.get("gcode")
    if not gcode:
        raise HTTPException(400, "This board has no G-code to send.")

    lines = load_lines(gcode)
    if not lines:
        raise HTTPException(400, "This board's G-code has no instructions.")

    job = session.start_job(lines, body.check, board.get("name", "board"))
    return {"ok": True, "total": len(lines), "check": job.check}


@app.post("/machine/pause")
def machine_pause():
    session.require_job().pause()
    return {"ok": True}


@app.post("/machine/resume")
def machine_resume():
    session.require_job().resume()
    return {"ok": True}


@app.post("/machine/stop")
def machine_stop():
    session.require_job().stop()
    return {"ok": True}
```

Add `from job import load_lines` to the imports.

- [ ] **Step 8: Add an endpoint test**

Append to `serverside/tests/test_machine_api.py`:

```python
def test_run_without_a_connection_is_409(client):
    r = client.post("/machine/run", json={"board_id": "0" * 24, "check": False})
    assert r.status_code == 409


def test_pause_without_a_job_is_409(client):
    client.post("/machine/connect", json={"port": "SIM", "baud": 115200})
    assert client.post("/machine/pause").status_code == 409
```

- [ ] **Step 9: Run the whole suite**

```bash
cd /c/pcb_ui/serverside && python -m pytest
```

Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
cd /c/pcb_ui
git add serverside/job.py serverside/machine.py serverside/grbl/state.py serverside/server.py serverside/tests/test_job_runner.py serverside/tests/test_machine_api.py
git commit -m "feat: stream a board's G-code to the machine

Progress is counted in acknowledged lines, not sent lines, and neither is
claimed to be the pen's position. Pause feed-holds as well as stopping the
feed, because the controller may hold a hundred queued moves. Stop keeps
the operator's work zero; e-stop, which does not, stays its own endpoint."
```

---

### Task 6: The live-state WebSocket

One socket carrying machine state, job progress, and console lines to the browser at up to 10 Hz.

**Files:**
- Modify: `serverside/server.py`
- Test: `serverside/tests/test_machine_ws.py`

**Interfaces:**
- Consumes: `machine.session`, `MachineState.snapshot()`, `MachineState.console_tail()`, `MachineState.console_head_seq()`.
- Produces: `WS /machine/ws`, sending JSON frames `{"type": "snapshot", "data": <MachineState.snapshot()>}` and `{"type": "console", "data": [{"direction", "text", "kind", "seq"}]}`.

- [ ] **Step 1: Write the failing test**

`serverside/tests/test_machine_ws.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /c/pcb_ui/serverside && python -m pytest tests/test_machine_ws.py -v
```

Expected: FAIL — the route does not exist.

- [ ] **Step 3: Port the WebSocket handler**

Copy slice-1's `main.py` `ws_endpoint` (lines 806–877) into `server.py` as `@app.websocket("/machine/ws")`, keeping the body and its comments verbatim. The two mechanisms it documents are both load-bearing and must survive the copy:

- **Object-identity resync.** `Session.connect()` rebinds `session.state` to a brand-new `MachineState`, restarting `seq` at 0. The loop compares `session.state is not state`, not sequence numbers, because a short prior connection can leave a small cursor that the new state races past — silently dropping the new session's opening lines.
- **Per-consumer `seq`, not the shared `dirty` flag.** `dirty` is one flag on `MachineState`; a second socket or a `GET /machine/state` poll steals the notification and this loop falls back to the 1 Hz keepalive for no visible reason.

Add the imports `asyncio`, `time` (check whether `server.py` already imports them) and `from fastapi import WebSocket, WebSocketDisconnect`.

- [ ] **Step 4: Run the tests**

```bash
cd /c/pcb_ui/serverside && python -m pytest tests/test_machine_ws.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /c/pcb_ui
git add serverside/server.py serverside/tests/test_machine_ws.py
git commit -m "feat: /machine/ws live state socket

Resyncs on MachineState object identity rather than sequence numbers, so a
reconnect cannot silently drop the new session's opening lines."
```

---

### Task 7: Remove the ESP32 path

The teardown. Deliberately its own task and its own commit, so the additive work above can be reviewed without the deletions tangled into it, and so this is revertible on its own.

**Files:**
- Modify: `serverside/server.py`
- Modify: `serverside/db.py`
- Create: `serverside/tests/test_machine_memory.py`

**Interfaces:**
- Consumes: `db.machines`.
- Produces:
  - `GET /machine/last` `?email=` → `{"port": str, "baud": int} | null`
  - `POST /machine/connect` additionally records `{user_email, last_port, last_baud}` when the request carries an `email`.
  - `ConnectRequest` gains `email: str | None = None`.

- [ ] **Step 1: Delete the ESP32 code from `serverside/server.py`**

Remove: `ESP_TIMEOUT`, `esp_base()`, `esp_request()`, `_device_for()`, `default_device()`, `out_device()`, the `PrintJob` and `RenameDevice` models, and the routes `POST /print`, `GET /print/status/{email}`, `POST /print/stop`, `GET /devices/{email}`, `POST /devices/pair`, `POST /devices/unpair`, `PATCH /devices/{email}`. Drop the now-unused `urllib.request` / `urllib.error` imports if nothing else uses them. Update the module docstring's endpoint list at the top of the file.

Confirm nothing is left behind:

```bash
cd /c/pcb_ui/serverside && grep -n "esp_\|ESP_\|/print\|devices" server.py db.py
```

Expected: no output.

- [ ] **Step 2: Swap the collection in `serverside/db.py`**

```python
users = db["users"]
machines = db["machines"]
boards = db["boards"]
```

Delete the `devices` binding and any index declared on it; update the module docstring, which names the three collections.

- [ ] **Step 3: Write the failing test**

`serverside/tests/test_machine_memory.py`:

```python
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
```

- [ ] **Step 4: Run it to verify it fails**

```bash
cd /c/pcb_ui/serverside && python -m pytest tests/test_machine_memory.py -v
```

Expected: FAIL — 404 on `/machine/last`.

- [ ] **Step 5: Implement the memory**

Extend `ConnectRequest`:

```python
class ConnectRequest(BaseModel):
    port: str
    baud: int = 115200
    email: str | None = None
```

In `machine_connect`, after a successful `session.connect(...)`:

```python
    if body.email:
        # A convenience crumb so Connect is one click next session. It carries
        # no identity and no authority: it cannot make a port exist, and
        # connecting never consults it.
        db.machines.replace_one(
            {"user_email": body.email.strip().lower()},
            {"user_email": body.email.strip().lower(),
             "last_port": body.port, "last_baud": body.baud},
            upsert=True,
        )
```

And the reader:

```python
@app.get("/machine/last")
def machine_last(email: str):
    doc = db.machines.find_one({"user_email": email.strip().lower()})
    if not doc:
        return None
    return {"port": doc["last_port"], "baud": doc["last_baud"]}
```

- [ ] **Step 6: Run the tests**

```bash
cd /c/pcb_ui/serverside && python -m pytest tests/test_machine_memory.py -v
```

Expected: PASS (needs MongoDB on localhost:27017).

- [ ] **Step 7: Run the whole suite and check the app still imports**

```bash
cd /c/pcb_ui/serverside && python -m pytest && python -c "import server; print(len(server.app.routes), 'routes')"
```

Expected: all PASS, and the import succeeds with no `NameError` from a half-removed reference.

- [ ] **Step 8: Commit**

```bash
cd /c/pcb_ui
git add serverside/server.py serverside/db.py serverside/tests/test_machine_memory.py
git commit -m "refactor: drop the ESP32 bridge and device pairing

The machine is on the end of a USB cable now, not on the network, so the
paired-device-by-ID model has nothing left to identify. The devices
collection becomes machines, holding only the last port and baud so
Connect is one click next session.

serverside/firmware/ is left on disk, unused."
```

---

### Task 8: Frontend machine client

The typed API surface and the hook that owns the WebSocket. Every later frontend task consumes this.

**Files:**
- Modify: `userpage/lib/api.ts`
- Create: `userpage/lib/machine.ts`

**Interfaces:**
- Consumes: the endpoints from Tasks 3–7.
- Produces:
  - Types in `lib/api.ts`: `PortInfo`, `PortList`, `JobSnapshot`, `MachineSnapshot`.
  - `api.machinePorts()`, `api.machineConnect(port, baud, email?)`, `api.machineDisconnect()`, `api.machineState()`, `api.machineLast(email)`, `api.jog(axis, distance, feed?)`, `api.jogCancel()`, `api.home()`, `api.unlock()`, `api.zero(axes)`, `api.command(line)`, `api.estop()`, `api.run(boardId, check)`, `api.pauseJob()`, `api.resumeJob()`, `api.stopJob()`.
  - `lib/machine.ts`: `useMachine(): { snap: MachineSnapshot | null; console: ConsoleLine[]; connected: boolean; live: boolean }` — `live` is the socket's own health, distinct from `connected`, which is the machine's.

- [ ] **Step 1: Replace the device and print types in `lib/api.ts`**

Delete the `Device` type, `PrintStart`, `PrintState`, `PrintStatus`, and the methods `getDevice`, `pairDevice`, `unpair`, `renameDevice`, `startPrint`, `printStatus`, `stopPrint`. Add:

```typescript
export type PortInfo = {
  device: string;
  description: string;
  chip: string | null;
  likely_controller: boolean;
};

export type PortList = {
  ports: PortInfo[];
  /** Filled only when exactly one candidate was found — never a guess. */
  suggested: string | null;
  bauds: number[];
};

export type JobState =
  | "idle" | "running" | "paused" | "done" | "error" | "stopped";

export type JobSnapshot = {
  name: string;
  state: JobState;
  /** Lines handed to the controller. Runs ahead of the pen. */
  sent: number;
  /** Lines the controller has parsed and queued. Also ahead of the pen. */
  acked: number;
  total: number;
  check: boolean;
  error: string | null;
  errorLine: number | null;
};

export type MachineSnapshot = {
  conn: {
    connected: boolean;
    port: string | null;
    baud: number;
    firmware: string;
    profile: string;
    penMode: string;
    travel: [number, number, number];
  };
  state: string;
  mpos: [number, number, number];
  wpos: [number, number, number];
  wco: [number, number, number];
  feed: number;
  spindle: number;
  pen: string;
  alarm: string | null;
  error: string | null;
  job: JobSnapshot | null;
  seq: number;
};

export type ConsoleLine = {
  direction: string;
  text: string;
  kind: string;
  seq: number;
};
```

- [ ] **Step 2: Add the methods to the `api` object**

```typescript
  // --- machine (USB serial, owned by the backend on this same PC) ---
  machinePorts: () => req<PortList>("/machine/ports"),

  machineConnect: (port: string, baud: number, email?: string) =>
    req<{ ok: boolean; firmware: string }>("/machine/connect", {
      method: "POST",
      body: JSON.stringify({ port, baud, email }),
    }),

  machineDisconnect: () =>
    req<{ ok: boolean }>("/machine/disconnect", { method: "POST" }),

  machineState: () => req<MachineSnapshot>("/machine/state"),

  machineLast: (email: string) =>
    req<{ port: string; baud: number } | null>(
      `/machine/last?email=${encodeURIComponent(email)}`
    ),

  jog: (axis: string, distance: number, feed = 1000) =>
    req<{ ok: boolean }>("/machine/jog", {
      method: "POST",
      body: JSON.stringify({ axis, distance, feed }),
    }),

  jogCancel: () =>
    req<{ ok: boolean }>("/machine/jog/cancel", { method: "POST" }),

  home: () => req<{ ok: boolean }>("/machine/home", { method: "POST" }),

  unlock: () => req<{ ok: boolean }>("/machine/unlock", { method: "POST" }),

  zero: (axes: string) =>
    req<{ ok: boolean }>("/machine/zero", {
      method: "POST",
      body: JSON.stringify({ axes }),
    }),

  command: (line: string) =>
    req<{ ok: boolean }>("/machine/command", {
      method: "POST",
      body: JSON.stringify({ line }),
    }),

  estop: () => req<{ ok: boolean }>("/machine/estop", { method: "POST" }),

  run: (boardId: string, check: boolean) =>
    req<{ ok: boolean; total: number; check: boolean }>("/machine/run", {
      method: "POST",
      body: JSON.stringify({ board_id: boardId, check }),
    }),

  pauseJob: () => req<{ ok: boolean }>("/machine/pause", { method: "POST" }),
  resumeJob: () => req<{ ok: boolean }>("/machine/resume", { method: "POST" }),
  stopJob: () => req<{ ok: boolean }>("/machine/stop", { method: "POST" }),
```

- [ ] **Step 3: Write `userpage/lib/machine.ts`**

```typescript
"use client";

import { useEffect, useRef, useState } from "react";

import { API_URL, type ConsoleLine, type MachineSnapshot } from "@/lib/api";

const CONSOLE_LIMIT = 300;

function wsUrl(): string {
  // API_URL is an http(s) origin; the socket lives on the same one.
  return API_URL.replace(/^http/, "ws") + "/machine/ws";
}

/**
 * Subscribes to the machine's live state.
 *
 * Two different notions of "connected" live here and are deliberately not
 * merged: `live` is whether this browser is talking to the server, and
 * `snap.conn.connected` is whether the server is talking to the machine.
 * A page that conflates them tells you the plotter is offline when in fact
 * your own socket dropped, which sends you to check the wrong cable.
 */
export function useMachine() {
  const [snap, setSnap] = useState<MachineSnapshot | null>(null);
  const [lines, setLines] = useState<ConsoleLine[]>([]);
  const [live, setLive] = useState(false);
  const retry = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;

    function open() {
      ws = new WebSocket(wsUrl());

      ws.onopen = () => setLive(true);

      ws.onmessage = (ev) => {
        const frame = JSON.parse(ev.data);
        if (frame.type === "snapshot") {
          setSnap(frame.data as MachineSnapshot);
        } else if (frame.type === "console") {
          setLines((prev) =>
            [...prev, ...(frame.data as ConsoleLine[])].slice(-CONSOLE_LIMIT)
          );
        }
      };

      ws.onclose = () => {
        setLive(false);
        if (closed) return;
        // The server restarts constantly under --reload during development,
        // and a dropped socket that never comes back looks exactly like a
        // dead machine. Retry rather than making the user reload the page.
        retry.current = setTimeout(open, 1000);
      };

      ws.onerror = () => ws?.close();
    }

    open();
    return () => {
      closed = true;
      if (retry.current) clearTimeout(retry.current);
      ws?.close();
    };
  }, []);

  return {
    snap,
    console: lines,
    live,
    connected: Boolean(snap?.conn.connected),
  };
}
```

- [ ] **Step 4: Confirm `API_URL` is exported from `lib/api.ts`**

```bash
cd /c/pcb_ui/userpage && grep -n "API_URL" lib/api.ts | head -3
```

If it is declared but not exported, add `export` to its declaration.

- [ ] **Step 5: Type-check**

```bash
cd /c/pcb_ui/userpage && npx tsc --noEmit
```

Expected: errors ONLY in `app/connect/page.tsx`, `app/dashboard/device/page.tsx`, `app/dashboard/page.tsx`, and `app/dashboard/projects/[id]/page.tsx`, all referring to the removed `Device` / print methods. Those pages are Tasks 9, 10 and 12. No errors in `lib/`.

- [ ] **Step 6: Commit**

```bash
cd /c/pcb_ui
git add userpage/lib/api.ts userpage/lib/machine.ts
git commit -m "feat: machine API client and the live-state hook

Keeps 'this browser is talking to the server' and 'the server is talking to
the machine' as two separate booleans: conflating them sends the user to
check the wrong cable."
```

---

### Task 9: The connect page

`/connect` stops asking for a device ID and starts listing serial ports.

**Files:**
- Rewrite: `userpage/app/connect/page.tsx`
- Modify: `userpage/app/dashboard/page.tsx` (fix the removed-`Device` type errors)

**Interfaces:**
- Consumes: `api.machinePorts`, `api.machineConnect`, `api.machineLast`, `useMachine`.
- Produces: no new exports; navigates to `/dashboard/device` on a successful connect.

- [ ] **Step 1: Read the current page to keep its visual language**

```bash
cd /c/pcb_ui/userpage && cat app/connect/page.tsx
```

Note the wrapper elements, the `tlabel` class, the panel styling, and the button classes. The rewrite keeps them — this is a content change, not a redesign.

- [ ] **Step 2: Rewrite the page**

Replace the body with a port picker. Requirements, all of which have a reason:

- On mount, `api.machinePorts()`. Also `api.machineLast(email)` when a session email is in localStorage (follow the existing pages' pattern for reading it).
- Pre-select `suggested`, else the remembered `port` if it is in the list. Never pre-select otherwise — the backend deliberately returns `suggested: null` when two candidates are present, and the UI must not undo that by picking the first.
- Render each port as `device — description`, with the chip name and a "likely controller" mark where present.
- A **Rescan** button. Plugging a cable in after the page loaded is the normal case, not the exception.
- Baud `<select>` from `bauds`, defaulting to the remembered baud or 115200.
- Empty list renders "No serial ports found — is the cable plugged in?" plus the Rescan button. Never an empty box.
- Connect calls `api.machineConnect(port, baud, email)`, shows the returned firmware string on success, then routes to `/dashboard/device`.
- Errors render the thrown message verbatim. The backend's 502 already says which port and why; paraphrasing it to "Connection failed" throws away the only useful part.
- Below the button, a standing note:

> Connecting resets the controller, so work zero is cleared every time you connect. Set it on the Machine page before plotting.

- [ ] **Step 3: Fix `app/dashboard/page.tsx`**

It renders the paired device. Replace that card with a machine-connection card driven by `useMachine()`: when `connected`, show the port and firmware; when not, a "Connect a machine" link to `/connect`. Delete every `Device` import and `api.getDevice` call.

- [ ] **Step 4: Type-check and run**

```bash
cd /c/pcb_ui/userpage && npx tsc --noEmit
```

Expected: remaining errors only in `app/dashboard/device/page.tsx` and `app/dashboard/projects/[id]/page.tsx` (Tasks 10 and 12).

- [ ] **Step 5: Check it by hand against the simulator**

```bash
# terminal 1
cd /c/pcb_ui/serverside && TRACEWORKS_SIM=1 uvicorn server:app --reload --port 8000
# terminal 2
cd /c/pcb_ui/userpage && npm run dev
```

Open `http://localhost:3000/connect`. Expected: the list shows "SIM — Simulator (GRBL 1.1) — no hardware", pre-selected; Connect reports a `Grbl 1.1h` firmware string and lands on the machine page.

- [ ] **Step 6: Commit**

```bash
cd /c/pcb_ui
git add userpage/app/connect/page.tsx userpage/app/dashboard/page.tsx
git commit -m "feat: /connect picks a serial port instead of a device ID

Pre-selects only what the backend suggested, which is never a guess between
two plausible boards. Says out loud that connecting clears work zero."
```

---

### Task 10: The machine page

`/dashboard/device` becomes the place you set up the machine before a job: position, jog, zero, home, console, E-stop.

**Files:**
- Rewrite: `userpage/app/dashboard/device/page.tsx`
- Create: `userpage/components/JogPad.tsx`
- Create: `userpage/components/Dro.tsx`
- Create: `userpage/components/MachineConsole.tsx`

**Interfaces:**
- Consumes: `useMachine`, `api.jog`, `api.zero`, `api.home`, `api.unlock`, `api.estop`, `api.command`, `api.machineDisconnect`.
- Produces:
  - `<Dro snap={MachineSnapshot | null} />`
  - `<JogPad disabled={boolean} onJog={(axis: string, distance: number) => void} />` — owns its own step-size state.
  - `<MachineConsole lines={ConsoleLine[]} onSend={(line: string) => void} disabled={boolean} />`

- [ ] **Step 1: Write `components/Dro.tsx`**

A digital readout: X, Y, Z in `wpos` (work coordinates — what the operator sets zero in and thinks in), with `mpos` smaller beneath, in IBM Plex Mono. Fixed to 3 decimals and a **fixed-width** column, so the numbers do not jitter sideways as digits change. Show the GRBL state word (`Idle` / `Run` / `Alarm` / …) as a badge; `Alarm` reads in the theme's warn colour. When `snap` is null or disconnected, render dashes rather than stale numbers.

- [ ] **Step 2: Write `components/JogPad.tsx`**

- Step size radio group: 0.1, 1, 10 mm. Default 1.
- X−/X+/Y−/Y+ in a cross layout, Z−/Z+ in a separate column, because mixing the pen axis into the same cross is how a pen gets driven into a board.
- Every button calls `onJog(axis, ±step)`.
- Disabled while `disabled` — the page passes `!connected || state === "Alarm" || jobRunning`.
- Keyboard: arrow keys for X/Y, PageUp/PageDown for Z, only while the pad has focus. Never bind them globally: a page-wide arrow-key listener moves a machine when the user is scrolling.

- [ ] **Step 3: Write `components/MachineConsole.tsx`**

A scrolling monospace log of `direction`/`text`, sent lines and replies distinguished by colour, `error`/`alarm` lines in the warn colour, auto-scrolled to the bottom **unless the user has scrolled up** (compare `scrollTop + clientHeight` against `scrollHeight` before scrolling). Below it, a single-line input that sends on Enter via `onSend`.

- [ ] **Step 4: Rewrite `app/dashboard/device/page.tsx`**

Compose them:

- Header: connection status, port, baud, firmware, and a Disconnect button. When disconnected, the whole page shows a "No machine connected" state with a link to `/connect`.
- `<Dro />`.
- `<JogPad />` beside Zero X / Zero Y / Zero Z / Zero All buttons (`api.zero("X")` … `api.zero("XYZ")`).
- Home (`api.home`) and Unlock (`api.unlock`) buttons. Unlock is visually prominent only while `state === "Alarm"`, because that is the only time it means anything.
- A red E-stop, visually separated from everything else so it is never a mis-click of an adjacent control. It calls `api.estop()` directly with **no confirmation dialog** — a stop that asks "are you sure?" is not a stop.
- The standing note that connecting reset the controller and cleared work zero.
- `useMachine()`'s `live === false` renders a "reconnecting…" strip, distinct from the machine being disconnected.

- [ ] **Step 5: Type-check**

```bash
cd /c/pcb_ui/userpage && npx tsc --noEmit
```

Expected: remaining errors only in `app/dashboard/projects/[id]/page.tsx` (Task 12).

- [ ] **Step 6: Check it by hand against the simulator**

With both servers running (as in Task 9 Step 5), connect to `SIM` and open `/dashboard/device`. Expected: the DRO shows `0.000` on all axes; a jog of X+10 moves the X readout to `10.000` and it stops there; Zero All sets `wpos` to zeros while `mpos` stays at 10; the console shows the sent lines and their `ok` replies.

- [ ] **Step 7: Commit**

```bash
cd /c/pcb_ui
git add userpage/app/dashboard/device/page.tsx userpage/components/JogPad.tsx userpage/components/Dro.tsx userpage/components/MachineConsole.tsx
git commit -m "feat: the machine page - DRO, jog pad, zeroing, console, e-stop

Z is a separate column from the XY cross because mixing the pen axis into
the same cross is how a pen gets driven into a board. E-stop takes no
confirmation: a stop that asks 'are you sure?' is not a stop."
```

---

### Task 11: Teach the visualizer to follow the machine

Two new optional props. Existing usage must be untouched.

**Files:**
- Modify: `userpage/lib/gcode.ts`
- Modify: `userpage/components/GcodeVisualizer.tsx`
- Create: `userpage/lib/gcode.test.ts` **only if** the frontend already has a test runner configured — check `userpage/package.json` first; if there is none, verify by hand in Step 4 instead and do not add a test framework as part of this task.

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `Segment` gains `line: number` — the 1-based source line number in the **cleaned** line list (`load_lines` order), which is what the backend counts, so the two agree.
  - `parseGcode` fills it.
  - `GcodeVisualizer` props gain `liveIndex?: number | null` and `penPos?: [number, number, number] | null`.

- [ ] **Step 1: Add the line number to the parser**

In `lib/gcode.ts`, add to the `Segment` type:

```typescript
  /**
   * 1-based index of the source line in the CLEANED line list — comments and
   * blanks stripped, exactly as serverside/job.py's load_lines() counts them.
   * The backend reports progress as a count of those lines, so anything else
   * here would drift by however many comments the file happens to carry.
   */
  line: number;
```

In `parseGcode`, maintain a counter that increments once per non-blank, non-comment line **before** the line is interpreted, and stamp it onto every segment that line emits.

- [ ] **Step 2: Add the props to the visualizer**

```typescript
type Props = {
  gcode: string;
  className?: string;
  /**
   * The last line the controller acknowledged, or null when no job is
   * running. Drives which segments render as drawn.
   *
   * Deliberately not used to place the pen: GRBL acknowledges a line when
   * it has parsed and QUEUED it, not when it has executed it, so this index
   * runs ahead of the machine — sometimes by a hundred moves.
   */
  liveIndex?: number | null;
  /** The machine's reported work position. Where the pen actually is. */
  penPos?: [number, number, number] | null;
};
```

- [ ] **Step 3: Wire them in**

- When `liveIndex` is a number, drive the existing scrub `apply(p)` from it instead of from the slider. Segments are in file order, so a binary search finds the boundary:

```typescript
/** Progress 0..1 for "the controller has acknowledged through line N".
 *
 * Segments carry the cleaned-file line number they came from, and one line
 * can emit several segments (a G1 with X, Y and Z all changing). Take the
 * LAST segment of the acknowledged line, not the first, or the path lags a
 * segment behind the machine for the whole job.
 */
function progressForLine(
  segments: Segment[],
  ends: Float64Array,
  total: number,
  line: number
): number {
  if (segments.length === 0 || total === 0) return 0;
  if (line <= 0) return 0;

  let lo = 0;
  let hi = segments.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (segments[mid].line <= line) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  if (found < 0) return 0;
  return ends[found] / total;
}
```

Call it in an effect that runs whenever `liveIndex` changes, and hand the result to the existing `api.current.apply(p)`:

```typescript
useEffect(() => {
  if (liveIndex == null || !api.current) return;
  const p = progressForLine(
    parsed.segments, timeline.ends, timeline.total, liveIndex
  );
  progressRef.current = p;
  setProgress(p);
  api.current.apply(p);
}, [liveIndex, parsed, timeline]);
```
- Hide the play/scrub controls while `liveIndex` is a number — a scrubber that fights a live feed is a confusing control. Restore them when it returns to null.
- When `penPos` is given, place the pen mesh at that coordinate instead of at the scrub point, so the pen sits where the machine says it is even though the drawn path is ahead of it.
- When both props are absent or null, every existing behaviour is unchanged, scrub timeline included.

- [ ] **Step 4: Verify the existing behaviour is untouched**

```bash
cd /c/pcb_ui/userpage && npx tsc --noEmit && npm run build
```

Then, with both servers running, open any existing board page. Expected: the visualizer plays, scrubs, toggles travel, and adjusts pen lift exactly as before — this task adds no live data yet.

- [ ] **Step 5: Commit**

```bash
cd /c/pcb_ui
git add userpage/lib/gcode.ts userpage/components/GcodeVisualizer.tsx
git commit -m "feat: the visualizer can follow a running job

liveIndex marks segments drawn; penPos places the pen. Kept separate on
purpose: GRBL acks a line when it queues it, so the acked index runs ahead
of where the pen actually is."
```

---

### Task 12: Run a board

The payoff task: press Plot on a board page and watch it draw.

**Files:**
- Modify: `userpage/app/dashboard/projects/[id]/page.tsx` (the stream panel, around lines 360–530)

**Interfaces:**
- Consumes: `useMachine`, `api.run`, `api.pauseJob`, `api.resumeJob`, `api.stopJob`, and the `GcodeVisualizer` props from Task 11.
- Produces: no new exports.

- [ ] **Step 1: Read the existing panel**

```bash
cd /c/pcb_ui/userpage && sed -n 355,535p "app/dashboard/projects/[id]/page.tsx"
```

The panel's shape — the "Stream to device" label, the dry-check toggle, the phase machine, the button row — is kept. What changes is where the state comes from: it stops being local `useState` polled from `/print/status` and becomes derived from `useMachine()`'s `snap.job`.

- [ ] **Step 2: Replace the local phase machine with the job snapshot**

Delete the `phase` state, the `startJob` polling effect, and every `api.startPrint` / `api.printStatus` / `api.stopPrint` call. Derive from `const { snap, connected, live } = useMachine()`:

```typescript
const job = snap?.job ?? null;
const running = job?.state === "running";
const paused = job?.state === "paused";
const active = running || paused;
// A job started from another tab, or before this page was opened, is still
// this machine's job. Read it from the snapshot rather than tracking it
// locally, or two tabs will disagree about whether the machine is busy.
const mine = job?.name === board.name;
```

Panel states and their controls:

| Condition | Panel shows |
|---|---|
| `!connected` | "No machine connected" and a link to `/connect`. The Plot button is disabled — never let it fail with a 409 the user has to decode. |
| `connected && !active` | The dry-check toggle and **Validate & plot** / **Plot now** |
| `running` | Progress, **Pause**, **Stop** |
| `paused` | Progress, **Resume**, **Stop** |
| `job.state === "done"` | "Finished — N lines" and a Plot again button |
| `job.state === "error"` | `job.error` verbatim, including the line number, plus Plot again |
| `job.state === "stopped"` | "Stopped at line N of M" plus Plot again |

Progress reads `job.acked / job.total`, labelled **"lines sent"** — not "complete". The controller has queued them; the pen has not necessarily drawn them, and a bar that claims otherwise finishes seconds before the machine does.

- [ ] **Step 3: Feed the visualizer**

```tsx
<GcodeVisualizer
  gcode={board.gcode}
  liveIndex={active && mine ? job.acked : null}
  penPos={active && mine ? snap!.wpos : null}
/>
```

- [ ] **Step 4: Type-check and build**

```bash
cd /c/pcb_ui/userpage && npx tsc --noEmit && npm run build
```

Expected: clean. This is the last file that referenced the removed print API, so `tsc` should now be fully green.

- [ ] **Step 5: Run a whole board against the simulator**

With `TRACEWORKS_SIM=1` on the backend and the frontend running: connect to `SIM` on `/connect`, open a board, toggle **Dry-check** on, press **Validate & plot**. Expected: the progress bar advances, the toolpath fills in, the pen marker tracks `wpos`, and the panel ends on "Finished". Then turn the toggle off, press **Plot now**, and confirm Pause holds the counters and Resume continues from the same line.

- [ ] **Step 6: Commit**

```bash
cd /c/pcb_ui
git add "userpage/app/dashboard/projects/[id]/page.tsx"
git commit -m "feat: plot a board over USB, with the visualizer following

Progress is labelled 'lines sent', not 'complete': the controller has
queued them and the pen has not necessarily drawn them. Job state comes
from the machine snapshot, so two tabs cannot disagree about it."
```

---

### Task 13: Documentation

Documentation describing a transport the code no longer has is worse than none.

**Files:**
- Modify: `README.md`
- Modify: `RUNNING.md`
- Modify: `serverside/README.md`
- Modify: `serverside/DOCS.md`
- Modify: `serverside/HARDWARE.md`
- Modify: `serverside/firmware/README.md`

- [ ] **Step 1: Find every claim that is now false**

```bash
cd /c/pcb_ui && grep -rn "device ID\|pairing\|paired\|ESP32\|FluidNC handshake\|/print\|ESP_BASE_URL\|esp_mock" README.md RUNNING.md serverside/*.md
```

Every hit is either rewritten or deleted.

- [ ] **Step 2: Update the root `README.md`**

- The opening paragraph's "stream it to a FluidNC machine, paired to your account by **device ID**" becomes streaming over USB to a GRBL controller on this PC.
- The pages table: `/connect` is now "**Machine connect**: pick the serial port and connect"; `/dashboard/device` is "Machine: live position, jog, zero, home, console, E-stop".
- The "How it connects" section: replace the pairing paragraph with the USB one — the backend owns the port because it runs on the same PC as the browser.
- Add the simulator to the run instructions: `TRACEWORKS_SIM=1` gives a `SIM` port so the whole app is usable with no hardware.
- Note in the caveats that connecting resets the controller and clears work zero.

- [ ] **Step 3: Update `RUNNING.md`**

Add `TRACEWORKS_SIM=1` to the environment-variable section. Delete `ESP_BASE_URL`. Add a troubleshooting entry: **"No serial ports found"** — on Windows, check Device Manager for the CH340/CP2102 driver; on Linux, the user must be in the `dialout` group.

- [ ] **Step 4: Update the `serverside/` docs**

`README.md` and `DOCS.md`: replace the `/print` and `/devices/*` endpoint documentation with the `/machine/*` table from the spec. Document `grbl/`, `machine.py`, and `job.py` alongside the existing pipeline modules. `HARDWARE.md`: the wiring and firmware notes stay, but the "pair the device" section becomes "plug in the USB cable".

- [ ] **Step 5: Mark the firmware directory unused**

At the top of `serverside/firmware/README.md`:

> **Not used by the API.** The backend now talks to the controller over USB
> serial (`serverside/grbl/`, `serverside/machine.py`). This directory keeps
> the ESP32 bridge sketch and `esp_mock.py` for reference and for a possible
> future wireless transport; nothing in the running app calls it.

- [ ] **Step 6: Verify no stale claims survive**

```bash
cd /c/pcb_ui && grep -rn "device ID\|pairing\|ESP_BASE_URL" README.md RUNNING.md serverside/*.md
```

Expected: no output outside `serverside/firmware/`.

- [ ] **Step 7: Full check, then commit**

```bash
cd /c/pcb_ui/serverside && python -m pytest
cd /c/pcb_ui/userpage && npx tsc --noEmit && npm run build
```

Expected: all PASS, clean build.

```bash
cd /c/pcb_ui
git add README.md RUNNING.md serverside/README.md serverside/DOCS.md serverside/HARDWARE.md serverside/firmware/README.md
git commit -m "docs: the machine is on a USB cable now, not on the network

Documents the /machine endpoints, the TRACEWORKS_SIM no-hardware path, and
that connecting resets the controller and clears work zero. Marks
serverside/firmware/ as no longer called by the app."
```

---

## Verification checklist

Run all of this after Task 13, with an actual Arduino attached:

- [ ] `cd serverside && python -m pytest` — all green
- [ ] `cd userpage && npx tsc --noEmit && npm run build` — clean
- [ ] Plug the FTDI cable in *after* loading `/connect`, press Rescan — the port appears with its chip name
- [ ] Connect at 115200 — the firmware banner is reported
- [ ] Jog X, Y, Z — the DRO tracks the real machine
- [ ] Jog past the envelope — refused with a message naming the axis, and the machine does not alarm
- [ ] Zero All — `wpos` goes to zero and `mpos` does not
- [ ] Plot a board with dry-check on — no motion, and it reports zero errors
- [ ] Plot the same board for real — the toolpath fills in and the pen marker follows
- [ ] Pause mid-plot — the machine stops within a second, not after the queue drains
- [ ] Resume — it continues from the same line, no repeated or skipped moves
- [ ] E-stop mid-plot — motion stops immediately and the UI shows Alarm
- [ ] Unplug the cable mid-plot — the job reports an error naming the lost link, and the UI does not sit at "running" forever
