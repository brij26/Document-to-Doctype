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

### Failure path
- [ ] Attach a corrupt or unsupported file (e.g. a renamed empty file) → job
      runs, status moves to `Failed`, `error_log` is populated with a useful
      message, and a corresponding `frappe.log_error` entry exists (Desk →
      Error Log).

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
scanned image is processed by PaddleOCR (not tesseract), failures land in
`Failed` with a visible error, and the phone-photo real-world gap is
explicitly called out if untested.

## Out of scope
No interpretation of the OCR text (classification, field extraction,
confidence scoring) — that's Phase 3.
