# TraceWorks for Windows

The whole stack as an installable Windows app: one `TraceWorks-Setup.exe`,
a Start-menu icon, its own window. No MongoDB, no Node, no terminals.

## Getting it (for users)

Download `TraceWorks-Setup-<version>.exe` from the
[Releases page](https://github.com/moi-script/pcb_ui/releases/latest), run it,
and open TraceWorks from the Start menu. It installs per-user, so no admin
prompt.

The installer isn't code-signed, so Windows SmartScreen shows "Windows
protected your PC" the first time: click **More info → Run anyway**.

Boards and settings are kept in `%LOCALAPPDATA%\TraceWorks` (`traceworks.db`,
plus `traceworks.log` if something goes wrong). Uninstalling leaves them there.

## How it differs from the dev setup

|                | dev (`uvicorn` + `npm run dev`) | desktop app |
|----------------|---------------------------------|-------------|
| database       | MongoDB                         | SQLite file (`serverside/sqlite_store.py`) |
| sign-in        | accounts, `/login`              | none — one local user |
| UI served by   | Next.js dev server, port 3000   | the Python app, static export |
| API            | `localhost:8000`                | same origin, a free port |
| window         | your browser                    | native window (pywebview / WebView2) |

The switches are `TRACEWORKS_DB=sqlite` (backend) and `NEXT_PUBLIC_DESKTOP=1`
(frontend build). Nothing changes unless they are set.

## Building it

Needs Python 3.12+, Node 22, and [Inno Setup 6](https://jrsoftware.org/isinfo.php)
(`winget install JRSoftware.InnoSetup`).

```powershell
powershell -ExecutionPolicy Bypass -File desktop\build.ps1 -Version 0.1.0
```

1. `next build` of `userpage/` with `NEXT_PUBLIC_DESKTOP=1` → `userpage/out/`
2. a clean venv in `desktop/.venv` from `desktop/requirements.txt`
3. PyInstaller (`traceworks.spec`) → `desktop/dist/TraceWorks/TraceWorks.exe`
4. Inno Setup (`installer.iss`) → `desktop/dist/TraceWorks-Setup-0.1.0.exe`

To try it without packaging, after step 1: `desktop\.venv\Scripts\python desktop\app.py`
(`TRACEWORKS_SIM=1` adds the simulated machine, as usual).

## Publishing a release

Push a version tag; `.github/workflows/desktop.yml` builds the installer on a
Windows runner and attaches it to a GitHub Release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The link to share is then
`https://github.com/moi-script/pcb_ui/releases/latest`, or, to start the
download straight away (the landing page's button uses this),
`https://github.com/moi-script/pcb_ui/releases/latest/download/TraceWorks-Setup.exe`.
