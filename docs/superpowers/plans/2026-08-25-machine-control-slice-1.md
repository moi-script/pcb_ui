# Machine Control Core — Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `pcb_ui` from a multi-tenant web product into a single-user CNC workbench that can connect to a GRBL controller over USB, jog every axis, and show a live console — verified end to end against a GRBL simulator.

**Architecture:** One local FastAPI process (`server/`) owns the serial port; Next.js is a pure client. The protocol codec (`serial/grbl.py`) is pure functions with no I/O, so it is exhaustively testable. The streamer owns the port on its own thread and uses character-counting flow control. All live state lives in Python and reaches the browser as one snapshot over one WebSocket; commands go back as REST.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, pyserial, pytest. Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS v4.

**Spec:** `docs/superpowers/specs/2026-08-25-single-user-cnc-workspace-design.md`

## Global Constraints

- **Slice scope is connect + jog + console only.** No file streaming, no CAM, no calibration wizard, no job history. Their routes exist as stubs that say what is coming.
- **`app/globals.css` is not edited.** The theme is preserved verbatim. All new UI is built from its existing tokens: `panel`, `panel-2`, `ticked`, `tlabel`, `btn`, `btn-primary`, `btn-copper`, `btn-ghost`, `field`, `dot`, `dot-live`, `substrate`, and the colour names `ink`, `ink-soft`, `muted`, `faint`, `paper`, `well`, `line`, `line-strong`, `copper`, `signal`, `warn`, `danger`.
- **No users, no accounts, no email parameter** anywhere in the new code.
- **Realtime bytes are never counted against the RX buffer**, and never sent through `send_line`.
- **RX buffer default is 128 bytes** (GRBL 1.1). It is a profile field, not a constant at the call site.
- **`?` is polled at 5 Hz** (every 200 ms). The WebSocket pushes on state change, capped at 10 Hz, with a ~1 Hz keepalive when idle.
- **Disconnect detection:** 3 consecutive unanswered `?` polls at 500 ms each (~1.5 s worst case).
- Python code targets **3.12**, uses `from __future__ import annotations`, and is type-annotated.
- Tests run with `python -m pytest server/tests/ -v` from the repo root.

### Deviation from the spec, agreed before planning

The spec lists `board_raw.json` as deleted and `PcbBoard.tsx` as growing into the live canvas. Slice 1 has no toolpath to draw, so instead a **new** `components/workspace/MachineCanvas.tsx` draws the work envelope, the live crosshair, and a jog trail. `PcbBoard.tsx`, `lib/board.ts`, and `board_raw.json` are left untouched for subsystem 2.

---

## File Structure

### Created — Python backend

| File | Responsibility |
|---|---|
| `server/requirements.txt` | Python dependencies |
| `server/__init__.py` | package marker |
| `server/grbl_serial/__init__.py` | package marker (named `grbl_serial`, not `serial`, to avoid shadowing pyserial) |
| `server/grbl_serial/grbl.py` | Pure protocol codec. No I/O. |
| `server/grbl_serial/streamer.py` | Owns the port, reader loop, character-counting send loop, `?` polling |
| `server/grbl_serial/ports.py` | Port enumeration and Arduino identification |
| `server/machine/__init__.py` | package marker |
| `server/machine/state.py` | Authoritative live state, snapshot building |
| `server/machine/limits.py` | Work-envelope checks |
| `server/store/__init__.py` | package marker |
| `server/store/db.py` | SQLite: machine profiles |
| `server/sim/__init__.py` | package marker |
| `server/sim/grbl_sim.py` | Model of a GRBL controller, used as a transport in tests |
| `server/main.py` | FastAPI app: REST routes and `/ws` |
| `server/tests/*` | pytest suites |

### Created — frontend

| File | Responsibility |
|---|---|
| `lib/machine.ts` | Snapshot TypeScript types + `useMachine()` WebSocket hook |
| `lib/api.ts` | *(rewritten)* REST client, no email anywhere |
| `components/workspace/TopBar.tsx` | Connection control, state badge, E-stop |
| `components/workspace/Dro.tsx` | Digital readout |
| `components/workspace/JogPanel.tsx` | Jog buttons, step/feed selectors, zero/home |
| `components/workspace/Console.tsx` | Log + command input |
| `components/workspace/MachineCanvas.tsx` | Work envelope, live crosshair, jog trail |
| `app/page.tsx` | *(rewritten)* the workspace screen |
| `app/projects/page.tsx`, `app/settings/page.tsx`, `app/history/page.tsx` | stubs |

### Deleted

`app/login/`, `app/signup/`, `app/connect/`, `app/dashboard/`, `components/AuthAside.tsx`, `components/MarketingNav.tsx`, `components/Footer.tsx`, `lib/auth.tsx`, `lib/data.ts`.

### Modified

`app/layout.tsx` (drop `AuthProvider`, new metadata), `package.json` (dev script), `README.md`.

---

## Task 1: Teardown and scaffold

**Files:**
- Delete: `app/login/`, `app/signup/`, `app/connect/`, `app/dashboard/`, `components/AuthAside.tsx`, `components/MarketingNav.tsx`, `components/Footer.tsx`, `lib/auth.tsx`, `lib/data.ts`
- Modify: `app/layout.tsx`, `package.json`
- Create: `server/requirements.txt`, `server/__init__.py`, `server/grbl_serial/__init__.py`, `server/machine/__init__.py`, `server/store/__init__.py`, `server/sim/__init__.py`, `server/tests/__init__.py`, `pytest.ini`, `app/page.tsx`, `app/projects/page.tsx`, `app/settings/page.tsx`, `app/history/page.tsx`

**Interfaces:**
- Consumes: nothing
- Produces: the `server` package tree that every later Python task imports from; a placeholder `app/page.tsx` that Task 14 replaces

- [ ] **Step 1: Delete the multi-tenant frontend**

```bash
git rm -r app/login app/signup app/connect app/dashboard
git rm components/AuthAside.tsx components/MarketingNav.tsx components/Footer.tsx
git rm lib/auth.tsx lib/data.ts
```

- [ ] **Step 2: Strip `AuthProvider` out of the root layout**

Replace the whole of `app/layout.tsx` with:

```tsx
import type { Metadata } from "next";
import { Space_Grotesk, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

const grotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-grotesk",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono-plex",
  display: "swap",
});

export const metadata: Metadata = {
  title: "TraceWorks · CNC Workbench",
  description: "Connect, jog, and send G-code to your PCB plotter.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${grotesk.variable} ${plexMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
```

- [ ] **Step 3: Replace the marketing landing with a workspace placeholder**

Replace the whole of `app/page.tsx` with:

```tsx
export default function Workspace() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-paper substrate">
      <span className="tlabel">workspace — under construction</span>
    </main>
  );
}
```

- [ ] **Step 4: Create the three stub routes**

`app/projects/page.tsx`:

```tsx
export default function Projects() {
  return (
    <main className="min-h-screen bg-paper p-10">
      <span className="tlabel">projects</span>
      <p className="mt-3 text-sm text-muted">
        Board upload and G-code generation arrive with the CAM subsystem.
      </p>
    </main>
  );
}
```

`app/settings/page.tsx`:

```tsx
export default function Settings() {
  return (
    <main className="min-h-screen bg-paper p-10">
      <span className="tlabel">machine settings</span>
      <p className="mt-3 text-sm text-muted">
        Profile editing arrives with the settings subsystem. The active profile
        is seeded in the database.
      </p>
    </main>
  );
}
```

`app/history/page.tsx`:

```tsx
export default function History() {
  return (
    <main className="min-h-screen bg-paper p-10">
      <span className="tlabel">job history</span>
      <p className="mt-3 text-sm text-muted">
        Job logging arrives once file streaming lands.
      </p>
    </main>
  );
}
```

- [ ] **Step 5: Create the Python package tree**

```bash
mkdir -p server/grbl_serial server/machine server/store server/sim server/tests
touch server/__init__.py server/grbl_serial/__init__.py server/machine/__init__.py
touch server/store/__init__.py server/sim/__init__.py server/tests/__init__.py
```

Note the package is `grbl_serial`, **not** `serial` — a package named `serial` inside `server/` would shadow pyserial and break imports in confusing ways.

`server/requirements.txt`:

```
fastapi>=0.115
uvicorn[standard]>=0.32
pyserial>=3.5
pytest>=8.0
httpx>=0.27
```

`pytest.ini` at the repo root:

```ini
[pytest]
testpaths = server/tests
python_files = test_*.py
addopts = -ra
```

- [ ] **Step 6: Add the dev script**

In `package.json`, add to `devDependencies`: `"concurrently": "^9.1.0"`. Add to `scripts`:

```json
"dev:api": "uvicorn server.main:app --reload --port 8000",
"dev:all": "concurrently -n api,web -c magenta,cyan \"npm run dev:api\" \"npm run dev\""
```

- [ ] **Step 7: Verify the frontend still builds**

Run: `npm run build`
Expected: build succeeds. If it fails, the error names a file still importing `@/lib/auth` or `@/lib/data` — delete that import or the file.

- [ ] **Step 8: Verify pytest collects**

Run: `python -m pytest server/tests/ -v`
Expected: `no tests ran` — exit code 5, no collection errors.

- [ ] **Step 9: Commit**

```bash
pip install -r server/requirements.txt
git add -A
git commit -m "refactor: strip multi-tenant frontend, scaffold local server package"
```

---

## Task 2: GRBL status report parsing

**Files:**
- Create: `server/grbl_serial/grbl.py`
- Test: `server/tests/test_grbl_status.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `class State(str, Enum)` with members `IDLE RUN HOLD JOG ALARM DOOR CHECK HOME SLEEP`
  - `@dataclass(frozen=True) Status(state: State, substate: int | None, mpos: tuple[float,float,float] | None, wpos: tuple[float,float,float] | None, wco: tuple[float,float,float] | None, feed: float, spindle: float, ov: tuple[int,int,int] | None, pins: str)`
  - `parse_status(line: str) -> Status | None`
  - `resolve_positions(status: Status, cached_wco: tuple[float,float,float] | None) -> tuple[tuple[float,float,float], tuple[float,float,float], tuple[float,float,float]]` returning `(mpos, wpos, wco)`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_grbl_status.py`:

```python
from __future__ import annotations

import pytest

from server.grbl_serial.grbl import State, Status, parse_status, resolve_positions


def test_parses_minimal_idle_report():
    s = parse_status("<Idle|MPos:0.000,0.000,0.000|FS:0,0>")
    assert s is not None
    assert s.state is State.IDLE
    assert s.substate is None
    assert s.mpos == (0.0, 0.0, 0.0)
    assert s.wpos is None
    assert s.wco is None
    assert s.feed == 0.0
    assert s.spindle == 0.0


def test_parses_full_run_report():
    s = parse_status(
        "<Run|MPos:124.500,62.858,5.000|FS:800,0"
        "|WCO:100.000,50.000,0.000|Ov:100,100,100|Pn:XY>"
    )
    assert s is not None
    assert s.state is State.RUN
    assert s.mpos == (124.5, 62.858, 5.0)
    assert s.wco == (100.0, 50.0, 0.0)
    assert s.feed == 800.0
    assert s.ov == (100, 100, 100)
    assert s.pins == "XY"


def test_parses_hold_substate():
    s = parse_status("<Hold:0|MPos:1.000,2.000,3.000|FS:0,0>")
    assert s is not None
    assert s.state is State.HOLD
    assert s.substate == 0


def test_parses_wpos_variant():
    """Controllers with the $10 mask set to work coords report WPos, not MPos."""
    s = parse_status("<Idle|WPos:10.000,20.000,1.000|FS:0,0>")
    assert s is not None
    assert s.wpos == (10.0, 20.0, 1.0)
    assert s.mpos is None


def test_parses_alarm_state():
    s = parse_status("<Alarm|MPos:0.000,0.000,0.000|FS:0,0>")
    assert s is not None
    assert s.state is State.ALARM


def test_ignores_non_status_lines():
    assert parse_status("ok") is None
    assert parse_status("error:15") is None
    assert parse_status("[MSG:Reset to continue]") is None
    assert parse_status("") is None


def test_resolve_uses_reported_wco():
    s = parse_status("<Run|MPos:124.500,62.858,5.000|FS:0,0|WCO:100.000,50.000,0.000>")
    assert s is not None
    mpos, wpos, wco = resolve_positions(s, None)
    assert mpos == (124.5, 62.858, 5.0)
    assert wpos == pytest.approx((24.5, 12.858, 5.0))
    assert wco == (100.0, 50.0, 0.0)


def test_resolve_uses_cached_wco_when_report_omits_it():
    """WCO is only sent every ~10th report. Without the cache the DRO jumps."""
    s = parse_status("<Run|MPos:125.000,62.858,5.000|FS:0,0>")
    assert s is not None
    mpos, wpos, wco = resolve_positions(s, (100.0, 50.0, 0.0))
    assert mpos == (125.0, 62.858, 5.0)
    assert wpos == pytest.approx((25.0, 12.858, 5.0))
    assert wco == (100.0, 50.0, 0.0)


def test_resolve_assumes_zero_wco_when_never_seen():
    s = parse_status("<Idle|MPos:5.000,5.000,5.000|FS:0,0>")
    assert s is not None
    mpos, wpos, wco = resolve_positions(s, None)
    assert wco == (0.0, 0.0, 0.0)
    assert wpos == (5.0, 5.0, 5.0)


def test_resolve_derives_mpos_from_wpos_variant():
    s = parse_status("<Idle|WPos:10.000,20.000,1.000|FS:0,0>")
    assert s is not None
    mpos, wpos, wco = resolve_positions(s, (3.0, 4.0, 0.0))
    assert wpos == (10.0, 20.0, 1.0)
    assert mpos == pytest.approx((13.0, 24.0, 1.0))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest server/tests/test_grbl_status.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.grbl_serial.grbl'`

- [ ] **Step 3: Write the implementation**

Create `server/grbl_serial/grbl.py`:

```python
"""GRBL 1.1 / FluidNC protocol codec.

Pure functions and dataclasses: bytes in, values out. Nothing in this module
performs I/O, which is what lets the fiddly parts of the protocol be tested
exhaustively without a controller attached.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

Vec3 = tuple[float, float, float]


class State(str, Enum):
    IDLE = "Idle"
    RUN = "Run"
    HOLD = "Hold"
    JOG = "Jog"
    ALARM = "Alarm"
    DOOR = "Door"
    CHECK = "Check"
    HOME = "Home"
    SLEEP = "Sleep"


@dataclass(frozen=True)
class Status:
    """One parsed `<...>` status report."""
    state: State
    substate: int | None
    mpos: Vec3 | None
    wpos: Vec3 | None
    wco: Vec3 | None
    feed: float
    spindle: float
    ov: tuple[int, int, int] | None
    pins: str


def _vec3(text: str) -> Vec3:
    parts = [float(p) for p in text.split(",")]
    while len(parts) < 3:
        parts.append(0.0)
    return (parts[0], parts[1], parts[2])


def parse_status(line: str) -> Status | None:
    """Parse a GRBL status report. Returns None for any other line."""
    line = line.strip()
    if not line.startswith("<") or not line.endswith(">"):
        return None

    fields = line[1:-1].split("|")
    if not fields:
        return None

    head = fields[0]
    substate: int | None = None
    if ":" in head:
        name, _, sub = head.partition(":")
        try:
            substate = int(sub)
        except ValueError:
            substate = None
    else:
        name = head

    try:
        state = State(name)
    except ValueError:
        return None

    mpos = wpos = wco = None
    ov: tuple[int, int, int] | None = None
    feed = spindle = 0.0
    pins = ""

    for field in fields[1:]:
        key, _, value = field.partition(":")
        if key == "MPos":
            mpos = _vec3(value)
        elif key == "WPos":
            wpos = _vec3(value)
        elif key == "WCO":
            wco = _vec3(value)
        elif key == "FS":
            nums = value.split(",")
            feed = float(nums[0]) if nums and nums[0] else 0.0
            spindle = float(nums[1]) if len(nums) > 1 and nums[1] else 0.0
        elif key == "F":
            feed = float(value) if value else 0.0
        elif key == "Ov":
            nums = [int(n) for n in value.split(",")]
            while len(nums) < 3:
                nums.append(100)
            ov = (nums[0], nums[1], nums[2])
        elif key == "Pn":
            pins = value

    return Status(
        state=state,
        substate=substate,
        mpos=mpos,
        wpos=wpos,
        wco=wco,
        feed=feed,
        spindle=spindle,
        ov=ov,
        pins=pins,
    )


def resolve_positions(status: Status, cached_wco: Vec3 | None) -> tuple[Vec3, Vec3, Vec3]:
    """Return (mpos, wpos, wco), filling in whichever the report omitted.

    GRBL transmits WCO only about every tenth report, so the offset must be
    carried across reports. Treating a missing WCO as zero makes the readout
    jump every time it is left out, which is the classic sender bug.
    """
    wco: Vec3 = status.wco or cached_wco or (0.0, 0.0, 0.0)

    if status.mpos is not None:
        mpos = status.mpos
        wpos = (mpos[0] - wco[0], mpos[1] - wco[1], mpos[2] - wco[2])
    elif status.wpos is not None:
        wpos = status.wpos
        mpos = (wpos[0] + wco[0], wpos[1] + wco[1], wpos[2] + wco[2])
    else:
        mpos = wpos = (0.0, 0.0, 0.0)

    return mpos, wpos, wco
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest server/tests/test_grbl_status.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add server/grbl_serial/grbl.py server/tests/test_grbl_status.py
git commit -m "feat(grbl): parse status reports with WCO carry-over"
```

---

## Task 3: Replies, message tables, and command encoding

**Files:**
- Modify: `server/grbl_serial/grbl.py`
- Test: `server/tests/test_grbl_commands.py`

**Interfaces:**
- Consumes: `State`, `Status`, `parse_status` from Task 2
- Produces:
  - `class Realtime` with byte constants `STATUS FEED_HOLD RESUME SOFT_RESET JOG_CANCEL SAFETY_DOOR FEED_100 FEED_PLUS_10 FEED_MINUS_10 RAPID_100 RAPID_50 RAPID_25`
  - `@dataclass(frozen=True) Reply(kind: str, code: int | None, text: str)` where `kind` is one of `"ok" | "error" | "alarm" | "message" | "banner" | "settings" | "unknown"`
  - `parse_reply(line: str) -> Reply | None`
  - `ERROR_MESSAGES: dict[int, str]`, `ALARM_MESSAGES: dict[int, str]`
  - `encode_jog(axis: str, distance: float, feed: float) -> str`
  - `encode_zero(axes: str) -> str`
  - `fmt(value: float) -> str`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_grbl_commands.py`:

```python
from __future__ import annotations

from server.grbl_serial.grbl import (
    ALARM_MESSAGES,
    ERROR_MESSAGES,
    Realtime,
    encode_jog,
    encode_zero,
    fmt,
    parse_reply,
)


def test_realtime_bytes_are_single_bytes():
    for name in (
        "STATUS", "FEED_HOLD", "RESUME", "SOFT_RESET", "JOG_CANCEL",
        "SAFETY_DOOR", "FEED_100", "RAPID_100",
    ):
        value = getattr(Realtime, name)
        assert isinstance(value, bytes)
        assert len(value) == 1


def test_realtime_byte_values_match_the_protocol():
    assert Realtime.STATUS == b"?"
    assert Realtime.FEED_HOLD == b"!"
    assert Realtime.RESUME == b"~"
    assert Realtime.SOFT_RESET == b"\x18"
    assert Realtime.JOG_CANCEL == b"\x85"


def test_parse_ok():
    r = parse_reply("ok")
    assert r is not None and r.kind == "ok" and r.code is None


def test_parse_error_carries_human_text():
    r = parse_reply("error:15")
    assert r is not None
    assert r.kind == "error"
    assert r.code == 15
    assert "Travel exceeded" in r.text or "travel" in r.text.lower()


def test_parse_unknown_error_code_still_returns_error():
    r = parse_reply("error:999")
    assert r is not None
    assert r.kind == "error"
    assert r.code == 999
    assert "999" in r.text


def test_parse_alarm_carries_human_text():
    r = parse_reply("ALARM:2")
    assert r is not None
    assert r.kind == "alarm"
    assert r.code == 2
    assert r.text


def test_parse_message():
    r = parse_reply("[MSG:Reset to continue]")
    assert r is not None
    assert r.kind == "message"
    assert r.text == "Reset to continue"


def test_parse_banner():
    r = parse_reply("Grbl 1.1h ['$' for help]")
    assert r is not None
    assert r.kind == "banner"
    assert "1.1h" in r.text


def test_parse_setting_line():
    r = parse_reply("$100=80.000")
    assert r is not None
    assert r.kind == "settings"
    assert r.text == "$100=80.000"


def test_status_reports_are_not_replies():
    assert parse_reply("<Idle|MPos:0.000,0.000,0.000|FS:0,0>") is None


def test_blank_lines_are_not_replies():
    assert parse_reply("") is None
    assert parse_reply("   ") is None


def test_error_table_covers_the_common_codes():
    for code in (1, 2, 3, 9, 15, 20, 24, 25):
        assert code in ERROR_MESSAGES
        assert ERROR_MESSAGES[code]


def test_alarm_table_covers_the_common_codes():
    for code in (1, 2, 3, 9):
        assert code in ALARM_MESSAGES
        assert ALARM_MESSAGES[code]


def test_fmt_trims_trailing_zeros():
    assert fmt(10.0) == "10"
    assert fmt(0.1) == "0.1"
    assert fmt(-1.500) == "-1.5"
    assert fmt(0.0) == "0"
    assert fmt(124.5) == "124.5"


def test_encode_jog_is_relative_metric_and_carries_feed():
    assert encode_jog("X", 10.0, 1000.0) == "$J=G91 G21 X10 F1000"
    assert encode_jog("Y", -0.1, 500.0) == "$J=G91 G21 Y-0.1 F500"
    assert encode_jog("Z", 1.0, 200.0) == "$J=G91 G21 Z1 F200"


def test_encode_zero_sets_work_offset_for_named_axes():
    assert encode_zero("XY") == "G10 L20 P1 X0 Y0"
    assert encode_zero("Z") == "G10 L20 P1 Z0"
    assert encode_zero("XYZ") == "G10 L20 P1 X0 Y0 Z0"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest server/tests/test_grbl_commands.py -v`
Expected: FAIL — `ImportError: cannot import name 'Realtime'`

- [ ] **Step 3: Append the implementation to `grbl.py`**

Add to the end of `server/grbl_serial/grbl.py`:

```python
# --- realtime command bytes -------------------------------------------------

class Realtime:
    """Single-byte realtime commands.

    These bypass GRBL's line parser and planner queue entirely. They produce
    no `ok`, and they must NEVER be counted against the RX buffer. Sending one
    through the line path is what makes senders hang on emergency stop, which
    is why this is a separate namespace from the line commands below.
    """
    STATUS = b"?"
    FEED_HOLD = b"!"
    RESUME = b"~"
    SOFT_RESET = b"\x18"
    SAFETY_DOOR = b"\x84"
    JOG_CANCEL = b"\x85"
    FEED_100 = b"\x90"
    FEED_PLUS_10 = b"\x91"
    FEED_MINUS_10 = b"\x92"
    RAPID_100 = b"\x95"
    RAPID_50 = b"\x96"
    RAPID_25 = b"\x97"


# --- reply parsing ----------------------------------------------------------

ERROR_MESSAGES: dict[int, str] = {
    1: "Expected a G-code command letter",
    2: "Bad number format in G-code value",
    3: "Unsupported '$' system command",
    4: "Negative value where a positive one is required",
    5: "Homing is disabled in settings ($22)",
    6: "Step pulse time is below the minimum",
    7: "EEPROM read failed; defaults restored",
    8: "'$' command needs the machine to be idle",
    9: "G-code locked out while in alarm or jog state",
    10: "Soft limits need homing enabled",
    11: "Line was longer than the input buffer",
    12: "Step rate exceeds the maximum",
    13: "A safety door or check input is active",
    14: "Build info or startup line exceeds the line limit",
    15: "Travel exceeded — jog target is outside the machine",
    16: "Invalid jog command",
    17: "Laser mode needs PWM output enabled",
    20: "Unsupported or invalid G-code command",
    21: "More than one G-code command from the same modal group",
    22: "Feed rate has not been set",
    23: "A G-code command needed an integer value",
    24: "Two G-code commands wanted the same axis word",
    25: "A G-code word was repeated on the line",
    26: "A G-code command is missing a required axis word",
    27: "Line number is out of range",
    28: "A G-code command is missing a required value word",
    29: "Only work coordinate systems P1-P6 are supported",
    30: "G53 needs G0 or G1 active",
    31: "Axis words were given but this command takes none",
    32: "G2/G3 arcs need at least one in-plane axis word",
    33: "Invalid motion target",
    34: "Arc radius is geometrically impossible",
    35: "G2/G3 offset mode needs an in-plane offset word",
    36: "Unused axis words remain in the block",
    37: "Tool length offset applies only to the configured axis",
    38: "Tool number is greater than the maximum",
}

ALARM_MESSAGES: dict[int, str] = {
    1: "Hard limit triggered — machine position is likely lost",
    2: "Soft limit — the commanded move exceeds the machine travel",
    3: "Reset while in motion — position is lost",
    4: "Probe failed: the probe was already triggered",
    5: "Probe failed: no contact within the travel",
    6: "Homing failed: reset during the cycle",
    7: "Homing failed: safety door opened",
    8: "Homing failed: the limit switch did not clear",
    9: "Homing failed: a limit switch was not found within the travel",
    10: "Homing failed: a second dual-axis switch was not found",
}


@dataclass(frozen=True)
class Reply:
    """A non-status line received from the controller."""
    kind: str  # "ok" | "error" | "alarm" | "message" | "banner" | "settings" | "unknown"
    code: int | None
    text: str


def _code_of(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def parse_reply(line: str) -> Reply | None:
    """Parse a non-status line. Returns None for blanks and status reports."""
    line = line.strip()
    if not line:
        return None
    if line.startswith("<") and line.endswith(">"):
        return None  # a status report; parse_status handles those

    low = line.lower()

    if low == "ok":
        return Reply("ok", None, "ok")

    if low.startswith("error:"):
        code = _code_of(line.split(":", 1)[1].strip())
        if code is None:
            return Reply("error", None, line)
        return Reply("error", code, ERROR_MESSAGES.get(code, f"Unknown error {code}"))

    if low.startswith("alarm:"):
        code = _code_of(line.split(":", 1)[1].strip())
        if code is None:
            return Reply("alarm", None, line)
        return Reply("alarm", code, ALARM_MESSAGES.get(code, f"Unknown alarm {code}"))

    if line.startswith("[") and line.endswith("]"):
        body = line[1:-1]
        _, _, text = body.partition(":")
        return Reply("message", None, text or body)

    if low.startswith("grbl ") or low.startswith("fluidnc"):
        return Reply("banner", None, line)

    if line.startswith("$"):
        return Reply("settings", None, line)

    return Reply("unknown", None, line)


# --- line command encoding --------------------------------------------------

def fmt(value: float) -> str:
    """Format a millimetre value the way G-code wants it: no trailing zeros."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def encode_jog(axis: str, distance: float, feed: float) -> str:
    """Build a `$J=` jog.

    Jogs are relative (G91) and metric (G21), and crucially do NOT alter the
    parser's modal state — so jogging mid-session cannot change how a
    subsequent job is interpreted. A jog in flight is cancelled with the
    realtime byte Realtime.JOG_CANCEL, not by resetting.
    """
    return f"$J=G91 G21 {axis.upper()}{fmt(distance)} F{fmt(feed)}"


def encode_zero(axes: str) -> str:
    """Set the work offset so the named axes read zero at the current position."""
    words = " ".join(f"{a}0" for a in axes.upper())
    return f"G10 L20 P1 {words}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest server/tests/test_grbl_commands.py -v`
Expected: 16 passed

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest server/tests/ -v`
Expected: 26 passed

- [ ] **Step 6: Commit**

```bash
git add server/grbl_serial/grbl.py server/tests/test_grbl_commands.py
git commit -m "feat(grbl): replies, error/alarm tables, jog and zero encoding"
```

---

## Task 4: The GRBL simulator

**Files:**
- Create: `server/sim/grbl_sim.py`
- Test: `server/tests/test_grbl_sim.py`

**Interfaces:**
- Consumes: `parse_status`, `State` from Task 2
- Produces:
  - `class GrblSim` with methods `write(data: bytes) -> None`, `read_available() -> bytes`, `tick(dt: float) -> None`, `close() -> None`
  - Constructor: `GrblSim(rx_buffer: int = 128, planner_blocks: int = 15, travel: tuple[float,float,float] = (300.0, 200.0, 5.0))`
  - Attributes for assertions: `.pos: list[float]`, `.state: str`, `.peak_rx_used: int`
  - Fault injection: `.fail_after_lines: int | None`, `.stop_answering_status: bool`, `.error_on_line: int | None`

This class is also the `Transport` that Task 5's streamer accepts, so `write`/`read_available`/`close` must match that protocol exactly.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_grbl_sim.py`:

```python
from __future__ import annotations

from server.grbl_serial.grbl import State, parse_status
from server.sim.grbl_sim import GrblSim


def drain(sim: GrblSim) -> list[str]:
    return [ln for ln in sim.read_available().decode().splitlines() if ln]


def test_emits_banner_on_wake():
    sim = GrblSim()
    sim.write(b"\r\n")
    lines = drain(sim)
    assert any(ln.startswith("Grbl 1.1") for ln in lines)


def test_answers_status_query_with_a_report():
    sim = GrblSim()
    sim.write(b"?")
    lines = drain(sim)
    status = parse_status(lines[-1])
    assert status is not None
    assert status.state is State.IDLE


def test_answers_a_motion_line_with_ok():
    sim = GrblSim()
    sim.write(b"G0 X10 Y10 F1000\n")
    assert "ok" in drain(sim)


def test_rejects_unknown_command_with_a_real_error():
    sim = GrblSim()
    sim.write(b"$nonsense\n")
    assert any(ln.startswith("error:") for ln in drain(sim))


def test_dollar_dollar_dumps_settings():
    sim = GrblSim()
    sim.write(b"$$\n")
    lines = drain(sim)
    assert any(ln.startswith("$100=") for ln in lines)
    assert lines[-1] == "ok"


def test_position_integrates_over_time():
    sim = GrblSim()
    sim.write(b"G0 X10 Y0 F600\n")   # 600 mm/min = 10 mm/s
    drain(sim)
    sim.tick(0.5)
    assert 4.0 < sim.pos[0] < 6.0     # about halfway
    assert sim.state == "Run"
    sim.tick(1.0)
    assert abs(sim.pos[0] - 10.0) < 1e-6
    assert sim.state == "Idle"


def test_soft_reset_returns_to_alarm_with_a_banner():
    sim = GrblSim()
    sim.write(b"\x18")
    lines = drain(sim)
    assert any(ln.startswith("Grbl 1.1") for ln in lines)
    assert sim.state == "Alarm"


def test_feed_hold_and_resume():
    sim = GrblSim()
    sim.write(b"G0 X100 F600\n")
    drain(sim)
    sim.tick(0.2)
    sim.write(b"!")
    assert sim.state == "Hold"
    frozen = sim.pos[0]
    sim.tick(1.0)
    assert sim.pos[0] == frozen       # no motion while held
    sim.write(b"~")
    assert sim.state == "Run"


def test_unlock_clears_alarm():
    sim = GrblSim()
    sim.write(b"\x18")
    drain(sim)
    assert sim.state == "Alarm"
    sim.write(b"$X\n")
    assert "ok" in drain(sim)
    assert sim.state == "Idle"


def test_motion_is_refused_while_in_alarm():
    sim = GrblSim()
    sim.write(b"\x18")
    drain(sim)
    sim.write(b"G0 X10\n")
    assert any(ln == "error:9" for ln in drain(sim))


def test_soft_limit_violation_raises_alarm_2():
    sim = GrblSim(travel=(300.0, 200.0, 5.0))
    sim.write(b"G0 X400\n")
    lines = drain(sim)
    assert any(ln.startswith("ALARM:2") for ln in lines)
    assert sim.state == "Alarm"


def test_planner_backpressure_withholds_ok_when_full():
    """With the planner full, `ok` is withheld — which is what makes the
    host's character-counting accounting observable."""
    sim = GrblSim(planner_blocks=2)
    for _ in range(5):
        sim.write(b"G1 X1 F100\n")
    oks = [ln for ln in drain(sim) if ln == "ok"]
    assert len(oks) < 5


def test_rx_buffer_overflow_is_an_assertion_failure():
    """The sim polices the host: exceeding the RX buffer is a host bug."""
    sim = GrblSim(rx_buffer=32, planner_blocks=1)
    try:
        for _ in range(50):
            sim.write(b"G1 X1 Y1 Z1 F1000\n")
    except AssertionError as exc:
        assert "RX buffer" in str(exc)
    else:
        raise AssertionError("sim should have caught the overflow")


def test_status_can_be_made_to_stop_answering():
    sim = GrblSim()
    sim.stop_answering_status = True
    sim.write(b"?")
    assert drain(sim) == []


def test_error_can_be_injected_on_a_chosen_line():
    sim = GrblSim()
    sim.error_on_line = 2
    sim.write(b"G0 X1\n")
    assert "ok" in drain(sim)
    sim.write(b"G0 X2\n")
    assert any(ln.startswith("error:") for ln in drain(sim))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest server/tests/test_grbl_sim.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.sim.grbl_sim'`

- [ ] **Step 3: Write the implementation**

Create `server/sim/grbl_sim.py`:

```python
"""A model of a GRBL 1.1 controller, used as a transport in tests and demos.

This is deliberately not a stub. It models the RX buffer and the planner
queue, because the only way to prove the host's character-counting flow
control is correct — rather than accidentally working — is to run it against
something that withholds `ok` under backpressure and complains when the host
oversends.
"""
from __future__ import annotations

import math

BANNER = "Grbl 1.1h ['$' for help]"

DEFAULT_SETTINGS: dict[int, str] = {
    10: "1",        # status report mask: machine position
    20: "0",        # soft limits off
    22: "0",        # homing off
    100: "80.000",  # X steps/mm
    101: "80.000",  # Y steps/mm
    102: "100.000", # Z steps/mm
    110: "5000.000",# X max rate
    111: "5000.000",# Y max rate
    112: "1000.000",# Z max rate
    120: "300.000", # X accel
    121: "300.000", # Y accel
    122: "100.000", # Z accel
    130: "300.000", # X max travel
    131: "200.000", # Y max travel
    132: "5.000",   # Z max travel
}

AXES = ("X", "Y", "Z")


class _Block:
    """One queued motion block."""

    def __init__(self, target: list[float], feed: float, rx_cost: int) -> None:
        self.target = target
        self.feed = feed
        self.rx_cost = rx_cost


class GrblSim:
    def __init__(
        self,
        rx_buffer: int = 128,
        planner_blocks: int = 15,
        travel: tuple[float, float, float] = (300.0, 200.0, 5.0),
    ) -> None:
        self.rx_buffer = rx_buffer
        self.planner_blocks = planner_blocks
        self.travel = list(travel)

        self.pos: list[float] = [0.0, 0.0, 0.0]
        self.wco: list[float] = [0.0, 0.0, 0.0]
        self.state = "Idle"
        self.feed = 0.0

        self._out: list[str] = []
        self._partial = ""
        self._queue: list[_Block] = []
        self._rx_used = 0
        self.peak_rx_used = 0
        self._lines_seen = 0
        self._closed = False
        # A real board banners the moment it is reset, unprompted. Emitting it
        # here rather than on a newline means the host does not have to nudge.
        self._emit(BANNER)

        # fault injection
        self.fail_after_lines: int | None = None
        self.stop_answering_status: bool = False
        self.error_on_line: int | None = None

    # --- transport surface -------------------------------------------------

    def write(self, data: bytes) -> None:
        if self._closed:
            raise OSError("port closed")
        for byte in data:
            ch = bytes([byte])
            if ch in (b"?", b"!", b"~", b"\x18", b"\x85", b"\x84"):
                self._realtime(ch)
                continue
            text = ch.decode("latin-1")
            if text in "\r\n":
                if self._partial.strip():
                    self._line(self._partial.strip())
                self._partial = ""
                if not data.strip():
                    self._emit(BANNER)
            else:
                self._partial += text

    def read_available(self) -> bytes:
        out = "".join(line + "\r\n" for line in self._out)
        self._out.clear()
        return out.encode()

    def close(self) -> None:
        self._closed = True

    # --- internals ---------------------------------------------------------

    def _emit(self, line: str) -> None:
        self._out.append(line)

    def _realtime(self, ch: bytes) -> None:
        if ch == b"?":
            if not self.stop_answering_status:
                self._emit(self._status_report())
        elif ch == b"!":
            if self.state == "Run":
                self.state = "Hold"
        elif ch == b"~":
            if self.state == "Hold":
                self.state = "Run" if self._queue else "Idle"
        elif ch == b"\x85":
            if self.state == "Jog":
                self._queue.clear()
                self._rx_used = 0
                self.state = "Idle"
        elif ch == b"\x18":
            self._queue.clear()
            self._rx_used = 0
            self.state = "Alarm"
            self._emit("")
            self._emit(BANNER)

    def _status_report(self) -> str:
        mpos = ",".join(f"{v:.3f}" for v in self.pos)
        return (
            f"<{self.state}|MPos:{mpos}|FS:{self.feed:.0f},0"
            f"|WCO:{self.wco[0]:.3f},{self.wco[1]:.3f},{self.wco[2]:.3f}>"
        )

    def _line(self, line: str) -> None:
        self._lines_seen += 1
        cost = len(line) + 1

        self._rx_used += cost
        self.peak_rx_used = max(self.peak_rx_used, self._rx_used)
        assert self._rx_used <= self.rx_buffer, (
            f"host overflowed the RX buffer: {self._rx_used} > {self.rx_buffer} bytes "
            f"in flight after {line!r}"
        )

        if self.fail_after_lines is not None and self._lines_seen > self.fail_after_lines:
            self._closed = True
            raise OSError("simulated disconnect")

        if self.error_on_line is not None and self._lines_seen == self.error_on_line:
            self._reply("error:20", cost)
            return

        upper = line.upper()

        if upper == "$X":
            self.state = "Idle"
            self._reply("ok", cost)
            return

        if upper == "$$":
            for key in sorted(DEFAULT_SETTINGS):
                self._emit(f"${key}={DEFAULT_SETTINGS[key]}")
            self._reply("ok", cost)
            return

        if upper == "$I":
            self._emit("[VER:1.1h.20190825:]")
            self._emit("[OPT:V,15,128]")
            self._reply("ok", cost)
            return

        if upper == "$H":
            self.pos = [0.0, 0.0, 0.0]
            self.state = "Idle"
            self._reply("ok", cost)
            return

        if self.state == "Alarm":
            self._reply("error:9", cost)
            return

        if upper.startswith("$J="):
            self._motion(upper[3:], cost, jog=True)
            return

        if upper.startswith("G10 L20"):
            for i, axis in enumerate(AXES):
                token = self._word(upper, axis)
                if token is not None:
                    self.wco[i] = self.pos[i] - token
            self._reply("ok", cost)
            return

        if upper.startswith("G0") or upper.startswith("G1") or upper.startswith("G9"):
            self._motion(upper, cost, jog=False)
            return

        if upper.startswith("$"):
            self._reply("error:3", cost)
            return

        self._reply("ok", cost)

    @staticmethod
    def _word(line: str, letter: str) -> float | None:
        idx = line.find(letter)
        if idx < 0:
            return None
        num = ""
        for ch in line[idx + 1:]:
            if ch.isdigit() or ch in "+-.":
                num += ch
            else:
                break
        try:
            return float(num)
        except ValueError:
            return None

    def _motion(self, body: str, cost: int, jog: bool) -> None:
        relative = "G91" in body
        target = list(self.pos)
        moved = False
        for i, axis in enumerate(AXES):
            value = self._word(body, axis)
            if value is None:
                continue
            moved = True
            target[i] = self.pos[i] + value if relative else value

        feed = self._word(body, "F")
        if feed is not None:
            self.feed = feed

        if not moved:
            self._reply("ok", cost)
            return

        for i, axis_travel in enumerate(self.travel):
            if target[i] < -1e-6 or target[i] > axis_travel + 1e-6:
                self._queue.clear()
                self._rx_used = 0
                self.state = "Alarm"
                self._emit("ALARM:2")
                return

        if len(self._queue) >= self.planner_blocks:
            # Planner full: the line stays in the RX buffer, un-acknowledged.
            # This is the backpressure the host's flow control must respect.
            self._queue.append(_Block(target, self.feed or 1000.0, cost))
            self.state = "Jog" if jog else "Run"
            return

        self._queue.append(_Block(target, self.feed or 1000.0, cost))
        self.state = "Jog" if jog else "Run"
        self._reply("ok", cost)

    def _reply(self, text: str, cost: int) -> None:
        self._rx_used = max(0, self._rx_used - cost)
        self._emit(text)

    def tick(self, dt: float) -> None:
        """Advance simulated motion by dt seconds."""
        if self.state in ("Hold", "Alarm"):
            return

        remaining = dt
        while remaining > 1e-9 and self._queue:
            block = self._queue[0]
            delta = [block.target[i] - self.pos[i] for i in range(3)]
            distance = math.sqrt(sum(d * d for d in delta))
            if distance < 1e-9:
                self._finish_block()
                continue

            speed = block.feed / 60.0  # mm/min -> mm/s
            step = speed * remaining
            if step >= distance:
                self.pos = list(block.target)
                remaining -= distance / speed
                self._finish_block()
            else:
                frac = step / distance
                self.pos = [self.pos[i] + delta[i] * frac for i in range(3)]
                remaining = 0.0

        if not self._queue and self.state in ("Run", "Jog"):
            self.state = "Idle"
            self.feed = 0.0

    def _finish_block(self) -> None:
        done = self._queue.pop(0)
        # A block that was held back by a full planner gets its `ok` now.
        if self._rx_used >= done.rx_cost and len(self._queue) >= self.planner_blocks - 1:
            self._reply("ok", done.rx_cost)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest server/tests/test_grbl_sim.py -v`
Expected: 15 passed. If `test_planner_backpressure_withholds_ok_when_full` fails, the `_motion` early return when the planner is full is not being hit — check `planner_blocks` is being respected.

- [ ] **Step 5: Commit**

```bash
git add server/sim/grbl_sim.py server/tests/test_grbl_sim.py
git commit -m "feat(sim): GRBL controller model with RX buffer and planner backpressure"
```

---

## Task 5: Streamer — transport, reader loop, and events

**Files:**
- Create: `server/grbl_serial/streamer.py`
- Test: `server/tests/test_streamer_events.py`

**Interfaces:**
- Consumes: `parse_status`, `parse_reply`, `Realtime`, `Status`, `Reply` from Tasks 2–3; `GrblSim` from Task 4 (tests only)
- Produces:
  - `class Transport(Protocol)` with `write(data: bytes) -> None`, `read_available() -> bytes`, `close() -> None`
  - Event dataclasses: `StatusEvent(status: Status)`, `ReplyEvent(reply: Reply)`, `SentEvent(line: str)`, `DisconnectedEvent(reason: str)`
  - `class Streamer` with `__init__(transport: Transport, rx_buffer: int = 128, on_event: Callable[[object], None] | None = None)`, `pump() -> None`, `send_line(line: str) -> None`, `send_realtime(byte: bytes) -> None`, `pending_bytes: int`

`pump()` is the single-step form of the loop. Task 6 adds the thread and the poll timer on top of it; keeping it synchronous here is what makes these tests deterministic.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_streamer_events.py`:

```python
from __future__ import annotations

from server.grbl_serial.grbl import Realtime, State
from server.grbl_serial.streamer import (
    DisconnectedEvent,
    ReplyEvent,
    SentEvent,
    StatusEvent,
    Streamer,
)
from server.sim.grbl_sim import GrblSim


def collect() -> tuple[list, callable]:
    events: list = []
    return events, events.append


def test_banner_arrives_as_a_reply_event():
    sim = GrblSim()
    events, sink = collect()
    s = Streamer(sim, on_event=sink)
    sim.write(b"\r\n")
    s.pump()
    banners = [e for e in events if isinstance(e, ReplyEvent) and e.reply.kind == "banner"]
    assert banners


def test_status_query_produces_a_status_event():
    sim = GrblSim()
    events, sink = collect()
    s = Streamer(sim, on_event=sink)
    s.send_realtime(Realtime.STATUS)
    s.pump()
    statuses = [e for e in events if isinstance(e, StatusEvent)]
    assert statuses
    assert statuses[-1].status.state is State.IDLE


def test_sent_lines_are_reported_before_their_reply():
    sim = GrblSim()
    events, sink = collect()
    s = Streamer(sim, on_event=sink)
    s.send_line("G0 X1 Y1 F1000")
    s.pump()
    kinds = [type(e).__name__ for e in events]
    assert kinds.index("SentEvent") < kinds.index("ReplyEvent")


def test_realtime_bytes_are_not_counted_against_the_buffer():
    sim = GrblSim()
    s = Streamer(sim)
    before = s.pending_bytes
    s.send_realtime(Realtime.STATUS)
    s.send_realtime(Realtime.FEED_HOLD)
    assert s.pending_bytes == before


def test_partial_lines_are_buffered_until_complete():
    """Serial reads split lines anywhere; the assembler must not lose them."""
    class Chunked:
        def __init__(self) -> None:
            self.chunks = [b"<Idle|MPos:1.000,", b"2.000,3.000|FS:0,0>\r\n"]
        def write(self, data: bytes) -> None: ...
        def read_available(self) -> bytes:
            return self.chunks.pop(0) if self.chunks else b""
        def close(self) -> None: ...

    events, sink = collect()
    s = Streamer(Chunked(), on_event=sink)
    s.pump()
    assert not [e for e in events if isinstance(e, StatusEvent)]
    s.pump()
    statuses = [e for e in events if isinstance(e, StatusEvent)]
    assert statuses[-1].status.mpos == (1.0, 2.0, 3.0)


def test_write_failure_produces_a_disconnected_event():
    class Dead:
        def write(self, data: bytes) -> None:
            raise OSError("device disappeared")
        def read_available(self) -> bytes:
            return b""
        def close(self) -> None: ...

    events, sink = collect()
    s = Streamer(Dead(), on_event=sink)
    s.send_line("G0 X1")
    s.pump()
    dropped = [e for e in events if isinstance(e, DisconnectedEvent)]
    assert dropped
    assert "device disappeared" in dropped[0].reason


def test_error_reply_is_surfaced_with_its_human_text():
    sim = GrblSim()
    events, sink = collect()
    s = Streamer(sim, on_event=sink)
    s.send_line("$nonsense")
    s.pump()
    errors = [e for e in events if isinstance(e, ReplyEvent) and e.reply.kind == "error"]
    assert errors
    assert errors[0].reply.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest server/tests/test_streamer_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.grbl_serial.streamer'`

- [ ] **Step 3: Write the implementation**

Create `server/grbl_serial/streamer.py`:

```python
"""Owns the serial port: reads replies, sends lines under flow control.

Split from grbl.py deliberately — everything here touches a transport, and
everything in grbl.py does not. The transport is a Protocol rather than a
pyserial object so the simulator can stand in for hardware with no mocking.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable, Protocol

from .grbl import Reply, Status, parse_reply, parse_status


class Transport(Protocol):
    def write(self, data: bytes) -> None: ...
    def read_available(self) -> bytes: ...
    def close(self) -> None: ...


@dataclass
class StatusEvent:
    status: Status


@dataclass
class ReplyEvent:
    reply: Reply


@dataclass
class SentEvent:
    line: str


@dataclass
class DisconnectedEvent:
    reason: str


class Streamer:
    def __init__(
        self,
        transport: Transport,
        rx_buffer: int = 128,
        on_event: Callable[[object], None] | None = None,
    ) -> None:
        self.transport = transport
        self.rx_buffer = rx_buffer
        self._on_event = on_event or (lambda _e: None)

        self._partial = ""
        self._pending: deque[int] = deque()   # byte cost of each unacknowledged line
        self._outbox: deque[str] = deque()    # lines waiting for buffer space
        self.connected = True

    # --- outbound ----------------------------------------------------------

    @property
    def pending_bytes(self) -> int:
        return sum(self._pending)

    def send_realtime(self, byte: bytes) -> None:
        """Send a single realtime byte.

        Deliberately a different method from send_line with a different
        argument type: realtime bytes bypass the planner queue, get no `ok`,
        and must never touch the pending-byte accounting.
        """
        if not self.connected:
            return
        try:
            self.transport.write(byte)
        except OSError as exc:
            self._drop(str(exc))

    def send_line(self, line: str) -> None:
        """Queue a line for transmission under flow control."""
        self._outbox.append(line.strip())
        self._flush_outbox()

    def _flush_outbox(self) -> None:
        while self._outbox and self.connected:
            line = self._outbox[0]
            cost = len(line) + 1
            if self.pending_bytes + cost >= self.rx_buffer:
                return  # no room; wait for an `ok` to free some
            self._outbox.popleft()
            try:
                self.transport.write((line + "\n").encode())
            except OSError as exc:
                self._drop(str(exc))
                return
            self._pending.append(cost)
            self._on_event(SentEvent(line))

    # --- inbound -----------------------------------------------------------

    def pump(self) -> None:
        """Read whatever is available and dispatch it. One non-blocking step."""
        if not self.connected:
            return
        try:
            chunk = self.transport.read_available()
        except OSError as exc:
            self._drop(str(exc))
            return

        if chunk:
            self._partial += chunk.decode(errors="replace")
            while "\n" in self._partial:
                raw, _, self._partial = self._partial.partition("\n")
                self._dispatch(raw.strip())

        self._flush_outbox()

    def _dispatch(self, line: str) -> None:
        if not line:
            return

        status = parse_status(line)
        if status is not None:
            self._on_event(StatusEvent(status))
            return

        reply = parse_reply(line)
        if reply is None:
            return

        # `ok` and `error` both close out exactly one queued line.
        if reply.kind in ("ok", "error") and self._pending:
            self._pending.popleft()

        self._on_event(ReplyEvent(reply))

    def _drop(self, reason: str) -> None:
        if not self.connected:
            return
        self.connected = False
        self._pending.clear()
        self._outbox.clear()
        self._on_event(DisconnectedEvent(reason))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest server/tests/test_streamer_events.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add server/grbl_serial/streamer.py server/tests/test_streamer_events.py
git commit -m "feat(streamer): transport protocol, line assembler, event dispatch"
```

---

## Task 6: Character-counting flow control and the polling thread

**Files:**
- Modify: `server/grbl_serial/streamer.py`
- Test: `server/tests/test_streamer_flow.py`

**Interfaces:**
- Consumes: everything from Task 5
- Produces:
  - `Streamer.start(poll_hz: float = 5.0) -> None`, `Streamer.stop() -> None`
  - `Streamer.missed_polls: int`
  - `class SimTransport` in tests, wrapping `GrblSim` with a clock

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_streamer_flow.py`:

```python
from __future__ import annotations

import time

from server.grbl_serial.streamer import DisconnectedEvent, Streamer
from server.sim.grbl_sim import GrblSim


def run_until_idle(streamer: Streamer, sim: GrblSim, max_steps: int = 20000) -> int:
    """Drive sim and streamer in lockstep. Returns the number of steps taken."""
    for step in range(max_steps):
        streamer.pump()
        sim.tick(0.002)
        if not streamer._outbox and streamer.pending_bytes == 0 and sim.state == "Idle":
            return step
    raise AssertionError("never went idle")


def test_never_exceeds_the_rx_buffer():
    """The simulator asserts on overflow, so simply completing proves this."""
    sim = GrblSim(rx_buffer=128, planner_blocks=15)
    s = Streamer(sim, rx_buffer=128)
    for i in range(200):
        s.send_line(f"G1 X{i % 50}.000 Y{i % 30}.000 F1000")
    run_until_idle(s, sim)
    assert sim.peak_rx_used <= 128


def test_keeps_more_than_one_line_in_flight():
    """Character counting exists to keep the planner fed. If only one line is
    ever outstanding we have accidentally written send-response."""
    sim = GrblSim(rx_buffer=128, planner_blocks=15)
    s = Streamer(sim, rx_buffer=128)
    for i in range(50):
        s.send_line(f"G1 X{i}.000 F1000")
    s.pump()
    assert len(s._pending) > 1


def test_every_line_is_delivered_in_order():
    sim = GrblSim(rx_buffer=128, planner_blocks=15)
    sent: list[str] = []
    original = sim._line
    sim._line = lambda ln: (sent.append(ln), original(ln))[1]  # type: ignore[method-assign]

    s = Streamer(sim, rx_buffer=128)
    expected = [f"G1 X{i}.000 F1000" for i in range(100)]
    for line in expected:
        s.send_line(line)
    run_until_idle(s, sim)
    assert sent == expected


def test_a_smaller_buffer_still_completes():
    sim = GrblSim(rx_buffer=48, planner_blocks=4)
    s = Streamer(sim, rx_buffer=48)
    for i in range(60):
        s.send_line(f"G1 X{i % 20}.000 F1000")
    run_until_idle(s, sim)
    assert sim.peak_rx_used <= 48


def test_polling_thread_produces_status_events():
    sim = GrblSim()
    events: list = []
    s = Streamer(sim, on_event=events.append)
    s.start(poll_hz=20.0)
    try:
        deadline = time.time() + 1.0
        while time.time() < deadline:
            sim.tick(0.01)
            time.sleep(0.01)
    finally:
        s.stop()
    from server.grbl_serial.streamer import StatusEvent
    assert len([e for e in events if isinstance(e, StatusEvent)]) >= 5


def test_unanswered_polls_raise_a_disconnect():
    sim = GrblSim()
    sim.stop_answering_status = True
    events: list = []
    s = Streamer(sim, on_event=events.append)
    s.start(poll_hz=20.0)
    try:
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if any(isinstance(e, DisconnectedEvent) for e in events):
                break
            time.sleep(0.02)
    finally:
        s.stop()
    assert any(isinstance(e, DisconnectedEvent) for e in events)


def test_stop_is_idempotent():
    sim = GrblSim()
    s = Streamer(sim)
    s.start()
    s.stop()
    s.stop()  # must not raise
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest server/tests/test_streamer_flow.py -v`
Expected: FAIL — `AttributeError: 'Streamer' object has no attribute 'start'`

- [ ] **Step 3: Add threading and polling to `streamer.py`**

Add these imports at the top of `server/grbl_serial/streamer.py`:

```python
import threading
import time
```

and `Realtime` to the existing grbl import:

```python
from .grbl import Realtime, Reply, Status, parse_reply, parse_status
```

Add to `Streamer.__init__`, after `self.connected = True`:

```python
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.RLock()
        self._last_poll = 0.0
        self._awaiting_status_since: float | None = None
        self.missed_polls = 0
        self.poll_timeout = 0.5
        self.max_missed_polls = 3
```

Add these methods to `Streamer`:

```python
    # --- background loop ---------------------------------------------------

    def start(self, poll_hz: float = 5.0) -> None:
        """Run the pump on its own thread, polling `?` at poll_hz."""
        if self._thread is not None:
            return
        self._running = True
        interval = 1.0 / poll_hz

        def loop() -> None:
            while self._running and self.connected:
                with self._lock:
                    self.pump()
                    now = time.time()
                    if now - self._last_poll >= interval:
                        self._last_poll = now
                        if self._awaiting_status_since is None:
                            self._awaiting_status_since = now
                        self.send_realtime(Realtime.STATUS)
                    self._check_poll_timeout(now)
                time.sleep(0.005)

        self._thread = threading.Thread(target=loop, name="grbl-streamer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _check_poll_timeout(self, now: float) -> None:
        """Three unanswered `?` polls at poll_timeout each means the link is gone."""
        started = self._awaiting_status_since
        if started is None:
            return
        if now - started < self.poll_timeout:
            return
        self._awaiting_status_since = now
        self.missed_polls += 1
        if self.missed_polls >= self.max_missed_polls:
            self._drop(
                f"no response to {self.max_missed_polls} status polls "
                f"({self.max_missed_polls * self.poll_timeout:.1f}s)"
            )
```

In `_dispatch`, immediately after the `if status is not None:` branch begins, reset the poll watchdog. The branch becomes:

```python
        status = parse_status(line)
        if status is not None:
            self._awaiting_status_since = None
            self.missed_polls = 0
            self._on_event(StatusEvent(status))
            return
```

Finally, wrap the public mutators so the thread and the request handlers cannot interleave. Change the first line of `send_line` and `send_realtime` to acquire the lock:

```python
    def send_realtime(self, byte: bytes) -> None:
        with self._lock:
            if not self.connected:
                return
            try:
                self.transport.write(byte)
            except OSError as exc:
                self._drop(str(exc))

    def send_line(self, line: str) -> None:
        with self._lock:
            self._outbox.append(line.strip())
            self._flush_outbox()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest server/tests/test_streamer_flow.py -v`
Expected: 7 passed

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest server/tests/ -v`
Expected: 55 passed

- [ ] **Step 6: Commit**

```bash
git add server/grbl_serial/streamer.py server/tests/test_streamer_flow.py
git commit -m "feat(streamer): character-counting flow control and poll watchdog"
```

---

## Task 7: Serial port enumeration and identification

**Files:**
- Create: `server/grbl_serial/ports.py`
- Test: `server/tests/test_ports.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `@dataclass(frozen=True) PortInfo(device: str, description: str, vid: int | None, pid: int | None, likely_controller: bool, chip: str | None)`
  - `identify(vid: int | None, pid: int | None) -> tuple[bool, str | None]`
  - `list_ports() -> list[PortInfo]`
  - `autoselect(ports: list[PortInfo]) -> str | None`
  - `BAUD_RATES: list[int]`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_ports.py`:

```python
from __future__ import annotations

from server.grbl_serial.ports import BAUD_RATES, PortInfo, autoselect, identify


def make(device: str, likely: bool) -> PortInfo:
    return PortInfo(device, "test", None, None, likely, None)


def test_identifies_ch340():
    likely, chip = identify(0x1A86, 0x7523)
    assert likely is True
    assert chip == "CH340"


def test_identifies_cp2102():
    likely, chip = identify(0x10C4, 0xEA60)
    assert likely is True
    assert chip == "CP2102"


def test_identifies_official_arduino():
    likely, chip = identify(0x2341, 0x0043)
    assert likely is True
    assert chip == "Arduino"


def test_identifies_esp32_usb_bridge():
    likely, _chip = identify(0x303A, 0x1001)
    assert likely is True


def test_unknown_vid_is_not_flagged():
    likely, chip = identify(0x9999, 0x0001)
    assert likely is False
    assert chip is None


def test_missing_vid_is_not_flagged():
    likely, chip = identify(None, None)
    assert likely is False
    assert chip is None


def test_autoselect_picks_the_only_likely_controller():
    ports = [make("COM1", False), make("COM5", True), make("COM9", False)]
    assert autoselect(ports) == "COM5"


def test_autoselect_declines_when_ambiguous():
    ports = [make("COM5", True), make("COM6", True)]
    assert autoselect(ports) is None


def test_autoselect_declines_when_nothing_looks_right():
    assert autoselect([make("COM1", False)]) is None


def test_autoselect_handles_an_empty_list():
    assert autoselect([]) is None


def test_baud_rates_include_the_grbl_defaults():
    assert 115200 in BAUD_RATES
    assert 250000 in BAUD_RATES
    assert BAUD_RATES[0] == 115200  # the default goes first
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest server/tests/test_ports.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.grbl_serial.ports'`

- [ ] **Step 3: Write the implementation**

Create `server/grbl_serial/ports.py`:

```python
"""Enumerate serial ports and guess which one is the controller."""
from __future__ import annotations

from dataclasses import dataclass

# USB vendor IDs seen on GRBL-capable boards. Mapping VID to a chip name lets
# the UI say "COM5 - CH340" instead of leaving the user to guess.
KNOWN_VENDORS: dict[int, str] = {
    0x1A86: "CH340",     # WCH, on most clone Unos and Nanos
    0x10C4: "CP2102",    # Silicon Labs, common on ESP32 boards
    0x0403: "FTDI",      # FTDI, on older Arduinos
    0x2341: "Arduino",   # Arduino SA
    0x2A03: "Arduino",   # Arduino SRL
    0x1B4F: "SparkFun",
    0x303A: "ESP32-S",   # Espressif native USB
}

BAUD_RATES: list[int] = [115200, 250000, 57600, 38400, 19200, 9600]


@dataclass(frozen=True)
class PortInfo:
    device: str
    description: str
    vid: int | None
    pid: int | None
    likely_controller: bool
    chip: str | None


def identify(vid: int | None, pid: int | None) -> tuple[bool, str | None]:
    """Return (looks like a controller, chip name)."""
    if vid is None:
        return False, None
    chip = KNOWN_VENDORS.get(vid)
    return (chip is not None), chip


def list_ports() -> list[PortInfo]:
    """Enumerate the machine's serial ports."""
    from serial.tools import list_ports as pyserial_ports

    out: list[PortInfo] = []
    for p in pyserial_ports.comports():
        likely, chip = identify(p.vid, p.pid)
        out.append(
            PortInfo(
                device=p.device,
                description=p.description or p.device,
                vid=p.vid,
                pid=p.pid,
                likely_controller=likely,
                chip=chip,
            )
        )
    return sorted(out, key=lambda p: (not p.likely_controller, p.device))


def autoselect(ports: list[PortInfo]) -> str | None:
    """Pre-select a port only when exactly one candidate is present.

    Guessing between two plausible boards is worse than asking, so ambiguity
    deliberately returns None rather than picking the first.
    """
    likely = [p for p in ports if p.likely_controller]
    return likely[0].device if len(likely) == 1 else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest server/tests/test_ports.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add server/grbl_serial/ports.py server/tests/test_ports.py
git commit -m "feat(ports): enumerate and identify likely GRBL controllers"
```

---

## Task 8: Machine profile storage

**Files:**
- Create: `server/store/db.py`
- Test: `server/tests/test_store.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `@dataclass Profile` with fields `id: int, name: str, controller: str, baud: int, rx_buffer: int, pen_mode: str, travel_x: float, travel_y: float, travel_z: float, pen_up_z: float, pen_down_z: float, servo_up: int, servo_down: int, travel_feed: float, draw_feed: float, z_feed: float, jog_feed: float`
  - `init_db(path: str | None = None) -> sqlite3.Connection`
  - `get_active_profile(conn) -> Profile`
  - `update_profile(conn, profile_id: int, **fields) -> Profile`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_store.py`:

```python
from __future__ import annotations

import pytest

from server.store.db import Profile, get_active_profile, init_db, update_profile


@pytest.fixture()
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


def test_seeds_a_default_profile(conn):
    p = get_active_profile(conn)
    assert isinstance(p, Profile)
    assert p.name
    assert p.baud == 115200
    assert p.rx_buffer == 128


def test_default_profile_matches_the_bench_plotter(conn):
    p = get_active_profile(conn)
    assert p.travel_x == 300.0
    assert p.travel_y == 200.0
    assert p.travel_z == 5.0
    assert p.pen_up_z == 5.0
    assert p.pen_down_z == 0.0
    assert p.pen_mode == "z-axis"


def test_update_persists(conn):
    p = get_active_profile(conn)
    updated = update_profile(conn, p.id, travel_x=250.0, jog_feed=1500.0)
    assert updated.travel_x == 250.0
    assert updated.jog_feed == 1500.0
    assert get_active_profile(conn).travel_x == 250.0


def test_update_rejects_unknown_fields(conn):
    p = get_active_profile(conn)
    with pytest.raises(ValueError, match="unknown profile field"):
        update_profile(conn, p.id, nonsense=1)


def test_pen_mode_is_constrained(conn):
    p = get_active_profile(conn)
    update_profile(conn, p.id, pen_mode="servo-pwm")
    assert get_active_profile(conn).pen_mode == "servo-pwm"
    with pytest.raises(ValueError, match="pen_mode"):
        update_profile(conn, p.id, pen_mode="hydraulic")


def test_init_is_idempotent(conn):
    first = get_active_profile(conn)
    init_db_again = get_active_profile(conn)
    assert first.id == init_db_again.id
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest server/tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.store.db'`

- [ ] **Step 3: Write the implementation**

Create `server/store/db.py`:

```python
"""SQLite storage. One user, so no accounts table — just machine profiles.

Slice 1 needs only profiles; the projects and jobs tables arrive with their
own subsystems.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, fields

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "workbench.db")

PEN_MODES = ("z-axis", "servo-pwm")


@dataclass
class Profile:
    id: int
    name: str
    controller: str
    baud: int
    rx_buffer: int
    pen_mode: str
    travel_x: float
    travel_y: float
    travel_z: float
    pen_up_z: float
    pen_down_z: float
    servo_up: int
    servo_down: int
    travel_feed: float
    draw_feed: float
    z_feed: float
    jog_feed: float


_COLUMNS = [f.name for f in fields(Profile)]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    controller  TEXT    NOT NULL DEFAULT 'GRBL 1.1',
    baud        INTEGER NOT NULL DEFAULT 115200,
    rx_buffer   INTEGER NOT NULL DEFAULT 128,
    pen_mode    TEXT    NOT NULL DEFAULT 'z-axis',
    travel_x    REAL    NOT NULL DEFAULT 300.0,
    travel_y    REAL    NOT NULL DEFAULT 200.0,
    travel_z    REAL    NOT NULL DEFAULT 5.0,
    pen_up_z    REAL    NOT NULL DEFAULT 5.0,
    pen_down_z  REAL    NOT NULL DEFAULT 0.0,
    servo_up    INTEGER NOT NULL DEFAULT 90,
    servo_down  INTEGER NOT NULL DEFAULT 0,
    travel_feed REAL    NOT NULL DEFAULT 3000.0,
    draw_feed   REAL    NOT NULL DEFAULT 800.0,
    z_feed      REAL    NOT NULL DEFAULT 500.0,
    jog_feed    REAL    NOT NULL DEFAULT 1000.0,
    active      INTEGER NOT NULL DEFAULT 0
);
"""


def init_db(path: str | None = None) -> sqlite3.Connection:
    """Open (creating if needed) the database and seed the default profile."""
    conn = sqlite3.connect(path or DEFAULT_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)

    existing = conn.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()["n"]
    if existing == 0:
        # Defaults describe the bench plotter documented in pcb_reader/HARDWARE.md.
        conn.execute(
            "INSERT INTO profiles (name, active) VALUES (?, 1)",
            ("Bench Plotter",),
        )
    conn.commit()
    return conn


def _row_to_profile(row: sqlite3.Row) -> Profile:
    return Profile(**{c: row[c] for c in _COLUMNS})


def get_active_profile(conn: sqlite3.Connection) -> Profile:
    row = conn.execute(
        "SELECT * FROM profiles WHERE active = 1 ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM profiles ORDER BY id LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("no machine profile exists; init_db was not run")
    return _row_to_profile(row)


def update_profile(conn: sqlite3.Connection, profile_id: int, **changes) -> Profile:
    for key in changes:
        if key not in _COLUMNS or key == "id":
            raise ValueError(f"unknown profile field: {key}")

    if "pen_mode" in changes and changes["pen_mode"] not in PEN_MODES:
        raise ValueError(f"pen_mode must be one of {PEN_MODES}")

    if changes:
        assignments = ", ".join(f"{k} = ?" for k in changes)
        conn.execute(
            f"UPDATE profiles SET {assignments} WHERE id = ?",
            (*changes.values(), profile_id),
        )
        conn.commit()

    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    return _row_to_profile(row)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest server/tests/test_store.py -v`
Expected: 6 passed

- [ ] **Step 5: Add the database to gitignore and commit**

```bash
echo "server/workbench.db" >> .gitignore
git add server/store/db.py server/tests/test_store.py .gitignore
git commit -m "feat(store): SQLite machine profiles, no accounts"
```

---

## Task 9: Work envelope limits

**Files:**
- Create: `server/machine/limits.py`
- Test: `server/tests/test_limits.py`

**Interfaces:**
- Consumes: `Profile` from Task 8
- Produces:
  - `class LimitError(Exception)`
  - `check_jog(profile: Profile, mpos: tuple[float,float,float], axis: str, distance: float) -> None` — raises `LimitError` with a readable message, returns None when allowed
  - `AXIS_INDEX: dict[str, int]`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_limits.py`:

```python
from __future__ import annotations

import pytest

from server.machine.limits import LimitError, check_jog
from server.store.db import get_active_profile, init_db


@pytest.fixture()
def profile():
    conn = init_db(":memory:")
    p = get_active_profile(conn)
    conn.close()
    return p  # travel 300 x 200 x 5


def test_allows_a_jog_inside_the_envelope(profile):
    check_jog(profile, (100.0, 100.0, 2.0), "X", 10.0)


def test_allows_landing_exactly_on_the_limit(profile):
    check_jog(profile, (290.0, 0.0, 0.0), "X", 10.0)


def test_refuses_a_jog_past_the_far_limit(profile):
    with pytest.raises(LimitError) as exc:
        check_jog(profile, (295.0, 0.0, 0.0), "X", 10.0)
    assert "305" in str(exc.value)
    assert "300" in str(exc.value)


def test_refuses_a_jog_below_zero(profile):
    with pytest.raises(LimitError) as exc:
        check_jog(profile, (5.0, 0.0, 0.0), "X", -10.0)
    assert "-5" in str(exc.value)


def test_checks_the_y_axis(profile):
    with pytest.raises(LimitError):
        check_jog(profile, (0.0, 195.0, 0.0), "Y", 10.0)


def test_checks_the_z_axis(profile):
    with pytest.raises(LimitError):
        check_jog(profile, (0.0, 0.0, 4.0), "Z", 2.0)


def test_message_names_the_axis(profile):
    with pytest.raises(LimitError) as exc:
        check_jog(profile, (0.0, 195.0, 0.0), "Y", 10.0)
    assert "Y" in str(exc.value)


def test_rejects_an_unknown_axis(profile):
    with pytest.raises(LimitError, match="unknown axis"):
        check_jog(profile, (0.0, 0.0, 0.0), "A", 1.0)


def test_axis_letter_is_case_insensitive(profile):
    check_jog(profile, (0.0, 0.0, 0.0), "x", 1.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest server/tests/test_limits.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.machine.limits'`

- [ ] **Step 3: Write the implementation**

Create `server/machine/limits.py`:

```python
"""Work-envelope checks.

Refusing an out-of-range jog here, before the bytes leave, is better than
letting GRBL alarm: an alarm costs the operator a reset and their zero, and
the error it prints does not say which axis or by how much.
"""
from __future__ import annotations

from server.store.db import Profile

AXIS_INDEX: dict[str, int] = {"X": 0, "Y": 1, "Z": 2}

EPS = 1e-6


class LimitError(Exception):
    """A requested move would leave the configured work envelope."""


def _travel(profile: Profile, axis: str) -> float:
    return {"X": profile.travel_x, "Y": profile.travel_y, "Z": profile.travel_z}[axis]


def check_jog(
    profile: Profile,
    mpos: tuple[float, float, float],
    axis: str,
    distance: float,
) -> None:
    """Raise LimitError if this relative jog would exit the envelope."""
    axis = axis.upper()
    if axis not in AXIS_INDEX:
        raise LimitError(f"unknown axis {axis!r}; expected X, Y, or Z")

    limit = _travel(profile, axis)
    target = mpos[AXIS_INDEX[axis]] + distance

    if target < -EPS:
        raise LimitError(
            f"{axis}{distance:+g} would reach {target:g} mm, below the 0 mm limit"
        )
    if target > limit + EPS:
        raise LimitError(
            f"{axis}{distance:+g} would reach {target:g} mm, "
            f"past the {limit:g} mm limit"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest server/tests/test_limits.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add server/machine/limits.py server/tests/test_limits.py
git commit -m "feat(limits): refuse out-of-envelope jogs before they are sent"
```

---

## Task 10: Live machine state and snapshots

**Files:**
- Create: `server/machine/state.py`
- Test: `server/tests/test_state.py`

**Interfaces:**
- Consumes: `StatusEvent`, `ReplyEvent`, `SentEvent`, `DisconnectedEvent` from Task 5; `resolve_positions` from Task 2; `Profile` from Task 8
- Produces:
  - `@dataclass ConsoleLine(direction: str, text: str, kind: str, seq: int)`
  - `class MachineState` with `__init__(profile: Profile)`, `apply(event) -> None`, `snapshot() -> dict`, `console_tail(n: int = 2000) -> list[dict]`, `set_connection(port: str | None, baud: int, firmware: str) -> None`, `.dirty: bool`
  - Snapshot keys exactly as in spec section 6.2: `conn state mpos wpos wco feed spindle ov pen alarm error job seq`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_state.py`:

```python
from __future__ import annotations

import pytest

from server.grbl_serial.grbl import parse_reply, parse_status
from server.grbl_serial.streamer import (
    DisconnectedEvent,
    ReplyEvent,
    SentEvent,
    StatusEvent,
)
from server.machine.state import MachineState
from server.store.db import get_active_profile, init_db


@pytest.fixture()
def state():
    conn = init_db(":memory:")
    p = get_active_profile(conn)
    conn.close()
    return MachineState(p)


def status_event(line: str) -> StatusEvent:
    parsed = parse_status(line)
    assert parsed is not None
    return StatusEvent(parsed)


def reply_event(line: str) -> ReplyEvent:
    parsed = parse_reply(line)
    assert parsed is not None
    return ReplyEvent(parsed)


def test_starts_disconnected(state):
    snap = state.snapshot()
    assert snap["conn"]["connected"] is False
    assert snap["state"] == "Disconnected"


def test_snapshot_has_every_documented_key(state):
    snap = state.snapshot()
    for key in (
        "conn", "state", "mpos", "wpos", "wco", "feed",
        "spindle", "ov", "pen", "alarm", "error", "job", "seq",
    ):
        assert key in snap


def test_status_updates_position_and_state(state):
    state.apply(status_event("<Run|MPos:124.500,62.858,5.000|FS:800,0|WCO:100.000,50.000,0.000>"))
    snap = state.snapshot()
    assert snap["state"] == "Run"
    assert snap["mpos"] == [124.5, 62.858, 5.0]
    assert snap["wpos"] == pytest.approx([24.5, 12.858, 5.0])
    assert snap["feed"] == 800


def test_wco_is_carried_between_reports(state):
    state.apply(status_event("<Idle|MPos:100.000,50.000,0.000|FS:0,0|WCO:100.000,50.000,0.000>"))
    state.apply(status_event("<Idle|MPos:110.000,50.000,0.000|FS:0,0>"))
    snap = state.snapshot()
    assert snap["wco"] == [100.0, 50.0, 0.0]
    assert snap["wpos"] == pytest.approx([10.0, 0.0, 0.0])


def test_pen_is_derived_from_z(state):
    """profile has pen_up_z=5, pen_down_z=0."""
    state.apply(status_event("<Idle|MPos:0.000,0.000,5.000|FS:0,0>"))
    assert state.snapshot()["pen"] == "up"
    state.apply(status_event("<Idle|MPos:0.000,0.000,0.000|FS:0,0>"))
    assert state.snapshot()["pen"] == "down"
    state.apply(status_event("<Idle|MPos:0.000,0.000,2.500|FS:0,0>"))
    assert state.snapshot()["pen"] == "moving"


def test_alarm_reply_sets_the_alarm_field(state):
    state.apply(reply_event("ALARM:2"))
    snap = state.snapshot()
    assert snap["alarm"] is not None
    assert "Soft limit" in snap["alarm"]


def test_error_reply_sets_the_error_field(state):
    state.apply(reply_event("error:20"))
    assert state.snapshot()["error"] is not None


def test_a_good_status_clears_a_stale_error(state):
    state.apply(reply_event("error:20"))
    assert state.snapshot()["error"] is not None
    state.apply(status_event("<Idle|MPos:0.000,0.000,0.000|FS:0,0>"))
    assert state.snapshot()["error"] is None


def test_alarm_survives_until_the_state_leaves_alarm(state):
    state.apply(reply_event("ALARM:2"))
    state.apply(status_event("<Alarm|MPos:0.000,0.000,0.000|FS:0,0>"))
    assert state.snapshot()["alarm"] is not None
    state.apply(status_event("<Idle|MPos:0.000,0.000,0.000|FS:0,0>"))
    assert state.snapshot()["alarm"] is None


def test_console_records_both_directions(state):
    state.apply(SentEvent("$J=G91 G21 X10 F1000"))
    state.apply(reply_event("ok"))
    tail = state.console_tail()
    assert tail[0]["direction"] == "tx"
    assert tail[1]["direction"] == "rx"


def test_console_is_capped(state):
    for i in range(2500):
        state.apply(SentEvent(f"G0 X{i}"))
    tail = state.console_tail()
    assert len(tail) <= 2000
    assert tail[-1]["text"].endswith("2499")


def test_status_reports_do_not_flood_the_console(state):
    """Polling at 5 Hz would drown the log in status lines."""
    for _ in range(20):
        state.apply(status_event("<Idle|MPos:0.000,0.000,0.000|FS:0,0>"))
    assert state.console_tail() == []


def test_disconnect_resets_the_connection(state):
    state.set_connection("COM5", 115200, "Grbl 1.1h")
    assert state.snapshot()["conn"]["connected"] is True
    state.apply(DisconnectedEvent("cable pulled"))
    snap = state.snapshot()
    assert snap["conn"]["connected"] is False
    assert snap["state"] == "Disconnected"
    assert "cable pulled" in snap["error"]


def test_seq_increases_on_every_change(state):
    first = state.snapshot()["seq"]
    state.apply(status_event("<Idle|MPos:1.000,0.000,0.000|FS:0,0>"))
    assert state.snapshot()["seq"] > first


def test_dirty_flag_tracks_unbroadcast_changes(state):
    state.apply(status_event("<Idle|MPos:1.000,0.000,0.000|FS:0,0>"))
    assert state.dirty is True
    state.snapshot()
    assert state.dirty is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest server/tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.machine.state'`

- [ ] **Step 3: Write the implementation**

Create `server/machine/state.py`:

```python
"""The single authoritative picture of the machine.

Everything the browser shows — readout, state badge, pen indicator, console,
connection light — is a field of one snapshot built here. There is deliberately
no second source for any of it, so the panels cannot drift apart.

Mutated only by events from the streamer thread; read by the WebSocket
broadcaster. That makes it testable by feeding it a list of events.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from server.grbl_serial.grbl import resolve_positions
from server.grbl_serial.streamer import (
    DisconnectedEvent,
    ReplyEvent,
    SentEvent,
    StatusEvent,
)
from server.store.db import Profile

CONSOLE_LIMIT = 2000
PEN_EPS = 0.01


@dataclass
class ConsoleLine:
    direction: str  # "tx" | "rx" | "sys"
    text: str
    kind: str       # "ok" | "error" | "alarm" | "message" | "banner" | "settings" | "line"
    seq: int


class MachineState:
    def __init__(self, profile: Profile) -> None:
        self.profile = profile

        self.connected = False
        self.port: str | None = None
        self.baud = profile.baud
        self.firmware = ""

        self.state = "Disconnected"
        self.mpos = [0.0, 0.0, 0.0]
        self.wpos = [0.0, 0.0, 0.0]
        self.wco: list[float] = [0.0, 0.0, 0.0]
        self._cached_wco: tuple[float, float, float] | None = None
        self.feed = 0.0
        self.spindle = 0.0
        self.ov = [100, 100, 100]

        self.alarm: str | None = None
        self.error: str | None = None

        self._console: deque[ConsoleLine] = deque(maxlen=CONSOLE_LIMIT)
        self._seq = 0
        self.dirty = False

    # --- mutation ----------------------------------------------------------

    def _touch(self) -> None:
        self._seq += 1
        self.dirty = True

    def set_connection(self, port: str | None, baud: int, firmware: str) -> None:
        self.connected = port is not None
        self.port = port
        self.baud = baud
        self.firmware = firmware
        if self.connected:
            self._log("sys", f"connected to {port} at {baud} — {firmware}", "message")
        else:
            self.state = "Disconnected"
            self._log("sys", "disconnected", "message")
        self._touch()

    def apply(self, event: object) -> None:
        if isinstance(event, StatusEvent):
            self._apply_status(event)
        elif isinstance(event, ReplyEvent):
            self._apply_reply(event)
        elif isinstance(event, SentEvent):
            self._log("tx", event.line, "line")
            self._touch()
        elif isinstance(event, DisconnectedEvent):
            self.connected = False
            self.port = None
            self.state = "Disconnected"
            self.error = f"connection lost: {event.reason}"
            self._log("sys", self.error, "error")
            self._touch()

    def _apply_status(self, event: StatusEvent) -> None:
        status = event.status
        mpos, wpos, wco = resolve_positions(status, self._cached_wco)
        if status.wco is not None:
            self._cached_wco = status.wco

        self.mpos = list(mpos)
        self.wpos = list(wpos)
        self.wco = list(wco)
        self.state = (
            f"{status.state.value}:{status.substate}"
            if status.substate is not None and status.state.value == "Hold"
            else status.state.value
        )
        self.feed = status.feed
        self.spindle = status.spindle
        if status.ov is not None:
            self.ov = list(status.ov)

        # A report arriving at all means the last error is history.
        self.error = None
        if not self.state.startswith("Alarm"):
            self.alarm = None

        self.connected = True
        self._touch()
        # Status reports are NOT logged: at 5 Hz they would bury everything else.

    def _apply_reply(self, event: ReplyEvent) -> None:
        reply = event.reply
        if reply.kind == "error":
            self.error = reply.text
        elif reply.kind == "alarm":
            self.alarm = reply.text
        elif reply.kind == "banner":
            self.firmware = reply.text

        self._log("rx", reply.text, reply.kind)
        self._touch()

    def _log(self, direction: str, text: str, kind: str) -> None:
        self._console.append(ConsoleLine(direction, text, kind, self._seq))

    # --- reads -------------------------------------------------------------

    def _pen(self) -> str:
        z = self.wpos[2]
        if abs(z - self.profile.pen_down_z) < PEN_EPS:
            return "down"
        if abs(z - self.profile.pen_up_z) < PEN_EPS:
            return "up"
        return "moving"

    def snapshot(self) -> dict:
        self.dirty = False
        return {
            "conn": {
                "connected": self.connected,
                "port": self.port,
                "baud": self.baud,
                "firmware": self.firmware,
                "profile": self.profile.name,
                "penMode": self.profile.pen_mode,
                "travel": [
                    self.profile.travel_x,
                    self.profile.travel_y,
                    self.profile.travel_z,
                ],
            },
            "state": self.state,
            "mpos": self.mpos,
            "wpos": self.wpos,
            "wco": self.wco,
            "feed": self.feed,
            "spindle": self.spindle,
            "ov": {"feed": self.ov[0], "rapid": self.ov[1], "spindle": self.ov[2]},
            "pen": self._pen(),
            "alarm": self.alarm,
            "error": self.error,
            "job": None,  # file streaming arrives in the next slice
            "seq": self._seq,
        }

    def console_tail(self, n: int = CONSOLE_LIMIT) -> list[dict]:
        lines = list(self._console)[-n:]
        return [
            {"direction": l.direction, "text": l.text, "kind": l.kind, "seq": l.seq}
            for l in lines
        ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest server/tests/test_state.py -v`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add server/machine/state.py server/tests/test_state.py
git commit -m "feat(state): one authoritative snapshot driving every panel"
```

---

## Task 11: FastAPI routes and the WebSocket

**Files:**
- Create: `server/main.py`
- Test: `server/tests/test_api.py`

**Interfaces:**
- Consumes: everything from Tasks 2–10
- Produces:
  - `app: FastAPI`
  - `class Session` holding `streamer`, `state`, `conn`, with `connect(port, baud)`, `disconnect()`, `require() -> Streamer`
  - REST: `GET /api/ports`, `GET /api/profile`, `POST /api/connect`, `POST /api/disconnect`, `POST /api/jog`, `POST /api/jog/cancel`, `POST /api/home`, `POST /api/zero`, `POST /api/unlock`, `POST /api/command`, `POST /api/estop`, `GET /api/state`
  - WebSocket: `GET /ws`
  - Test seam: `app.state.transport_factory: Callable[[str, int], Transport] | None`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_api.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.main import app, session
from server.sim.grbl_sim import GrblSim


@pytest.fixture()
def client():
    sim = GrblSim()
    app.state.transport_factory = lambda port, baud: sim
    app.state.sim = sim
    with TestClient(app) as c:
        yield c
    session.disconnect()
    app.state.transport_factory = None


def test_profile_is_available_before_connecting(client):
    r = client.get("/api/profile")
    assert r.status_code == 200
    assert r.json()["travel_x"] == 300.0


def test_ports_endpoint_returns_a_list(client):
    r = client.get("/api/ports")
    assert r.status_code == 200
    body = r.json()
    assert "ports" in body
    assert "bauds" in body
    assert 115200 in body["bauds"]


def test_state_before_connecting_is_disconnected(client):
    r = client.get("/api/state")
    assert r.json()["conn"]["connected"] is False


def test_connect_reports_firmware(client):
    r = client.post("/api/connect", json={"port": "COM-SIM", "baud": 115200})
    assert r.status_code == 200
    assert "Grbl 1.1" in r.json()["firmware"]


def test_jog_before_connecting_is_refused(client):
    r = client.post("/api/jog", json={"axis": "X", "distance": 10, "feed": 1000})
    assert r.status_code == 409
    assert "not connected" in r.json()["detail"].lower()


def test_jog_after_connecting_is_accepted(client):
    client.post("/api/connect", json={"port": "COM-SIM", "baud": 115200})
    r = client.post("/api/jog", json={"axis": "X", "distance": 10, "feed": 1000})
    assert r.status_code == 200


def test_out_of_envelope_jog_is_refused_with_a_reason(client):
    client.post("/api/connect", json={"port": "COM-SIM", "baud": 115200})
    r = client.post("/api/jog", json={"axis": "X", "distance": 400, "feed": 1000})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "400" in detail and "300" in detail


def test_unknown_axis_is_refused(client):
    client.post("/api/connect", json={"port": "COM-SIM", "baud": 115200})
    r = client.post("/api/jog", json={"axis": "Q", "distance": 1, "feed": 1000})
    assert r.status_code == 400


def test_zero_requires_valid_axes(client):
    client.post("/api/connect", json={"port": "COM-SIM", "baud": 115200})
    assert client.post("/api/zero", json={"axes": "XY"}).status_code == 200
    assert client.post("/api/zero", json={"axes": "QQ"}).status_code == 400


def test_estop_works_while_connected(client):
    client.post("/api/connect", json={"port": "COM-SIM", "baud": 115200})
    r = client.post("/api/estop")
    assert r.status_code == 200
    assert app.state.sim.state == "Alarm"


def test_raw_command_is_forwarded(client):
    client.post("/api/connect", json={"port": "COM-SIM", "baud": 115200})
    r = client.post("/api/command", json={"line": "$$"})
    assert r.status_code == 200


def test_disconnect_is_idempotent(client):
    client.post("/api/connect", json={"port": "COM-SIM", "baud": 115200})
    assert client.post("/api/disconnect").status_code == 200
    assert client.post("/api/disconnect").status_code == 200


def test_websocket_sends_a_snapshot_on_connect(client):
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert "state" in msg["data"]


def test_websocket_replays_the_console_backlog(client):
    client.post("/api/connect", json={"port": "COM-SIM", "baud": 115200})
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()               # snapshot
        msg = ws.receive_json()         # console backlog
        assert msg["type"] == "console"
        assert isinstance(msg["data"], list)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest server/tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.main'`

- [ ] **Step 3: Write the implementation**

Create `server/main.py`:

```python
"""The local workbench server.

One process: it owns the serial port, keeps the authoritative machine state,
and serves both the REST command surface and the state WebSocket. There is no
authentication because there is one user, sitting at the machine.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from server.grbl_serial import ports as ports_mod
from server.grbl_serial.grbl import Realtime, encode_jog, encode_zero
from server.grbl_serial.streamer import Streamer, Transport
from server.machine.limits import AXIS_INDEX, LimitError, check_jog
from server.machine.state import MachineState
from server.store.db import get_active_profile, init_db

BANNER_TIMEOUT = 3.0


class SerialTransport:
    """pyserial wrapped in the Transport protocol."""

    def __init__(self, port: str, baud: int) -> None:
        import serial

        self._ser = serial.Serial(port, baud, timeout=0)
        # Toggling DTR resets an Arduino, which is how we provoke the banner.
        self._ser.dtr = False
        time.sleep(0.1)
        self._ser.dtr = True
        time.sleep(0.2)

    def write(self, data: bytes) -> None:
        self._ser.write(data)

    def read_available(self) -> bytes:
        waiting = self._ser.in_waiting
        return self._ser.read(waiting) if waiting else b""

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


class Session:
    """Holds the one connection and the one machine state."""

    def __init__(self) -> None:
        self.conn = init_db()
        self.profile = get_active_profile(self.conn)
        self.state = MachineState(self.profile)
        self.streamer: Streamer | None = None

    def require(self) -> Streamer:
        if self.streamer is None or not self.streamer.connected:
            raise HTTPException(409, "Machine is not connected.")
        return self.streamer

    def connect(self, transport: Transport, port: str, baud: int) -> str:
        self.disconnect()
        self.profile = get_active_profile(self.conn)
        self.state = MachineState(self.profile)

        streamer = Streamer(
            transport,
            rx_buffer=self.profile.rx_buffer,
            on_event=self.state.apply,
        )
        self.streamer = streamer

        # Wait for the controller to identify itself. The DTR toggle in
        # SerialTransport is what actually resets an Arduino; this newline is
        # only a nudge for a board that was already powered up. One byte, so
        # the realtime contract still holds.
        streamer.send_realtime(b"\n")
        deadline = time.time() + BANNER_TIMEOUT
        while time.time() < deadline and not self.state.firmware:
            streamer.pump()
            time.sleep(0.02)

        if not self.state.firmware:
            # Some boards miss the reset window; a status poll also proves life.
            streamer.send_realtime(Realtime.STATUS)
            deadline = time.time() + 1.0
            while time.time() < deadline and self.state.state == "Disconnected":
                streamer.pump()
                time.sleep(0.02)

        if not self.state.firmware and self.state.state == "Disconnected":
            self.disconnect()
            raise HTTPException(
                502,
                f"Opened {port} but the controller never identified itself. "
                "Wrong baud rate, or not a GRBL controller.",
            )

        streamer.send_line("$I")
        streamer.send_line("$$")
        streamer.start(poll_hz=5.0)
        self.state.set_connection(port, baud, self.state.firmware or "unknown")
        return self.state.firmware

    def disconnect(self) -> None:
        if self.streamer is not None:
            self.streamer.stop()
            try:
                self.streamer.transport.close()
            except Exception:
                pass
            self.streamer = None
        self.state.set_connection(None, self.profile.baud, "")


session = Session()

app = FastAPI(title="TraceWorks Workbench")
app.state.transport_factory = None
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _make_transport(port: str, baud: int) -> Transport:
    factory = app.state.transport_factory
    if factory is not None:
        return factory(port, baud)
    return SerialTransport(port, baud)


# --- REST -------------------------------------------------------------------

@app.get("/api/profile")
def read_profile() -> dict:
    return asdict(get_active_profile(session.conn))


@app.get("/api/ports")
def read_ports() -> dict:
    try:
        found = ports_mod.list_ports()
    except Exception:
        found = []
    return {
        "ports": [asdict(p) for p in found],
        "bauds": ports_mod.BAUD_RATES,
        "suggested": ports_mod.autoselect(found),
    }


@app.get("/api/state")
def read_state() -> dict:
    return session.state.snapshot()


@app.post("/api/connect")
def connect(port: str = Body(..., embed=True), baud: int = Body(115200, embed=True)) -> dict:
    try:
        transport = _make_transport(port, baud)
    except Exception as exc:
        raise HTTPException(502, f"Could not open {port}: {exc}") from exc
    firmware = session.connect(transport, port, baud)
    return {"ok": True, "firmware": firmware}


@app.post("/api/disconnect")
def disconnect() -> dict:
    session.disconnect()
    return {"ok": True}


@app.post("/api/jog")
def jog(
    axis: str = Body(...),
    distance: float = Body(...),
    feed: float = Body(1000.0),
) -> dict:
    streamer = session.require()
    try:
        check_jog(
            session.profile,
            (session.state.mpos[0], session.state.mpos[1], session.state.mpos[2]),
            axis,
            distance,
        )
    except LimitError as exc:
        raise HTTPException(400, str(exc)) from exc
    streamer.send_line(encode_jog(axis, distance, feed))
    return {"ok": True}


@app.post("/api/jog/cancel")
def jog_cancel() -> dict:
    session.require().send_realtime(Realtime.JOG_CANCEL)
    return {"ok": True}


@app.post("/api/home")
def home() -> dict:
    session.require().send_line("$H")
    return {"ok": True}


@app.post("/api/unlock")
def unlock() -> dict:
    session.require().send_line("$X")
    return {"ok": True}


@app.post("/api/zero")
def zero(axes: str = Body(..., embed=True)) -> dict:
    streamer = session.require()
    axes = axes.upper()
    if not axes or any(a not in AXIS_INDEX for a in axes):
        raise HTTPException(400, f"axes must be made up of X, Y, Z — got {axes!r}")
    streamer.send_line(encode_zero(axes))
    return {"ok": True}


@app.post("/api/command")
def command(line: str = Body(..., embed=True)) -> dict:
    streamer = session.require()
    text = line.strip()
    if not text:
        raise HTTPException(400, "empty command")
    streamer.send_line(text)
    return {"ok": True}


@app.post("/api/estop")
def estop() -> dict:
    """Soft reset, immediately. No feed hold, no queue, no confirmation."""
    streamer = session.streamer
    if streamer is None:
        raise HTTPException(409, "Machine is not connected.")
    streamer.send_realtime(Realtime.SOFT_RESET)
    return {"ok": True}


# --- WebSocket --------------------------------------------------------------

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "snapshot", "data": session.state.snapshot()})
    await websocket.send_json({"type": "console", "data": session.state.console_tail()})

    sent_console = len(session.state.console_tail())
    last_keepalive = time.time()

    try:
        while True:
            await asyncio.sleep(0.1)  # 10 Hz cap

            now = time.time()
            if session.state.dirty:
                await websocket.send_json(
                    {"type": "snapshot", "data": session.state.snapshot()}
                )
                last_keepalive = now
            elif now - last_keepalive >= 1.0:
                await websocket.send_json(
                    {"type": "snapshot", "data": session.state.snapshot()}
                )
                last_keepalive = now

            tail = session.state.console_tail()
            if len(tail) != sent_console:
                fresh = tail[sent_console:] if len(tail) > sent_console else tail
                sent_console = len(tail)
                if fresh:
                    await websocket.send_json({"type": "console", "data": fresh})
    except WebSocketDisconnect:
        return
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest server/tests/test_api.py -v`
Expected: 14 passed

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest server/tests/ -v`
Expected: 110 passed

- [ ] **Step 6: Commit**

```bash
git add server/main.py server/tests/test_api.py
git commit -m "feat(api): REST command surface and state WebSocket"
```

---

## Task 12: Frontend types, API client, and the machine hook

**Files:**
- Create: `lib/machine.ts`
- Modify: `lib/api.ts` (full rewrite)

**Interfaces:**
- Consumes: the REST surface and snapshot schema from Task 11
- Produces:
  - `types Snapshot, ConnInfo, ConsoleLine, PortInfo, Profile` in `lib/machine.ts`
  - `useMachine(): { snap: Snapshot; console: ConsoleLine[]; live: boolean }`
  - `api.ports() api.profile() api.connect(port, baud) api.disconnect() api.jog(axis, distance, feed) api.jogCancel() api.home() api.unlock() api.zero(axes) api.command(line) api.estop()` in `lib/api.ts`

- [ ] **Step 1: Write the types and the hook**

Create `lib/machine.ts`:

```ts
"use client";

import { useEffect, useRef, useState } from "react";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type ConnInfo = {
  connected: boolean;
  port: string | null;
  baud: number;
  firmware: string;
  profile: string;
  penMode: "z-axis" | "servo-pwm";
  travel: [number, number, number];
};

export type Snapshot = {
  conn: ConnInfo;
  state: string;
  mpos: [number, number, number];
  wpos: [number, number, number];
  wco: [number, number, number];
  feed: number;
  spindle: number;
  ov: { feed: number; rapid: number; spindle: number };
  pen: "up" | "down" | "moving";
  alarm: string | null;
  error: string | null;
  job: null;
  seq: number;
};

export type ConsoleLine = {
  direction: "tx" | "rx" | "sys";
  text: string;
  kind: string;
  seq: number;
};

export type PortInfo = {
  device: string;
  description: string;
  vid: number | null;
  pid: number | null;
  likely_controller: boolean;
  chip: string | null;
};

export type Profile = {
  id: number;
  name: string;
  controller: string;
  baud: number;
  rx_buffer: number;
  pen_mode: "z-axis" | "servo-pwm";
  travel_x: number;
  travel_y: number;
  travel_z: number;
  pen_up_z: number;
  pen_down_z: number;
  servo_up: number;
  servo_down: number;
  travel_feed: number;
  draw_feed: number;
  z_feed: number;
  jog_feed: number;
};

export const EMPTY_SNAPSHOT: Snapshot = {
  conn: {
    connected: false,
    port: null,
    baud: 115200,
    firmware: "",
    profile: "",
    penMode: "z-axis",
    travel: [300, 200, 5],
  },
  state: "Disconnected",
  mpos: [0, 0, 0],
  wpos: [0, 0, 0],
  wco: [0, 0, 0],
  feed: 0,
  spindle: 0,
  ov: { feed: 100, rapid: 100, spindle: 100 },
  pen: "up",
  alarm: null,
  error: null,
  job: null,
  seq: 0,
};

const CONSOLE_CAP = 2000;

/**
 * Subscribes to the server's machine state.
 *
 * Every panel reads from the one snapshot this returns, which is what keeps
 * the readout, the state badge, and the canvas from disagreeing. Reconnects
 * on its own, because the page outliving a server restart is normal in dev.
 */
export function useMachine() {
  const [snap, setSnap] = useState<Snapshot>(EMPTY_SNAPSHOT);
  const [lines, setLines] = useState<ConsoleLine[]>([]);
  const [live, setLive] = useState(false);
  const seqRef = useRef(-1);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const open = () => {
      const url = API_URL.replace(/^http/, "ws") + "/ws";
      ws = new WebSocket(url);

      ws.onopen = () => setLive(true);

      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data) as
          | { type: "snapshot"; data: Snapshot }
          | { type: "console"; data: ConsoleLine[] };

        if (msg.type === "snapshot") {
          // Frames can arrive out of order after a reconnect; seq settles it.
          if (msg.data.seq >= seqRef.current) {
            seqRef.current = msg.data.seq;
            setSnap(msg.data);
          }
        } else {
          setLines((prev) => [...prev, ...msg.data].slice(-CONSOLE_CAP));
        }
      };

      ws.onclose = () => {
        setLive(false);
        if (!closed) retry = setTimeout(open, 1000);
      };

      ws.onerror = () => ws?.close();
    };

    open();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, []);

  return { snap, console: lines, live };
}
```

- [ ] **Step 2: Rewrite the API client**

Replace the whole of `lib/api.ts`:

```ts
// REST client for the local workbench server. One user, one machine —
// no accounts, no email, no device pairing.
import { API_URL, type PortInfo, type Profile, type Snapshot } from "./machine";

async function req<T>(path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(
      `Can't reach the workbench server. Is it running on ${API_URL}?`
    );
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error(data?.detail || `Request failed (${res.status}).`);
  return data as T;
}

export type PortsResponse = {
  ports: PortInfo[];
  bauds: number[];
  suggested: string | null;
};

export const api = {
  ports: () => req<PortsResponse>("/api/ports"),
  profile: () => req<Profile>("/api/profile"),
  state: () => req<Snapshot>("/api/state"),

  connect: (port: string, baud: number) =>
    req<{ ok: boolean; firmware: string }>("/api/connect", { port, baud }),
  disconnect: () => req<{ ok: boolean }>("/api/disconnect", {}),

  jog: (axis: string, distance: number, feed: number) =>
    req<{ ok: boolean }>("/api/jog", { axis, distance, feed }),
  jogCancel: () => req<{ ok: boolean }>("/api/jog/cancel", {}),

  home: () => req<{ ok: boolean }>("/api/home", {}),
  unlock: () => req<{ ok: boolean }>("/api/unlock", {}),
  zero: (axes: string) => req<{ ok: boolean }>("/api/zero", { axes }),
  command: (line: string) => req<{ ok: boolean }>("/api/command", { line }),
  estop: () => req<{ ok: boolean }>("/api/estop", {}),
};
```

- [ ] **Step 3: Verify it typechecks**

Run: `npx tsc --noEmit`
Expected: no errors. If it reports unused imports in files you deleted in Task 1, those files were missed — delete them.

- [ ] **Step 4: Commit**

```bash
git add lib/machine.ts lib/api.ts
git commit -m "feat(ui): machine snapshot types, WebSocket hook, REST client"
```

---

## Task 13: Top bar, DRO, and console

**Files:**
- Create: `components/workspace/TopBar.tsx`, `components/workspace/Dro.tsx`, `components/workspace/Console.tsx`

**Interfaces:**
- Consumes: `useMachine`, `Snapshot`, `ConsoleLine` from Task 12; `api` from Task 12
- Produces:
  - `<TopBar snap={Snapshot} live={boolean} onError={(m: string) => void} />`
  - `<Dro snap={Snapshot} />`
  - `<Console lines={ConsoleLine[]} connected={boolean} onError={(m: string) => void} />`

- [ ] **Step 1: Write the top bar**

Create `components/workspace/TopBar.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { api, type PortsResponse } from "@/lib/api";
import type { Snapshot } from "@/lib/machine";

const STATE_TONE: Record<string, string> = {
  Idle: "text-signal",
  Run: "text-copper",
  Jog: "text-copper",
  Home: "text-copper",
  Hold: "text-warn",
  "Hold:0": "text-warn",
  "Hold:1": "text-warn",
  Check: "text-warn",
  Door: "text-warn",
  Alarm: "text-danger",
  Disconnected: "text-faint",
};

export default function TopBar({
  snap,
  live,
  onError,
}: {
  snap: Snapshot;
  live: boolean;
  onError: (message: string) => void;
}) {
  const [ports, setPorts] = useState<PortsResponse | null>(null);
  const [port, setPort] = useState("");
  const [baud, setBaud] = useState(115200);
  const [busy, setBusy] = useState(false);

  const connected = snap.conn.connected;

  useEffect(() => {
    if (connected) return;
    api
      .ports()
      .then((p) => {
        setPorts(p);
        setPort((current) => current || p.suggested || p.ports[0]?.device || "");
      })
      .catch((e) => onError((e as Error).message));
  }, [connected, onError]);

  async function toggle() {
    setBusy(true);
    try {
      if (connected) await api.disconnect();
      else await api.connect(port, baud);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function estop() {
    try {
      await api.estop();
    } catch (e) {
      onError((e as Error).message);
    }
  }

  return (
    <header className="flex h-14 flex-none items-center gap-4 border-b border-line bg-panel px-4">
      <span className={`dot ${connected && live ? "dot-live" : ""}`}
            style={{ background: connected ? undefined : "var(--color-faint)" }} />

      {connected ? (
        <span className="font-mono text-xs text-ink-soft">
          {snap.conn.port} · {snap.conn.baud} · {snap.conn.firmware || "unknown"}
        </span>
      ) : (
        <div className="flex items-center gap-2">
          <select
            className="field !w-auto !py-1.5"
            value={port}
            onChange={(e) => setPort(e.target.value)}
          >
            {(ports?.ports ?? []).map((p) => (
              <option key={p.device} value={p.device}>
                {p.device}
                {p.chip ? ` — ${p.chip}` : ""}
              </option>
            ))}
            {(ports?.ports.length ?? 0) === 0 && <option value="">no ports found</option>}
          </select>
          <select
            className="field !w-auto !py-1.5"
            value={baud}
            onChange={(e) => setBaud(Number(e.target.value))}
          >
            {(ports?.bauds ?? [115200]).map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
        </div>
      )}

      <button
        className={`btn ${connected ? "btn-ghost" : "btn-primary"}`}
        onClick={toggle}
        disabled={busy || (!connected && !port)}
      >
        {connected ? "Disconnect" : "Connect"}
      </button>

      <span className={`tlabel !text-sm ${STATE_TONE[snap.state] ?? "text-ink"}`}>
        {snap.state}
      </span>

      <div className="ml-auto flex items-center gap-4">
        <span className="tlabel">{snap.conn.profile}</span>
        <button
          className="btn"
          style={{
            background: "var(--color-danger)",
            color: "#fdf3ea",
            borderColor: "var(--color-danger)",
          }}
          onClick={estop}
          disabled={!connected}
          title="Soft reset — halts immediately, position is lost"
        >
          ■ E-Stop
        </button>
      </div>
    </header>
  );
}
```

- [ ] **Step 2: Write the DRO**

Create `components/workspace/Dro.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import type { Snapshot } from "@/lib/machine";

const AXES = ["X", "Y", "Z"] as const;

export default function Dro({ snap }: { snap: Snapshot }) {
  const [mode, setMode] = useState<"work" | "machine">("work");
  const [stale, setStale] = useState(false);
  const lastSeq = useRef(snap.seq);
  const lastAt = useRef(Date.now());

  // A frozen readout must LOOK frozen, otherwise a dead link reads as a
  // parked machine.
  useEffect(() => {
    if (snap.seq !== lastSeq.current) {
      lastSeq.current = snap.seq;
      lastAt.current = Date.now();
      setStale(false);
    }
    const t = setInterval(() => {
      setStale(Date.now() - lastAt.current > 1000);
    }, 250);
    return () => clearInterval(t);
  }, [snap.seq]);

  const values = mode === "work" ? snap.wpos : snap.mpos;

  return (
    <section className="panel ticked p-4">
      <div className="flex items-center justify-between">
        <span className="tlabel">position</span>
        <div className="flex gap-1">
          {(["work", "machine"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`tlabel rounded px-1.5 py-0.5 ${
                mode === m ? "bg-well text-ink" : "text-faint hover:text-muted"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      <dl className={`mt-3 space-y-1 ${stale ? "opacity-40" : ""}`}>
        {AXES.map((axis, i) => (
          <div key={axis} className="flex items-baseline justify-between gap-3">
            <dt className="font-mono text-xs text-muted">{axis}</dt>
            <dd
              className="font-mono text-2xl text-ink"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {values[i].toFixed(3)}
            </dd>
          </div>
        ))}
      </dl>

      <div className="mt-4 space-y-1 border-t border-line pt-3">
        <div className="flex justify-between">
          <span className="tlabel">feed</span>
          <span className="font-mono text-xs text-ink">{snap.feed.toFixed(0)}</span>
        </div>
        <div className="flex justify-between">
          <span className="tlabel">pen</span>
          <span
            className={`font-mono text-xs ${
              snap.pen === "down" ? "text-copper" : "text-muted"
            }`}
          >
            {snap.pen}
          </span>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 3: Write the console**

Create `components/workspace/Console.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ConsoleLine } from "@/lib/machine";

const TONE: Record<string, string> = {
  error: "text-danger",
  alarm: "text-danger",
  ok: "text-signal",
  banner: "text-copper",
  message: "text-warn",
};

export default function Console({
  lines,
  connected,
  onError,
}: {
  lines: ConsoleLine[];
  connected: boolean;
  onError: (message: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [cursor, setCursor] = useState(-1);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [lines.length]);

  async function send() {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    setHistory((h) => [...h, text]);
    setCursor(-1);
    try {
      await api.command(text);
    } catch (e) {
      onError((e as Error).message);
    }
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      send();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const next = cursor < 0 ? history.length - 1 : Math.max(0, cursor - 1);
      if (history[next] !== undefined) {
        setCursor(next);
        setDraft(history[next]);
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = cursor + 1;
      if (next >= history.length) {
        setCursor(-1);
        setDraft("");
      } else {
        setCursor(next);
        setDraft(history[next]);
      }
    }
  }

  return (
    <section className="panel ticked flex min-h-0 flex-col">
      <div className="flex-none border-b border-line px-3 py-2">
        <span className="tlabel">console</span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2 font-mono text-xs leading-relaxed">
        {lines.length === 0 && (
          <p className="text-faint">Nothing yet. Connect to see traffic.</p>
        )}
        {lines.map((l, i) => (
          <div key={`${l.seq}-${i}`} className="flex gap-2">
            <span className="text-faint">
              {l.direction === "tx" ? ">" : l.direction === "rx" ? "<" : "·"}
            </span>
            <span className={TONE[l.kind] ?? "text-ink-soft"}>{l.text}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className="flex flex-none gap-2 border-t border-line p-2">
        <input
          className="field"
          placeholder={connected ? "$$ or G0 X10…" : "connect first"}
          value={draft}
          disabled={!connected}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKey}
        />
        <button className="btn btn-ghost" onClick={send} disabled={!connected}>
          Send
        </button>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Verify it typechecks**

Run: `npx tsc --noEmit`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add components/workspace/
git commit -m "feat(ui): top bar with connect and E-stop, DRO, console"
```

---

## Task 14: Jog panel, canvas, and the assembled workspace

**Files:**
- Create: `components/workspace/JogPanel.tsx`, `components/workspace/MachineCanvas.tsx`
- Modify: `app/page.tsx` (full rewrite)

**Interfaces:**
- Consumes: `useMachine`, `api`, `TopBar`, `Dro`, `Console` from Tasks 12–13
- Produces: `<JogPanel snap={Snapshot} onError={(m: string) => void} />`, `<MachineCanvas snap={Snapshot} />`, and the workspace page

- [ ] **Step 1: Write the jog panel**

Create `components/workspace/JogPanel.tsx`:

```tsx
"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Snapshot } from "@/lib/machine";

const STEPS = [0.1, 1, 10, 100];
const FEEDS = [100, 500, 1000, 2000, 3000];

export default function JogPanel({
  snap,
  onError,
}: {
  snap: Snapshot;
  onError: (message: string) => void;
}) {
  const [step, setStep] = useState(1);
  const [feed, setFeed] = useState(1000);
  const connected = snap.conn.connected;
  const servoPen = snap.conn.penMode === "servo-pwm";

  async function call(fn: () => Promise<unknown>) {
    try {
      await fn();
    } catch (e) {
      onError((e as Error).message);
    }
  }

  const jog = (axis: string, sign: number) =>
    call(() => api.jog(axis, sign * step, feed));

  // With the servo on the spindle PWM pin there is no Z axis to move, so the
  // Z buttons become pen commands and the step size stops applying to them.
  const penUp = () => call(() => api.command(`M3 S90`));
  const penDown = () => call(() => api.command(`M3 S0`));

  const Btn = ({
    label,
    onClick,
    title,
  }: {
    label: string;
    onClick: () => void;
    title?: string;
  }) => (
    <button
      className="btn btn-ghost !px-0 !py-3 w-full"
      onClick={onClick}
      disabled={!connected}
      title={title}
    >
      {label}
    </button>
  );

  return (
    <section className="panel ticked space-y-4 p-4">
      <span className="tlabel">jog</span>

      <div className="flex gap-3">
        <div className="grid flex-1 grid-cols-3 gap-1">
          <div />
          <Btn label="Y+" onClick={() => jog("Y", 1)} />
          <div />
          <Btn label="X−" onClick={() => jog("X", -1)} />
          <button
            className="btn btn-copper !px-0 !py-3 w-full"
            onClick={() => call(api.home)}
            disabled={!connected}
            title="$H — run the homing cycle"
          >
            HOME
          </button>
          <Btn label="X+" onClick={() => jog("X", 1)} />
          <div />
          <Btn label="Y−" onClick={() => jog("Y", -1)} />
          <div />
        </div>

        <div className="flex w-16 flex-col gap-1">
          {servoPen ? (
            <>
              <Btn label="PEN↑" onClick={penUp} title="M3 S90 — lift the pen" />
              <Btn label="PEN↓" onClick={penDown} title="M3 S0 — drop the pen" />
            </>
          ) : (
            <>
              <Btn label="Z+" onClick={() => jog("Z", 1)} />
              <Btn label="Z−" onClick={() => jog("Z", -1)} />
            </>
          )}
        </div>
      </div>

      <div>
        <span className="tlabel">step (mm)</span>
        <div className="mt-1 flex gap-1">
          {STEPS.map((s) => (
            <button
              key={s}
              onClick={() => setStep(s)}
              className={`btn flex-1 !px-0 ${step === s ? "btn-primary" : "btn-ghost"}`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div>
        <span className="tlabel">feed (mm/min)</span>
        <div className="mt-1 flex gap-1">
          {FEEDS.map((f) => (
            <button
              key={f}
              onClick={() => setFeed(f)}
              className={`btn flex-1 !px-0 ${feed === f ? "btn-primary" : "btn-ghost"}`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      <div>
        <span className="tlabel">zero</span>
        <div className="mt-1 flex gap-1">
          {["X", "Y", "Z", "XYZ"].map((axes) => (
            <button
              key={axes}
              className="btn btn-ghost flex-1 !px-0"
              disabled={!connected}
              onClick={() => call(() => api.zero(axes))}
            >
              {axes === "XYZ" ? "ALL" : axes}
            </button>
          ))}
        </div>
      </div>

      {snap.alarm && (
        <div className="rounded border border-line-strong bg-well p-2">
          <p className="font-mono text-xs text-danger">{snap.alarm}</p>
          <button
            className="btn btn-ghost mt-2 w-full"
            onClick={() => call(api.unlock)}
          >
            Unlock ($X)
          </button>
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Write the canvas**

Create `components/workspace/MachineCanvas.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import type { Snapshot } from "@/lib/machine";

const PAD = 12; // mm of margin around the bed
const TRAIL = 400; // points kept in the motion trail

/**
 * The work envelope with the tool's live position on it.
 *
 * Slice 1 has no toolpath to draw, so this shows where the machine is and
 * where it has just been — which is what makes a jog visibly a jog.
 */
export default function MachineCanvas({ snap }: { snap: Snapshot }) {
  const [bedX, bedY] = snap.conn.travel;
  const [x, y] = snap.wpos;
  const [trail, setTrail] = useState<[number, number][]>([]);
  const lastSeq = useRef(-1);

  useEffect(() => {
    if (snap.seq === lastSeq.current) return;
    lastSeq.current = snap.seq;
    setTrail((prev) => {
      const last = prev[prev.length - 1];
      if (last && Math.hypot(last[0] - x, last[1] - y) < 0.05) return prev;
      return [...prev, [x, y] as [number, number]].slice(-TRAIL);
    });
  }, [snap.seq, x, y]);

  const vb = `${-PAD} ${-PAD} ${bedX + PAD * 2} ${bedY + PAD * 2}`;
  const penDown = snap.pen === "down";

  return (
    <div className="panel ticked substrate flex min-h-0 flex-1 items-center justify-center p-4">
      <svg
        viewBox={vb}
        className="h-full w-full"
        /* G-code Y grows toward the machine's rear; SVG Y grows downward. */
        style={{ transform: "scaleY(-1)" }}
      >
        <rect
          x={0}
          y={0}
          width={bedX}
          height={bedY}
          fill="var(--color-panel-2)"
          stroke="var(--color-line-strong)"
          strokeWidth={0.4}
        />

        {trail.length > 1 && (
          <polyline
            points={trail.map(([px, py]) => `${px},${py}`).join(" ")}
            fill="none"
            stroke="var(--color-copper)"
            strokeWidth={0.5}
            strokeOpacity={0.5}
            strokeLinecap="round"
          />
        )}

        <g stroke={penDown ? "var(--color-copper)" : "var(--color-muted)"} strokeWidth={0.5}>
          <line x1={x - 6} y1={y} x2={x + 6} y2={y} />
          <line x1={x} y1={y - 6} x2={x} y2={y + 6} />
          <circle cx={x} cy={y} r={2} fill="none" />
        </g>

        <g stroke="var(--color-line)" strokeWidth={0.25} strokeDasharray="2 2">
          <line x1={0} y1={y} x2={bedX} y2={y} />
          <line x1={x} y1={0} x2={x} y2={bedY} />
        </g>
      </svg>
    </div>
  );
}
```

- [ ] **Step 3: Assemble the workspace**

Replace the whole of `app/page.tsx`:

```tsx
"use client";

import { useCallback, useState } from "react";
import Console from "@/components/workspace/Console";
import Dro from "@/components/workspace/Dro";
import JogPanel from "@/components/workspace/JogPanel";
import MachineCanvas from "@/components/workspace/MachineCanvas";
import TopBar from "@/components/workspace/TopBar";
import { useMachine } from "@/lib/machine";

export default function Workspace() {
  const { snap, console: lines, live } = useMachine();
  const [banner, setBanner] = useState<string | null>(null);

  const onError = useCallback((message: string) => {
    setBanner(message);
    setTimeout(() => setBanner(null), 6000);
  }, []);

  return (
    <div className="flex h-screen flex-col bg-paper">
      <TopBar snap={snap} live={live} onError={onError} />

      {banner && (
        <div className="flex-none border-b border-line bg-well px-4 py-2">
          <p className="font-mono text-xs text-danger">{banner}</p>
        </div>
      )}

      <main className="grid min-h-0 flex-1 grid-cols-[15rem_1fr_15rem] gap-3 p-3">
        <div className="min-h-0 overflow-y-auto">
          <Dro snap={snap} />
        </div>

        <MachineCanvas snap={snap} />

        <div className="min-h-0 overflow-y-auto">
          <JogPanel snap={snap} onError={onError} />
        </div>
      </main>

      <div className="h-56 flex-none px-3 pb-3">
        <Console
          lines={lines}
          connected={snap.conn.connected}
          onError={onError}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Verify it typechecks and builds**

Run: `npx tsc --noEmit && npm run build`
Expected: both succeed

- [ ] **Step 5: Commit**

```bash
git add components/workspace/JogPanel.tsx components/workspace/MachineCanvas.tsx app/page.tsx
git commit -m "feat(ui): jog panel, machine canvas, assembled workspace"
```

---

## Task 15: End-to-end verification and the hardware checklist

**Files:**
- Create: `server/tests/test_e2e.py`, `server/sim/serve_sim.py`, `docs/HARDWARE_CHECKLIST.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything
- Produces: `serve_sim.py` — a standalone runner that lets the real UI drive the simulator

- [ ] **Step 1: Write the end-to-end tests**

Create `server/tests/test_e2e.py`:

```python
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from server.main import app, session
from server.sim.grbl_sim import GrblSim


@pytest.fixture()
def rig():
    sim = GrblSim()
    app.state.transport_factory = lambda port, baud: sim
    with TestClient(app) as client:
        client.post("/api/connect", json={"port": "COM-SIM", "baud": 115200})
        yield client, sim
    session.disconnect()
    app.state.transport_factory = None


def settle(sim: GrblSim, seconds: float = 1.5) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        sim.tick(0.02)
        time.sleep(0.01)


def test_connect_then_jog_moves_the_machine(rig):
    client, sim = rig
    client.post("/api/jog", json={"axis": "X", "distance": 10, "feed": 1000})
    settle(sim)
    assert abs(sim.pos[0] - 10.0) < 0.01
    assert abs(client.get("/api/state").json()["mpos"][0] - 10.0) < 0.01


def test_jogging_every_axis(rig):
    client, sim = rig
    for axis, index in (("X", 0), ("Y", 1), ("Z", 2)):
        client.post("/api/jog", json={"axis": axis, "distance": 2, "feed": 1000})
        settle(sim, 0.8)
        assert sim.pos[index] > 1.9


def test_zero_makes_the_work_readout_read_zero(rig):
    client, sim = rig
    client.post("/api/jog", json={"axis": "X", "distance": 25, "feed": 2000})
    settle(sim)
    client.post("/api/zero", json={"axes": "XYZ"})
    settle(sim, 0.8)
    snap = client.get("/api/state").json()
    assert abs(snap["wpos"][0]) < 0.01
    assert abs(snap["mpos"][0] - 25.0) < 0.01


def test_estop_leaves_the_machine_in_alarm(rig):
    client, sim = rig
    client.post("/api/jog", json={"axis": "X", "distance": 100, "feed": 500})
    settle(sim, 0.3)
    client.post("/api/estop")
    settle(sim, 0.5)
    assert sim.state == "Alarm"
    assert client.get("/api/state").json()["state"] == "Alarm"


def test_unlock_recovers_from_alarm(rig):
    client, sim = rig
    client.post("/api/estop")
    settle(sim, 0.5)
    client.post("/api/unlock")
    settle(sim, 0.8)
    assert client.get("/api/state").json()["state"] == "Idle"


def test_out_of_envelope_jog_never_reaches_the_controller(rig):
    client, sim = rig
    before = list(sim.pos)
    r = client.post("/api/jog", json={"axis": "X", "distance": 500, "feed": 1000})
    assert r.status_code == 400
    settle(sim, 0.3)
    assert sim.pos == before
    assert sim.state != "Alarm"   # refused by us, so the controller never alarmed


def test_pulling_the_cable_is_detected(rig):
    client, sim = rig
    sim.stop_answering_status = True
    deadline = time.time() + 4.0
    while time.time() < deadline:
        if not client.get("/api/state").json()["conn"]["connected"]:
            break
        time.sleep(0.05)
    snap = client.get("/api/state").json()
    assert snap["conn"]["connected"] is False
    assert "status polls" in (snap["error"] or "")


def test_console_records_the_whole_exchange(rig):
    client, sim = rig
    client.post("/api/command", json={"line": "$$"})
    settle(sim, 0.5)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        console = ws.receive_json()["data"]
    texts = [c["text"] for c in console]
    assert any(t == "$$" for t in texts)
    assert any(t.startswith("$100=") for t in texts)
```

- [ ] **Step 2: Run them**

Run: `python -m pytest server/tests/test_e2e.py -v`
Expected: 8 passed

- [ ] **Step 3: Write the standalone simulator runner**

Create `server/sim/serve_sim.py`:

```python
"""Run the workbench server against the simulator, with no hardware attached.

    python -m server.sim.serve_sim

Then open http://localhost:3000 and connect to the port named SIM. Everything
in the UI works: jog, zero, home, console, E-stop.
"""
from __future__ import annotations

import threading
import time

import uvicorn

from server.main import app
from server.sim.grbl_sim import GrblSim

sim = GrblSim()


def _clock() -> None:
    """Advance the simulated machine in real time."""
    last = time.time()
    while True:
        now = time.time()
        sim.tick(now - last)
        last = now
        time.sleep(0.01)


def main() -> None:
    app.state.transport_factory = lambda port, baud: sim
    threading.Thread(target=_clock, daemon=True).start()
    print("Simulator running. Connect to the port named 'SIM' in the UI.")
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
```

Also make the port list offer it. In `server/main.py`, change `read_ports` to append a simulated entry when the transport factory is overridden:

```python
@app.get("/api/ports")
def read_ports() -> dict:
    try:
        found = ports_mod.list_ports()
    except Exception:
        found = []
    if app.state.transport_factory is not None:
        found = [
            ports_mod.PortInfo("SIM", "GRBL simulator", None, None, True, "simulator"),
            *found,
        ]
    return {
        "ports": [asdict(p) for p in found],
        "bauds": ports_mod.BAUD_RATES,
        "suggested": ports_mod.autoselect(found),
    }
```

- [ ] **Step 4: Drive the real UI against the simulator**

In two terminals:

```bash
python -m server.sim.serve_sim
```

```bash
npm run dev
```

Open http://localhost:3000 and confirm each of these by hand:

- [ ] The port dropdown lists `SIM — simulator` and it is pre-selected
- [ ] **Connect** turns the light green and shows `Grbl 1.1h`
- [ ] The state badge reads `Idle`
- [ ] `X+` at step 10 moves the crosshair right and the DRO X to 10.000
- [ ] `Y+`, `Y−`, `X−`, `Z+`, `Z−` all move the right axis in the right direction
- [ ] Changing step to 100 and pressing `X+` three times gets refused at the limit, with the reason shown in the banner
- [ ] `ZERO ALL` sets the work readout to zeros while the machine readout keeps its value
- [ ] The work/machine toggle switches between the two
- [ ] Typing `$$` in the console prints the settings table
- [ ] `E-Stop` puts the state badge into `Alarm` and the unlock button appears
- [ ] `Unlock ($X)` returns the badge to `Idle`
- [ ] Reloading the browser restores the console backlog and the current position
- [ ] Stopping the Python process turns the light grey within ~2 s

- [ ] **Step 5: Write the hardware checklist**

Create `docs/HARDWARE_CHECKLIST.md`:

```markdown
# Bench checklist — slice 1

Run this once against the real controller. Everything here already passes
against the simulator, so a failure means a hardware or firmware difference
worth writing down.

## Before plugging in

- [ ] The pen is raised or removed. Nothing below can crash a pen if it is not there.
- [ ] The bed is clear.

## Connection

- [ ] `python -m uvicorn server.main:app --port 8000` starts without error
- [ ] `npm run dev`, then open http://localhost:3000
- [ ] The port dropdown lists the controller, labelled with its chip (CH340, CP2102, …)
- [ ] It is pre-selected automatically when it is the only candidate
- [ ] **Connect** at 115200 reports the firmware banner
- [ ] The reported version matches what UGS shows for the same board
- [ ] Connecting at the wrong baud (9600) fails within a few seconds with a readable message, not a hang

## Readout

- [ ] The state badge reads `Idle` (or `Alarm` if homing is enforced)
- [ ] Moving an axis by hand, if the motors are disengaged, changes nothing — position comes from the controller
- [ ] The DRO shows three axes to 3 decimal places

## Jog — do this at step 1 mm first

- [ ] `X+` moves the carriage in the direction you call +X. If it moves the wrong way, that is a `$3` direction-mask issue in firmware, not an app bug.
- [ ] `X−`, `Y+`, `Y−` each move the right way
- [ ] `Z+` raises the pen carrier, `Z−` lowers it
- [ ] For a servo pen on FluidNC: `Z+` and `Z−` visibly lift and drop the pen
- [ ] Step 0.1 mm produces a small but visible move
- [ ] Step 10 mm produces a move you can measure — check it with a rule; a 10 mm command that measures 8 mm means `$100`/`$101` steps-per-mm need calibrating
- [ ] Feed selector changes how fast the jog runs

## Limits and safety

- [ ] Jogging past the configured travel is refused in the UI, and the machine does not move
- [ ] The refusal names the axis and the distance
- [ ] **E-Stop** stops motion immediately, mid-jog
- [ ] After E-Stop the badge reads `Alarm` and `Unlock ($X)` clears it
- [ ] Unplugging the USB cable mid-session turns the light grey within ~2 s and says the connection was lost

## Console

- [ ] `$$` prints the settings table
- [ ] `$I` prints build info
- [ ] A malformed command (`$nonsense`) prints a readable error, not a bare code
- [ ] Up-arrow recalls the previous command

## Notes

Record anything that differed from the simulator here — those differences are
what the next slice has to account for.
```

- [ ] **Step 6: Update the README**

Replace the "Stack", "Run", "Pages", and "How it connects" sections of `README.md` with:

```markdown
## Stack
- Next.js 15 (App Router) + React 19 + TypeScript
- Tailwind CSS v4 ("engineering instrument" theme)
- Python 3.12 + FastAPI + pyserial, talking GRBL 1.1 / FluidNC over USB
- SQLite for machine profiles. No accounts, no MongoDB.

## Run

```bash
pip install -r server/requirements.txt
npm install
npm run dev:all          # API on :8000, UI on :3000
```

No hardware? Run the simulator instead of the API:

```bash
python -m server.sim.serve_sim   # then npm run dev, and connect to port "SIM"
```

## Pages
| Route | What it is |
|-------|-----------|
| `/` | **Workspace** — connect, jog, live position, console |
| `/projects` | Board projects (arrives with the CAM subsystem) |
| `/settings` | Machine profiles (arrives with the settings subsystem) |
| `/history` | Job history (arrives with file streaming) |

## How it connects
The Python server owns the serial port on its own thread, streams with GRBL's
character-counting flow control, and polls `?` at 5 Hz. All live state lives in
Python and reaches the browser as one snapshot over one WebSocket, so the
readout, the state badge, and the canvas cannot disagree. Commands go back as
REST, which is what lets a refused jog return a real reason.

Emitted G-code is plain GRBL 1.1 and loads unmodified in Universal Gcode Sender.
```

- [ ] **Step 7: Run the full suite one last time**

Run: `python -m pytest server/tests/ -v && npx tsc --noEmit && npm run build`
Expected: 118 passed, no type errors, build succeeds

- [ ] **Step 8: Commit**

```bash
git add server/tests/test_e2e.py server/sim/serve_sim.py server/main.py docs/HARDWARE_CHECKLIST.md README.md
git commit -m "test: end-to-end coverage against the simulator, plus a bench checklist"
```

---

## Self-Review Notes

**Spec coverage.** Every section of the spec that falls inside slice 1 has a task: teardown and route tree (Task 1), status parsing with WCO carry-over (Task 2), the realtime/line split and message tables (Task 3), the simulator with RX-buffer and planner modelling (Task 4), the transport and event dispatch (Task 5), character counting and the poll watchdog (Task 6), port identification (Task 7), profiles including `pen_mode` (Task 8), the jog clamp (Task 9), the snapshot schema and derived `pen` (Task 10), REST plus WebSocket (Task 11), and the workspace UI (Tasks 12–14).

**Spec items deliberately deferred, as slice 1 defines:** character-counting streaming *of a file* (the mechanism is built and tested in Task 6, but nothing loads a `.nc` yet), pause/resume/stop job semantics, job pre-flight bounding-box checks, the start confirmation gate, ETA, job history, and the calibration wizard. `snapshot()["job"]` is `None` throughout and the field exists so the next slice fills it without reshaping the contract.

**One spec detail intentionally simplified:** section 5.4 describes Stop as feed-hold → flush → soft reset → `$X` → restore WCO. Slice 1 has no job to stop, so only E-stop (bare soft reset) is implemented. The full Stop sequence belongs with file streaming.
