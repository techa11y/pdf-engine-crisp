"""Pixel budget for page rasterization.

The engines rasterize original pages (visual pages in /build, AI page images in
/split*) at a fixed DPI. For ordinary page sizes that is a few megapixels, but a
large-format page (e.g. a 33x55 in poster) at 250 DPI is 113 MP: the pixmap plus
PyMuPDF's JPEG encode peak at ~1 GB, which on top of the resident form-detection
model exceeds the 2 GiB container and the process is OOM-killed (observed on
pdf-engine-crisp, 2026-11-02). `capped_dpi` keeps the requested DPI whenever the
bitmap fits the budget and lowers it only for oversized pages.
"""
import math
import os

DEFAULT_MAX_PIXELS = 30_000_000  # ~30 MP: a 33x55 in page renders at ~128 DPI, Letter/Tabloid are untouched
MIN_DPI = 36


def max_pixels() -> int:
    """Budget from PDF_VISUAL_MAX_PIXELS (0 or negative disables the cap)."""
    try:
        return int(os.getenv("PDF_VISUAL_MAX_PIXELS", DEFAULT_MAX_PIXELS))
    except ValueError:
        return DEFAULT_MAX_PIXELS


def capped_dpi(width_pt: float, height_pt: float, dpi: int, max_px: int | None = None) -> int:
    """DPI to rasterize a width_pt x height_pt page so the bitmap stays within max_px pixels.

    Returns `dpi` unchanged when the page already fits; otherwise the largest DPI
    (never below MIN_DPI) whose bitmap fits the budget.
    """
    if max_px is None:
        max_px = max_pixels()
    if max_px <= 0:
        return dpi
    w_in = max(float(width_pt), 1.0) / 72.0
    h_in = max(float(height_pt), 1.0) / 72.0
    if w_in * h_in * dpi * dpi <= max_px:
        return dpi
    return max(MIN_DPI, int(math.sqrt(max_px / (w_in * h_in))))
