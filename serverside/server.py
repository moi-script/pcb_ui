"""TraceWorks API — the server side of the web UI.

Wraps the KiCad -> G-code pipeline in an HTTP API and stores accounts, routed
boards, and the last serial port used in MongoDB. The Next.js frontend
(userpage) talks to this over HTTP.

The machine itself hangs off a USB cable on this PC: the backend owns the
serial port and the /machine/* routes drive it. A browser tab cannot open a
COM port; localhost:8000 can.

Run it:
    uvicorn server:app --reload --port 8000

Endpoints:
    GET  /                     health + db status
    POST /auth/signup          {name,email,password} -> user
    POST /auth/login           {email,password}      -> user
    POST /route                (multipart: file, email) -> routed board
    POST /trace                (multipart: file, email, size_mm, mode, preset) -> traced board
    POST /board/{id}/retrace   {size_mm, mode, preset, ...} -> re-traced board
    GET  /boards/{email}       -> [board summary]
    GET  /board/{id}           -> board (with geometry + gcode)
    DELETE /board/{id}

    GET  /machine/ports        -> serial ports, chip names, a suggestion
    POST /machine/connect      {port, baud, email?}  -> firmware banner
    POST /machine/disconnect
    GET  /machine/state        -> the machine snapshot
    GET  /machine/last         ?email= -> {port, baud} | null
    WS   /machine/ws           -> snapshots, console lines, job progress
    POST /machine/jog | jog/cancel | home | unlock | zero | command | estop
    POST /machine/run          {board_id, check} -> stream a board's G-code
    POST /machine/pause | resume | stop

Trace modes: centerline (down the middle of each stroke), outline (around each
shape), fill (outline plus hatching — the one that actually covers copper for
etch resist).
"""
import asyncio
import hashlib
import json
import math
import logging
import os
import secrets
import time
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import (FastAPI, File, Form, HTTPException, UploadFile,
                     WebSocket, WebSocketDisconnect)
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
from pymongo import ReturnDocument

import db
from grbl import ports as grbl_ports
from grbl.limits import AXIS_INDEX, EPS, LimitError, check_program, program_extents
from grbl.profile import DEFAULT_PROFILE
from grbl.protocol import Realtime, encode_jog, encode_zero
from job import load_lines
from machine import SIM_PORT, PositionUncertain, make_transport, session
from pcb_gcode import CONFIG, generate_gcode, optimize_order, travel_distance
from pcb_read import extract_wiring, layer_usage
from tracer import TraceError, TraceParams, trace_image
from tracer import emit

# --------------------------------------------------------- terminal narration
# uvicorn installs handlers for its OWN loggers and nothing else; every other
# logger propagates to a bare root that drops anything below WARNING on the
# floor. So the `traceworks` tree gets its own handler here, and a plot
# narrates itself — what started, how far in it is, what it stopped on — in
# the terminal already running the server. Guarded because `--reload`
# re-imports this module, and a second handler would double every line.
_narration = logging.getLogger("traceworks")
if not _narration.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
    _narration.addHandler(_handler)
    _narration.setLevel(logging.INFO)
    _narration.propagate = False


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


# ------------------------------------------------------------- board building
def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def reject_if_double_sided(wiring: list) -> None:
    """Refuse anything a pen plotter cannot draw in one pass.

    The pen reaches one face of the work. A board with copper on both sides
    cannot be plotted faithfully, and a via exists precisely to cross between
    layers, so neither can be honoured. Before this check the router silently
    plotted F.Cu and dropped everything else, which returned a board that
    looked complete and was missing most of its copper.
    """
    usage = layer_usage(wiring)
    counts, layers, vias = usage["tracks"], usage["layers"], usage["vias"]
    if len(layers) <= 1 and not vias:
        return

    def plural(n: int, word: str) -> str:
        return f"{n} {word}" + ("" if n == 1 else "s")

    per_layer = ", ".join(f"{counts[layer]} on {layer}" for layer in layers)
    if len(layers) > 1:
        lead = f"This board is double-sided: {per_layer}"
        if vias:
            lead += f", plus {plural(vias, 'via')}"
    else:
        lead = (f"This board has {per_layer}, but also {plural(vias, 'via')}, "
                "which cross between copper layers")

    raise HTTPException(400, (
        f"{lead}. A pen plotter draws one face of the work, so only "
        "single-layer boards can be routed. Re-route the board onto one copper "
        "layer with no vias, then upload it again."
    ))


def reject_if_off_the_bed(width: float, height: float) -> None:
    """Refuse a board that cannot be drawn, at the moment it is uploaded.

    Caught here rather than at plot time because this is where the operator
    can still do something about it: the answer is to shrink the board or
    re-route it, and being told that while looking at the file beats being
    told it with the pen in the air.
    """
    bed_x, bed_y = session.profile.travel_x, session.profile.travel_y
    if width <= bed_x + 1e-6 and height <= bed_y + 1e-6:
        return
    raise HTTPException(400, (
        f"This board is {width:g} x {height:g} mm, and the bed is "
        f"{bed_x:g} x {bed_y:g} mm. Re-route it to fit, or trace it at a "
        f"smaller size."
    ))


def build_board(wiring: list, name: str, filename: str) -> dict:
    """Turn raw wiring data into a stored board document: normalized tracks,
    bounds, per-layer counts, G-code, and a route report."""
    tracks = [w for w in wiring if w["type"] == "track"]
    if not tracks:
        raise HTTPException(400, "No copper tracks found in this file.")

    reject_if_double_sided(wiring)

    xs = [c for w in tracks for c in (w["start"][0], w["end"][0])]
    ys = [c for w in tracks for c in (w["start"][1], w["end"][1])]
    minx, miny = min(xs), min(ys)
    width = round(max(xs) - minx, 2)
    height = round(max(ys) - miny, 2)
    reject_if_off_the_bed(width, height)

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
    # rough time: draw + travel at their feeds, plus a pen drop and lift
    # (1 mm of Z each, at z_feed) per track
    pen_moves = len(layer_tracks) * 2 * abs(cfg["pen_up_z"] - cfg["pen_down_z"])
    est_minutes = max(
        1,
        math.ceil(draw_len / cfg["draw_feed"]
                  + pen_up_after / cfg["travel_feed"]
                  + pen_moves / cfg["z_feed"]),
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
    reject_if_off_the_bed(width, height)

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


def refresh_legacy_gcode(doc: dict) -> dict:
    """Rebuild G-code saved before work zero moved to the top-left corner.

    Old boards hang above a bottom-left zero (Y up to +height); the bed now
    runs 0 .. -height below the pen, so that file would be refused or send
    the pen up off the bed. The stored geometry is unaffected, so the G-code
    is regenerated from it and saved back — once, the first time the board
    is opened or run. A board already top-left is returned untouched.
    """
    extents = program_extents((doc.get("gcode") or "").splitlines())
    if extents is None or extents[3] <= EPS:
        return doc

    fields: dict = {}
    if doc.get("source") == "image" and doc.get("strokes"):
        strokes = [[tuple(p) for p in s] for s in doc["strokes"]]
        lines = emit.generate_from_strokes(strokes, label=doc["name"])
        fields["gcode"] = "\n".join(lines) + "\n"
        fields["gcodeLines"] = len(lines)
        fields["frameGcode"] = "\n".join(
            emit.emit_frame(emit.bounds(strokes))) + "\n"
    elif doc.get("tracks"):
        wiring = [{"type": "track", "layer": t["layer"],
                   "start": (t["x1"], t["y1"]), "end": (t["x2"], t["y2"])}
                  for t in doc["tracks"]]
        cfg = dict(CONFIG)
        cfg["layer"] = doc["layer"]
        lines = generate_gcode(wiring, cfg)
        fields["gcode"] = "\n".join(lines) + "\n"
        fields["gcodeLines"] = len(lines)
    else:
        return doc

    db.boards.update_one({"_id": doc["_id"]}, {"$set": fields})
    return {**doc, **fields}


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


class Email(BaseModel):
    email: str


class RenameBoard(BaseModel):
    name: str


class ConnectRequest(BaseModel):
    port: str
    baud: int = 115200
    email: str | None = None


class JogRequest(BaseModel):
    axis: str
    distance: float
    feed: float = DEFAULT_PROFILE.jog_feed  # grbl_servo_z's $110 cap


class ZeroRequest(BaseModel):
    axes: str


class CommandRequest(BaseModel):
    line: str


class RunRequest(BaseModel):
    board_id: str
    check: bool = False


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
    return out_board(refresh_legacy_gcode(doc), full=True)


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


# ------------------------------------------------------------------- machine
#
# The backend runs on the same PC as the browser, so it — not the tab — owns
# the serial port. Everything here drives the one `machine.session`.

@app.get("/machine/ports")
def machine_ports():
    """Serial ports, controller-looking ones first.

    `suggested` is filled only when exactly one candidate is present:
    guessing between two plausible boards is worse than asking, and picking
    the wrong one moves a machine.
    """
    try:
        found = grbl_ports.list_ports()
    except Exception:  # noqa: BLE001 - a broken enumeration is not fatal
        # ...but it must not be silent: an empty list with no reason is
        # indistinguishable from "nothing is plugged in".
        logging.getLogger("traceworks.ports").exception(
            "listing serial ports failed")
        found = []
    payload = [
        {
            "device": p.device,
            "description": p.description,
            "chip": p.chip,
            "likely_controller": p.likely_controller,
        }
        for p in found
    ]
    suggested = grbl_ports.autoselect(found)

    if os.environ.get("TRACEWORKS_SIM") == "1":
        payload.append({
            "device": SIM_PORT,
            "description": "Simulator (GRBL 1.1) — no hardware",
            "chip": None,
            "likely_controller": False,
        })
        if suggested is None:
            suggested = SIM_PORT

    return {"ports": payload, "suggested": suggested,
            "bauds": grbl_ports.BAUD_RATES}


@app.post("/machine/connect")
def machine_connect(body: ConnectRequest):
    job = session.job
    if job is not None and job.state in ("running", "paused"):
        # Reopening the port reboots the Arduino: the plot would die halfway
        # and the pen would be left wherever it was.
        raise HTTPException(
            409, f"A plot is running on {session.state.port} ('{job.name}'). "
                 "Stop it before connecting again.")
    try:
        transport = make_transport(body.port, body.baud)
    except Exception as exc:  # noqa: BLE001 - pyserial raises many shapes
        raise HTTPException(502, f"Could not open {body.port}: {exc}") from exc
    firmware = session.connect(transport, body.port, body.baud)
    if body.email:
        # A convenience crumb so Connect is one click next session. It carries
        # no identity and no authority: it cannot make a port exist, and
        # connecting never consults it.
        email = body.email.strip().lower()
        db.machines.replace_one(
            {"user_email": email},
            {"user_email": email,
             "last_port": body.port, "last_baud": body.baud},
            upsert=True,
        )
    return {"ok": True, "firmware": firmware}


@app.get("/machine/last")
def machine_last(email: str):
    doc = db.machines.find_one({"user_email": email.strip().lower()})
    if not doc:
        return None
    return {"port": doc["last_port"], "baud": doc["last_baud"]}


@app.post("/machine/disconnect")
def machine_disconnect():
    session.disconnect()
    return {"ok": True}


@app.get("/machine/state")
def machine_state():
    return session.state.snapshot()


@app.post("/machine/jog")
def machine_jog(body: JogRequest) -> dict:
    axis, distance, feed = body.axis, body.distance, body.feed
    streamer = session.require()

    # ONE atomic read of the machine picture, before anything else. Every
    # input to the safety decision below -- machine state, position, the
    # status counter, and whether that status report was dispatched with a
    # quiet streamer -- comes out of this single snapshot. Reading them
    # separately lets an incoming report land between two of the reads and
    # pair a NEWER counter with OLDER coordinates, which is exactly the
    # combination that would wrongly lift a taint and then validate against
    # a stale position. `snapshot()` copies its lists under
    # MachineState._lock, so nothing here can be rebound underneath us.
    #
    # `streamer.quiet` is read here too, before any leaf lock: the
    # established order is Streamer._lock -> MachineState._lock -> leaf, and
    # `_planned_lock` (taken inside settle/reserve_jog) must never be held
    # while wanting Streamer._lock.
    quiet = streamer.quiet
    snap = session.state.snapshot()
    current_state = snap["state"]
    if current_state.startswith("Alarm"):
        # Refuse outright rather than send a jog GRBL will bounce with
        # error:9 -- and taint: whatever was in flight before the alarm
        # tripped stopped at an unknown point, so any tracked target (or a
        # fallback to live mpos, which may also be stale) can no longer be
        # trusted. This is what closes the C1 hole: no jog issued in Alarm
        # can ever reach `reserve_jog` and poison the base.
        session.taint_planned()
        raise HTTPException(400, "Machine is in Alarm. Unlock ($X) before jogging.")

    # The position from that same snapshot — already a private copy, so no
    # later report can rebind it underneath the checks below.
    m = snap["mpos"]

    # If the controller reports Idle, the live position may be
    # authoritative again: clear a matched planned target, or lift a taint
    # if (and only if) this report proves the queue drained — see
    # Session.settle. No dedicated polling loop — this rides along on the
    # jog route, which is exactly where the decision is needed.
    session.settle(snap, quiet)

    # Validate and reserve atomically against the end of the last jog we
    # queued, not the live position: rapid successive jogs (including two
    # truly concurrent requests racing on FastAPI's threadpool) land here
    # before the controller has reported back, so live mpos still lags.
    # `reserve_jog` falls back to live mpos only when nothing is tracked
    # (or once `settle` has confirmed settling), and refuses outright when
    # tainted rather than guessing.
    try:
        session.reserve_jog(m, axis, distance)
    except PositionUncertain as exc:
        raise HTTPException(400, str(exc)) from exc
    except LimitError as exc:
        raise HTTPException(400, str(exc)) from exc

    try:
        streamer.send_line(encode_jog(axis, distance, feed))
    except OSError:
        # We don't know whether the controller ever saw the line. The
        # reservation `reserve_jog` just made is no longer trustworthy
        # either way (accepted-but-unconfirmed, or never sent at all), so
        # poison it rather than leave an unverified target on the books.
        session.taint_planned()
        raise HTTPException(
            502, "Lost connection to the machine while sending the jog."
        ) from None

    if not streamer.connected:
        # Streamer.send_line can also fail "successfully": it swallows
        # OSError internally and just marks the connection dead (see
        # Streamer._drop) rather than raising. Either way the line's fate
        # is unknown, so the same poisoning applies.
        session.taint_planned()

    return {"ok": True}


@app.post("/machine/jog/cancel")
def machine_jog_cancel() -> dict:
    # Jog cancel decelerates and stops -- the exact stopping point isn't
    # known synchronously, and live mpos hasn't caught up to it yet either
    # (same lag `_planned` exists to cover). Taint rather than clear: the
    # next jog is refused until a confirmed Idle report proves where the
    # machine actually stopped.
    streamer = session.require()
    streamer.send_realtime(Realtime.JOG_CANCEL)
    session.taint_and_resync(streamer)
    return {"ok": True}


@app.post("/machine/home")
def machine_home() -> dict:
    # $H runs a real homing cycle -- motion, not an instant coordinate
    # change. Taint rather than clear: live mpos still reflects the
    # pre-home position until the cycle completes and reports Idle, so
    # clearing to None here would reopen the exact stale-live-mpos hole
    # this mechanism exists to close, just triggered by home instead of a
    # jog.
    streamer = session.require()
    streamer.send_line("$H")
    session.taint_and_resync(streamer)
    return {"ok": True}


@app.post("/machine/unlock")
def machine_unlock() -> dict:
    # Alarm halts all motion outright -- nothing is left in flight for the
    # position to be uncertain about, so the live position is trustworthy
    # the instant the controller leaves Alarm. Round 2 cleared straight to
    # None here on that reasoning, which was the ONE call site left lifting
    # a taint with no confirmation and no resync at all -- inconsistent
    # with every other taint-clearing path in this file, all of which now
    # require an observed-after-the-fact status report (see
    # taint_and_resync / settle, N1). Using taint_and_resync costs nothing
    # here: the machine genuinely is Idle right after $X, so the very next
    # status report clears it -- but it does so through the same
    # observed-after-taint mechanism as everywhere else, rather than an
    # unconditional bare clear.
    streamer = session.require()
    streamer.send_line("$X")
    session.taint_and_resync(streamer)
    return {"ok": True}


@app.post("/machine/zero")
def machine_zero(body: ZeroRequest) -> dict:
    axes = body.axes
    streamer = session.require()
    axes = axes.upper()
    if not axes or any(a not in AXIS_INDEX for a in axes):
        raise HTTPException(400, f"axes must be made up of X, Y, Z — got {axes!r}")
    if "Z" in axes:
        # grbl_servo_z switches the pen on MACHINE Z (below 0 is down). A Z
        # work offset moves every G-code Z but not that switch, so "pen up"
        # can land below it and the pen drags between traces.
        raise HTTPException(
            400, "Z can't be zeroed: the pen servo follows machine Z, so a "
                 "Z offset would leave the pen down between traces. Zero X "
                 "and Y only.")
    streamer.send_line(encode_zero(axes))
    # G10 L20 itself doesn't move the machine, but this route can't prove a
    # jog isn't still draining through the queue underneath it (the ZERO
    # buttons sit in the same jog panel and are clickable mid-jog). Taint
    # unconditionally rather than try to detect in-flight motion -- that
    # detection is exactly what would need the same live-mpos fallback this
    # mechanism exists to distrust.
    session.taint_and_resync(streamer)
    return {"ok": True}


_REALTIME_CHARS: dict[str, bytes] = {
    "?": Realtime.STATUS,
    "!": Realtime.FEED_HOLD,
    "~": Realtime.RESUME,
    "\x18": Realtime.SOFT_RESET,
}


@app.post("/machine/command")
def machine_command(body: CommandRequest) -> dict:
    line = body.line
    streamer = session.require()
    text = line.strip()
    if not text:
        raise HTTPException(400, "empty command")
    if "\n" in text or "\r" in text:
        raise HTTPException(400, "one command per line")
    if len(text) == 1 and text in _REALTIME_CHARS:
        # A single realtime character (?, !, ~, ^X) must never go through
        # send_line: it would be charged against the RX buffer and never
        # acknowledged, permanently shrinking the flow-control budget for
        # the rest of the session. Route it through the realtime channel
        # instead — this also makes it useful (an operator can type ? for
        # a status poll or ! to feed-hold from the console input).
        streamer.send_realtime(_REALTIME_CHARS[text])
        # ^X (soft reset) in particular can interrupt motion; the others
        # don't move the machine on their own, but tainting unconditionally
        # here costs nothing and stays on the safe side.
        session.taint_and_resync(streamer)
        return {"ok": True}
    streamer.send_line(text)
    # A raw console command can itself be a motion line (or $H, or M3/M5
    # spindle control -- the PEN UP/DOWN buttons go through this exact
    # route -- or anything else that moves the machine or redefines its
    # origin) that this route has no way to parse and fold into `_planned`.
    # Falling back to live mpos here (the old `clear_planned()` behavior)
    # is exactly the C2 hole: mpos hasn't caught up to whatever this line
    # just started, so a subsequent jog checked against it could pass when
    # it should not. Taint instead: refuse the next jog until a confirmed
    # Idle report proves the position again.
    session.taint_and_resync(streamer)
    return {"ok": True}


@app.post("/machine/estop")
def machine_estop() -> dict:
    """Soft reset, immediately. No feed hold, no queue, no confirmation."""
    streamer = session.streamer
    if streamer is None:
        raise HTTPException(409, "Machine is not connected.")
    streamer.send_realtime(Realtime.SOFT_RESET)
    # Taint, do NOT clear. A soft reset aborts motion mid-move: the machine
    # decelerates (or is cut) at a point nobody knows, and live mpos has
    # certainly not caught up to it -- so "trust live mpos", which is what
    # clear_planned() means, is the stale-low fallback this whole mechanism
    # exists to distrust. Round 3 argued it was moot because the jog route's
    # Alarm gate refuses afterwards anyway; that leans on the controller
    # actually reaching (and reporting) Alarm, which is a second mechanism's
    # behaviour, not this one's. Tainting is correct on its own terms.
    #
    # Deliberately NOT taint_and_resync: e-stop must return instantly and
    # must never wait on the link. The taint lifts through the ordinary
    # settle() path once a status report proves the machine is Idle with
    # nothing of ours outstanding.
    session.taint_planned()
    return {"ok": True}


@app.post("/machine/run")
def machine_run(body: RunRequest):
    """Stream a stored board's G-code to the connected machine.

    `check` brackets the job with GRBL's $C: every line is parsed and
    validated, no motor moves. It is the cheapest way to find out the file
    is acceptable before it is also expensive to be wrong about.
    """
    # The connection is checked before the board is looked up: "no machine
    # is connected" is the answer the operator can act on, and it should not
    # depend on whether the board id also happened to be good.
    session.require()

    try:
        oid = ObjectId(body.board_id)
    except InvalidId:
        raise HTTPException(404, "Board not found.")
    board = db.boards.find_one({"_id": oid})
    if not board:
        raise HTTPException(404, "Board not found.")
    board = refresh_legacy_gcode(board)
    gcode = board.get("gcode")
    if not gcode:
        raise HTTPException(400, "This board has no G-code to send.")

    lines = load_lines(gcode)
    if not lines:
        raise HTTPException(400, "This board's G-code has no instructions.")

    # The last gate before the bytes go out. Boards routed before the
    # generator moved its output to the origin still carry their KiCad
    # sheet coordinates — a hundred millimetres off the bed — and streaming
    # one alarms the machine mid-plot, which costs the operator the work
    # zero they set by hand. Refusing here costs a sentence.
    try:
        check_program(session.profile, lines)
    except LimitError as exc:
        raise HTTPException(
            400,
            f"This board will not fit the {session.profile.travel_x:g} x "
            f"{session.profile.travel_y:g} mm bed: {exc}. Upload the file "
            "again to re-route it against the current bed.",
        )

    logging.getLogger("traceworks.run").info(
        "run requested: board %r (%d lines) -> %s",
        board.get("name", "board"), len(lines), session.state.port,
    )
    job = session.start_job(lines, body.check, board.get("name", "board"))
    return {"ok": True, "total": len(lines), "check": job.check}


@app.post("/machine/pause")
def machine_pause():
    session.require_job().pause()
    return {"ok": True}


@app.post("/machine/resume")
def machine_resume():
    session.require_job().resume()
    return {"ok": True}


@app.post("/machine/stop")
def machine_stop():
    session.require_job().stop()
    return {"ok": True}


@app.post("/machine/restart")
def machine_restart():
    """Stop the current job and run the same file again from the top.

    Blocks for as long as the machine takes to come to rest — a second or
    so of queued moves — because streaming a new file into a head that is
    still finishing the old one is how a plot ends up drawn twice.
    """
    session.require()
    logging.getLogger("traceworks.run").info(
        "restart requested for %r", session.require_job().name
    )
    job = session.restart_job()
    return {"ok": True, "total": len(job.lines), "check": job.check}


# --------------------------------------------------------- live machine state

@app.websocket("/machine/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    """The live feed. Every read of machine state goes through
    `run_in_threadpool`, deliberately.

    These calls take the link lock, which the streamer thread holds while it
    writes to the serial port. Called directly from this coroutine, a write
    that blocks for even a moment blocks the ONLY event loop, and with it
    every other request the server has — a stalled cable would look like a
    dead API. On a worker thread it stalls this socket alone.
    """
    await websocket.accept()

    # `state` tracks the MachineState object this loop is currently reading.
    # Session.connect() rebinds session.state to a brand-new MachineState on
    # every reconnect, which restarts both `seq` and console seq numbering at
    # 0. A seq-based "did it go backwards" check is a proxy for that with a
    # hole: a short-lived prior connection can leave the cursor small (a
    # failed connect logs only "disconnected", seq 0 or 1), and the new
    # state can log its banner/$I/$$/status events and race past that small
    # cursor before the next 100 ms tick — so `head_seq > last_console_seq`
    # never goes backwards and the reset never fires, silently dropping the
    # new session's opening lines. Tracking object identity has no such gap,
    # and reading `state` once up front (rather than re-reading
    # `session.state` between the head-seq and tail calls) also closes the
    # double-dereference race where a reconnect could land between the two.
    state = session.state
    snap = await run_in_threadpool(state.snapshot)
    await websocket.send_json({"type": "snapshot", "data": snap})
    last_seq = snap["seq"]

    backlog = await run_in_threadpool(state.console_tail)
    await websocket.send_json({"type": "console", "data": backlog})
    last_console_seq = backlog[-1]["seq"] if backlog else -1

    last_keepalive = time.time()

    try:
        while True:
            await asyncio.sleep(0.1)  # 10 Hz cap

            if session.state is not state:
                # A reconnect (or disconnect) swapped in a new MachineState.
                # Resync to it and resend everything from scratch — the old
                # cursor and seq numbers no longer mean anything.
                state = session.state
                snap = await run_in_threadpool(state.snapshot)
                await websocket.send_json({"type": "snapshot", "data": snap})
                last_seq = snap["seq"]
                last_keepalive = time.time()

                backlog = await run_in_threadpool(state.console_tail)
                await websocket.send_json({"type": "console", "data": backlog})
                last_console_seq = backlog[-1]["seq"] if backlog else -1
                continue

            now = time.time()
            # `dirty` is a single shared flag on MachineState: any other
            # consumer (a second /machine/ws client, or a GET /machine/state poll, which
            # also calls snapshot() and clears it) steals the change
            # notification, so this loop would fall back to the 1 Hz
            # keepalive and feel laggy for no visible reason. `seq` is not
            # shared state — it is a per-consumer comparison against the
            # payload just taken — so use that instead.
            snap = await run_in_threadpool(state.snapshot)
            if snap["seq"] != last_seq or now - last_keepalive >= 1.0:
                await websocket.send_json({"type": "snapshot", "data": snap})
                last_seq = snap["seq"]
                last_keepalive = now

            head_seq = await run_in_threadpool(state.console_head_seq)
            if head_seq > last_console_seq:
                tail = await run_in_threadpool(state.console_tail)
                fresh = [line for line in tail if line["seq"] > last_console_seq]
                if fresh:
                    await websocket.send_json({"type": "console", "data": fresh})
                    last_console_seq = fresh[-1]["seq"]
                else:
                    last_console_seq = head_seq
    except WebSocketDisconnect:
        return


if __name__ == "__main__":
    # `python server.py` should just work; `uvicorn server:app --reload` is
    # the same thing spelled out. reload=True watches the .py files and
    # restarts on save.
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
