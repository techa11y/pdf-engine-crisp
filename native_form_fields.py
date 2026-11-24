"""The original's own form fields stay working fields on its picture pages (team prompt 6, 2026-11-24).

WHY: the first pages of every remediated PDF are pictures of the original. A fillable original's fields were
lost there: the picture shows them but nothing can be typed or ticked, and the engine's form layer (Layer 3)
draws only what the worker sends, which today is never anything (the worker's payload has no coordinates).
The original's fields are known exactly from its own widgets, so they are read here, not guessed by an AI.

WHAT, for every editable text, check box, radio button, combo box and list box widget of the page:
- a real HTML field at the widget's own spot (page points, rotation applied, the same coordinates as the
  link and checkbox overlays), so WeasyPrint writes a real PDF field there;
- its own field name (a period becomes "_": PDF partial names may not hold one; a clash with a field already
  taken, in the accessible text or an earlier page, gets "_2", "_3"; a radio group keeps one name per page,
  and its buttons lose the repeated name WeasyPrint gives them, `settle_radio_names`);
- its label (/TU): the original's own /TU, else the words beside it on the page, else its name in words;
- its value, ticks and choices: check boxes and radio buttons by `checked` (WeasyPrint writes their state);
  text and choices AFTER WeasyPrint (`apply_field_values`), because WeasyPrint prints an <input>'s value
  into the page as well as into the field, so it would show twice and stay under what a user types;
- in the picture itself each such field is drawn empty (`blank_for_raster`, on the in-memory copy only):
  ticks off, and a filled field's text removed from its appearance, so nothing shows twice.
Push buttons, signatures, read-only and hidden fields are left as they are in the picture. A page with
fields takes them from here and ignores the worker's AI form boxes. Layer 3b (visual_checkboxes.py) already
leaves alone any printed box that holds one of the original's fields, so a spot never gets two fields.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field

import fitz

from visual_checkboxes import _clean

TEXT = fitz.PDF_WIDGET_TYPE_TEXT
CHECKBOX = fitz.PDF_WIDGET_TYPE_CHECKBOX
RADIO = fitz.PDF_WIDGET_TYPE_RADIOBUTTON
COMBO = fitz.PDF_WIDGET_TYPE_COMBOBOX
LISTBOX = fitz.PDF_WIDGET_TYPE_LISTBOX
KINDS = {TEXT, CHECKBOX, RADIO, COMBO, LISTBOX}

FF_READ_ONLY = 1
FF_MULTILINE = 1 << 12
FF_PASSWORD = 1 << 13
FF_MULTISELECT = 1 << 21
ANNOT_HIDDEN = 1 << 1
ANNOT_NOVIEW = 1 << 5
MAX_FIELDS_PER_PAGE = 500


@dataclass
class NativeField:
    kind: str  # text, textarea, password, checkbox, radio, select
    xref: int
    name: str  # the original's field name
    label: str
    rect: fitz.Rect  # on-screen page points
    value: str = ""
    checked: bool = False
    export: str = ""
    options: list = field(default_factory=list)  # [(export value, shown text)]
    selected: list = field(default_factory=list)
    multiple: bool = False
    maxlen: int = 0
    font_pt: float = 0.0
    has_off_look: bool = True
    group_label: str = ""  # a radio button's question ("Preferred contact"); its label adds the choice


# ---------------------------------------------------------------- reading the page

def _annot_flags(doc: "fitz.Document", xref: int) -> int:
    kind, val = doc.xref_get_key(xref, "F")
    try:
        return int(val) if kind == "int" else 0
    except ValueError:
        return 0


def _pdf_strings(src: str) -> list:
    """The strings in a PDF object's text ("(a)", "[(a) (b)]", "<FEFF0061>")."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == "(":
            depth, i, buf = 1, i + 1, []
            while i < n and depth:
                ch = src[i]
                if ch == "\\" and i + 1 < n:
                    nxt = src[i + 1]
                    buf.append({"n": "\n", "r": "\r", "t": "\t"}.get(nxt, nxt))
                    i += 2
                    continue
                depth += ch == "("
                depth -= ch == ")"
                if depth:
                    buf.append(ch)
                i += 1
            out.append("".join(buf))
        elif c == "<" and not src.startswith("<<", i):
            j = src.find(">", i)
            raw = bytes.fromhex(re.sub(r"\s", "", src[i + 1:j if j > 0 else n]) or "")
            out.append(raw[2:].decode("utf-16-be", "replace") if raw[:2] == b"\xfe\xff" else raw.decode("latin-1"))
            i = (j if j > 0 else n) + 1
        else:
            i += 1
    return out


def _selected(doc: "fitz.Document", xref: int) -> list:
    for key in ("V", "Parent/V"):
        kind, val = doc.xref_get_key(xref, key)
        if kind in ("string", "array"):
            return _pdf_strings(val) if kind == "array" or val.startswith(("(", "<")) else [val]
        if kind == "name":
            return [val.lstrip("/")]
    return []


def _screen_words(page: "fitz.Page") -> list:
    m = page.rotation_matrix
    out = []
    for w in page.get_text("words"):
        text = _clean(w[4])
        if text:
            out.append((fitz.Rect(w[:4]) * m, text))
    return out


def _same_line(word: "fitz.Rect", r: "fitz.Rect") -> bool:
    return min(word.y1, r.y1 + 2) - max(word.y0, r.y0 - 2) >= 0.5 * word.height


def _words_left(words: list, r: "fitz.Rect", others: list) -> str:
    line = sorted((w for w in words if _same_line(w[0], r) and w[0].x1 <= r.x0 + 1), key=lambda w: -w[0].x1)
    picked, edge = [], r.x0
    for rect, text in line:
        limit = 120 if not picked else max(3.0, 0.6 * rect.height)
        # Stop at another field between the words and this one (the previous field's own label ends there).
        if edge - rect.x1 > limit or any(o.x0 >= rect.x1 - 1 and o.x1 <= edge + 1 and _same_line(o, r) for o in others):
            break
        picked.append(text)
        edge = rect.x0
        if len(picked) >= 12:
            break
    return _clean(" ".join(reversed(picked)))


def _words_right(words: list, r: "fitz.Rect", others: list) -> str:
    stop = min((o.x0 for o in others if o.x0 >= r.x1 - 1 and _same_line(o, r)), default=1e9)
    line = sorted((w for w in words if _same_line(w[0], r) and w[0].x0 >= r.x1 - 1 and w[0].x0 < stop),
                  key=lambda w: w[0].x0)
    picked, edge = [], r.x1
    for rect, text in line:
        limit = 15 if not picked else max(3.0, 0.6 * rect.height)
        if rect.x0 - edge > limit:
            break
        picked.append(text)
        edge = rect.x1
        if len(picked) >= 12:
            break
    return _clean(" ".join(picked))


def _words_above(words: list, r: "fitz.Rect") -> str:
    above = [w for w in words if r.y0 - 16 <= w[0].y1 <= r.y0 + 1 and w[0].x1 > r.x0 - 4 and w[0].x0 < r.x1]
    return _clean(" ".join(t for _, t in sorted(above, key=lambda w: w[0].x0)[:12]))


def labelize(name: str) -> str:
    """A field name in words: "form1[0].first_name[0]" -> "first name"."""
    last = re.split(r"[.]", name or "")[-1]
    last = re.sub(r"\[\d+\]", "", last)
    last = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", last)
    return _clean(re.sub(r"[_\-]+", " ", last)) or "Form field"


def read_native_fields(page: "fitz.Page") -> list:
    """The page's editable fields, in on-screen points, with their labels, values and choices."""
    try:
        widgets = list(page.widgets() or [])
    except Exception:
        return []
    doc = page.parent
    m = page.rotation_matrix
    screen = page.rect
    words = None
    found = []
    rects = [fitz.Rect(w.rect) * m for w in widgets]
    for w, r in zip(widgets, rects):
        if w.field_type not in KINDS or (w.field_flags or 0) & FF_READ_ONLY:
            continue
        if _annot_flags(doc, w.xref) & (ANNOT_HIDDEN | ANNOT_NOVIEW):
            continue
        r = fitz.Rect(r).normalize()
        if r.width < 4 or r.height < 4 or (r & screen).is_empty:
            continue
        if words is None:
            words = _screen_words(page)
        others = [o for o in rects if o != r]
        name = w.field_name or ""
        tu = _clean(w.field_label or "")
        flags = w.field_flags or 0
        nf = NativeField(kind="text", xref=w.xref, name=name, label=tu, rect=r,
                         font_pt=float(w.text_fontsize or 0), maxlen=int(w.text_maxlen or 0))
        if w.field_type == TEXT:
            nf.kind = "textarea" if flags & FF_MULTILINE else "password" if flags & FF_PASSWORD else "text"
            nf.value = w.field_value if isinstance(w.field_value, str) else ""
            nf.label = tu or _words_left(words, r, others) or _words_above(words, r) or labelize(name)
        elif w.field_type in (CHECKBOX, RADIO):
            on = w.on_state()
            nf.export = str(on) if on not in (None, False, True, "", "Off") else "Yes"
            value = str(w.field_value) if w.field_value not in (None, False) else "Off"
            nf.checked = value not in ("", "Off", "False") and (w.field_type == CHECKBOX or value == nf.export)
            nf.has_off_look = doc.xref_get_key(w.xref, "AP/N/Off")[0] != "null"
            beside = _words_right(words, r, others) or _words_left(words, r, others)
            if w.field_type == CHECKBOX:
                nf.kind = "checkbox"
                nf.label = tu or beside or labelize(name)
            else:
                nf.kind = "radio"
                group, option = tu or labelize(name), beside or labelize(nf.export)
                nf.group_label = group
                nf.label = group if group == option else f"{group}: {option}"
        else:
            nf.kind = "select"
            nf.multiple = w.field_type == LISTBOX and bool(flags & FF_MULTISELECT)
            for opt in w.choice_values or []:
                if isinstance(opt, (list, tuple)) and len(opt) >= 2:
                    nf.options.append((str(opt[0]), str(opt[1])))
                else:
                    nf.options.append((str(opt), str(opt)))
            nf.selected = _selected(doc, w.xref)
            nf.label = tu or _words_left(words, r, others) or _words_above(words, r) or labelize(name)
        found.append(nf)
        if len(found) >= MAX_FIELDS_PER_PAGE:
            break
    return found


# ---------------------------------------------------------------- the picture

_TEXT_OBJECT = re.compile(rb"\bBT\b.*?\bET\b", re.S)


def blank_for_raster(page: "fitz.Page", fields: list) -> "fitz.Page":
    """Draw these fields empty in the picture (in-memory copy only). Returns the page to render.

    Check boxes and radio buttons show their off look; a text or choice field with a value loses the text of
    its appearance (its border and background stay); one whose appearance cannot be changed is hidden."""
    doc = page.parent
    for nf in fields:
        try:
            if nf.kind in ("checkbox", "radio"):
                doc.xref_set_key(nf.xref, "AS", "/Off")
                continue
            if not (nf.value or nf.selected):
                continue
            kind, val = doc.xref_get_key(nf.xref, "AP/N")
            ap = int(val.split()[0]) if kind == "xref" else 0
            if ap and doc.xref_is_stream(ap):
                doc.update_stream(ap, _TEXT_OBJECT.sub(b"", doc.xref_stream(ap) or b""))
            else:
                doc.xref_set_key(nf.xref, "F", str(_annot_flags(doc, nf.xref) | ANNOT_HIDDEN))
        except Exception:
            try:
                doc.xref_set_key(nf.xref, "F", str(_annot_flags(doc, nf.xref) | ANNOT_HIDDEN))
            except Exception:
                pass
    return doc.reload_page(page)


# ---------------------------------------------------------------- names

_HTML_FIELD_NAME = re.compile(r"<(?:input|select|textarea|button)\b[^>]*?\bname\s*=\s*([\"'])(.*?)\1", re.I | re.S)


class FieldNames:
    """Unique PDF field names for the whole build: the accessible text's own fields are taken first."""

    def __init__(self, html_content: str = ""):
        self.used = {_html.unescape(m.group(2)) for m in _HTML_FIELD_NAME.finditer(html_content or "")}
        self.radio = {}
        self.radio_labels = {}

    def take(self, name: str, page_index: int, kind: str) -> str:
        base = re.sub(r"[\x00-\x1f]", "", (name or "").replace(".", "_")).strip() or f"field_p{page_index + 1}"
        if kind == "radio" and (page_index, base) in self.radio:
            return self.radio[(page_index, base)]
        final, n = base, 2
        while final in self.used:
            final, n = f"{base}_{n}", n + 1
        self.used.add(final)
        if kind == "radio":
            self.radio[(page_index, base)] = final
        return final

    def radio_groups(self) -> dict:
        """{radio group name: its question}, for `settle_radio_names`."""
        return {name: self.radio_labels.get(name, "") for name in self.radio.values()}


# ---------------------------------------------------------------- the overlay

def _font_css_pt(nf: NativeField) -> float:
    """The field's text size: the original's own, else one that fits (WeasyPrint writes the CSS size, in pt)."""
    if nf.font_pt > 0:
        size = nf.font_pt
    elif nf.kind == "textarea" or (nf.kind == "select" and nf.rect.height > 30):
        size = 10.0
    else:
        size = min(12.0, max(6.0, nf.rect.height * 0.6))
    return round(size, 2)


def native_fields_overlay(fields: list, page_index: int, names: FieldNames) -> tuple:
    """(HTML for real fields over the picture, {field name: value to write after WeasyPrint}, count)."""
    parts, values = [], {}
    for n, nf in enumerate(fields, start=1):
        r = nf.rect
        name = names.take(nf.name, page_index, nf.kind)
        esc_name = _html.escape(name, quote=True)
        label = _html.escape(nf.label, quote=True)
        border = "border:none;" if nf.has_off_look or nf.kind not in ("checkbox", "radio") else "border:0.75pt solid #000;"
        style = (f"position:absolute; left:{round(r.x0, 2)}pt; top:{round(r.y0, 2)}pt; width:{round(r.width, 2)}pt; "
                 f"height:{round(r.height, 2)}pt; margin:0; padding:0; {border} background:transparent; z-index:95;")
        common = f'id="nf_{page_index}_{n}" name="{esc_name}" title="{label}" aria-label="{label}"'
        if nf.kind in ("checkbox", "radio"):
            if nf.kind == "radio":
                names.radio_labels.setdefault(name, nf.group_label)
            checked = " checked" if nf.checked else ""
            parts.append(f'<input type="{nf.kind}" {common} value="{_html.escape(nf.export, quote=True)}"{checked} '
                         f'style="{style}" />')
            continue
        text_style = f'{style} font-family:Arial,Helvetica,sans-serif; font-size:{_font_css_pt(nf)}pt; color:#000;'
        if nf.kind == "select":
            options = "".join(f'<option value="{_html.escape(v, quote=True)}">{_html.escape(t)}</option>'
                              for v, t in nf.options)
            multiple = " multiple" if nf.multiple else ""
            parts.append(f'<select {common}{multiple} style="{text_style}">{options}</select>')
            chosen = [s for s in nf.selected if s in {v for v, _ in nf.options}]
            if chosen:
                values[name] = chosen if nf.multiple else chosen[-1]
        elif nf.kind == "textarea":
            parts.append(f'<textarea {common} style="{text_style}"></textarea>')
            if nf.value:
                values[name] = nf.value
        else:
            maxlen = f' maxlength="{nf.maxlen}"' if nf.maxlen > 0 else ""
            parts.append(f'<input type="{nf.kind}" {common}{maxlen} style="{text_style}" />')
            if nf.value:
                values[name] = nf.value
    return "".join(parts), values, len(fields)


def settle_radio_names(doc: "fitz.Document", groups: dict) -> int:
    """WeasyPrint gives each radio button its group's name as well, so the group reads "contact.contact", and
    gives the group the FIRST button's label ("Preferred contact: Phone"). A button is a widget of its group,
    not a field of its own: drop the repeated name, and label the group with its question (our groups only).
    Each button keeps its own "question: choice" label."""
    done = 0
    for page in doc:
        for w in page.widgets() or []:
            if w.field_type != RADIO:
                continue
            kind, own = doc.xref_get_key(w.xref, "T")
            pkind, parent = doc.xref_get_key(w.xref, "Parent/T")
            if kind == "string" and pkind == "string" and own == parent and own in groups:
                doc.xref_set_key(w.xref, "T", "null")
                pref = doc.xref_get_key(w.xref, "Parent")
                if groups[own] and pref[0] == "xref":
                    doc.xref_set_key(int(pref[1].split()[0]), "TU", fitz.get_pdf_str(groups[own]))
                done += 1
    return done


def apply_field_values(doc: "fitz.Document", values: dict) -> int:
    """Write the original's text and choice values into the built PDF's fields, by name. Returns how many."""
    if not values:
        return 0
    done = 0
    for page in doc:
        for w in page.widgets() or []:
            v = values.get(w.field_name)
            if v is None:
                continue
            if isinstance(v, list):
                doc.xref_set_key(w.xref, "V", "[" + " ".join(fitz.get_pdf_str(s) for s in v) + "]")
            else:
                doc.xref_set_key(w.xref, "V", fitz.get_pdf_str(v))
            done += 1
    return done
