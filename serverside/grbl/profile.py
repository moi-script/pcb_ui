"""The machine's fixed characteristics: travel envelope, feeds, pen geometry.

Slice-1 kept this in sqlite behind a profile editor. Here it is a constant:
there is one machine, its envelope does not change between requests, and a
frozen dataclass is honest about that. If per-user machine profiles are ever
wanted, this is the seam to widen — everything downstream takes a Profile.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from grbl.axes import ORIGINS, AxisMap

PEN_MODES = ("z-axis", "servo-pwm")

# The largest bed this plotter has. A smaller one may be configured (a jig,
# a small sheet), never a larger one: past 100 mm the carriage hits the frame.
MAX_TRAVEL_XY = 100.0


@dataclass(frozen=True)
class Profile:
    name: str = "Default"
    controller: str = "grbl"
    baud: int = 115200
    rx_buffer: int = 128
    # grbl_servo_z drives the SG90 from the Z axis (D10), not from a
    # spindle PWM (M3 S...). servo_up/servo_down only apply to servo-pwm.
    pen_mode: str = "z-axis"
    # The bed. 100 x 100 mm is the whole working area of this machine, and
    # everything downstream measures against it: what a board may be, what
    # a jog may reach, and what a file is allowed to command. Z is the pen
    # servo's throw, not a travel axis.
    travel_x: float = 100.0
    travel_y: float = 100.0
    travel_z: float = 5.0
    # Matches what pcb_gcode.py emits: Z >= 0 holds the pen up, Z < 0
    # drops it. These drive the pen up/down readout, not the G-code.
    pen_up_z: float = 0.5
    pen_down_z: float = -0.5
    servo_up: int = 0
    servo_down: int = 255
    # grbl_servo_z's $110-$112 are 500 mm/min; Grbl clamps anything above.
    travel_feed: float = 500.0
    draw_feed: float = 500.0
    # 1 mm of Z at F200 is 300 ms, the SG90's travel budget. The pen lift
    # after a stop uses this, so a faster Z would leave the pen dragging.
    z_feed: float = 200.0
    jog_feed: float = 500.0
    # Machine setup, the way Universal G-code Sender offers it. `origin` is
    # the corner of the drawing that sits on work zero (where the pen is
    # parked); the plot extends from it into the bed. `invert_x`/`invert_y`
    # reverse an axis whose motor turns the wrong way — see grbl/axes.py
    # for why that is done here and not with Grbl's `$3`.
    origin: str = "top-left"
    invert_x: bool = False
    invert_y: bool = False

    @property
    def axis_map(self) -> AxisMap:
        return AxisMap(self.invert_x, self.invert_y)

    def setup(self) -> dict:
        """The operator-editable part, as the API reports it."""
        return {
            "travelX": self.travel_x,
            "travelY": self.travel_y,
            "origin": self.origin,
            "invertX": self.invert_x,
            "invertY": self.invert_y,
            "maxTravel": MAX_TRAVEL_XY,
        }


def with_setup(
    profile: Profile,
    travel_x: float | None = None,
    travel_y: float | None = None,
    origin: str | None = None,
    invert_x: bool | None = None,
    invert_y: bool | None = None,
) -> Profile:
    """A copy of `profile` with the machine setup changed, validated.

    Raises ValueError with an operator-readable message on a bad value.
    """
    changes: dict = {}
    for name, value in (("travel_x", travel_x), ("travel_y", travel_y)):
        if value is None:
            continue
        value = float(value)
        if not 1.0 <= value <= MAX_TRAVEL_XY:
            raise ValueError(
                f"The bed must be between 1 and {MAX_TRAVEL_XY:g} mm on each "
                f"axis; got {value:g} mm."
            )
        changes[name] = value
    if origin is not None:
        if origin not in ORIGINS:
            raise ValueError(
                f"Start corner must be one of {', '.join(ORIGINS)}; got {origin!r}."
            )
        changes["origin"] = origin
    if invert_x is not None:
        changes["invert_x"] = bool(invert_x)
    if invert_y is not None:
        changes["invert_y"] = bool(invert_y)
    return replace(profile, **changes)


DEFAULT_PROFILE = Profile()
