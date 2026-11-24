"""A fillable original keeps working fields on its picture pages (native_form_fields.py, 2026-11-24).

Rules under test (tests/fillable_fixture.py is the form: every field type, a read-only field, a push button, a
signature, a box drawn under a real checkbox, a printed box with no field, a rotated second page):
- every editable text, check box, radio button, combo box and list box is read at its on-screen spot (rotation
  applied), with its own name, its /TU, else the words beside it, its value, tick and choices;
- read-only fields, push buttons and signatures are left in the picture;
- names stay unique across the build (the accessible text's own fields first); a radio group keeps one name;
- the picture shows each field empty (ticks off, a filled field's text gone from its look);
- through /build: the picture pages get real fields with those names, labels, values and choices; the values
  are in the fields, never printed on the page; the drawn box under a real checkbox gets no second checkbox;
  the worker's AI boxes are ignored on a page that has the original's own fields.
"""
import io, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
import pikepdf
import native_form_fields as nff
from fillable_fixture import make_fillable


def fixture():
    return fitz.open(stream=make_fillable(), filetype="pdf")


def by_name(fields):
    out = {}
    for f in fields:
        out.setdefault(f.name, []).append(f)
    return out


def test_reads_every_editable_field_with_its_label_value_and_choices():
    doc = fixture()
    fields = by_name(nff.read_native_fields(doc[0]))
    assert set(fields) == {"full_name", "email", "notes", "agree", "newsletter", "contact", "shirt", "days"}, set(fields)
    one = {k: v[0] for k, v in fields.items()}
    assert [one[k].kind for k in ("full_name", "notes", "agree", "shirt", "days")] == ["text", "textarea", "checkbox", "select", "select"]
    # Labels: the original's /TU, else the words beside the field on the page.
    assert one["full_name"].label == "Full name"
    assert one["email"].label == "Email address"
    assert one["newsletter"].label == "Send me the newsletter"
    assert [f.label for f in fields["contact"]] == ["Preferred contact: Phone", "Preferred contact: Email", "Preferred contact: Post"]
    # Values, ticks and choices.
    assert (one["email"].value, one["notes"].value, one["full_name"].value) == ("jo@example.org", "Line one", "")
    assert one["agree"].checked and not one["newsletter"].checked and one["agree"].export == "Yes"
    assert [(f.export, f.checked) for f in fields["contact"]] == [("phone", False), ("email", True), ("post", False)]
    assert one["shirt"].options == [("s", "Small"), ("m", "Medium"), ("l", "Large")] and one["shirt"].selected == ["m"]
    assert one["days"].multiple and one["days"].selected == ["Mon", "Wed"] and not one["shirt"].multiple
    assert abs(one["full_name"].rect.x0 - 150) < 0.5 and abs(one["full_name"].rect.y0 - 96) < 0.5


def test_read_only_buttons_and_signatures_stay_in_the_picture():
    names = {f.name for f in nff.read_native_fields(fixture()[0])}
    assert not names & {"ref", "print", "sig"}, names


def test_rotated_page_field_at_its_on_screen_spot_named_by_its_words():
    (f,) = nff.read_native_fields(fixture()[1])
    assert f.name == "page2_note" and f.label == "Second page note", (f.name, f.label)
    assert [round(v) for v in f.rect] == [180, 96, 400, 114], f.rect


def test_names_unique_across_the_build_and_radio_groups_keep_one_name():
    names = nff.FieldNames('<input type="text" name="full_name"><select name=\'shirt\'></select>')
    assert names.take("full_name", 0, "text") == "full_name_2"
    assert names.take("shirt", 0, "select") == "shirt_2"
    assert names.take("contact", 0, "radio") == names.take("contact", 0, "radio") == "contact"
    assert names.take("contact", 1, "radio") == "contact_2"
    assert names.take("form1[0].Name[0]", 0, "text") == "form1[0]_Name[0]"
    assert set(names.radio_groups()) == {"contact", "contact_2"}
    assert nff.labelize("form1[0].firstName_2[0]") == "first Name 2"


def test_overlay_html_writes_no_values_into_the_page():
    fields = nff.read_native_fields(fixture()[0])
    html, values, n = nff.native_fields_overlay(fields, 0, nff.FieldNames())
    assert n == 10
    assert "jo@example.org" not in html and "Line one" not in html and "selected" not in html
    assert values == {"email": "jo@example.org", "notes": "Line one", "shirt": "m", "days": ["Mon", "Wed"]}, values
    assert 'type="checkbox" id="nf_0_4" name="agree" title="I agree to the terms"' in html
    assert html.count('type="radio"') == 3 and html.count('name="contact"') == 3 and 'value="email" checked' in html
    assert '<select id="nf_0_10" name="days" title="Days available" aria-label="Days available" multiple' in html
    assert '<option value="m">Medium</option>' in html
    tricky = nff.NativeField(kind="text", xref=0, name='a"b', label='Tom & "Jerry" <b>', rect=fitz.Rect(0, 0, 50, 10))
    html2, _, _ = nff.native_fields_overlay([tricky], 0, nff.FieldNames())
    assert 'name="a&quot;b" title="Tom &amp; &quot;Jerry&quot; &lt;b&gt;"' in html2, html2


def test_picture_shows_the_fields_empty():
    doc = fixture()
    page = doc[0]
    fields = nff.read_native_fields(page)
    agree = next(f for f in fields if f.name == "agree")
    email = next(f for f in fields if f.name == "email")
    ap = int(doc.xref_get_key(email.xref, "AP/N")[1].split()[0])
    assert b"jo@example.org" in doc.xref_stream(ap)
    page = nff.blank_for_raster(page, fields)
    assert doc.xref_get_key(agree.xref, "AS")[1] == "/Off"
    assert b"jo@example.org" not in doc.xref_stream(ap) and b" re" in doc.xref_stream(ap)  # its border stays
    # The read-only field keeps its value in the picture.
    ref = next(w for w in page.widgets() if w.field_name == "ref")
    assert b"REF-123" in doc.xref_stream(int(doc.xref_get_key(ref.xref, "AP/N")[1].split()[0]))


def test_pdf_strings():
    assert nff._pdf_strings("[(Mon) (We\\)d) <FEFF00E9>]") == ["Mon", "We)d", "é"]


def _content_text(data: bytes, page_no: int) -> str:
    """The page's own text, without the fields' looks (MuPDF draws field values into its text otherwise)."""
    pdf = pikepdf.open(io.BytesIO(data))
    for p in pdf.pages:
        if "/Annots" in p.obj:
            del p.obj["/Annots"]
    buf = io.BytesIO(); pdf.save(buf)
    return fitz.open(stream=buf.getvalue(), filetype="pdf")[page_no].get_text("text")


def test_build_keeps_the_originals_fields_working():
    try:
        import types
        from fastapi.testclient import TestClient
    except ImportError:
        print("  (FastAPI not installed; build check skipped)")
        return
    os.environ.pop("SUPABASE_URL", None); os.environ.pop("SUPABASE_KEY", None)
    sys.modules.setdefault("commonforms", types.SimpleNamespace(prepare_form=lambda *a, **k: None))
    import main
    html = ('<section aria-label="Page 1" data-page="0"><h1>Volunteer sign-up form</h1>'
            '<p><label>Full name <input type="text" name="full_name"></label></p></section>')
    ai_box = {"0": [{"x0": 400, "y0": 700, "x1": 500, "y1": 720, "type": 7, "name": "ai_guess"}]}
    r = TestClient(main.app, raise_server_exceptions=False).post(
        "/build",
        data={"html_content": html, "corrected_forms_json": json.dumps(ai_box), "document_title": "Volunteer form",
              "guide_style": "v2"},
        files={"original_pdf": ("orig.pdf", make_fillable(), "application/pdf")},
    )
    assert r.status_code == 200, (r.status_code, r.text[:300])
    out = fitz.open(stream=r.content, filetype="pdf")
    p1 = {w.field_name: w for w in out[0].widgets()}
    assert set(p1) == {"full_name_2", "email", "notes", "agree", "newsletter", "contact", "shirt", "days",
                       "visual_p1_cb1"}, sorted(p1)
    assert [w.field_name for w in out[1].widgets()] == ["page2_note"]
    assert p1["email"].field_label == "Email address" and p1["agree"].field_label == "I agree to the terms"
    assert p1["shirt"].field_type == fitz.PDF_WIDGET_TYPE_COMBOBOX and p1["days"].field_type == fitz.PDF_WIDGET_TYPE_LISTBOX
    radios = [w for w in out[0].widgets() if w.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON]
    assert len(radios) == 3 and {w.field_name for w in radios} == {"contact"}
    # The group is labelled with its question; each button with the question and its choice.
    group = int(out.xref_get_key(radios[0].xref, "Parent")[1].split()[0])
    assert out.xref_get_key(group, "TU")[1] == "Preferred contact"
    assert [out.xref_get_key(w.xref, "TU")[1] for w in radios] == [
        "Preferred contact: Phone", "Preferred contact: Email", "Preferred contact: Post"]
    # Values and ticks are in the fields...
    get = lambda name, key="V": out.xref_get_key(p1[name].xref, key)[1]
    assert (get("email"), get("notes"), get("shirt"), get("days")) == ("jo@example.org", "Line one", "m", "[(Mon)(Wed)]")
    assert get("agree", "AS") == "/on" and get("newsletter", "AS") == "/Off"
    assert [out.xref_get_key(w.xref, "AS")[1] for w in radios] == ["/Off", "/1", "/Off"]
    # ...and never printed on the page.
    text = _content_text(r.content, 0)
    assert "jo@example.org" not in text and "Line one" not in text and "Medium" not in text, text
    # The box drawn under the agree checkbox gets no second checkbox; the printed box with no field gets one.
    agree, extra = p1["agree"].rect, p1["visual_p1_cb1"].rect
    assert not agree.intersects(extra) and p1["visual_p1_cb1"].field_label == "Bring a friend"
    # The worker's AI box is ignored on a page with the original's own fields.
    assert "ai_guess" not in p1


if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print(f"ok: {name}")
            except Exception as e:
                fails += 1; print(f"FAIL: {name}: {e!r}")
    print(f"\n{'ALL' if not fails else fails} native_form_fields tests {'passed' if not fails else 'FAILED'}")
    sys.exit(1 if fails else 0)
