"""Form fields in reading order (field_order.py, checklist 2.4).

Rules under test:
- row order: top to bottom, left to right within a line; a checkbox beside a taller text box shares its row;
  items at the same spot keep their order; odd coordinates (strings, None, swapped corners) don't break it;
- check_field_order reads the tags of a finished PDF: fields tagged out of row order are reported by page, and so
  is a page with fields but no /Tabs /S; a PDF without fields reports nothing; a broken file is not an error;
- through /build, a picture page's fields are tagged in row order, whatever list each came from: the original's
  own fields, the worker's AI boxes and the printed checkboxes are mixed by position, not written list by list.
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fitz
import pikepdf
import field_order as fo


def _ids(items):
    return [it[4] for it in fo.row_order(items)]


def test_row_order():
    items = [(300, 100, 400, 114, "b"), (72, 101, 200, 115, "a"), (72, 200, 82, 210, "c"), (90, 140, 99, 149, "x")]
    assert _ids(items) == ["a", "b", "x", "c"]
    # A small checkbox beside a tall text box shares its row.
    assert _ids([(300, 120, 310, 130, "cb"), (72, 100, 280, 160, "notes")]) == ["notes", "cb"]
    # The next line down is a new row, even when it starts further left.
    assert _ids([(300, 100, 400, 114, "top-right"), (40, 130, 120, 144, "next-left")]) == ["top-right", "next-left"]
    # Same spot: the order they came in.
    assert _ids([(72, 100, 82, 110, "first"), (72, 100, 82, 110, "second")]) == ["first", "second"]
    # Strings, None and swapped corners.
    assert _ids([("200", "100", "100", "110", "r"), (None, 100, 50, 110, "l"), (10, 300, 20, 290, "low")]) == ["l", "r", "low"]
    assert fo.row_order([]) == [] and fo.ordered_html([]) == ""
    assert fo.ordered_html([(200, 100, 210, 110, "<b2>"), (72, 100, 82, 110, "<b1>")]) == "<b1><b2>"


def _weasy_pdf(inputs, tabs=True):
    """A one-page tagged PDF with absolutely placed text inputs, in the DOM order given."""
    from weasyprint import HTML
    body = "".join(
        f'<input type="text" name="{n}" title="{n}" aria-label="{n}" '
        f'style="position:absolute; left:{x}pt; top:{y}pt; width:100pt; height:14pt;" />'
        for n, x, y in inputs)
    html = f'<!DOCTYPE html><html lang="en"><head><title>t</title></head><body><h1>Form</h1><div style="position:relative">{body}</div></body></html>'
    path = tempfile.mktemp(suffix=".pdf")
    HTML(string=html).write_pdf(path, pdf_variant="pdf/ua-1", pdf_forms=True)
    # WeasyPrint sets /Tabs /S on a page with fields itself; take it away to test the report.
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        for page in pdf.pages:
            if tabs:
                page.obj.Tabs = pikepdf.Name.S
            elif "/Tabs" in page.obj:
                del page.obj["/Tabs"]
        pdf.save(path)
    return path


def test_check_reports_out_of_order_and_missing_tabs():
    good = _weasy_pdf([("first", 72, 100), ("second", 72, 200)])
    r = fo.check_field_order(good)
    assert r == {"fields": 2, "pages": 1, "outOfOrderPages": [], "noTabsPages": []}, r
    bad = _weasy_pdf([("lower", 72, 200), ("upper", 72, 100)], tabs=False)
    r = fo.check_field_order(bad)
    assert r["fields"] == 2 and r["outOfOrderPages"] == [1] and r["noTabsPages"] == [1], r
    plain = tempfile.mktemp(suffix=".pdf")
    doc = fitz.open(); doc.new_page(); doc.save(plain)
    assert fo.check_field_order(plain) == {"fields": 0, "pages": 0, "outOfOrderPages": [], "noTabsPages": []}
    junk = tempfile.mktemp(suffix=".pdf")
    open(junk, "wb").write(b"not a pdf")
    assert "error" in fo.check_field_order(junk)


def _tagged_tops(pdf_bytes, page_no=0):
    """Field tops on one page, in tag order (first tag of each field: pdfua_repair adds a second <Form> per
    widget under <Document>, in the same order)."""
    path = tempfile.mktemp(suffix=".pdf")
    open(path, "wb").write(pdf_bytes)
    tops, seen = [], set()
    with pikepdf.open(path) as pdf:
        page = pdf.pages[page_no].obj
        h = float(page.MediaBox[3])
        on_page = {a.objgen for a in page.get("/Annots", []) if a.get("/Subtype") == "/Widget"}

        def visit(node, in_form):
            if isinstance(node, pikepdf.Array):
                for k in node:
                    visit(k, in_form)
                return
            if not isinstance(node, pikepdf.Dictionary):
                return
            if node.get("/Type") == "/OBJR":
                obj = node.get("/Obj")
                if in_form and obj is not None and obj.objgen in on_page and obj.objgen not in seen:
                    seen.add(obj.objgen)
                    tops.append(round(h - float(max(obj.Rect[1], obj.Rect[3])), 1))
                return
            k = node.get("/K")
            if k is not None:
                visit(k, in_form or node.get("/S") == "/Form")
        visit(pdf.Root.StructTreeRoot.get("/K"), False)
    return tops, fo.check_field_order(path)


def _build(original: bytes, forms_json: str = "{}"):
    import types
    from fastapi.testclient import TestClient
    os.environ.pop("SUPABASE_URL", None); os.environ.pop("SUPABASE_KEY", None)
    os.environ.pop("PDF_ENGINE_SECRET", None)
    sys.modules.setdefault("commonforms", types.SimpleNamespace(prepare_form=lambda *a, **k: None))
    import main
    html = '<section aria-label="Page 0" data-page="0"><h1>Form</h1><p>Text version.</p></section>'
    r = TestClient(main.app, raise_server_exceptions=False).post(
        "/build",
        data={"html_content": html, "corrected_forms_json": forms_json, "document_title": "Order form", "guide_style": "v2"},
        files={"original_pdf": ("orig.pdf", original, "application/pdf")},
    )
    assert r.status_code == 200, (r.status_code, r.text[:300])
    return r


def _printed_box(page, y, text):
    page.draw_rect(fitz.Rect(72, y, 82, y + 10), color=(0, 0, 0), width=0.8)
    page.insert_text((88, y + 9), text, fontsize=10)


def test_build_mixes_native_fields_and_printed_boxes_by_position():
    try:
        import fastapi  # noqa: F401
    except ImportError:
        print("  (FastAPI not installed; build check skipped)")
        return
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _printed_box(page, 100, "Morning")
    page.insert_text((72, 209), "Your name", fontsize=10)
    w = fitz.Widget()
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.field_name = "name"
    w.rect = fitz.Rect(140, 198, 340, 212)
    page.add_widget(w)
    _printed_box(page, 300, "Evening")
    r = _build(doc.tobytes())
    tops, report = _tagged_tops(r.content)
    assert len(tops) == 3 and tops == sorted(tops), tops  # the old order was 198 (own field), then 100, 300
    assert report["outOfOrderPages"] == [] and report["noTabsPages"] == [] and report["fields"] == 3, report
    assert r.headers.get("X-Form-Order"), "the build reports its field order"


def test_build_mixes_ai_boxes_and_printed_boxes_by_position():
    try:
        import fastapi  # noqa: F401
    except ImportError:
        print("  (FastAPI not installed; build check skipped)")
        return
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _printed_box(page, 100, "Agree")
    page.insert_text((72, 309), "Signature", fontsize=10)
    forms = '{"0": [{"x0": 140, "y0": 298, "x1": 340, "y1": 314, "type": 7, "name": "signature"}]}'
    tops, report = _tagged_tops(_build(doc.tobytes(), forms).content)
    assert len(tops) == 2 and tops == sorted(tops), tops
    assert report["outOfOrderPages"] == [], report


if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print(f"ok: {name}")
            except Exception as e:
                fails += 1; print(f"FAIL: {name}: {e!r}")
    print(f"\n{'ALL' if not fails else fails} field_order tests {'passed' if not fails else 'FAILED'}")
    sys.exit(1 if fails else 0)
