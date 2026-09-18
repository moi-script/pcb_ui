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
    def test_a_routed_kicad_board_plunges_once_per_stroke(self):
        """Every segment is drawn, but joined segments share one pen drop."""
        board = "labExam.kicad_pcb"
        with open(board, encoding="utf-8", errors="replace") as f:
            wiring = extract_wiring(f.read())
        lines = pcb_gcode.generate_gcode(wiring)
        tracks = [w for w in wiring
                  if w["type"] == "track" and w["layer"] == "F.Cu"]
        plunges = [z for _m, z, _f in z_moves(lines) if z < 0]
        draws = [l for l in lines if l.startswith("G1 X")]

        assert len(draws) == len(tracks)
        assert len(plunges) < len(tracks)
        # And no lift is wasted: every travel goes somewhere the pen is not.
        pos = None
        for line in lines:
            m = re.match(r"G([01]) X(-?[\d.]+) Y(-?[\d.]+)", line)
            if not m:
                continue
            here = (float(m.group(2)), float(m.group(3)))
            if m.group(1) == "0" and pos is not None:
                assert here != pos, f"lifted only to land again at {here}"
            pos = here


# --------------------------------------------------------------- the bed

# A board sitting where KiCad actually leaves one: a hundred-odd millimetres
# up the sheet. Its own extent is 20 x 10 mm, which fits any bed; its sheet
# coordinates fit none.
OFFSET_TRACKS = [
    {"type": "track", "layer": "F.Cu",
     "start": (142.5, 97.96), "end": (162.5, 97.96)},
    {"type": "track", "layer": "F.Cu",
     "start": (142.5, 107.96), "end": (162.5, 107.96)},
]


def _xy(lines):
    xs, ys = [], []
    for line in lines:
        for letter, value in re.findall(
            r"([XY])(-?[\d.]+)", line.split(";", 1)[0]
        ):
            (xs if letter == "X" else ys).append(float(value))
    return xs, ys


def test_the_board_is_plotted_from_its_own_corner_not_the_kicad_sheet():
    """The pen starts at work zero, and work zero is the board's TOP-left.

    A KiCad file places the board wherever it sits on the sheet. Emitting
    those numbers sends the pen a hundred millimetres away to look for
    copper that is not there — and off the end of a 100 mm bed on the way.
    The operator parks the pen at the top of the bed, so the plot hangs
    below it: X runs 0 .. width, Y runs 0 .. -height.
    """
    cfg = dict(pcb_gcode.CONFIG)
    cfg["layer"] = "F.Cu"
    lines = pcb_gcode.generate_gcode(OFFSET_TRACKS, cfg)
    xs, ys = _xy(lines)

    assert min(xs) == 0.0
    assert max(ys) == 0.0
    # The drawing keeps its own size and orientation; only its position changed.
    assert max(xs) == 20.0
    assert min(ys) == -10.0


def test_a_normalised_board_fits_the_bed_the_sheet_coordinates_did_not():
    from grbl.limits import LimitError, check_program
    from grbl.profile import DEFAULT_PROFILE

    cfg = dict(pcb_gcode.CONFIG)
    cfg["layer"] = "F.Cu"

    check_program(DEFAULT_PROFILE, pcb_gcode.generate_gcode(OFFSET_TRACKS, cfg))

    # The same geometry left where the sheet put it is refused, and the
    # message says which axis and by how much.
    raw = [
        f"G0 X{s[0]:g} Y{s[1]:g}" for t in OFFSET_TRACKS
        for s in (t["start"], t["end"])
    ]
    with pytest.raises(LimitError) as exc:
        check_program(DEFAULT_PROFILE, ["G21", "G90", *raw])
    assert "X162.5" in str(exc.value)
    assert "100 mm" in str(exc.value)


def test_ordering_starts_from_the_pen_not_from_a_corner_of_the_sheet():
    """Nearest-first is measured from work zero, so the board must be there.

    Ordered against un-normalised coordinates, every track is roughly the
    same enormous distance from (0, 0) and the ordering is close to
    arbitrary. This pins the first move as the track nearest the origin.
    """
    cfg = dict(pcb_gcode.CONFIG)
    cfg["layer"] = "F.Cu"
    lines = pcb_gcode.generate_gcode(OFFSET_TRACKS, cfg)

    first_travel = next(l for l in lines if l.startswith("G0 X"))
    # The upper track (y=0 after normalising) is nearest work zero.
    assert first_travel.startswith("G0 X0 Y0")
    # ...and the job comes back to where the pen started.
    assert [l for l in lines if l.startswith("G0 ")][-1].startswith("G0 X0 Y0")


# --- the rest of the machine settings, against grbl_servo_z's defaults --------
from grbl.profile import DEFAULT_PROFILE  # noqa: E402
from grbl.sim import MAX_RATE  # noqa: E402

FIRMWARE_MAX_RATE = min(MAX_RATE)  # $110-$112, mm/min


def test_generated_feeds_do_not_exceed_the_firmware_max_rate():
    # Grbl silently clamps anything faster, so a higher F only makes the
    # time estimate and the simulator lie about the real machine.
    for key in ("travel_feed", "draw_feed", "z_feed"):
        assert pcb_gcode.CONFIG[key] <= FIRMWARE_MAX_RATE, key


def test_profile_feeds_do_not_exceed_the_firmware_max_rate():
    for key in ("travel_feed", "draw_feed", "z_feed", "jog_feed"):
        assert getattr(DEFAULT_PROFILE, key) <= FIRMWARE_MAX_RATE, key


def test_profile_pen_lift_gives_the_servo_time_to_travel():
    # machine.py lifts the pen with the profile's z_feed after a stop.
    p = DEFAULT_PROFILE
    seconds = abs(p.pen_up_z - p.pen_down_z) / p.z_feed * 60
    assert seconds >= MIN_Z_MOVE_SECONDS


def test_profile_pen_matches_the_generated_gcode():
    assert DEFAULT_PROFILE.pen_up_z == pcb_gcode.CONFIG["pen_up_z"]
    assert DEFAULT_PROFILE.pen_down_z == pcb_gcode.CONFIG["pen_down_z"]
    # The pen is the Z axis on grbl_servo_z, not an M3 S<pwm> spindle servo.
    assert DEFAULT_PROFILE.pen_mode == "z-axis"
