"""Automatic keyboard and screen-reader checks of a finished PDF (checklist 5.2, 5.3 and 5.4).

Geoffrey, 2026-11-27: "we still want that automatic", then "we want both": every PDF gets an automatic keyboard and
screen-reader check, recorded with its date; a small daily sample is also tested by a person (another feature).

What a keyboard or screen-reader user gets from a tagged PDF is decided by its structure tree, so this reads it,
the way NVDA / JAWS and Acrobat do, and reports counts and page numbers (never any of the document's words):

  keyboard  every link and form field annotation is in the structure tree (reachable in structure order) and every
            page with annotations has /Tabs /S. Field order itself is field_order.py's report.
  reader    the document's language, title and DisplayDocTitle; headings (and any skipped level); images (Figures)
            with and without a description, and descriptions that look like a file name or a placeholder word;
            tables with and without header cells; lists whose children are not list items.

Page numbers are pages of THIS output PDF (1-based): the accessible text pages have no single original page.
Read-only, bounded by a time budget, and it never raises: a report, never a reason to fail a build.

KEEP IN STEP: this file is identical in pdf-engine-crisp and pdf-enginev2.
"""
import re
import time
from datetime import datetime, timezone

import pikepdf
from pikepdf import Array, Dictionary, Name

READING_CHECK_VERSION = 1
DEFAULT_BUDGET_S = 15.0
MAX_PAGES_LISTED = 50

HEADING_RE = re.compile(r"^H([1-6])$")
# A description that is a file name, a camera / scanner file stem, or a lone placeholder word is worth a look.
FILE_NAME_ALT = re.compile(r"\.(png|jpe?g|gif|bmp|tiff?|svg|webp|heic|pdf)\s*$|^(img|dsc|dscn|pxl|image|photo|scan|screenshot|screen shot)[ _-]?\d+", re.I)
PLACEHOLDER_ALT = re.compile(r"^(image|picture|photo|graphic|figure|img|icon|untitled|chart|diagram|alt|description|placeholder)\s*\d*$", re.I)
TABLE_CELL = {"TH", "TD"}


def _objgen(obj):
    try:
        og = obj.objgen
        return og if og != (0, 0) else None
    except Exception:
        return None


def _name(v):
    return str(v)[1:] if isinstance(v, Name) else None


def _text(v):
    try:
        return str(v).strip()
    except Exception:
        return ""


def _kids(node):
    k = node.get(Name.K, None) if isinstance(node, Dictionary) else None
    if k is None:
        return []
    return list(k) if isinstance(k, Array) else [k]


def _empty_report():
    return {
        "version": READING_CHECK_VERSION,
        "checkedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pages": 0,
        "keyboard": {
            "links": 0, "fields": 0, "untaggedLinks": 0, "untaggedFields": 0,
            "untaggedPages": [], "noTabsPages": [],
        },
        "reader": {
            "lang": False, "title": False, "displayDocTitle": False,
            "headings": 0, "headingSkips": 0, "headingSkipPages": [],
            "images": 0, "imagesDescribed": 0, "imagesWithoutDescriptionPages": [],
            "placeholderDescriptionPages": [],
            "tables": 0, "tablesWithHeaders": 0, "tablesWithoutHeadersPages": [],
            "lists": 0, "listsMalformed": 0,
        },
        "timeUp": False,
    }


def _add_page(lst, page):
    if page and page not in lst and len(lst) < MAX_PAGES_LISTED:
        lst.append(page)


def check_reading(path: str, budget_s: float = DEFAULT_BUDGET_S) -> dict:
    """The keyboard and screen-reader report for a finished PDF (see the module docstring)."""
    out = _empty_report()
    started = time.monotonic()
    kb, rd = out["keyboard"], out["reader"]
    try:
        with pikepdf.open(path) as pdf:
            out["pages"] = len(pdf.pages)
            page_no = {}
            annot_kind = {}  # annotation objgen -> ("link" | "field", page)
            field_ids = set()
            for i, page in enumerate(pdf.pages):
                og = _objgen(page.obj)
                if og is not None:
                    page_no[og] = i + 1
                has_annots = False
                for a in page.obj.get(Name.Annots, []) or []:
                    sub = a.get(Name.Subtype, None)
                    aog = _objgen(a)
                    if aog is None:
                        continue
                    if sub == Name.Link:
                        annot_kind[aog] = ("link", i + 1)
                        kb["links"] += 1
                        has_annots = True
                    elif sub == Name.Widget:
                        annot_kind[aog] = ("field", i + 1)
                        parent = a.get(Name.Parent, None)
                        field_ids.add(_objgen(parent) if parent is not None and _objgen(parent) else aog)
                        has_annots = True
                if has_annots and page.obj.get(Name.Tabs, None) != Name.S:
                    _add_page(kb["noTabsPages"], i + 1)
            kb["fields"] = len(field_ids)

            root = pdf.Root
            rd["lang"] = bool(_text(root.get(Name.Lang, "")))
            try:
                rd["title"] = bool(_text(pdf.docinfo.get(Name.Title, ""))) if pdf.docinfo is not None else False
            except Exception:
                rd["title"] = False
            vp = root.get(Name.ViewerPreferences, None)
            rd["displayDocTitle"] = bool(vp is not None and vp.get(Name.DisplayDocTitle, False) is True)

            st = root.get(Name.StructTreeRoot, None)
            tagged = set()
            if st is not None:
                role_map = st.get(Name.RoleMap, None)

                def resolve(raw):
                    seen = 0
                    while raw and role_map is not None and Name("/" + raw) in role_map and seen < 10:
                        nxt = _name(role_map[Name("/" + raw)])
                        if not nxt or nxt == raw:
                            break
                        raw, seen = nxt, seen + 1
                    return raw

                def first_page(node, inherited):
                    """The page an element is on: its own /Pg, else the nearest ancestor's, else a descendant's."""
                    pg = node.get(Name.Pg, None) if isinstance(node, Dictionary) else None
                    if pg is not None and _objgen(pg) in page_no:
                        return page_no[_objgen(pg)]
                    if inherited:
                        return inherited
                    stack, steps = list(_kids(node)), 0
                    while stack and steps < 200:
                        k, steps = stack.pop(), steps + 1
                        if isinstance(k, Dictionary):
                            kpg = k.get(Name.Pg, None)
                            if kpg is not None and _objgen(kpg) in page_no:
                                return page_no[_objgen(kpg)]
                            stack.extend(_kids(k))
                    return None

                def has_th(table):
                    stack = list(_kids(table))
                    while stack:
                        k = stack.pop()
                        if not isinstance(k, Dictionary):
                            continue
                        t = resolve(_name(k.get(Name.S, None)))
                        if t == "TH":
                            return True
                        if t == "Table":
                            continue  # a nested table has its own headers
                        stack.extend(_kids(k))
                    return False

                last_level = 0
                seen = set()
                # Depth-first, in structure order (the reading order): (node, inherited page).
                stack = [(k, None) for k in reversed(_kids(st))]
                visited = 0
                while stack:
                    visited += 1
                    if visited % 500 == 0 and time.monotonic() - started > budget_s:
                        out["timeUp"] = True
                        break
                    node, inherited = stack.pop()
                    if not isinstance(node, Dictionary):
                        continue
                    og = _objgen(node)
                    if og is not None:
                        if og in seen:
                            continue
                        seen.add(og)
                    if node.get(Name.Type, None) == Name.OBJR:
                        target = node.get(Name.Obj, None)
                        tog = _objgen(target) if target is not None else None
                        if tog is not None:
                            tagged.add(tog)
                        continue
                    pg = node.get(Name.Pg, None)
                    page = page_no.get(_objgen(pg)) if pg is not None else None
                    page = page or inherited
                    s = resolve(_name(node.get(Name.S, None)))
                    if s:
                        m = HEADING_RE.match(s)
                        if m:
                            level = int(m.group(1))
                            rd["headings"] += 1
                            if level > last_level + 1:
                                rd["headingSkips"] += 1
                                _add_page(rd["headingSkipPages"], first_page(node, page))
                            last_level = level
                        elif s == "Figure":
                            rd["images"] += 1
                            alt = _text(node.get(Name.Alt, "")) or _text(node.get(Name.ActualText, ""))
                            if alt:
                                rd["imagesDescribed"] += 1
                                if FILE_NAME_ALT.search(alt) or PLACEHOLDER_ALT.match(alt):
                                    _add_page(rd["placeholderDescriptionPages"], first_page(node, page))
                            else:
                                _add_page(rd["imagesWithoutDescriptionPages"], first_page(node, page))
                        elif s == "Table":
                            rd["tables"] += 1
                            if has_th(node):
                                rd["tablesWithHeaders"] += 1
                            else:
                                _add_page(rd["tablesWithoutHeadersPages"], first_page(node, page))
                        elif s == "L":
                            rd["lists"] += 1
                            kid_types = [resolve(_name(k.get(Name.S, None))) for k in _kids(node) if isinstance(k, Dictionary)
                                         and k.get(Name.Type, None) != Name.OBJR and k.get(Name.Type, None) != Name.MCR]
                            if any(t not in ("LI", "Caption", "L") for t in kid_types if t):
                                rd["listsMalformed"] += 1
                    for k in reversed(_kids(node)):
                        stack.append((k, page))

            for aog, (kind, page) in annot_kind.items():
                if aog not in tagged:
                    kb["untaggedLinks" if kind == "link" else "untaggedFields"] += 1
                    _add_page(kb["untaggedPages"], page)
            kb["untaggedPages"].sort()
    except Exception as e:  # a report, never a reason to fail a build
        out["error"] = type(e).__name__
    out["ms"] = int((time.monotonic() - started) * 1000)
    return out
