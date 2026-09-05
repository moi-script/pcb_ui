# USB Serial Machine Control — Design

Date: 2026-09-06
Repo: `pcb_ui` — `serverside/` (FastAPI backend), `userpage/` (Next.js frontend)
Source of the ported code (same repo, separate worktree branch):
`machine-control-slice-1/server/`

## Goal

Open the web app, plug an Arduino running GRBL into the PC over an FTDI/USB
cable, and plot — the way Universal Gcode Sender works. No device ID, no
pairing handshake, no ESP32 on the network.

Today `POST /print` forwards a board's G-code over HTTP to an ESP32 bridge at
the paired device's IP address (`esp_base()`, `serverside/server.py:359`). The
machine has to be on the network, running the bridge firmware, and paired to
an account by ID before anything can move. `serverside/pcb_send.py` can already
stream over USB, but it is a blocking CLI script that nothing in the API
imports.

This replaces the network transport with a direct USB serial connection owned
by the backend, and adds the machine controls — jog, home, zero — without which
you cannot set a work origin and therefore cannot place a drawing on a board.

## The key fact this rests on

The backend runs on the same machine as the browser. A browser tab cannot open
a COM port, but `localhost:8000` can. So "plug in the cable, pick the port,
connect, run" is a plain backend feature; the frontend only ever speaks HTTP
and WebSocket.

```
Chrome (localhost:3000)
   │  REST for commands, WebSocket for live state
   ▼
FastAPI (localhost:8000) ── serverside/machine.py: ONE process-wide Session
   │                         owns the port, the streamer thread, the job
   ▼
pyserial ──USB / FTDI──▶ Arduino running GRBL 1.1
```

## Decisions

- **One process-wide session, not one per account.** There is one physical
  machine on one PC. Keying the connection by user would model a fleet that
  does not exist and would let two browser tabs believe they each own the port.
  The session is a module-level singleton; accounts remain only for boards.

- **Port the proven stack, do not rewrite it.**
  `machine-control-slice-1/server/` already contains a tested GRBL 1.1
  implementation: protocol codec, a port-owning streamer thread with
  character-counting flow control, machine state, and — most valuable — a GRBL
  *simulator* that models the RX buffer and planner queue, plus ~2,100 lines of
  tests. Rewriting that against `pcb_send.py`'s simpler send-and-wait handshake
  would re-solve solved problems and lose the ability to develop with no
  hardware attached.

- **The simulator is a first-class port, not a test fixture.** With
  `TRACEWORKS_SIM=1` the port list carries a `SIM` entry alongside the real
  ones. The whole feature — connect, jog, zero, run a real board's G-code,
  watch the visualizer follow — is exercisable with nothing plugged in. This is
  how the feature gets built and verified.

- **Delete the ESP32 path rather than keep both.** Two transports means two
  code paths, two failure modes, and two things to explain. The bridge
  endpoints, `esp_base()`, `esp_request()`, and the `devices` collection go.
  `serverside/pcb_send.py` survives untouched as a documented standalone CLI,
  but nothing in the API imports it.

- **Pairing is replaced by remembering, not by nothing.** A new `machines`
  collection stores `{user_email, last_port, last_baud}` — a convenience crumb
  so Connect is one click next session. It carries no identity and no
  authority: it cannot make a port exist, and connecting never requires it.

- **Progress is measured in acknowledged lines, position in `WPos`.** GRBL
  acknowledges a line when it has *parsed and queued* it, not when it has
  executed it, so the acked index runs ahead of the pen. Drawing the toolpath
  from the acked index alone would show ink laid down before the machine got
  there. So: acked index drives which segments are marked complete, the
  reported `WPos` drives where the pen model sits, and the two are presented as
  what they are — "sent" and "where it is".

- **Connecting resets the Arduino, so work zero is lost every session.**
  Opening the port toggles DTR and GRBL reboots. This is normal (UGS behaves
  the same way) but it means zero must be set *after* connecting, every time.
  The Machine page states this rather than letting it be discovered by plotting
  into the table.

## Backend

### New package: `serverside/grbl/`

Ported near-verbatim from `machine-control-slice-1/server/`:

| New path | From | What it is |
|---|---|---|
| `grbl/ports.py` | `grbl_serial/ports.py` | Port enumeration; VID→chip names so the UI says "COM5 — CH340"; `autoselect()` returns a port only when exactly one candidate exists, because guessing between two plausible boards is worse than asking |
| `grbl/protocol.py` | `grbl_serial/grbl.py` | GRBL 1.1 codec — status reports, replies, realtime bytes. Pure functions, no I/O |
| `grbl/streamer.py` | `grbl_serial/streamer.py` | The thread that owns the transport: character-counting flow control, event stream. Takes a `Transport` Protocol, not a pyserial object, so the simulator substitutes with no mocking |
| `grbl/state.py`, `grbl/limits.py` | `machine/state.py`, `machine/limits.py` | Machine state model and travel limits |
| `grbl/sim.py` | `sim/grbl_sim.py` | The GRBL simulator |

The rename `grbl.py` → `protocol.py` avoids `grbl.grbl`. Imports are rewritten
accordingly; nothing else about these files changes.

### New module: `serverside/machine.py`

The `Session` singleton, lifted from `machine-control-slice-1/server/main.py`'s
`Session` class (lines 104–534) together with `SerialTransport` and the
position-taint mechanism. That mechanism is subtle and is ported deliberately:
after a soft reset or a cancelled jog the machine stops at a point nobody
knows, and live `mpos` has not caught up — so the session marks the position
*uncertain* and refuses moves that depend on it until a status report proves
the machine is idle with nothing of ours outstanding.

**New code, the one thing slice-1 lacks — the job runner.** A `Job` owned by
the session:

- holds the board's G-code lines (comments and blanks stripped, as
  `pcb_send.load_lines` does),
- feeds them to the streamer under its existing flow control,
- tracks `sent`, `acked`, and `total` line counts,
- supports pause (feed hold, stop feeding), resume, and stop (feed hold, flush
  the queue, lift the pen, end the job),
- aborts on the first `error:N`, reporting the offending line number and text,
- ends cleanly if the link drops mid-job, leaving the failure visible rather
  than silently stopping.

Only one job runs at a time; `POST /machine/run` while a job is active is a
409.

### Endpoints on `serverside/server.py`

```
GET  /machine/ports        → {ports: [{device, description, chip,
                                       likely_controller}], suggested}
POST /machine/connect      {port, baud}   → state
POST /machine/disconnect
GET  /machine/state        → {connected, port, baud, grbl_state, wpos, mpos,
                              position_certain, job}
WS   /machine/ws           → the same state pushed at ~5–10 Hz, plus job
                             progress and console lines

POST /machine/jog          {axis, delta, feed}
POST /machine/jog/cancel
POST /machine/home
POST /machine/unlock
POST /machine/zero         {axes}
POST /machine/command      {line}
POST /machine/estop

POST /machine/run          {board_id, check}
POST /machine/pause
POST /machine/resume
POST /machine/stop
```

The first block through `/machine/estop` is ported near-verbatim from slice-1's
`/api/*` handlers. The `/machine/run|pause|resume|stop` block is new.

`check: true` sends GRBL's `$C` before the job and toggles it off after: every
line is parsed and validated, no motor moves. This preserves the dry-check
toggle the board page already has.

`POST /machine/estop` sends the realtime soft-reset byte `0x18`, which bypasses
the line queue entirely — the only thing that stops a machine promptly — and
marks the position uncertain. It must return instantly and must never wait on
the link.

### Removed

From `serverside/server.py`: `esp_base()`, `esp_request()`, `ESP_TIMEOUT`,
`POST /print`, `GET /print/status/{email}`, `POST /print/stop`,
`GET /devices/{email}`, `POST /devices/pair`, `POST /devices/unpair`,
`PATCH /devices/{email}`, `default_device()`, `out_device()`, `_device_for()`,
the `PrintJob` and `RenameDevice` models, and the `devices` collection in `db.py`. The
`ESP_BASE_URL` environment variable goes with them.

`serverside/firmware/` — the ESP32 bridge sketch, its README, and
`esp_mock.py` — is **left on disk, unused**. It is real firmware work and
deleting it is not this change's call to make; its README gains a line saying
the API no longer talks to it. Removing it is a separate decision.

### Documentation

`README.md`, `RUNNING.md`, `serverside/README.md`, `serverside/DOCS.md`, and
`serverside/HARDWARE.md` all describe pairing by device ID and streaming to a
networked ESP32. Each is updated to describe the USB flow, including the
`TRACEWORKS_SIM=1` no-hardware path. This is part of the change, not a
follow-up: documentation that describes a transport the code no longer has is
worse than none.

## Frontend

- **`lib/machine.ts`** — a `useMachine()` hook owning the WebSocket with
  auto-reconnect, exposing connection state, DRO position, GRBL state, and job
  progress. Single source of truth; pages subscribe.

- **`lib/api.ts`** — `pairDevice`, `unpair`, `getDevice`, `renameDevice`,
  `startPrint`, `printStatus`, `stopPrint` are replaced by the `/machine/*`
  calls.

- **`/connect`** — rewritten as the machine connect page: the port list with
  chip names and a "likely controller" mark, pre-selected when exactly one
  candidate is present, a baud dropdown defaulting to 115200, and Connect. The
  device-ID field and the FluidNC handshake animation are deleted. An empty
  list says "no serial ports found — is the cable plugged in?" rather than
  showing an empty box.

- **`/dashboard/device`** → the Machine page: connection status and port, a DRO
  showing live X/Y/Z, a jog pad (axis buttons with a step-size selector), Home,
  Unlock, Zero X / Y / Z / All, a prominent E-stop, and a console listing sent
  lines and controller replies. Carries the note that connecting resets the
  board and clears work zero.

- **Board detail page** — the existing "Stream to device" panel keeps its shape
  and its dry-check toggle but calls `/machine/run` and reads progress from the
  WebSocket instead of polling `/print/status/{email}`. It refuses to start
  when no machine is connected, linking to `/connect`.

- **`components/GcodeVisualizer.tsx`** gains two optional props:
  `liveIndex` (segments up to the last acknowledged line render as drawn, the
  rest as pending) and `penPos` (the pen model sits at the reported `WPos`).
  When both are absent the component behaves exactly as it does today, scrub
  timeline included — no existing usage changes.

## Testing

- Slice-1's ported tests (`test_ports`, `test_grbl_status`,
  `test_grbl_commands`, `test_grbl_sim`, `test_streamer_flow`,
  `test_streamer_events`, `test_state`, `test_limits`) run under
  `serverside/pytest.ini` with imports rewritten and nothing else changed.
  `test_api` and `test_e2e` are adapted to the `/machine/*` routes.
- New tests for the job runner, all against the simulator: a full board's
  G-code streams to completion with correct acked counts; flow control holds
  under backpressure; pause stops feeding and resume continues from the right
  line; stop mid-job flushes and ends; an `error:N` mid-job aborts and reports
  the line number; a disconnect mid-job ends the job as failed.
- New tests for check mode: `$C` is sent before and toggled off after, and a
  job that errors in check mode still leaves check mode off.

## Out of scope

- Multiple simultaneous machines, or any machine not on this PC.
- Restoring the ESP32/WiFi transport. If wireless plotting is wanted later it
  should come back as a `Transport` implementation behind the same session, not
  as a parallel print path.
- Real authentication. The prototype's account handling is unchanged and still
  trusts the email passed by the client (see the README caveat).
- Homing-cycle configuration, soft limits, and machine profiles beyond what
  `grbl/limits.py` already carries.
