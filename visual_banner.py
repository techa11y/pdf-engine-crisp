"""Layout of the guide_style="v2" banner on the visual pages of /build.

The v2 guide draws a one-line banner across the top of every visual page
("Remediated by MediaA11y | Visual page N of M | ..."). It used to be painted on
top of the full-page image, so any original whose content reaches the top edge
(browser "Print to PDF" exports of Google Docs, flyers, scans) lost its first
line behind it.

`banner_layout` reserves a strip for the banner and fits the page image, and the
link and form-field overlays drawn over it, into the rest of the page: scaled
uniformly, centred horizontally, page size unchanged. On Letter the strip is
22 pt and the page is drawn at 97.2 %.
"""
import math
from typing import NamedTuple

BANNER_PT = 22.0           # strip height on ordinary pages
BANNER_MAX_FRACTION = 0.08  # never more than 8 % of a very short page
BANNER_FONT_PT = 9.0
BANNER_TEXT_EM = 54.0      # banner text width in em (~51 em measured, room for 2-digit page numbers)
BANNER_PAD_PT = 8.0        # horizontal padding on each side


class BannerLayout(NamedTuple):
    band: float      # height of the banner strip, pt
    scale: float     # factor applied to the page image and its overlays
    offset_x: float  # left offset that centres the scaled page, pt
    font_pt: float   # banner font size, pt (shrinks on narrow pages so it stays one line)


def banner_layout(width_pt: float, height_pt: float) -> BannerLayout:
    band = round(min(BANNER_PT, height_pt * BANNER_MAX_FRACTION), 2)
    scale = (height_pt - band) / height_pt
    offset_x = round(width_pt * (1 - scale) / 2, 3)
    font = min(BANNER_FONT_PT, (width_pt - 2 * BANNER_PAD_PT) / BANNER_TEXT_EM, band * 0.45)
    return BannerLayout(band, round(scale, 6), offset_x, max(math.floor(font * 100) / 100, 1.0))
