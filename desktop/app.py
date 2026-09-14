"""TraceWorks for Windows — the whole stack in one window.

Starts the FastAPI app from serverside/ on a free localhost port, serves the
static export of userpage/ (built with NEXT_PUBLIC_DESKTOP=1) from the same
origin, and shows it in a native window through pywebview (Edge WebView2).

What differs from the dev setup:
- storage is SQLite in %LOCALAPPDATA%\\TraceWorks, not MongoDB;
- there is no sign-in — the UI uses one local user;
- the API and the UI share an origin, so there is no CORS and no fixed port.

Run from source (after building the UI, see desktop/README.md):
    python desktop/app.py
Set TRACEWORKS_SIM=1 to get the simulated GRBL port, as with uvicorn.
"""
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

APP_NAME = "TraceWorks"
FROZEN = getattr(sys, "frozen", False)

# Where things are: inside the PyInstaller bundle, or in the repo.
if FROZEN:
    BUNDLE = Path(sys._MEIPASS)
    UI_DIR = BUNDLE / "ui"
else:
    ROOT = Path(__file__).resolve().parent.parent
    UI_DIR = ROOT / "userpage" / "out"
    sys.path.insert(0, str(ROOT / "serverside"))

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME

# db.py reads these at import, so they are set before server is imported.
os.environ.setdefault("TRACEWORKS_DB", "sqlite")
os.environ.setdefault("TRACEWORKS_DATA_DIR", str(DATA_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# A windowed exe has no console: stdout/stderr are None, and the first log
# line uvicorn writes would crash it. Send everything to a file instead.
if FROZEN or sys.stdout is None:
    _log = open(DATA_DIR / "traceworks.log", "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr = _log

# uvicorn runs with log_config=None (its default config assumes a console),
# so its loggers need somewhere to go: the root handler, i.e. the log file.
logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")

from fastapi import HTTPException  # noqa: E402
from fastapi.responses import FileResponse, RedirectResponse  # noqa: E402

import server  # noqa: E402  (serverside/server.py)

app = server.app


# ------------------------------------------------------------------- the UI
def _drop_route(path: str, method: str) -> None:
    app.router.routes[:] = [
        r for r in app.router.routes
        if not (getattr(r, "path", None) == path
                and method in getattr(r, "methods", ()))
    ]


# "/" is the API's health check in dev; here it is the app's front door.
# The health check moves to /health.
_drop_route("/", "GET")
app.add_api_route("/health", server.health, methods=["GET"])

# The export has one copy of the board page, built for the id "_". Any real
# id is served that copy (its HTML and its RSC payload alike).
_BOARD_PREFIX = ("dashboard", "projects")


def _resolve(path: str) -> Path | None:
    parts = [p for p in path.split("/") if p and p not in (".", "..")]
    if len(parts) >= 3 and tuple(parts[:2]) == _BOARD_PREFIX:
        if not (UI_DIR.joinpath(*parts[:3])).exists():
            parts[2] = "_"
    target = UI_DIR.joinpath(*parts)
    if target.is_dir():
        target = target / "index.html"
    elif not target.exists() and not target.suffix:
        target = target.with_suffix(".html")
    return target if target.is_file() else None


@app.get("/", include_in_schema=False)
def ui_root():
    return FileResponse(UI_DIR / "index.html")


# Registered last, so every API route above still matches first.
@app.get("/{path:path}", include_in_schema=False)
def ui_file(path: str):
    target = _resolve(path)
    if target is not None:
        return FileResponse(target)
    # trailingSlash export: /dashboard -> /dashboard/
    if not path.endswith("/") and _resolve(path + "/") is not None:
        return RedirectResponse("/" + path + "/")
    if (UI_DIR / "404.html").is_file():
        return FileResponse(UI_DIR / "404.html", status_code=404)
    raise HTTPException(404)


# --------------------------------------------------------------- the window
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_up(port: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _already_running() -> bool:
    """True if another TraceWorks window is open on this PC.

    Two copies means two servers, and only one of them can hold the
    plotter's COM port: the other is told "Access is denied" on Connect, or
    worse, one is plotting while the operator presses buttons in the other.
    A named mutex lives exactly as long as the process that created it.
    """
    if sys.platform != "win32":
        return False
    import ctypes

    kernel32 = ctypes.windll.kernel32
    global _instance_mutex  # held for the life of the process
    _instance_mutex = kernel32.CreateMutexW(None, False, "Local\\TraceWorksDesktop")
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        ctypes.windll.user32.MessageBoxW(
            None,
            "TraceWorks is already open. Only one window can control the "
            "plotter at a time.",
            APP_NAME,
            0x40,  # MB_ICONINFORMATION
        )
        return True
    return False


_instance_mutex = None


def main() -> None:
    import uvicorn
    import webview

    if _already_running():
        sys.exit(0)

    if not (UI_DIR / "index.html").is_file():
        sys.exit(f"UI not built: {UI_DIR} is missing. See desktop/README.md.")

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port,
                            log_level="info", log_config=None)
    srv = uvicorn.Server(config)
    threading.Thread(target=srv.run, daemon=True).start()
    if not _wait_until_up(port):
        logging.getLogger("traceworks").error("server did not start")
        sys.exit(1)

    webview.create_window(APP_NAME, f"http://127.0.0.1:{port}/",
                          width=1360, height=880, min_size=(900, 600))
    # Keep WebView2's cache and localStorage with the app's data.
    webview.start(private_mode=False, storage_path=str(DATA_DIR / "webview"))

    # Window closed: let go of the machine before the process goes.
    try:
        server.session.disconnect()
    except Exception:  # noqa: BLE001
        pass
    srv.should_exit = True


if __name__ == "__main__":
    main()
