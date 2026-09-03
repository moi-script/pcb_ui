"""The G-code contract for grbl_servo_z firmware.

The target machine is an Arduino running grbl_servo_z, where Z is an SG90
servo acting as a binary pen actuator rather than a stepper. Two rules in that
firmware constrain everything we emit:

1. `servo_set_z()` is `if (z_steps < SERVO_Z_THRESHOLD_STEPS)`, with the
   threshold at 0 and the comparison strictly less than. Pen-down therefore
   needs a NEGATIVE Z. A `Z0` plunge leaves the pen up and plots nothing.

2. The servo takes its travel time from how long Grbl spends executing the Z
   move, because Z is still a fully planned axis. A rapid, or a feed rate in
   the thousands, moves on to the next X/Y before the pen has landed.

These tests pin both rules so a change to the pen heights or feeds can't
silently produce G-code that draws in the air.
"""
from __future__ import annotations

import re

import pytest

import pcb_gcode
from pcb_read import extract_wiring
from tracer import emit


# Servo travel for an SG90 is ~0.2 s; the firmware README budgets 300 ms
# (1 mm at F200). Anything under this and the pen drags into the next move.
MIN_Z_MOVE_SECONDS = 0.25

SQUARE = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]]

TRACKS = [
    {"type": "track", "layer": "F.Cu", "start": (0.0, 0.0), "end": (10.0, 0.0)},
    {"type": "track", "layer": "F.Cu", "start": (0.0, 5.0), "end": (10.0, 5.0)},
]

Z_MOVE = re.compile(r"^G([01])\s+Z(-?[\d.]+)(?:\s+F([\d.]+))?\s*$")


def z_moves(lines: list[str]) -> list[tuple[int, float, float | None]]:
    """Every Z-only move as (motion, z, feed)."""
    out = []
    for ln in lines:
        m = Z_MOVE.match(ln.strip())
        if m:
            out.append((int(m.group(1)), float(m.group(2)),
                        float(m.group(3)) if m.group(3) else None))
    return out


def both_emitters() -> dict[str, list[str]]:
    return {
        "pcb_gcode": pcb_gcode.generate_gcode(TRACKS),
        "tracer": emit.generate_from_strokes(SQUARE),
    }


class TestPenHeights:
    def test_pen_down_z_is_negative(self):
        # Z0 would leave the pen up: the firmware tests z_steps < 0.
        assert pcb_gcode.CONFIG["pen_down_z"] < 0

    def test_pen_up_z_is_not_negative(self):
        assert pcb_gcode.CONFIG["pen_up_z"] >= 0

    @pytest.mark.parametrize("name", ["pcb_gcode", "tracer"])
    def test_emitted_plunges_are_negative(self, name):
        lines = both_emitters()[name]
        downs = [z for _m, z, _f in z_moves(lines) if z < 0]
        assert downs, f"{name} emits no negative Z: the pen never comes down"

    @pytest.mark.parametrize("name", ["pcb_gcode", "tracer"])
    def test_no_plunge_sits_exactly_on_the_threshold(self, name):
        lines = both_emitters()[name]
        # Z0 is the trap: it reads as pen-up, so it must never be a plunge.
        zs = [z for _m, z, _f in z_moves(lines)]
        assert 0.0 not in zs, f"{name} emits a Z0 move, which reads as pen-up"


class TestServoHasTimeToTravel:
    @pytest.mark.parametrize("name", ["pcb_gcode", "tracer"])
    def test_every_z_move_is_a_feed_move(self, name):
        lines = both_emitters()[name]
        rapids = [(m, z) for m, z, _f in z_moves(lines) if m == 0]
        assert not rapids, (
            f"{name} moves Z with G0 {rapids}: a rapid gives the servo no time"
        )

    @pytest.mark.parametrize("name", ["pcb_gcode", "tracer"])
    def test_every_z_move_carries_a_feed_rate(self, name):
        lines = both_emitters()[name]
        assert all(f is not None for _m, _z, f in z_moves(lines)), (
            f"{name} emits a Z move with no F word"
        )

    @pytest.mark.parametrize("name", ["pcb_gcode", "tracer"])
    def test_each_transition_lasts_long_enough(self, name):
        """Time is only owed where the servo actually swings.

        The opening move is a park: grbl_servo_z already holds the pen up from
        servo_init(), so going to the pen-up height moves nothing. What must be
        paid for is a move that crosses the threshold and flips the pen.
        """
        lines = both_emitters()[name]
        pos = 0.0
        up_now = True  # firmware parks the pen up at boot
        for _motion, z, feed in z_moves(lines):
            distance = abs(z - pos)
            up_next = z >= 0
            transition = up_next != up_now
            pos, up_now = z, up_next
            if not transition:
                continue
            seconds = distance / (feed / 60.0)
            assert seconds >= MIN_Z_MOVE_SECONDS, (
                f"{name}: pen transition of {distance} mm at F{feed} takes "
                f"{seconds:.3f}s, under the {MIN_Z_MOVE_SECONDS}s the servo needs"
            )


class TestJobShape:
    @pytest.mark.parametrize("name", ["pcb_gcode", "tracer"])
    def test_job_starts_and_ends_pen_up(self, name):
        lines = both_emitters()[name]
        moves = z_moves(lines)
        assert moves, "no Z motion at all"
        assert moves[0][1] >= 0, f"{name} starts with the pen down"
        assert moves[-1][1] >= 0, f"{name} ends with the pen down"

    @pytest.mark.parametrize("name", ["pcb_gcode", "tracer"])
    def test_pen_alternates_down_and_up(self, name):
        lines = both_emitters()[name]
        states = [z < 0 for _m, z, _f in z_moves(lines)]
        # collapse repeats: the pen must never plunge twice without lifting
        collapsed = [s for i, s in enumerate(states) if i == 0 or s != states[i - 1]]
        for a, b in zip(collapsed, collapsed[1:]):
            assert a != b, f"{name} repeats a pen state without a transition"

    def test_alignment_frame_never_goes_pen_down(self):
        lines = emit.emit_frame(emit.bounds(SQUARE))
        assert all(z >= 0 for _m, z, _f in z_moves(lines)), "frame must not draw"


class TestAgainstARealBoard:
    def test_a_routed_kicad_board_plunges_once_per_track(self):
        board = "labExam.kicad_pcb"
        with open(board, encoding="utf-8", errors="replace") as f:
            wiring = extract_wiring(f.read())
        lines = pcb_gcode.generate_gcode(wiring)
        tracks = [w for w in wiring
                  if w["type"] == "track" and w["layer"] == "F.Cu"]
        plunges = [z for _m, z, _f in z_moves(lines) if z < 0]
        assert len(plunges) == len(tracks)
