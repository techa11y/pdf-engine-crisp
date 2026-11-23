# Bundled fonts

`NotoEmoji-VariableFont_wght.ttf`: monochrome Noto Emoji (SIL Open Font License 1.1, `OFL.txt`), from
google/fonts `ofl/notoemoji/NotoEmoji[wght].ttf`, fetched 2026-11-23,
sha256 `de6c18832938afc99caf132b39d6a30a19bac7f2e812e28db2535b4608d27551`.

Why: the image has no emoji font, so WeasyPrint printed emoji (🍽️ 🍝 🌮 in RJUSD's "Titan Student
Bulletin") as the `.notdef` glyph with no Unicode mapping, and veraPDF PDF/UA-1 failed 7.21.7-1 and
7.21.8-1. The Dockerfile installs this folder into fontconfig; Pango falls back to it on its own for
any character the text font lacks, so no CSS change is needed, and the PDF text keeps the real emoji
(a screen reader announces "spaghetti", "taco"). A color emoji font (Noto Color Emoji, CBDT) still
fails veraPDF 7.21.5 (glyph widths), so it must stay monochrome. Test: `tests/test_emoji_font.py`.
