"""esp_mock.py — a stand-in for the ESP32 bridge, for testing without hardware.

Emulates the same HTTP API as esp32_bridge.ino (/print, /status, /stop, /) and
fakes GRBL's line-by-line pacing on a timer, so the full
web -> backend -> ESP chain can be exercised from a laptop.

    python firmware/esp_mock.py                 # listens on :8770
    # then point the backend at it:
    ESP_BASE_URL=http://localhost:8770 uvicorn server:app --reload --port 8000

Override the port with --port. It streams roughly `--rate` lines/sec (default
40) so progress is visible but quick.
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ------------------------------------------------------------- shared job state
_lock = threading.Lock()
_job = {
    "state": "idle",   # idle|checking|printing|done|error|stopped
    "line": 0,
    "total": 0,
}
_rate = 40.0  # lines per second


def _count_lines(text: str) -> int:
    n = 0
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if line:
            n += 1
    return n


def _run_job(total: int, check: bool):
    """Advance `line` on a timer until it reaches `total` or we're stopped."""
    with _lock:
        _job["state"] = "checking" if check else "printing"
        _job["line"] = 0
        _job["total"] = total
    delay = 1.0 / _rate if _rate > 0 else 0
    for i in range(1, total + 1):
        time.sleep(delay)
        with _lock:
            if _job["state"] in ("stopped", "error", "idle"):
                return  # aborted
            _job["line"] = i
    with _lock:
        if _job["state"] in ("checking", "printing"):
            _job["state"] = "done"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # quiet
        pass

    def do_GET(self):
        if self.path == "/status":
            with _lock:
                self._send(200, dict(_job))
        elif self.path == "/":
            self._send(200, {"name": "esp-mock", "state": _job["state"]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/print":
            with _lock:
                if _job["state"] in ("checking", "printing"):
                    self._send(409, {"error": "a job is already running"})
                    return
            length = int(self.headers.get("Content-Length", 0))
            gcode = self.rfile.read(length).decode("utf-8", "replace")
            if not gcode.strip():
                self._send(400, {"error": "empty body; expected G-code"})
                return
            total = _count_lines(gcode)
            check = self.headers.get("X-Check") == "1"
            threading.Thread(
                target=_run_job, args=(total, check), daemon=True
            ).start()
            self._send(202, {"ok": True, "total": total, "check": check})
        elif self.path == "/stop":
            with _lock:
                if _job["state"] in ("checking", "printing"):
                    _job["state"] = "stopped"
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})


def main():
    global _rate
    ap = argparse.ArgumentParser(description="Mock ESP32 G-code bridge.")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--rate", type=float, default=40.0,
                    help="fake stream speed in lines/sec")
    args = ap.parse_args()
    _rate = args.rate
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"esp-mock listening on http://localhost:{args.port} "
          f"({args.rate:g} lines/s)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
