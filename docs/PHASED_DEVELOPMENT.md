# docapture — Phased Development

Phase-gate process. One phase = one focused, independently testable chunk. A phase
ends at its checkpoint; the next phase does **not** start until the user signs off
(see `CLAUDE.md`). `PHASE_STATUS.md` is the live tracker.

Each phase below lists: **Goal · Scope · Exit criteria · Excluded · Flags.**

---

## Phase 0 — Scaffold

**Goal:** a real, installable `docapture` app on the site.

**Scope:**
- `bench new-app docapture`; install onto `erpnext.yoursite.in`.
- Declare Python deps in `apps/docapture/pyproject.toml`: `pymupdf`, `paddleocr`,
  a Tesseract binding (`pytesseract`), `opencv-python-headless`, `pillow`,
  `rapidfuzz` (used later). Install via bench's venv — no `uv`/`.venv`.
- Seed `docs/PHASE_STATUS.md`.

**Exit criteria:** app installs; `bench --site erpnext.yoursite.in migrate` runs
clean; an empty `run-tests --app docapture` passes.

**Excluded:** any doctype, any OCR, any pipeline code.

**Flags:** none. Cheap and reversible.

---

## Phase 1 — Capture doctype + upload + status

**Goal:** capture a document and move it through its lifecycle by hand (no OCR yet).

**Scope:**
- `Captured Document` doctype (schema per `ARCHITECTURE.md`), with the status flow
  `Uploaded → OCR Done → Parsed → In Review → Approved → Posted` (+ `Rejected`,
  `Failed`).
- `Capture Alias` doctype — **seam only** (fields + unique constraint), no resolver
  logic yet.
- File attach (Frappe File). `content_hash` computed on upload; duplicate check fires.
- Role permissions: uploader vs reviewer.

**Exit criteria:** create a `Captured Document`, attach a file, manually walk it
through the states; a duplicate upload is detected; a basic doctype test passes.

**Excluded:** OCR, LLM parse, alias resolution, draft creation.

> ⚠️ **Expensive to unwind.** The `Captured Document` schema, JSON field shapes, and
> status model are the foundation everything else builds on and are painful to change
> once real data exists. Get them right here.

---

## Phase 2 — OCR layer (`docapture/ocr/*`)

**Goal:** turn an uploaded file into normalized OCR JSON, asynchronously.

**Scope:**
- `OCREngine` protocol.
- `pymupdf_extractor`: detect text layer → extract directly; else rasterize pages.
- `preprocess` (OpenCV): grayscale, orientation correction (coarse 90/180/270,
  not just skew), deskew, denoise, contrast enhancement (CLAHE), threshold —
  computed per-document (Otsu or adaptive), never a fixed constant, since
  lighting/contrast varies per scan.
- `paddle_engine` (primary), `tesseract_engine` (fallback).
- Background job (`frappe.enqueue`) that runs OCR and writes `raw_ocr_json`, moving
  status `Uploaded → OCR Done` (or `Failed` with `error_log`).

**Exit criteria:** upload a digital PDF and a scanned image; each produces
`raw_ocr_json` via the job; per-engine unit tests pass (including the digital-vs-
scanned branch).

**Excluded:** any interpretation of the text (that's Phase 3).

**Flags:** OCR quality on messy scans is inherently variable — preprocessing matters.
Not architecturally expensive, but budget test fixtures for real-world scans.

`Expense Voucher`/`Payment Receipt` sources are often phone photos, not flatbed
scans — deskew alone only corrects small rotation, it does not fix keystone/
perspective distortion from an angled phone shot. Add a perspective-correct
step (detect the document's four corners, warp to a flat rectangle) for that
source type, and a DPI/resolution check that upscales images below the OCR
engine's effective minimum (roughly 150-200 DPI) before running them through
PaddleOCR/Tesseract — both are common, well-understood failure modes for
photographed receipts specifically, not scanned pages.

Job design (bake in when building this phase, matters more once Phase 3 chains
off it):
- Chain stages by enqueueing the next job on completion (or off an
  `on_update`/status-change hook), not by calling the next stage's code
  directly inside the current job. Each job re-checks the doc's current
  `status` before doing work, guarding against a duplicate/stale run if it
  got enqueued twice or the document was rejected mid-flight.
- Use `enqueue_after_commit=True` wherever the enqueue call happens in the
  same request/transaction that just set the status — otherwise the job can
  start before that status write is even committed and read stale state.
- Separate queues (`short` for OCR/lightweight docs, `long` for slow scans or
  LLM calls) so one slow document doesn't block quick ones behind it.

---

## Phase 3 — Mapper / LLM layer (`docapture/mappers/*`)

**Goal:** turn OCR JSON into a structured DTO with confidence, and resolve known
entities automatically.

**Scope:**
- `LLMParser` protocol (vendor-agnostic; recommend Claude, not hardwired).
- `classifier`: detect `source_type`.
- `payment_entry_mapper`, `journal_entry_mapper`: OCR JSON → DTO.
- `confidence`: per-field + overall.
- **Alias resolver:** normalize → `Capture Alias` lookup → auto-map on hit; on miss
  leave the field unresolved for review.
- Writes `extracted_json` + `confidence`, status `OCR Done → Parsed → In Review`.

**Exit criteria:** OCR JSON produces a structured DTO with confidence; the classifier
routes each source type correctly; a value already in `Capture Alias` auto-maps with
no prompt; fixture-document tests pass.

**Excluded:** the review UI and actual draft creation (Phase 4); fuzzy assist (Future).

> ⚠️ **Expensive to unwind.** The router/target-registry abstraction and the DTO
> contract must be pluggable so a Purchase Invoice target adds cleanly later. A rigid
> `if source_type ==` design here is costly to undo.

---

## Phase 4 — Review queue + draft creation

**Goal:** a human approves a capture and the correct draft appears, linked and
dedup-checked.

**Scope:**
- Review queue: filtered List View of `In Review` captures with approve/reject
  actions; reviewer can fix unresolved fields and confirm aliases (writing new
  `Capture Alias` rows).
- `docapture/router` registry; `creators/payment_entry_creator`,
  `creators/journal_entry_creator`: DTO → `docstatus=0` draft.
- Dedup check (`content_hash` + party/amount/date/reference) before creation.
- Multi-company / multi-currency field mapping onto the draft (ERPNext owns the
  accounting).
- Audit link: `target_doctype` + `target_docname`; status `Approved → Posted`.
- **Everything goes through the queue — no auto-post, no auto-draft.**

**Exit criteria:** approve a captured document → the correct Payment Entry or
Journal Entry draft is created, linked back, respects company/currency, and a
duplicate is blocked; end-to-end test from upload through draft passes.

**Excluded:** auto-draft thresholds, Purchase Invoice, line items, three-way matching.

**Flags:** this is the first phase that writes to the ledger space (as drafts). Keep
the "everything to review" guarantee intact — it's the product's trust story.

When the pre-creation dedup check finds a business-key match, the existing
draft is never touched or deleted — the blocked capture instead lands in a
distinct outcome (e.g. `status = Rejected` + `error_log` naming the colliding
`target_doctype`/`target_docname`) so a human decides: genuine duplicate, or a
real second transaction that happens to match, in which case they override.
No draft ever gets created or removed automatically either way.

---

## Phase 5+ — Future (Should-Have / Nice-to-Have)

Not scheduled; each becomes its own phase when prioritized.
- **Fuzzy alias assist** (`rapidfuzz` pre-selection on a miss).
- **Auto-draft above a confidence threshold** (deliberately out of v1).
- **Bank-statement multi-line splitting** (one statement → many Payment Entries).
- **Purchase Invoice target + line items + three-way matching** — the real AP path;
  where line items finally have a home.
- **Vertical document types** (pharma COA, steel test certificates).
- **Feedback / learning loop** from reviewer corrections.

> ⚠️ **Expensive to unwind (forward-looking).** Purchase Invoice changes the data
> model (line items) and the reconciliation story. The Phase 1 schema and Phase 3
> registry are designed to absorb it — honor those seams so this phase stays additive.
