import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from visual_links import internal_visual_page, LINK_GOTO, LINK_NAMED

N = 51  # visual pages rendered


def test_explicit_goto_in_range():
    assert internal_visual_page({"kind": LINK_GOTO, "page": 3}, N) == 3


def test_named_destination_resolved():
    # Word/Acrobat internal hyperlinks: NAMED kind, PyMuPDF resolved the page.
    assert internal_visual_page({"kind": LINK_NAMED, "page": 0, "nameddest": "_Toc1"}, N) == 0
    assert internal_visual_page({"kind": LINK_NAMED, "page": 50, "nameddest": "menu"}, N) == 50


def test_named_destination_unresolved_is_skipped():
    assert internal_visual_page({"kind": LINK_NAMED, "page": None, "nameddest": "gone"}, N) is None
    assert internal_visual_page({"kind": LINK_NAMED, "nameddest": "gone"}, N) is None


def test_out_of_range_is_skipped():
    assert internal_visual_page({"kind": LINK_GOTO, "page": 51}, N) is None
    assert internal_visual_page({"kind": LINK_GOTO, "page": -1}, N) is None


def test_url_and_other_kinds_are_not_internal():
    assert internal_visual_page({"kind": 2, "uri": "https://x.example"}, N) is None   # LINK_URI
    assert internal_visual_page({"kind": 5, "page": 1, "file": "o.pdf"}, N) is None  # LINK_GOTOR
    assert internal_visual_page({"kind": 3, "file": "a.exe"}, N) is None              # LINK_LAUNCH
    assert internal_visual_page({"kind": LINK_GOTO, "page": True}, N) is None        # bool is not a page


def test_constants_match_pymupdf_when_available():
    try:
        import fitz
    except ImportError:
        print("  (PyMuPDF not installed; constant check skipped)")
        return
    assert LINK_GOTO == fitz.LINK_GOTO and LINK_NAMED == fitz.LINK_NAMED


def test_word_style_named_dest_pdf_end_to_end():
    """A real PDF whose internal links are NAMED destinations (Word style)
    must yield a visual-page target for each of them."""
    try:
        import fitz, pikepdf
        from pikepdf import Pdf, Dictionary, Name, Array, String
    except ImportError:
        print("  (PyMuPDF/pikepdf not installed; end-to-end case skipped)")
        return
    import tempfile
    pdf = Pdf.new()
    for _ in range(3):
        pdf.add_blank_page(page_size=(300, 300))
    p1, p2 = pdf.pages[1].obj, pdf.pages[2].obj
    pdf.Root.Names = pdf.make_indirect(Dictionary(Dests=pdf.make_indirect(Dictionary(
        Names=Array([String("menu"), Array([p2, Name("/Fit")]), String("sec"), Array([p1, Name("/Fit")])])))))
    def link(rect, **kw):
        return pdf.make_indirect(Dictionary(Type=Name("/Annot"), Subtype=Name("/Link"), Rect=Array(rect), Border=Array([0, 0, 0]), **kw))
    pdf.pages[0].obj.Annots = Array([
        link([10, 10, 100, 40], Dest=String("menu")),                                   # /Dest name  (Word)
        link([10, 50, 100, 80], A=Dictionary(S=Name("/GoTo"), D=String("sec"))),        # GoTo name   (Acrobat)
        link([10, 90, 100, 120], A=Dictionary(S=Name("/GoTo"), D=String("missing"))),   # unresolvable
        link([10, 130, 100, 160], A=Dictionary(S=Name("/URI"), URI=String("https://x.example"))),
    ])
    path = os.path.join(tempfile.mkdtemp(), "named.pdf")
    pdf.save(path)
    links = fitz.open(path)[0].get_links()
    got = [internal_visual_page(L, 3) for L in links]
    assert got == [2, 1, None, None], got


if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print(f"ok: {name}")
            except Exception as e:
                fails += 1; print(f"FAIL: {name}: {e!r}")
    print(f"\n{'ALL' if not fails else fails} visual_links tests {'passed' if not fails else 'FAILED'}")
    sys.exit(1 if fails else 0)
