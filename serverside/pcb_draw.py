"""Draw the extracted PCB wiring on a matplotlib canvas.

Reuses the parser in pcb_read.py to get `wiring_data`, then renders each
track segment as a line (coloured by net) and each via as a dot.
Y is inverted so the picture matches KiCad's screen orientation.
"""
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from pcb_read import read_file

board = sys.argv[1] if len(sys.argv) > 1 else "newProject.kicad_pcb"
stem = os.path.splitext(os.path.basename(board))[0]
wiring_data = read_file(board)

# Colour by copper layer (KiCad convention: F.Cu red, B.Cu blue)
layer_color = {"F.Cu": "red", "B.Cu": "blue"}
default_color = "green"          # any unexpected layer stands out

fig, ax = plt.subplots(figsize=(11, 11))

for row in wiring_data:
    if row["type"] == "track":
        color = layer_color.get(row["layer"], default_color)
        (x0, y0), (x1, y1) = row["start"], row["end"]
        ax.plot([x0, x1], [y0, y1],
                color=color, linewidth=row["width_mm"] * 4, solid_capstyle="round")
    elif row["type"] == "via":
        x, y = row["position"]
        ax.plot(x, y, "o", color="green", markersize=(row["size_mm"] or 0.6) * 6,
                markeredgecolor="black")

ax.set_aspect("equal")
ax.invert_yaxis()                     # KiCad Y points down
ax.set_xlabel("X (mm)")
ax.set_ylabel("Y (mm)")
ax.set_title(f"{os.path.basename(board)}  -  {len(wiring_data)} elements")
ax.grid(True, linewidth=0.3, alpha=0.4)

# Legend of layers (only those actually present)
present = [lay for lay in layer_color if any(
    r["type"] == "track" and r["layer"] == lay for r in wiring_data)]
handles = [Line2D([0], [0], color=layer_color[lay], lw=3, label=lay) for lay in present]
ax.legend(handles=handles, fontsize=10, loc="upper right")

fig.tight_layout()
out = f"{stem}_wiring.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved {out}")
