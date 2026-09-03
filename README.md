# TraceWorks

The full stack for the single-layer PCB pen-plotter pipeline: upload a KiCad
board or an image, route it into G-code, preview the toolpath in the browser,
and stream it to a FluidNC machine, paired to your account by **device ID**.

Frontend and backend live side by side in this one repo.

```
pcb_ui/
├── serverside/              the backend  — Python, FastAPI + MongoDB
├── userpage/                the frontend — Next.js 15 + React 19 + TypeScript
├── machine-control-slice-1/ a separate workbench app (own UI + own server)
├── docs/                    design specs and plans
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

# Terminal 2 — frontend
cd userpage
npm install
npm run dev                                 # http://localhost:3000
```

## Stack

**`userpage/`** — Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS v4
(custom "engineering instrument" theme, no gradient slop). Fonts: Space Grotesk
(display/UI) + IBM Plex Mono (data). No server of its own; it calls the API in
`serverside/` at `http://localhost:8000` (`userpage/lib/api.ts`, override with
`NEXT_PUBLIC_API_URL`).

**`serverside/`** — FastAPI (`server.py`) wrapping the PCB pipeline
(`pcb_read.py` → `pcb_gcode.py` → `pcb_send.py`) and the image tracer
(`tracer/`). Accounts, devices, and routed boards are stored in MongoDB
(`db.py`, database `traceworks`). It is also a standalone CLI pipeline —
`python main.py` — and has its own [README](serverside/README.md),
[DOCS.md](serverside/DOCS.md), and [HARDWARE.md](serverside/HARDWARE.md) for the
ESP32 / FluidNC build.

**`machine-control-slice-1/`** — a separate, self-contained app on its own git
worktree branch: its own Next.js UI *and* its own FastAPI backend that owns the
serial port and streams G-code to GRBL/FluidNC. Has a simulator, so it runs
without hardware. It uses neither `serverside/` nor `userpage/`, and it wants
the same ports, so run one stack at a time. See RUNNING.md.

## Pages (`userpage/`)
| Route | What it is |
|-------|-----------|
| `/` | Marketing landing: pipeline, device-pairing story, hardware, pricing |
| `/signup`, `/login` | Account creation / sign-in (stored in MongoDB via the API) |
| `/connect` | **Device pairing**: enter the device ID, watch the FluidNC handshake, bind it to your account |
| `/dashboard` | Overview: paired device, your routed boards, travel-saved stats |
| `/dashboard/projects` | Upload a `.kicad_pcb` to route, or an image to trace; both are saved to your account |
| `/dashboard/projects/[id]` | Board detail: layer-toggle preview of the real traces, route report, real G-code (downloadable), stream-to-device with a dry-check |
| `/dashboard/device` | Device identity, machine profile, unpair |

## How it connects
- **Upload → route:** the uploader POSTs your `.kicad_pcb` to `POST /route`. The
  API parses it (`pcb_read.extract_wiring`), runs `pcb_gcode.generate_gcode`,
  stores the result in MongoDB, and returns the board. The detail page renders
  the real tracks and G-code, not a sample.
- **Accounts & devices** live in MongoDB (`traceworks` database: `users`,
  `devices`, `boards`). A light session (name, email, paired device) is kept in
  localStorage so the browser remembers who's signed in.
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
