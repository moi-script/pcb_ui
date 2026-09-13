"""Work-envelope checks.

Refusing an out-of-range jog here, before the bytes leave, is better than
letting GRBL alarm: an alarm costs the operator a reset and their zero, and
the error it prints does not say which axis or by how much.
"""
from __future__ import annotations

import re

from grbl.profile import Profile

# `X-1.5`, `Y.25`, `x 12` — the same loose shapes the visualizer's parser
# accepts, because real files come unspaced and in either case.
_WORD = re.compile(r"([XY])\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")

AXIS_INDEX: dict[str, int] = {"X": 0, "Y": 1, "Z": 2}

EPS = 1e-6


class LimitError(Exception):
    """A requested move would leave the configured work envelope."""


def _travel(profile: Profile, axis: str) -> float:
    return {"X": profile.travel_x, "Y": profile.travel_y, "Z": profile.travel_z}[axis]


def envelope(profile: Profile, axis: str) -> tuple[float, float]:
    """(low, high) work coordinates an axis may reach.

    Work zero is the TOP-left of the bed, where the pen is parked: X runs
    right to +travel_x, Y runs down to -travel_y. Z is the pen servo, which
    grbl_servo_z drops only below machine Z0, so it spans both sides of 0.
    """
    limit = _travel(profile, axis)
    return {"X": (0.0, limit), "Y": (-limit, 0.0), "Z": (-limit, limit)}[axis]


def check_jog(
    profile: Profile,
    mpos: tuple[float, float, float],
    axis: str,
    distance: float,
) -> None:
    """Raise LimitError if this relative jog would exit the envelope."""
    axis = axis.upper()
    if axis not in AXIS_INDEX:
        raise LimitError(f"unknown axis {axis!r}; expected X, Y, or Z")

    floor, limit = envelope(profile, axis)
    target = mpos[AXIS_INDEX[axis]] + distance

    if target < floor - EPS:
        raise LimitError(
            f"{axis}{distance:+g} would reach {target:g} mm, "
            f"below the {floor:g} mm limit"
        )
    if target > limit + EPS:
        raise LimitError(
            f"{axis}{distance:+g} would reach {target:g} mm, "
            f"past the {limit:g} mm limit"
        )


def program_extents(
    lines: list[str],
) -> tuple[float, float, float, float] | None:
    """Min/max X and Y a G-code program will command, or None if unknowable.

    Narrow on purpose, and honest about it: it understands the absolute
    G90 files this project emits, and the moment it sees relative mode it
    gives up rather than reporting an extent it cannot stand behind. A
    wrong answer here is worse than no answer — it would clear a file to
    run off the end of the bed.
    """
    x = y = 0.0
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    seen = False

    for raw in lines:
        line = raw.split(";", 1)[0].upper()
        if not line.strip():
            continue
        if "G91" in line:
            return None  # relative mode: the numbers stop meaning position

        nx, ny = x, y
        moved = False
        for letter, value in _WORD.findall(line):
            if letter == "X":
                nx = float(value)
                moved = True
            elif letter == "Y":
                ny = float(value)
                moved = True
        if not moved:
            continue

        x, y = nx, ny
        seen = True
        minx = min(minx, x)
        maxx = max(maxx, x)
        miny = min(miny, y)
        maxy = max(maxy, y)

    return (minx, maxx, miny, maxy) if seen else None


def check_program(profile: Profile, lines: list[str]) -> None:
    """Raise LimitError if a program would leave the bed.

    Checked before a byte goes out, for the same reason a jog is: an alarm
    mid-plot costs the operator their work zero and half a board, and the
    message GRBL prints does not say which move was the one that did it.
    A file whose extents cannot be determined is left alone — refusing what
    cannot be measured would block every hand-written file.
    """
    extents = program_extents(lines)
    if extents is None:
        return
    minx, maxx, miny, maxy = extents

    for axis, low, high in (("X", minx, maxx), ("Y", miny, maxy)):
        floor, limit = envelope(profile, axis)
        if low < floor - EPS:
            raise LimitError(
                f"this file reaches {axis}{low:g} mm, past the {floor:g} mm "
                f"edge of the bed"
            )
        if high > limit + EPS:
            raise LimitError(
                f"this file reaches {axis}{high:g} mm, past the {limit:g} mm "
                f"edge of the bed"
            )
