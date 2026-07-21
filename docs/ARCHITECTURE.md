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
  • Bank Statement only: Resolve Unknowns (docapture/resolve.py) — asks once
    per *unique* unresolved counterparty/date/duplicate, not once per row
    (a 190-row statement can share a handful of distinct unknowns); answers
    write Capture Alias rows the same way Preview corrections do
  • Preview (docapture/review.py) — reviewer inspects every field/row,
    fixes anything wrong, confirms aliases; always available, not just for
    Bank Statement
  • approve
  ▼
Router → Creator (docapture/creators/*)
  • dedup check (Docapture Posting audit trail: party/amount/date/reference)
  • DTO → Payment Entry OR Journal Entry at docstatus=0
  • Bank Statement: one Journal Entry per transaction row (not grouped by
    date, not one per statement) — the whole per-row loop runs inside a DB
    savepoint, so a mid-loop failure rolls back every JE that attempt
    already inserted, never leaving a partial/un-audited draft behind
  │  links target_doctype + target_docname, appends Docapture Posting
  │  status: Approved → Posted (or Rejected if every row was a dedup hit)
  ▼
[ERPNext draft accounting document]  (human submits it in ERPNext as usual)

  ⤷ On failure: status → Failed, error_log holds the traceback. A reviewer
    fixes the actual cause (e.g. a missing default account) and clicks
    Retry (docapture/router.py::retry) — resets straight back to In Review
    with extracted_json untouched, no re-upload/re-OCR/re-LLM-call needed.
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
| `exchange_rate` | Float | 1 statement-currency unit = this many of the company's currency; set via the Resolve Unknowns dialog, only used when they differ |
| `raw_ocr_json` | Long Text | normalized OCR text/blocks |
| `extracted_json` | Long Text | structured mapper DTO |
| `confidence` | Float | overall extraction confidence |
| `content_hash` | Data (indexed) | dedup key over file content |
| `status` | Select | workflow state (below) |
| `target_doctype` | Data | created draft's doctype (single-draft source types only) |
| `target_docname` | Dynamic Link | created draft's name (audit link, single-draft source types only) |
| `postings` | Table (Docapture Posting) | one row per draft actually created or dedup-collision skipped — the audit trail for the Bank Statement one-JE-per-row case, where `target_doctype`/`target_docname` alone can't represent "many drafts from one capture" |
| `error_log` | Long Text | failure detail when `status = Failed`; cleared on Retry |

**Status flow:** `Uploaded → OCR Done → Parsed → In Review → Approved → Posted`,
plus `Rejected` as a terminal side-state and `Failed` as a *recoverable*
side-state — `router.py::retry()` sends `Failed → In Review` (clearing
`error_log`, leaving `extracted_json` untouched) so a reviewer fixes the
actual cause and re-approves without redoing OCR/LLM extraction.

> ⚠️ **Expensive to unwind.** The `Captured Document` schema, the JSON shapes, and
> the status model are hard to change once real captures exist. Settle them in
> Phase 1 before data accumulates.

### `Capture Alias` (learned mapping memory)
Generic, cross-field lookup so a value resolved once is never re-asked.

| Field | Type | Purpose |
|---|---|---|
| `entity_type` | Select | Company / Customer / Supplier / Employee / Account / Bank Account / Mode of Payment / Currency |
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

**Bank Statement row identity isn't always a name.** A row can have no
`counterparty_name` at all — just a bare bank reference code ("TRF
201-54921") or a tax-payment narration. `docapture/resolve.py`'s
`_row_identifier()` falls back to `narration`, then `reference_no`, so
these still get a Resolve Unknowns question and a Capture Alias entry;
`bank_statement_mapper.py::_resolve_row()` mirrors the same fallback for
auto-resolving a future document. entity_type `Account` does double duty
here — a reviewer's "Internal Transfer" or "Other (bank charge/tax/fee)"
answer resolves against `Account`, not a party doctype, since that row
isn't a real counterparty at all; `journal_entry_creator.py` posts straight
to the picked account with no `party_type`/`party` in that case.

### `Docapture Posting` (child table, on `Captured Document.postings`)
The audit trail `dedup.py` checks against — one row per draft actually
created (`status = Draft`) or per business-key collision skipped
(`status = Rejected`). Exists because a date-grouped or one-per-row Bank
Statement capture can produce *many* drafts from one `Captured Document`,
which the single `target_doctype`/`target_docname` pair can't represent.

| Field | Type | Purpose |
|---|---|---|
| `target_doctype` / `target_docname` | Data / Dynamic Link | the draft this row is about |
| `status` | Select | Draft / Rejected |
| `party`, `amount`, `posting_date`, `reference` | — | the business key this row was keyed/deduped on |
| `note` | Data | e.g. `"Duplicate of existing Journal Entry ACC-JV-..."` |

Scoped to `Docapture Posting`'s own rows only — never the general ledger —
so a legitimate second transaction that happens to share a business key
with something posted through a different path is never blocked.

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
- **`docapture/router.py`** — whitelisted API surface + a `source_type` → creator
  registry (`_CREATE_BY_SOURCE_TYPE`). Adding a target is a new registry entry +
  new creator file, not an edit to an if/else chain. Owns loading/saving the
  `Captured Document` itself; delegates the actual logic to `review.py`/`resolve.py`/
  the creators. Endpoints: `preview`/`save_corrections` (per-row correction dialog),
  `unknowns`/`save_resolutions` (Resolve Unknowns, Bank Statement only),
  `approve`/`reject`/`retry`.
- **`docapture/review.py`** — pure functions (no DB access) turning a parsed
  `extracted_json` into the Preview dialog's shape and applying reviewer
  corrections back into it; DTO-shape-agnostic (branches on `rows`/`transactions`
  key presence, not `source_type`).
- **`docapture/resolve.py`** — Bank Statement's "Resolve Unknowns" step. Unlike
  `review.py`, this one *does* touch `frappe.db` (dedup lookups, bank-account
  resolution), so it stays a separate module to keep `review.py`'s pure-functions
  contract true. `unknowns_summary()` reads; `apply_resolutions()`/
  `alias_specs_from_resolutions()` are themselves pure.
- **`docapture/creators/`** — DTO → `docstatus=0` draft (`payment_entry_creator`,
  `journal_entry_creator`, plus shared `accounts.py`/`fields.py` helpers). Depends
  only on the DTO (DIP), never on OCR/LLM internals.
- **`docapture/dedup.py`** — business-key lookup (party/amount/date/reference)
  against `Docapture Posting` only, run immediately before creation.
- **`docapture/postings.py`** — appends a `Docapture Posting` row per draft
  created or dedup collision skipped.
- **`docapture/notify.py`** — bell-icon Notification Log to every System
  Manager/Docapture Reviewer on a pipeline failure.

---

## Integration points (and why included or deferred)

| Integration | Status | Why |
|---|---|---|
| PyMuPDF, PaddleOCR, Tesseract, OpenCV | **Phase 2** | Core ingestion; the product is nothing without OCR. |
| `LLMParser` interface | **Phase 3** | The extraction brain. Behind an interface because the vendor is undecided — no hardwired dependency. `temperature=0` on every call (both `OpenAIParser`/`ClaudeParser`) — structured extraction has no business sampling creatively; ambiguous calls (e.g. "is this bare digit string a name?") were answering differently run-to-run before this. |
| A concrete LLM vendor (e.g. Claude) | **Phase 3, pluggable** | Recommended but swappable (`llm_backend` site config); chosen when needed, not baked into the architecture. |
| ERPNext Payment Entry / Journal Entry | **Phase 4, built** | Built-in doctypes; we create drafts via the standard API, never reimplement accounting. Bank Statement posts one Journal Entry per row (`voucher_type = "Bank Entry"`), not one per statement or grouped by date. |
| ERPNext multi-company / multi-currency | **Phase 4, built** | We detect + map fields (`Captured Document.exchange_rate`, set via Resolve Unknowns); ERPNext owns the FX math and inter-company accounting (`multi_currency` flag set only when the resolved rate isn't 1). |
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

**Resolve Unknowns matches by exact text, not by real-world identity.** Two
rows referencing the same underlying account number but worded differently
by the bank ("TRF 312801010037001" vs "eTXN/To:312801010037001") surface as
two separate questions, not one — `_row_identifier()` groups by literal
`counterparty_name`/`narration`/`reference_no` text, with no embedded-number
extraction across differently-worded narrations. Deliberate, not an
oversight: merging by a shared digit substring risks conflating two
genuinely different parties that happen to share digits. Revisit only with
real evidence this costs more repeat-questions than the false-merge risk is
worth.

**This app's own test suite must never run against a real working site.**
`bench run-tests`' `IntegrationTestCase` rolls back its DB transaction when
a test class finishes — running it against `erpnext.yoursite.in` (rather
than a dedicated `docapture-test.localhost`) once wiped a full session's
real captures/aliases/Journal Entries. `apps/docapture/.claude/CLAUDE.md`'s
Hard Constraints now say this explicitly.
