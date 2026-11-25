"""Text contrast on picture pages (contrast_check.py, checklist 1.3).

Rules under test:
- the WCAG maths: #777 on white is 4.48:1, black on white 21:1, a colour on itself 1:1, either order;
- large text is at least 18 pt, or 14 pt bold, and needs 3:1; other text needs 4.5:1;
- on a made-up page, light grey body text is flagged and black text is not; white text on a dark band is read
  against the band, not the white page; a large grey heading passes at 3:1 where small grey text fails;
- a page with no visible text (blank, or only invisible OCR-style text) is "not checked", not "fine";
- the report runs out of time politely (later pages "timeUp") and never raises;
- through /build: the X-Contrast header lists the grey-text page and the page without text, and the
  accessible text pages the engine writes stay black on white (nothing on them is flagged).
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fitz
import contrast_check as cc

GREY = (0.6, 0.6, 0.6)  # #999 on white: 2.85:1


def made_up_page(doc=None):
    doc = doc or fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Light grey body text for the test", fontsize=11, color=GREY)
    page.insert_text((72, 130), "Black body text", fontsize=11, color=(0, 0, 0))
    return doc, page


def test_ratio_maths():
    assert abs(cc.contrast_ratio((0x77 / 255,) * 3, (1, 1, 1)) - 4.48) < 0.01
    assert round(cc.contrast_ratio((0, 0, 0), (1, 1, 1)), 2) == 21.0
    assert cc.contrast_ratio((0.3, 0.5, 0.7), (0.3, 0.5, 0.7)) == 1.0
    assert cc.contrast_ratio(GREY, (1, 1, 1)) == cc.contrast_ratio((1, 1, 1), GREY)
    assert cc._to_rgb((0.25,), 1) == (0.25, 0.25, 0.25)
    assert cc._to_rgb((0, 0, 0, 1), 4) == (0, 0, 0) and cc._to_rgb((0, 0, 0, 0), 4) == (1, 1, 1)


def test_large_text_rule():
    assert cc.is_large(18, False) and cc.is_large(14, True)
    assert not cc.is_large(17.9, False) and not cc.is_large(13.9, True)


def test_grey_is_flagged_black_is_not():
    doc, _ = made_up_page()
    r = cc.page_contrast(doc, 0)
    assert r["spans"] == 2 and r["low"] == 1, r
    assert abs(r["lowest"] - 2.85) < 0.05, r


def test_background_is_what_is_behind_the_text():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(60, 160, 500, 200), color=None, fill=(0.1, 0.1, 0.3))
    page.insert_text((72, 185), "White text on a dark band", fontsize=11, color=(1, 1, 1))
    r = cc.page_contrast(doc, 0)
    assert r["low"] == 0 and r["lowest"] > 10, r
    page.insert_text((72, 240), "Pale yellow on white", fontsize=11, color=(1, 1, 0.6))
    r = cc.page_contrast(doc, 0)
    assert r["low"] == 1 and r["lowest"] < 1.2, r


def test_large_text_uses_three_to_one():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Big grey heading", fontsize=20, color=(0.55, 0.55, 0.55))  # 3.35:1
    assert cc.page_contrast(doc, 0)["low"] == 0
    page.insert_text((72, 140), "Small grey text", fontsize=11, color=(0.55, 0.55, 0.55))
    assert cc.page_contrast(doc, 0)["low"] == 1


def test_page_without_visible_text_is_not_checked():
    doc = fitz.open()
    doc.new_page()
    hidden = doc.new_page()
    hidden.insert_text((72, 100), "OCR layer drawn invisibly", fontsize=11, render_mode=3)
    assert cc.page_contrast(doc, 0) is None and cc.page_contrast(doc, 1) is None
    report = cc.ContrastReport()
    for i in range(2):
        report.check(doc, i, i + 1)
    out = report.as_dict()
    assert out["pagesChecked"] == 0 and out["notChecked"]["noText"] == [1, 2], out


def test_report_runs_out_of_time_and_never_raises():
    doc, _ = made_up_page()
    late = cc.ContrastReport(seconds=0)
    late.check(doc, 0, 1)
    assert late.as_dict()["notChecked"]["timeUp"] == [1]
    report = cc.ContrastReport()
    report.check(doc, 0, 1)
    report.check(doc, 7, 8)  # no such page: counted, not raised
    out = report.as_dict()
    assert out["pagesChecked"] == 1 and out["lowContrastPages"] == [{"page": 1, "spans": 1, "lowest": out["lowContrastPages"][0]["lowest"]}]
    assert out["errors"] == 1 and out["notChecked"]["noText"] == [8], out


def test_build_reports_contrast_and_text_pages_stay_black_on_white():
    try:
        import types
        from fastapi.testclient import TestClient
    except ImportError:
        print("  (FastAPI not installed; build check skipped)")
        return
    for k in ("SUPABASE_URL", "SUPABASE_KEY", "PDF_ENGINE_SECRET"):
        os.environ.pop(k, None)
    sys.modules.setdefault("commonforms", types.SimpleNamespace(prepare_form=lambda *a, **k: None))
    import main
    doc, _ = made_up_page()
    doc.new_page(width=612, height=792)  # page 2: nothing to check
    html = ('<section aria-label="Page 0" data-page="0"><h1>Contrast test</h1><p>Text version of page one.</p>'
            '<p><a href="https://example.org">A link</a></p></section>'
            '<section aria-label="Page 1" data-page="1"><h2>Page two</h2><p>Text version of page two.</p></section>')
    r = TestClient(main.app, raise_server_exceptions=False).post(
        "/build",
        data={"html_content": html, "corrected_forms_json": "{}", "document_title": "Contrast test", "guide_style": "v2"},
        files={"original_pdf": ("orig.pdf", doc.tobytes(), "application/pdf")},
    )
    assert r.status_code == 200, (r.status_code, r.text[:300])
    info = json.loads(r.headers["X-Contrast"])
    assert info["pagesChecked"] == 1, info
    assert [p["page"] for p in info["lowContrastPages"]] == [1] and info["lowContrastPages"][0]["spans"] == 1, info
    assert info["notChecked"]["noText"] == [2], info
    out = fitz.open(stream=r.content, filetype="pdf")
    # Pages 1-2 are pictures, page 3 the guide; the accessible text pages follow and are black on white.
    for i in range(2, len(out)):
        res = cc.page_contrast(out, i)
        assert res is None or res["low"] == 0, (i + 1, res)


if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print(f"ok: {name}")
            except Exception as e:
                fails += 1; print(f"FAIL: {name}: {e!r}")
    print(f"\n{'ALL' if not fails else fails} contrast_check tests {'passed' if not fails else 'FAILED'}")
    sys.exit(1 if fails else 0)
