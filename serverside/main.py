"""PCB Plotter pipeline runner.

Executes the full flow in order, one step at a time, with clear status output.
Each stage is also runnable on its own; this just chains them.

    KiCad file
      1. parse        pcb_read.py           -> wiring_data (in-memory)
      2. board preview pcb_draw.py           -> labExam_wiring.png
      3. G-code       pcb_gcode.py           -> labExam.gcode
      4. verify path  pcb_gcode_preview.py   -> labExam_toolpath.png

Usage:
    python main.py                # run every step
    python main.py --skip-preview # run without the matplotlib image steps
"""
import subprocess
import sys
import time

# Step 1 uses a compact summary instead of pcb_read.py's full row dump.
PARSE_SUMMARY = (
    "from pcb_read import wiring_data;"
    "n=len(wiring_data);"
    "layers=sorted({r['layer'] for r in wiring_data if r['type']=='track'});"
    "print(f'Parsed {n} elements; track layers: '+', '.join(layers))"
)

STEPS = [
    ("Parse KiCad file", [sys.executable, "-c", PARSE_SUMMARY], False),
    ("Render board preview (by layer)", [sys.executable, "pcb_draw.py"], True),
    ("Generate optimized G-code", [sys.executable, "pcb_gcode.py"], False),
    ("Verify toolpath", [sys.executable, "pcb_gcode_preview.py"], True),
]


def run_step(index, title, cmd):
    print(f"\n{'='*60}")
    print(f"STEP {index}: {title}")
    print("-" * 60)
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.time() - t0
    for line in result.stdout.splitlines():
        print(f"  {line}")
    if result.returncode != 0:
        for line in result.stderr.splitlines():
            print(f"  {line}")
        print(f"\n[FAILED] step exited with code {result.returncode}")
        sys.exit(result.returncode)
    print(f"[OK] {title}  ({dt:.1f}s)")


def main():
    skip_preview = "--skip-preview" in sys.argv
    print("PCB Plotter pipeline")
    if skip_preview:
        print("(skipping matplotlib preview steps)")

    n = 0
    for title, cmd, is_preview in STEPS:
        if is_preview and skip_preview:
            continue
        n += 1
        run_step(n, title, cmd)

    print(f"\n{'='*60}")
    print("Pipeline complete. Outputs:")
    print("  labExam_wiring.png     - board traces by copper layer")
    print("  labExam.gcode          - plotter-ready G-code (optimized)")
    print("  labExam_toolpath.png   - G-code toolpath verification")
    print("\nNext: stream labExam.gcode to GRBL/FluidNC (USB or WiFi).")


if __name__ == "__main__":
    main()
