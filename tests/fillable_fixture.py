#!/usr/bin/env python3
"""A fillable test form, built from scratch (no customer data), for native_form_fields.py's tests.

make_fillable(path=None) -> bytes. Page 1 (letter, portrait):
- text "full_name" (TU "Full name", empty), text "email" (no TU, words "Email address" to its left,
  value "jo@example.org"), multi-line "notes" (TU "Notes", value "Line one");
- checkbox "agree" (TU "I agree to the terms", checked, on state "Yes") with a square DRAWN under it,
  checkbox "newsletter" (no TU, words "Send me the newsletter" to its right, unchecked);
- radio group "contact" (TU "Preferred contact"; phone / email / post, "email" chosen);
- combo box "shirt" (TU "T-shirt size"; s/Small m/Medium l/Large, "m" chosen);
- multi-select list "days" (TU "Days available"; Mon Tue Wed, Mon + Wed chosen);
- read-only text "ref" (value "REF-123"), push button "print", signature "sig": never overlaid;
- a square drawn with the words "Bring a friend" and no field (a printed box: Layer 3b's job).
Page 2 (/Rotate 90, drawn sideways so it reads upright on screen, as a scanned landscape page is): text
"page2_note" (no TU) right of the words "Second page note"; on screen the words sit at (72, 100) and the
field at (180, 96)-(400, 114).
"""
import io
import sys

import pikepdf
from pikepdf import Array, Dictionary, Name, Pdf, Stream, String

H = 792.0


def _box(x0, top, x1, bottom):
    """Top-left coordinates (as PyMuPDF shows them) -> a PDF rectangle."""
    return Array([x0, H - bottom, x1, H - top])


def make_fillable(path=None) -> bytes:
    pdf = Pdf.new()
    helv = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica,
                                        Encoding=Name.WinAnsiEncoding))
    zadb = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.ZapfDingbats))

    def ap(w, h, ops):
        s = Stream(pdf, ops.encode("latin-1"))
        s.Type = Name.XObject
        s.Subtype = Name.Form
        s.BBox = Array([0, 0, w, h])
        s.Resources = Dictionary(Font=Dictionary(Helv=helv, ZaDb=zadb))
        return pdf.make_indirect(s)

    def frame(w, h, inner=""):
        return ap(w, h, f"0 G 0.8 w 0.4 0.4 {w - 0.8} {h - 0.8} re S {inner}")

    def text_ap(w, h, text):
        inner = f"BT /Helv 10 Tf 0 g 2 {h / 2 - 3.5:.1f} Td ({text}) Tj ET" if text else ""
        return frame(w, h, inner)

    fields = []

    def page_with(content, rotate=0):
        cs = pdf.make_indirect(Stream(pdf, content.encode("latin-1")))
        p = Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]), Contents=cs, Annots=Array(),
                       Resources=Dictionary(Font=Dictionary(F1=helv)))
        if rotate:
            p.Rotate = rotate
        pdf.pages.append(pikepdf.Page(p))
        return pdf.pages[-1].obj

    def label(x, top, text, size=10):
        return f"BT /F1 {size} Tf {x} {H - top - size * 0.8:.1f} Td ({text}) Tj ET\n"

    content = label(72, 60, "Volunteer sign-up form", 16)
    content += label(72, 100, "Full name:") + label(72, 130, "Email address") + label(72, 160, "Notes")
    content += label(92, 241, "I agree to the terms")
    content += "0 G 1 w 72 539 10 10 re S\n"  # the square drawn UNDER the agree checkbox (top 243)
    content += label(92, 271, "Send me the newsletter")
    content += label(72, 300, "Preferred contact")
    for n, word in enumerate(("Phone", "Email", "Post")):
        content += label(92, 321 + n * 20, word)
    content += label(72, 400, "T-shirt size") + label(72, 440, "Days available")
    content += label(72, 520, "Reference") + label(92, 551, "Bring a friend")
    content += "0 G 1 w 72 231 10 10 re S\n"  # a printed box with no field (top 551)
    page1 = page_with(content)

    def widget(page, rect, **kw):
        d = Dictionary(Type=Name.Annot, Subtype=Name.Widget, Rect=rect, F=4, P=page, **kw)
        ref = pdf.make_indirect(d)
        page.Annots.append(ref)
        return ref

    def field(page, rect, **kw):
        ref = widget(page, rect, **kw)
        fields.append(ref)
        return ref

    da = String("/Helv 10 Tf 0 g")
    field(page1, _box(150, 96, 400, 114), FT=Name.Tx, T=String("full_name"), TU=String("Full name"), DA=da,
          V=String(""), AP=Dictionary(N=text_ap(250, 18, "")))
    field(page1, _box(150, 126, 400, 144), FT=Name.Tx, T=String("email"), DA=da, V=String("jo@example.org"),
          AP=Dictionary(N=text_ap(250, 18, "jo@example.org")))
    field(page1, _box(150, 156, 400, 196), FT=Name.Tx, Ff=4096, T=String("notes"), TU=String("Notes"), DA=da,
          V=String("Line one"), AP=Dictionary(N=frame(250, 40, "BT /Helv 10 Tf 0 g 2 28 Td (Line one) Tj ET")))

    def check_aps(w, h, on):
        tick = f"BT /ZaDb {h - 2} Tf 0 g 1.5 1.5 Td (4) Tj ET"
        return Dictionary(N=Dictionary({f"/{on}": frame(w, h, tick), "/Off": frame(w, h)}))

    field(page1, _box(72, 243, 82, 253), FT=Name.Btn, T=String("agree"), TU=String("I agree to the terms"),
          V=Name.Yes, AS=Name.Yes, AP=check_aps(10, 10, "Yes"))
    field(page1, _box(72, 273, 82, 283), FT=Name.Btn, T=String("newsletter"), V=Name.Off, AS=Name.Off,
          AP=check_aps(10, 10, "Yes"))

    group = pdf.make_indirect(Dictionary(FT=Name.Btn, Ff=49152, T=String("contact"),
                                         TU=String("Preferred contact"), V=Name.email, Kids=Array()))
    fields.append(group)
    for n, state in enumerate(("phone", "email", "post")):
        kid = widget(page1, _box(72, 323 + n * 20, 82, 333 + n * 20), Parent=group,
                     AS=Name("/" + state) if state == "email" else Name.Off, AP=check_aps(10, 10, state))
        group.Kids.append(kid)

    opts = Array([Array([String(v), String(t)]) for v, t in (("s", "Small"), ("m", "Medium"), ("l", "Large"))])
    field(page1, _box(150, 396, 300, 414), FT=Name.Ch, Ff=131072, T=String("shirt"), TU=String("T-shirt size"),
          DA=da, Opt=opts, V=String("m"), AP=Dictionary(N=text_ap(150, 18, "Medium")))
    field(page1, _box(150, 436, 300, 486), FT=Name.Ch, Ff=2097152, T=String("days"), TU=String("Days available"),
          DA=da, Opt=Array([String("Mon"), String("Tue"), String("Wed")]), V=Array([String("Mon"), String("Wed")]),
          AP=Dictionary(N=frame(150, 50, "BT /Helv 10 Tf 0 g 2 38 Td (Mon) Tj 0 -14 Td (Tue) Tj 0 -14 Td (Wed) Tj ET")))
    field(page1, _box(150, 516, 300, 534), FT=Name.Tx, Ff=1, T=String("ref"), DA=da, V=String("REF-123"),
          AP=Dictionary(N=text_ap(150, 18, "REF-123")))
    field(page1, _box(320, 516, 380, 534), FT=Name.Btn, Ff=65536, T=String("print"), MK=Dictionary(CA=String("Print")),
          AP=Dictionary(N=text_ap(60, 18, "Print")))
    field(page1, _box(150, 600, 400, 640), FT=Name.Sig, T=String("sig"), AP=Dictionary(N=frame(250, 40)))

    # On screen (x', y') is (792 - y_down, x) of the unrotated page: text runs up the page in PDF space.
    page2 = page_with("BT /F1 10 Tf 0 1 -1 0 110 72 Tm (Second page note) Tj ET\n", rotate=90)
    field(page2, Array([96, 180, 114, 400]), FT=Name.Tx, T=String("page2_note"), DA=da, V=String(""),
          MK=Dictionary(R=90), AP=Dictionary(N=frame(18, 220)))

    pdf.Root.AcroForm = Dictionary(Fields=Array(fields), DA=da, NeedAppearances=False,
                                   DR=Dictionary(Font=Dictionary(Helv=helv, ZaDb=zadb)))
    buf = io.BytesIO()
    pdf.save(buf)
    data = buf.getvalue()
    if path:
        with open(path, "wb") as f:
            f.write(data)
    return data


if __name__ == "__main__":
    make_fillable(sys.argv[1] if len(sys.argv) > 1 else "fillable.pdf")
