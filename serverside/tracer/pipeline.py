"""Image bytes to strokes in millimetres.

This is the one place where scale is decided. An image has pixels; a machine
has millimetres, and there is no DPI worth trusting in a photograph, so the
caller states the size it wants and everything else follows from that.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, UnidentifiedImageError

from tracer import centerline as cl
from tracer import prep

Point = tuple[float, float]
Stroke = list[Point]


class TraceError(ValueError):
    """Something the user can act on: bad file, blank result, wrong polarity."""


MODES = ("centerline", "outline", "fill")


@dataclass
class TraceParams:
    size_mm: float = 50.0            # longest edge; 0 means fit the bed
    mode: str = "centerline"         # or "outline", or "fill"
    preset: str = "line"             # or "pcb"
    threshold: int | None = None     # None means Otsu + faint-line soften
    invert: bool = False
    bed: tuple[float, float] = (300.0, 200.0)
    margin: float = 10.0
    # fill mode only — the gap between hatch line centres, in mm. To actually
    # cover copper it must be no wider than the pen.
    hatch_spacing_mm: float = 0.4
    hatch_angle: float = 45.0
    hatch_cross: bool = False


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


def _binary(img: Image.Image, params: TraceParams,
            cfg: dict) -> tuple[np.ndarray, float]:
    """Clean the image to a boolean ink mask (True = ink), plus ink coverage.

    Coverage is measured before cropping. It exists to answer "is this artwork
    the wrong way round?", which is a property of what the user handed over —
    after cropping to the ink bounding box, every image looks dense.
    """
    if cfg["adaptive"]:
        from tracer import cv_image
        gray = np.array(img.convert("L"))
        ink = cv_image.pcb_from_gray(
            gray, block_size=cfg["block_size"], C=cfg["adaptive_c"],
            min_area=cfg["min_area"])
        if params.invert:
            ink = ~ink
        return ink, float(ink.mean()) if ink.size else 0.0

    gray = np.array(img.convert("L"))
    cut = prep.choose_threshold(gray, params.threshold)
    dark = gray <= cut
    coverage = float((~dark if params.invert else dark).mean()) if dark.size else 0.0

    cleaned = prep.prepare_array(
        img, threshold=params.threshold, invert=params.invert,
        speck=cfg["despeckle"], max_px=2000, crop=True, bridge=cfg["bridge"])
    # prepare_array returns mode "1", where True is paper; ink is its inverse
    return ~np.array(cleaned).astype(bool), coverage


def _size_factor(strokes: list[Stroke], params: TraceParams) -> float:
    """How much the traced drawing must grow to reach the requested size."""
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    longest = max(width, height)
    if longest <= 0:
        return 1.0
    if params.size_mm and params.size_mm > 0:
        return params.size_mm / longest
    bed_x, bed_y = params.bed
    usable_x = max(bed_x - 2 * params.margin, 1.0)
    usable_y = max(bed_y - 2 * params.margin, 1.0)
    return min(usable_x / width if width else float("inf"),
               usable_y / height if height else float("inf"))


def _fit(strokes: list[Stroke], params: TraceParams) -> tuple[list[Stroke], float]:
    """Scale the traced drawing to the size the caller asked for.

    Tracing works in bitmap pixels, and the bitmap is not the drawing: the
    cleaner crops to the ink with a small pad, and thinning tapers stroke ends
    inward by about half the stroke width. Deriving the scale from the bitmap
    would make `size_mm` mean "the cropped bitmap's longest edge", which is a
    few percent larger than what actually gets drawn. Scaling the finished
    strokes instead makes 50 mm mean 50 mm of ink.
    """
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    longest = max(width, height)
    if longest <= 0:
        return strokes, 1.0

    if params.size_mm and params.size_mm > 0:
        factor = params.size_mm / longest
    else:
        bed_x, bed_y = params.bed
        usable_x = max(bed_x - 2 * params.margin, 1.0)
        usable_y = max(bed_y - 2 * params.margin, 1.0)
        factor = min(usable_x / width if width else float("inf"),
                     usable_y / height if height else float("inf"))

    scaled = [[(x * factor, y * factor) for x, y in s] for s in strokes]
    return scaled, factor


def _mm_per_px(shape: tuple[int, int], params: TraceParams) -> float:
    """A first-pass scale, used only so the minimum-stroke filter runs in
    roughly the right units. `_fit` sets the final size exactly."""
    h, w = shape
    if params.size_mm and params.size_mm > 0:
        return params.size_mm / max(h, w)
    bed_x, bed_y = params.bed
    usable_x = max(bed_x - 2 * params.margin, 1.0)
    usable_y = max(bed_y - 2 * params.margin, 1.0)
    return min(usable_x / w, usable_y / h)


def trace_image(data: bytes, params: TraceParams) -> tuple[list[Stroke], dict]:
    """Trace image bytes to strokes in mm, plus an info dict."""
    if params.mode not in MODES:
        raise TraceError(f"Unknown trace mode {params.mode!r}.")
    cfg = PRESETS.get(params.preset)
    if cfg is None:
        raise TraceError(f"Unknown preset {params.preset!r}.")

    img = _load(data)
    ink, coverage = _binary(img, params, cfg)

    if not ink.any():
        raise TraceError(
            "Nothing to trace: the cleaned image is blank. If your artwork is "
            "light-on-dark, set invert; otherwise try a different threshold.")

    mm_per_px = _mm_per_px(ink.shape, params)
    # Fill draws the silhouette first, then floods it; the edge is what makes
    # a filled shape look deliberate rather than shaggy.
    edge_mode = "outline" if params.mode == "fill" else params.mode
    strokes = cl.trace(
        ink, mm_per_px,
        simplify_tol=cfg["simplify_tol"],
        min_stroke_mm=cfg["min_stroke_mm"],
        smooth_passes=cfg["smooth_passes"],
        spline_tol=cfg["spline_tol"],
        mode=edge_mode,
    )

    if not strokes:
        raise TraceError(
            "Nothing survived tracing: every stroke came out shorter than the "
            "minimum. Try a larger size, or a different threshold.")

    strokes, factor = _fit(strokes, params)

    if params.mode == "fill":
        # Hatch in the *final* scale. Generating it before the fit and scaling
        # it afterwards would multiply the spacing by the same factor, so a
        # request for 0.4 mm lines would silently come out at some other gap
        # and leave copper bare.
        from tracer import hatch as hatch_mod
        try:
            fill = hatch_mod.hatch(
                ink, mm_per_px * factor,
                spacing_mm=params.hatch_spacing_mm,
                angle_deg=params.hatch_angle,
                cross=params.hatch_cross)
        except ValueError as e:
            raise TraceError(str(e)) from e
        if not fill:
            raise TraceError(
                "The fill came out empty. The shapes are probably thinner than "
                "the hatch spacing - tighten the spacing, or trace larger.")
        strokes = strokes + fill

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
            "white - try a lower threshold, or invert.")
    if coverage < 0.005:
        warnings.append("The image is nearly blank; very little was traced.")

    return strokes, {
        "inkCoverage": round(coverage, 4),
        "strokeCount": len(strokes),
        "warnings": warnings,
    }
