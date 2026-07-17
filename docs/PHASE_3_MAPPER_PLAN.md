# Phase 3 Mapper Plan — `docapture/mappers/*`

Status: implementation complete, pending manual-test pass and user sign-off.
All 4 `source_type` fixtures acquired, classifier calibrated against them.

See also: `docs/manual_test/phase-3-mapper-llm-layer.md` — this doc
explains the *design*; that one is the manual checklist for *verifying*
it works. Neither is the complete picture alone.

## File layout (`docapture/mappers/`)

`schema.py` (DTOs — `FieldValue`, `PaymentEntryDTO`, `JournalEntryDTO`,
`BankStatementDTO`), `layout.py` (`reconstruct`, `reconstruct_pages`),
`llm_client.py` (`LLMParser` protocol — `extract_fields` +
`extract_rows` — `get_parser()` — the config-driven factory pipeline.py
calls instead of importing a concrete class, plus
`build_schema`/`build_prompt`/`build_row_schema`/`build_row_prompt`, the
vendor-agnostic schema/prompt shapes shared by every concrete client,
factored out once a second one existed), `claude_client.py`
(`ClaudeParser`), `openai_client.py` (`OpenAIParser`), `classifier.py`
(`classify`), `payment_entry_mapper.py` / `journal_entry_mapper.py`
(`FIELDS` + `build_dto`), `bank_statement_mapper.py` (`FIELDS` +
`ROW_FIELDS` + `build_dto` — a table of a-priori-unknown row count, one
`extract_rows` call per page via `reconstruct_pages` rather than the
single-transaction/fixed-row shape the other two mappers use),
`alias_resolver.py` (`normalize`/`resolve`/`resolve_extracted`),
`pipeline.py` (`run_mapper`, chained off `docapture/ocr/pipeline.py`'s
`run_ocr` via `frappe.enqueue`).

**LLM backend: `OpenAIParser` (`gpt-4.1`) by default, chosen via
`llm_client.get_parser()`, not hardcoded.** No Anthropic API key was
available in this environment; an OpenAI key was, so the default backend
is OpenAI. Rather than have `pipeline.py` import a specific concrete
class directly, `llm_client.get_parser() -> LLMParser` reads
`site_config.json`'s `llm_backend` (`"openai"` default, `"claude"` the
alternative) and returns the matching client — `pipeline.py` only ever
holds an `LLMParser`, never knows which vendor backs it (Liskov
substitution applied at the one call site that constructs one, not by
turning the `Protocol` into an inheritance hierarchy — Python's structural
typing already gives every `LLMParser` implementer interchangeability
without a shared base class, see `docs/DESIGN_PRINCIPLES.md`'s L section).
Swapping vendor, or trying `gpt-5` vs `gpt-4.1` at the deploy level, is now
a `bench set-config llm_backend claude` away — zero code edits.
`claude_client.py` is kept (still covered by `test_claude_client.py`) as
the second implementation `get_parser()` switches to. `openai_client.py`
uses the OpenAI Responses API (`client.responses.create`, `text.format` =
`{"type": "json_schema", "strict": true, ...}`) — the SDK's
structured-output equivalent of Claude's `output_config.format`. Model is
a swap-if-quality-warrants choice, not calibrated: try `gpt-4.1` first,
fall back to a stronger model if extraction accuracy on messy OCR text
falls short.

**LangSmith tracing:** both `ClaudeParser`/`OpenAIParser` wrap their
*default* client (`wrap_anthropic`/`wrap_openai` from `langsmith.wrappers`)
— only when a caller doesn't inject its own (tests always inject a fake,
so test assertions on `call_args` still see the unwrapped double, and no
tracing/network side effect leaks into a test run). Controlled purely by
env vars (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` —
see `.env.example` at the bench root); off (`LANGSMITH_TRACING=false` or
unset) is a no-op wrapper, not a code path that needs disabling.

**Explicit `.flush()` after every call — required, not optional.**
`frappe.enqueue` jobs run under RQ, which forks a child process per job and
`os._exit(0)`s it once the job returns (`rq/worker.py`). That skips
Python's `atexit` hooks entirely, including the one LangSmith's `Client`
normally relies on to flush its background send queue — without an
explicit flush, every trace from a background job (i.e. every real trace
this app produces, since `run_mapper` only ever runs as an enqueued job)
gets stuck "pending" in the LangSmith UI: it recorded a start but the
end/output event never made it out before the process was hard-killed.
Fix: `llm_client.new_tracer()` hands each parser its own `langsmith.Client`
(passed into `wrap_anthropic`/`wrap_openai` via `tracing_extra={"client":
...}`), and `extract_fields()` calls `tracer.flush()` synchronously right
after building its result, before returning to the job. Safe to call
unconditionally — a no-op when tracing is off or nothing was queued.

No standalone `confidence.py` — an earlier draft of this plan named one for
"per-field + overall scoring, shared by both mappers." That landed inside
`schema.py` instead (`FieldValue`, `overall_confidence()`,
`DTO.confidence`) once built: the scoring logic is one small property
directly on the DTO it scores, and a separate file would have been a
single-function module with one caller shape repeated twice.

## Decision: FIELDS is a hardcoded, hand-curated superset per mapper

Field list per target (`payment_entry_mapper.py`, `journal_entry_mapper.py`)
is a hardcoded `FIELDS` constant, not a configurable doctype — matches
`PHASED_DEVELOPMENT.md`'s existing `source_type` → mapper → DTO design.
Isolated at the top of each mapper file, separate from the function that
uses it, so a future pivot to configurable fields is a contained refactor,
not a rewrite.

**Why not derive FIELDS from ERPNext doctype meta:** audited Payment Entry
/ Journal Entry JSON + controller code
(`apps/erpnext/erpnext/accounts/doctype/{payment_entry,journal_entry}/`).
Most conditional-requiredness — `party_type`/`party` only for
Receivable/Payable accounts, `exchange_rate` only when account currency ≠
company currency, `reference_no`/`reference_date` only for Bank accounts —
lives in Python `validate()` logic, not in JSON `reqd` flags. A field list
auto-generated from doctype meta would be actively wrong. Resolution: the
mapper doesn't replicate ERPNext's mandatory-field logic. `FIELDS` is a
superset that opportunistically extracts domain-relevant fields (including
conditionally-mandatory ones like `party_type`, `exchange_rate`,
`reference_no`) with per-field confidence; true requiredness is enforced by
ERPNext itself when Phase 4's creator inserts the `docstatus=0` draft, and
anything missing/low-confidence surfaces in the human review queue first.

## Text reconstruction: `layout.py`

`raw_ocr_json` is structured-only (pages → lines → words + pixel boxes, per
Phase 2) — no page/document-level flattened text anywhere in the schema or
OCR code. `layout.py::reconstruct(ocr_json) -> str` is the named step that
does this for Phase 3: order lines top-to-bottom by `bbox` y-coordinate,
left-to-right within a horizontal band (so multi-column content — e.g. a
letterhead with company info left and document title/number right, or a
label-left/value-right bill layout — doesn't interleave). Both mappers call
it before building their prompt; not duplicated per mapper.

## Naming: `build_dto` vs `extract_fields`

Two calls previously risked sharing the name `parse` across layers:
- `<target>_mapper.build_dto(ocr_json, llm) -> <Target>DTO` — owns
  `layout.reconstruct`, prompt-building (from `FIELDS`), and DTO assembly.
- `LLMParser.extract_fields(prompt_text, field_specs) -> dict` — the one
  vendor-swappable call that actually talks to an LLM API. Narrower than
  `DESIGN_PRINCIPLES.md:43`'s original `LLMParser.parse(ocr_json,
  source_type) -> dto` (that signature bundled prompt-building, layout
  handling, and DTO assembly into one call). `DESIGN_PRINCIPLES.md:43` is
  updated to match as part of this phase's own diff.

Call sequence: `pipeline.py` → `classifier.classify(ocr_json, llm)` →
`<target>_mapper.build_dto(ocr_json, llm)` → (`layout.reconstruct` →
`build_prompt` → `llm.extract_fields` → `alias_resolver.resolve_extracted` →
`assemble`) → writes `extracted_json = dto.to_json()`, `confidence =
dto.confidence` → status `OCR Done → Parsed → In Review`.

## Classifier: heuristic-first, not a second LLM call

`classifier.classify(ocr_json, llm)` runs a rule-based/keyword scorer over
`layout.reconstruct(ocr_json)` first — an LLM-based classifier would double
API cost per document (one call to classify, one to extract) for a 4-way
decision keyword scoring can likely handle. Falls back to one LLM
classification call only if the heuristic's top score is below a
threshold.

**Threshold calibration method:** tune against the fixture set (below)
until zero misclassifications, same fixture-driven approach as Phase 2's
DPI/threshold work. **Update policy: this section is edited in place with
the real number once calibration runs — not addended.** The dated history
of that change belongs in `PHASE_STATUS.md`'s append-only log, not stacked
here.

**Known v1 limitation:** calibration ran against exactly 5 documents — the
4 real `source_type` fixtures (one positive example each) plus the Sales
Order fixture as the one negative case. This is a
zero-misclassifications-on-5-documents result, not a general robustness
claim — same spirit as "a false negative in practice is a calibration bug
to fix" below. More real-world documents will surface edge cases (a bank
statement that says "opening balance" instead of "previous balance", a
receipt that omits "receipt number") this fixture set doesn't cover.

**Calibrated keyword vocabulary** (`classifier.KEYWORDS`, drawn from
actually OCR-ing all 5 fixtures — two earlier draft assumptions, "received
with thanks"/"receipt no." for Payment Receipt and "expense head" for
Expense Voucher, turned out not to appear in the real documents at all and
were replaced):
- Bank Statement: `"withdrawals"`, `"deposits"` — originally `"previous
  balance"`/`"withdrawals"`, recalibrated after a real Union Bank of India
  statement (`sample_bank_statement_ubi.pdf`, title "Statement of Account")
  scored only 0.5 under the old pair (no "previous balance" phrase anywhere)
  and fell through to the LLM fallback, which misclassified it as Payment
  Receipt. `"withdrawals"`/`"deposits"` are the transaction table's own
  column headers, present in both the original stock fixture and the real
  UBI statement — proof that per-field semantic hints (not literal per-bank
  column strings) generalize, but the *classifier's* keyword list is still
  literal string matching and needs the same "real formats vary" caveat:
  the next bank statement with different column headers (e.g. "Debit"/
  "Credit") is a calibration bug to fix, not a false negative to route
  around silently.
- Payment Receipt: `"payment receipt"`, `"receipt number"`.
- Supplier Bill: `"invoice"`, `"bill to"`.
- Expense Voucher: `"expense voucher"`, `"payment method"`.

`CLASSIFICATION_THRESHOLD = 0.6`. Score is `(keywords found) /
(keywords in that type's list)` — 2-item lists, so a real match scores 1.0
(both phrases present) and 0.6 sits well clear of the worst observed
cross-contamination (Expense Voucher's fixture also contains "bill to",
scoring 0.5 against Supplier Bill's list — still loses to Expense
Voucher's own 1.0 via argmax, but noted here since it's a real, not
theoretical, near-miss). The Sales Order negative case scores 0 against
every type's list, correctly falling back to the LLM rather than being
confidently misclassified.

## Fixtures

- **Sales Order** (`tests/fixtures/ocr/sales_order_page1/`) — existing,
  genuinely multi-column (letterhead: company info left, "Sales
  Order"/order-number right, same vertical band). Used for the
  `layout.reconstruct` reading-order test. Not shaped like any docapture
  `source_type`, so it can't drive classifier calibration.
- **Bank Statement** (`sample_bank_statement.png`) — stock/generic sample
  ("First Bank of Wiki", fictional bank, placeholder name/address/account
  number, verified fixture-safe). PNG → exercises the rasterize-then-OCR
  branch (PaddleOCR/Tesseract), not PyMuPDF's text-layer branch.
  Repeated-row transaction table with running balance — a different
  document geometry from the Sales Order fixture, good for
  stress-testing `layout.reconstruct` against a second shape.
- **Bank Statement, real-world** (`sample_bank_statement_ubi.pdf`) — a real
  Union Bank of India "Statement of Account", 9 pages, ~190 transaction
  rows, born-digital PDF (PyMuPDF native text-layer branch, not raster
  OCR). Added when the single-transaction fixture above proved insufficient
  to catch two real gaps: the classifier's original keyword pair
  misclassified this document (see "Classifier" above), and the
  single-transaction `PaymentEntryDTO`/fixed-2-row `JournalEntryDTO` shapes
  can't represent a variable-length transaction table at all — this fixture
  drove `BankStatementDTO` + `bank_statement_mapper.py` +
  `LLMParser.extract_rows`.
- **Expense Voucher** (`sample_Expense_Voucher.png`) — stock template
  (placeholder name/address/email, 555 phone number, a far-future "date
  signed"; verified fixture-safe).
- **Supplier Bill** (`sample_supplier_bill.png`) — stock template
  (bracketed placeholder fields throughout: `[name]`, `[street address]`,
  `[123456]`; verified fixture-safe).
- **Payment Receipt** (`sample_payment_reciept.webp`) — stock template
  (placeholder name/address/email, 555 phone number; verified
  fixture-safe). First `.webp` fixture in the app — see "WEBP support"
  below.

All 4 `source_type` fixtures are now in hand; classifier calibration ran
against all 5 (4 positive + the Sales Order negative).

## WEBP support

`sample_payment_reciept.webp` needed `.webp` added to
`Captured Document.ALLOWED_EXTENSIONS`
(`docapture/docapture/doctype/captured_document/captured_document.py`) and
the matching client-side `allowed_file_types` list
(`captured_document.js`) — both previously excluded it. Everything past
that point was already format-agnostic: this bench's
`opencv-contrib-python==4.10.0.84` build decodes WEBP correctly (bundled
libwebp, empirically verified), and `docapture/ocr/pipeline.py`,
`preprocess.py`, `paddle_engine.py`, `tesseract_engine.py` all operate on
already-decoded numpy arrays regardless of source format.

Checked for a third gate beyond the two allowlists: Frappe core's `File`
doctype (`validate()`, `validate_file_extension()`, `pdf_contains_js`,
`strip_exif_data`, thumbnail generation via generic `PIL.Image.open()`,
mimetype detection) has none — Pillow 12.2.0 in this venv has WEBP support
built in. One real gate exists but doesn't apply:
`frappe/handler.py`'s `ALLOWED_MIMETYPES` (used by the whitelisted
`upload_file` REST endpoint) omits `image/webp`, but only fires for Guest
or no-desk-access users; `docapture` uploads go through the Desk `Attach`
control (System Users), so it never triggers here — flagged in
`docs/ARCHITECTURE.md`'s "Known ceiling" section for future-proofing.

## Routing

- `Payment Receipt` → `payment_entry_mapper`
- `Supplier Bill`, `Expense Voucher` → `journal_entry_mapper`
- `Bank Statement` → `bank_statement_mapper` (not `payment_entry_mapper`,
  despite both originally targeting the same mapper). A bank statement's
  rows become one Journal Entry each (bank leg + counter-account leg) in
  Phase 4, not a Payment Entry — plenty of real rows (self-transfers
  between the account holder's own sub-accounts, GST/TDS/ESIC payments,
  bank interest/fees) have no Customer/Supplier party at all, which
  Payment Entry requires and Journal Entry doesn't. `BankStatementDTO.
  to_json()` sets `target_doctype: "Journal Entry"` accordingly.

## Bank Statement: variable-length table extraction

Unlike the other three source types (one document → one transaction, or a
fixed 2-row journal entry), a bank statement is a table of an a-priori
unknown number of rows — anywhere from a handful to hundreds. Neither
`PaymentEntryDTO` (one flat set of fields) nor `JournalEntryDTO` (fixed at
exactly 2 rows) can represent that, and `LLMParser.extract_fields` can only
return one flat dict per call — there was no capability anywhere in Phase 3
to ask an LLM for a variable-length array of row-objects. Discovered via a
real fixture (`sample_bank_statement_ubi.pdf`): running the existing
`payment_entry_mapper` against it captured exactly one transaction (the
statement's first row) and silently dropped the other ~189.

**Fix, kept bank-format-agnostic on purpose** (a different bank's column
names/layout must not require new code): `ROW_FIELDS` in
`bank_statement_mapper.py` is a list of *canonical* target field names with
semantic hints (`date`, `narration`, `reference_no`, `withdrawal`,
`deposit`, `balance`, `counterparty_name`) — the same technique the
existing `FIELDS` lists already use for single-field extraction, extended
to a whole row. The LLM maps whatever the source calls its columns
("Withdrawals" vs "Debit" vs "Dr Amt") onto these canonical fields; nothing
in this app hardcodes a literal per-bank column string.

- `LLMParser.extract_rows(prompt_text, field_specs) -> list[dict]` — new
  Protocol method alongside `extract_fields`, same per-field
  `{value, confidence}` contract, implemented in both `OpenAIParser` and
  `ClaudeParser` via `build_row_schema`/`build_row_prompt` (a JSON schema
  wrapping the row array in `{"rows": [...]}`, since structured-output APIs
  expect an object at the schema root, not a bare array).
- `layout.reconstruct_pages(ocr_json) -> list[str]` — per-page text,
  alongside the existing whole-document `reconstruct()`.
  `bank_statement_mapper.build_dto` calls `extract_rows` once per page
  (concatenating results) rather than once for the whole document — a
  9-page, ~190-row statement risks context/accuracy limits on a long table
  in a single LLM call.
- `counterparty_name` resolves against `Capture Alias` trying `Customer`
  then `Supplier` (in that fixed order — a `ponytail:` simplification;
  ERPNext's own `auto_match_party.py` picks the trial order from the
  deposit/withdrawal sign instead, worth adopting here if this order causes
  real mismatches). This is also why `Capture Alias.entity_type` gained a
  `Customer` option — it previously only had `Company`/`Supplier`/
  `Account`/`Bank Account`/`Mode of Payment`/`Currency`.
