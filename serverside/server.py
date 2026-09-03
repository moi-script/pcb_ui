"""TraceWorks API — the server side of the web UI.

Wraps the KiCad -> G-code pipeline in an HTTP API and stores accounts, paired
devices, and routed boards in MongoDB. The Next.js frontend (pcb_ui) talks to
this over HTTP.

Run it:
    uvicorn server:app --reload --port 8000

Endpoints:
    GET  /                     health + db status
    POST /auth/signup          {name,email,password} -> user
    POST /auth/login           {email,password}      -> user
    GET  /devices/{email}      -> device | null
    POST /devices/pair         {email, device_id}    -> device
    POST /devices/unpair       {email}
    POST /route                (multipart: file, email) -> routed board
    POST /trace                (multipart: file, email, size_mm, mode, preset) -> traced board
    POST /board/{id}/retrace   {size_mm, mode, preset, ...} -> re-traced board
    GET  /boards/{email}       -> [board summary]
    GET  /board/{id}           -> board (with geometry + gcode)
    DELETE /board/{id}

Trace modes: centerline (down the middle of each stroke), outline (around each
shape), fill (outline plus hatching — the one that actually covers copper for
etch resist).
"""
import hashlib
import json
import math
import os
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo import ReturnDocument

import db
from pcb_gcode import CONFIG, generate_gcode, optimize_order, travel_distance
from pcb_read import extract_wiring
from tracer import TraceError, TraceParams, trace_image
from tracer import emit

app = FastAPI(title="TraceWorks API", version="0.1.0")

# The browser (Next.js dev server) runs on some localhost port; allow any.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return secrets.compare_digest(h.hex(), digest)


# -------------------------------------------------------- default device spec
def default_device(device_id: str) -> dict:
    """Sensible profile stored when a machine is first paired."""
    return {
        "device_id": device_id,
        "alias": "Bench Plotter 01",
        "firmware": "FluidNC 3.9.7",
        "controller": "MKS DLC32 · ESP32",
        "connection": "WiFi",
        "port": "192.168.1.42",
        "bed": "300 × 300",
        "penUpZ": 5,
        "penDownZ": 0,
        "travelFeed": 3000,
        "drawFeed": 800,
    }


# ------------------------------------------------------------- board building
def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def build_board(wiring: list, name: str, filename: str) -> dict:
    """Turn raw wiring data into a stored board document: normalized tracks,
    bounds, per-layer counts, G-code, and a route report."""
    tracks = [w for w in wiring if w["type"] == "track"]
    if not tracks:
        raise HTTPException(400, "No copper tracks found in this file.")

    xs = [c for w in tracks for c in (w["start"][0], w["end"][0])]
    ys = [c for w in tracks for c in (w["start"][1], w["end"][1])]
    minx, miny = min(xs), min(ys)
    width = round(max(xs) - minx, 2)
    height = round(max(ys) - miny, 2)

    norm = [{
        "net": w["net"],
        "x1": round(w["start"][0] - minx, 3),
        "y1": round(w["start"][1] - miny, 3),
        "x2": round(w["end"][0] - minx, 3),
        "y2": round(w["end"][1] - miny, 3),
        "w": w["width_mm"],
        "layer": w["layer"],
    } for w in tracks]

    fcu = sum(1 for w in tracks if w["layer"] == "F.Cu")
    bcu = sum(1 for w in tracks if w["layer"] == "B.Cu")
    nets = sorted({w["net"] for w in tracks})

    # Plot front copper by default (the project's convention); fall back to
    # back copper only if the board has no F.Cu tracks at all.
    target = "F.Cu" if fcu > 0 else ("B.Cu" if bcu > 0 else "F.Cu")
    layer_tracks = [w for w in tracks if w["layer"] == target]

    cfg = dict(CONFIG)
    cfg["layer"] = target
    gcode_lines = generate_gcode(wiring, cfg)

    pairs_raw = [(w["start"], w["end"]) for w in layer_tracks]
    pen_up_before = round(travel_distance(pairs_raw))
    pen_up_after = round(travel_distance(optimize_order(layer_tracks)))
    draw_len = sum(_dist(w["start"], w["end"]) for w in layer_tracks)
    # rough time: draw + travel at their feeds, plus ~1.8s per pen lift
    est_minutes = max(
        1,
        math.ceil(draw_len / 800 + pen_up_after / 3000 + len(layer_tracks) * 0.03),
    )

    return {
        "name": name,
        "filename": filename,
        "width": width,
        "height": height,
        "fcu": fcu,
        "bcu": bcu,
        "nets": len(nets),
        "layer": target,
        "tracks": norm,
        "gcode": "\n".join(gcode_lines) + "\n",
        "gcodeLines": len(gcode_lines),
        "drawMoves": len(layer_tracks),
        "travelMoves": len(layer_tracks) + 1,
        "penUpBefore": pen_up_before,
        "penUpAfter": pen_up_after,
        "size": f"{width} × {height}",
        "estMinutes": est_minutes,
    }


def build_board_from_strokes(strokes: list, name: str, filename: str,
                             params: TraceParams, info: dict) -> dict:
    """A traced image as the same board document `build_board` produces.

    `strokes` is the geometry, and the G-code comes from it. A KiCad board
    stores `tracks` because that is genuinely what it is; a traced one does
    not, because a stroke is a path and flattening it loses that.
    """
    minx, miny, maxx, maxy = emit.bounds(strokes)
    width = round(maxx - minx, 2)
    height = round(maxy - miny, 2)

    gcode_lines = emit.generate_from_strokes(strokes, label=name)
    frame_lines = emit.emit_frame((minx, miny, maxx, maxy))
    report = emit.stroke_report(strokes)

    return {
        "name": name,
        "filename": filename,
        "width": width,
        "height": height,
        # A traced job is one layer with one "net". Reporting the stroke count
        # as fcu keeps the existing summary tiles honest rather than blank.
        "fcu": len(strokes),
        "bcu": 0,
        "nets": 1,
        "layer": "F.Cu",
        # Strokes are the only geometry a traced board keeps. They were once
        # also flattened into two-point `tracks` so the SVG preview could
        # render them unchanged; the preview now draws strokes directly, and
        # the flattened copy was 63% of the stored document for nothing.
        "strokes": [[list(p) for p in s] for s in strokes],
        # A decimated copy for the boards list, so a grid of traced boards
        # does not ship megabytes of geometry to draw postage stamps.
        "thumbStrokes": [[list(p) for p in s]
                         for s in emit.thumbnail_strokes(strokes)],
        "gcode": "\n".join(gcode_lines) + "\n",
        "gcodeLines": len(gcode_lines),
        "frameGcode": "\n".join(frame_lines) + "\n",
        "drawMoves": report["drawMoves"],
        "travelMoves": report["travelMoves"],
        "penUpBefore": report["penUpBefore"],
        "penUpAfter": report["penUpAfter"],
        "size": f"{width} × {height}",
        "estMinutes": report["estMinutes"],
        "source": "image",
        "traceParams": {
            "size_mm": params.size_mm,
            "mode": params.mode,
            "preset": params.preset,
            "threshold": params.threshold,
            "invert": params.invert,
            "hatch_spacing_mm": params.hatch_spacing_mm,
            "hatch_angle": params.hatch_angle,
            "hatch_cross": params.hatch_cross,
        },
        "traceInfo": info,
    }


# ----------------------------------------------------------------- serializers
def out_user(doc: dict) -> dict:
    return {"name": doc["name"], "email": doc["email"]}


def out_device(doc: dict) -> dict:
    d = {k: v for k, v in doc.items() if k not in ("_id", "user_email")}
    d["id"] = doc["device_id"]
    return d


def out_board(doc: dict, full: bool = False) -> dict:
    d = {
        "id": str(doc["_id"]),
        "name": doc["name"],
        "filename": doc["filename"],
        "width": doc["width"],
        "height": doc["height"],
        "fcu": doc["fcu"],
        "bcu": doc["bcu"],
        "nets": doc["nets"],
        "layer": doc["layer"],
        "gcodeLines": doc["gcodeLines"],
        "drawMoves": doc["drawMoves"],
        "travelMoves": doc["travelMoves"],
        "penUpBefore": doc["penUpBefore"],
        "penUpAfter": doc["penUpAfter"],
        "size": doc["size"],
        "estMinutes": doc["estMinutes"],
        "status": doc.get("status", "ready"),
        "createdAt": doc["createdAt"].isoformat() if isinstance(
            doc.get("createdAt"), datetime) else doc.get("createdAt"),
    }
    # Tracks travel with the summary (for list thumbnails) whenever present;
    # the heavy gcode string is only attached on the full board view.
    traced = doc.get("source") == "image"
    if traced:
        # A traced board is strokes, full stop. The summary carries only the
        # decimated set; the full view gets every point.
        d["strokes"] = doc["strokes"] if full else doc.get(
            "thumbStrokes", doc.get("strokes", []))
    elif "tracks" in doc:
        d["tracks"] = doc["tracks"]
    # Traced boards carry their provenance so the UI can offer a re-trace.
    for key in ("source", "traceParams", "traceInfo"):
        if key in doc:
            d[key] = doc[key]
    # Whether re-tracing is possible at all. Boards traced before source
    # images were kept have provenance but nothing to trace again.
    d["hasSource"] = bool(doc.get("sourceFile"))
    if full:
        d["gcode"] = doc["gcode"]
        if "frameGcode" in doc:
            d["frameGcode"] = doc["frameGcode"]
    return d


# --------------------------------------------------------------------- models
class SignUp(BaseModel):
    name: str
    email: str
    password: str


class LogIn(BaseModel):
    email: str
    password: str


class Pair(BaseModel):
    email: str
    device_id: str


class Email(BaseModel):
    email: str


class RenameBoard(BaseModel):
    name: str


class RenameDevice(BaseModel):
    alias: str


class PrintJob(BaseModel):
    email: str
    board_id: str
    check: bool = False


# --------------------------------------------------------------- ESP32 bridge
ESP_TIMEOUT = 4  # seconds; a dead bridge should fail fast


def esp_base(device: dict) -> str:
    """Base URL of the ESP32 bridge for a device. ESP_BASE_URL overrides it
    (handy for the esp_mock.py bench test); otherwise use the paired device's
    network address stored in its `port` field."""
    override = os.environ.get("ESP_BASE_URL")
    if override:
        return override.rstrip("/")
    ip = device.get("port")
    if not ip:
        raise HTTPException(400, "Paired device has no network address.")
    return f"http://{ip}"


def esp_request(url: str, method: str = "GET", data: bytes = None,
                headers: dict = None):
    """Call the ESP32 bridge; return (status, parsed_json). Raises 502 if the
    bridge is unreachable."""
    req = urllib.request.Request(
        url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=ESP_TIMEOUT) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {"error": body or f"HTTP {e.code}"}
        return e.code, payload
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise HTTPException(502, f"Can't reach the plotter bridge: {e}")


def _device_for(email: str) -> dict:
    doc = db.devices.find_one({"user_email": email.strip().lower()})
    if not doc:
        raise HTTPException(400, "No paired device for this account.")
    return doc


# ------------------------------------------------------------------- endpoints
@app.get("/")
def health():
    try:
        db.ping()
        return {"status": "ok", "db": "connected", "database": db.DB_NAME}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"database unreachable: {e}")


@app.post("/auth/signup")
def signup(body: SignUp):
    email = body.email.strip().lower()
    if not email or not body.password:
        raise HTTPException(400, "Email and password are required.")
    if db.users.find_one({"email": email}):
        raise HTTPException(409, "An account with that email already exists.")
    db.users.insert_one({
        "name": body.name.strip() or email.split("@")[0],
        "email": email,
        "password": hash_password(body.password),
        "createdAt": datetime.now(timezone.utc),
    })
    return {"name": body.name.strip() or email.split("@")[0], "email": email}


@app.post("/auth/login")
def login(body: LogIn):
    email = body.email.strip().lower()
    user = db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password"]):
        raise HTTPException(401, "Wrong email or password.")
    return out_user(user)


@app.get("/devices/{email}")
def get_device(email: str):
    doc = db.devices.find_one({"user_email": email.strip().lower()})
    return out_device(doc) if doc else None


@app.post("/devices/pair")
def pair(body: Pair):
    email = body.email.strip().lower()
    device_id = body.device_id.strip().upper()
    if not device_id:
        raise HTTPException(400, "A device ID is required.")
    doc = {"user_email": email, **default_device(device_id),
           "pairedAt": datetime.now(timezone.utc)}
    db.devices.replace_one({"user_email": email}, doc, upsert=True)
    return out_device(doc)


@app.post("/devices/unpair")
def unpair(body: Email):
    db.devices.delete_one({"user_email": body.email.strip().lower()})
    return {"ok": True}


@app.post("/route")
async def route(file: UploadFile = File(...), email: str = Form(...)):
    raw = await file.read()
    text = raw.decode("utf-8", errors="replace")
    try:
        wiring = extract_wiring(text)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not parse this file: {e}")

    name = (file.filename or "board").rsplit(".", 1)[0]
    board = build_board(wiring, name=name, filename=file.filename or "board.kicad_pcb")
    board["user_email"] = email.strip().lower()
    board["status"] = "ready"
    board["createdAt"] = datetime.now(timezone.utc)
    res = db.boards.insert_one(board)
    board["_id"] = res.inserted_id
    return out_board(board, full=True)


@app.post("/trace")
async def trace(file: UploadFile = File(...), email: str = Form(...),
                size_mm: float = Form(50.0), mode: str = Form("centerline"),
                preset: str = Form("line"), threshold: int | None = Form(None),
                invert: bool = Form(False),
                hatch_spacing_mm: float = Form(0.4),
                hatch_angle: float = Form(45.0),
                hatch_cross: bool = Form(False)):
    """Trace a raster image to single-line strokes and store it as a board.

    Produces the same document shape as /route, so the projects grid, the
    preview, and the print path all work on a traced board unchanged.
    """
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(
            400, "That is not an image. Upload a PNG, JPG, BMP, or WEBP — "
                 "or use the board upload for a .kicad_pcb file.")

    raw = await file.read()
    params = TraceParams(size_mm=size_mm, mode=mode, preset=preset,
                         threshold=threshold, invert=invert,
                         hatch_spacing_mm=hatch_spacing_mm,
                         hatch_angle=hatch_angle, hatch_cross=hatch_cross)
    try:
        strokes, info = trace_image(raw, params)
    except TraceError as e:
        raise HTTPException(400, str(e))

    name = (file.filename or "traced").rsplit(".", 1)[0]
    board = build_board_from_strokes(
        strokes, name=name, filename=file.filename or "traced.png",
        params=params, info=info)
    # Keep the original so the trace can be tuned without re-uploading it.
    board["sourceFile"] = db.sources.put(
        raw, filename=file.filename or "traced.png",
        contentType=file.content_type or "image/png")
    board["user_email"] = email.strip().lower()
    board["status"] = "ready"
    board["createdAt"] = datetime.now(timezone.utc)
    res = db.boards.insert_one(board)
    board["_id"] = res.inserted_id
    return out_board(board, full=True)


class Retrace(BaseModel):
    size_mm: float = 50.0
    mode: str = "centerline"
    preset: str = "line"
    threshold: int | None = None
    invert: bool = False
    hatch_spacing_mm: float = 0.4
    hatch_angle: float = 45.0
    hatch_cross: bool = False


@app.post("/board/{board_id}/retrace")
def retrace(board_id: str, body: Retrace):
    """Trace a stored board's source image again with different settings.

    Updates the board in place: the id, name, and creation date survive, so
    the link the user is looking at keeps working and a rename is not undone.
    Getting a trace right is iterative, and re-uploading the file each round
    is the friction worth removing.
    """
    try:
        oid = ObjectId(board_id)
    except InvalidId:
        raise HTTPException(404, "Board not found.")
    board = db.boards.find_one({"_id": oid})
    if not board:
        raise HTTPException(404, "Board not found.")

    source_id = board.get("sourceFile")
    if not source_id:
        raise HTTPException(
            400, "This board has no source image to re-trace. Only boards "
                 "made from an uploaded image can be re-traced.")
    try:
        raw = db.sources.get(source_id).read()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "The source image for this board is missing.")

    params = TraceParams(size_mm=body.size_mm, mode=body.mode,
                         preset=body.preset, threshold=body.threshold,
                         invert=body.invert,
                         hatch_spacing_mm=body.hatch_spacing_mm,
                         hatch_angle=body.hatch_angle,
                         hatch_cross=body.hatch_cross)
    try:
        strokes, info = trace_image(raw, params)
    except TraceError as e:
        raise HTTPException(400, str(e))

    # Rebuild the geometry, but keep what the user owns: the name they gave
    # it, when it was made, and the source image itself.
    fresh = build_board_from_strokes(
        strokes, name=board["name"], filename=board["filename"],
        params=params, info=info)
    fresh.pop("name", None)
    fresh.pop("filename", None)

    updated = db.boards.find_one_and_update(
        {"_id": oid}, {"$set": fresh},
        return_document=ReturnDocument.AFTER)
    return out_board(updated, full=True)


@app.get("/boards/{email}")
def list_boards(email: str):
    cur = db.boards.find(
        {"user_email": email.strip().lower()},
        {"gcode": 0},
    ).sort("createdAt", -1)
    return [out_board(d) for d in cur]


@app.get("/board/{board_id}")
def get_board(board_id: str):
    try:
        oid = ObjectId(board_id)
    except InvalidId:
        raise HTTPException(404, "Board not found.")
    doc = db.boards.find_one({"_id": oid})
    if not doc:
        raise HTTPException(404, "Board not found.")
    return out_board(doc, full=True)


@app.post("/print")
def start_print(body: PrintJob):
    """Send a board's G-code to the paired ESP32 bridge. `check` runs GRBL's
    validate-only mode ($C) first."""
    device = _device_for(body.email)
    try:
        oid = ObjectId(body.board_id)
    except InvalidId:
        raise HTTPException(404, "Board not found.")
    board = db.boards.find_one({"_id": oid})
    if not board:
        raise HTTPException(404, "Board not found.")
    gcode = board.get("gcode")
    if not gcode:
        raise HTTPException(400, "This board has no G-code to send.")

    headers = {"Content-Type": "text/plain"}
    if body.check:
        headers["X-Check"] = "1"
    status, payload = esp_request(
        f"{esp_base(device)}/print", method="POST",
        data=gcode.encode("utf-8"), headers=headers)
    if status >= 400:
        raise HTTPException(502, payload.get("error", "Plotter rejected the job."))
    return payload


@app.get("/print/status/{email}")
def print_status(email: str):
    device = _device_for(email)
    status, payload = esp_request(f"{esp_base(device)}/status")
    if status >= 400:
        raise HTTPException(502, payload.get("error", "Plotter status unavailable."))
    return payload


@app.post("/print/stop")
def print_stop(body: Email):
    device = _device_for(body.email)
    _status, payload = esp_request(
        f"{esp_base(device)}/stop", method="POST", data=b"")
    return payload


@app.patch("/board/{board_id}")
def rename_board(board_id: str, body: RenameBoard):
    try:
        oid = ObjectId(board_id)
    except InvalidId:
        raise HTTPException(404, "Board not found.")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "A board name is required.")
    doc = db.boards.find_one_and_update(
        {"_id": oid},
        {"$set": {"name": name}},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise HTTPException(404, "Board not found.")
    return out_board(doc, full=True)


@app.patch("/devices/{email}")
def rename_device(email: str, body: RenameDevice):
    alias = body.alias.strip()
    if not alias:
        raise HTTPException(400, "A device name is required.")
    doc = db.devices.find_one_and_update(
        {"user_email": email.strip().lower()},
        {"$set": {"alias": alias}},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise HTTPException(404, "No paired device for this account.")
    return out_device(doc)


@app.delete("/board/{board_id}")
def delete_board(board_id: str):
    try:
        oid = ObjectId(board_id)
    except InvalidId:
        raise HTTPException(404, "Board not found.")
    # Drop the source image too, or GridFS fills with orphans no one can reach.
    doc = db.boards.find_one({"_id": oid})
    if doc and doc.get("sourceFile"):
        try:
            db.sources.delete(doc["sourceFile"])
        except Exception:  # noqa: BLE001
            pass
    db.boards.delete_one({"_id": oid})
    return {"ok": True}


if __name__ == "__main__":
    # `python server.py` should just work; `uvicorn server:app --reload` is
    # the same thing spelled out. reload=True watches the .py files and
    # restarts on save.
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
