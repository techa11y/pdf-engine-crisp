"""Carry HTML ``lang`` attributes into the PDF tag tree (WCAG 3.1.2 Language of Parts).

WeasyPrint 70 writes the document language (catalog /Lang, from ``<html lang>``)
but ignores ``lang`` on any other element, so a Spanish paragraph inside an
English document was announced in English. ``install()`` wraps WeasyPrint's
private tag-tree builder: when a box's own element carries a ``lang`` that differs
from the root ``<html lang>`` (compared by language subtag, so ``en`` inside an
``en-US`` document is left alone), the structure element made for it gets ``/Lang``.
Documents with no passage in another language are byte-for-byte unchanged.

The wrapper only adds a key to elements WeasyPrint already built; it never adds,
removes or reorders elements, so the tag tree and MCIDs are untouched. It is
installed only on the WeasyPrint version it was written against (70.x); on any
other version it logs and does nothing, so the engine keeps working.
The same file lives in pdf-engine-crisp and pdf-enginev2; keep them identical.
"""
import logging

logger = logging.getLogger(__name__)
_INSTALLED = False


def _primary(lang):
    """Language subtag only: en-US and en-GB are both English."""
    return (lang or "").strip().lower().replace("_", "-").split("-")[0]


def _document_lang(pdf):
    """The document language WeasyPrint already put in the catalog (from <html lang>).

    WeasyPrint 70's HTML tree is xml.etree (no getroottree), so the root element
    cannot be reached from a box; the catalog /Lang is set before the tags are built.
    """
    try:
        value = pdf.catalog.get("Lang")
    except Exception:
        return None
    if value is None:
        return None
    return getattr(value, "string", None) or str(value).strip("()")


def install():
    """Idempotently wrap weasyprint.pdf.tags._build_box_tree. Returns True when active."""
    global _INSTALLED
    if _INSTALLED:
        return True
    try:
        import pydyf
        import weasyprint
        from weasyprint.pdf import tags as wp_tags
    except Exception as e:  # pragma: no cover - engine always has WeasyPrint
        logger.warning("lang_tags: WeasyPrint not importable (%s); passage languages not tagged", e)
        return False
    if not str(getattr(weasyprint, "__version__", "")).startswith("70.") or not hasattr(wp_tags, "_build_box_tree"):
        logger.warning("lang_tags: unsupported WeasyPrint %s; passage languages not tagged",
                       getattr(weasyprint, "__version__", "?"))
        return False

    original = wp_tags._build_box_tree

    def _build_box_tree(box, parent, pdf, *args, **kwargs):
        inner = getattr(box, "_box", box)  # AbsolutePlaceholder unwraps the same way
        element = getattr(inner, "element", None)
        lang = None
        if element is not None and getattr(inner, "element_tag", None) not in ("html", "body"):
            own = element.get("lang") if hasattr(element, "get") else None
            if own and own.strip() and _primary(own) != _primary(_document_lang(pdf)):
                lang = own.strip()
        for struct in original(box, parent, pdf, *args, **kwargs):
            if lang is not None:
                try:
                    if struct.get("P") == parent.reference and "Lang" not in struct:
                        struct["Lang"] = pydyf.String(lang)
                except Exception:
                    pass
            yield struct

    wp_tags._build_box_tree = _build_box_tree
    _INSTALLED = True
    return True
