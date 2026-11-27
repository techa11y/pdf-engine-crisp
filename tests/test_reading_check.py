"""Automatic keyboard and screen-reader checks (reading_check.py, checklist 5.2 / 5.3 / 5.4).

Rules under test:
- keyboard: links and form fields are counted (a radio group counts once); an annotation missing from the structure
  tree is reported with its page; a page with annotations but no /Tabs /S is reported;
- reader: language, title and DisplayDocTitle; a skipped heading level; images with a description, without one, and
  with a description that is a file name or a placeholder word; tables with and without header cells; a list whose
  children are not list items;
- it never raises (a broken file is an `error`, not an exception) and it reports page numbers, never text;
- through /build, the report rides on the response as X-Reading-Check.
"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fitz
import pikepdf
import reading_check as rc


def _weasy(body, lang="en", title="Reading check", tabs=True):
    from weasyprint import HTML
    html = (f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8"><title>{title}</title></head>'
            f'<body>{body}</body></html>')
    path = tempfile.mktemp(suffix=".pdf")
    HTML(string=html).write_pdf(path, pdf_variant="pdf/ua-1", pdf_forms=True)
    if not tabs:
        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            for page in pdf.pages:
                if "/Tabs" in page.obj:
                    del page.obj["/Tabs"]
            pdf.save(path)
    return path


PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def test_a_clean_document():
    path = _weasy(
        '<h1>Quartzlake</h1><h2>Part</h2><p>Text with <a href="https://example.org/a">a link</a>.</p>'
        f'<img src="{PNG}" alt="Cobaltfern square" style="width:20px;height:20px">'
        '<table><tr><th>Day</th><th>Time</th></tr><tr><td>Mon</td><td>9</td></tr></table>'
        '<ul><li>one</li><li>two</li></ul>'
        '<form><label>Name <input type="text" name="name"></label>'
        '<label><input type="radio" name="c" value="a"> A</label><label><input type="radio" name="c" value="b"> B</label></form>')
    r = rc.check_reading(path)
    kb, rd = r["keyboard"], r["reader"]
    assert "error" not in r and r["timeUp"] is False, r
    assert kb["links"] == 1 and kb["untaggedLinks"] == 0 and kb["untaggedFields"] == 0, kb
    assert kb["fields"] == 2, kb  # the text box and ONE radio group
    assert kb["noTabsPages"] == [], kb
    assert rd["lang"] and rd["title"] and rd["displayDocTitle"], rd
    assert rd["headings"] == 2 and rd["headingSkips"] == 0, rd
    assert rd["images"] == 1 and rd["imagesDescribed"] == 1 and rd["placeholderDescriptionPages"] == [], rd
    assert rd["tables"] == 1 and rd["tablesWithHeaders"] == 1 and rd["tablesWithoutHeadersPages"] == [], rd
    assert rd["lists"] == 1 and rd["listsMalformed"] == 0, rd
    assert "Quartzlake" not in json.dumps(r) and "Cobaltfern" not in json.dumps(r), "never the document's words"


def test_things_worth_a_look_are_found_with_their_page():
    path = _weasy(
        '<h1>Title</h1><h3>Skipped a level</h3>'
        f'<img src="{PNG}" alt="IMG_1234.jpg" style="width:20px;height:20px">'
        f'<img src="{PNG}" alt="image" style="width:20px;height:20px">'
        f'<img src="{PNG}" style="width:20px;height:20px">'
        f'<div style="page-break-before:always"></div><table><tr><td>a</td><td>b</td></tr></table>', tabs=False)
    rd = rc.check_reading(path)["reader"]
    assert rd["headingSkips"] == 1 and rd["headingSkipPages"] == [1], rd
    assert rd["placeholderDescriptionPages"] == [1], rd
    assert rd["images"] == 3 and rd["imagesDescribed"] == 2 and rd["imagesWithoutDescriptionPages"] == [1], rd
    assert rd["tables"] == 1 and rd["tablesWithHeaders"] == 0 and rd["tablesWithoutHeadersPages"] == [2], rd


def test_untagged_link_and_missing_tab_order():
    path = _weasy('<h1>T</h1><p><a href="https://example.org">tagged</a></p>', tabs=False)
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        page = pdf.pages[0].obj
        stray = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link, Rect=[0, 0, 10, 10],
            A=pikepdf.Dictionary(S=pikepdf.Name.URI, URI=pikepdf.String("https://example.org/x"))))
        page.Annots.append(stray)
        if "/Tabs" in page:
            del page["/Tabs"]
        pdf.save(path)
    kb = rc.check_reading(path)["keyboard"]
    assert kb["links"] == 2 and kb["untaggedLinks"] == 1 and kb["untaggedPages"] == [1], kb
    assert kb["noTabsPages"] == [1], kb


def test_language_and_title_missing_are_reported():
    path = _weasy("<h1>T</h1><p>x</p>")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        if "/Lang" in pdf.Root:
            del pdf.Root["/Lang"]
        pdf.docinfo["/Title"] = ""
        if "/ViewerPreferences" in pdf.Root:
            del pdf.Root["/ViewerPreferences"]
        pdf.save(path)
    rd = rc.check_reading(path)["reader"]
    assert rd["lang"] is False and rd["title"] is False and rd["displayDocTitle"] is False, rd


def test_a_malformed_list_and_a_broken_file():
    path = _weasy("<h1>T</h1><ul><li>a</li></ul>")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        def walk(node):
            if isinstance(node, pikepdf.Array):
                for k in node:
                    walk(k)
                return
            if not isinstance(node, pikepdf.Dictionary):
                return
            if node.get("/S") == "/LI":
                node.S = pikepdf.Name.P  # a list child that is not a list item
                return
            if "/K" in node:
                walk(node.K)
        walk(pdf.Root.StructTreeRoot.K)
        pdf.save(path)
    assert rc.check_reading(path)["reader"]["listsMalformed"] == 1
    junk = tempfile.mktemp(suffix=".pdf")
    open(junk, "wb").write(b"not a pdf")
    r = rc.check_reading(junk)
    assert "error" in r and r["keyboard"]["links"] == 0


def test_build_reports_the_reading_check():
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
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Original page", fontsize=12)
    html = ('<section aria-label="Page 0" data-page="0"><h1>Reading</h1><p>See '
            '<a href="https://example.org/r">the rules</a>.</p>'
            '<table><tr><th>A</th></tr><tr><td>1</td></tr></table></section>')
    r = TestClient(main.app, raise_server_exceptions=False).post(
        "/build",
        data={"html_content": html, "corrected_forms_json": "{}", "document_title": "Reading check", "guide_style": "v2"},
        files={"original_pdf": ("orig.pdf", doc.tobytes(), "application/pdf")},
    )
    assert r.status_code == 200, (r.status_code, r.text[:300])
    report = json.loads(r.headers.get("X-Reading-Check") or "{}")
    assert report.get("version") == 1, report
    assert report["keyboard"]["links"] >= 1 and report["keyboard"]["untaggedLinks"] == 0, report
    assert report["reader"]["tables"] == 1 and report["reader"]["tablesWithHeaders"] == 1, report
    assert report["reader"]["lang"] and report["reader"]["title"] and report["reader"]["displayDocTitle"], report


if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print(f"ok: {name}")
            except Exception as e:
                fails += 1; print(f"FAIL: {name}: {e!r}")
    print(f"\n{'ALL' if not fails else fails} reading_check tests {'passed' if not fails else 'FAILED'}")
    sys.exit(1 if fails else 0)
