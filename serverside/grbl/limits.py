"""Work-envelope checks.

Refusing an out-of-range jog here, before the bytes leave, is better than
letting GRBL alarm: an alarm costs the operator a reset and their zero, and
the error it prints does not say which axis or by how much.
"""
from __future__ import annotations

from grbl.profile import Profile

AXIS_INDEX: dict[str, int] = {"X": 0, "Y": 1, "Z": 2}

EPS = 1e-6


class LimitError(Exception):
    """A requested move would leave the configured work envelope."""


def _travel(profile: Profile, axis: str) -> float:
    return {"X": profile.travel_x, "Y": profile.travel_y, "Z": profile.travel_z}[axis]


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

    limit = _travel(profile, axis)
    target = mpos[AXIS_INDEX[axis]] + distance

    if target < -EPS:
        raise LimitError(
            f"{axis}{distance:+g} would reach {target:g} mm, below the 0 mm limit"
        )
    if target > limit + EPS:
        raise LimitError(
            f"{axis}{distance:+g} would reach {target:g} mm, "
            f"past the {limit:g} mm limit"
        )
