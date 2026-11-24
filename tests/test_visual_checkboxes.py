"""Drawn checkboxes on the picture pages become real checkboxes (visual_checkboxes.py, 2026-11-24).

Rules under test:
- a small hollow square drawn as a path (stroked, or a filled ring), a box character in the text, or
  (on a scanned page) a hollow square in the pixels is found at its own spot;
- bullets (filled squares, hollow circles), table cells (too big), letters (O, 0, D), and a box
  character printed already ticked (☑: an answer) are not boxes to tick;
- a spot the original already has a real form field on is left alone; a page with too many is left alone;
- a box is named by the words beside it on its line, stopping at the next box; else "Checkbox n of m";
- the overlay is one real checkbox per box, at the box's points, with a unique name and an escaped label;
- through /build: the picture page gets one checkbox widget per printed box, named, and each ticks.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fitz
import visual_checkboxes as vc

DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def form_page(doc=None):
    """A digital form: three drawn boxes with words, a Yes/No row, and things that are not boxes."""
    doc = doc or fitz.open()
    page = doc.new_page(width=612, height=792)
    for n, (y, text) in enumerate(((100, "No School"), (130, "Water bottle in class"), (160, "Allow breaks"))):
        page.draw_rect(fitz.Rect(72, y, 82, y + 10), color=(0, 0, 0), width=0.8)
        page.insert_text((88, y + 9), text, fontsize=10)
    # A row of two choices: each name stops at the next box.
    page.draw_rect(fitz.Rect(72, 200, 82, 210), color=(0, 0, 0), width=0.8)
    page.insert_text((88, 209), "Yes", fontsize=10)
    page.draw_rect(fitz.Rect(120, 200, 130, 210), color=(0, 0, 0), width=0.8)
    page.insert_text((136, 209), "No", fontsize=10)
    # Not boxes: a filled bullet, a hollow circle bullet, a table cell, letters.
    page.draw_rect(fitz.Rect(72, 240, 80, 248), color=(0, 0, 0), fill=(0, 0, 0))
    page.draw_circle(fitz.Point(100, 244), 3, color=(0, 0, 0), width=0.8)
    page.draw_rect(fitz.Rect(72, 270, 172, 300), color=(0, 0, 0), width=0.8)
    page.insert_text((72, 340), "O 0 D o Q", fontsize=14)
    return doc, page


def test_vector_boxes_found_and_named():
    doc, page = form_page()
    boxes = vc.detect_checkboxes(page)
    assert len(boxes) == 5, [tuple(b) for b in boxes]
    assert vc.name_checkboxes(page, boxes, 1) == ["No School", "Water bottle in class", "Allow breaks", "Yes", "No"]
    assert all(abs(b.width - 10) < 1.5 and abs(b.height - 10) < 1.5 for b in boxes)


def test_box_characters_found_at_their_own_square():
    if not os.path.exists(DEJAVU):
        print("  (DejaVu Sans not installed; glyph check skipped)")
        return
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_font(fontname="dv", fontfile=DEJAVU)
    page.insert_text((72, 120), "☐ I agree to the terms", fontname="dv", fontsize=12)
    page.insert_text((72, 150), "☑ Already checked", fontname="dv", fontsize=12)  # an answer, not a box
    page.insert_text((72, 180), "☐​Academic", fontname="dv", fontsize=12)  # written with no space
    boxes = vc.detect_checkboxes(page)
    assert len(boxes) == 2, [tuple(b) for b in boxes]
    assert vc.name_checkboxes(page, boxes, 1) == ["I agree to the terms", "Academic"]
    for b, baseline in zip(boxes, (120, 180)):
        assert b.y1 <= baseline + 2 and b.y0 >= baseline - 13, tuple(b)  # the drawn square, not the em box


def test_scanned_page_found_in_pixels_with_plain_names():
    doc, page = form_page()
    pix = page.get_pixmap(dpi=150)
    scan = fitz.open()
    sp = scan.new_page(width=612, height=792)
    sp.insert_image(sp.rect, stream=pix.tobytes("png"))
    assert not sp.get_text("text").strip()
    boxes = vc.detect_checkboxes(sp)
    assert len(boxes) == 5, [tuple(b) for b in boxes]
    assert vc.name_checkboxes(sp, boxes, 2) == [f"Checkbox {n} of 5, visual page 2" for n in range(1, 6)]
    first = boxes[0]
    assert abs(first.x0 - 72) < 1.5 and abs(first.y0 - 100) < 1.5, tuple(first)


def test_no_raster_when_the_budget_is_spent():
    doc, page = form_page()
    scan = fitz.open()
    sp = scan.new_page(width=612, height=792)
    sp.insert_image(sp.rect, stream=page.get_pixmap(dpi=150).tobytes("png"))
    assert vc.detect_checkboxes(sp, allow_raster=False) == []


def test_a_real_form_field_is_left_alone():
    doc, page = form_page()
    w = fitz.Widget()
    w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    w.field_name = "already_a_field"
    w.rect = fitz.Rect(72, 100, 82, 110)
    page.add_widget(w)
    page = doc.reload_page(page)
    names = vc.name_checkboxes(page, vc.detect_checkboxes(page), 1)
    assert "No School" not in names and len(names) == 4, names


def test_filled_ring_box_counts_and_names_stop_at_the_next_label():
    """A box drawn as a filled outline (course-selection sheets), and a name that stops before the next
    field's label ("Part Time   Monthly Payroll Frequency")."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    ring = page.new_shape()
    ring.draw_rect(fitz.Rect(72, 100, 82, 110)); ring.draw_rect(fitz.Rect(73, 101, 81, 109))
    ring.finish(fill=(0.35, 0.35, 0.35), color=None, even_odd=True); ring.commit()
    page.insert_text((86, 109), "English 11 (203313)", fontsize=10)
    page.draw_rect(fitz.Rect(72, 140, 82, 150), color=(0, 0, 0), width=0.8)
    page.insert_text((86, 149), "Part Time", fontsize=10)
    page.insert_text((150, 149), "Monthly Payroll Frequency:", fontsize=10)
    boxes = vc.detect_checkboxes(page)
    assert len(boxes) == 2, [tuple(b) for b in boxes]
    assert vc.name_checkboxes(page, boxes, 1) == ["English 11 (203313)", "Part Time"]


def test_scanned_letters_and_qr_rings_are_not_boxes():
    """A box in pixels needs white space round it and an empty middle: a letter inside a word touches
    its neighbours; a QR code's corner ring holds a square and touches modules."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(72, 100, 82, 110), color=(0, 0, 0), width=0.8)  # a real box, alone
    # A QR-style finder: a ring with a filled square inside, next to dark modules.
    page.draw_rect(fitz.Rect(200, 100, 214, 114), color=(0, 0, 0), width=2)
    page.draw_rect(fitz.Rect(204, 104, 210, 110), color=(0, 0, 0), fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(216, 100, 222, 106), color=(0, 0, 0), fill=(0, 0, 0))
    # A box-like shape squeezed between letters, as in a blurry scanned word.
    page.insert_text((300, 110), "Su", fontsize=12)
    page.draw_rect(fitz.Rect(314, 101, 320, 109), color=(0, 0, 0), width=1)
    page.insert_text((321, 110), "scriber", fontsize=12)
    scan = fitz.open()
    sp = scan.new_page(width=612, height=792)
    sp.insert_image(sp.rect, stream=page.get_pixmap(dpi=150).tobytes("png"))
    boxes = vc.detect_checkboxes(sp)
    assert len(boxes) == 1 and abs(boxes[0].x0 - 72) < 1.5, [tuple(b) for b in boxes]


def test_too_many_boxes_is_not_a_form():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for row in range(16):
        for col in range(10):
            x, y = 40 + col * 50, 40 + row * 40
            page.draw_rect(fitz.Rect(x, y, x + 10, y + 10), color=(0, 0, 0), width=0.8)
    assert vc.detect_checkboxes(page) == []


def test_overlay_html():
    doc, page = form_page()
    html, count = vc.checkbox_overlay(page, 1)
    assert count == 5
    assert html.count('<input type="checkbox"') == 5
    assert 'name="visual_p2_cb1"' in html and 'name="visual_p2_cb5"' in html and 'id="vcb_1_5"' in html
    assert 'aria-label="No School"' in html and 'title="No School"' in html
    m = __import__("re").search(r'name="visual_p2_cb1"[^>]*left:([\d.]+)pt; top:([\d.]+)pt; width:([\d.]+)pt; height:([\d.]+)pt', html)
    assert m and all(abs(float(a) - b) < 1.5 for a, b in zip(m.groups(), (72, 100, 10, 10))), html[:300]
    doc2 = fitz.open()
    p2 = doc2.new_page(width=612, height=792)
    p2.draw_rect(fitz.Rect(72, 100, 82, 110), color=(0, 0, 0), width=0.8)
    p2.insert_text((88, 109), 'Tom & "Jerry" <b>', fontsize=10)
    html2, _ = vc.checkbox_overlay(p2, 0)
    assert 'aria-label="Tom &amp; &quot;Jerry&quot; &lt;b&gt;"' in html2, html2


def test_build_places_tickable_named_checkboxes():
    try:
        import types
        from fastapi.testclient import TestClient
    except ImportError:
        print("  (FastAPI not installed; build check skipped)")
        return
    os.environ.pop("SUPABASE_URL", None); os.environ.pop("SUPABASE_KEY", None)
    sys.modules.setdefault("commonforms", types.SimpleNamespace(prepare_form=lambda *a, **k: None))
    import main
    doc, _ = form_page()
    html = '<section aria-label="Page 0" data-page="0"><h1>Form</h1><p>Text version.</p></section>'
    r = TestClient(main.app, raise_server_exceptions=False).post(
        "/build",
        data={"html_content": html, "corrected_forms_json": "{}", "document_title": "Checkbox form", "guide_style": "v2"},
        files={"original_pdf": ("orig.pdf", doc.tobytes(), "application/pdf")},
    )
    assert r.status_code == 200, (r.status_code, r.text[:300])
    out = fitz.open(stream=r.content, filetype="pdf")
    boxes = [w for w in out[0].widgets() if w.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX]
    assert len(boxes) == 5, len(boxes)
    assert sorted(w.field_name for w in boxes) == [f"visual_p1_cb{n}" for n in range(1, 6)]
    assert {w.field_label for w in boxes} >= {"No School", "Yes", "No"}, [w.field_label for w in boxes]


if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print(f"ok: {name}")
            except Exception as e:
                fails += 1; print(f"FAIL: {name}: {e!r}")
    print(f"\n{'ALL' if not fails else fails} visual_checkboxes tests {'passed' if not fails else 'FAILED'}")
    sys.exit(1 if fails else 0)
