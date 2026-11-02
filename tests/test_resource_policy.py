#!/usr/bin/env python3
"""Regression test: HTML sent to /build cannot make the engine read local files or URLs.

Before the fix, <link rel="attachment" href="file:///..."> embedded the file in the PDF.
The engine's own resources (data: GIF overlays, per-request visual-page JPEGs) must keep
working.

Run with:  python tests/test_resource_policy.py
"""
import io
import logging
import os
import sys
import tempfile
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
import pikepdf
from fastapi.testclient import TestClient

import main
from resource_policy import RestrictedURLFetcher

client = TestClient(main.app, raise_server_exceptions=False)
CANARY = b"RESOURCE-POLICY-CANARY-51c2"


def _canary_file():
    f = tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False)
    f.write(CANARY)
    f.close()
    return f.name


def _original_pdf():
    d = mupdf.open()
    p = d.new_page(width=612, height=792)
    p.insert_text((72, 72), "Original page", fontsize=12)
    p.insert_link({"kind": mupdf.LINK_URI, "from": mupdf.Rect(72, 60, 200, 80), "uri": "https://example.org/"})
    return d.tobytes()


def _build(html):
    r = client.post(
        "/build",
        data={"html_content": html, "corrected_forms_json": "{}", "document_title": "Policy", "guide_style": "v2"},
        files={"original_pdf": ("orig.pdf", _original_pdf(), "application/pdf")},
    )
    assert r.status_code == 200, (r.status_code, r.text[:200])
    return r.content


def test_fetcher_unit():
    path = _canary_file()
    f = RestrictedURLFetcher(allowed_files=[path])
    assert f.fetch(f"file://{path}") is not None
    assert f.fetch("data:text/plain,hi") is not None
    for url in ("file:///etc/hostname", "http://127.0.0.1:1/x", "https://example.org/a.png", "ftp://x/y"):
        try:
            f.fetch(url)
        except ValueError:
            continue
        raise AssertionError(f"not blocked: {url}")
    print("ok: data: and allow-listed files load; other files, http(s) and ftp are refused")


def test_attachment_of_local_file_is_not_embedded():
    path = _canary_file()
    pdf_bytes = _build(f'<p>x</p><link rel="attachment" href="file://{path}">'
                       f'<p><a rel="attachment" href="file://{path}">doc</a></p>'
                       f'<p><img src="file://{path}" alt="x"></p>'
                       f'<link rel="stylesheet" href="file://{path}">')
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        for spec in pdf.attachments.values():
            assert CANARY not in spec.get_file().read_bytes(), "local file embedded in the PDF"
    assert CANARY not in pdf_bytes
    print("ok: a local file referenced by the page HTML is not read into the PDF")


def test_remote_resources_are_not_fetched():
    """No request may reach a server named in the page HTML, in ANY render pass
    (/build lays the document out twice: a TOC page-number pass and the final write)."""
    import http.server, threading
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        pdf_bytes = _build(f'<p><img src="{base}/img.png" alt="remote"></p>'
                           f'<link rel="attachment" href="{base}/attach.txt">'
                           f'<link rel="stylesheet" href="{base}/style.css">')
    finally:
        srv.shutdown()
    assert pdf_bytes.startswith(b"%PDF")
    assert hits == [], f"engine fetched URLs named in the page HTML: {hits}"
    print("ok: no request reaches a URL named in the page HTML (both render passes)")


def test_engine_visual_page_image_still_rendered():
    pdf_bytes = _build("<h1>Heading</h1><p>Body.</p>")
    doc = mupdf.open(stream=pdf_bytes, filetype="pdf")
    assert len(doc[0].get_images()) >= 1, "visual page lost its page image"
    assert any(l.get("uri") == "https://example.org/" for l in doc[0].get_links()), "visual link overlay lost"
    print("ok: the visual page keeps its rendered page image and link overlay")


if __name__ == "__main__":
    test_fetcher_unit()
    test_attachment_of_local_file_is_not_embedded()
    test_remote_resources_are_not_fetched()
    test_engine_visual_page_image_still_rendered()
    print("\nALL resource_policy tests passed")
