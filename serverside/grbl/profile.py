"""The machine's fixed characteristics: travel envelope, feeds, pen geometry.

Slice-1 kept this in sqlite behind a profile editor. Here it is a constant:
there is one machine, its envelope does not change between requests, and a
frozen dataclass is honest about that. If per-user machine profiles are ever
wanted, this is the seam to widen — everything downstream takes a Profile.
"""
from __future__ import annotations

from dataclasses import dataclass

PEN_MODES = ("z-axis", "servo-pwm")


@dataclass(frozen=True)
class Profile:
    name: str = "Default"
    controller: str = "grbl"
    baud: int = 115200
    rx_buffer: int = 128
    pen_mode: str = "servo-pwm"
    travel_x: float = 300.0
    travel_y: float = 200.0
    travel_z: float = 5.0
    # Matches what pcb_gcode.py emits: Z >= 0 holds the pen up, Z < 0
    # drops it. These drive the pen up/down readout, not the G-code.
    pen_up_z: float = 0.5
    pen_down_z: float = -0.5
    servo_up: int = 0
    servo_down: int = 255
    travel_feed: float = 3000.0
    draw_feed: float = 1200.0
    z_feed: float = 500.0
    jog_feed: float = 1000.0


DEFAULT_PROFILE = Profile()
