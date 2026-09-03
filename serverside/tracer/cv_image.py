#!/usr/bin/env python
"""OpenCV-based image processing for CNC plotter and PCB plotting.

Provides three processing pipelines, all returning a bool ndarray (True = ink)
that plugs directly into centerline.trace():

  stencil()   Adaptive thresholding + morphological cleanup.
              Best for: JPEG photos, scanned artwork, uneven lighting.

  edges()     Canny edge detection + skeletonise to single-pixel width.
              Best for: tracing the outlines of filled shapes.
              GUARANTEES a single-line result — no doubled lines.

  pcb()       Tight adaptive threshold + gap-closing morphology.
              Best for: PCB copper trace photos, resist artwork,
              high-contrast bi-level images.

All pipelines include connected-component filtering to remove tiny specks
before the result is returned.

Requires: opencv-python  (pip install opencv-python)
"""
from __future__ import annotations

import numpy as np

try:
    import cv2
except ImportError as exc:
    raise ImportError(
        "\nopencv-python is required for the --engine cv / --edge-detect / --pcb pipelines.\n"
        "  pip install opencv-python\n"
    ) from exc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_gray(path: str, max_px: int = 0) -> np.ndarray:
    """Load an image as uint8 grayscale, optionally downscaling the long edge."""
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(
            f"OpenCV could not open {path!r}.\n"
            "Make sure the file exists and is a supported image format."
        )
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if max_px and max(gray.shape) > max_px:
        h, w = gray.shape
        if h >= w:
            new_w = max(1, int(w * max_px / h))
            gray = cv2.resize(gray, (new_w, max_px), interpolation=cv2.INTER_AREA)
        else:
            new_h = max(1, int(h * max_px / w))
            gray = cv2.resize(gray, (max_px, new_h), interpolation=cv2.INTER_AREA)
    return gray


def _odd(n: int, minimum: int = 3) -> int:
    """Return n rounded up to the nearest odd number >= minimum."""
    n = max(minimum, n)
    return n if n % 2 == 1 else n + 1


def _remove_small(mask: np.ndarray, min_area: int) -> np.ndarray:
    """Remove connected ink components smaller than min_area pixels.

    `mask` is uint8 (255 = ink).  Returns uint8.
    """
    if min_area <= 0:
        return mask
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )
    out = np.zeros_like(mask, dtype=np.uint8)
    for i in range(1, num_labels):           # 0 is background
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            out[labels == i] = 255
    return out


def _thin_to_skeleton(ink_uint8: np.ndarray) -> np.ndarray:
    """Reduce binary ink to single-pixel-wide centrelines.

    Tries OpenCV ximgproc thinning (contrib, fastest) then falls back
    to skimage skeletonize.  Both guarantee a single-pixel-wide result.
    Returns uint8 (255 = ink).
    """
    try:
        from cv2 import ximgproc          # opencv-contrib-python
        return ximgproc.thinning(
            ink_uint8,
            thinningType=ximgproc.THINNING_ZHANGSUEN,
        )
    except (ImportError, AttributeError):
        from skimage.morphology import skeletonize
        sk = skeletonize((ink_uint8 > 0).astype(bool))
        return sk.astype(np.uint8) * 255


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def stencil(
    path: str,
    min_area: int = 100,
    blur_size: int = 5,
    block_size: int = 21,
    C: int = 3,
    kernel_size: int = 2,
    max_px: int = 0,
) -> np.ndarray:
    """Convert an image to a clean stencil-style binary mask (True = ink).

    This is the OpenCV equivalent of prep_image.prepare().  It handles
    uneven lighting and JPEG gradients far better than a global threshold.

    Processing order
    ----------------
    1. Load + grayscale
    2. Gaussian blur           (softens noise before thresholding)
    3. Adaptive thresholding   (local contrast → robust to uneven light)
    4. Morphological opening   (removes very fine speckle)
    5. Connected-component filter (drops isolated blobs by pixel area)

    Parameters
    ----------
    path        : path to input image
    min_area    : minimum component area in pixels to keep (removes stray dots)
    blur_size   : Gaussian kernel side length (must be odd; try 3, 5, 7)
    block_size  : adaptive threshold neighbourhood size (must be odd; try 11–31)
    C           : constant subtracted from local mean; higher → more ink picked up
    kernel_size : morphological opening kernel size (1–3 is usually enough)
    max_px      : downscale the long edge to at most this many pixels (0 = off)

    Returns
    -------
    bool ndarray, True where there is ink, with shape (H, W).
    """
    gray = _load_gray(path, max_px)

    blurred = cv2.GaussianBlur(gray, (_odd(blur_size), _odd(blur_size)), 0)

    thresh = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        _odd(block_size),
        C,
    )

    if kernel_size >= 1:
        k = np.ones((max(1, kernel_size), max(1, kernel_size)), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, k)

    ink = _remove_small(thresh, min_area)
    return ink.astype(bool)


def edges(
    path: str,
    low_thresh: int = 50,
    high_thresh: int = 150,
    blur_size: int = 3,
    dilate: int = 1,
    min_area: int = 0,
    thin: bool = True,
    max_px: int = 0,
) -> np.ndarray:
    """Detect edges via Canny then thin to guaranteed single-pixel lines.

    Canny produces ~2 px wide edge responses.  Thinning (skeletonise) reduces
    them to a true single-pixel-wide skeleton: the GCode will have no doubled
    lines.

    Processing order
    ----------------
    1. Load + grayscale
    2. Optional Gaussian blur   (reduces false edge responses from noise)
    3. Canny edge detection
    4. Optional dilation         (closes tiny gaps between edge segments)
    5. Optional component filter
    6. Zhang-Suen thinning       (single-pixel-wide skeleton)

    Parameters
    ----------
    path         : path to input image
    low_thresh   : Canny lower hysteresis threshold (0–255)
    high_thresh  : Canny upper hysteresis threshold (0–255)
    blur_size    : Gaussian blur before Canny (must be odd; 0 disables)
    dilate       : dilation radius to close edge gaps (0 disables)
    min_area     : remove edge fragments smaller than this many pixels
    thin         : skeletonise edges to single-pixel width (default True)
    max_px       : downscale long edge to at most this many pixels (0 = off)

    Returns
    -------
    bool ndarray, True where there is an edge, with shape (H, W).
    """
    gray = _load_gray(path, max_px)

    if blur_size >= 3:
        gray = cv2.GaussianBlur(gray, (_odd(blur_size), _odd(blur_size)), 0)

    canny = cv2.Canny(gray, low_thresh, high_thresh)

    if dilate >= 1:
        k = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * dilate + 1, 2 * dilate + 1)
        )
        canny = cv2.dilate(canny, k, iterations=1)

    if min_area > 0:
        canny = _remove_small(canny, min_area)

    if thin:
        canny = _thin_to_skeleton(canny)

    return (canny > 0).astype(bool)


def pcb(
    path: str,
    blur_size: int = 3,
    block_size: int = 15,
    C: int = 2,
    min_area: int = 50,
    close_gaps: int = 2,
    sharpen: bool = True,
    max_px: int = 0,
) -> np.ndarray:
    """Specialised pipeline optimised for PCB trace photos and artwork.

    Tuned for high-contrast PCB images (copper traces on FR4, or resist
    artwork).  Sharpening before thresholding recovers trace edge definition
    lost by camera focus; gap-closing morphology reconnects broken trace
    segments caused by lighting reflections.

    Processing order
    ----------------
    1. Load + grayscale
    2. Optional unsharp-mask sharpening (recovers camera-blurred trace edges)
    3. Gaussian blur                    (removes sensor/JPEG noise)
    4. Adaptive thresholding
    5. Morphological close              (reconnects broken trace segments)
    6. Morphological open               (removes single-pixel speckle)
    7. Connected-component filter

    Parameters
    ----------
    path        : path to PCB image
    blur_size   : Gaussian smoothing kernel (must be odd)
    block_size  : adaptive threshold neighbourhood (must be odd; 9–21)
    C           : threshold bias; lower picks up more trace area
    min_area    : minimum trace fragment in pixels
    close_gaps  : morphological close radius (px) to reconnect trace breaks
    sharpen     : apply unsharp mask before blur to boost edge contrast
    max_px      : downscale long edge to at most this many pixels (0 = off)

    Returns
    -------
    bool ndarray, True where there is a PCB trace/pad, with shape (H, W).
    """
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

    ink = _remove_small(thresh, min_area)
    return ink.astype(bool)


# ---------------------------------------------------------------------------
# Utility: save intermediate steps as a debug image grid
# ---------------------------------------------------------------------------

def save_debug_grid(path: str, steps: list[tuple[str, np.ndarray]], out: str) -> None:
    """Write a side-by-side grid of intermediate processing steps to `out`.

    Each entry in `steps` is (label, uint8_or_bool_array).
    Useful for tuning parameters: pass --save-steps to plot.py.
    """
    import math
    from PIL import Image as _PIL, ImageDraw as _Draw, ImageFont as _Font

    imgs = []
    for label, arr in steps:
        if arr.dtype == bool:
            arr = (~arr).astype(np.uint8) * 255   # True=ink → black on white
        if arr.max() <= 1:
            arr = arr.astype(np.uint8) * 255
        if arr.ndim == 2:
            rgb = cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)
        else:
            rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
        pil = _PIL.fromarray(rgb)
        draw = _Draw.Draw(pil)
        draw.rectangle([0, 0, pil.width, 18], fill=(30, 30, 30))
        draw.text((4, 2), label, fill=(220, 220, 60))
        imgs.append(pil)

    if not imgs:
        return
    cols = min(len(imgs), 4)
    rows = math.ceil(len(imgs) / cols)
    W, H = imgs[0].size
    grid = _PIL.new("RGB", (W * cols, H * rows), (200, 200, 200))
    for idx, img in enumerate(imgs):
        r, c = divmod(idx, cols)
        grid.paste(img, (c * W, r * H))
    grid.save(out)
