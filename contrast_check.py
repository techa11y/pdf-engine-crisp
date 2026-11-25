"""Text contrast on picture pages (checklist 1.3: enough colour contrast between text and background).

Picture pages keep the original's colours, so pale or low-contrast text stays as the publisher made it. This
check measures that text and reports it. It never changes a colour.

How it works:
- Text comes from PyMuPDF's text trace for the original page: each span's colour, size, bold flag, render mode
  and opacity. Invisible text (render mode 3, such as an OCR layer over a scan) and blank spans are skipped.
- The background under each span is read from a low-resolution render of a one-page copy with its text removed
  (a redaction that keeps images and drawings). So the glyphs and their anti-aliasing never mix into the
  background colour. Text over a photo or gradient is measured against the middle colour behind it.
- Ratios use the WCAG 2 relative-luminance formula. The TypeScript twin of this maths is
  server/services/contrast-math.ts in the TechA11y platform.
- Large text (at least 18 pt, or 14 pt bold) needs 3:1. Other text needs 4.5:1 (WCAG 1.4.3).

Not checked: pages with no visible text layer (scans, or OCR text drawn invisibly), and pages after the time
budget runs out. The check only reads, and it never raises.

KEEP IN STEP: this file is identical in pdf-engine-crisp and pdf-enginev2.
"""
import os
import time

import fitz  # PyMuPDF

NORMAL_MIN = 4.5
LARGE_MIN = 3.0
CHECK_DPI = 72
CONTRAST_BUDGET_S = 20.0  # for the whole build; later pages are reported as not checked
MAX_SAMPLES = 400  # background pixels read per span
REPORT_PAGE_CAP = 50  # pages listed in the report; the rest are counted


def enabled() -> bool:
    """PDF_CONTRAST_CHECK=0 turns the check off (default on)."""
    return os.getenv("PDF_CONTRAST_CHECK", "1") != "0"


def _channel(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb) -> float:
    """WCAG 2 relative luminance of an sRGB colour with 0..1 channels."""
    r, g, b = (_channel(min(max(float(v), 0.0), 1.0)) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b) -> float:
    """WCAG contrast ratio of two sRGB colours (1 to 21)."""
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def is_large(size: float, bold: bool) -> bool:
    return size >= 18 or (bold and size >= 14)


def _to_rgb(color, components: int):
    """A text-trace colour as sRGB 0..1."""
    c = [float(v) for v in (color or ())]
    if components == 1 and c:
        return (c[0], c[0], c[0])
    if components == 4 and len(c) == 4:
        cy, m, y, k = c
        return ((1 - cy) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    if len(c) >= 3:
        return tuple(c[:3])
    return (0.0, 0.0, 0.0)


def _visible_spans(page: "fitz.Page") -> list:
    """(bbox, rgb, opacity, size, bold) for each visible, non-blank text span on the page."""
    spans, area = [], page.rect
    for t in page.get_texttrace():
        if t.get("type") == 3 or float(t.get("opacity", 1.0) or 0.0) <= 0.05:
            continue
        if not any(not chr(ch[0]).isspace() for ch in t.get("chars", ()) if ch and ch[0] is not None and ch[0] >= 0):
            continue
        r = fitz.Rect(t["bbox"]) & area
        if r.is_empty or r.width < 1 or r.height < 2:
            continue
        bold = bool(int(t.get("flags", 0)) & 16) or "bold" in str(t.get("font", "")).lower()
        spans.append((r, _to_rgb(t.get("color"), int(t.get("colorspace", 3) or 3)),
                      float(t.get("opacity", 1.0) or 1.0), float(t.get("size", 0) or 0), bold))
    return spans


def _background(pix: "fitz.Pixmap", rect: "fitz.Rect", scale: float):
    """Median colour of the text-less render inside `rect`, as sRGB 0..1."""
    x0, y0 = max(int(rect.x0 * scale), 0), max(int(rect.y0 * scale), 0)
    x1, y1 = min(int(rect.x1 * scale + 0.999), pix.width), min(int(rect.y1 * scale + 0.999), pix.height)
    if x1 <= x0 or y1 <= y0:
        return None
    step = max(1, int(((x1 - x0) * (y1 - y0) / MAX_SAMPLES) ** 0.5))
    n, stride, data = pix.n, pix.stride, pix.samples
    reds, greens, blues = [], [], []
    for y in range(y0, y1, step):
        row = y * stride
        for x in range(x0, x1, step):
            o = row + x * n
            if n >= 3:
                reds.append(data[o]); greens.append(data[o + 1]); blues.append(data[o + 2])
            else:
                reds.append(data[o]); greens.append(data[o]); blues.append(data[o])
    if not reds:
        return None
    mid = len(reds) // 2
    return tuple(sorted(ch)[mid] / 255.0 for ch in (reds, greens, blues))


def page_contrast(doc: "fitz.Document", index: int, dpi: int = CHECK_DPI):
    """{"spans": checked, "low": below the minimum, "lowest": lowest ratio} for one page, or None when the page
    has no visible text to check."""
    spans = _visible_spans(doc[index])
    if not spans:
        return None
    one = fitz.open()
    try:
        one.insert_pdf(doc, from_page=index, to_page=index, annots=False)
        bare = one[0]
        for r, *_ in spans:
            bare.add_redact_annot(r, fill=False, cross_out=False)
        bare.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                              text=fitz.PDF_REDACT_TEXT_REMOVE)
        pix = bare.get_pixmap(dpi=dpi, alpha=False, annots=False, colorspace=fitz.csRGB)
    finally:
        one.close()
    scale = dpi / 72.0
    checked, low, lowest = 0, 0, None
    for r, rgb, opacity, size, bold in spans:
        bg = _background(pix, r, scale)
        if bg is None:
            continue
        if opacity < 1.0:  # what the reader sees: the text colour blended over the background
            rgb = tuple(opacity * f + (1 - opacity) * b for f, b in zip(rgb, bg))
        ratio = contrast_ratio(rgb, bg)
        checked += 1
        if ratio < (LARGE_MIN if is_large(size, bold) else NORMAL_MIN):
            low += 1
        lowest = ratio if lowest is None else min(lowest, ratio)
    if not checked:
        return None
    return {"spans": checked, "low": low, "lowest": round(lowest, 2)}


class ContrastReport:
    """Collects page results for one build. `page` is the original document's page number (1-based)."""

    def __init__(self, seconds: float = CONTRAST_BUDGET_S):
        self.deadline = time.monotonic() + seconds
        self.checked, self.spans = 0, 0
        self.low_pages, self.no_text, self.time_up = [], [], []
        self.errors = 0

    def check(self, doc: "fitz.Document", index: int, page_no: int) -> None:
        if time.monotonic() >= self.deadline:
            self.time_up.append(page_no)
            return
        try:
            result = page_contrast(doc, index)
        except Exception:  # a report, never a reason to fail a build
            self.errors += 1
            self.no_text.append(page_no)
            return
        if result is None:
            self.no_text.append(page_no)
            return
        self.checked += 1
        self.spans += result["spans"]
        if result["low"]:
            self.low_pages.append({"page": page_no, "spans": result["low"], "lowest": result["lowest"]})

    def as_dict(self) -> dict:
        out = {
            "pagesChecked": self.checked,
            "spansChecked": self.spans,
            "lowContrastPages": self.low_pages[:REPORT_PAGE_CAP],
            "notChecked": {"noText": self.no_text[:REPORT_PAGE_CAP], "timeUp": self.time_up[:REPORT_PAGE_CAP]},
        }
        more = max(0, len(self.low_pages) - REPORT_PAGE_CAP)
        if more:
            out["moreLowContrastPages"] = more
        if self.errors:
            out["errors"] = self.errors
        return out
