"""Visually verify a .gcode file before sending it to the machine.

Parses the G-code and plots draw moves (pen down) as solid red lines and
travel moves (pen up) as thin grey dashes -- so you can confirm the toolpath
looks right without any hardware.
"""
import re
import sys

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


def parse_gcode(path):
    """Yield (x0, y0, x1, y1, drawing) for each XY move."""
    x = y = 0.0
    pen_down = False
    coord = re.compile(r"([XYZ])(-?\d+\.?\d*)")
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split(";", 1)[0].strip()
            if not line:
                continue
            words = dict(coord.findall(line.upper()))
            if "Z" in words:                       # pen state follows Z
                pen_down = float(words["Z"]) <= 0.0
            if "X" in words or "Y" in words:
                nx = float(words.get("X", x))
                ny = float(words.get("Y", y))
                yield x, y, nx, ny, pen_down
                x, y = nx, ny


def main(path="labExam.gcode"):
    fig, ax = plt.subplots(figsize=(11, 11))
    n_draw = n_travel = 0
    for x0, y0, x1, y1, drawing in parse_gcode(path):
        if drawing:
            ax.plot([x0, x1], [y0, y1], color="red", linewidth=1.2)
            n_draw += 1
        else:
            ax.plot([x0, x1], [y0, y1], color="grey", linewidth=0.4,
                    linestyle="--", alpha=0.5)
            n_travel += 1

    ax.set_aspect("equal")
    ax.invert_yaxis()
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.set_title(f"{path}  -  {n_draw} draw / {n_travel} travel moves")
    ax.grid(True, linewidth=0.3, alpha=0.4)
    ax.legend(handles=[
        Line2D([0], [0], color="red", lw=2, label="draw (pen down)"),
        Line2D([0], [0], color="grey", lw=1, ls="--", label="travel (pen up)"),
    ], loc="upper right")

    out = path.rsplit(".", 1)[0] + "_toolpath.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved {out}: {n_draw} draw moves, {n_travel} travel moves.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "labExam.gcode")
