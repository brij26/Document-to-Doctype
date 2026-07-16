# Manual Test — Phase 2: OCR layer (`docapture/ocr/*`)

**Status:** Awaiting Review
**Goal:** turn an uploaded file into normalized OCR JSON, asynchronously.

## Prerequisites
- Background workers running (`bench start`, or at least the `long` queue worker).
- Fixture files available at:
  - `apps/docapture/tests/fixtures/ocr/sales_order_page1/Sales order.pdf`
    (born-digital PDF)
  - `apps/docapture/tests/fixtures/ocr/sales_order_page1/input.jpg`
    (scanned/photo image)

## Manual test steps

### Born-digital PDF path
- [ ] Create a `Captured Document`, attach `Sales order.pdf`, save (status
      `Uploaded`).
- [ ] Wait for the background job to run → status moves to `OCR Done`
      automatically.
- [ ] Open `raw_ocr_json` → populated, non-empty.
- [ ] Confirm the page used the native PyMuPDF text-layer path (no OCR engine
      needed) — check the per-page `engine`/`confidence_source` discriminator
      reflects the digital-text branch, not `paddleocr`/`tesseract`.

### Scanned/photo image path
- [ ] Create a new `Captured Document`, attach `input.jpg`, save.
- [ ] Wait for the job → status moves to `OCR Done`.
- [ ] Open `raw_ocr_json` → populated.
- [ ] Confirm per-page `engine == "paddleocr"` (not `tesseract` — this was a
      real bug where every raster page silently fell back to tesseract;
      confirm the fix holds).

### Unsupported file type — rejected at upload, not async
- [ ] On a new `Captured Document`, click Attach and try to pick a `.txt` file
      — confirm the OS file-picker either filters it out, or (drag-drop /
      "all files" override) Frappe's own orange "skipped, invalid file type"
      alert appears and the field stays a plain **Attach** button — no
      **Reload File**/**Clear** buttons should ever appear for a rejected file.
- [ ] If the client-side restriction is somehow bypassed (or testing directly
      via the API): confirm `captured_document.py`'s `check_file_type()`
      still rejects it on save with a clear "Unsupported file type" message,
      naming the extension, before any OCR job is enqueued.

### Failure path (corrupt file of a *supported* type)
- [ ] Attach a corrupt file with an allowed extension (e.g. a `.pdf` renamed
      from an empty/garbage file, so it passes the extension check but isn't
      a real PDF) → save succeeds, job runs, status moves to `Failed`,
      `error_log` is populated with a useful message, and a corresponding
      `frappe.log_error` entry exists (Desk → Error Log).

### raw_ocr_json shape spot-check
- [ ] For either fixture's result, confirm the JSON structure is
      pages → lines → words, coordinates are integer pixels at 200 DPI, and
      each page carries its own `engine` / `confidence_source` /
      `word_tokenization` fields.

### Known gap — flag, don't silently pass
- [ ] Phone-photo perspective correction (keystone warp for angled phone
      shots) has only been validated against a **synthetic** fixture so far,
      not a real phone photo. If you have a real photographed receipt/bill
      handy, upload it as a `Payment Receipt`/`Expense Voucher` source type
      and check the OCR output quality; if not, note this as still unverified
      rather than marking it passed.

## Expected result
Both fixture types reach `OCR Done` with correctly shaped `raw_ocr_json`, the
scanned image is processed by PaddleOCR (not tesseract), an unsupported file
type is rejected before it ever uploads (not left `Failed` async), a corrupt
file of a supported type still lands in `Failed` with a visible error, and the
phone-photo real-world gap is explicitly called out if untested.

## Out of scope
No interpretation of the OCR text (classification, field extraction,
confidence scoring) — that's Phase 3.
