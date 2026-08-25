# Single-User CNC PCB Workspace — Design

**Date:** 2026-08-25
**Status:** Approved for planning
**Supersedes:** the multi-tenant TraceWorks product described in `README.md`

---

## 1. What changes and why

`pcb_ui` today is a multi-tenant web product: a marketing landing page, signup
and login backed by MongoDB, device *pairing by ID*, and G-code streamed to a
FluidNC controller over WiFi through an ESP32 bridge. Every request carries an
email address.

None of that serves the actual use: **one person, at one bench, with one
machine plugged into one USB port.** Accounts, pairing, and the WiFi bridge are
ceremony around a cable. This design replaces the product with a workbench
application — a G-code sender in the mould of Universal Gcode Sender, built
around the PCB pen-plotting pipeline that already exists.

Three subsystems are in scope overall. **This spec covers subsystem 1 only.**

| # | Subsystem | Covers | Status |
|---|-----------|--------|--------|
| 1 | **Machine control core** | serial/COM, GRBL dialect, jog, live status, streaming, E-stop, soft limits, console | **this spec** |
| 2 | CAM / G-code generation | file upload (PDF/SVG/DXF/Gerber/image), traces + holes + outline toolpaths, preview | later spec |
| 3 | Settings, calibration, projects | machine profiles, steps/mm, calibration wizard, job history, save/load | later spec |

Subsystem 1 is the spine — nothing else is testable without it. The single-user
teardown rides along with it, because the teardown is what makes room for the
workspace UI.

---

## 2. Existing assets

### `C:\pcb_ui` (this repo)

Next.js 15 / React 19 / Tailwind v4, ~2,200 lines of TypeScript. The valuable
part is `app/globals.css`: an "engineering instrument" theme — copper accent on
warm paper, flat surfaces, mono technical labels, engineering-drawing corner
ticks. **The theme is preserved verbatim.** `components/PcbBoard.tsx` renders
board tracks as SVG in board coordinates and becomes the live toolpath canvas.

### `C:\cnc_line_backend\cnc_1line_tracer-main`

A working offline CAM pipeline in Python: image prep, centerline skeleton
tracing, simplify, centripetal Catmull-Rom spline, greedy stroke ordering, and
G-code emission. 92 passing tests. `tools/pen_post.py` already supports
`--pen-mode z|servo|spindle` with `--servo-up`/`--servo-down`/`--z-delay`.
Feeds subsystem 2; only its G-code emitter conventions matter here.

### `C:\pcb_reader`

FastAPI + MongoDB service the current UI talks to. `pcb_read.py` parses KiCad
boards; `pcb_gcode.py` emits pen-plotter G-code; `pcb_send.py` streams over
serial using simple send-response. **Its `HARDWARE.md` settles the Z question**
(section 4.1). Left on disk as reference; `pcb_read.py` is vendored when
subsystem 2 lands. Not deleted by this work.

---

## 3. Architecture

One local FastAPI process, `server/`, owns serial, CAM, and storage. Next.js is
a pure client. All live state lives in Python, pushed over a single WebSocket.

```
Browser (Next.js)                    server/ (FastAPI, one process)
  |-- REST  ---- commands -------->    main.py
  \-- WS    <--- state @10Hz ----->      |-- serial/   ports . grbl . streamer   [pyserial]
                                         |-- machine/  state . limits . jobs     [pure logic]
                                         |-- cam/      tracer . kicad . pipeline [subprocess]
                                         |-- store/    SQLite                    [no users table]
                                         \-- sim/      grbl_sim
                                                       |
                                                    USB serial
                                                       v
                                          GRBL 1.1 (Uno/Nano) or FluidNC (ESP32)
```

**Rationale.** The send-loop cannot live in a browser tab — a refresh or a
closed tab must not abort a running job. Keeping *all* live state behind one
WebSocket snapshot means the DRO, the real-time toolpath, and the progress bar
can never disagree, because they read the same object. And it is one thing to
run.

**Hedge borrowed from a two-process design:** CAM runs in a worker subprocess so
a slow or crashing trace cannot stall the send-loop. If the control layer later
needs to ship standalone, `serial/` + `machine/` lift out cleanly — they have no
dependency on `cam/` or the web layer.

### Module boundaries

| Module | Does | Depends on | Testable without hardware |
|---|---|---|---|
| `serial/grbl.py` | Protocol codec: bytes to dataclasses and back | nothing | yes — pure functions |
| `serial/streamer.py` | Owns the port, send-loop, `?` polling | `grbl`, pyserial | yes — via in-process sim |
| `serial/ports.py` | Enumerate/identify ports | pyserial | partially — mocked |
| `machine/state.py` | Authoritative live state | `grbl` | yes — event sequences |
| `machine/limits.py` | Envelope checks, pre-flight | `store` | yes — pure |
| `machine/jobs.py` | Run lifecycle, history | `store`, `streamer` | yes |
| `store/db.py` | SQLite: projects, profiles, history | nothing | yes |
| `sim/grbl_sim.py` | Fake controller | `grbl` | n/a — is the test rig |

Each answers: what does it do, how is it used, what does it depend on. `grbl.py`
in particular has no I/O whatsoever, which is why the subtle parts of the
protocol can be tested exhaustively.

---

## 4. Target hardware and G-code dialect

### 4.1 Z is a normal G-code axis

`pcb_reader/HARDWARE.md` shows how the bench machine handles pen lift: FluidNC
declares the `z` axis with a **`servo:` motor** (`min_pulse_us: 1000` = pen
down, `max_pulse_us: 2000` = pen up, over `max_travel_mm: 5`). The firmware maps
Z *position* onto servo pulse width. So the emitted G-code is plain:

```gcode
G21
G90
G0 Z5           ; pen up
G0 X94.48 Y64.38 F3000
G1 Z0 F3000     ; pen down
G1 X95.5912 Y65.4912 F800
```

**Consequence:** the servo is a firmware concern, not a sender concern. Z is
jogged, homed, and zeroed exactly like X and Y. The UI shows Z+/Z−/Zero Z. This
is also what a real Z stepper accepts, and what Universal Gcode Sender expects —
so one dialect satisfies every target.

### 4.2 Controller support

GRBL 1.1 and FluidNC are treated as one dialect. They agree on everything this
app uses: `?`, `$$`, `$I`, `$H`, `$X`, `$J=`, `$C`, `!`, `~`, `0x18`, `0x85`,
and the `<...|...>` status report format. Differences (RX buffer size, `$I`
banner text) are profile fields, not code branches.

A machine profile carries `pen_mode`:

| `pen_mode` | Pen up / down | Applies to |
|---|---|---|
| `z-axis` **(default)** | `G0 Z{pen_up_z}` / `G1 Z{pen_down_z} F{z_feed}` | FluidNC servo-as-Z; any real Z stepper |
| `servo-pwm` | `M3 S{servo_up}` / `M3 S{servo_down}` | Stock GRBL on an Uno with the servo on the spindle PWM pin (D11) |

`servo-pwm` exists because stock GRBL for the Uno has no servo motor type. It
maps onto `pen_post.py`'s existing `servo` mode, so subsystem 2 needs no new
emitter.

**Hard requirement:** every `.nc` file this app produces must load and run in
real Universal Gcode Sender unmodified. No proprietary extensions, no custom
comments that carry meaning.

---

## 5. The GRBL protocol layer (`server/serial/`)

### 5.1 `grbl.py` — pure codec

Parses GRBL 1.1 status reports into a `Status` dataclass:

```
<Idle|MPos:0.000,0.000,0.000|FS:0,0|WCO:0.000,0.000,0.000|Ov:100,100,100|Pn:XY>
```

Two details that are commonly got wrong and are explicitly handled:

1. **`MPos` vs `WPos`** depends on the `$10` status-report mask. The parser
   reads whichever is present and records which it was.
2. **`WCO` is only transmitted every ~10th report.** The work-coordinate offset
   MUST be cached across reports. Recomputing work position from a report that
   omitted `WCO` makes the DRO jump. The cache is invalidated by `G10`, `G92`,
   `$X`, and soft reset.

Machine states parse to an enum: `Idle`, `Run`, `Hold:0`, `Hold:1`, `Jog`,
`Alarm`, `Door`, `Check`, `Home`, `Sleep`. `error:N` and `ALARM:N` map to
GRBL's real message tables, so the console shows *"Soft limit error — machine
position exceeded"*, never a bare `error:15`.

### 5.2 The realtime / line-command split

This is the layer's core invariant. GRBL has two command channels; conflating
them is what makes senders deadlock on E-stop.

| Channel | Examples | Rules |
|---|---|---|
| **Realtime bytes** | `?` status, `!` feed hold, `~` resume, `0x18` soft reset, `0x85` jog cancel, `0x90`–`0x97` feed/rapid overrides | Single byte. Bypasses the planner queue. Returns **no** `ok`. **Never** counted against the RX buffer. |
| **Line commands** | `G0 X10`, `$$`, `$H`, `$X`, `$J=...`, `$C` | Newline-terminated. Returns exactly one `ok` or `error:N`. **Always** counted against the RX buffer. |

Enforced by API shape: `send_realtime(byte)` and `send_line(str)` are separate
functions with different return types. There is no code path that can send a
realtime byte through the line accounting.

### 5.3 `streamer.py` — character-counting send-loop

`pcb_reader/pcb_send.py` uses simple send-response: send one line, wait for
`ok`. Correct, but it drains GRBL's planner between every line. The tracer emits
segments around 0.19 mm, so a plot is thousands of very short moves and
send-response would make the pen visibly stutter.

**Therefore: character counting**, the same protocol UGS uses.

- Maintain a FIFO of the byte lengths of lines sent but not yet acknowledged.
- Send the next line while `sum(pending) + len(next_line) < rx_buffer`.
- On each `ok`, pop one length off the front of the FIFO.
- `rx_buffer` is a profile field: 128 for GRBL 1.1; FluidNC reports its own.

The loop runs on its own thread and owns the port exclusively. Everything else
reaches it through a command queue. It also polls `?` on a ~5 Hz timer — a
realtime byte, so it interleaves with streaming without disturbing buffer
accounting.

### 5.4 Control semantics

| Action | Sequence | Notes |
|---|---|---|
| **Pause** | `!` | Feed hold. Decelerates cleanly, position preserved. |
| **Resume** | `~` | |
| **Stop** | `!`, flush queue, `0x18` | Soft reset clears work offsets and may leave `Alarm`. The streamer then re-sends `$X` and restores the WCO rather than leaving a broken state. |
| **E-stop** | `0x18` immediately | No feed hold. Fastest halt, accepting lost position. Never queued, never behind a dialog. |
| **Jog** | `$J=G91 G21 {axis}{step} F{feed}` | Cancellable with `0x85`; does not alter parser modal state. |
| **Continuous jog** | long `$J=` on press, `0x85` on release | Prevents queueing dozens of moves during a button hold. |

### 5.5 `ports.py` — connection

Enumerates via pyserial `list_ports`, surfacing VID/PID to label CH340 and
CP2102 devices as likely Arduinos; auto-selects when exactly one candidate is
present. Connect toggles DTR, waits, reads the `Grbl 1.1h` banner, then issues
`$I` (build info) and `$$` (settings).

If no banner arrives within the timeout, the failure is reported as *"port
opened but the controller never identified itself — wrong baud rate, or not a
GRBL controller"*. It does not hang.

**Connection loss** is detected by either a `SerialException` on write, or three
consecutive `?` polls going unanswered for 500 ms each — a worst case of ~1.5 s,
inside the 2 s budget in section 10. Either one, during a job, immediately halts
streaming and marks the job `interrupted`.

---

## 6. Live state and the WebSocket contract

### 6.1 `machine/state.py`

One authoritative `MachineState`, mutated only by events from the streamer
thread (status parsed, `ok` received, line sent, error raised) and read by the
WS broadcaster. Pure logic: a test drives it with a list of fake events and
asserts the snapshot. No port, no simulator required.

### 6.2 Snapshot schema

```jsonc
{
  "conn":  { "connected": true, "port": "COM5", "baud": 115200,
             "firmware": "Grbl 1.1h", "profile": "Bench Plotter" },
  "state": "Run",
  "mpos":  [124.500, 62.858, 5.000],
  "wpos":  [ 24.500, 12.858, 5.000],
  "wco":   [100.000, 50.000, 0.000],
  "feed":  800,
  "spindle": 0,
  "ov":    { "feed": 100, "rapid": 100, "spindle": 100 },
  "pen":   "down",
  "alarm": null,
  "error": null,
  "job":   { "id": "abc", "name": "labExam", "state": "running",
             "line": 412, "total": 1180, "pct": 34.9,
             "elapsed_s": 74, "eta_s": 138,
             "current": "G1 X104.149 Y65.4912 F800" },
  "seq":   88213
}
```

**One snapshot, one truth.** The DRO, progress bar, toolpath cursor,
current-line readout, pen indicator, and connection light are all fields of this
object. They cannot drift apart because there is nothing else to read.

**`pen` is derived, not tracked** — live Z compared against the profile's
`pen_up_z`/`pen_down_z`. Correct for servo firmware and stepper Z alike, correct
when someone jogs Z by hand, and impossible to leave stale.

### 6.3 Transport

Single WebSocket at `/ws`. Full snapshot on connect, then a push on every state
change, rate-capped at 10 Hz, with a keepalive snapshot at ~1 Hz when nothing is
moving. Note the two rates are different things: `?` is polled at 5 Hz
(section 5.3), so position updates arrive at 5 Hz, while job line/progress
changes arrive as they happen — hence a 10 Hz cap rather than a 10 Hz timer.
`seq` lets the client discard out-of-order frames.

Console output (lines sent, `ok`s, errors, `[MSG:...]`) rides the **same** socket
as `{"type":"console", ...}` events so log entries stay correctly ordered
relative to state changes. The server keeps a 2,000-line ring buffer and replays
it on connect — refreshing the page does not lose the log.

Commands go the other way as **REST**: `POST /jog`, `/home`, `/zero`,
`/job/start`, `/job/pause`, `/job/resume`, `/job/stop`, `/estop`, `/connect`,
`/disconnect`, `/command`. Chosen over WS messages because they are
request/response and a refused jog must return a real HTTP 400 with a readable
reason. `/estop` and `/job/stop` jump the command queue.

The cost is accepted explicitly: a jog is two round-trips (POST, then the effect
appears in the next WS frame) rather than one.

### 6.4 `machine/limits.py` — safety

Three layers, cheapest first:

1. **Jog clamp.** Before any `$J=` is sent, the target is computed and checked
   against the profile's work envelope. Out of bounds is refused with
   *"X+10 would reach 312 mm, past the 300 mm limit"*. The button never sends a
   move that would alarm the controller.
2. **Job pre-flight.** On load, the G-code bounding box is checked against the
   envelope. An oversized file is rejected before anything moves, naming the
   offending extent.
3. **Confirmation gate.** Starting a job requires an explicit confirmation
   naming the file, its extent, the estimated time, and whether Z has been
   zeroed.

### 6.5 `machine/jobs.py`

Owns run lifecycle and writes history rows. **ETA is computed from remaining
path length divided by commanded feed**, not from line count — line count lies
badly when a file mixes long rapids with thousands of short segments.

---

## 7. Repository layout and teardown

```
pcb_ui/
  app/                    Next.js App Router — the client
  components/
  lib/
  server/                 the unified local backend
    main.py               app factory, REST routes, /ws
    serial/               ports.py  grbl.py  streamer.py
    machine/              state.py  limits.py  jobs.py
    cam/                  (scaffolded empty in slice 1; filled by subsystem 2)
    store/                db.py  models.py  migrations/
    sim/                  grbl_sim.py
    tests/
  docs/superpowers/specs/
```

### Deleted

Frontend: `app/page.tsx` (marketing landing), `app/login/`, `app/signup/`,
`app/connect/`, `components/AuthAside.tsx`, `components/MarketingNav.tsx`,
`components/Footer.tsx`, `lib/auth.tsx`, `lib/data.ts`, `board_raw.json`.

Backend concepts: the `users` and `devices` collections, every `/auth/*` and
`/devices/*` endpoint, the ESP32 WiFi bridge relay, and MongoDB itself.

### Kept

`app/globals.css` **verbatim** — the theme is the product's face and does not
change. `components/PcbBoard.tsx` (becomes the live canvas),
`components/Uploader.tsx`, `components/InlineEdit.tsx`, `components/Logo.tsx`,
`lib/board.ts`. `lib/api.ts` keeps its shape and loses every `email` parameter.

### Routes

| Route | Purpose |
|---|---|
| `/` | **Workspace** — canvas, DRO, jog, console, progress. No auth gate. |
| `/projects` | Local project list |
| `/projects/[id]` | Board detail, G-code editor, load into workspace |
| `/settings` | Machine profiles |
| `/settings/calibrate` | Calibration wizard |
| `/history` | Job log |

### Storage

SQLite replaces MongoDB. Tables: `profiles` (machine configurations),
`projects`, `jobs` (history). **No users table.** The active profile is a single
row. One `dev` script starts uvicorn and `next dev` together.

---

## 8. Workspace UI

`/` is a single full-height screen, three columns, no scrolling chrome — an
instrument panel rather than a document. Built from existing theme tokens:
`panel`/`ticked` for boxes, `tlabel` for mono uppercase captions, copper for the
drawing accent, `dot-live` for the connection light.

```
+- TOPBAR ----------------------------------------------------------------+
| COM5 . 115200 . Grbl 1.1h    [*] IDLE       Bench Plotter v    E-STOP    |
+--------------+---------------------------------------+------------------+
|  DRO         |                                       |  JOG             |
|  X   24.500  |         TOOLPATH CANVAS               |     Y+     Z+    |
|  Y   12.858  |   --- done (copper, solid)            |  X-  HOME  X+    |
|  Z    5.000  |   --- pending (faint)                 |     Y-     Z-    |
|  work v mach |   ... travel (dashed)                 |  step .1 1 10 100|
|  FEED  800   |   (+) live cursor                     |  feed -------o-- |
|  PEN   down  |                                       |  ZERO X Y Z ALL  |
+--------------+---------------------------------------+------------------+
| CONSOLE                                        | JOB                     |
| > $J=G91 X10 F1000                             | labExam.nc              |
| < ok                                           | ######----- 34.9%       |
| < <Run|MPos:124.500,62.858,5.000|FS:800,0>     | 412 / 1180  ETA 2:18    |
| [_________________________________] SEND       | PAUSE   STOP            |
+------------------------------------------------+-------------------------+
```

**Canvas.** `PcbBoard.tsx` grows three things: a dashed faint stroke style for
pen-up travel; a **progress split** — the toolpath drawn twice, once faint in
full and once in copper clipped to the completed portion via `stroke-dasharray`;
and a live crosshair at `wpos`. Completed fraction comes from the job snapshot,
so "completed and remaining toolpath" is one dash computation, not a second data
structure. The existing `trace-draw` keyframe already animates dash-offset.

**DRO.** IBM Plex Mono, tabular numerals, large. Work/machine toggle mirrors
UGS. Values not updated within 1 s render faint, so a stalled connection *looks*
stalled.

**Jog panel adapts to `pen_mode`.** Under `z-axis`, Z+/Z− step like X/Y. Under
`servo-pwm`, those buttons become **Pen Up** / **Pen Down** emitting `M3 S...`
and the step selector greys out for Z — a PWM servo has no jog distance. One
component, one profile field.

**E-stop** sits in the topbar, red, always reachable, never behind a dialog. It
posts directly and does not wait for the WebSocket to agree.

**Console** is a virtualized 2,000-line log with command history on up/down
arrows, colour coded with the theme's `signal`/`danger`/`muted`.

Routes other than `/` keep the current sidebar shell from `dashboard/layout.tsx`
minus the device card and sign-out. The workspace does not use that shell; it is
full-bleed.

---

## 9. Verification

### 9.1 `sim/grbl_sim.py`

A model of GRBL, not a stub. It:

- Emits the `Grbl 1.1h` banner on wake; answers `$I` and `$$` with a full
  settings table.
- Answers every line with `ok` or a **real** `error:N` — unknown words, bad
  numbers, `$J=` while in `Alarm`.
- Integrates simulated position over time at the commanded feed, so `?` returns
  a *moving* `MPos` and the DRO and cursor genuinely animate.
- Models the 128-byte RX buffer, withholding `ok`s when full. This is the only
  way to prove the character-counting streamer is correct rather than
  accidentally working.
- Implements transitions: `Idle` to `Run` to `Idle`, `!` to `Hold:0`, `~` to
  `Run`, `0x18` to banner plus `Alarm`, `$H` to `Home` to `Idle`, soft-limit to
  `Alarm:2`.
- Injects faults: drop the connection mid-job, stop answering `?`, return
  `error:9` on a chosen line.

Exposed two ways: **in-process** (tests hand the streamer a fake transport —
fast, deterministic, no OS involvement) and over a **virtual COM pair** via
com0com on Windows, so the full UI is clickable with nothing plugged in.
`pcb_reader/firmware/esp_mock.py` is the starting point.

### 9.2 Test layers

| Layer | Approach |
|---|---|
| `grbl.py` | Table-driven over recorded real report strings, including missing `WCO`, `Hold:1`, `Pn:XYZ`, `Ov:` present and absent |
| `streamer.py` | Buffer accounting against the in-process sim; the sim asserts in-flight bytes never exceed the buffer |
| `state.py` | Event-sequence tests |
| `limits.py` | Boundary tests on each axis |
| Full stack | connect, jog, assert position; load, stream, assert every line arrived in order |

TDD throughout. The protocol layer is precisely the kind of code where writing
the assertion first pays.

---

## 10. Scope of the first slice

**Connect + jog + console.** Done when, against both the simulator and the bench
machine:

1. `/` lists serial ports, labels the likely Arduino, connects at a chosen baud,
   and reports firmware version — or explains precisely why it could not.
2. The DRO tracks live position; work/machine toggle works; the state badge
   tracks `Idle`/`Jog`/`Alarm`.
3. Jog moves each axis by the selected step at the selected feed; press-and-hold
   jogs continuously and cancels cleanly on release; Home and Zero X/Y/Z/All
   work; out-of-envelope jogs are refused with a readable reason.
4. E-stop halts immediately from any state.
5. The console shows traffic in both directions and accepts typed commands.
6. Losing the port is detected and surfaced within ~2 s.

**Deliberately not in this slice**, stubbed behind it: file streaming, CAM and
upload, calibration wizard, job history. Their routes exist and say what is
coming. The data model already has room for them, so nothing needs reshaping
later.

**Order of work:** teardown and scaffold (mostly deletion), then `grbl.py` plus
the simulator together with tests, then `streamer.py`, then `state.py` and the
WebSocket, then the workspace UI.

---

## 11. Decisions on record

| Decision | Chosen | Rejected alternative and why |
|---|---|---|
| Serial ownership | Local Python agent | Web Serial (Chrome-only, job dies with the tab); desktop app (packaging Python on Windows) |
| Process topology | One FastAPI process | Split agent plus CAM service — deferred; a CAM subprocess gets most of the benefit |
| Backend consolidation | New unified local backend | Extending `pcb_reader` in place — keeps CAM split across repos |
| Teardown depth | Strip to a single workspace | Keeping the dashboard shell — stays document-centric, not machine-centric |
| Streaming protocol | Character counting | Send-response — stutters on 0.19 mm segments |
| Command transport | REST | WebSocket messages — no real error bodies for limit refusals |
| Pen control | Z as a normal axis, `servo-pwm` as a profile option | Spindle-PWM only — breaks UGS compatibility and Z jogging |
| Controller target | GRBL 1.1 and FluidNC as one dialect | Either alone |
| Verification | GRBL simulator | Hardware-only testing — integration bugs found late |
| Storage | SQLite | MongoDB — a server process for one user's local data |
