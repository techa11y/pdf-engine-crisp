"""The bundled emoji font (fonts/README.md): emoji must render as real glyphs with a Unicode mapping.

Without an emoji font WeasyPrint prints emoji as the .notdef glyph and veraPDF PDF/UA-1 fails
7.21.7-1 / 7.21.8-1 (RJUSD "Titan Student Bulletin", 2026-11-23). These tests check the font file
covers the emoji we have seen, that it is monochrome (a color font fails 7.21.5), and that a
WeasyPrint render with only DejaVu + this folder embeds it for the emoji.

Runnable with pytest, or directly: `python tests/test_emoji_font.py`.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, "fonts")
FONT = os.path.join(FONT_DIR, "NotoEmoji-VariableFont_wght.ttf")
DEJAVU = "/usr/share/fonts/truetype/dejavu"
# the Titan bulletin's food emoji, plus common ones in school documents
EMOJI = [0x1F37D, 0x1F35D, 0x1F32E, 0x1F959, 0x1F35A, 0x1F9C0, 0x1F4DE, 0x1F4C5, 0x2705, 0x1F600]


def test_font_covers_the_emoji_and_is_monochrome():
    from fontTools.ttLib import TTFont
    font = TTFont(FONT)
    cmap = font.getBestCmap()
    missing = [hex(cp) for cp in EMOJI if cp not in cmap]
    assert not missing, missing
    for color_table in ("CBDT", "CBLC", "sbix", "COLR", "SVG "):
        assert color_table not in font, f"{color_table}: a color emoji font fails veraPDF 7.21.5"


def test_render_embeds_the_emoji_font():
    if not os.path.isdir(DEJAVU):
        print("skip: no DejaVu here")
        return
    import pikepdf
    tmp = tempfile.mkdtemp()
    conf = os.path.join(tmp, "fonts.conf")
    with open(conf, "w") as f:
        f.write(f'<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
                f"<dir>{DEJAVU}</dir><dir>{FONT_DIR}</dir><cachedir>{tmp}/cache</cachedir></fontconfig>")
    out = os.path.join(tmp, "out.pdf")
    code = (
        "from weasyprint import HTML; import sys\n"
        "HTML(string='<html lang=\"en\"><head><title>t</title></head><body style=\"font-family:Arial,sans-serif\">"
        "<p>\\U0001F37D\\uFE0F Cafeteria \\U0001F35D Pasta \\U0001F32E Taco</p></body></html>')"
        ".write_pdf(sys.argv[1], pdf_variant='pdf/ua-1')\n"
    )
    import subprocess
    env = dict(os.environ, FONTCONFIG_FILE=conf)
    subprocess.run([sys.executable, "-c", code, out], check=True, env=env)
    names = set()
    with pikepdf.open(out) as pdf:
        for page in pdf.pages:
            for _, font in (page.Resources.get("/Font") or {}).items():
                names.add(str(font.get("/BaseFont", "")))
    assert any("notoemoji" in n.lower().replace("-", "") for n in names), names  # BaseFont is "Noto-Emoji"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok:", fn.__name__)
    print(f"\nALL {len(fns)} emoji font tests passed")
