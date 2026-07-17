# docapture — Architecture

## What docapture does

Users upload supplier/payment documents (PDF, image, scan). docapture OCRs and
parses them into structured data, stores that as JSON on a custom doctype, routes
each document to the correct accounting draft (`docstatus=0`), and holds
**everything in a human review queue before anything posts**.

Design north star: **the OCR layer, the mapper layer, and draft creation are
strictly separated** (see `DESIGN_PRINCIPLES.md`). Each layer has one job and
talks to the next through a plain data structure, not through shared internals.

---

## Data flow

```
upload
  │
  ▼
[Captured Document]  status: Uploaded
  │  enqueue background job
  ▼
OCR layer (docapture/ocr/*)
  • PyMuPDF: has text layer? → extract text directly
  •                          → no? rasterize page → OpenCV preprocess → PaddleOCR (Tesseract fallback)
  │  writes raw_ocr_json      status: OCR Done
  ▼
Mapper layer (docapture/mappers/*)
  • classifier → source_type
  • LLMParser → structured DTO (fields + per-field confidence)
  • alias resolver → map raw values (company/supplier/ledger/…) to real records
  │  writes extracted_json + confidence   status: Parsed → In Review
  ▼
Review queue (human)             ← EVERYTHING stops here in v1
  • reviewer inspects, fixes unresolved fields, confirms aliases
  • approve
  ▼
Router → Creator (docapture/creators/*)
  • dedup check (content_hash + party/amount/date/reference)
  • DTO → Payment Entry OR Journal Entry at docstatus=0
  │  links target_doctype + target_docname   status: Approved → Posted
  ▼
[ERPNext draft accounting document]  (human submits it in ERPNext as usual)
```

**Where confidence sits:** computed in the mapper layer, *before* the review queue.
Confidence informs the reviewer (and, in a later phase, an auto-draft threshold).
In v1 it never bypasses review.

**Where review sits:** between parsing and draft creation. A draft is only built
*after* a human approves — the review gate guards whether extracted data is
trustworthy enough to become a draft at all, not merely whether to submit one.

---

## Doctypes

### `Captured Document` (core)
The pipeline's spine. One row per uploaded document.

| Field | Type | Purpose |
|---|---|---|
| `file` | Attach | the uploaded PDF/image (Frappe File) |
| `source_type` | Select | Payment Receipt / Bank Statement / Supplier Bill / Expense Voucher |
| `company` | Link (Company) | detected/mapped company |
| `currency` | Link (Currency) | detected/mapped currency |
| `raw_ocr_json` | Long Text | normalized OCR text/blocks |
| `extracted_json` | Long Text | structured mapper DTO |
| `confidence` | Float | overall extraction confidence |
| `content_hash` | Data (indexed) | dedup key over file content |
| `status` | Select | workflow state (below) |
| `target_doctype` | Data | created draft's doctype |
| `target_docname` | Dynamic Link | created draft's name (audit link) |
| `error_log` | Long Text | failure detail when `status = Failed` |

**Status flow:** `Uploaded → OCR Done → Parsed → In Review → Approved → Posted`,
plus `Rejected` and `Failed` as terminal side-states.

> ⚠️ **Expensive to unwind.** The `Captured Document` schema, the JSON shapes, and
> the status model are hard to change once real captures exist. Settle them in
> Phase 1 before data accumulates.

### `Capture Alias` (learned mapping memory)
Generic, cross-field lookup so a value resolved once is never re-asked.

| Field | Type | Purpose |
|---|---|---|
| `entity_type` | Select | Company / Supplier / Account / Bank Account / Mode of Payment / Currency / … |
| `raw_value` | Data | the extracted string, e.g. `"ABC pvt limited"` |
| `normalized_value` | Data (indexed) | lookup key after normalization |
| `mapped_doctype` | Data | the real record's doctype |
| `mapped_docname` | Dynamic Link | the real record |
| `company` | Link (optional) | scope: same string may map differently per company |
| `source` | Select | User Confirmed / Auto |

Unique on `(entity_type, normalized_value, company)`.

**Normalization** collapses variants into one key: lowercase, strip punctuation,
drop legal suffixes (`pvt ltd`, `private limited`, `llp`, `inc`). So
`"ABC pvt limited"`, `"ABC Pvt. Ltd."`, `"ABC PRIVATE LIMITED"` all resolve to the
same alias.

**Resolver:** extract → normalize → lookup. **Hit** → auto-map, high field
confidence, no question. **Miss** → field left unresolved → surfaces in the review
queue → user picks the record once → write the alias row → next identical document
resolves silently.

**Performance:** a net win. The lookup is one indexed read (microseconds) against
an OCR/LLM pipeline measured in seconds, and a hit removes a human round-trip.
Ceiling: the optional fuzzy assist runs only on a miss and scans existing records
(O(N)); prefilter candidates by first token if a record set exceeds ~100k. Misses
shrink as the table fills.

**Native check:** ERPNext Bank Reconciliation does party-matching, but it is
bank-transaction-specific. One small generic alias doctype beats bending it and
also covers company/ledger/currency, not just parties.

---

## Layers (the SOLID seams)

- **`docapture/ocr/`** — bytes → normalized text/blocks JSON. `OCREngine` protocol;
  implementations `pymupdf_extractor` (text-layer + rasterize), `paddle_engine`,
  `tesseract_engine` (fallback); `preprocess` (OpenCV). Knows nothing about
  accounting.
- **`docapture/mappers/`** — OCR JSON → structured DTO + confidence. `LLMParser`
  protocol (vendor-agnostic); `classifier` (source_type); per-target mappers
  `payment_entry_mapper`, `journal_entry_mapper`; `confidence`; the alias resolver.
  Knows nothing about how to OCR.
- **`docapture/router`** — a registry mapping `source_type` → the target mapper +
  creator. Adding a target is a new registry entry + new files, not an edit here.
- **`docapture/creators/`** — DTO → `docstatus=0` draft (`payment_entry_creator`,
  `journal_entry_creator`). Depends only on the DTO (DIP), never on OCR/LLM internals.
- **Dedup** — `content_hash` plus a business-key check (party, amount, date,
  reference) run immediately before creation.

---

## Integration points (and why included or deferred)

| Integration | Status | Why |
|---|---|---|
| PyMuPDF, PaddleOCR, Tesseract, OpenCV | **Phase 2** | Core ingestion; the product is nothing without OCR. |
| `LLMParser` interface | **Phase 3** | The extraction brain. Behind an interface because the vendor is undecided — no hardwired dependency. |
| A concrete LLM vendor (e.g. Claude) | **Phase 3, pluggable** | Recommended but swappable; chosen when needed, not baked into the architecture. |
| ERPNext Payment Entry / Journal Entry | **Phase 4** | Built-in doctypes; we create drafts via the standard API, never reimplement accounting. |
| ERPNext multi-company / multi-currency | **Phase 4, built-in** | We detect + map fields; ERPNext owns the FX and inter-company accounting. |
| Purchase Invoice + three-way matching | **Future** | Needs line items and existing POs/GRNs; deferred until PE/JE prove out. |

---

## Known ceiling (documented, not hidden)

Booking a supplier bill as a Journal-Entry-to-Creditors means a later payment
Payment Entry references a JE rather than an invoice, so reconciliation is clunkier
than the Purchase Invoice path. This is an accepted MVP tradeoff (the user chose
PE/JE-first over Purchase Invoice) and is resolved when supplier bills graduate to
Purchase Invoice in a Future phase.

Frappe core's `frappe/handler.py` `ALLOWED_MIMETYPES` (used by the whitelisted
`upload_file` REST endpoint) omits `image/webp`, and rejects Guest/no-desk-access
uploads outright regardless of `Captured Document`'s own `ALLOWED_EXTENSIONS`.
Inapplicable today — `docapture` uploads only go through the Desk `Attach`
control (System Users, not portal/Guest) — but worth a written flag so it isn't
silently rediscovered if a portal-facing upload path is ever added.
