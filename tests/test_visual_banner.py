#!/usr/bin/env python3
"""Regression test: the guide_style="v2" banner must not cover the visual page.

Before the fix the banner was painted over the full-page image, hiding the first
line of any original whose content reaches the top edge (e.g. a Google Docs
bulletin printed to PDF). Now the banner has its own strip and the page image,
link overlays and form fields are scaled to fit below it; the page size is
unchanged and the classic layout is untouched.

Run with:  python tests/test_visual_banner.py
"""
import json
import logging
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
for k in ("SUPABASE_URL", "SUPABASE_KEY"):
    os.environ.pop(k, None)
try:
    import commonforms  # noqa: F401
except ImportError:
    stub = types.ModuleType("commonforms")
    stub.prepare_form = lambda *a, **k: None
    sys.modules["commonforms"] = stub
logging.disable(logging.CRITICAL)

try:
    import pymupdf as mupdf
except ImportError:
    import fitz as mupdf
from fastapi.testclient import TestClient

import main
from visual_banner import BANNER_PAD_PT, BANNER_TEXT_EM, banner_layout

client = TestClient(main.app, raise_server_exceptions=False)

LINK_RECT = (72, 2, 200, 18)  # a link right at the top edge, inside the old banner area
FORMS = {"0": [{"x0": 300, "y0": 4, "x1": 460, "y1": 20, "type": 7, "name": "top_field"}]}
TOL = 0.2


def _original_pdf():
    d = mupdf.open()
    p = d.new_page(width=612, height=792)
    p.insert_text((72, 14), "First line reaches the top edge", fontsize=12)
    p.insert_link({"kind": mupdf.LINK_URI, "from": mupdf.Rect(*LINK_RECT), "uri": "https://example.org/top"})
    return d.tobytes()


def _build(style):
    r = client.post(
        "/build",
        data={"html_content": "<h1>Doc</h1><p>Body.</p>", "corrected_forms_json": json.dumps(FORMS),
              "document_title": "Banner", "guide_style": style},
        files={"original_pdf": ("orig.pdf", _original_pdf(), "application/pdf")},
    )
    assert r.status_code == 200, (r.status_code, r.text[:200])
    return mupdf.open(stream=r.content)


def _page_image_rect(page):
    rects = [rc for im in page.get_images(full=True) for rc in page.get_image_rects(im[0]) if rc.width > 500]
    assert len(rects) == 1, rects
    return rects[0]


def _top_link(page):
    # WeasyPrint emits two annotations per overlay <a> (the anchor and its inline image), same rect.
    rects = {tuple(round(v, 2) for v in l["from"]) for l in page.get_links() if l.get("uri") == "https://example.org/top"}
    assert len(rects) == 1, rects
    return rects.pop()


def _close(a, b):
    return all(abs(x - y) < TOL for x, y in zip(a, b))


def test_layout_numbers():
    letter = banner_layout(612, 792)
    assert letter.band == 22 and letter.font_pt == 9, letter
    assert abs(letter.scale - 770 / 792) < 1e-6 and abs(letter.offset_x - 612 * (1 - 770 / 792) / 2) < 1e-3, letter
    landscape = banner_layout(792, 612)
    assert landscape.band == 22 and landscape.scale > 0.96, landscape
    short = banner_layout(400, 100)  # strip capped at 8 % of a very short page
    assert short.band == 8 and abs(short.scale - 0.92) < 1e-6, short
    narrow = banner_layout(288, 432)  # 4x6 in: font shrinks so the banner stays on one line
    assert narrow.font_pt < 9 and narrow.font_pt * BANNER_TEXT_EM <= 288 - 2 * BANNER_PAD_PT, narrow
    print("ok: banner layout numbers")


def test_v2_banner_has_its_own_strip():
    page = _build("v2")[0]
    lay = banner_layout(612, 792)
    assert (page.rect.width, page.rect.height) == (612, 792), page.rect
    img = _page_image_rect(page)
    assert _close(img, (lay.offset_x, lay.band, 612 - lay.offset_x, 792)), img
    strips = [d["rect"] for d in page.get_drawings()
              if d.get("fill") == (1.0, 1.0, 1.0) and d["rect"].width > 600 and d["rect"].height < 50]
    assert strips, "banner background not found"
    assert all(s.y1 <= img.y0 + TOL for s in strips), (strips, img)
    hits = page.search_for("Remediated by MediaA11y")
    assert len(hits) == 1 and hits[0].y1 <= lay.band + TOL, hits
    print("ok: v2 banner sits in its own strip above the page image")


def test_v2_links_and_fields_follow_the_page():
    lay = banner_layout(612, 792)
    s, ox, oy = lay.scale, lay.offset_x, lay.band
    classic, v2 = _build("classic")[0], _build("v2")[0]
    link = _top_link(v2)
    x0, y0, x1, y1 = LINK_RECT
    assert _close(link, (ox + s * x0, oy + s * y0, ox + s * x1, oy + s * y1)), link
    (cw,), (vw,) = list(classic.widgets()), list(v2.widgets())
    c = cw.rect
    assert _close(vw.rect, (ox + s * c.x0, oy + s * c.y0, ox + s * c.x1, oy + s * c.y1)), (vw.rect, c)
    print("ok: link overlay and form field move with the scaled page")


def test_classic_layout_unchanged():
    page = _build("classic")[0]
    assert _close(_page_image_rect(page), (0, 0, 612, 792))
    assert _close(_top_link(page), LINK_RECT)
    print("ok: classic layout unchanged")


if __name__ == "__main__":
    test_layout_numbers()
    test_v2_banner_has_its_own_strip()
    test_v2_links_and_fields_follow_the_page()
    test_classic_layout_unchanged()
    print("all visual banner tests passed")
