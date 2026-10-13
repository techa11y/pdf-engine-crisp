"""Target selection for the link overlays drawn on the visual pages of /build.

PyMuPDF ``page.get_links()`` reports an in-document link in two shapes:

* ``LINK_GOTO``  -- an explicit destination (page + position);
* ``LINK_NAMED`` -- a NAMED destination. This is what Word / Acrobat exports
  use for every internal hyperlink (TOC entries, "Go to main screen", cross
  references). PyMuPDF still resolves it and fills in the 0-based target
  ``page``; an unresolvable name leaves ``page`` as ``None``.

Both must be reproduced on the visual pages. The constants are hard-coded so
this module and its test need no PyMuPDF import; ``tests/test_visual_links.py``
verifies them against the real library when it is installed.
"""

LINK_GOTO = 1
LINK_NAMED = 4


def internal_visual_page(link, visual_count):
    """Return the 0-based visual page an in-document *link* should jump to, or
    ``None`` when there is nothing in-document to point at (a URL link, an
    unresolved target, a GOTOR/LAUNCH link, or a target outside the rendered
    page range). The caller maps the index to the ``id="page_{n}"`` anchor
    every visual page carries.
    """
    if link.get("uri"):
        return None
    if link.get("kind") not in (LINK_GOTO, LINK_NAMED):
        return None
    page = link.get("page")
    if isinstance(page, bool) or not isinstance(page, int):
        return None
    if not 0 <= page < visual_count:
        return None
    return page
