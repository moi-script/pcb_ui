"""Tests for the bitmap cleaner in tracer/prep.py."""
import numpy as np
import pytest
from PIL import Image, ImageDraw
from skimage.measure import label

from tracer import prep


def test_explicit_threshold_always_wins():
    gray = np.full((20, 20), 255, np.uint8)
    assert prep.choose_threshold(gray, 140) == 140


def _scan_with_faint_linework() -> np.ndarray:
    """A scan holding solid ink, paper, and a faint stroke between them.

    The greys are spread rather than flat. A histogram of two or three exact
    values leaves Otsu's between-class variance flat across the whole gap, so
    its argmax lands on the low end of that plateau and any band added
    afterwards is swallowed below the cut - which is not the case under test.
    """
    rng = np.random.default_rng(7)
    gray = np.clip(rng.normal(245, 6, (200, 200)), 0, 255).astype(np.uint8)
    gray[10:70, 10:190] = np.clip(
        rng.normal(45, 8, (60, 180)), 0, 255).astype(np.uint8)     # solid ink
    gray[110:118, 10:190] = np.clip(
        rng.normal(150, 4, (8, 180)), 0, 255).astype(np.uint8)     # faint stroke
    return gray


def test_auto_threshold_pulls_faint_linework_above_the_cut():
    """A faint stroke just above Otsu's cut is real ink. The auto cut should be
    softened to include it, instead of letting the trace lose the whole line."""
    gray = _scan_with_faint_linework()
    base = prep.otsu(gray)
    cut = prep.choose_threshold(gray, None)

    # the soften path is what is under test, so prove it actually ran
    assert cut == min(base + 30, 255)
    assert cut > base

    # and prove it bought something: the faint stroke is ink at the softened
    # cut, but almost all of it would have been lost at the raw Otsu cut.
    # "Almost" because the stroke has grain, so its darkest pixels fall below
    # the cut on their own - a handful of scattered pixels, not a line.
    faint = gray[110:118, 10:190]
    assert (faint <= cut).all(), "softened cut still misses the faint stroke"
    kept_by_otsu = float((faint <= base).mean())
    assert kept_by_otsu < 0.05, (
        f"fixture is wrong - Otsu already keeps {kept_by_otsu:.0%} of the stroke")


def test_bridge_does_nothing_at_radius_zero():
    ink = np.zeros((10, 10), dtype=bool)
    ink[5, 2:8] = True
    assert (prep.bridge_ink(ink, 0) == ink).all()


def test_bridge_fills_a_one_pixel_gap():
    ink = np.zeros((10, 10), dtype=bool)
    ink[5, 2:5] = True
    ink[5, 6:9] = True               # the pixel at column 5 is missing
    joined = prep.bridge_ink(ink, 1)
    assert joined[5, 5]


def test_bridging_merges_a_broken_line_into_one_stroke(tmp_path):
    img = Image.new("L", (80, 40), 255)
    d = ImageDraw.Draw(img)
    d.line((5, 20, 34, 20), fill=0, width=3)
    d.line((36, 20, 75, 20), fill=0, width=3)   # 1px gap at x=35

    def components(radius):
        out = prep.prepare(str(img_path), None, False, 1, 200, False, radius)
        ink = ~np.array(out).astype(bool)       # True = ink
        return label(ink).max()

    img_path = tmp_path / "broken.png"
    img.save(img_path)
    assert components(0) == 2
    assert components(1) == 1