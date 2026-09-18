"""What the machine was doing when the link dropped.

A dropped plot leaves three numbers behind: lines sent, lines acknowledged,
and the last position the controller reported. None of them is the line the
pen was on. `ok` means parsed and queued, so the pen trails the acknowledged
count by a planner's worth of moves; and the status report is up to one poll
old. This module closes that gap geometrically: it replays the file to learn
where every line starts and ends, then finds the line whose move contains the
last reported position.

What it reports is a *likely* line, named with the axes that were moving —
X/Y for travel and drawing, Z for the pen servo — and a plain-language
reading of what that points to. One report says what one drop was doing; the
history (DropHistory) is what shows a pattern, and the pattern is what finds
the cause: drops that cluster on pen moves are a power problem, not G-code.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("traceworks.trace")

# grbl_servo_z drops the pen for Z strictly below zero (see pcb_gcode.py).
PEN_DOWN_BELOW = 0.0

# How far the reported position may sit from a line's path and still count
# as on it. Status positions are rounded to 3 decimals by Grbl and the file
# to a few more; 0.05 mm is well above that and well below any trace pitch.
ON_PATH_MM = 0.05

# How many lines behind the last acknowledged one the pen can be. Grbl's
# planner holds 16 blocks on a 328P; the margin covers blocks that take no
# planner slot (modal-only lines) and a status report a poll old.
LOOKBACK = 48

# Lines of context either side of the match in a report.
CONTEXT_BEFORE = 3
CONTEXT_AFTER = 6

_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")


@dataclass(frozen=True)
class Move:
    """One file line, replayed: where it starts, where it ends, what moves."""
    index: int                           # 0-based into the job's lines
    code: str
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    axes: str                            # the axes whose position changes, e.g. "XY", "Z", ""


def replay(lines: list[str],
           origin: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> list[Move]:
    """Every line with the move it makes, tracking G90/G91 and G20/G21.

    Arcs (G2/G3) are treated as straight chords to their end point — close
    enough to say which line the pen was on, and this machine's files have
    none. Lines that move nothing (units, feeds, M-codes, a travel to where
    the pen already is) come back with `axes == ""`.
    """
    pos = list(origin)
    absolute = True
    scale = 1.0
    moves: list[Move] = []
    for i, code in enumerate(lines):
        words = [(letter, float(value)) for letter, value in _WORD.findall(code.upper())]
        for letter, value in words:
            if letter == "G":
                if value == 90:
                    absolute = True
                elif value == 91:
                    absolute = False
                elif value == 20:
                    scale = 25.4
                elif value == 21:
                    scale = 1.0
        # `$J=` jogs and `G53` machine-frame moves are not in the work frame
        # this replays; `G4 P..` and `G10 L20 ..` carry numbers that are not
        # positions. None of them moves the pen along the file.
        skip = code.lstrip().startswith("$") or any(
            letter == "G" and value in (4, 10, 28, 30, 53, 92)
            for letter, value in words
        )
        start = tuple(pos)
        if not skip:
            for letter, value in words:
                axis = "XYZ".find(letter)
                if axis < 0:
                    continue
                pos[axis] = value * scale if absolute else pos[axis] + value * scale
        end = tuple(pos)
        axes = "".join(
            name for name, a, b in zip("XYZ", start, end) if abs(a - b) > 1e-6
        )
        moves.append(Move(i, code, start, end, axes))  # type: ignore[arg-type]
    return moves


def _distance(p, a, b) -> tuple[float, float]:
    """Distance from p to segment a-b, and how far along it (0..1) p sits."""
    ab = [b[k] - a[k] for k in range(3)]
    ap = [p[k] - a[k] for k in range(3)]
    length2 = sum(v * v for v in ab)
    if length2 == 0:
        t = 0.0
    else:
        t = max(0.0, min(1.0, sum(ab[k] * ap[k] for k in range(3)) / length2))
    closest = [a[k] + t * ab[k] for k in range(3)]
    return sum((p[k] - closest[k]) ** 2 for k in range(3)) ** 0.5, t


def locate(moves: list[Move], pos, lo: int, hi: int,
           tol: float = ON_PATH_MM) -> tuple[Move | None, list[int], str]:
    """The move the pen was on at `pos`, searching lines lo..hi (0-based).

    Returns (best, candidates, confidence). A point strictly inside one
    move's path is `exact`. A point at a corner belongs to the move that
    ends there and the one that starts there, and a PCB revisits pads, so
    several moves can match: then the latest is chosen — the planner runs
    oldest-first, so the newest match in the window is nearest the front —
    and the confidence is `likely`. No match at all is `none`.
    """
    interior: list[Move] = []
    touching: list[Move] = []
    for move in moves[max(0, lo): hi + 1]:
        if not move.axes:
            continue
        dist, _ = _distance(pos, move.start, move.end)
        if dist > tol:
            continue
        at_end = min(_distance(pos, move.start, move.start)[0],
                     _distance(pos, move.end, move.end)[0]) <= tol
        (touching if at_end else interior).append(move)
    found = interior + touching
    candidates = sorted(m.index for m in found)
    if len(interior) == 1:
        return interior[0], candidates, "exact"
    if found:
        best = max(interior or touching, key=lambda m: m.index)
        return best, candidates, "likely"
    return None, [], "none"


def classify(move: Move | None, machine_state: str) -> str:
    """What kind of motion the drop happened during.

    `z_down` / `z_up` — the pen servo; `draw` — X/Y with the pen down;
    `travel` — X/Y with the pen up; `idle` — nothing was moving;
    `unknown` — no position to go on.
    """
    if machine_state.startswith(("Idle", "Hold", "Alarm", "Door", "Sleep")):
        return "idle"
    if move is None:
        return "unknown"
    if "Z" in move.axes and not ("X" in move.axes or "Y" in move.axes):
        return "z_down" if move.end[2] < move.start[2] else "z_up"
    return "draw" if move.end[2] < PEN_DOWN_BELOW else "travel"


# Read after "The link dropped while ...".
KIND_LABEL = {
    "z_down": "the pen was going down (Z)",
    "z_up": "the pen was lifting (Z)",
    "draw": "drawing (X/Y, pen down)",
    "travel": "travelling (X/Y, pen up)",
    "idle": "the machine was not moving",
    "unknown": "the machine's position was unknown",
}

_WHY = {
    "z_down": (
        "The SG90 servo pulls a burst of current every time it swings. If the "
        "Arduino shares that 5 V with USB, the dip can reset the USB chip or "
        "the board. If drops keep landing on Z moves, power the servo from its "
        "own 5 V supply (common ground) — the G-code is not the problem."
    ),
    "z_up": (
        "The servo was swinging the pen up — the same current burst as a pen "
        "drop. Drops that cluster on Z moves point at the servo's power, not "
        "at the file: give it a separate 5 V supply with a shared ground."
    ),
    "draw": (
        "The steppers were drawing a trace. Stepper wiring beside the USB "
        "cable couples noise into it, and an undersized motor supply sags "
        "under load. Route the USB cable away from the motor leads, try a "
        "shorter or ferrite-bead cable, and check the driver supply."
    ),
    "travel": (
        "The steppers were travelling with the pen up — the fastest moves in "
        "the file, so the highest motor current. If drops cluster here, check "
        "the motor supply and keep the USB cable away from the motor leads."
    ),
    "idle": (
        "The machine was not moving, so this drop is not motion-related. "
        "Suspect the cable or port itself, or Windows USB power saving "
        "(Device Manager → USB Root Hub → Power Management → untick "
        "'Allow the computer to turn off this device')."
    ),
    "unknown": (
        "No position report arrived before the drop, so the line the pen was "
        "on cannot be placed. The lines below are what the controller had "
        "accepted."
    ),
}


def build_report(
    *,
    lines: list[str],
    acked: int,
    sent: int,
    job_name: str,
    cause: str,
    reason: str,
    pos: list[float] | None,
    machine_state: str,
    status_age: float | None,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> dict:
    """A JSON-ready report of one drop. `cause` is `link_lost` or `controller_reset`."""
    moves = replay(lines, origin)
    hi = min(acked, len(lines)) - 1          # the newest line the pen could be on
    lo = max(0, hi - LOOKBACK)
    move = None
    candidates: list[int] = []
    confidence = "none"
    if pos is not None and hi >= 0:
        move, candidates, confidence = locate(moves, pos, lo, hi)
    kind = classify(move, machine_state) if pos is not None else "unknown"

    focus = move.index if move is not None else max(hi, 0)
    first = max(0, focus - CONTEXT_BEFORE)
    last = min(len(lines) - 1, focus + CONTEXT_AFTER)
    context = []
    for m in moves[first: last + 1]:
        if move is not None and m.index == move.index:
            role = "match"
        elif m.index in candidates:
            role = "candidate"
        elif m.index > hi:
            role = "unsent" if m.index >= sent else "queued"
        elif move is not None and m.index > move.index:
            role = "queued"
        else:
            role = "before"
        context.append({"n": m.index + 1, "code": m.code, "axes": m.axes, "role": role})

    where = KIND_LABEL[kind]
    if cause == "controller_reset":
        headline = f"The controller restarted while {where}"
        why = (
            "A restart mid-plot is the board losing power for an instant. "
            + _WHY.get(kind, "")
        ) if kind != "idle" else (
            "The board restarted while nothing was moving — check the USB cable "
            "and the board's power input."
        )
    else:
        headline = f"The link dropped while {where}"
        why = _WHY[kind]
    if move is not None:
        headline += f" — line {move.index + 1}"
    if status_age is not None and status_age > 1.0:
        why += (
            f" The last position report was {status_age:.1f} s old, so the "
            "machine may have moved on from this line before the drop."
        )

    return {
        "at": time.time(),
        "job": job_name,
        "cause": cause,
        "reason": reason,
        "kind": kind,
        "axes": move.axes if move is not None else "",
        "headline": headline,
        "explanation": why,
        "line": move.index + 1 if move is not None else None,
        "code": move.code if move is not None else "",
        "candidates": [i + 1 for i in candidates],
        "confidence": confidence,
        "pos": list(pos) if pos is not None else None,
        "state": machine_state,
        "statusAge": status_age,
        "acked": acked,
        "sent": sent,
        "total": len(lines),
        "context": context,
    }


class DropHistory:
    """The last few drop reports, kept in a small JSON file.

    `path` None keeps them in memory only (tests). The file survives a
    backend restart, which matters: a drop that takes the USB port with it
    often takes the operator's patience too, and the pattern is only visible
    across several of them.
    """

    LIMIT = 20

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._reports: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if self._path is None or not self._path.is_file():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return [r for r in data if isinstance(r, dict)][-self.LIMIT:]
        except (OSError, ValueError, TypeError) as exc:
            log.warning("ignoring unreadable drop history %s: %s", self._path, exc)
            return []

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._reports, indent=1), encoding="utf-8")
        except OSError as exc:
            log.warning("could not save drop history %s: %s", self._path, exc)

    def add(self, report: dict) -> None:
        with self._lock:
            self._reports.append(report)
            del self._reports[: -self.LIMIT]
            self._save()

    def clear(self) -> None:
        with self._lock:
            self._reports = []
            self._save()

    def snapshot(self) -> dict:
        """Newest first, with a count per kind of motion."""
        with self._lock:
            reports = list(reversed(self._reports))
        tally = {kind: 0 for kind in KIND_LABEL}
        for r in reports:
            tally[r.get("kind", "unknown")] = tally.get(r.get("kind", "unknown"), 0) + 1
        return {"reports": reports, "tally": tally}
