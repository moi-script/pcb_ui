# Real Print Streaming (Web → ESP32 → Arduino) — Design

Date: 2026-07-25
Repos: `pcb_ui` (Next.js frontend), `pcb_reader` (FastAPI backend + firmware)

## Goal

Replace the simulated `PlotControl` streamer with a real path: the user clicks
"Start printing", the web app tells the FastAPI backend to send the board's
G-code to the paired ESP32 over HTTP; the ESP32 relays it line-by-line to an
Arduino running GRBL over serial, using the standard `ok`/`error` handshake. The
web page shows live progress by polling the machine status.

## Architecture

```
PlotControl (web)  →  FastAPI (server.py)  →  ESP32 bridge (.ino)  →  Arduino (GRBL)
  POST /print ─────────▶ load board.gcode ── HTTP POST /print ──▶ buffer + stream ──serial──▶ GRBL
  GET  /print/status/{email} ─▶ proxy GET /status ──────────────▶ {state,line,total}
  POST /print/stop ──────────▶ proxy POST /stop ────────────────▶ abort
```

## Decisions (approved)

- Data path: **Web → Python backend → ESP32** (not browser-direct). Avoids
  CORS / mixed-content; reuses the paired-device record.
- Arduino runs stock **GRBL** (flashed by the user, not generated here). ESP32
  streams one line, waits for `ok`/`error`, then the next.
- **Live progress** via status polling, reusing the existing progress-bar UI.
- WiFi credentials are placeholder `#define`s in the firmware.

## Components

### 1. ESP32 firmware — `pcb_reader/firmware/esp32_bridge/esp32_bridge.ino`

- WiFi station connect; SSID/pass as `#define` placeholders.
- `WebServer` on port 80:
  - `POST /print` — body is raw G-code. Header `X-Check: 1` → send GRBL `$C`
    (validate only, no motion) before streaming. Buffers the job and returns
    `202` immediately; does NOT stream inside the handler.
  - `GET /status` — JSON `{state, line, total}` where state ∈
    `idle|checking|printing|done|error|stopped`.
  - `POST /stop` — abort the current job.
  - `GET /` — health JSON.
- Non-blocking streamer in `loop()`: feed one line to `Serial2` (GPIO16 RX /
  GPIO17 TX, 115200), wait for `ok`/`error` with timeout, advance `line`. On
  `error` or timeout → `state=error`, stop. On end → `state=done`.
- Also mirrors ESP32 boot: wake GRBL, discard banner, reset input buffer.
- A short `pcb_reader/firmware/README.md`: wiring (ESP32 Serial2 ↔ Arduino
  RX/TX, common ground, level note), flashing, filling in WiFi creds, and that
  the Arduino must be flashed with stock GRBL.

### 2. Backend relay — `pcb_reader/server.py` (no new pip deps; stdlib urllib)

- Helper `esp_base(device)` → `os.environ.get("ESP_BASE_URL")` or
  `http://{device['port']}`.
- `POST /print` `{email, board_id, check?}`:
  - find device for email (400 if none), load board by id (404 if missing,
    400 if it has no `gcode`),
  - POST gcode to `<esp>/print` with `X-Check` header when `check`,
  - 502 if the ESP is unreachable/times out; else `{ok, total}`.
- `GET /print/status/{email}` → find device, proxy `<esp>/status`; 502 on
  failure. Returns `{state, line, total}`.
- `POST /print/stop` `{email}` → proxy `<esp>/stop`.
- Short timeouts (~4s) so a dead ESP fails fast.

### 3. Frontend — `pcb_ui/lib/api.ts` + `app/dashboard/projects/[id]/page.tsx`

- api: `startPrint(email, boardId, check)`, `printStatus(email)`,
  `stopPrint(email)`.
- Rewrite `PlotControl`: remove the fake `setInterval`. On plot, call
  `startPrint`; then poll `printStatus` every ~500ms and drive the existing bar
  from `{line,total,state}`. Dry-check toggle → `check:true`; on `checking`→done
  offer "stream for real" (`check:false`). Stop → `stopPrint`. Map ESP/backend
  errors to the existing error phase with a readable message. Requires the
  signed-in `email` (from `useAuth`) — pass it into `PlotControl`.

### 4. Testability — `pcb_reader/firmware/esp_mock.py` (stdlib http.server)

- Emulates `/print` (accepts gcode, starts a timed fake stream), `/status`,
  `/stop`, `/`. Advances `line` on a timer to mimic GRBL pacing.
- Run it, set `ESP_BASE_URL=http://localhost:8770`, and the full
  web→backend→(mock)ESP chain is exercisable without hardware.

## Non-goals

- No GRBL generation (user flashes it).
- No auth/ownership enforcement (consistent with the rest of the app).
- No changes to the G-code generation pipeline.

## Git plan

One commit per component (firmware, backend, frontend, mock) in the repo it
touches; push to `origin/main` after each. Order: firmware → mock → backend →
frontend, so the chain can be smoke-tested against the mock before finishing.
