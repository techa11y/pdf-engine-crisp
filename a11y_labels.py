"""Small, pure helpers for /build's document language and visual-page link labels.

* ``safe_lang`` validates the optional ``document_lang`` form field. The PDF's
  language (catalog /Lang and ``<html lang>``) used to be hard-coded to en-US,
  so a Spanish document was announced to screen readers as English (WCAG 3.1.1).
  Anything that is not a plausible BCP 47 tag falls back to en-US, so a bad value
  can never leave the PDF without a language (PDF/UA-1 needs one).
* ``visual_link_label`` names a link overlay on a visual page after where it goes.
  Every overlay used to be labelled just "Link" (WCAG 2.4.4 Link Purpose).

Kept free of PyMuPDF / WeasyPrint imports so tests/test_a11y_labels.py runs anywhere.
The same file lives in pdf-engine-crisp and pdf-enginev2; keep them identical.
"""
import re
from urllib.parse import unquote, urlparse

DEFAULT_LANG = "en-US"
_LANG_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}$")
_MAX_LABEL_PATH = 40


def safe_lang(value) -> str:
    """Return a normalised BCP 47 tag (``es``, ``en-US``, ``zh-Hant``), else en-US."""
    text = str(value or "").strip().replace("_", "-")
    if not _LANG_RE.match(text):
        return DEFAULT_LANG
    parts = text.split("-")
    out = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            out.append(part.upper())      # region: US, MX
        elif len(part) == 4 and part.isalpha():
            out.append(part.title())      # script: Hant
        else:
            out.append(part.lower())      # region number or variant: 419
    return "-".join(out)


def visual_link_label(href: str, target_page=None) -> str:
    """Accessible name for a link overlay on a visual page.

    ``target_page`` is the 0-based visual page for an in-document jump.
    """
    if target_page is not None:
        return f"Go to visual page {int(target_page) + 1}"
    href = (href or "").strip()
    lower = href.lower()
    if lower.startswith("mailto:"):
        return f"Email {unquote(href[7:]).split('?')[0]}" if len(href) > 7 else "Email link"
    if lower.startswith("tel:"):
        return f"Call {unquote(href[4:])}" if len(href) > 4 else "Phone link"
    parsed = urlparse(href if "://" in href else f"https://{href}")
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return "Link"
    path = unquote(parsed.path or "").rstrip("/")
    if len(path) > _MAX_LABEL_PATH:
        path = path[: _MAX_LABEL_PATH - 3] + "..."
    return f"Link to {host}{path}"
