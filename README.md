# pdf-engine-crisp — PDF Accessibility Engine (CRISP worker / small-docs lane)

FastAPI service that turns an HTML representation + the original PDF into a
tagged, accessible **PDF/UA-1** output. Sibling engine: `pdf-enginev2`
(core / heavy lane). The two share `pdfua_repair.py` and the upload handling.

## Large source PDFs

Source PDFs are POSTed as multipart `file` / `original_pdf` fields to
`/get-page-count`, `/split-to-queue`, `/detect-forms`, `/detect-forms-single`,
`/build`, and `/split`. Every endpoint **streams the upload to a temp file on
disk** (`shutil.copyfileobj`) rather than reading it into memory, so large
documents do not spike RSS.

### `MAX_PDF_UPLOAD_MB`
Maximum accepted upload size, in megabytes. **Default: `600`.**

Raise it to accept larger source PDFs. It is applied to the multipart parser at
startup. Starlette (>= 0.41, including the 1.x line now pinned) caps every
non-file multipart part at 1 MiB by default, which would reject the
`html_content` form field of a large `/build` request; this override lifts that
cap to `MAX_PDF_UPLOAD_MB` (a bare class-attribute assignment would not, because
the parser sets a per-instance default). File parts always spool to disk. Small
PDFs behave exactly as before. Regression test: `tests/test_upload_limits.py`.

## Environment variables

| var | default | purpose |
|-----|---------|---------|
| `MAX_PDF_UPLOAD_MB` | `600` | max multipart upload size (MB) |
| `PDF_VISUAL_MAX_PIXELS` | `30000000` | pixel budget per rasterized page (visual pages and AI page images). The DPI is lowered only for pages that would exceed it, so Letter/Tabloid keep full resolution while a 33×55 in poster renders at ~128 DPI instead of 113 MP (which OOM-killed a 2 GiB instance). `0` disables the cap. |
| `PORT` | `10000` | uvicorn listen port |
| `SUPABASE_URL` | – | Supabase project URL (job queue + built-PDF storage) |
| `SUPABASE_KEY` | – | Supabase service key |
| `PDF_ENGINE_SECRET` | unset (check off) | shared secret: when set, every endpoint except `/healthz` needs the same value in the `x-pdf-engine-key` header, else 401. See "Access" below. |

See `.env.example`.

## Access: shared secret (`PDF_ENGINE_SECRET`)

`engine_auth.py` (same file as in pdf-enginev2) checks the `x-pdf-engine-key` header on
every request (constant-time compare) and answers `401 {"error": "unauthorized"}` when it
is missing or wrong, before the endpoint runs. `/healthz` stays open. **Off while
`PDF_ENGINE_SECRET` is unset or blank**, so deploying the code changes nothing. To turn it
on without a failed request, set the same value on the callers first (the TechA11y worker
on Render sends the header whenever its own `PDF_ENGINE_SECRET` is set; an engine without
the check ignores it), then on both engines. Regression test: `tests/test_engine_auth.py`.

This engine has no endpoint that downloads a caller-supplied URL (no `/merge-parts`), and
WeasyPrint's resource loading on `/build` is already restricted by `resource_policy.py`.

## Picture pages: the original's own form fields (`native_form_fields.py`)

When the original is fillable, its picture pages keep working fields: every editable text, check box, radio
button, combo box and list box of the original becomes a real field at its own spot, with its own name, its
label (/TU, else the words beside it), and its value, ticks and choices. Read-only fields, push buttons and
signatures stay as pictures. Text and choice values are written into the fields after WeasyPrint (never into
the page), and the picture shows each field empty, so nothing shows twice. A page with such fields ignores the
`corrected_forms_json` boxes. Test: `python tests/test_native_form_fields.py` (form: `tests/fillable_fixture.py`).

## Picture pages: fields in reading order (`field_order.py`)

A picture page's fields (the original's own, the worker's AI boxes, and printed checkboxes made tickable) are
written in row order: top to bottom, left to right within a line. WeasyPrint tags them in that order and every
page has `/Tabs /S`, so it is also the Tab order. Before, they were written list by list, so Tab visited every
text field before any checkbox. After each build, `check_field_order` reads the finished PDF and reports pages
whose fields are tagged out of row order or lack `/Tabs /S`: response header `X-Form-Order` (and `form_order`
in the JSON response when the PDF is uploaded). veraPDF does not check field order. The file is identical in
both engines. Test: `python tests/test_field_order.py`.

## Picture pages: text contrast report (`contrast_check.py`)

Picture pages keep the original's colours, so low-contrast text stays as the publisher made it. Each build
measures it and reports it; it never changes a colour (checklist 1.3). For each original page:
- text spans come from PyMuPDF's text trace (colour, size, bold, render mode, opacity); invisible text such as
  an OCR layer is skipped;
- the background is read from a 72 DPI render of the page with its text removed, so glyphs don't mix in;
- ratios use the WCAG 2 formula (the TypeScript twin is `server/services/contrast-math.ts` in the TechA11y
  platform): large text (at least 18 pt, or 14 pt bold) needs 3:1, other text 4.5:1.

The report is in the `X-Contrast` header (and `contrast` in the JSON response when the PDF is uploaded):
pages checked, the pages with low-contrast text (count and lowest ratio, original page numbers), and pages not
checked (`noText`: scans or invisible text only; `timeUp`: after the 20 s budget). `PDF_CONTRAST_CHECK=0` turns
it off. It never fails a build. The file is identical in both engines. Test: `python tests/test_contrast_check.py`.

## Automatic keyboard and screen-reader check (`reading_check.py`)

Every build reads the finished PDF's tags the way a screen reader (NVDA, JAWS) and Acrobat's keyboard navigation
do, and reports what a keyboard or screen-reader user will meet (checklist 5.2 keyboard, 5.3 screen reader, 5.4
date; the TechA11y platform words it in each document's Accessibility notes, dated):
- keyboard: links and form fields (a radio group counts once), any Link or Widget annotation missing from the
  structure tree (the Tab key may skip it), and pages with annotations but no `/Tabs /S`;
- screen reader: `/Lang`, the title and `DisplayDocTitle`; headings and skipped levels; images (Figures) with
  and without Alt / ActualText, and descriptions that are a file name or a placeholder word; tables with and
  without header cells (TH); lists whose children are not list items.

The report is in the `X-Reading-Check` header (and `reading_check` in the JSON response when the PDF is
uploaded): counts and page numbers of the accessible PDF, never the document's words, plus `checkedAt` (UTC),
`pages`, `timeUp` (after the 15 s budget) and `error` (a file it could not read). It only reads, never raises
and never fails a build. On crisp builds the worker's post-build chain then repairs heading levels and empty
figures, so those counts can be higher here than in the served file. The file is identical in both engines.
Test: `python tests/test_reading_check.py`.

## Run

```
uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --timeout-keep-alive 2700
```

## Notes on the largest documents

- Upload **acceptance** is independent of the instance tier (uploads spool to
  disk). **Processing** very large / high-page-count PDFs (rasterization +
  WeasyPrint in `/build`) is CPU- and memory-intensive and may need a larger
  Render tier and adequate ephemeral disk for the transient temp files.
- The built output is uploaded to the Supabase `pdf_outputs` bucket. If that
  store rejects an oversized output, `/build` falls back to returning the PDF
  inline, so ingestion is never blocked by the store's own size cap. To store
  large built outputs, raise the bucket / project storage file-size limit in
  Supabase.
