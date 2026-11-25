"""Form fields in reading order (checklist 2.4: form fields labelled and in a logical order).

A picture page's fields come from three places: the original's own fields (native_form_fields.py), the
worker's AI boxes (main.build_form_control) and the printed checkboxes made tickable (visual_checkboxes.py).
They used to be written in that order, so Tab visited every text field before any checkbox, wherever each
sat on the page. WeasyPrint tags the fields in HTML order and every page gets /Tabs /S, so the HTML order is
the tab order. Fields are now written in row order: top to bottom, and left to right within a line, which is
Acrobat's "row order". A layout of two independent columns also gets row order.

check_field_order() reads a finished PDF and reports the pages whose fields are tagged out of row order and
the pages that have fields but no /Tabs /S. It only reads, and it never raises.

KEEP IN STEP: this file is identical in pdf-engine-crisp and pdf-enginev2.
"""
import pikepdf
from pikepdf import Array, Dictionary, Name


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _box(item) -> tuple:
    x0, y0, x1, y1 = (_num(v) for v in item[:4])
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def row_order(items: list) -> list:
    """Items `(x0, y0, x1, y1, ...)` in page points with y growing downwards, returned in row order.

    Two items share a row when they overlap vertically by at least half the shorter one's height (measured
    against the row's first item, so a run of slightly lower items does not drift into one long row). The
    sort is stable: items at the same spot keep the order they came in."""
    boxed = sorted(((_box(it), n, it) for n, it in enumerate(items)), key=lambda t: (t[0][1], t[0][0], t[1]))
    rows = []
    for box, n, it in boxed:
        if rows:
            top, bottom = rows[-1][0]
            overlap = min(bottom, box[3]) - max(top, box[1])
            shorter = max(min(bottom - top, box[3] - box[1]), 1.0)
            if overlap >= shorter / 2:
                rows[-1][1].append((box, n, it))
                continue
        rows.append(((box[1], box[3]), [(box, n, it)]))
    ordered = []
    for _, members in rows:
        ordered.extend(it for _, _, it in sorted(members, key=lambda t: (t[0][0], t[0][1], t[1])))
    return ordered


def ordered_html(controls: list) -> str:
    """The HTML of `(x0, y0, x1, y1, html)` controls, joined in row order."""
    return "".join(c[4] for c in row_order(controls))


def _objgen(obj):
    try:
        og = obj.objgen
        return og if og != (0, 0) else None
    except Exception:
        return None


def _kids(node) -> list:
    k = node.get(Name.K, None) if isinstance(node, Dictionary) else None
    if k is None:
        return []
    return list(k) if isinstance(k, Array) else [k]


def check_field_order(path: str) -> dict:
    """Per-page field order of a finished PDF, read from its tags.

    Returns {"fields": tagged widgets, "pages": pages with fields, "outOfOrderPages": [1-based page numbers
    whose fields are tagged out of row order], "noTabsPages": [pages with fields whose /Tabs is not /S]}."""
    out = {"fields": 0, "pages": 0, "outOfOrderPages": [], "noTabsPages": []}
    try:
        with pikepdf.open(path) as pdf:
            widget_page, page_info = {}, {}
            for i, page in enumerate(pdf.pages):
                mb = [float(v) for v in page.obj.get(Name.MediaBox, [0, 0, 612, 792])]
                page_info[i] = (mb[3], page.obj.get(Name.Tabs, None) == Name.S)
                for annot in page.obj.get(Name.Annots, []) or []:
                    og = _objgen(annot)
                    if og is not None and annot.get(Name.Subtype, None) == Name.Widget:
                        widget_page[og] = (i, annot)
            st = pdf.Root.get(Name.StructTreeRoot, None)
            per_page, seen, in_form = {}, set(), set()

            def visit(node, form_depth):
                og = _objgen(node)
                if og is not None:
                    if og in seen:
                        return
                    seen.add(og)
                if not isinstance(node, Dictionary):
                    return
                if node.get(Name.Type, None) == Name.OBJR:
                    obj = node.get(Name.Obj, None)
                    target = _objgen(obj) if obj is not None else None
                    if form_depth and target in widget_page and target not in in_form:
                        in_form.add(target)
                        i, annot = widget_page[target]
                        x0, y0, x1, y1 = (float(v) for v in annot.get(Name.Rect, [0, 0, 0, 0]))
                        h = page_info[i][0]
                        per_page.setdefault(i, []).append((x0, h - max(y0, y1), x1, h - min(y0, y1)))
                    return
                depth = form_depth + (1 if node.get(Name.S, None) == Name.Form else 0)
                for kid in _kids(node):
                    visit(kid, depth)

            if st is not None:
                for kid in _kids(st):
                    visit(kid, 0)
            pages_with_widgets = {i for i, _ in widget_page.values()}
            out["fields"] = len(in_form)
            out["pages"] = len(pages_with_widgets)
            for i in sorted(per_page):
                tagged = [(*box, n) for n, box in enumerate(per_page[i])]
                if [t[4] for t in row_order(tagged)] != list(range(len(tagged))):
                    out["outOfOrderPages"].append(i + 1)
            out["noTabsPages"] = [i + 1 for i in sorted(pages_with_widgets) if not page_info[i][1]]
    except Exception as e:  # a report, never a reason to fail a build
        out["error"] = type(e).__name__
    return out
