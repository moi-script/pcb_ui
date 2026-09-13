"""Convert extracted PCB wiring into G-code for a pen-plotter / drawing machine.

Flow:  KiCad file  ->  pcb_read.wiring_data  ->  G-code  ->  GRBL (grbl_servo_z)

Each track segment becomes a pen-up travel to its start, a pen-down, a draw
to its end, then a pen-up. Coordinates are passed straight through in mm.

This targets a SINGLE-LAYER plot by default (front copper), which is the
common case for the mini / hobby projects this tool is aimed at.
"""
from pcb_read import wiring_data

# ---- Machine configuration (edit to match your plotter) --------------------
CONFIG = {
    # Z targets grbl_servo_z, where Z is an SG90 acting as a binary pen
    # actuator, not a stepper. Its servo_set_z() is
    #     if (z_steps < SERVO_Z_THRESHOLD_STEPS)   // threshold 0, strictly <
    # so pen-down MUST be negative. A Z0 plunge reads as pen-up and plots the
    # whole board in the air.
    #
    # The heights are symbolic: the servo throws the pen mechanically, so
    # nothing here sets a physical clearance. Only the sign matters, and the
    # travel, which is kept to 1 mm so a transition is quick.
    "pen_up_z": 0.5,        # >= 0 -> servo holds the pen up
    "pen_down_z": -0.5,     # < 0  -> servo drops the pen
    # Z is still a fully planned Grbl axis, so a Z move's duration is what
    # gives the servo time to travel; no dwell is needed. 1 mm at F200 is
    # 300 ms, the budget the grbl_servo_z README sets for an SG90. Raising
    # this feed or shortening the throw starts the next X/Y move before the
    # pen has landed.
    "z_feed": 200,          # speed for pen up/down moves (mm/min)
    # grbl_servo_z caps every axis at 500 mm/min ($110-$112 in its
    # defaults.h). Grbl clamps a faster F without a word, so asking for more
    # changes nothing on the machine and only makes estimates wrong. Raise
    # these together with $110/$111 if the 28BYJ-48s keep up.
    "travel_feed": 500,     # speed for pen-up moves (mm/min)
    "draw_feed": 500,       # speed while drawing (mm/min)
    "flip_y": False,        # set True if your machine's Y is inverted vs KiCad
    "layer": "F.Cu",        # which copper layer to plot ("F.Cu", "B.Cu", or None for all)
    "optimize": True,       # reorder tracks to minimise pen-up travel
}


def _y(y):
    return -y if CONFIG["flip_y"] else y


def _to_origin(pairs):
    """Shift every point so the drawing's own bottom-left corner is (0, 0)."""
    if not pairs:
        return pairs
    xs = [p[0] for pair in pairs for p in pair]
    ys = [p[1] for pair in pairs for p in pair]
    dx, dy = min(xs), min(ys)
    if dx == 0 and dy == 0:
        return pairs
    return [
        ((a[0] - dx, a[1] - dy), (b[0] - dx, b[1] - dy)) for a, b in pairs
    ]


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def optimize_order(tracks, start=(0.0, 0.0)):
    """Greedy nearest-neighbour ordering with endpoint flipping.

    Returns a list of (start, end) pairs oriented so each trace begins at the
    endpoint nearest the pen's current position, minimising pen-up travel.
    """
    return optimize_order_pairs(
        [(r["start"], r["end"]) for r in tracks], start
    )


def optimize_order_pairs(pairs, start=(0.0, 0.0)):
    """`optimize_order` on bare (start, end) pairs.

    The generator normalises coordinates before ordering them, at which
    point they are no longer the track dicts that came out of the file.
    """
    remaining = list(pairs)
    pos = start
    ordered = []
    while remaining:
        best_i, best_d, best_flip = 0, float("inf"), False
        for i, (rs, re_) in enumerate(remaining):
            ds = _dist(pos, rs)
            de = _dist(pos, re_)
            if ds < best_d:
                best_i, best_d, best_flip = i, ds, False
            if de < best_d:
                best_i, best_d, best_flip = i, de, True
        rs, re_ = remaining.pop(best_i)
        s, e = (re_, rs) if best_flip else (rs, re_)
        ordered.append((s, e))
        pos = e
    return ordered


def travel_distance(pairs, start=(0.0, 0.0)):
    """Total pen-up (travel) distance for an ordered list of (start, end)."""
    pos, total = start, 0.0
    for s, e in pairs:
        total += _dist(pos, s)
        pos = e
    return total


def generate_gcode(data, cfg=CONFIG):
    """Return a list of G-code lines for the given wiring data."""
    up, down = cfg["pen_up_z"], cfg["pen_down_z"]
    tf, df = cfg["travel_feed"], cfg["draw_feed"]
    zf = cfg.get("z_feed", 200)

    tracks = [r for r in data if r["type"] == "track"
              and (cfg["layer"] is None or r["layer"] == cfg["layer"])]

    pairs = [(r["start"], r["end"]) for r in tracks]

    # Move the board to its own corner before anything else looks at it.
    #
    # A KiCad file places the board wherever it sits on the sheet, which is
    # routinely a hundred millimetres from the origin. Those numbers are
    # meaningless to the machine: the operator sets work zero at the corner
    # of the copper, so plotting the sheet coordinates sends the pen off to
    # find a board that is not there — and on a 100 mm bed, straight past
    # the end of the travel. Normalising here also makes the plot agree
    # with the preview, which has always drawn the board at the origin.
    #
    # Before `optimize_order`, deliberately: that orders tracks by distance
    # from the pen's starting point, and the starting point is work zero.
    # Measured from a corner the board is nowhere near, "nearest first" is
    # not the question anyone meant to ask.
    pairs = _to_origin(pairs)

    if cfg["optimize"]:
        pairs = optimize_order_pairs(pairs)

    lines = [
        "; Generated by pcb_gcode.py",
        f"; layer={cfg['layer']}  tracks={len(tracks)}  optimize={cfg['optimize']}",
        f"; pen-up travel = {travel_distance(pairs):.1f} mm",
        "G21",              # units = millimetres
        "G90",              # absolute positioning
        # Every Z move is a timed G1, never a G0: a rapid would reach the next
        # X/Y before the servo has finished swinging.
        f"G1 Z{up:g} F{zf}",   # start with pen up
    ]

    for (x0, y0), (x1, y1) in pairs:
        lines += [
            f"G0 X{x0:g} Y{_y(y0):g} F{tf}",   # travel to start (pen up)
            f"G1 Z{down:g} F{zf}",             # pen down
            f"G1 X{x1:g} Y{_y(y1):g} F{df}",   # draw the trace
            f"G1 Z{up:g} F{zf}",               # pen up
        ]

    lines += [
        "G0 X0 Y0 F%d" % tf,   # return home
        "M2",                  # program end
    ]
    return lines


def main():
    lines = generate_gcode(wiring_data)
    out = "labExam.gcode"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    n_tracks = sum(1 for r in wiring_data if r["type"] == "track"
                   and (CONFIG["layer"] is None or r["layer"] == CONFIG["layer"]))
    print(f"Wrote {out}: {len(lines)} lines, {n_tracks} tracks on layer {CONFIG['layer']}.")


if __name__ == "__main__":
    main()
