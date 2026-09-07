"""GRBL 1.1 / FluidNC protocol codec.

Pure functions and dataclasses: bytes in, values out. Nothing in this module
performs I/O, which is what lets the fiddly parts of the protocol be tested
exhaustively without a controller attached.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

Vec3 = tuple[float, float, float]


class State(str, Enum):
    IDLE = "Idle"
    RUN = "Run"
    HOLD = "Hold"
    JOG = "Jog"
    ALARM = "Alarm"
    DOOR = "Door"
    CHECK = "Check"
    HOME = "Home"
    SLEEP = "Sleep"


@dataclass(frozen=True)
class Status:
    """One parsed `<...>` status report."""
    state: State
    substate: int | None
    mpos: Vec3 | None
    wpos: Vec3 | None
    wco: Vec3 | None
    feed: float
    spindle: float
    ov: tuple[int, int, int] | None
    pins: str


def _vec3(text: str) -> Vec3:
    parts = [float(p) for p in text.split(",")]
    while len(parts) < 3:
        parts.append(0.0)
    return (parts[0], parts[1], parts[2])


def parse_status(line: str) -> Status | None:
    """Parse a GRBL status report. Returns None for any other line."""
    line = line.strip()
    if not line.startswith("<") or not line.endswith(">"):
        return None

    fields = line[1:-1].split("|")
    if not fields:
        return None

    head = fields[0]
    substate: int | None = None
    if ":" in head:
        name, _, sub = head.partition(":")
        try:
            substate = int(sub)
        except ValueError:
            substate = None
    else:
        name = head

    try:
        state = State(name)
    except ValueError:
        return None

    mpos = wpos = wco = None
    ov: tuple[int, int, int] | None = None
    feed = spindle = 0.0
    pins = ""

    for field in fields[1:]:
        key, _, value = field.partition(":")
        if key == "MPos":
            mpos = _vec3(value)
        elif key == "WPos":
            wpos = _vec3(value)
        elif key == "WCO":
            wco = _vec3(value)
        elif key == "FS":
            nums = value.split(",")
            feed = float(nums[0]) if nums and nums[0] else 0.0
            spindle = float(nums[1]) if len(nums) > 1 and nums[1] else 0.0
        elif key == "F":
            feed = float(value) if value else 0.0
        elif key == "Ov":
            nums = [int(n) for n in value.split(",")]
            while len(nums) < 3:
                nums.append(100)
            ov = (nums[0], nums[1], nums[2])
        elif key == "Pn":
            pins = value

    return Status(
        state=state,
        substate=substate,
        mpos=mpos,
        wpos=wpos,
        wco=wco,
        feed=feed,
        spindle=spindle,
        ov=ov,
        pins=pins,
    )


def resolve_positions(status: Status, cached_wco: Vec3 | None) -> tuple[Vec3, Vec3, Vec3]:
    """Return (mpos, wpos, wco), filling in whichever the report omitted.

    GRBL transmits WCO only about every tenth report, so the offset must be
    carried across reports. Treating a missing WCO as zero makes the readout
    jump every time it is left out, which is the classic sender bug.
    """
    wco: Vec3 = status.wco or cached_wco or (0.0, 0.0, 0.0)

    if status.mpos is not None:
        mpos = status.mpos
        wpos = (mpos[0] - wco[0], mpos[1] - wco[1], mpos[2] - wco[2])
    elif status.wpos is not None:
        wpos = status.wpos
        mpos = (wpos[0] + wco[0], wpos[1] + wco[1], wpos[2] + wco[2])
    else:
        mpos = wpos = (0.0, 0.0, 0.0)

    return mpos, wpos, wco


# --- realtime command bytes -------------------------------------------------

class Realtime:
    """Single-byte realtime commands.

    These bypass GRBL's line parser and planner queue entirely. They produce
    no `ok`, and they must NEVER be counted against the RX buffer. Sending one
    through the line path is what makes senders hang on emergency stop, which
    is why this is a separate namespace from the line commands below.
    """
    STATUS = b"?"
    FEED_HOLD = b"!"
    RESUME = b"~"
    SOFT_RESET = b"\x18"
    SAFETY_DOOR = b"\x84"
    JOG_CANCEL = b"\x85"
    FEED_100 = b"\x90"
    FEED_PLUS_10 = b"\x91"
    FEED_MINUS_10 = b"\x92"
    RAPID_100 = b"\x95"
    RAPID_50 = b"\x96"
    RAPID_25 = b"\x97"


# --- reply parsing ----------------------------------------------------------

ERROR_MESSAGES: dict[int, str] = {
    1: "Expected a G-code command letter",
    2: "Bad number format in G-code value",
    3: "Unsupported '$' system command",
    4: "Negative value where a positive one is required",
    5: "Homing is disabled in settings ($22)",
    6: "Step pulse time is below the minimum",
    7: "EEPROM read failed; defaults restored",
    8: "'$' command needs the machine to be idle",
    9: "G-code locked out while in alarm or jog state",
    10: "Soft limits need homing enabled",
    11: "Line was longer than the input buffer",
    12: "Step rate exceeds the maximum",
    13: "A safety door or check input is active",
    14: "Build info or startup line exceeds the line limit",
    15: "Travel exceeded — jog target is outside the machine",
    16: "Invalid jog command",
    17: "Laser mode needs PWM output enabled",
    20: "Unsupported or invalid G-code command",
    21: "More than one G-code command from the same modal group",
    22: "Feed rate has not been set",
    23: "A G-code command needed an integer value",
    24: "Two G-code commands wanted the same axis word",
    25: "A G-code word was repeated on the line",
    26: "A G-code command is missing a required axis word",
    27: "Line number is out of range",
    28: "A G-code command is missing a required value word",
    29: "Only work coordinate systems P1-P6 are supported",
    30: "G53 needs G0 or G1 active",
    31: "Axis words were given but this command takes none",
    32: "G2/G3 arcs need at least one in-plane axis word",
    33: "Invalid motion target",
    34: "Arc radius is geometrically impossible",
    35: "G2/G3 offset mode needs an in-plane offset word",
    36: "Unused axis words remain in the block",
    37: "Tool length offset applies only to the configured axis",
    38: "Tool number is greater than the maximum",
}

ALARM_MESSAGES: dict[int, str] = {
    1: "Hard limit triggered — machine position is likely lost",
    2: "Soft limit — the commanded move exceeds the machine travel",
    3: "Reset while in motion — position is lost",
    4: "Probe failed: the probe was already triggered",
    5: "Probe failed: no contact within the travel",
    6: "Homing failed: reset during the cycle",
    7: "Homing failed: safety door opened",
    8: "Homing failed: the limit switch did not clear",
    9: "Homing failed: a limit switch was not found within the travel",
    10: "Homing failed: a second dual-axis switch was not found",
}


@dataclass(frozen=True)
class Reply:
    """A non-status line received from the controller."""
    kind: str  # "ok" | "error" | "alarm" | "message" | "banner" | "settings" | "unknown"
    code: int | None
    text: str


def _code_of(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def parse_reply(line: str) -> Reply | None:
    """Parse a non-status line. Returns None for blanks and status reports."""
    line = line.strip()
    if not line:
        return None
    if line.startswith("<") and line.endswith(">"):
        return None  # a status report; parse_status handles those

    low = line.lower()

    if low == "ok":
        return Reply("ok", None, "ok")

    if low.startswith("error:"):
        code = _code_of(line.split(":", 1)[1].strip())
        if code is None:
            return Reply("error", None, line)
        return Reply("error", code, ERROR_MESSAGES.get(code, f"Unknown error {code}"))

    if low.startswith("alarm:"):
        code = _code_of(line.split(":", 1)[1].strip())
        if code is None:
            return Reply("alarm", None, line)
        return Reply("alarm", code, ALARM_MESSAGES.get(code, f"Unknown alarm {code}"))

    if line.startswith("[") and line.endswith("]"):
        body = line[1:-1]
        _, _, text = body.partition(":")
        return Reply("message", None, text or body)

    if low.startswith("grbl ") or low.startswith("fluidnc"):
        return Reply("banner", None, line)

    if line.startswith("$"):
        return Reply("settings", None, line)

    return Reply("unknown", None, line)


# --- line command encoding --------------------------------------------------

def fmt(value: float) -> str:
    """Format a millimetre value the way G-code wants it: no trailing zeros."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def encode_jog(axis: str, distance: float, feed: float) -> str:
    """Build a `$J=` jog.

    Jogs are relative (G91) and metric (G21), and crucially do NOT alter the
    parser's modal state — so jogging mid-session cannot change how a
    subsequent job is interpreted. A jog in flight is cancelled with the
    realtime byte Realtime.JOG_CANCEL, not by resetting.
    """
    return f"$J=G91 G21 {axis.upper()}{fmt(distance)} F{fmt(feed)}"


def encode_zero(axes: str) -> str:
    """Set the work offset so the named axes read zero at the current position."""
    words = " ".join(f"{a}0" for a in axes.upper())
    return f"G10 L20 P1 {words}"
