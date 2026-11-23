#!/usr/bin/env python3
"""Document language and visual-page link labels (a11y_labels.py + /build).

Before: every PDF was tagged en-US whatever its language (WCAG 3.1.1), and every
link overlay on a visual page was named just "Link" (WCAG 2.4.4).

Run with:  python tests/test_a11y_labels.py
"""
import io
import logging
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
for k in ("SUPABASE_URL", "SUPABASE_KEY"):
    os.environ.pop(k, None)  # /build then returns the PDF inline
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

from a11y_labels import safe_lang, visual_link_label
import main

client = TestClient(main.app, raise_server_exceptions=False)


def test_safe_lang():
    assert safe_lang(None) == "en-US" and safe_lang("") == "en-US"
    assert safe_lang("es") == "es" and safe_lang("ES") == "es"
    assert safe_lang("es-mx") == "es-MX" and safe_lang("en_us") == "en-US"
    assert safe_lang("zh-hant-tw") == "zh-Hant-TW" and safe_lang("es-419") == "es-419"
    for bad in ("spanish", "e", "en US", "<script>", "en-US; x", "toolongprimary"):
        assert safe_lang(bad) == "en-US", bad
    print("ok: safe_lang normalises BCP 47 tags and falls back to en-US")


def test_visual_link_label():
    assert visual_link_label("https://www.example.org/board/agenda.pdf") == "Link to example.org/board/agenda.pdf"
    assert visual_link_label("http://example.org/") == "Link to example.org"
    assert visual_link_label("www.city.gov") == "Link to city.gov"
    assert visual_link_label("mailto:clerk@city.gov?subject=Hi") == "Email clerk@city.gov"
    assert visual_link_label("tel:+15551234567") == "Call +15551234567"
    assert visual_link_label("#page_3", 3) == "Go to visual page 4"
    long = visual_link_label("https://example.org/" + "a" * 80)
    assert long.endswith("...") and len(long) < 70, long
    assert visual_link_label("") == "Link"
    print("ok: visual_link_label names where each link goes")


def _original_pdf():
    d = mupdf.open()
    p = d.new_page(width=612, height=792)
    p.insert_text((72, 72), "Original page with a link", fontsize=12)
    p.insert_link({"kind": mupdf.LINK_URI, "from": mupdf.Rect(72, 90, 300, 110),
                   "uri": "https://www.example.org/board/agenda.pdf"})
    return d.tobytes()


def _build(**extra):
    data = {"html_content": "<section><h1>Informe</h1><p>Este es el informe anual.</p></section>",
            "corrected_forms_json": "{}", "document_title": "Informe anual", "guide_style": "v2"}
    data.update(extra)
    r = client.post("/build", data=data, files={"original_pdf": ("orig.pdf", _original_pdf(), "application/pdf")})
    assert r.status_code == 200, (r.status_code, r.text[:200])
    return pikepdf.open(io.BytesIO(r.content))


def _walk(pdf):
    out = []

    def rec(e):
        if isinstance(e, pikepdf.Array):
            for k in e:
                rec(k)
        elif isinstance(e, pikepdf.Dictionary) and "/S" in e:
            out.append(e)
            if "/K" in e:
                rec(e.K)
    rec(pdf.Root.StructTreeRoot.get("/K"))
    return out


def test_document_lang_spanish():
    pdf = _build(document_lang="es")
    assert str(pdf.Root.get("/Lang")) == "es", pdf.Root.get("/Lang")
    english = [e for e in _walk(pdf) if str(e.get("/Lang", "")) == "en"]
    assert english, "guide page / visual pages should be marked lang=en in a Spanish document"
    print("ok: document_lang=es sets /Lang es; engine-written English text is marked en")


def test_document_lang_omitted_or_bad_stays_english():
    for extra in ({}, {"document_lang": "not a tag"}):
        pdf = _build(**extra)
        assert str(pdf.Root.get("/Lang")).startswith("en"), (extra, pdf.Root.get("/Lang"))
        assert not [e for e in _walk(pdf) if "/Lang" in e and str(e.Lang) == "en"], "no extra marking in English docs"
    print("ok: omitted or invalid document_lang keeps the English default, unchanged")


def test_passage_lang_is_tagged():
    html = ('<section><h1>Report</h1><p>English text.</p>'
            '<p lang="es">Este párrafo está en español.</p></section>')
    pdf = _build(html_content=html)
    assert str(pdf.Root.get("/Lang")).startswith("en"), pdf.Root.get("/Lang")
    tagged = [e for e in _walk(pdf) if str(e.get("/Lang", "")) == "es"]
    assert len(tagged) == 1 and str(tagged[0].S) == "/P", [(str(e.S), str(e.get("/Lang"))) for e in tagged]
    print("ok: a Spanish paragraph in an English document is tagged /Lang es")


def test_visual_page_link_is_named():
    pdf = _build()
    alts = {str(e.get("/Alt")) for e in _walk(pdf) if str(e.S) == "/Figure"}
    assert "Link to example.org/board/agenda.pdf" in alts, alts
    assert "Link" not in alts, alts
    print("ok: the visual-page link overlay is named after its destination")


if __name__ == "__main__":
    test_safe_lang()
    test_visual_link_label()
    test_document_lang_spanish()
    test_document_lang_omitted_or_bad_stays_english()
    test_passage_lang_is_tagged()
    test_visual_page_link_is_named()
    print("\nALL a11y_labels tests passed")
