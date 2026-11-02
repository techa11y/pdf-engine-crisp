#!/usr/bin/env python3
"""Regression test: /build must not crash or emit a corrupt PDF when the page HTML contains
<button> or <input type="submit"> (WeasyPrint >= 66 turns them into push-button fields).

Observed in production on 2026-10-23 (HTTP 500 "'NoneType' object has no attribute 'element'")
after the WeasyPrint 62.3 -> 70.0 upgrade. Real form fields (text inputs) must stay fields.

Run with:  python tests/test_build_buttons.py
"""
import io
import logging
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
for k in ("SUPABASE_URL", "SUPABASE_KEY"):
    os.environ.pop(k, None)  # /build then returns the PDF inline instead of uploading it
try:
    import commonforms  # noqa: F401
except ImportError:  # heavy ML dependency not needed for /build
    stub = types.ModuleType("commonforms")
    stub.prepare_form = lambda *a, **k: None
    sys.modules["commonforms"] = stub
logging.disable(logging.CRITICAL)

try:
    import pymupdf as mupdf
except ImportError:
    import fitz as mupdf
import pikepdf
from fastapi.testclient import TestClient

import main

client = TestClient(main.app, raise_server_exceptions=False)
BODY = "<h1>Report</h1><p>Intro paragraph.</p>"


def _original_pdf():
    d = mupdf.open()
    p = d.new_page(width=612, height=792)
    p.insert_text((72, 72), "Original page", fontsize=12)
    return d.tobytes()


def _build(html):
    r = client.post(
        "/build",
        data={"html_content": html, "corrected_forms_json": "{}", "document_title": "Buttons", "guide_style": "v2"},
        files={"original_pdf": ("orig.pdf", _original_pdf(), "application/pdf")},
    )
    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert r.headers.get("content-type", "").startswith("application/pdf"), r.headers.get("content-type")
    assert b" None 0 R" not in r.content, "dangling field reference in the PDF"
    with pikepdf.open(io.BytesIO(r.content)) as pdf:
        return sum(1 for pg in pdf.pages for a in (pg.get("/Annots") or []) if a.get("/Subtype") == "/Widget")


def test_button_outside_form_builds():
    widgets = _build(BODY + '<p>Click <button type="button">Apply now</button> to start.</p>')
    assert widgets == 0, widgets
    print("ok: <button> with no ancestor <form> builds (no push-button field)")


def test_submit_in_post_form_builds():
    widgets = _build(BODY + '<form action="https://example.org/x" method="post"><input type="submit" value="Send"></form>')
    assert widgets == 0, widgets
    print("ok: <input type=submit> in a POST form builds, PDF valid")


def test_real_text_field_is_kept():
    widgets = _build(BODY + '<form><label>Name <input type="text" name="full_name"></label>'
                            '<button type="submit">Send</button></form>')
    assert widgets == 1, widgets
    print("ok: a real text input stays a form field next to a neutralized button")


if __name__ == "__main__":
    test_button_outside_form_builds()
    test_submit_in_post_form_builds()
    test_real_text_field_is_kept()
    print("\nALL build_buttons tests passed")
