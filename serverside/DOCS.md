# PCB Plotter — Project Documentation (in progress)

> Living document. Status reflects what is **verified working** as of 2026-07-23.
> A one-layer PCB "drawer": take a KiCad board → extract copper traces →
> emit G-code → plot it on a pen-plotter / small CNC driven by a microcontroller.

---

## 1. Product goal

Let hobbyists and students turn a **simple, single-layer** KiCad PCB into a
physical drawing on paper/board using an inexpensive plotter. The emphasis is
**simplicity for mini projects**, not professional copper milling.

**Target user:** beginners / makers doing 1-layer mini projects. (Experienced
copper-milling users are already served by FlatCAM — not our audience.)

### Build vs. reuse decision

| Layer | Decision | Rationale |
|-------|----------|-----------|
| KiCad → coordinates → G-code | **Build** (done) | Thin; this is where our simplicity lives |
| Preview / verification UI | **Build** (in progress) | This is the product |
| Motion control on the chip | **Reuse GRBL** | Hard real-time work; never rebuild |
| Who owns the serial port | **The backend, not the browser** | A tab cannot open a COM port; the server runs on the same PC and can |

We do **not** ship on FlatCAM — it targets copper isolation milling (offset
toolpaths), while we draw trace centerlines with a pen, which is simpler. We
use FlatCAM only as a reference to validate our output.

---

## 2. Pipeline

Run the whole thing with `python main.py` (see §6), or each stage on its own.

```
labExam.kicad_pcb
      │  pcb_read.py      (s-expression parser → wiring_data)
      ▼
   wiring_data  [{type, net, start, end, width_mm, layer}, ...]
      │  pcb_gcode.py     (per-layer G-code, travel-optimized)
      ▼
   labExam.gcode
      │  pcb_gcode_preview.py   (visual sanity check — no hardware)
      ▼
   labExam_toolpath.png
      │  the web app: server.py -> job.py -> grbl/ -> USB serial
      │  (or the CLI: pcb_send.py)
      ▼
   Arduino running GRBL 1.1
      ▼
   physical plot

   main.py orchestrates all of the above, step by step.
```

---

## 3. Components (current state)

### `pcb_read.py` — parser ✅ working
- Custom s-expression parser (kiutils does **not** support KiCad 10; the file is
  version 20260206 with name-only nets `(net "…")`).
- Produces `wiring_data`: a list of dicts, coordinates in **mm**.
- Handles `segment` (tracks) and `via` (none in current files, code ready).
- Importable — printing is guarded by `if __name__ == "__main__"`.
- **Verified:** 359 elements parsed from `labExam.kicad_pcb`.

### `pcb_draw.py` — board preview ✅ working
- Renders traces with matplotlib, **colored by copper layer**
  (F.Cu = red, B.Cu = blue), Y inverted to match KiCad.
- Output: `labExam_wiring.png` (currently hardcoded name — see backlog).

### `pcb_gcode.py` — G-code exporter ✅ working
- Converts `wiring_data` → G-code (`G21`/`G90`, pen-up travel, pen-down draw).
- Config block at top: pen up/down Z, Z feed, feed rates, Y-flip, target layer,
  optimize.

Pen state is the **sign of Z**: negative is down, zero or above is up. That is
what `grbl_servo_z` tests (`z_steps < 0`), and every Z move is a timed `G1` at
`z_feed` so the servo has time to swing. See `tests/test_servo_gcode.py`.
- Default target layer **F.Cu** (single-layer plot).
- **Travel optimization** (`optimize_order`): greedy nearest-neighbour ordering
  with endpoint flipping. Header comment reports total pen-up travel.
  **Measured: 4200 mm → 332 mm (92% less pen-up travel)** on `labExam`.
- **Verified:** 143 F.Cu tracks → `labExam.gcode` (580 lines).

### `pcb_gcode_preview.py` — toolpath verification ✅ working
- Re-parses the `.gcode` and plots draw moves (solid red) vs travel (grey dash).
- Lets you confirm the path before sending to hardware.
- **Verified:** 143 draw / 144 travel moves → `labExam_toolpath.png`.

### `main.py` — pipeline runner ✅ working
- Runs parse → board preview → G-code → toolpath verify, step by step, with
  ordered status output and fail-fast on any non-zero exit.
- `python main.py` runs all; `python main.py --skip-preview` skips the two
  matplotlib image steps.

### `pcb_send.py` — serial G-code streamer (CLI only) ✅ working
- **Not imported by the API.** The web app has its own serial path — see
  `grbl/`, `machine.py` and `job.py` below — which is flow-controlled rather
  than send-and-wait, and which the UI drives. This stays as a standalone CLI
  for streaming a file with no server and no browser.
- Streams a `.gcode` file to GRBL over USB serial using the standard
  send-response (`ok`) handshake; reports any `error:N` replies.
- `--check` toggles firmware **Check Mode** (`$C`): validate every line with no
  motion. `--dry-run` parses the file without opening a port (no pyserial/HW
  needed). `--port`, `--baud`, `-v/--verbose` for the rest.
- Lazy `import serial`, clean errors on bad/missing port.
- **Verified (software paths):** dry-run, missing file, missing port, bad port
  all handled. Serial streaming itself needs real hardware to exercise.
- Requires `pyserial` (only when actually connecting).

### `grbl/` — the GRBL 1.1 stack ✅ working
- `protocol.py` — the codec: status reports, replies, realtime bytes. Pure
  functions, no I/O.
- `streamer.py` — the thread that owns the transport, with character-counting
  flow control: it tracks how many bytes of unacknowledged line are in the
  controller's RX buffer and never oversends. Takes a `Transport` protocol
  rather than a pyserial object, so the simulator substitutes with no mocking.
- `ports.py` — port enumeration, VID→chip names ("COM5 — CH340"). `autoselect`
  returns a port only when exactly one candidate exists: guessing between two
  plausible boards is worse than asking, and the wrong guess moves a machine.
- `state.py`, `limits.py` — the machine state model and travel envelope.
- `profile.py` — the machine's fixed characteristics, a frozen dataclass.
- `sim.py` — a model of a GRBL 1.1 controller, including its RX buffer and
  planner queue. Not a stub: it withholds `ok` under backpressure and asserts
  if the host oversends, which is the only way to prove the flow control is
  correct rather than accidentally working. `TRACEWORKS_SIM=1` exposes it as a
  port named `SIM`.

### `machine.py` — the one connection ✅ working
- A module-level `Session` singleton, not a per-account object: there is one
  physical plotter on the PC running this server.
- Owns the port, the streamer thread, and the current job; tracks whether the
  position is *certain* and refuses moves that depend on it when it is not
  (after a soft reset, or a jog the controller bounced).

### `job.py` — streaming one file ✅ working
- Feeds a board's G-code through the streamer, counting `sent` and `acked`
  separately and claiming neither is the pen's position — GRBL answers `ok`
  when it has parsed and queued a line, not when it has drawn it.
- Pause feed-holds as well as stopping the feed; stop drops the rest of the
  file and releases the hold so the controller drains and returns to Idle,
  keeping work zero. `check=True` brackets the job with `$C`.

---

## 4. G-code we emit (reference)

```gcode
G21              ; units = mm
G90              ; absolute positioning
G1 Z0.5 F200     ; pen up
G0 X.. Y.. F3000 ; travel to trace start
G1 Z-0.5 F200    ; pen down
G1 X.. Y.. F800  ; draw the trace
G1 Z0.5 F200     ; pen up
...
G0 X0 Y0         ; return home
M2               ; end
```

Compatible with GRBL 1.1. The web app streams it over the USB cable itself —
see `grbl/`, `machine.py` and `job.py` above.

---

## 5. Roadmap / backlog

**Next up**
- [x] **Travel optimization** — nearest-neighbour ordering + endpoint flipping.
      Done in `pcb_gcode.py::optimize_order`; cut pen-up travel by 92% (4200→332 mm).
- [ ] **CLI arguments** — take input file / layer / output name instead of
      hardcoded `labExam.*` (affects `pcb_draw.py`, `pcb_gcode.py`, `main.py`).
- [ ] Merge collinear/continuous segments so a multi-segment trace draws in one
      pen-down stroke (fewer pen lifts, cleaner lines).

**Later**
- [x] Web UI: upload `.kicad_pcb`, preview the toolpath in the browser,
      download the G-code, and plot it over USB. Done — `../userpage`.
- [ ] Pad/footprint rendering so traces visibly connect to component pads.
- [ ] Two-sided support (plot F.Cu and B.Cu with a flip/registration step).
- [ ] Configurable machine profiles (bed size, pen offset, feed presets).

**Validation to do**
- [ ] Compare our G-code against FlatCAM output on the same board.
- [ ] `POST /machine/run` with `check: true` against real GRBL firmware
      (Check Mode, no motion). Green against the simulator.
- [ ] Dry-run on real hardware (pen up, no contact) to check registration.

### Recommended validation order before a real plot
1. `pcb_gcode_preview.py` — offline visual check (catches wrong geometry).
2. `pcb_send.py --check --port ...` — firmware Check Mode; parses, no motion.
3. Pen-up dry run — run for real with the pen raised (checks scale/limits).
4. Real plot.

---

## 6. How to run

```bash
python main.py                # run the whole pipeline, step by step
python main.py --skip-preview # ... without the matplotlib image steps

# or run any stage on its own:
python pcb_read.py            # print extracted wiring_data
python pcb_draw.py            # -> labExam_wiring.png (board, by layer)
python pcb_gcode.py           # -> labExam.gcode
python pcb_gcode_preview.py   # -> labExam_toolpath.png (verify before hardware)
```

Dependencies: Python 3, `matplotlib`. (kiutils intentionally **not** used.)
