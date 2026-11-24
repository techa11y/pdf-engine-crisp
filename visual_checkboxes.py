"""Drawn checkboxes on the picture pages become real, tickable checkboxes (2026-11-24).

Why (Geoffrey relaying QA, Return to Learn Protocol 98378eec: "he said he cannot tick this", then
"I think only page 2 has the checkboxes so that should be tickable"): the first pages of every
remediated PDF are pictures of the original. A box printed on the original is only pixels there,
so a sighted user cannot tick it. This module finds those boxes on each original page and the
build places a real checkbox field over each one, at the same spot, inside the picture.

Where a box comes from:
- vector: a small square drawn as a path (Word / InDesign exports), stroked or as a filled ring;
  each is confirmed by its own pixels (all four edges inked, the middle empty);
- glyph: a box character in the text layer (☐ □ ❏ ..., or Wingdings' box codes); its exact square
  is found by rendering just that glyph's area;
- raster: a scanned page (no text layer): hollow squares in the page's pixels, 5-16 pt, square
  within 20 %, with sharp corners (a letter O / 0 / D is rounded), empty inside and with white space
  all round (a letter inside a word touches its neighbours; a QR code's corner ring touches modules).
A spot the original already has a real form field on is skipped (that field is handled elsewhere).

Each box is named by the words printed right beside it on its line (a page with a text layer), else
"Checkbox n of m, visual page p". The accessible text's own checkbox labels are NOT matched to the
boxes: on Return to Learn page 2 both counts are 37, yet the picture has a box before "Mandatory
Breaks" (a text field in the accessible text) and none before "minutes per class" (a checkbox there),
so matching by order named 20 boxes after their neighbour. A wrong name is worse than a plain one;
the accessible text pages keep their own, correctly named checkboxes.
"""
from __future__ import annotations

import html as _html
import re
import time

import fitz
from PIL import Image

MIN_PT = 5.0
MAX_PT = 16.0
# More than this on one page is not a form: a grid or a pattern. Place none rather than litter.
MAX_BOXES_PER_PAGE = 150
# Pixel detection is pure Python (about 0.3 s a page); a very long scan stops being checked after this.
RASTER_BUDGET_S = 90.0

BOX_CHARS = set("☐☑☒□▢❏❐❑❒⬜")
# Wingdings codes that draw a box: o q r x (box, shadowed boxes, box with X), ¨ (medium square),
# ý þ (box with X / with check). PyMuPDF reports a symbol font's code as itself or as U+F0xx.
WINGDINGS_BOX_CODES = {0x6F, 0x71, 0x72, 0x78, 0xA8, 0xFD, 0xFE}


def _is_square(w: float, h: float) -> bool:
    return MIN_PT <= w <= MAX_PT and MIN_PT <= h <= MAX_PT and abs(w - h) <= 0.2 * max(w, h)


def _dark(data: bytes, W: int, H: int, x0: int, y0: int, x1: int, y1: int) -> float:
    """Share of dark pixels in a rectangle of a thresholded image (outside the image counts as white)."""
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W - 1, x1), min(H - 1, y1)
    if x1 < x0 or y1 < y0:
        return 0.0
    n = sum(data[y * W + x0:y * W + x1 + 1].count(0) for y in range(y0, y1 + 1))
    return n / ((x1 - x0 + 1) * (y1 - y0 + 1))


# ---------------------------------------------------------------- pixel detection

def raster_boxes(page: "fitz.Page", dpi: int = 150, clip: "fitz.Rect | None" = None) -> list:
    """Hollow squares in the page's pixels (or in `clip`), in page points."""
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, clip=clip, alpha=False)
    W, H = pix.width, pix.height
    data = Image.frombytes("L", (W, H), pix.samples).point(lambda v: 0 if v < 140 else 255).tobytes()
    parent: dict = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    runs: dict = {}
    prev: list = []
    rid = 0
    for y in range(H):
        row = data[y * W:(y + 1) * W]
        cur = []
        for m in re.finditer(rb"\x00+", row):
            x0, x1 = m.start(), m.end() - 1
            parent[rid] = rid
            runs[rid] = (y, x0, x1)
            cur.append((x0, x1, rid))
            for (px0, px1, prid) in prev:
                if px0 <= x1 + 1 and px1 >= x0 - 1:
                    ra, rb = find(rid), find(prid)
                    if ra != rb:
                        parent[rb] = ra
            rid += 1
        prev = cur
    comps: dict = {}
    for r, run in runs.items():
        comps.setdefault(find(r), []).append(run)
    scale = 72.0 / dpi
    ox, oy = (clip.x0, clip.y0) if clip is not None else (0.0, 0.0)
    out = []
    for rr in comps.values():
        ys = [y for y, _, _ in rr]
        bx0 = min(a for _, a, _ in rr)
        bx1 = max(b for _, _, b in rr)
        by0, by1 = min(ys), max(ys)
        w, h = bx1 - bx0 + 1, by1 - by0 + 1
        if not _is_square(w * scale, h * scale):
            continue
        dark = sum(b - a + 1 for _, a, b in rr)
        if not (0.12 <= dark / (w * h) <= 0.65):
            continue
        # Hollow: the middle half is (nearly) empty, so not a letter or a filled bullet.
        ix0, ix1, iy0, iy1 = bx0 + w * 0.25, bx1 - w * 0.25, by0 + h * 0.25, by1 - h * 0.25
        inner = sum(max(0, min(b, ix1) - max(a, ix0) + 1) for y, a, b in rr if iy0 <= y <= iy1)
        if inner > 0.08 * (ix1 - ix0 + 1) * (iy1 - iy0 + 1):
            continue
        top = sum(b - a + 1 for y, a, b in rr if y <= by0 + 2)
        bot = sum(b - a + 1 for y, a, b in rr if y >= by1 - 2)
        if top < 0.7 * w or bot < 0.7 * w:
            continue

        def dark_near(cx, cy, k=1):
            return any(abs(y - cy) <= k and a <= cx + k and b >= cx - k for y, a, b in rr)

        # Sharp corners: a drawn box reaches all four; a letter O / 0 / D is rounded.
        if not all(dark_near(cx, cy) for cx, cy in ((bx0, by0), (bx1, by0), (bx0, by1), (bx1, by1))):
            continue
        # Empty inside in the whole picture (a QR code's corner ring holds a square), and white space
        # all round (a letter inside a word touches its neighbours; a QR ring touches modules).
        if _dark(data, W, H, int(ix0), int(iy0), int(ix1), int(iy1)) > 0.08:
            continue
        m = max(3, int(round(0.6 * w)))
        strips = ((bx0 - m, by0, bx0 - 1, by1), (bx1 + 1, by0, bx1 + m, by1),
                  (bx0, by0 - m, bx1, by0 - 1), (bx0, by1 + 1, bx1, by1 + m))
        if any(_dark(data, W, H, *s_) > 0.15 for s_ in strips):
            continue
        out.append(fitz.Rect(ox + bx0 * scale, oy + by0 * scale, ox + (bx1 + 1) * scale, oy + (by1 + 1) * scale))
    return out


# ---------------------------------------------------------------- vector and glyph detection

def _outlined_square(page: "fitz.Page", r: "fitz.Rect", dpi: int = 200) -> "fitz.Rect | None":
    """A drawn shape is a box when its pixels outline its own square: each of the four edges inked
    along at least 85 % of its length, ink at all four corners, and the middle empty. Text touching
    the box does not matter; a hollow circle (no ink at the corners) and a filled bullet do not pass."""
    clip = fitz.Rect(r) + (-1, -1, 1, 1)
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, clip=clip, alpha=False)
    W, H = pix.width, pix.height
    data = Image.frombytes("L", (W, H), pix.samples).point(lambda v: 0 if v < 140 else 255).tobytes()
    k = dpi / 72.0
    x0, y0 = int(round((r.x0 - clip.x0) * k)), int(round((r.y0 - clip.y0) * k))
    x1, y1 = int(round((r.x1 - clip.x0) * k)) - 1, int(round((r.y1 - clip.y0) * k)) - 1
    w, h = x1 - x0 + 1, y1 - y0 + 1
    if w < 4 or h < 4:
        return None
    t = max(2, int(round(0.15 * min(w, h))))

    def covered(xs, ys, along_x):
        hits = 0
        for a in (xs if along_x else ys):
            band = [(a, b) for b in ys] if along_x else [(b, a) for b in xs]
            hits += any(0 <= x < W and 0 <= y < H and data[y * W + x] == 0 for x, y in band)
        return hits / (len(xs) if along_x else len(ys))

    inner_x = range(x0 + t, x1 - t + 1)
    inner_y = range(y0 + t, y1 - t + 1)
    if not inner_x or not inner_y:
        return None
    edges = (
        covered(inner_x, range(y0 - 1, y0 + t), True),   # top
        covered(inner_x, range(y1 - t + 1, y1 + 2), True),  # bottom
        covered(range(x0 - 1, x0 + t), inner_y, False),  # left
        covered(range(x1 - t + 1, x1 + 2), inner_y, False),  # right
    )
    if min(edges) < 0.85:
        return None
    # Square corners: ink at all four corners of the drawing's own square (a small circle has none there).
    c = max(1, int(round(0.06 * min(w, h))))  # 1 px for a 5 pt shape, 2 px at 10 pt (anti-aliased corners)
    if not all(_dark(data, W, H, cx - c, cy - c, cx + c, cy + c) > 0 for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))):
        return None
    if _dark(data, W, H, int(x0 + 0.25 * w), int(y0 + 0.25 * h), int(x1 - 0.25 * w), int(y1 - 0.25 * h)) > 0.1:
        return None
    return fitz.Rect(r)


def vector_boxes(page: "fitz.Page") -> list:
    """Small squares drawn as paths, judged by their own pixels (`_outlined_square`): a stroked square or
    a filled outline (a ring) counts; a filled bullet or a hollow circle does not."""
    out = []
    cands = [fitz.Rect(d["rect"]) for d in page.get_drawings()
             if d.get("rect") is not None and 4.5 <= d["rect"].width <= 18 and 4.5 <= d["rect"].height <= 18
             and abs(d["rect"].width - d["rect"].height) <= 0.25 * max(d["rect"].width, d["rect"].height)]
    if len(cands) > 4 * MAX_BOXES_PER_PAGE:  # a chart or a pattern, not a form
        return out
    for r in cands:
        if any(_overlaps(r, o) for o in out):
            continue
        sq = _outlined_square(page, r)
        if sq is not None:
            out.append(sq)
    return out


def _is_box_char(c: int, font: str) -> bool:
    if chr(c) in BOX_CHARS:
        return True
    if "wingding" in (font or "").lower():
        code = c - 0xF000 if 0xF000 <= c <= 0xF0FF else c
        return code in WINGDINGS_BOX_CODES
    return False


def _glyph_square(page: "fitz.Page", bbox: "fitz.Rect", dpi: int = 200) -> "fitz.Rect | None":
    """The square a box character actually draws: the dark pixels' extent inside its glyph box, which
    must be square, 5-18 pt and empty inside (a ☒ / ☑ printed already ticked is an answer, not a box
    to tick). The text layer already says it is a box, so a slanted or shadowed one (❏ ❑) counts."""
    clip = fitz.Rect(bbox) + (-1, -1, 1, 1)
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, clip=clip, alpha=False)
    W, H = pix.width, pix.height
    data = Image.frombytes("L", (W, H), pix.samples).point(lambda v: 0 if v < 140 else 255).tobytes()
    rows = [y for y in range(H) if data[y * W:(y + 1) * W].count(0)]
    if not rows:
        return None
    cols = [x for x in range(W) if any(data[y * W + x] == 0 for y in rows)]
    x0, x1, y0, y1 = cols[0], cols[-1], rows[0], rows[-1]
    w, h = x1 - x0 + 1, y1 - y0 + 1
    scale = 72.0 / dpi
    if not (MIN_PT <= w * scale <= 18 and MIN_PT <= h * scale <= 18 and abs(w - h) <= 0.25 * max(w, h)):
        return None
    if _dark(data, W, H, int(x0 + 0.25 * w), int(y0 + 0.25 * h), int(x1 - 0.25 * w), int(y1 - 0.25 * h)) > 0.1:
        return None
    return fitz.Rect(clip.x0 + x0 * scale, clip.y0 + y0 * scale, clip.x0 + (x1 + 1) * scale, clip.y0 + (y1 + 1) * scale)


def glyph_boxes(page: "fitz.Page") -> list:
    """Box characters in the text layer, at the square they draw."""
    out = []
    try:
        spans = page.get_texttrace()
    except Exception:
        return out
    for span in spans:
        font = span.get("font", "")
        for ch in span.get("chars", ()):
            if not _is_box_char(ch[0], font):
                continue
            bbox = fitz.Rect(ch[3])
            if bbox.is_empty:
                continue
            sq = _glyph_square(page, bbox)
            if sq is not None:
                out.append(sq)
    return out


def _overlaps(a: "fitz.Rect", b: "fitz.Rect", share: float = 0.5) -> bool:
    i = fitz.Rect(a) & b
    if i.is_empty:
        return False
    return i.width * i.height >= share * min(a.width * a.height, b.width * b.height)


def detect_checkboxes(page: "fitz.Page", allow_raster: bool = True) -> list:
    """The page's drawn checkboxes (page points, reading order), minus spots holding a real field."""
    has_text = bool(page.get_text("text").strip())
    found = vector_boxes(page) + glyph_boxes(page)
    if not found and not has_text and allow_raster:
        found = raster_boxes(page)
    boxes: list = []
    for r in found:
        if not any(_overlaps(r, b) for b in boxes):
            boxes.append(r)
    try:
        fields = [w.rect for w in page.widgets()]
    except Exception:
        fields = []
    boxes = [r for r in boxes if not any(_overlaps(r, f, 0.3) for f in fields)]
    if len(boxes) > MAX_BOXES_PER_PAGE:
        return []
    boxes.sort(key=lambda r: (round(r.y0 / 4), r.x0))
    return boxes


# ---------------------------------------------------------------- names

INVISIBLE = "\u200b\u200c\u200d\u2060\ufeff\u00ad"


def _clean(text: str, limit: int = 120) -> str:
    text = re.sub(f"[{INVISIBLE}]", "", text or "")
    text = re.sub(r"_{2,}", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" :")
    return text[:limit].rstrip()


def words_beside(page: "fitz.Page", boxes: list) -> list:
    """For each box, the words printed right after it on its line (up to the next box or a wide gap)."""
    words = page.get_text("words")
    lead = re.compile(f"^[{''.join(sorted(BOX_CHARS))}{INVISIBLE}\uf000-\uf0ff\\s]+")
    out = []
    for b in boxes:
        cy0, cy1 = b.y0 - 2, b.y1 + 2
        line = []
        for w in words:
            if min(w[3], cy1) - max(w[1], cy0) < 0.5 * (w[3] - w[1]):
                continue
            if w[0] >= b.x1 - 1:
                line.append(w)
            elif w[2] > b.x1 + 1 and lead.match(w[4]):
                # The box character and its words were written without a space ("❏Academic").
                line.append((b.x1, w[1], w[2], w[3], lead.sub("", w[4])))
        line = [w for w in line if _clean(w[4])]
        line.sort(key=lambda w: w[0])
        # Stop at the next box on the same line (a row of "Yes ☐ No ☐" choices).
        stop_x = min((o.x0 for o in boxes if o is not b and o.x0 > b.x1 and min(o.y1, cy1) > max(o.y0, cy0)), default=1e9)
        picked, last_x = [], b.x1
        for w in line:
            # The first word may sit up to 15 pt from the box; after that, a gap wider than half the
            # text's height is the start of the next field's label ("Part Time   Monthly Payroll ...").
            limit = 15 if not picked else max(3.0, 0.5 * (w[3] - w[1]))
            if w[0] >= stop_x or w[0] - last_x > limit or len(picked) >= 12:
                break
            picked.append(w[4])
            last_x = w[2]
        out.append(_clean(" ".join(picked)))
    return out


def name_checkboxes(page: "fitz.Page", boxes: list, visual_page: int) -> list:
    names = words_beside(page, boxes)
    return [beside or f"Checkbox {n + 1} of {len(boxes)}, visual page {visual_page}" for n, beside in enumerate(names)]


# ---------------------------------------------------------------- the overlay

class RasterBudget:
    """Pixel detection time left for this build."""

    def __init__(self, seconds: float = RASTER_BUDGET_S):
        self.deadline = time.monotonic() + seconds

    def left(self) -> bool:
        return time.monotonic() < self.deadline


def checkbox_overlay(page: "fitz.Page", page_index: int, budget: "RasterBudget | None" = None) -> tuple:
    """HTML for real checkboxes over this picture page's drawn boxes, and how many.

    Coordinates are the original page's points, like the link overlays, so the boxes sit in the same
    (scaled) container as the picture."""
    try:
        boxes = detect_checkboxes(page, allow_raster=budget.left() if budget else True)
    except Exception:
        return "", 0
    if not boxes:
        return "", 0
    names = name_checkboxes(page, boxes, page_index + 1)
    parts = []
    for n, (r, name) in enumerate(zip(boxes, names), start=1):
        label = _html.escape(name, quote=True)
        parts.append(
            f'<input type="checkbox" id="vcb_{page_index}_{n}" name="visual_p{page_index + 1}_cb{n}" '
            f'title="{label}" aria-label="{label}" '
            f'style="position:absolute; left:{round(r.x0, 2)}pt; top:{round(r.y0, 2)}pt; '
            f'width:{round(r.width, 2)}pt; height:{round(r.height, 2)}pt; margin:0; padding:0; '
            f'border:none; background:transparent; z-index:95;" />'
        )
    return "".join(parts), len(boxes)
