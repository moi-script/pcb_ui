# TraceWorks — Web UI

A Next.js + TypeScript web app for the single-layer PCB pen-plotter pipeline in
`../pcb_reader`. It's the "product" side of the vision in that repo's DOCS.md:
upload a KiCad board, route it into G-code, preview the toolpath in the browser,
and stream it to a FluidNC machine, paired to your account by **device ID**.

## Stack
- Next.js 15 (App Router) + React 19 + TypeScript
- Tailwind CSS v4 (custom "engineering instrument" theme, no gradient slop)
- Fonts: Space Grotesk (display/UI) + IBM Plex Mono (data)
- Talks to the Python API in `../pcb_reader` (FastAPI + MongoDB)

## Run

You need **two servers** running: the Python API and this frontend.

```bash
# 1. Backend (in ../pcb_reader) — parses boards, generates G-code, stores in Mongo
#    Requires a local MongoDB on mongodb://localhost:27017
cd ../pcb_reader
pip install -r requirements.txt
uvicorn server:app --reload --port 8000

# 2. Frontend (this folder)
npm install
npm run dev            # http://localhost:3000
```

The frontend calls the API at `http://localhost:8000` by default. Override with
`NEXT_PUBLIC_API_URL` in a `.env.local` if your API runs elsewhere.

## Pages
| Route | What it is |
|-------|-----------|
| `/` | Marketing landing: pipeline, device-pairing story, hardware, pricing |
| `/signup`, `/login` | Account creation / sign-in (stored in MongoDB via the API) |
| `/connect` | **Device pairing**: enter the device ID, watch the FluidNC handshake, bind it to your account |
| `/dashboard` | Overview: paired device, your routed boards, travel-saved stats |
| `/dashboard/projects` | Upload a `.kicad_pcb`; it's routed by the API and saved to your account |
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

## Caveats (prototype)
- Auth is intentionally simple: passwords are hashed (PBKDF2) but there's no
  token/JWT or session expiry, and endpoints trust the email passed from the
  client. Fine for local development; add real sessions before exposing it.
