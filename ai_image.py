"""Size the page image that is sent to the LLM to the model's visual-token budget.

The worker forwards the base64 page image produced by /split-to-queue and /split to
Claude (and to the narrative model). Claude bills an image as
``ceil(width / 28) * ceil(height / 28)`` visual tokens and downscales any image above
the model's cap before processing: 1,568 tokens on the standard tier (e.g. Sonnet 4.6),
4,784 on the high-resolution tier (e.g. Sonnet 5.5). Rendering above the cap therefore
only adds bytes - which count against the organisation's prompt-bytes-per-hour limit and
bloat the ``pdf_pages`` row - or, on a high-resolution-tier model, extra billed tokens.

``render_ai_image`` renders the page once, directly at the largest aspect-preserving
size that fits the budget, so no oversized bitmap is ever allocated.

Environment:
  PDF_AI_IMAGE_MAX_TOKENS    visual-token budget per page image (default 1568; 0 disables
                             the cap and renders at the call site's native DPI)
  PDF_AI_IMAGE_JPEG_QUALITY  JPEG quality 30-95 (default 80)
"""
import math
import os

try:  # PyMuPDF >= 1.24 exposes the `pymupdf` name; `fitz` is the deprecated alias
    import pymupdf as _mupdf
except ImportError:  # pragma: no cover
    import fitz as _mupdf

PATCH_PX = 28
DEFAULT_MAX_TOKENS = 1568
DEFAULT_JPEG_QUALITY = 80


def max_tokens() -> int:
    try:
        return int(os.getenv("PDF_AI_IMAGE_MAX_TOKENS", DEFAULT_MAX_TOKENS))
    except ValueError:
        return DEFAULT_MAX_TOKENS


def jpeg_quality() -> int:
    try:
        q = int(os.getenv("PDF_AI_IMAGE_JPEG_QUALITY", DEFAULT_JPEG_QUALITY))
    except ValueError:
        q = DEFAULT_JPEG_QUALITY
    return max(30, min(95, q))


def visual_tokens(width_px: float, height_px: float) -> int:
    """Claude's visual-token count for an image of the given pixel size."""
    return math.ceil(width_px / PATCH_PX) * math.ceil(height_px / PATCH_PX)


def fit_dimensions(width_px: float, height_px: float, budget: int) -> tuple[int, int]:
    """Largest aspect-preserving size, never larger than the input, within `budget` tokens."""
    w, h = max(int(width_px), 1), max(int(height_px), 1)
    if budget <= 0 or visual_tokens(w, h) <= budget:
        return w, h
    scale = math.sqrt(budget * PATCH_PX * PATCH_PX / (w * h))
    tw, th = max(int(w * scale), 1), max(int(h * scale), 1)
    while visual_tokens(tw, th) > budget and (tw > 1 or th > 1):
        # ceil() padding can push the estimate over; step down one percent at a time
        tw, th = max(int(tw * 0.99), 1), max(int(th * 0.99), 1)
    return tw, th


def render_ai_image(page, dpi: int, *, budget: int | None = None, quality: int | None = None) -> bytes:
    """Render `page` as JPEG bytes for the LLM: at `dpi`, but no larger than the token budget."""
    if budget is None:
        budget = max_tokens()
    if quality is None:
        quality = jpeg_quality()
    w_pt, h_pt = max(float(page.rect.width), 1.0), max(float(page.rect.height), 1.0)
    native_w, native_h = w_pt / 72.0 * dpi, h_pt / 72.0 * dpi
    tw, th = fit_dimensions(native_w, native_h, budget)
    matrix = _mupdf.Matrix(tw / w_pt, th / h_pt)
    pix = page.get_pixmap(matrix=matrix)
    try:
        return pix.tobytes("jpeg", quality)
    finally:
        pix = None
