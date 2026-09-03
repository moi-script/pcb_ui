#!/usr/bin/env python
"""Clean a bitmap so Inkscape's centerline tracer can find single lines.

Centerline tracing looks for the middle of a dark stroke. Anti-aliased
edges, JPEG mush and grey shading all confuse it into producing doubled or
broken paths, so the image gets flattened to hard black-on-white first.

    python tools/prep_image.py input/drawing.jpg
    python tools/prep_image.py input/photo.png --threshold 140 --invert
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps
from skimage.measure import label as sk_label, regionprops


def otsu(gray: np.ndarray) -> int:
    """Pick the threshold that best separates ink from paper."""
    hist = np.bincount(gray.ravel(), minlength=256).astype(float)
    total = hist.sum()
    weight_bg = np.cumsum(hist)
    weight_fg = total - weight_bg
    mean = np.cumsum(hist * np.arange(256))
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_bg = mean / weight_bg
        mean_fg = (mean[-1] - mean) / weight_fg
        variance = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
    variance[~np.isfinite(variance)] = 0
    return int(np.argmax(variance))


def choose_threshold(gray: np.ndarray, threshold: int | None) -> int:
    """The ink cutoff, with faint linework pulled up out of the noise.

    Otsu splits the histogram, but a scan of a pencil sketch often has a
    run of faint grey just above its cut - real lines, nearly at the paper's
    brightness. Left alone, those lines vanish from the trace entirely.
    If a softer cut would pick up a significant but not flooding amount of
    extra ink, use it; an explicit --threshold always wins.
    """
    if threshold is not None:
        return threshold
    cut = otsu(gray)
    softer = min(cut + 30, 255)
    here = int((gray <= cut).sum())
    added = int((gray <= softer).sum()) - here
    if here and 0 < added <= here * 0.5:
        return softer
    return cut


def bridge_ink(ink: np.ndarray, radius: int) -> np.ndarray:
    """Grow the ink by `radius` pixels so faint gaps reconnect.

    Scanning drops a line where it thins out; the skeleton then stops at
    each piece and draws a broken dash instead of a continuous stroke.
    Growing the ink with a diamond footprint joins pieces that are up to
    `radius` pixels apart, and the thinning step afterwards finds one line
    through both. Zero disables it.
    """
    if radius <= 0:
        return ink
    offsets = [(dr, dc) for dr in range(-radius, radius + 1)
               for dc in range(-radius, radius + 1)
               if abs(dr) + abs(dc) <= radius]
    out = ink.copy()
    h, w = ink.shape
    for dr, dc in offsets:
        if dr == 0 and dc == 0:
            continue
        out[max(0, -dr):min(h, h - dr), max(0, -dc):min(w, w - dc)] |= \
            ink[max(0, dr):min(h, h + dr), max(0, dc):min(w, w + dc)]
    return out


def despeckle(binary: Image.Image, size: int) -> Image.Image:
    """Drop isolated dots that would each become their own stray stroke.

    Uses a majority (mode) filter: every pixel becomes the most common value
    in a square window of the given side length.  A single dark pixel in a
    sea of white flips to white.  Use --despeckle 1 to disable.
    """
    if size <= 1:
        return binary
    return binary.filter(ImageFilter.ModeFilter(size))


def reduce_colors(img: Image.Image, n_colors: int) -> Image.Image:
    """Quantise an RGB image to at most n_colors distinct colours.

    JPEG images contain millions of nearly-identical shades that straddle the
    threshold boundary and produce broken, noisy ink masks.  Merging those
    shades into flat zones gives a cleaner binary image downstream.

    PIL's Median-Cut quantisation (no dithering) is used: it preserves edge
    sharpness while flattening gradients.  The result is returned as an RGB
    image so the normal grayscale conversion and thresholding still apply.
    """
    if n_colors <= 0:
        return img
    rgb = img.convert("RGB")
    quantized = rgb.quantize(colors=n_colors, method=Image.Quantize.MEDIANCUT, dither=0)
    return quantized.convert("RGB")


def remove_small_blobs(ink: np.ndarray, min_px: int) -> np.ndarray:
    """Delete every connected ink region whose pixel area is below min_px.

    Unlike the window-based ModeFilter, this operates on whole connected
    components: a scanned dot or speck is removed entirely, no matter its
    shape, as long as it is isolated and smaller than min_px pixels.

    `ink` is a boolean array (True = ink).  Returns a boolean array of the
    same shape with small components zeroed out.
    """
    if min_px <= 0 or not ink.any():
        return ink
    labeled = sk_label(ink)
    out = np.zeros_like(ink, dtype=bool)
    for prop in regionprops(labeled):
        if prop.area >= min_px:
            out[labeled == prop.label] = True
    return out


def prepare_array(img: Image.Image, threshold: int | None = None,
                  invert: bool = False, speck: int = 3,
                  max_px: int = 2000, crop: bool = True, bridge: int = 1,
                  n_colors: int = 0, min_blob: int = 0) -> Image.Image:
    """Clean and binarise an already-loaded image, ready for tracing.

    Processing order:
      1. Convert to RGB (preserves colour for quantisation).
      2. Optional colour reduction.
      3. Convert to grayscale and threshold.
      4. Optional invert.
      5. ModeFilter despeckling.
      6. Crop to ink bounding box.
      7. Optional blob despeckling.
      8. Optional ink bridging — LAST, and deliberately so: growing the ink
         before skeletonisation is what makes a gappy scanned line come
         through as one stroke instead of a dashed one.
    """
    img = img.convert("RGB")
    if max_px and max(img.size) > max_px:
        img.thumbnail((max_px, max_px), Image.LANCZOS)
    # Step 2: colour reduction
    if n_colors > 0:
        img = reduce_colors(img, n_colors)
    # Step 3: grayscale + threshold
    gray = np.array(img.convert("L"))
    cut = choose_threshold(gray, threshold)
    binary = Image.fromarray(np.where(gray > cut, 255, 0).astype(np.uint8))
    if invert:
        binary = ImageOps.invert(binary)
    binary = despeckle(binary, speck)
    if crop:
        box = ImageOps.invert(binary).getbbox()   # ink is dark; bbox wants bright
        if box:
            pad = 4
            binary = binary.crop((max(box[0] - pad, 0), max(box[1] - pad, 0),
                                  min(box[2] + pad, binary.width),
                                  min(box[3] + pad, binary.height)))
    out = binary.convert("1")                     # True = white/paper
    # Step 7: blob despeckling
    if min_blob > 0:
        ink = ~np.array(out).astype(bool)         # True = ink
        ink = remove_small_blobs(ink, min_blob)
        out = Image.fromarray((~ink).astype(np.uint8) * 255).convert("1")
    # Step 8: ink bridging
    if bridge:
        ink = ~np.array(out).astype(bool)         # True = ink
        ink = bridge_ink(ink, bridge)
        out = Image.fromarray((~ink).astype(np.uint8) * 255).convert("1")
    return out


def prepare(path: str, threshold: int | None = None, invert: bool = False,
            speck: int = 3, max_px: int = 2000, crop: bool = True,
            bridge: int = 1, n_colors: int = 0, min_blob: int = 0) -> Image.Image:
    """Path-taking wrapper around `prepare_array`."""
    return prepare_array(Image.open(path), threshold, invert, speck, max_px,
                         crop, bridge, n_colors, min_blob)
