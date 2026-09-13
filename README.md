# TraceWorks

The full stack for the single-layer PCB pen-plotter pipeline: upload a KiCad
board or an image, route it into G-code, preview the toolpath in the browser,
and plot it — over a USB cable to an Arduino running GRBL, the way Universal
Gcode Sender works. Plug it in, pick the port, connect, run.

Frontend and backend live side by side in this one repo.

```
pcb_ui/
├── serverside/              the backend  — Python, FastAPI + MongoDB
├── userpage/                the frontend — Next.js 15 + React 19 + TypeScript
├── machine-control-slice-1/ a separate workbench app (own UI + own server)
├── docs/                    design specs and plans
├── desktop/                 the Windows app: installer, window, SQLite build
└── RUNNING.md               how to run both halves  ← start here
```

## Run it

**[RUNNING.md](RUNNING.md) is the full guide** — prerequisites, first-time
install, environment variables, troubleshooting. The short version, two
terminals:

```bash
# Terminal 1 — backend (needs MongoDB on localhost:27017)
cd serverside
pip install -r requirements.txt
uvicorn server:app --reload --port 8000     # http://localhost:8000/docs

# ...or with no hardware attached: adds a port named SIM that behaves like a
# GRBL 1.1 controller, so connect, jog, zero and plotting all work.
TRACEWORKS_SIM=1 uvicorn server:app --reload --port 8000

# Terminal 2 — frontend
cd userpage
npm install
npm run dev                                 # http://localhost:3000
```

## Windows app

TraceWorks also ships as an installable Windows app — one setup file, its own
window, no MongoDB or Node needed, no sign-in. Download it from
[Releases](https://github.com/moi-script/pcb_ui/releases/latest); build and
release it as described in [desktop/README.md](desktop/README.md).

## Stack

**`userpage/`** — Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS v4
(custom "engineering instrument" theme, no gradient slop). Fonts: Space Grotesk
(display/UI) + IBM Plex Mono (data). No server of its own; it calls the API in
`serverside/` at `http://localhost:8000` (`userpage/lib/api.ts`, override with
`NEXT_PUBLIC_API_URL`).

**`serverside/`** — FastAPI (`server.py`) wrapping the PCB pipeline
(`pcb_read.py` → `pcb_gcode.py` → `pcb_send.py`) and the image tracer
(`tracer/`), and owning the serial link to the machine (`grbl/`,
`machine.py`, `job.py`). Accounts, routed boards, and the last serial port used
are stored in MongoDB (`db.py`, database `traceworks`). It is also a standalone
CLI pipeline — `python main.py` — and has its own [README](serverside/README.md),
[DOCS.md](serverside/DOCS.md), and [HARDWARE.md](serverside/HARDWARE.md) for the
controller build.

**`machine-control-slice-1/`** — a separate, self-contained app on its own git
worktree branch: its own Next.js UI *and* its own FastAPI backend that owns the
serial port and streams G-code to GRBL/FluidNC. Has a simulator, so it runs
without hardware. It uses neither `serverside/` nor `userpage/`, and it wants
the same ports, so run one stack at a time. See RUNNING.md.

## Pages (`userpage/`)
| Route | What it is |
|-------|-----------|
| `/` | Marketing landing: pipeline, hardware, pricing |
| `/signup`, `/login` | Account creation / sign-in (stored in MongoDB via the API) |
| `/connect` | **Machine connect**: pick the serial port and baud rate, connect |
| `/dashboard` | Overview: machine status, your routed boards, travel-saved stats |
| `/dashboard/projects` | Upload a `.kicad_pcb` to route, or an image to trace; both are saved to your account |
| `/dashboard/projects/[id]` | Board detail: layer-toggle preview of the real traces, route report, real G-code (downloadable), and Plot — with a dry-check, live progress, and a toolpath that fills in as the machine draws |
| `/dashboard/device` | Machine: live position, jog pad, zeroing, home, unlock, console, E-stop |

## How it connects
- **Upload → route:** the uploader POSTs your `.kicad_pcb` to `POST /route`. The
  API parses it (`pcb_read.extract_wiring`), runs `pcb_gcode.generate_gcode`,
  stores the result in MongoDB, and returns the board. The detail page renders
  the real tracks and G-code, not a sample.
- **Plot:** the backend runs on the same PC as the browser, so it — not the
  tab — owns the COM port. A browser tab cannot open a serial port;
  `localhost:8000` can. `POST /machine/connect` opens it, `POST /machine/run`
  streams the board's stored G-code under GRBL's character-counting flow
  control, and `WS /machine/ws` pushes position, console lines and job progress
  back at up to 10 Hz.
- **Progress is counted in acknowledged lines, position in `WPos`.** GRBL
  answers `ok` when it has parsed and *queued* a line, not when it has drawn
  it, so the line counter runs ahead of the pen. The UI shows both and names
  them for what they are.
- **Accounts & boards** live in MongoDB (`traceworks` database: `users`,
  `machines`, `boards`). A light session (name, email) is kept in localStorage
  so the browser remembers who's signed in. `machines` holds only the last port
  and baud, as a convenience so Connect is one click next time — it carries no
  identity and connecting never requires it.
- **Connecting resets the controller.** Opening the port toggles DTR and the
  Arduino reboots, so work zero is cleared every session. Set it on the Machine
  page, after connecting, before plotting.
- The built-in `labExam` sample geometry in `board_raw.json` is only used for the
  marketing/landing previews, not the dashboard.

### Tracing an image

Upload a PNG or JPG instead of a `.kicad_pcb` and the API traces it to a
single-line pen path. No Inkscape, no jscut: the image is thinned to a
one-pixel skeleton down the middle of each stroke, and that skeleton is walked
into paths.

- **Longest edge (mm) is required.** An image has pixels, a machine has
  millimetres, and there is no DPI worth trusting in a photo. Ask for 50 mm and
  the drawing comes out 50 mm.
- **Centreline** draws one line down the middle of each stroke. Right for line
  art, diagrams, and text.
- **Outline** draws around each filled shape — the silhouette edge only.
- **Fill** draws the outline and then floods it with parallel strokes. This is
  the one to use for **etch resist**: centreline draws down the middle of a
  trace and outline draws its edge, so neither covers the copper, and the etch
  gets everything they missed. Set the line spacing to your pen's width or a
  little under; cross-hatching adds a second pass at 90° and covers far more
  reliably for double the plotting time.
- **PCB source** switches to adaptive thresholding, which copes with the uneven
  lighting in a photo of a board, keeps corners sharp, and preserves small pad
  marks.

The source image is kept, so the **Re-trace** panel on the board page reruns
it with different settings — size, mode, preset, threshold, invert — without
re-uploading. The board keeps its id and name, so the link stays valid and a
rename is not undone. Deleting the board deletes the stored source with it.

Two limits of **centreline** mode specifically: a filled shape becomes a
spidery skeleton rather than a filled area, and a perfect disc thins to a
single point — its medial axis is its centre — so it has no centreline at all
and is rejected with an error. Both are what fill mode is for.

Every traced board stores a pen-up alignment frame alongside its G-code. Run
the frame first to check placement — it costs nothing and it is the cheapest
way to find out the drawing runs off the edge of the work.

## Caveats (prototype)
- Auth is intentionally simple: passwords are hashed (PBKDF2) but there's no
  token/JWT or session expiry, and endpoints trust the email passed from the
  client. Fine for local development; add real sessions before exposing it.
- **One machine, one connection, one PC.** The serial session is a
  process-wide singleton, not a per-account object: there is one plotter on
  the end of one cable. Two browser tabs share it rather than each believing
  they own it.
- **Connecting resets the controller and clears work zero.** Opening the port
  toggles DTR and the Arduino reboots. This is normal — UGS does the same —
  but it means zero has to be set after connecting, every session.
- **Stop is not E-stop.** Stop drops the rest of the file and lets the moves
  already inside the controller run out, so work zero survives. E-stop
  soft-resets: motion ends immediately and position and zero are both lost.
