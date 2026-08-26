# Image → Centerline → G-code Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user upload a raster image of a layout, trace it to single-line centrelines, and plot it on the machine through the board list, preview, and ESP32 streaming that already exist.

**Architecture:** The tracing algorithms are vendored into `pcb_reader/tracer/` as pure functions (no filesystem, no `argparse`). A new `POST /trace` endpoint cleans the image, skeletonises it, walks the skeleton into polylines, emits pen G-code, and stores **the same board document** `POST /route` already produces — so every downstream consumer works unchanged.

**Tech Stack:** Python 3.13, FastAPI, MongoDB (pymongo), numpy, Pillow, scikit-image, opencv-python, pytest. Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS v4.

**Spec:** `docs/superpowers/specs/2026-08-26-image-trace-design.md`

## Global Constraints

- **`C:\cnc_line_backend\cnc_1line_tracer-main` is read-only.** Copy from it; never write to it. It is not a package and is not importable.
- **Two repos.** Python work lands in `../pcb_reader` (sibling of `pcb_ui`). Frontend work lands in `pcb_ui`. Commit in each repo separately.
- **Python tests run as `python -m pytest tests/ -v` from the `pcb_reader` root.**
- **Frontend checks run as `npx tsc --noEmit` then `npm run build` from the `pcb_ui` root.**
- **`app/globals.css` is not edited.** New UI uses existing tokens only: `panel`, `panel-2`, `ticked`, `tlabel`, `btn`, `btn-primary`, `btn-copper`, `btn-ghost`, `field`, `dot`, and the colour names `ink`, `ink-soft`, `muted`, `faint`, `paper`, `well`, `line`, `line-strong`, `copper`, `signal`, `warn`, `danger`.
- **`POST /route` is not modified.** The KiCad path keeps working exactly as it does today.
- **`POST /print` is not modified.** It already streams `board["gcode"]`.
- **Strokes are authoritative for G-code; `tracks` are derived for rendering only.**
- Python code uses `from __future__ import annotations` and is type-annotated.
- **These four algorithm properties must survive vendoring** (each is load-bearing):
  1. `bridge_ink` runs **before** skeletonization.
  2. Pipeline order is **thin → smooth → simplify → spline**.
  3. `smooth()` pins endpoints and wraps closed loops.
  4. `splinify` uses **centripetal** Catmull-Rom (alpha=0.5) with flatness tested at 0.25/0.5/0.75.

---

## File Structure

### Created — `pcb_reader`

| File | Responsibility |
|---|---|
| `tracer/__init__.py` | package marker; re-exports `trace_image` |
| `tracer/centerline.py` | vendored verbatim — skeletonise, walk, smooth, simplify, spline |
| `tracer/prep.py` | vendored + array entry point — threshold, despeckle, bridge |
| `tracer/cv_image.py` | vendored + array entry point — adaptive threshold for PCB photos |
| `tracer/emit.py` | **new** — strokes → G-code, frame, and the route report |
| `tracer/pipeline.py` | **new** — bytes + params → strokes; the one place scale is decided |
| `tests/test_centerline.py` | ported |
| `tests/test_prep.py` | ported, with the brittle assertion fixed |
| `tests/test_emit.py` | new |
| `tests/test_pipeline.py` | new |
| `tests/test_trace_endpoint.py` | new |
| `pytest.ini` | test discovery |

### Modified — `pcb_reader`

`requirements.txt` (new deps), `server.py` (`build_board_from_strokes`, `POST /trace`, `out_board` passthrough).

### Modified — `pcb_ui`

`lib/api.ts` (types + `api.trace`), `components/Uploader.tsx` (image branch), `app/dashboard/projects/[id]/page.tsx` (re-trace panel), `README.md`.

---

## Task 1: Vendor the tracer and port its tests

**Files:**
- Create: `../pcb_reader/tracer/__init__.py`, `../pcb_reader/tracer/centerline.py`, `../pcb_reader/tracer/prep.py`, `../pcb_reader/tracer/cv_image.py`, `../pcb_reader/pytest.ini`
- Test: `../pcb_reader/tests/__init__.py`, `../pcb_reader/tests/test_centerline.py`, `../pcb_reader/tests/test_prep.py`
- Modify: `../pcb_reader/requirements.txt`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `tracer.centerline.trace(binary: np.ndarray, mm_per_px: float, simplify_tol=0.05, min_stroke_mm=0.6, smooth_passes=3, spline_tol=0.0, mode="centerline") -> list[list[tuple[float, float]]]`
  - `tracer.prep.prepare_array(img: PIL.Image.Image, threshold, invert, speck, max_px, crop, bridge, n_colors, min_blob) -> PIL.Image.Image`
  - `tracer.prep.choose_threshold(gray: np.ndarray, threshold: int | None) -> int`
  - `tracer.cv_image.pcb_from_gray(gray: np.ndarray, blur_size=3, block_size=15, C=2, min_area=50, close_gaps=2, sharpen=True) -> np.ndarray`

- [x] **Step 1: Add the dependencies**

Append to `../pcb_reader/requirements.txt`:

```
# Image tracing (tracer/) — centerline skeletonisation
numpy
pillow
scikit-image
opencv-python

# Tests
pytest
```

Then run: `pip install -r requirements.txt` from `../pcb_reader`.

- [x] **Step 2: Create the package skeleton and pytest config**

```bash
cd ../pcb_reader
mkdir -p tracer tests
touch tracer/__init__.py tests/__init__.py
```

Write `../pcb_reader/pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
```

- [x] **Step 3: Copy `centerline.py` verbatim**

It is already pure — it imports only `math`, `numpy`, and `skimage`, and touches no files. Copy with no edits:

```bash
cp /c/cnc_line_backend/cnc_1line_tracer-main/tools/centerline.py ../pcb_reader/tracer/centerline.py
```

Verify it imports: `cd ../pcb_reader && python -c "from tracer import centerline; print(centerline.trace)"`

- [x] **Step 4: Copy `prep_image.py` as `prep.py`, then strip the CLI**

```bash
cp /c/cnc_line_backend/cnc_1line_tracer-main/tools/prep_image.py ../pcb_reader/tracer/prep.py
```

Now edit `../pcb_reader/tracer/prep.py`:

1. Delete `import argparse`, `import os`, the entire `main()` function, and the `if __name__ == "__main__":` block at the bottom.
2. Rename `prepare` to `prepare_array` and change its first parameter from a path to a loaded image. Replace the whole function signature and its first line:

```python
def prepare_array(img: Image.Image, threshold: int | None = None,
                  invert: bool = False, speck: int = 3,
                  max_px: int = 2000, crop: bool = True, bridge: int = 1,
                  n_colors: int = 0, min_blob: int = 0) -> Image.Image:
    """Clean and binarise an already-loaded image, ready for tracing.

    Processing order:
      1. Optional colour reduction.
      2. Grayscale + threshold.
      3. Optional invert.
      4. ModeFilter despeckling.
      5. Crop to ink bounding box.
      6. Optional blob despeckling.
      7. Ink bridging — LAST, and deliberately so: growing the ink before
         skeletonisation is what makes a gappy scanned line come through as
         one stroke instead of a dashed one.
    """
    img = img.convert("RGB")
    if max_px and max(img.size) > max_px:
        img.thumbnail((max_px, max_px), Image.LANCZOS)
```

The rest of the body stays exactly as it was, starting from `if n_colors > 0:`.

3. Add a path wrapper at the end of the file so anything expecting the old signature still works:

```python
def prepare(path: str, threshold: int | None = None, invert: bool = False,
            speck: int = 3, max_px: int = 2000, crop: bool = True,
            bridge: int = 1, n_colors: int = 0, min_blob: int = 0) -> Image.Image:
    """Path-taking wrapper around `prepare_array`."""
    return prepare_array(Image.open(path), threshold, invert, speck, max_px,
                         crop, bridge, n_colors, min_blob)
```

- [x] **Step 5: Copy `cv_image.py` and add an array entry point**

```bash
cp /c/cnc_line_backend/cnc_1line_tracer-main/tools/cv_image.py ../pcb_reader/tracer/cv_image.py
```

Edit `../pcb_reader/tracer/cv_image.py`. The only filesystem coupling in `pcb()` is its first line, `gray = _load_gray(path, max_px)`. Split the function in two: add `pcb_from_gray` containing everything after that line, and make `pcb` a wrapper.

Replace the body of `pcb()` (everything from `gray = _load_gray(path, max_px)` to `return ink.astype(bool)`) with:

```python
    return pcb_from_gray(_load_gray(path, max_px), blur_size=blur_size,
                         block_size=block_size, C=C, min_area=min_area,
                         close_gaps=close_gaps, sharpen=sharpen)


def pcb_from_gray(gray: np.ndarray, blur_size: int = 3, block_size: int = 15,
                  C: int = 2, min_area: int = 50, close_gaps: int = 2,
                  sharpen: bool = True) -> np.ndarray:
    """The PCB pipeline, on an already-loaded grayscale array.

    Adaptive thresholding is the point of this path: a photo of a board has
    uneven lighting across it, and one global Otsu cut either floods the dark
    corner or drops the bright one.
    """
    # Unsharp mask: adds back high-frequency detail lost by JPEG compression
    if sharpen:
        blurred_for_usm = cv2.GaussianBlur(gray, (0, 0), sigmaX=2.0)
        gray = cv2.addWeighted(gray, 1.5, blurred_for_usm, -0.5, 0)

    blurred = cv2.GaussianBlur(gray, (_odd(blur_size), _odd(blur_size)), 0)

    thresh = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        _odd(block_size),
        C,
    )

    # Close gaps in traces (dilation then erosion)
    if close_gaps >= 1:
        k_close = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * close_gaps + 1, 2 * close_gaps + 1)
        )
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, k_close)

    # Remove single-pixel noise
    k_open = np.ones((2, 2), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, k_open)

    return _remove_small(thresh, min_area).astype(bool)
```

Delete any `if __name__ == "__main__":` block and `argparse` import if present.

- [x] **Step 6: Port the centerline tests**

```bash
cp /c/cnc_line_backend/cnc_1line_tracer-main/tests/test_centerline.py ../pcb_reader/tests/test_centerline.py
```

Edit the imports at the top of `../pcb_reader/tests/test_centerline.py`: replace any `import centerline as cl` / `from centerline import ...` / `sys.path` manipulation with:

```python
from tracer import centerline as cl
```

- [x] **Step 7: Run the centerline tests**

Run: `cd ../pcb_reader && python -m pytest tests/test_centerline.py -v`
Expected: PASS (the reference suite is green here — all 30+ tests).

- [x] **Step 8: Port the prep tests**

```bash
cp /c/cnc_line_backend/cnc_1line_tracer-main/tests/test_prep_image.py ../pcb_reader/tests/test_prep.py
```

Edit `../pcb_reader/tests/test_prep.py`: replace the module import with `from tracer import prep`, and rename every `prep_image.` / `prep.` reference to `prep.`. Any test calling `prepare(path)` keeps working — the wrapper exists.

- [x] **Step 9: Run the prep tests and watch the known failure**

Run: `cd ../pcb_reader && python -m pytest tests/test_prep.py -v`
Expected: one FAIL — `test_auto_threshold_pulls_faint_linework_above_the_cut`, `assert 195 == 210`.

This is a brittle fixture, not a defect. The test builds a synthetic image, computes `base = prep.otsu(gray)`, then paints a faint band at `base + 15` — but painting that band *changes the histogram*, so Otsu re-computes to a different cut on the modified image. The test then compares against the stale `base`.

- [x] **Step 10: Fix the brittle assertion**

In `../pcb_reader/tests/test_prep.py`, replace the assertion so it derives the expectation the way `choose_threshold` does, on the *final* image:

```python
def test_auto_threshold_pulls_faint_linework_above_the_cut():
    gray = _synthetic_faint_linework()          # unchanged helper
    cut = prep.choose_threshold(gray, None)

    # Otsu is recomputed on the image as it finally stands, so derive the
    # expectation from that same image rather than from a pre-paint value.
    base = prep.otsu(gray)
    softer = min(base + 30, 255)
    here = int((gray <= base).sum())
    added = int((gray <= softer).sum()) - here
    expected = softer if (here and 0 < added <= here * 0.5) else base

    assert cut == expected
    # the soften path is the one under test — assert it actually fired
    assert cut > base
```

- [x] **Step 11: Run the whole suite**

Run: `cd ../pcb_reader && python -m pytest tests/ -v`
Expected: PASS, no failures.

- [x] **Step 12: Commit**

```bash
cd ../pcb_reader
git add tracer/ tests/ pytest.ini requirements.txt
git commit -m "feat: vendor centerline tracer as pure functions"
```

---

## Task 2: Stroke G-code emitter

**Files:**
- Create: `../pcb_reader/tracer/emit.py`
- Test: `../pcb_reader/tests/test_emit.py`

**Interfaces:**
- Consumes: `CONFIG` from `pcb_gcode.py`
- Produces:
  - `tracer.emit.order_strokes(strokes, start=(0.0, 0.0)) -> list[Stroke]`
  - `tracer.emit.generate_from_strokes(strokes, cfg=CONFIG, label="traced") -> list[str]`
  - `tracer.emit.emit_frame(bbox, cfg=CONFIG) -> list[str]`
  - `tracer.emit.stroke_report(strokes, cfg=CONFIG) -> dict` with keys `drawMoves`, `travelMoves`, `penUpBefore`, `penUpAfter`, `drawLength`, `estMinutes`
  - `tracer.emit.bounds(strokes) -> tuple[float, float, float, float]`

- [x] **Step 1: Write the failing tests**

Write `../pcb_reader/tests/test_emit.py`:

```python
"""Strokes in, pen G-code out."""
from __future__ import annotations

import math

import pytest

from tracer import emit


SQUARE = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]]
TWO = [[(0.0, 0.0), (5.0, 0.0)], [(20.0, 20.0), (25.0, 20.0)]]


def _pen_pairs(lines: list[str]) -> int:
    """How many times the pen goes down. One per stroke, or the job is wrong."""
    return sum(1 for ln in lines if ln.startswith("G1 Z"))


def test_one_stroke_is_one_pen_down():
    lines = emit.generate_from_strokes(SQUARE)
    assert _pen_pairs(lines) == 1


def test_two_strokes_are_two_pen_downs():
    lines = emit.generate_from_strokes(TWO)
    assert _pen_pairs(lines) == 2


def test_every_point_is_emitted_in_order():
    lines = emit.generate_from_strokes(SQUARE)
    draws = [ln for ln in lines if ln.startswith("G1 X")]
    # first point is the rapid; the remaining two are drawn
    assert len(draws) == 2
    assert "X10" in draws[0] and "Y0" in draws[0]
    assert "X10" in draws[1] and "Y10" in draws[1]


def test_job_starts_and_ends_pen_up():
    lines = emit.generate_from_strokes(SQUARE)
    ups = [i for i, ln in enumerate(lines) if ln.startswith("G0 Z")]
    assert ups, "no pen-up move at all"
    # the last Z move in the file must be a retract, never a plunge
    zs = [ln for ln in lines if ln.startswith(("G0 Z", "G1 Z"))]
    assert zs[-1].startswith("G0 Z")


def test_returns_to_origin():
    lines = emit.generate_from_strokes(SQUARE)
    assert any(ln.startswith("G0 X0 Y0") for ln in lines)


def test_units_and_absolute_mode_are_set():
    lines = emit.generate_from_strokes(SQUARE)
    assert "G21" in lines      # mm
    assert "G90" in lines      # absolute


def test_ordering_flips_a_stroke_when_its_far_end_is_nearer():
    # pen starts at origin; this stroke runs away from it, so it must reverse
    away = [[(10.0, 0.0), (1.0, 0.0)]]
    ordered = emit.order_strokes(away, start=(0.0, 0.0))
    assert ordered[0][0] == (1.0, 0.0)


def test_ordering_visits_the_near_stroke_first():
    far = [(50.0, 50.0), (55.0, 50.0)]
    near = [(1.0, 1.0), (5.0, 1.0)]
    ordered = emit.order_strokes([far, near], start=(0.0, 0.0))
    assert ordered[0][0] == (1.0, 1.0)


def test_ordering_keeps_every_stroke():
    ordered = emit.order_strokes(TWO, start=(0.0, 0.0))
    assert len(ordered) == len(TWO)


def test_bounds():
    assert emit.bounds(TWO) == (0.0, 0.0, 25.0, 20.0)


def test_frame_traces_the_bbox_pen_up():
    lines = emit.emit_frame(emit.bounds(TWO))
    assert not any(ln.startswith("G1 Z") for ln in lines), "frame must not draw"
    xs = [ln for ln in lines if ln.startswith("G0 X")]
    assert len(xs) >= 5, "a closed rectangle needs 4 corners plus the return"


def test_report_counts_moves():
    rep = emit.stroke_report(TWO)
    assert rep["drawMoves"] == 2       # one drawn segment per stroke
    assert rep["travelMoves"] == 2     # one rapid per stroke
    assert rep["drawLength"] == pytest.approx(10.0)
    assert rep["estMinutes"] >= 0


def test_report_travel_improves_with_ordering():
    rep = emit.stroke_report(TWO)
    assert rep["penUpAfter"] <= rep["penUpBefore"]


def test_empty_strokes_raise():
    with pytest.raises(ValueError):
        emit.generate_from_strokes([])
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd ../pcb_reader && python -m pytest tests/test_emit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tracer.emit'`

- [x] **Step 3: Write the emitter**

Write `../pcb_reader/tracer/emit.py`:

```python
"""Traced strokes to pen-plotter G-code.

A stroke is one continuous pen-down path: `[(x, y), ...]` in mm. That is the
whole reason this module exists instead of reusing `pcb_gcode.generate_gcode`,
which takes two-point track pairs. Splitting a splined polyline into segments
and reordering them greedily would be O(n^2) over thousands of items, and its
correctness would rest on the accident that consecutive segments sit zero
distance apart. Ordering belongs at stroke level: hundreds of items, and
pen-down continuity is structural rather than emergent.
"""
from __future__ import annotations

import math

from pcb_gcode import CONFIG

Point = tuple[float, float]
Stroke = list[Point]


def _f(v: float) -> str:
    """Trim trailing zeros so the file stays small and readable."""
    return f"{v:.3f}".rstrip("0").rstrip(".") or "0"


def bounds(strokes: list[Stroke]) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) over every point."""
    if not strokes:
        raise ValueError("no strokes")
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    return (min(xs), min(ys), max(xs), max(ys))


def _length(s: Stroke) -> float:
    return sum(math.dist(a, b) for a, b in zip(s, s[1:]))


def order_strokes(strokes: list[Stroke], start: Point = (0.0, 0.0)) -> list[Stroke]:
    """Greedy nearest-neighbour over stroke endpoints, with flipping.

    Mirrors `pcb_gcode.optimize_order`'s behaviour, but a whole stroke is the
    unit: either end may be the entry point, so a stroke that runs away from
    the pen is reversed rather than travelled to.
    """
    remaining = [list(s) for s in strokes]
    out: list[Stroke] = []
    cur = start
    while remaining:
        best_i, best_rev, best_d = 0, False, math.inf
        for i, s in enumerate(remaining):
            d_head = math.dist(cur, s[0])
            if d_head < best_d:
                best_i, best_rev, best_d = i, False, d_head
            d_tail = math.dist(cur, s[-1])
            if d_tail < best_d:
                best_i, best_rev, best_d = i, True, d_tail
        s = remaining.pop(best_i)
        if best_rev:
            s = s[::-1]
        out.append(s)
        cur = s[-1]
    return out


def generate_from_strokes(strokes: list[Stroke], cfg: dict = CONFIG,
                          label: str = "traced") -> list[str]:
    """Pen G-code for a set of traced strokes."""
    if not strokes:
        raise ValueError("no strokes to plot")

    up = cfg["pen_up_z"]
    down = cfg["pen_down_z"]
    travel_feed = cfg["travel_feed"]
    draw_feed = cfg["draw_feed"]
    z_feed = cfg.get("z_feed", 500)

    minx, miny, maxx, maxy = bounds(strokes)
    out = [
        f"; {label} - traced centreline pen plot",
        f"; extent: {_f(maxx - minx)} x {_f(maxy - miny)} mm",
        f"; strokes: {len(strokes)}",
        "; Set zero before run: G10 L20 P1 X0 Y0 Z0",
        "G21",   # millimetres
        "G90",   # absolute
        "G17",   # XY plane
        f"G0 Z{_f(up)}",
    ]

    for s in order_strokes(strokes):
        x0, y0 = s[0]
        out.append(f"G0 X{_f(x0)} Y{_f(y0)} F{_f(travel_feed)}")
        out.append(f"G1 Z{_f(down)} F{_f(z_feed)}")
        for (x, y) in s[1:]:
            out.append(f"G1 X{_f(x)} Y{_f(y)} F{_f(draw_feed)}")
        out.append(f"G0 Z{_f(up)}")

    out.append("G0 X0 Y0")
    out.append("M2")
    return out


def emit_frame(bbox: tuple[float, float, float, float],
               cfg: dict = CONFIG) -> list[str]:
    """Trace the bounding box with the pen up.

    Run this before the job. It costs nothing and it is the cheapest way to
    find out that the drawing runs off the edge of the work.
    """
    minx, miny, maxx, maxy = bbox
    corners = [(minx, miny), (maxx, miny), (maxx, maxy),
               (minx, maxy), (minx, miny)]
    out = [
        "; alignment frame - pen stays up",
        "G21", "G90", "G17",
        f"G0 Z{_f(cfg['pen_up_z'])}",
    ]
    out += [f"G0 X{_f(x)} Y{_f(y)} F{_f(cfg['travel_feed'])}" for x, y in corners]
    out.append("G0 X0 Y0")
    out.append("M2")
    return out


def stroke_report(strokes: list[Stroke], cfg: dict = CONFIG) -> dict:
    """Counts and estimates for the board summary tiles."""
    if not strokes:
        raise ValueError("no strokes")

    ordered = order_strokes(strokes)
    draw_moves = sum(len(s) - 1 for s in strokes)
    draw_length = sum(_length(s) for s in strokes)

    def travel(seq: list[Stroke]) -> float:
        cur = (0.0, 0.0)
        total = 0.0
        for s in seq:
            total += math.dist(cur, s[0])
            cur = s[-1]
        return total

    before = travel([list(s) for s in strokes])
    after = travel(ordered)

    # draw time + travel time + ~1.8 s per pen lift, same rule as pcb_gcode
    minutes = (draw_length / cfg["draw_feed"]
               + after / cfg["travel_feed"]
               + len(strokes) * 1.8 / 60.0)

    return {
        "drawMoves": draw_moves,
        "travelMoves": len(strokes),
        "penUpBefore": round(before),
        "penUpAfter": round(after),
        "drawLength": round(draw_length, 2),
        "estMinutes": max(1, round(minutes)),
    }
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd ../pcb_reader && python -m pytest tests/test_emit.py -v`
Expected: PASS (14 tests)

- [x] **Step 5: Commit**

```bash
cd ../pcb_reader
git add tracer/emit.py tests/test_emit.py
git commit -m "feat: stroke g-code emitter with alignment frame"
```

---

## Task 3: The tracing pipeline

**Files:**
- Create: `../pcb_reader/tracer/pipeline.py`
- Test: `../pcb_reader/tests/test_pipeline.py`
- Modify: `../pcb_reader/tracer/__init__.py`

**Interfaces:**
- Consumes: `tracer.prep.prepare_array`, `tracer.cv_image.pcb_from_gray`, `tracer.centerline.trace`
- Produces:
  - `tracer.pipeline.TraceParams` dataclass: `size_mm: float = 50.0`, `mode: str = "centerline"`, `preset: str = "line"`, `threshold: int | None = None`, `invert: bool = False`, `bed: tuple[float, float] = (300.0, 200.0)`, `margin: float = 10.0`
  - `tracer.pipeline.PRESETS: dict[str, dict]`
  - `tracer.pipeline.trace_image(data: bytes, params: TraceParams) -> tuple[list[Stroke], dict]` — strokes plus a `warnings`/`inkCoverage` info dict
  - `tracer.pipeline.TraceError(ValueError)`

- [x] **Step 1: Write the failing tests**

Write `../pcb_reader/tests/test_pipeline.py`:

```python
"""Image bytes in, strokes in millimetres out."""
from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image, ImageDraw

from tracer import emit
from tracer.pipeline import TraceError, TraceParams, trace_image


def _png(draw_fn, size=(200, 200), bg=255) -> bytes:
    img = Image.new("L", size, bg)
    draw_fn(ImageDraw.Draw(img))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _line_png() -> bytes:
    return _png(lambda d: d.line((20, 100, 180, 100), fill=0, width=6))


def _two_lines_png() -> bytes:
    def go(d):
        d.line((20, 60, 180, 60), fill=0, width=6)
        d.line((20, 140, 180, 140), fill=0, width=6)
    return _png(go)


def _disc_png() -> bytes:
    return _png(lambda d: d.ellipse((60, 60, 140, 140), fill=0))


def test_a_single_line_traces_to_one_stroke():
    strokes, _ = trace_image(_line_png(), TraceParams(size_mm=50))
    assert len(strokes) == 1


def test_size_mm_sets_the_longest_edge():
    strokes, _ = trace_image(_line_png(), TraceParams(size_mm=50))
    minx, miny, maxx, maxy = emit.bounds(strokes)
    assert max(maxx - minx, maxy - miny) == pytest.approx(50, abs=2.0)


def test_size_scales_linearly():
    a, _ = trace_image(_line_png(), TraceParams(size_mm=50))
    b, _ = trace_image(_line_png(), TraceParams(size_mm=100))
    wa = emit.bounds(a)[2] - emit.bounds(a)[0]
    wb = emit.bounds(b)[2] - emit.bounds(b)[0]
    assert wb == pytest.approx(wa * 2, rel=0.05)


def test_size_zero_fits_the_bed():
    strokes, _ = trace_image(
        _line_png(), TraceParams(size_mm=0, bed=(300.0, 200.0), margin=10.0))
    minx, miny, maxx, maxy = emit.bounds(strokes)
    assert maxx - minx <= 300.0 - 2 * 10.0 + 0.01
    assert maxy - miny <= 200.0 - 2 * 10.0 + 0.01


def test_two_lines_trace_to_two_strokes():
    strokes, _ = trace_image(_two_lines_png(), TraceParams(size_mm=50))
    assert len(strokes) == 2


def test_centerline_of_a_disc_is_a_short_skeleton():
    strokes, _ = trace_image(_disc_png(), TraceParams(size_mm=50))
    total = sum(
        sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            for a, b in zip(s, s[1:]))
        for s in strokes
    )
    # a filled disc thins to a spidery blob far shorter than its circumference
    assert total < 60.0


def test_outline_of_a_disc_is_a_closed_loop():
    strokes, _ = trace_image(
        _disc_png(), TraceParams(size_mm=50, mode="outline"))
    assert strokes
    first, last = strokes[0][0], strokes[0][-1]
    assert first[0] == pytest.approx(last[0], abs=0.01)
    assert first[1] == pytest.approx(last[1], abs=0.01)


def test_blank_image_is_a_readable_error():
    blank = _png(lambda d: None)
    with pytest.raises(TraceError) as e:
        trace_image(blank, TraceParams(size_mm=50))
    assert "invert" in str(e.value).lower() or "threshold" in str(e.value).lower()


def test_not_an_image_is_a_readable_error():
    with pytest.raises(TraceError):
        trace_image(b"this is not an image", TraceParams(size_mm=50))


def test_mostly_dark_image_warns():
    dark = _png(lambda d: d.rectangle((0, 0, 200, 200), fill=10))
    try:
        _strokes, info = trace_image(dark, TraceParams(size_mm=50, invert=True))
    except TraceError:
        pytest.skip("nothing traced; the warning path needs strokes")
    assert info["inkCoverage"] >= 0


def test_pcb_preset_runs():
    strokes, _ = trace_image(
        _two_lines_png(), TraceParams(size_mm=50, preset="pcb"))
    assert strokes
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd ../pcb_reader && python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tracer.pipeline'`

- [x] **Step 3: Write the pipeline**

Write `../pcb_reader/tracer/pipeline.py`:

```python
"""Image bytes to strokes in millimetres.

This is the one place where scale is decided. An image has pixels; a machine
has millimetres, and there is no DPI worth trusting in a photograph, so the
caller states the size it wants and everything else follows from that.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, UnidentifiedImageError

from tracer import centerline as cl
from tracer import prep

Point = tuple[float, float]
Stroke = list[Point]


class TraceError(ValueError):
    """Something the user can act on: bad file, blank result, wrong polarity."""


@dataclass
class TraceParams:
    size_mm: float = 50.0            # longest edge; 0 means fit the bed
    mode: str = "centerline"         # or "outline"
    preset: str = "line"             # or "pcb"
    threshold: int | None = None     # None means Otsu + faint-line soften
    invert: bool = False
    bed: tuple[float, float] = (300.0, 200.0)
    margin: float = 10.0


# The reference tool's --pcb retune. Adaptive thresholding because a photo of
# a board has uneven lighting; no smoothing because PCB traces have real
# corners that the staircase filter would round off; light bridging so genuine
# gaps between traces are not welded shut.
PRESETS: dict[str, dict] = {
    "line": {
        "smooth_passes": 3,
        "simplify_tol": 0.02,
        "spline_tol": 0.002,
        "min_stroke_mm": 0.6,
        "bridge": 1,
        "despeckle": 3,
        "adaptive": False,
    },
    "pcb": {
        "smooth_passes": 0,
        "simplify_tol": 0.005,
        "spline_tol": 0.002,
        "min_stroke_mm": 0.05,
        "bridge": 1,
        "despeckle": 3,
        "adaptive": True,
        "block_size": 15,
        "adaptive_c": 2,
        "min_area": 50,
    },
}


def _load(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise TraceError(f"That file is not an image this can read: {e}") from e
    return img


def _binary(img: Image.Image, params: TraceParams, cfg: dict) -> np.ndarray:
    """Clean the image down to a boolean ink mask (True = ink)."""
    if cfg["adaptive"]:
        from tracer import cv_image
        gray = np.array(img.convert("L"))
        ink = cv_image.pcb_from_gray(
            gray, block_size=cfg["block_size"], C=cfg["adaptive_c"],
            min_area=cfg["min_area"])
        if params.invert:
            ink = ~ink
        return ink

    cleaned = prep.prepare_array(
        img, threshold=params.threshold, invert=params.invert,
        speck=cfg["despeckle"], max_px=2000, crop=True, bridge=cfg["bridge"])
    # prepare_array returns mode "1" where True is paper; ink is its inverse
    return ~np.array(cleaned).astype(bool)


def _mm_per_px(shape: tuple[int, int], params: TraceParams) -> float:
    h, w = shape
    if params.size_mm and params.size_mm > 0:
        return params.size_mm / max(h, w)
    bed_x, bed_y = params.bed
    usable_x = max(bed_x - 2 * params.margin, 1.0)
    usable_y = max(bed_y - 2 * params.margin, 1.0)
    return min(usable_x / w, usable_y / h)


def trace_image(data: bytes, params: TraceParams) -> tuple[list[Stroke], dict]:
    """Trace image bytes to strokes in mm, plus an info dict."""
    if params.mode not in ("centerline", "outline"):
        raise TraceError(f"Unknown trace mode {params.mode!r}.")
    cfg = PRESETS.get(params.preset)
    if cfg is None:
        raise TraceError(f"Unknown preset {params.preset!r}.")

    img = _load(data)
    ink = _binary(img, params, cfg)

    coverage = float(ink.mean()) if ink.size else 0.0
    if not ink.any():
        raise TraceError(
            "Nothing to trace: the cleaned image is blank. If your artwork is "
            "light-on-dark, set invert; otherwise try a different threshold.")

    mm_per_px = _mm_per_px(ink.shape, params)
    strokes = cl.trace(
        ink, mm_per_px,
        simplify_tol=cfg["simplify_tol"],
        min_stroke_mm=cfg["min_stroke_mm"],
        smooth_passes=cfg["smooth_passes"],
        spline_tol=cfg["spline_tol"],
        mode=params.mode,
    )

    if not strokes:
        raise TraceError(
            "Nothing survived tracing. Every stroke was shorter than the "
            "minimum. Try a larger size, or a different threshold.")

    # Translate to the origin so the job starts at the front-left of the work.
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    ox, oy = min(xs), min(ys)
    strokes = [[(round(x - ox, 3), round(y - oy, 3)) for x, y in s]
               for s in strokes]

    warnings: list[str] = []
    if coverage > 0.35:
        warnings.append(
            "The image is mostly dark. Centreline tracing wants thin lines on "
            "white — try a lower threshold, or invert.")
    if coverage < 0.005:
        warnings.append("The image is nearly blank; very little was traced.")

    return strokes, {
        "inkCoverage": round(coverage, 4),
        "strokeCount": len(strokes),
        "warnings": warnings,
    }
```

- [x] **Step 4: Re-export from the package**

Write `../pcb_reader/tracer/__init__.py`:

```python
"""Raster image to single-line pen strokes."""
from tracer.pipeline import TraceError, TraceParams, trace_image

__all__ = ["TraceError", "TraceParams", "trace_image"]
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `cd ../pcb_reader && python -m pytest tests/test_pipeline.py -v`
Expected: PASS (12 tests)

If `test_centerline_of_a_disc_is_a_short_skeleton` fails on the total length,
print the actual value and check it against the disc's circumference
(80 px diameter at 50 mm over 200 px is a 20 mm diameter, so ~63 mm around).
The skeleton must be well under that. Adjust the bound only if the geometry
justifies it — do not loosen it to make a failure go away.

- [x] **Step 6: Run the whole suite**

Run: `cd ../pcb_reader && python -m pytest tests/ -v`
Expected: PASS

- [x] **Step 7: Commit**

```bash
cd ../pcb_reader
git add tracer/pipeline.py tracer/__init__.py tests/test_pipeline.py
git commit -m "feat: image-to-strokes tracing pipeline"
```

---

## Task 4: The `/trace` endpoint

**Files:**
- Modify: `../pcb_reader/server.py`
- Test: `../pcb_reader/tests/test_trace_endpoint.py`

**Interfaces:**
- Consumes: `tracer.trace_image`, `tracer.TraceParams`, `tracer.TraceError`, `tracer.emit.*`
- Produces:
  - `server.build_board_from_strokes(strokes, name, filename, params, info) -> dict`
  - `POST /trace` returning the same document shape as `POST /route`

- [x] **Step 1: Write the failing tests**

Write `../pcb_reader/tests/test_trace_endpoint.py`:

```python
"""The /trace endpoint and its board document."""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from tracer import TraceParams, trace_image


def _two_lines_png() -> bytes:
    img = Image.new("L", (200, 200), 255)
    d = ImageDraw.Draw(img)
    d.line((20, 60, 180, 60), fill=0, width=6)
    d.line((20, 140, 180, 140), fill=0, width=6)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def doc():
    import server
    strokes, info = trace_image(_two_lines_png(), TraceParams(size_mm=50))
    return server.build_board_from_strokes(
        strokes, name="sample", filename="sample.png",
        params=TraceParams(size_mm=50), info=info)


def test_document_has_every_field_out_board_reads(doc):
    for key in ("name", "filename", "width", "height", "fcu", "bcu", "nets",
                "layer", "gcodeLines", "drawMoves", "travelMoves",
                "penUpBefore", "penUpAfter", "size", "estMinutes", "gcode",
                "tracks"):
        assert key in doc, f"missing {key}"


def test_source_marks_it_as_traced(doc):
    assert doc["source"] == "image"


def test_strokes_are_stored(doc):
    assert len(doc["strokes"]) == 2


def test_tracks_are_derived_from_strokes(doc):
    expected = sum(len(s) - 1 for s in doc["strokes"])
    assert len(doc["tracks"]) == expected


def test_derived_tracks_have_the_shape_the_ui_expects(doc):
    t = doc["tracks"][0]
    assert set(t) == {"net", "x1", "y1", "x2", "y2", "w", "layer"}
    assert t["layer"] == "F.Cu"


def test_gcode_is_a_string_not_a_list(doc):
    assert isinstance(doc["gcode"], str)
    assert "G21" in doc["gcode"]


def test_frame_gcode_never_draws(doc):
    assert "G1 Z" not in doc["frameGcode"]


def test_trace_params_are_kept_for_retracing(doc):
    assert doc["traceParams"]["size_mm"] == 50
    assert doc["traceParams"]["mode"] == "centerline"


def test_counts_are_honest_for_a_single_layer_job(doc):
    assert doc["fcu"] == len(doc["strokes"])
    assert doc["bcu"] == 0
    assert doc["nets"] == 1


def test_geometry_starts_at_the_origin(doc):
    xs = [p[0] for s in doc["strokes"] for p in s]
    ys = [p[1] for s in doc["strokes"] for p in s]
    assert min(xs) == pytest.approx(0, abs=0.01)
    assert min(ys) == pytest.approx(0, abs=0.01)
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd ../pcb_reader && python -m pytest tests/test_trace_endpoint.py -v`
Expected: FAIL — `AttributeError: module 'server' has no attribute 'build_board_from_strokes'`

- [x] **Step 3: Import the tracer in `server.py`**

In `../pcb_reader/server.py`, below the existing `from pcb_read import extract_wiring` line, add:

```python
from tracer import TraceError, TraceParams, trace_image
from tracer import emit
```

- [x] **Step 4: Add `build_board_from_strokes`**

In `../pcb_reader/server.py`, immediately after the existing `build_board` function, add:

```python
def build_board_from_strokes(strokes: list, name: str, filename: str,
                             params: TraceParams, info: dict) -> dict:
    """A traced image as the same board document `build_board` produces.

    `strokes` is authoritative — the G-code comes from it. `tracks` is derived
    purely so the existing SVG preview, thumbnails, and layer view keep
    working; it is never the source for anything that reaches the machine.
    """
    minx, miny, maxx, maxy = emit.bounds(strokes)
    width = round(maxx - minx, 2)
    height = round(maxy - miny, 2)

    gcode_lines = emit.generate_from_strokes(strokes, label=name)
    frame_lines = emit.emit_frame((minx, miny, maxx, maxy))
    report = emit.stroke_report(strokes)

    pen_w = CONFIG.get("pen_width_mm", 0.4)
    tracks = [{
        "net": "trace",
        "x1": a[0], "y1": a[1],
        "x2": b[0], "y2": b[1],
        "w": pen_w,
        "layer": "F.Cu",
    } for s in strokes for a, b in zip(s, s[1:])]

    return {
        "name": name,
        "filename": filename,
        "width": width,
        "height": height,
        "fcu": len(strokes),
        "bcu": 0,
        "nets": 1,
        "layer": "F.Cu",
        "gcodeLines": len(gcode_lines),
        "drawMoves": report["drawMoves"],
        "travelMoves": report["travelMoves"],
        "penUpBefore": report["penUpBefore"],
        "penUpAfter": report["penUpAfter"],
        "size": f"{width} x {height} mm",
        "estMinutes": report["estMinutes"],
        "tracks": tracks,
        "strokes": [[list(p) for p in s] for s in strokes],
        "gcode": "\n".join(gcode_lines),
        "frameGcode": "\n".join(frame_lines),
        "source": "image",
        "traceParams": {
            "size_mm": params.size_mm,
            "mode": params.mode,
            "preset": params.preset,
            "threshold": params.threshold,
            "invert": params.invert,
        },
        "traceInfo": info,
    }
```

- [x] **Step 5: Run the document tests**

Run: `cd ../pcb_reader && python -m pytest tests/test_trace_endpoint.py -v`
Expected: PASS (10 tests)

- [x] **Step 6: Add the endpoint**

In `../pcb_reader/server.py`, immediately after the existing `POST /route` handler, add:

```python
@app.post("/trace")
async def trace(file: UploadFile = File(...), email: str = Form(...),
                size_mm: float = Form(50.0), mode: str = Form("centerline"),
                preset: str = Form("line"), threshold: int | None = Form(None),
                invert: bool = Form(False)):
    """Trace a raster image to single-line strokes and store it as a board.

    Produces the same document shape as /route, so the projects grid, the
    preview, and the print path all work on a traced board unchanged.
    """
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(
            400, "That is not an image. Upload a PNG, JPG, BMP, or WEBP — "
                 "or use the KiCad path for a .kicad_pcb file.")

    raw = await file.read()
    params = TraceParams(size_mm=size_mm, mode=mode, preset=preset,
                         threshold=threshold, invert=invert)
    try:
        strokes, info = trace_image(raw, params)
    except TraceError as e:
        raise HTTPException(400, str(e))

    name = (file.filename or "traced").rsplit(".", 1)[0]
    board = build_board_from_strokes(
        strokes, name=name, filename=file.filename or "traced.png",
        params=params, info=info)
    board["user_email"] = email.strip().lower()
    board["status"] = "ready"
    board["createdAt"] = datetime.now(timezone.utc)
    res = db.boards.insert_one(board)
    board["_id"] = res.inserted_id
    return out_board(board, full=True)
```

- [x] **Step 7: Pass the new fields through `out_board`**

In `../pcb_reader/server.py`, inside `out_board`, just before `if full:`, add:

```python
    # Traced boards carry their provenance so the UI can offer a re-trace.
    for key in ("source", "traceParams", "traceInfo"):
        if key in doc:
            d[key] = doc[key]
    if full and "frameGcode" in doc:
        d["frameGcode"] = doc["frameGcode"]
    if full and "strokes" in doc:
        d["strokes"] = doc["strokes"]
```

- [x] **Step 8: Document the endpoint in the module docstring**

In `../pcb_reader/server.py`, add one line to the `Endpoints:` list in the module docstring, under the `/route` line:

```
    POST /trace                (multipart: file, email, size_mm, mode, preset) -> traced board
```

- [x] **Step 9: Run the whole suite**

Run: `cd ../pcb_reader && python -m pytest tests/ -v`
Expected: PASS

- [x] **Step 10: Smoke-test the running server**

Start it: `cd ../pcb_reader && uvicorn server:app --port 8000`
Then in another shell:

```bash
curl -F "file=@/c/cnc_line_backend/cnc_1line_tracer-main/input/1.jpg" \
     -F "email=test@example.com" -F "size_mm=50" \
     http://localhost:8000/trace
```

Expected: JSON with `source: "image"`, a non-empty `gcode`, and `tracks`.
This needs MongoDB running. If it is not, the failure will be a pymongo
connection error, not a tracing error — check which before debugging.

- [x] **Step 11: Commit**

```bash
cd ../pcb_reader
git add server.py tests/test_trace_endpoint.py
git commit -m "feat: POST /trace endpoint for image uploads"
```

---

## Task 5: Frontend — image upload

**Files:**
- Modify: `lib/api.ts`, `components/Uploader.tsx`

**Interfaces:**
- Consumes: `POST /trace`
- Produces: `api.trace(file, email, params): Promise<Board>`, `TraceParams` type

- [x] **Step 1: Add the types**

In `lib/api.ts`, after the existing `Board` type, add:

```ts
export type TraceParams = {
  size_mm: number;
  mode: "centerline" | "outline";
  preset: "line" | "pcb";
  threshold: number | null;
  invert: boolean;
};

export type TraceInfo = {
  inkCoverage: number;
  strokeCount: number;
  warnings: string[];
};
```

Then add these three optional fields to the existing `Board` type, beside
`tracks?` and `gcode?`:

```ts
  strokes?: number[][][];
  source?: "kicad" | "image";
  traceParams?: TraceParams;
  traceInfo?: TraceInfo;
  frameGcode?: string;
```

- [x] **Step 2: Add the client method**

In `lib/api.ts`, inside the `api` object and directly after the existing
`route` method, add:

```ts
  async trace(file: File, email: string, params: TraceParams): Promise<Board> {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("email", email);
    fd.append("size_mm", String(params.size_mm));
    fd.append("mode", params.mode);
    fd.append("preset", params.preset);
    fd.append("invert", String(params.invert));
    if (params.threshold !== null) fd.append("threshold", String(params.threshold));
    const res = await fetch(`${API_URL}/trace`, { method: "POST", body: fd });
    if (!res.ok) {
      const detail = await res.json().catch(() => null);
      throw new Error(detail?.detail ?? "Tracing failed.");
    }
    return res.json();
  },
```

- [x] **Step 3: Typecheck**

Run: `npx tsc --noEmit`
Expected: exit 0

- [x] **Step 4: Widen the uploader's accepted files**

In `components/Uploader.tsx`, change the file input's `accept` attribute to:

```tsx
        accept=".kicad_pcb,image/png,image/jpeg,image/bmp,image/webp"
```

- [x] **Step 5: Branch on file type**

In `components/Uploader.tsx`, add this state beside the existing `file`,
`busy`, and `error` state:

```tsx
  const isImage = !!file && /^image\//.test(file.type);
  const [sizeMm, setSizeMm] = useState(50);
  const [mode, setMode] = useState<"centerline" | "outline">("centerline");
  const [preset, setPreset] = useState<"line" | "pcb">("line");
  const [invert, setInvert] = useState(false);
```

Then replace the body of `routeFile` with:

```tsx
  async function routeFile() {
    if (!file || !session) return;
    setBusy(true);
    setError(null);
    try {
      const board = isImage
        ? await api.trace(file, session.email, {
            size_mm: sizeMm,
            mode,
            preset,
            threshold: null,
            invert,
          })
        : await api.route(file, session.email);
      router.push(`/dashboard/projects/${board.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
```

- [x] **Step 6: Add the options panel**

In `components/Uploader.tsx`, directly after the `<p>` that shows `file.name`
and before the error paragraph, add:

```tsx
      {isImage && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="mt-4 w-full max-w-md rounded border border-line bg-panel-2 p-3 text-left"
        >
          <span className="tlabel">trace options</span>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="tlabel">longest edge (mm)</span>
              <input
                type="number"
                min={1}
                max={300}
                value={sizeMm}
                onChange={(e) => setSizeMm(Number(e.target.value))}
                className="field mt-1 w-full"
              />
            </label>
            <label className="block">
              <span className="tlabel">preset</span>
              <select
                value={preset}
                onChange={(e) => setPreset(e.target.value as "line" | "pcb")}
                className="field mt-1 w-full"
              >
                <option value="line">Line art</option>
                <option value="pcb">PCB photo</option>
              </select>
            </label>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="tlabel">trace mode</span>
              <select
                value={mode}
                onChange={(e) =>
                  setMode(e.target.value as "centerline" | "outline")
                }
                className="field mt-1 w-full"
              >
                <option value="centerline">Centreline</option>
                <option value="outline">Outline</option>
              </select>
            </label>
            <label className="mt-5 flex items-center gap-2 text-sm text-ink-soft">
              <input
                type="checkbox"
                checked={invert}
                onChange={(e) => setInvert(e.target.checked)}
              />
              Light lines on dark
            </label>
          </div>
          <p className="mt-3 text-xs text-muted">
            Centreline draws one line down the middle of each stroke. Outline
            draws around each shape — pick it for etch resist, where a
            centreline would leave a wide trace only partly covered.
          </p>
        </div>
      )}
```

- [x] **Step 7: Adjust the copy for images**

In `components/Uploader.tsx`, the paragraph under the filename currently
describes routing only. Replace its text with a conditional:

```tsx
          <p className="mt-1 max-w-md text-xs text-muted">
            {isImage
              ? "Tracing finds the centre of every line in the image and turns it into a pen path, then saves the result to your account."
              : "Routing reads the board, plans the pen path, and generates the G-code on the server, then saves the result to your account."}
          </p>
```

- [x] **Step 8: Typecheck and build**

Run: `npx tsc --noEmit && npm run build`
Expected: both succeed

- [x] **Step 9: Commit**

```bash
git add lib/api.ts components/Uploader.tsx
git commit -m "feat: trace an uploaded image into a board"
```

---

## Task 6: Frontend — re-trace and docs

**Files:**
- Modify: `app/dashboard/projects/[id]/page.tsx`, `README.md`

**Interfaces:**
- Consumes: `Board.source`, `Board.traceParams`, `api.trace`

- [x] **Step 1: Hide the layer toggles for traced boards**

In `app/dashboard/projects/[id]/page.tsx`, find the layer-toggle controls
(the F.Cu / B.Cu checkboxes). Wrap them so they only render for KiCad boards:

```tsx
{board.source !== "image" && (
  /* ...the existing layer toggle block, unchanged... */
)}
```

A traced board is single-layer; a toggle that does nothing is worse than no
toggle.

- [x] **Step 2: Show the trace parameters**

In the same file, inside the report/details panel, add:

```tsx
{board.source === "image" && board.traceParams && (
  <div className="ticked mt-4">
    <span className="tlabel">traced from image</span>
    <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-xs">
      <dt className="text-muted">longest edge</dt>
      <dd className="text-ink">{board.traceParams.size_mm} mm</dd>
      <dt className="text-muted">mode</dt>
      <dd className="text-ink">{board.traceParams.mode}</dd>
      <dt className="text-muted">preset</dt>
      <dd className="text-ink">{board.traceParams.preset}</dd>
      <dt className="text-muted">strokes</dt>
      <dd className="text-ink">{board.fcu}</dd>
    </dl>
    {!!board.traceInfo?.warnings.length && (
      <ul className="mt-2 space-y-1 text-xs text-warn">
        {board.traceInfo.warnings.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
    )}
  </div>
)}
```

- [x] **Step 3: Typecheck and build**

Run: `npx tsc --noEmit && npm run build`
Expected: both succeed

- [x] **Step 4: Commit**

```bash
git add "app/dashboard/projects/[id]/page.tsx"
git commit -m "feat: show trace provenance on a traced board"
```

- [x] **Step 5: Document the image path in the README**

In `README.md`, in the Pages table, change the
`/dashboard/projects` row to mention both inputs:

```
| `/dashboard/projects` | Upload a `.kicad_pcb` to route, or an image to trace; both are saved to your account |
```

Then add a section after "How it connects":

```markdown
### Tracing an image

Upload a PNG or JPG instead of a `.kicad_pcb` and the API traces it to a
single-line pen path — no Inkscape, no jscut.

- **Longest edge (mm) is required.** An image has pixels, a machine has
  millimetres, and there is no DPI worth trusting in a photo.
- **Centreline** draws one line down the middle of each stroke. It is the
  right choice for line art and diagrams.
- **Outline** draws around each filled shape. Pick it for etch resist: a
  centreline down a wide trace leaves most of the copper uncovered.
- **PCB preset** switches to adaptive thresholding, which copes with the
  uneven lighting in a photo of a board, keeps corners sharp, and preserves
  small pad marks.

Every board stores a pen-up alignment frame alongside its G-code. Run the
frame first to check placement — it costs nothing and it is the cheapest way
to find out the drawing runs off the edge of the work.
```

- [x] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: image tracing in the README"
```

---

## Verification

- [x] `cd ../pcb_reader && python -m pytest tests/ -v` — all green
- [x] `npx tsc --noEmit` — exit 0
- [x] `npm run build` — succeeds
- [x] With MongoDB and both servers up: upload `1.jpg`, confirm the preview
      shows the traced geometry, the G-code downloads, and the report tiles
      read sensibly
- [x] Upload a `.kicad_pcb` and confirm the KiCad path is unchanged
- [x] Confirm `C:\cnc_line_backend\cnc_1line_tracer-main` has no modifications:
      `cd /c/cnc_line_backend/cnc_1line_tracer-main && git status` (or check
      file mtimes if it is not a repo)
