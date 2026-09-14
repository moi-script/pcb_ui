"""Axis direction and start corner — the machine setup a sender owns.

Universal G-code Sender lets you reverse an axis and pick the corner a plot
starts from. Grbl normally does the first with `$3`, the direction invert
mask, but grbl_servo_z cannot: its stepper ISR writes the 28BYJ-48 coil
sequence straight from the planner's direction bits (stepper.c), so `$3`
never reaches the motors. Reversal therefore happens here, in the host.

Two pure pieces, no I/O:

- `AxisMap` rewrites what crosses the wire. Every X/Y the app sends is
  negated on the way out for a reversed axis, and every position the
  controller reports is negated on the way back in, so everything above the
  streamer — jogs, limits, the readout, the files — lives in one frame where
  +X is right and +Y is up, whatever the wiring does.
- `place_program` moves a top-left-anchored program so its chosen corner
  sits on work zero. A translation, never a mirror: the drawing keeps its
  orientation, only where it lands relative to the pen changes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ORIGINS = ("top-left", "top-right", "bottom-left", "bottom-right")

_NUM = r"[+-]?(?:\d+\.?\d*|\.\d+)"
_WORD = re.compile(rf"([A-Z])\s*({_NUM})")
# Report fields that carry a machine or work position as `x,y,z`.
_POS_FIELD = re.compile(
    rf"(MPos|WPos|WCO|G5[4-9]|G28|G30|G92|PRB):({_NUM}),({_NUM})"
)


def _fmt(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _negate(text: str) -> str:
    return _fmt(-float(text))


@dataclass(frozen=True)
class AxisMap:
    invert_x: bool = False
    invert_y: bool = False

    @property
    def identity(self) -> bool:
        return not (self.invert_x or self.invert_y)

    def outbound(self, line: str) -> str:
        """The line as the controller must receive it."""
        if self.identity:
            return line
        body = line.strip()
        upper = body.upper()
        if upper.startswith("$J="):
            return body[:3] + self._rewrite_gcode(body[3:])
        if upper.startswith("$") or not body:
            return body  # settings and system commands carry no coordinates
        return self._rewrite_gcode(body)

    def _rewrite_gcode(self, body: str) -> str:
        # Comments carry no motion and may hold anything; leave them be.
        code, sep, comment = body.partition(";")
        code = re.sub(r"\([^)]*\)", "", code)
        mirror = self.invert_x != self.invert_y

        def word(m: re.Match) -> str:
            letter, value = m.group(1), m.group(2)
            if letter in "XI" and self.invert_x:
                return letter + _negate(value)
            if letter in "YJ" and self.invert_y:
                return letter + _negate(value)
            if letter == "G" and mirror and float(value) in (2.0, 3.0):
                # A mirrored plane turns clockwise arcs counter-clockwise.
                return "G3" if float(value) == 2.0 else "G2"
            return m.group(0)

        out = _WORD.sub(word, code.upper())
        return out + (sep + comment if sep else "")

    def inbound(self, line: str) -> str:
        """A controller line with its positions mapped back to the app's frame."""
        if self.identity or ":" not in line:
            return line

        def field(m: re.Match) -> str:
            x, y = m.group(2), m.group(3)
            if self.invert_x:
                x = _negate(x)
            if self.invert_y:
                y = _negate(y)
            return f"{m.group(1)}:{x},{y}"

        return _POS_FIELD.sub(field, line)


def origin_offset(
    origin: str, extents: tuple[float, float, float, float]
) -> tuple[float, float]:
    """How far to move a top-left program so `origin` lands on work zero.

    `extents` is (minx, maxx, miny, maxy) of the program as generated: X
    running right from 0, Y running down from 0.
    """
    if origin not in ORIGINS:
        raise ValueError(f"unknown origin {origin!r}")
    minx, maxx, miny, maxy = extents
    dx = -minx if origin.endswith("left") else -maxx
    dy = -maxy if origin.startswith("top") else -miny
    return dx, dy


def place_program(lines: list[str], dx: float, dy: float) -> list[str]:
    """Shift every absolute X/Y in a program by (dx, dy).

    Only for the absolute G90 programs this project emits — the caller
    measures extents first, and `program_extents` refuses relative files.
    Arc centres (I/J) are offsets from the start point, so they stay put.
    """
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return list(lines)

    def word(m: re.Match) -> str:
        letter, value = m.group(1), float(m.group(2))
        if letter == "X":
            return "X" + _fmt(value + dx)
        if letter == "Y":
            return "Y" + _fmt(value + dy)
        return m.group(0)

    out: list[str] = []
    for raw in lines:
        code, sep, comment = raw.partition(";")
        upper = code.upper()
        # G10/G92 set offsets, they do not go anywhere; `$` lines are not G-code.
        if upper.lstrip().startswith("$") or re.search(r"G\s*(10|92)(?!\d|\.)", upper):
            out.append(raw)
            continue
        out.append(_WORD.sub(word, upper) + (sep + comment if sep else ""))
    return out
