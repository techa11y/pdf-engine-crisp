#!/usr/bin/env python3
"""The text section opens with the document title (#accessible-text-header); the page's own first heading
that repeats it is dropped, also when it sits inside the worker's page wrappers
(`<section aria-label="Page 1" data-page="1"><div lang="en"><h1>…`). Before 2026-11-24 the strip only looked
at the very start of the HTML, so every document whose first page opens with its title printed it twice
(QA's fillable test form, 2026-11-24).

Run with:  python tests/test_duplicate_title.py
"""
import io
import logging
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
for k in ("SUPABASE_URL", "SUPABASE_KEY", "PDF_ENGINE_SECRET"):
    os.environ.pop(k, None)
try:
    import commonforms  # noqa: F401
except ImportError:
    stub = types.ModuleType("commonforms")
    stub.prepare_form = lambda *a, **k: None
    sys.modules["commonforms"] = stub
try:
    import supabase  # noqa: F401
except ImportError:  # storage client not needed: /build returns the PDF inline without SUPABASE_URL
    stub = types.ModuleType("supabase")
    stub.create_client = lambda *a, **k: None
    stub.Client = object
    sys.modules["supabase"] = stub
logging.disable(logging.CRITICAL)

try:
    import pymupdf as mupdf
except ImportError:
    import fitz as mupdf
from fastapi.testclient import TestClient

import main

TITLE = "Volunteer sign-up form"
WRAPPED = (f'<section aria-label="Page 1" data-page="1">\n<div lang="en">\n  <h1>{TITLE}</h1>\n'
           '  <p>Full name:</p>\n</div>\n</section>')


def test_strip_inside_page_wrappers_keeps_the_wrappers():
    out = main.strip_duplicate_leading_title(WRAPPED, TITLE)
    assert TITLE not in out, out
    assert out.startswith('<section aria-label="Page 1" data-page="1">\n<div lang="en">'), out
    assert "<p>Full name:</p>" in out and out.count("</section>") == 1
    print("ok: a title heading inside the page wrappers is dropped, the wrappers stay")


def test_strip_unchanged_cases():
    assert main.strip_duplicate_leading_title(f"<h1>{TITLE}</h1><p>x</p>", TITLE) == "<p>x</p>"
    assert main.strip_duplicate_leading_title("<h1>Other</h1><p>x</p>", TITLE) == "<h1>Other</h1><p>x</p>"
    later = f'<section><p>Intro</p><h1>{TITLE}</h1></section>'
    assert main.strip_duplicate_leading_title(later, TITLE) == later, "only the FIRST block is compared"
    assert main.strip_duplicate_leading_title(WRAPPED, "") == WRAPPED
    print("ok: an unwrapped title is still dropped; another heading or a later one is kept")


def _original_pdf():
    d = mupdf.open()
    p = d.new_page(width=612, height=792)
    p.insert_text((72, 72), TITLE, fontsize=14)
    return d.tobytes()


def test_build_prints_the_title_once_on_the_text_pages():
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.post(
        "/build",
        data={"html_content": WRAPPED, "corrected_forms_json": "{}", "document_title": TITLE, "guide_style": "v2"},
        files={"original_pdf": ("orig.pdf", _original_pdf(), "application/pdf")},
    )
    assert r.status_code == 200, (r.status_code, r.text[:200])
    doc = mupdf.open(stream=io.BytesIO(r.content).read(), filetype="pdf")
    text_pages = [pg.get_text() for pg in doc if "Full name:" in pg.get_text()]
    assert text_pages, "no accessible text page"
    count = sum(t.count(TITLE) for t in text_pages)
    assert count == 1, f"title printed {count} times on the text pages"
    print("ok: /build prints the title once on the accessible text pages")


if __name__ == "__main__":
    test_strip_inside_page_wrappers_keeps_the_wrappers()
    test_strip_unchanged_cases()
    test_build_prints_the_title_once_on_the_text_pages()
