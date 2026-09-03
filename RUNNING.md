# Running TraceWorks

Two halves, two terminals. `serverside/` is the API, `userpage/` is the web UI.
The UI is useless on its own — every page it has calls the API — so **start the
backend first**.

```
pcb_ui/
├── serverside/              Python — FastAPI + MongoDB (the backend)
├── userpage/                Next.js + React + TypeScript (the frontend)
├── machine-control-slice-1/ separate workbench app, own UI + own server (see below)
└── RUNNING.md               this file
```

| | Command | Port |
|---|---|---|
| Backend | `cd serverside && uvicorn server:app --reload --port 8000` | http://localhost:8000 |
| Frontend | `cd userpage && npm run dev` | http://localhost:3000 |

---

## What you need installed

- **Python 3.10+** — `python --version`
- **Node 18.18+** — `node --version`
- **MongoDB running locally** on `mongodb://localhost:27017`. The API stores
  accounts, paired devices, and routed boards there and will fail on the first
  request without it.

Check Mongo is up before anything else:

```bash
mongosh --eval "db.runCommand({ping:1})"
```

On Windows, MongoDB installed as a service usually starts itself; if not:
`net start MongoDB` in an **admin** terminal.

---

## First time: install dependencies

Do this once per machine (and again whenever `requirements.txt` or
`package.json` changes).

```bash
# Backend
cd serverside
python -m venv .venv                 # optional but recommended
source .venv/Scripts/activate        # Git Bash on Windows
# .venv\Scripts\activate             # PowerShell / cmd
# source .venv/bin/activate          # macOS / Linux
pip install -r requirements.txt
```

```bash
# Frontend
cd userpage
npm install
```

---

## Terminal 1 — backend

```bash
cd serverside
uvicorn server:app --reload --port 8000
```

You should see `Uvicorn running on http://127.0.0.1:8000`. Confirm it:

- http://localhost:8000/ — health check
- http://localhost:8000/docs — interactive API docs (every endpoint, try them live)

`--reload` restarts the server whenever you save a `.py` file. Drop it in
production.

If you made a venv, activate it in this terminal first.

## Terminal 2 — frontend

```bash
cd userpage
npm run dev
```

Open http://localhost:3000. Sign up, pair a device on `/connect`, then upload a
board or an image on `/dashboard/projects`.

---

## How the two find each other

The frontend calls `http://localhost:8000` by default — see `API_URL` in
`userpage/lib/api.ts`. To point it somewhere else, make
`userpage/.env.local`:

```
NEXT_PUBLIC_API_URL=http://192.168.1.50:8000
```

`NEXT_PUBLIC_*` values are baked in at build time, so **restart `npm run dev`**
after changing it.

The backend reads its database location from the environment, defaulting to
local Mongo (`serverside/db.py`):

```
MONGO_URL=mongodb://localhost:27017
MONGO_DB=traceworks
```

---

## Other things you can run

```bash
# Backend tests (135 of them, no Mongo or hardware needed)
cd serverside && python -m pytest -q

# The original CLI pipeline: KiCad file → preview → G-code → toolpath image
cd serverside && python main.py
cd serverside && python main.py --skip-preview   # skip the matplotlib steps

# Stream a .gcode file straight to the machine over USB serial
cd serverside && python pcb_send.py --check      # validate without moving anything

# Production frontend build
cd userpage && npm run build && npm start
```

---

## Troubleshooting

**Frontend loads but every action fails / "Failed to fetch"**
The API isn't running, or it's on a different port. Open
http://localhost:8000/docs in a browser — if that's blank, fix terminal 1 first.

**`ServerSelectionTimeoutError` in the backend log**
MongoDB isn't running. Start it, then retry — the API doesn't need a restart.

**`Address already in use` on 8000 or 3000**
Something else has the port. Either kill it, or move: `--port 8001` for uvicorn
(then set `NEXT_PUBLIC_API_URL` to match), `npm run dev -- -p 3001` for Next.

**`ModuleNotFoundError: No module named 'fastapi'`**
Dependencies aren't installed, or your venv isn't active in that terminal.
Re-run `pip install -r requirements.txt` from `serverside/`.

**`uvicorn: command not found`**
Same cause. Or call it through Python: `python -m uvicorn server:app --reload --port 8000`.

**Changed `NEXT_PUBLIC_API_URL` and nothing happened**
Restart the dev server. Those variables are inlined at build time.

---

## The other app: `machine-control-slice-1/`

That folder is a **separate, self-contained application** — a git worktree on
its own branch — with its own Next.js UI *and* its own FastAPI server that owns
the serial port and streams G-code to GRBL/FluidNC. It does not use
`serverside/` or `userpage/` at all.

It also wants ports 8000 and 3000, so **run one stack at a time** unless you
change ports.

```bash
cd machine-control-slice-1
pip install -r server/requirements.txt
npm install
npm run dev:all          # its API on :8000 + its UI on :3000
```

No machine plugged in? Run its simulator instead of the API and pick the port
named `SIM` in its UI:

```bash
cd machine-control-slice-1
python -m server.sim.serve_sim
npm run dev
```
