# serverside — the TraceWorks backend

A simple one-layer **PCB "drawer"**: read a KiCad board, extract the copper
traces, and turn them into travel-optimized **G-code** you can plot on a
pen-plotter / small CNC driven by a microcontroller (GRBL / FluidNC).

Aimed at hobby / student **mini projects**, not professional copper milling.

## Pipeline

```
labExam.kicad_pcb
  → pcb_read.py          parse (custom s-expression parser; supports KiCad 10)
  → pcb_draw.py          board preview by copper layer  (labExam_wiring.png)
  → pcb_gcode.py         travel-optimized G-code         (labExam.gcode)
  → pcb_gcode_preview.py verify toolpath, no hardware     (labExam_toolpath.png)
  → pcb_send.py          stream to GRBL/FluidNC over USB serial (--check to validate)
  → GRBL / FluidNC (ESP32) over USB or WiFi
```

## Run

```bash
python main.py                # run the whole pipeline, step by step
python main.py --skip-preview # ... without the matplotlib image steps
```

Each stage also runs on its own — see [`DOCS.md`](DOCS.md) for full
documentation, status, and roadmap, and [`HARDWARE.md`](HARDWARE.md) for the
ESP32 / FluidNC plotter build (parts list, flashing steps, starter config).

## Web API + database (server side of the UI)

`server.py` is a FastAPI app that wraps this pipeline for the web UI in
`../userpage`. It parses uploaded boards, generates G-code, and stores accounts,
paired devices, and routed boards in **MongoDB** (`mongodb://localhost:27017`,
database `traceworks`).

```bash
pip install -r requirements.txt
uvicorn server:app --reload --port 8000     # needs a local MongoDB running
```

Key endpoints: `POST /route` (upload a `.kicad_pcb` → parsed + routed board),
`/auth/signup` · `/auth/login`, `/devices/pair`, `/boards/{email}`,
`/board/{id}`. See `server.py` for the full list and `db.py` for the Mongo
connection. The reusable entry point is `pcb_read.extract_wiring(text)`.

## Requirements

Python 3 and `matplotlib` for the CLI pipeline. The web API also needs
`fastapi`, `uvicorn`, `python-multipart`, and `pymongo` (all in
`requirements.txt`), plus a running MongoDB. (kiutils is intentionally not used —
it does not support the KiCad 10 file format.)

See [`../RUNNING.md`](../RUNNING.md) for running this together with the
frontend in `../userpage`.
