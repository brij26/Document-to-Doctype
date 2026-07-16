# docapture — Feature List

Legend for each feature:
- **[custom]** — genuinely custom code we build.
- **[built-in]** — use an existing Frappe/ERPNext feature; do not rebuild.
- **[hybrid]** — thin custom glue over a built-in.

The default is **use the built-in**. A feature is only `[custom]` when nothing
native covers it.

---

## Must-Have (MVP)

### Ingestion
- **Document upload (PDF / image / scan)** — **[built-in]** Frappe File / Attach
  field on the `Captured Document` doctype. No custom uploader.
- **File type + text-layer detection** — **[custom]** decide digital-PDF vs
  scanned-image path (drives OCR vs direct text extraction).
- **Background processing** — **[built-in]** `frappe.enqueue` / Frappe workers.
  OCR + LLM run async; the UI never blocks.

### OCR layer (`docapture/ocr/*`)
- **Digital PDF text extraction** — **[custom]** via PyMuPDF (`fitz`); no OCR when
  a text layer exists.
- **Scanned/image OCR** — **[custom]** PaddleOCR engine, Tesseract fallback.
- **Scan preprocessing** — **[custom]** OpenCV deskew / denoise / threshold.
- **Swappable OCR engine interface** — **[custom]** `OCREngine` protocol so a new
  engine is a new file, not an edit.

### Mapper / LLM layer (`docapture/mappers/*`)
- **Structured field extraction** — **[custom]** OCR text → structured DTO via a
  pluggable `LLMParser` interface (vendor undecided; recommend Claude, not hardwired).
- **Source-document classification** — **[custom]** detect Payment Receipt /
  Bank Statement / Supplier Bill / Expense Voucher.
- **Confidence scoring** — **[custom]** per-field + overall confidence on the DTO.
- **Learned alias resolution (`Capture Alias`)** — **[custom]** map an extracted
  raw value (e.g. company/supplier/ledger name) to the real ERPNext record; ask the
  user once, remember forever. Not ML — the review queue is the labeling step.

### Routing + draft creation
- **Router: source → target doctype** — **[custom]** receipts + bank-statement lines
  → Payment Entry; supplier bills + expense/misc → Journal Entry. Registry-based so
  new targets add without editing the router.
- **Payment Entry draft creation** — **[hybrid]** build ERPNext Payment Entry at
  `docstatus=0` from the DTO. The doctype and its accounting are **[built-in]**; the
  DTO→fields mapping is **[custom]**.
- **Journal Entry draft creation** — **[hybrid]** same pattern for Journal Entry.
- **Duplicate detection** — **[custom]** `content_hash` + (party, amount, date,
  reference) uniqueness check before a draft is created.
- **Multi-company / multi-currency mapping** — **[hybrid]** detection + field
  mapping is **[custom]**; the FX and multi-company accounting are **[built-in]**
  ERPNext. We never build FX logic.

### Review + governance
- **Human review queue (everything, no auto-post)** — **[hybrid]** a filtered List
  View of `Captured Document` in `In Review` status (**[built-in]** list view +
  status field) with **[custom]** approve/reject actions that trigger draft creation.
- **Audit trail** — **[hybrid]** link `Captured Document` ↔ created draft
  (`target_doctype` + `target_docname`), plus **[built-in]** Frappe document
  version history / activity log.
- **Permissions & roles** — **[built-in]** Frappe role permissions on the doctypes
  (e.g. an uploader role vs a reviewer role). No custom permission engine.

---

## Should-Have

- **Fuzzy alias assist** — **[custom]** on an alias miss, `rapidfuzz` against existing
  records to pre-select the top candidate in the review UI (still user-confirmed).
- **Auto-draft above a confidence threshold** — **[custom]** high-confidence docs
  skip the queue and land as drafts directly. Deliberately excluded from v1 (trust).
- **Bank-statement multi-line splitting** — **[custom]** one statement → many Payment
  Entries, one per transaction row, each dedup-checked.
- **Reprocess / re-OCR action** — **[custom]** re-run a failed or low-quality capture.
- **Basic capture dashboard** — **[built-in]** Frappe Number Cards / Report View over
  `Captured Document` (counts by status, throughput).

---

## Nice-to-Have / Future

- **Purchase Invoice target + line-item extraction** — **[custom]** the real AP path:
  line items, expense/GL coding, and three-way matching against existing POs/GRNs.
  This is where line items finally have a home (PE/JE have no item table).
- **Vertical document types** — **[custom]** pharma batch/COA, steel test certificates,
  etc. Domain-specific extraction schemas.
- **Feedback / learning loop** — **[custom]** use reviewer corrections to improve
  extraction prompts/heuristics over time.
- **Straight-through processing metrics + SLA** — **[custom]** measure auto-vs-manual
  rates, exception aging.
- **Per-document / per-page metering** — **[custom]** for a usage-based billing model.

---

## Explicit non-goals (for now)
- No FX/multi-company accounting engine — ERPNext owns that.
- No custom file storage — Frappe File owns that.
- No custom auth/permission system — Frappe roles own that.
- No line items or three-way matching until Purchase Invoice lands (Future).
- No auto-posting or auto-drafting in v1 — everything goes through review.
