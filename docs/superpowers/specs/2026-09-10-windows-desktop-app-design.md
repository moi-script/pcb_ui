# TraceWorks as a Windows desktop application

Date: 2026-09-10
Status: approved design, not yet implemented

## Purpose

Today TraceWorks is a local development stack: two terminals, a separately
installed MongoDB, and a browser pointed at `localhost:3000`. This design turns
it into a single Windows application — one installer, one icon, one window —
that a person with no Python, no Node, and no MongoDB can install and use to
plot a board.

Nothing about what the app *does* changes. The KiCad and image pipelines, the
G-code emitter, the GRBL session and the visualizer all keep their current
behaviour. What changes is how the pieces are started, how they find each
other, where data lives, and who the app thinks the user is.

### Success criteria

1. A clean Windows 11 machine with no developer tooling installs the app from
   one `.exe` and reaches the dashboard.
2. `/connect` lists real COM ports, and a board plots over USB, with no
   terminal open at any point.
3. Closing the window stops every child process; relaunching does not pay for
   MongoDB crash recovery.
4. The existing backend test suite stays green, minus the tests that assert
   behaviour this design deliberately removes.

### Non-goals

- `machine-control-slice-1/` — a separate application on its own branch. Not
  touched.
- Code signing and auto-update. Both are wanted eventually; see Deferred work.
- macOS and Linux builds. The structure does not preclude them; this work does
  not deliver them.
- Any change to tracing, G-code generation, or motion behaviour.

## Decisions taken

These were settled during brainstorming and are not open questions:

| Decision | Chosen | Rejected |
|---|---|---|
| Data store | Bundle `mongod.exe` in the installer | SQLite shim; requiring a separate MongoDB install |
| App shell | Electron | Tauri; pywebview |
| Accounts | Removed entirely | Keeping login as-is; silent local profile |

The MongoDB choice trades installer size (~200MB) and a process lifecycle to
manage against leaving `serverside/db.py` and every query in `server.py`
untouched. The account removal is the largest diff in this design but produces
the desktop behaviour: the app opens ready to work.

## Architecture

The Electron main process is the supervisor. It owns two child processes and
one window.

```
Electron main (desktop/src/main.ts)
├── spawns  mongod.exe          --dbpath %APPDATA%\TraceWorks\db
│                               --bind_ip 127.0.0.1 --port <ephemeral>
├── spawns  traceworks-api.exe  PORT=<ephemeral>
│                               MONGO_URL=mongodb://127.0.0.1:<mongo port>
└── opens   BrowserWindow       app://index.html  (static Next.js export)
                                preload injects window.__TRACEWORKS_API__
```

Three units, each with one job:

- **`desktop/src/ports.ts`** — finds free TCP ports. Input: nothing. Output: a
  port number nothing else holds.
- **`desktop/src/supervisor.ts`** — starts, health-checks, and stops the two
  child processes. Input: a data directory and resource paths. Output: the
  backend's base URL, or a startup error. Depends on `ports.ts` and the
  bundled binaries; depends on nothing in the UI.
- **`desktop/src/main.ts`** — Electron lifecycle and windows. Depends on
  `supervisor.ts` and nothing else.

Keeping the supervisor free of Electron imports means it can be exercised from
a plain Node script during development, which is the only practical way to
debug a launch failure.

### Ports are ephemeral, not fixed

The app must never collide with a running dev stack, another copy of itself, or
an unrelated service. Both children get a port chosen at launch from the
ephemeral range, bound to `127.0.0.1` only.

This creates one problem worth stating plainly: `NEXT_PUBLIC_API_URL` is
inlined at build time, and the port is not known until launch. The preload
script therefore sets `window.__TRACEWORKS_API__` before any page script runs,
and `userpage/lib/api.ts` changes its resolution order to:

```
window.__TRACEWORKS_API__  ??  process.env.NEXT_PUBLIC_API_URL  ??  "http://localhost:8000"
```

`npm run dev` in a browser sees no injected value and behaves exactly as it
does today.

### The UI ships as a static export

Only `app/layout.tsx` and `app/page.tsx` lack `"use client"`; the other 17
files are already client components. So `output: 'export'` is viable and no
Node runtime ships inside the app. Two blockers must be cleared first.

**Dynamic route.** `app/dashboard/projects/[id]/page.tsx` cannot be exported —
board ids are created at runtime, so `generateStaticParams` has nothing to
enumerate. The route becomes `/dashboard/projects/view?id=<id>`, reading the id
from `useSearchParams`. Three call sites link to it: `app/dashboard/page.tsx`
(two) and `components/Uploader.tsx` (one).

**Protocol.** `file://` mangles both query strings and the export's absolute
asset paths. Electron registers a custom `app://` scheme serving the `out/`
directory, which behaves like an origin and keeps `localStorage` stable across
launches.

### Accounts are removed

Every board and the remembered serial port are currently keyed by email. On a
single-user machine that indirection buys nothing and costs a login wall.

Backend (`serverside/server.py`, `serverside/db.py`) — about 35 references:

- Delete `POST /auth/signup`, `POST /auth/login`, and the `users` collection
  with its index.
- Drop the `email` form field from `POST /route` and `POST /trace`, and the
  `email` parameter from `POST /machine/connect` and `GET /machine/last`.
- `GET /boards/{email}` becomes `GET /boards`.
- `boards` documents lose `user_email`; the index on it goes.
- `machines` collapses from one document per user to a single settings document
  with a fixed `_id`, holding `last_port` and `last_baud`.

Frontend — nine files, about 46 references:

- Delete `lib/auth.tsx`, `app/login/`, `app/signup/`, `components/AuthAside.tsx`.
- `app/dashboard/layout.tsx` loses its session guard and redirect.
- `lib/api.ts` loses `email` from every signature, and the `signUp`/`signIn`
  calls.
- `app/connect/page.tsx`, `app/dashboard/page.tsx`,
  `app/dashboard/projects/page.tsx`, the projects detail page and
  `components/Uploader.tsx` drop their `useAuth()` usage.

**Entry point.** With no login there is no reason to land on a marketing page
inside a desktop app. `app://` opens `/dashboard` directly, and the marketing
landing route (`app/page.tsx`, plus `components/MarketingNav.tsx` and
`components/Footer.tsx` if nothing else uses them) is removed from the
application. This was flagged during brainstorming and not explicitly
confirmed; it is the only decision here that can be reversed cheaply — if the
landing page should stay, keep the route and point the window at `/` instead.

## Packaging

### Backend freeze

PyInstaller, one-dir (not one-file: one-file unpacks to a temp directory on
every launch, which is slow and confuses antivirus). Reachable third-party
imports from `server.py`, computed by tracing the import graph:

```
fastapi  uvicorn  starlette  pydantic  pymongo  bson  gridfs
serial   numpy    cv2        skimage   PIL
```

`matplotlib` is **not** reachable from `server.py` — it is used only by
`pcb_draw.py`, `pcb_gcode_preview.py` and `main.py`, which are CLI tools that
do not ship. It is excluded, along with `pytest` and `tkinter`.

`uvicorn` and `pymongo` load transports and codecs dynamically, so both need
`--collect-submodules`; `skimage` and `cv2` need their data files collected.
Getting these wrong produces an executable that starts and then fails on the
first request, so the freeze is verified by running the packaged binary and
hitting the health endpoint, not by watching PyInstaller exit zero.

### Installer

`electron-builder`, NSIS target, per-user install (no admin prompt). Bundled as
`extraResources`: `mongod.exe`, the frozen backend directory, and the Next.js
`out/`. Icon derived from `userpage/app/icon.svg`.

One build command wires the three stages together:

```
npm run build:desktop   # next build (export) -> pyinstaller -> electron-builder
```

Expected installer size is 400–500MB: Chromium ~150MB, mongod ~200MB, and the
frozen Python with OpenCV and scikit-image ~150MB. This follows from the
decisions above and is accepted.

### Filesystem layout

```
%APPDATA%\TraceWorks\
├── db\       MongoDB data directory
└── logs\     mongod.log, backend.log, main.log
```

The installed program files stay read-only; everything mutable lives here, so
uninstall-and-reinstall preserves boards.

## Startup, shutdown, and failure

**Startup** is sequential, because the backend cannot connect to a database
that is not listening yet:

1. Ensure `%APPDATA%\TraceWorks\{db,logs}` exist.
2. Reap orphans — any `mongod.exe`/`traceworks-api.exe` left by a previous
   crash, identified by a pid file in the data directory.
3. Start mongod; poll until it accepts a connection, 20s ceiling.
4. Start the backend; poll `GET /` until it reports the database reachable,
   20s ceiling.
5. Load the window.

A loading window is shown from step 1 and replaced at step 5. If any step
exceeds its ceiling or a child exits early, the loading window becomes an error
window naming the failed step and the log path. A blank window is never an
acceptable outcome.

**Shutdown** must be graceful in both directions. The backend gets a terminate
signal and closes its serial port — an abandoned COM port stays locked until
the driver times out, and the next launch cannot connect to the machine.
mongod is stopped with a clean `shutdown` command rather than a kill; skipping
this makes every subsequent launch pay for journal recovery. Both also run on
`window-all-closed` and on an uncaught exception in main.

**A running job is a special case.** If G-code is streaming when the user
closes the window, the app must ask before quitting, and on confirmation send a
feed hold and stop to the controller before closing the port. Quitting
mid-stream otherwise leaves the tool down on the board.

## Testing

**Unaffected and must stay green.** The backend suite (135 tests) exercises
tracing, G-code, GRBL state, limits, streaming and the simulator. None of it
touches Electron. `test_machine_memory.py` and `test_retrace.py` reference
email and get updated; the rest should not move. `vitest` on `lib/gcode.test.ts`
is untouched.

**New unit tests.**

- `ports.ts` returns a port that is genuinely free, and two calls never collide.
- `supervisor.ts` health-check polling: succeeds on a slow starter, reports the
  right failed step on timeout, and reports a child that exits early rather
  than waiting out the ceiling.
- `api.ts` base-URL resolution: injected value wins over env var wins over
  default.

**Verified by hand, because nothing else can.** On a clean Windows VM: install;
first launch creates the data directory; the dashboard opens; `TRACEWORKS_SIM`
plots a board end to end; a real board plots over USB; quitting leaves no
`mongod.exe` or `traceworks-api.exe` in Task Manager; relaunch is fast, which
is the observable proof that shutdown was clean.

## Deferred work

- **Code signing.** Unsigned, the installer trips SmartScreen with a warning
  most users read as malware. Fixing it needs a purchased certificate and a
  signing step in `electron-builder`. Required before distributing to anyone
  else; not required to use the app yourself.
- **Auto-update.** `electron-updater` needs a hosting target and signing first.
- **Installer slimming.** If size becomes a real problem, the levers are the
  data store (SQLite would remove ~200MB) and the shell (Tauri, ~140MB) — both
  were considered and rejected here, and either would be a new design.
- **Simulator toggle in the UI.** `TRACEWORKS_SIM` is an environment variable
  today, which is awkward without a terminal. A menu item would suit the
  desktop app, but it is not needed to ship.

## Build order

Each step leaves the repository working:

1. Account removal, backend then frontend, with the test suite green after each.
2. Static export: dynamic route to query parameter, `output: 'export'`,
   `api.ts` base-URL resolution.
3. Electron shell against dev servers — window, `app://` protocol, preload —
   with no packaging yet.
4. Supervisor: ports, spawning, health checks, shutdown, error window.
5. PyInstaller freeze, verified by running the frozen binary directly.
6. `electron-builder` installer, verified on a clean VM.
