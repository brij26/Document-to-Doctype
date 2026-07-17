# docapture — Phase Status

**Read this first, every session, before any other action.**

Source of truth for the current phase and status. Update it at every phase
transition. Status values: `Not Started` · `In Progress` · `Awaiting Review` ·
`Approved`.

Only set a phase to `Approved` after **explicit user sign-off** (see `CLAUDE.md`).

| Phase | Title | Status |
|---|---|---|
| 0 | Scaffold | Approved |
| 1 | Capture doctype + upload + status | Approved |
| 2 | OCR layer (`ocr/*`) | Approved |
| 3 | Mapper / LLM layer (`mappers/*`) | Awaiting Review |
| 4 | Review queue + draft creation | Not Started |
| 5+ | Future (Should / Nice-to-Have) | Not Started |

---

## Current focus

**Phase 3 — Awaiting Review.** Mapper / LLM layer (`mappers/*`) complete —
`schema.py`, `layout.py`, `llm_client.py`/`claude_client.py`,
`classifier.py`, both mappers' `FIELDS` + `build_dto`, `alias_resolver.py`,
`pipeline.py`. All 4 `source_type` fixtures acquired and classifier
calibrated against them. See `docs/PHASE_3_MAPPER_PLAN.md` for the full
design rationale. Awaiting user sign-off before Phase 4.

## Log

- Planning complete; awaiting user go-ahead to start Phase 0.
- 2026-07-14: user said go. Phase 0 started.
- 2026-07-14: `docapture` app scaffolded, installed on `erpnext.yoursite.in`,
  deps declared and installed via bench venv, migrate clean, empty
  `run-tests` passes, `ruff check` clean. Phase 0 → Awaiting Review.
- 2026-07-14: user approved. Phase 0 → Approved.
- 2026-07-14: user said start Phase 1. Phase 1 started.
- 2026-07-14: Phase 1 built — `Captured Document` + `Capture Alias` doctypes,
  `Docapture Uploader`/`Docapture Reviewer` roles, content_hash dedup check,
  status walk + duplicate tests. `migrate`, `run-tests --app docapture`, and
  `ruff check` all clean. Phase 1 → Awaiting Review.
- 2026-07-14: review feedback — `content_hash` dedup check was blocking a
  re-upload of an identical file forever, even after the original capture was
  `Rejected`/`Failed`. Fixed: dedup check now excludes those two terminal
  states, so a re-upload after rejection reruns the chain instead of staying
  blocked. Added `test_reupload_allowed_after_rejection`; `run-tests` (3/3)
  and `ruff check` still clean. Also documented (docs-only, no code): job
  chaining/`enqueue_after_commit`/queue-split notes on Phase 2, and the
  blocked-duplicate outcome state on Phase 4.
- 2026-07-14: user approved. Phase 1 → Approved.
- 2026-07-16: user approved the Phase 2 OCR-layer plan. Phase 2 started.
  Decisions taken into the phase: (a) `raw_ocr_json` is one normalized shape for
  both engines — pages → lines → words, integer pixels at 200 DPI, single Long
  Text field; (b) text-layer detection is **per page**, so a mixed PDF gets
  per-page `engine`/`confidence_source`/`word_tokenization` discriminators; (c) no
  punctuation-normalizing pass — each page declares its own grain via
  `word_tokenization`, whitespace uniformly dropped; (d) `paddleocr==3.7.0` and
  `onnxruntime==1.27.0` pinned. Verified in bench's real venv (Python 3.14.6):
  `pip install --dry-run` resolves 62 packages with **no paddlepaddle** —
  `paddlex[ocr-core]` does not pull it transitively, closing the cp314 blocker
  outside Colab for the first time. Also verified `Sales order.pdf` is genuinely
  born-digital (Skia/PDF, 194 words, 0 images), so it is a valid PyMuPDF-branch
  fixture. Open at start: two OpenCV builds installed (`opencv-contrib-python`
  from paddlex vs our declared `opencv-python-headless`) — to be resolved in this
  phase; and a phone-photo fixture (synthetic first, real photo required before
  sign-off).
- 2026-07-16: Phase 2 built — `docapture/ocr/{engine,schema}.py` (the `OCREngine`
  protocol + `raw_ocr_json` DTO helpers), `pymupdf_extractor.py` (per-page text-layer
  detection, native word/line extraction scaled to 200 DPI, rasterize fallback),
  `preprocess.py` (grayscale, coarse 90/180/270 orientation via Tesseract OSD, deskew,
  denoise, CLAHE, per-doc Otsu/adaptive threshold, perspective correction for phone-photo
  source types, DPI upscale check), `paddle_engine.py` (PP-OCRv6_medium, cached
  singleton), `tesseract_engine.py` (fallback), and `pipeline.py` (orchestrates all of
  the above, writes `raw_ocr_json`, status `Uploaded → OCR Done`/`Failed`, re-checks
  status before running). Wired via a new `after_insert` hook on `Captured Document`
  (`enqueue_after_commit=True`, `queue="long"`).
  Fixed an open item from Phase 2 kickoff: `opencv-python-headless` and
  `opencv-contrib-python` were both installed and silently sharing the same `cv2`
  import — pyproject now declares only `opencv-contrib-python==4.10.0.84` (matching
  paddlex's own transitive pin), reinstalled clean, single `cv2` build confirmed.
  Caught and fixed a real bug during testing: `preprocess.deskew`'s minAreaRect angle
  read ~90° on an already-upright, full-page multi-line document (the ambiguity
  between "long side is the page width" vs "...is the page height" for a foreground
  mass that fills most of the page) and rotated it a full 90° instead of leaving it
  alone. Normalized the angle into (-45°, 45°] before applying the correction; added
  a regression test (`test_deskew_does_not_rotate_an_already_upright_dense_document`)
  using the real fixture image.
  Checks: `bench --site erpnext.yoursite.in run-tests --app docapture` — 24/24 pass
  (17 unit + 7 integration); `ruff check .` clean; `bench --site erpnext.yoursite.in
  migrate` clean (no schema changes this phase).
  Exit criteria: a born-digital PDF (`Sales order.pdf` fixture) produces
  `raw_ocr_json` via `pymupdf`'s native path; a scanned/photographed image
  (`input.jpg` fixture) produces it via the PaddleOCR PP-OCRv6_medium engine or the
  tesseract fallback; per-engine unit tests pass, including the digital-vs-scanned
  branch. **Correction (see 2026-07-16 follow-up entry below): the "ran for real"
  claim here was wrong — a bug made every raster page silently fall back to
  tesseract. Now fixed.**
  Two disclosed simplifications (Design Principles §"Pragmatic exceptions"):
  (a) OCR jobs always enqueue on the `long` queue — the `short`/`long` split floated
  in this phase's scope note was collapsed to just `long`, since there is only one
  job type today and no lightweight job exists yet to justify routing logic (YAGNI;
  add the split when a second, genuinely lightweight job type exists).
  (b) The DPI/resolution upscale check for bare raster uploads (`ensure_min_dpi`)
  estimates effective DPI against an assumed A4/Letter physical width, since a raw
  image carries no physical-size metadata — flagged in-code with a `ponytail:`
  comment; upgrade path is reading DPI from EXIF when present or reviewer-confirmed
  physical size.
  Known gap carried forward (unchanged from kickoff): the phone-photo perspective
  fixture is still synthetic, not a real photo — real-photo validation remains
  outstanding before this phase can be considered fully proven on that path.
- 2026-07-16 (follow-up): user asked how to tell which OCR engine produced a
  result, then why it was using tesseract instead of paddleocr — surfaced a real
  bug via `.claude/skills/paddleocr-debug`. `preprocess.preprocess_page()` returns
  a 2D grayscale/binarized array; PaddleOCR's internal resize step unconditionally
  unpacks `img.shape` as `(H, W, C)` and raised `ValueError` on every single raster
  page, so `pipeline.py`'s `except: tesseract_engine` fallback fired every time —
  PaddleOCR had never actually run through the real pipeline, contrary to what the
  entry above claimed. Root cause was invisible because the fallback's
  `except Exception:` logged nothing. Fixed: `paddle_engine.extract_page()` now
  converts a 2D input to 3-channel BGR before calling `.predict()`; `pipeline.py`
  now calls `frappe.log_error` on a paddle failure before falling back, so a
  regression is visible instead of silent. Tightened
  `test_scanned_image_produces_ocr_engine_page` to assert `engine == "paddleocr"`
  outright, and added `test_extract_page_accepts_grayscale_2d_input` as the
  regression test. `run-tests --app docapture` and `ruff check` both clean after
  the fix.
- 2026-07-16 (follow-up 2): per-engine preprocessing split, decided with the user
  after discussing that paddle is a deep model (trained on natural grayscale/color
  images, not our hard-binarized output) while tesseract is a classic algorithm
  that wants binarization and has no preprocessing of its own. `preprocess.py` now
  has `preprocess_for_paddle()` (DPI upscale + phone-photo perspective correction
  only, stays color) alongside the existing full `preprocess_page()` (kept for
  tesseract only). `paddle_engine.py`'s `_MODEL_KWARGS` turns on paddle's own
  `use_doc_orientation_classify`/`use_doc_unwarping`/`use_textline_orientation`
  models at construction (loaded once) instead of leaving them off. Testing then
  surfaced a real accuracy regression: `use_doc_unwarping` (UVDoc, built for
  photographed page curvature) drops/shifts leading characters on the already-flat
  `input.jpg` fixture (`"Sigzen Tech"` -> `"Sigzeln Tech"`, verified by isolating
  each of the three flags individually). Fixed by overriding `use_doc_unwarping`
  per-`.predict()`-call in `extract_page()` — `True` only when `source_type` is a
  phone-photo source (`preprocess.PHONE_PHOTO_SOURCE_TYPES`), `False` otherwise;
  `doc_orientation_classify`/`textline_orientation` stay on unconditionally (both
  verified harmless on the flat fixture). `correct_perspective()` in `preprocess.py`
  was made channel-agnostic (grayscale or color in, same back out) to support both
  callers. `test_scanned_image_produces_ocr_engine_page`'s fixture source_type
  changed from `Payment Receipt` to `Bank Statement` (it's a flat scan, not a real
  phone photo — asserting exact recognized text under a source_type that would
  trigger unwarping was testing the wrong thing); the unwarp on/off wiring itself
  is covered by a new mocked test,
  `test_extract_page_enables_doc_unwarping_only_for_phone_photo_sources`.
  `run-tests --app docapture` (30/30) and `ruff check` both clean. All PaddleOCR
  sub-models (det/rec/doc-orientation/UVDoc/textline-orientation) are now cached
  locally in this sandbox, downloaded successfully during this work despite the
  earlier-assumed network restriction — that earlier assumption was wrong.
- 2026-07-16 (follow-up 3): discussed scoping `use_doc_unwarping` more precisely
  (a new "captured by phone" checkbox field on Captured Document, or EXIF-based
  auto-detection — `source_type` alone doesn't reliably mean "this was
  photographed": a Payment Receipt can be scanned, a Bank Statement can be
  phone-photographed). User decided to defer that and disable `use_doc_unwarping`
  for every document instead, until a real signal exists. `paddle_engine.py`'s
  `_MODEL_KWARGS["use_doc_unwarping"]` is back to `False` unconditionally (no
  more per-`.predict()`-call override, no more `source_type` param on
  `extract_page()`); `doc_orientation_classify`/`textline_orientation` stay `True`
  (verified harmless). Removed the now-obsolete mocked test
  (`test_extract_page_enables_doc_unwarping_only_for_phone_photo_sources`) and the
  now-unneeded `source_type` override in
  `test_scanned_image_produces_ocr_engine_page`. `correct_perspective()` staying
  channel-agnostic and `preprocess_for_paddle()` (DPI upscale + phone-photo
  perspective correction, no unwarping either way) are unaffected — this only
  touches paddle's own built-in unwarping model. `run-tests --app docapture`
  (29/29) and `ruff check` both clean.
  **Open follow-up, not yet scheduled:** decide how to detect "this was actually
  photographed" (checkbox field vs. EXIF) before re-enabling `use_doc_unwarping`
  for anyone.
- 2026-07-16 (follow-up 4): discussed what should happen on an unsupported
  upload (e.g. `.txt`) — traced it to an async `Failed` status with a raw
  Python traceback (`cv2.imdecode` returns `None`, `.shape` on `None` raises).
  Decided to reject at upload time instead. `captured_document.py` (Phase 1,
  already `Approved`) gets a new `ALLOWED_EXTENSIONS` set and
  `check_file_type()`, called first in `validate()` (before the existing
  `content_hash`/duplicate check — fail fast without reading the whole file).
  Knock-on: Phase 1's own `test_captured_document.py` used placeholder text
  content named `.txt` for its dedup/status-walk tests — now rejected by the
  new check, and simply renaming to `.pdf`/`.jpg` wasn't enough either, since
  Frappe's own File doctype validates real PDF/image structure at attach time
  (`pdf_contains_js`, `strip_exif_data` — same class of issue hit earlier with
  `test_pipeline.py`'s corrupt-file test). Fixed by using real fixture bytes
  (`Sales order.pdf`/`input.jpg`) instead of placeholder text, salted per test
  method (`frappe.generate_hash`) so re-running the suite doesn't collide with
  a leftover row from a previous invocation — tests here aren't transactionally
  rolled back, confirmed by hitting exactly that collision mid-fix. Added
  `test_unsupported_file_type_rejected`. `run-tests --app docapture` (30/30,
  confirmed stable across two consecutive runs) and `ruff check` both clean.
- 2026-07-16 (follow-up 5): server-side `check_file_type()` only rejects on
  save — by then the browser has already uploaded the raw file and put the
  Attach widget into its "attached" state (Reload File/Clear buttons), which
  stayed stuck showing those for a file that was never actually saved. Traced
  Frappe's Attach control (`attach.js`) and its uploader (`FileUploader.vue`):
  the docfield's `options.restrictions.allowed_file_types` is checked
  client-side *before* any upload starts, using the same extension-list format
  as our Python `ALLOWED_EXTENSIONS`. Added a `refresh(frm)` handler in
  `captured_document.js` (previously empty boilerplate) setting that
  restriction via `frm.set_df_property("file", "options", {...})` — an
  unsupported file is now filtered out before it's ever uploaded (Frappe's own
  orange "skipped, invalid file type" alert), so the field never leaves its
  plain "Attach" state. Server-side `check_file_type()` unchanged, kept as
  defense-in-depth for uploads that bypass the browser (API/REST). Pure
  client-side change — no Python/test changes; not exercised by
  `bench run-tests`, verification is manual-in-browser (see
  `docs/manual_test/phase-2-ocr-layer.md` if adding a case there).
- 2026-07-16: user signed off. Phase 2 → Approved. Phase 3 not started —
  will not begin until the user explicitly says go.
- 2026-07-16: user said go. Phase 3 started. Planning discussion pinned down
  4 design gaps before code: (a) `FIELDS` is a hand-curated superset per
  mapper, not derived from ERPNext doctype `reqd` meta — audited Payment
  Entry/Journal Entry `validate()` and confirmed most conditional-mandatory
  fields (`party_type`, `exchange_rate`, `reference_no`) aren't visible in
  the JSON schema at all; (b) added `layout.py::reconstruct` as an explicit
  named step — `raw_ocr_json` has no document-level flattened text anywhere,
  confirmed against the existing multi-column `sales_order_page1` fixture;
  (c) split `LLMParser.parse(ocr_json, source_type) -> dto`
  (`DESIGN_PRINCIPLES.md:43`) into `<target>_mapper.build_dto` (owns
  reconstruction/prompt/DTO assembly) + `LLMParser.extract_fields` (the one
  vendor-swappable call) to remove a naming collision — `DESIGN_PRINCIPLES.md`
  updated to match; (d) classifier is heuristic-first (keyword scorer over
  `layout.reconstruct` output), falling back to one LLM call only on
  low-confidence, to avoid doubling API cost per document; threshold
  calibrated by tuning against fixtures for zero misclassifications, same
  approach as Phase 2's DPI work. Full rationale: `docs/PHASE_3_MAPPER_PLAN.md`
  (cross-referenced from `docs/manual_test/phase-3-mapper-llm-layer.md`,
  which also gained 2 new checks for reconstruction/heuristic-path
  coverage). Fixture status: `sales_order_page1` (existing, multi-column,
  used for the reconstruction test) and a newly-acquired Bank Statement
  sample (stock/generic, verified fixture-safe) are in place; Payment
  Receipt, Supplier Bill, and Expense Voucher fixtures are still needed
  before classifier calibration can run — `classifier.py` and
  `pipeline.py` are blocked on those and deferred. Building the
  non-blocked pieces first: `schema.py`, `layout.py`,
  `llm_client.py`/`claude_client.py`, `payment_entry_mapper.py` +
  `journal_entry_mapper.py` (`FIELDS` + `build_dto`), `alias_resolver.py`.
- 2026-07-16 (follow-up): built the non-blocked Phase 3 pieces. New files:
  `docapture/mappers/schema.py` (`FieldValue`, `PaymentEntryDTO`,
  `JournalEntryDTO`, `overall_confidence`, `to_json`), `layout.py`
  (`reconstruct()` — bands lines by y-overlap via union-find, then sorts
  bands top-to-bottom and lines within a band left-to-right), `llm_client.py`
  (`LLMParser` protocol, `extract_fields(prompt_text, field_specs)`),
  `claude_client.py` (`ClaudeParser`, `claude-opus-4-8`, structured-output
  JSON schema built per field, `additionalProperties: false`),
  `payment_entry_mapper.py` and `journal_entry_mapper.py` (`FIELDS` +
  `build_dto`; Journal Entry rows are flattened as `row1_*`/`row2_*`
  dto_fields since `extract_fields` returns a flat dict, then split back into
  `JournalEntryDTO.rows` — fixed at 2 rows, documented as a `ponytail:`
  simplification), `alias_resolver.py` (`normalize`, `resolve`,
  `resolve_extracted`). `anthropic` added to `pyproject.toml` and installed
  via `bench pip install`.
  Two bugs caught by tests during this pass, both fixed: `normalize()`
  only stripped `"pvt ltd"` as a suffix, so `"ABC pvt limited"` (no periods,
  no comma) left a dangling `"pvt"` — added `"pvt limited"` to the suffix
  list. `alias_resolver.resolve()` was designed to scope lookups to "no
  company" (matching Capture Alias rows with an empty `company`), but Frappe
  auto-fills any Link field whose `options` is `"Company"` from the site's
  default Company on insert — so in a single-company deployment nearly every
  Capture Alias row ends up with `company` set, and the "unscoped" filter
  matched nothing. Fixed by dropping the `company` filter entirely for
  Phase 3 (documented as a `ponytail:` — thread real company-scoping through
  once Phase 4 resolves a document's company before extraction).
  Checks: `bench --site erpnext.yoursite.in run-tests --app docapture` —
  48/48 pass (30 unit + 18 integration, all pre-existing OCR-layer tests
  still green); `ruff check .` clean; `bench --site erpnext.yoursite.in
  migrate` clean (no schema changes this pass).
  Still blocked, unchanged from the prior entry: `classifier.py` (heuristic
  keyword scorer + threshold calibration) and `pipeline.py` (orchestration)
  need the 3 missing fixtures (Payment Receipt, Supplier Bill, Expense
  Voucher) before they can be built and tested — calibration specifically
  needs all 4 `source_type` fixtures to tune against. `docs/PHASE_STATUS.md`
  stays `In Progress`, not `Awaiting Review`, until those land.
- 2026-07-16 (follow-up 2): user supplied the 3 remaining `source_type`
  fixtures (`sample_Expense_Voucher.png`, `sample_supplier_bill.png`,
  `sample_payment_reciept.webp` — the last a new format, first `.webp` in
  the app) plus corrected real-vocabulary findings from reading the images
  directly: two of the plan's assumed keywords ("received with
  thanks"/"receipt no." for Payment Receipt, "expense head" for Expense
  Voucher) don't actually appear in the documents. Before building, OCR'd
  all 5 calibration documents (4 real fixtures + Sales Order as the
  negative case) for real via `paddle_engine` + `layout.reconstruct` to get
  ground-truth text rather than guessing the Expense Voucher's true second
  signal — found `"expense voucher"` (the title itself) + `"payment
  method"`.
  **WEBP:** investigated the full ingestion path before assuming it needed
  a new decode branch. `cv2.imdecode` (this bench's
  `opencv-contrib-python==4.10.0.84`, bundled libwebp) and Pillow 12.2.0
  both decode WEBP correctly, confirmed empirically; `docapture/ocr/
  pipeline.py`'s raster branch and every downstream OCR module are already
  format-agnostic. The only two real gates were `Captured Document`'s
  `ALLOWED_EXTENSIONS` (`captured_document.py`) and its client-side mirror
  (`captured_document.js`) — both updated to include `.webp`. Also checked
  Frappe core's `File` doctype end-to-end (validate, thumbnailing, mimetype
  detection) for a third gate: none found, except `frappe/handler.py`'s
  `ALLOWED_MIMETYPES` on the Guest/portal `upload_file` endpoint, which
  omits `image/webp` but doesn't apply to `docapture`'s Desk-only upload
  path — flagged in `docs/ARCHITECTURE.md`'s "Known ceiling" section so
  it isn't silently rediscovered if a portal upload path is ever added.
  **New files:** `docapture/mappers/classifier.py` (`classify(ocr_json,
  llm) -> {source_type, confidence, method}` — heuristic keyword scorer
  first, one LLM classification call only on low signal) and
  `docapture/mappers/pipeline.py` (`run_mapper` — classifies, routes to the
  matching mapper's `build_dto`, writes `extracted_json`/`confidence`,
  walks `OCR Done → Parsed → In Review`, same staleness-guard and
  `Failed`+`error_log` pattern as `ocr/pipeline.py::run_ocr`).
  **Chaining:** `ocr/pipeline.py::run_ocr()` now enqueues
  `docapture.mappers.pipeline.run_mapper` (by dotted string, not import, to
  keep `ocr/` and `mappers/` decoupled per `DESIGN_PRINCIPLES.md`) right
  after writing `status = "OCR Done"`, `enqueue_after_commit=True` — `db_set`
  doesn't fire hooks, so nothing chained the mapper job before this.
  **Calibration result:** `CLASSIFICATION_THRESHOLD = 0.6`; all 4 real
  fixtures score 1.0 on their own type (both keywords present) and 0 on
  every other type except Expense Voucher, which scores 0.5 against
  Supplier Bill's list (shares "bill to") — still correctly resolved via
  argmax since Expense Voucher's own score is 1.0. Sales Order (negative)
  scores 0 against every type, correctly triggering the LLM fallback
  instead of a confident misclassification. Documented in
  `docs/PHASE_3_MAPPER_PLAN.md` as a known v1 limit: calibrated against
  exactly 5 documents, not a general robustness claim.
  Also fixed 2 documentation bugs found during this pass, both in
  `docs/PHASE_3_MAPPER_PLAN.md`: the "Call sequence" section said
  `confidence = dto.overall_confidence`, but the actual implemented API
  exposes it as the `confidence` property (`overall_confidence()` is the
  module-level helper the property calls, not a DTO attribute) — fixed;
  added a "File layout" section documenting that confidence scoring lives
  in `schema.py`, not a separate `confidence.py` as an earlier draft named
  (promoted from a planning-session-only note into the actual design doc).
  **New tests:** `test_classifier.py` (6 — one heuristic-path test per real
  fixture including the `.webp` decode, one synthetic near-blank case
  forcing the LLM fallback since none of the 4 real fixtures exercise that
  path by construction, one confirming Sales Order falls back rather than
  being misclassified), `test_pipeline.py` under `mappers/` (3 — happy path
  with a mocked `ClaudeParser`, stale-status no-op, exception → `Failed`),
  plus a `.webp` happy-path test in both `captured_document`'s own
  `test_pipeline.py` (full OCR decode) and `test_captured_document.py`
  (attach-time acceptance).
  Checks: `bench --site erpnext.yoursite.in run-tests --app docapture` —
  59/59 pass (36 unit + 23 integration); `ruff check .` clean; `bench
  --site erpnext.yoursite.in migrate` clean.
  **Not done:** the manual UI walkthrough in
  `docs/manual_test/phase-3-mapper-llm-layer.md` — every item on that
  checklist has an equivalent automated-test assertion (listed above), but
  no one has driven the actual Desk UI end-to-end (upload → OCR → mapper →
  `In Review`) yet. Flagging this explicitly rather than marking the
  checklist done on the strength of automated coverage alone.
  Phase 3 → Awaiting Review. Exit criteria met per
  `docs/PHASED_DEVELOPMENT.md`: OCR JSON produces a structured DTO with
  confidence; the classifier routes each source type correctly; a value
  already in `Capture Alias` auto-maps with no prompt; fixture-document
  tests pass. Stopping here for explicit user review before any Phase 4
  work, per the phase-gate.

- **2026-07-17, follow-up 3 (LLM backend swap — Claude → OpenAI):** no
  Anthropic API key available in this environment; an OpenAI key was, so
  the wired `LLMParser` implementation changed from `ClaudeParser` to a new
  `OpenAIParser` (`docapture/mappers/openai_client.py`, `gpt-4.1`, OpenAI
  Responses API structured output). `claude_client.py` is kept, not
  deleted, as a second `LLMParser` implementation — this is exactly the
  vendor-swap seam `docs/PHASE_3_MAPPER_PLAN.md`'s "Naming" section
  designed `extract_fields` for. Only `pipeline.py`'s one import changed;
  `classifier.py`, both mappers, `alias_resolver.py` are untouched (they
  depend on the `LLMParser` protocol, never a concrete client). Factored
  the JSON-schema/prompt-building logic (previously private to
  `claude_client.py`) out into `llm_client.py` as `build_schema`/
  `build_prompt`, since a second concrete client made the duplication real
  rather than hypothetical. `pyproject.toml` gained `openai`; `anthropic`
  kept. New test: `test_openai_client.py` (mirrors `test_claude_client.py`).
  Updated `test_pipeline.py`'s two `patch.object(pipeline, "ClaudeParser",
  ...)` calls to `"OpenAIParser"`. `docs/PHASE_3_MAPPER_PLAN.md`'s "File
  layout" section updated in place.
  Checks: `bench run-tests --app docapture` — 60/60 pass (37 unit + 23
  integration); `ruff check .` clean.
  **Still open, not part of this fix:** `OPENAI_API_KEY` isn't set in this
  bench yet — `OpenAIParser()`'s default `openai.OpenAI()` reads it from
  the environment. Needs either an exported env var ahead of `bench start`/
  `bench worker`, or `bench --site erpnext.yoursite.in set-config
  openai_api_key <key>` plumbed into `OpenAIParser.__init__` explicitly
  (not done here — no key was supplied to test against, so wiring it
  untested would just move the failure, not fix it). Phase 3 stays
  `Awaiting Review`; this is a same-phase fix, not new scope.

- **2026-07-17, follow-up 4 (config-driven parser selection):** user
  feedback on follow-up 3 — `pipeline.py` importing `OpenAIParser` by name
  meant every vendor swap touched production code (`pipeline.py`) plus a
  test patch target, when the whole point of the `LLMParser` protocol
  (`docs/DESIGN_PRINCIPLES.md`'s L section) is that callers shouldn't care
  which concrete implementation they hold. Added `llm_client.get_parser()`
  — reads `site_config.json`'s `llm_backend` (`"openai"` default,
  `"claude"` alternative), returns the matching concrete `LLMParser`.
  `pipeline.py` now calls `llm_client.get_parser()` instead of importing
  `OpenAIParser` directly; swapping vendor (or trying a different model
  tier) is a `bench set-config llm_backend claude` away, zero code edits.
  Considered and rejected the "make `LLMParser` an ABC, have both clients
  inherit it" framing of the same feedback — Python's `Protocol` already
  gives structural interchangeability without inheritance; forcing a base
  class would add boilerplate with no substitutability gain the `Protocol`
  doesn't already provide. New test: `test_llm_client.py` (2 — default
  branch, `"claude"` branch; both stub `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`
  via `patch.dict` so branch selection doesn't need real credentials to
  test). Updated `test_pipeline.py`'s two patch targets from
  `pipeline.OpenAIParser` to `llm_client.get_parser`.
  Checks: `bench run-tests --app docapture` — 62/62 pass (39 unit + 23
  integration); `ruff check .` clean.
  `docs/PHASE_3_MAPPER_PLAN.md`'s "File layout" and "LLM backend" sections
  updated in place. Phase 3 stays `Awaiting Review` — same-phase fix.

- **2026-07-17, follow-up 5 (LangSmith tracing):** user request — observe
  `LLMParser` calls (prompt, response, latency, cost) via LangSmith.
  `ClaudeParser`/`OpenAIParser` now wrap only their *default*-constructed
  client (`wrap_anthropic`/`wrap_openai` from `langsmith.wrappers`); a
  caller-supplied client (every test) is left unwrapped, so no test needed
  changing and no test run produces a trace. Purely env-var controlled
  (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`) — off by
  default, no code branch to toggle. Added `.env.example` at the bench
  root (`/home/brij/frappe/frappe-bench/.env.example`, outside
  `apps/docapture/` — it documents bench-wide process env, same as
  `Procfile`) listing `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` alongside the
  three `LANGSMITH_*` vars, since `bench start` (honcho) auto-loads
  `.env` from the bench root for every Procfile process including the
  worker. `pyproject.toml` gained `langsmith`.
  Checks: `bench run-tests --app docapture` — 62/62 pass; `ruff check .`
  clean. `docs/PHASE_3_MAPPER_PLAN.md`'s "LLM backend" section updated in
  place. Phase 3 stays `Awaiting Review` — same-phase fix, no scope
  change to Phase 3's exit criteria.

- **2026-07-17, follow-up 6 (Print Format for extracted_json):** user
  request — see `extracted_json`'s structured content readably, via a real
  Frappe Print Format (not just the raw JSON textbox on the form). Added
  `docapture/docapture/print_format/extracted_fields_view/` ("Docapture
  Extracted Fields", Jinja, `doc_type: Captured Document`) — same pattern
  as Phase 2's existing `ocr_text_view` ("Docapture OCR Text") print
  format. Parses `doc.extracted_json`, renders source_type/status/overall
  confidence, a field/value/confidence table for `fields`, and one more
  such table per `rows` entry (Journal Entry's 2-row shape) when present;
  falls back to "No extracted fields yet." when `extracted_json` is empty
  (mirrors `ocr_text_view`'s empty-state handling). Verified via
  `frappe.get_print("Captured Document", "CAP-00028", print_format=...)`
  against a real `In Review` doc from a prior test run — renders the full
  Supplier Bill → Journal Entry field/row breakdown correctly, no
  exceptions.
  Checks: `bench run-tests --app docapture` — 62/62 pass; `ruff check .`
  clean; `bench migrate` clean (new Print Format synced). Phase 3 stays
  `Awaiting Review` — same-phase fix.

- **2026-07-17, follow-up 7 (LangSmith traces stuck "pending"):** root
  cause — `frappe.enqueue` jobs run under RQ, which forks a child process
  per job and calls `os._exit(0)` on it when the job returns
  (`rq/worker.py`). `os._exit` skips `atexit` entirely, so LangSmith
  `Client`'s normal atexit-registered flush of its background send queue
  never runs; every trace from a background job (the only place
  `OpenAIParser`/`ClaudeParser` ever actually run) recorded a start but
  never got its end/output event out before the process was killed —
  hence "pending" forever. Fix: `llm_client.new_tracer()` — each parser
  now creates its own `langsmith.Client`, passes it into
  `wrap_anthropic`/`wrap_openai` via `tracing_extra={"client": ...}`, and
  calls `tracer.flush()` synchronously inside `extract_fields()` right
  after building the result, before returning control to the job. Safe
  unconditionally (no-op when tracing is off). No test changes needed —
  test doubles are still injected via the `client=` param and skip the
  tracer path entirely (`self._tracer` stays `None`).
  Checks: `bench run-tests --app docapture` — 62/62 pass; `ruff check .`
  clean. `docs/PHASE_3_MAPPER_PLAN.md`'s "LangSmith tracing" section
  updated in place. Phase 3 stays `Awaiting Review` — same-phase fix.

- **2026-07-17, follow-up 8 (UML_DIAGRAM.md sync):** `docs/UML_DIAGRAM.md`
  still showed the whole `Phase3_MapperLLM` namespace as "Not Started" /
  grey-dashed "(planned)" boxes, stale since follow-ups 1-7 actually built
  it. Replaced with the real modules/classes (`llm_client.py`'s `get_parser`
  and `new_tracer`, `ClaudeParser`/`OpenAIParser` realizing `LLMParser`,
  `layout.py`, `schema.py`'s DTOs, `classifier.py`, both mappers,
  `alias_resolver.py`, `mappers/pipeline.py`) and real relationship edges,
  including the `ocr/pipeline.py` → `mappers/pipeline.py` chaining
  (`enqueue_after_commit`) that connects Phase 2 to Phase 3. Phase 4's
  namespace is untouched — still genuinely not started, stays
  planned/dashed. No code changed; doc-only sync.

- **2026-07-17, follow-up 9 (bank-statement table extraction):** user
  uploaded a real 9-page, ~190-row Union Bank of India bank statement
  (`CAP-00031`) and asked for it to end up as one Journal Entry per row.
  Checked its actual `extracted_json` first: `payment_entry_mapper` had
  captured exactly the statement's first transaction and silently dropped
  the other ~189 — neither `PaymentEntryDTO` (one flat field set) nor
  `JournalEntryDTO` (fixed at 2 rows) can represent a variable-length
  table, and `LLMParser.extract_fields` could only ever return one flat
  dict per call. `classifier.py` also misrouted this real document as
  Payment Receipt (0.94 confidence): `KEYWORDS["Bank Statement"] =
  ["previous balance", "withdrawals"]` scored 0.5 (this statement says
  "Statement of Account", never "previous balance") and fell through to an
  LLM fallback that guessed wrong.
  User raised a real design constraint before any code: different banks
  use different column names/layouts for the same data, so nothing here
  may hardcode literal source column strings. Confirmed this doesn't touch
  the existing `FIELDS` design — those already extract by canonical target
  field name + semantic hint, not literal column text — the actual gap was
  variable-row-count extraction, not column-naming.
  **Built:** `schema.py` gained `BankStatementDTO` (`fields` +
  `transactions: list[dict[str, FieldValue]]`, variable length,
  `to_json()` sets `target_doctype: "Journal Entry"`); `llm_client.py`
  gained `LLMParser.extract_rows` + `build_row_schema`/`build_row_prompt`
  (array-of-rows, same per-field contract as `extract_fields`), implemented
  in both `OpenAIParser` and `ClaudeParser`; `layout.py` gained
  `reconstruct_pages` (per-page text, `reconstruct()` now built on top of
  it); new `bank_statement_mapper.py` (`FIELDS` for statement-level data +
  `ROW_FIELDS` for canonical per-row fields, one `extract_rows` call per
  page rather than one call for the whole document); `Capture Alias`
  gained a `Customer` `entity_type` option (previously missing entirely);
  `classifier.py`'s `KEYWORDS["Bank Statement"]` recalibrated to
  `["withdrawals", "deposits"]` — the transaction table's own column
  headers, verified present in both the original stock fixture and the
  real UBI statement; `pipeline.py` now routes `Bank Statement` →
  `bank_statement_mapper` instead of `payment_entry_mapper` (deliberate
  divergence from `docs/FEATURE_LIST.md`'s original "bank statement →
  Payment Entry" plan — many real rows here, self-transfers between the
  account holder's own sub-accounts, GST/TDS/bank fees, have no
  Customer/Supplier party at all, which Journal Entry doesn't require and
  Payment Entry does). Added `sample_bank_statement_ubi.pdf` as a
  real-world calibration fixture alongside the existing stock PNG.
  **Explicitly out of scope, deferred:** turning
  `BankStatementDTO.transactions` into actual per-row Journal Entry drafts
  — that's Phase 4 (review queue + draft creation), not started, needs its
  own explicit go-ahead per this file's phase-gate rule.
  Two Capture Alias-dependent tests
  (`test_counterparty_name_resolves_against_customer_alias`,
  `..._falls_back_to_supplier_alias`) initially failed with
  `LinkValidationError: Could not find Mapped Docname` — `mapped_docname`
  is a Dynamic Link validated against `mapped_doctype`, so the test fixture
  needs a real inserted `Customer`/`Supplier` record, not just an arbitrary
  string. Fixed by inserting one in each test before the `Capture Alias`
  row.
  Checks: `bench --site erpnext.yoursite.in run-tests --app docapture` —
  76/76 pass (46 unit + 30 integration); `ruff check .` clean (3 import-sort
  autofixes in `claude_client.py`/`openai_client.py`/`pipeline.py`, no
  logic changes); `bench migrate` clean.
  `docs/PHASE_3_MAPPER_PLAN.md`'s "File layout", "Classifier", "Fixtures",
  and "Routing" sections updated in place, plus a new "Bank Statement:
  variable-length table extraction" section. Phase 3 stays `Awaiting
  Review` — same-phase addition, not new scope beyond what Phase 3 already
  covers (structured extraction with confidence, for every source type).
  **Verified live, not just by tests:** a real re-upload of the UBI
  statement (`CAP-00032`) went through the actual pipeline (real OpenAI
  call, not a stub) and correctly classified as Bank Statement, routed to
  `bank_statement_mapper`, and extracted all 189 transaction rows — matches
  the PDF's own "Records from 1 to 189" footer exactly, first row is the
  01-12-2025 ₹50,00,000 TRF GAYATRI PRIVATE LIMITED entry, confidence 0.97.

- **2026-07-17, follow-up 10 (print format missing Bank Statement
  transactions):** user viewed `CAP-00032`'s "Docapture Extracted Fields"
  print format and saw only the 4 statement-level fields — none of the 189
  transaction rows confirmed present in follow-up 9. Root cause: the print
  format (`extracted_fields_view.json`, added before `BankStatementDTO`
  existed) only has template branches for `extracted.fields` and
  `extracted.rows` (`JournalEntryDTO`'s fixed 2-row shape) — no branch for
  `extracted.transactions` at all, so it silently stopped after the parent
  fields table. Fixed: added an `{%- elif extracted.transactions %}`
  branch rendering one single table (Date/Narration/Reference No/
  Withdrawal/Deposit/Balance/Counterparty/Party columns, one row per
  transaction) instead of the existing per-row field/value/confidence
  sub-table pattern, which only makes sense at 2 rows, not 189. Also added
  `word-wrap`/`overflow-wrap`/`word-break` CSS on every table cell in this
  print format, in case a long value (e.g. a long narration string) was
  separately getting visually clipped.
  ponytail: the new transactions table skips the per-field confidence
  column the other two tables show — unreadable at 8 fields × 189 rows,
  and confidence is ~1.0 across the board on the real document; add a
  low-confidence flag back if that turns out to matter during review.
  **Real gotcha hit during verification:** editing the `.json` fixture file
  directly and running `bench migrate` did NOT update the live `Print
  Format` DB record — `frappe.db.get_value("Print Format", ..., "html")`
  still showed the old template after migrate. Standard-doctype fixture
  sync appears to skip re-importing when it judges the DB copy no older
  than the file (this file's `modified` timestamp was left unchanged by
  the edit). Fixed by explicitly calling
  `frappe.reload_doc("docapture", "print_format", "extracted_fields_view", force=True)`
  once, which force-syncs from the file regardless of timestamps — worth
  remembering for any future direct edit to a standard fixture `.json`.
  Verified via `frappe.get_print("Captured Document", "CAP-00032", ...)`:
  196 `<tr>` total (1 info + 5 fields-table + 1 transactions-header + 189
  transaction rows — exact expected count), first/last transaction values
  present and correct. Pure print-format content change — no doctype/
  schema/Python changes, so no test suite impact; not itself Phase 4 scope
  (no draft/document creation), just fixing visibility into data Phase 3
  already extracts.

- **2026-07-17, follow-up 11 (withdrawal/deposit misclassification):** user
  reported many rows on the real UBI statement have the amount under the
  wrong one of `withdrawal`/`deposit` (example given: the "TRF 201-54921"
  row is a deposit but was extracted as a withdrawal). Root cause:
  `layout._reconstruct_page()` reconstructs OCR bands into plain
  reading-order text, which discards column position — a table row like
  `date | narration | ref | withdrawal | deposit | balance` becomes a flat
  string with just one bare amount (since the two fields are mutually
  exclusive per row), leaving `extract_rows` nothing but context/wording to
  guess which named column it came from. Not a prompt-wording problem: the
  column identity is already gone by the time the LLM sees the text.
  Researched the reference product the user pointed at (aiaccountant.com,
  a Tally-focused AI-accountant tool) for how it handles this class of
  document — its own published description: "For each row, previous
  balance plus credits minus debits must equal next balance... amount
  sanity checks catch sign flips." Same technique applied here: added
  `bank_statement_mapper._correct_withdrawal_deposit()`, a deterministic
  post-process (no LLM/OCR change) that walks the fully concatenated
  `transactions` list once, carrying forward the last parseable `balance`,
  and for each row where the balance delta's sign disagrees with which
  field (`withdrawal` vs `deposit`) the LLM populated, swaps the amount
  into the correct field (keeping the same OCR digit value — only "which
  field it belongs to" was wrong). Rows with no previous parseable balance
  to diff against (the first row; any row following one with an
  unparseable balance) are left as extracted, not guessed at.
  ponytail: only the debit/credit sign-flip is fixed — aiaccountant.com's
  write-up mentions adjacent checks (opening/closing balance
  reconciliation, UTR-based duplicate detection, date monotonicity,
  IFSC/UTR format validation) that are the same family of idea but have no
  evidence of being a problem here yet; not built speculatively.
  New tests in `test_bank_statement_mapper.py`: wrong-side amount corrected
  in both directions, already-correct amount left untouched (value/
  confidence unchanged), row with unparseable balance left uncorrected
  while the chain still continues past it using the last known balance,
  and correction chains across a page boundary. **Checks:** `bench
  --site erpnext.yoursite.in run-tests --app docapture` — 81/81 pass (46
  unit + 35 integration); `ruff check .` — clean. **Verified against real
  data:** ran the new correction function over `CAP-00032`'s already-
  stored 189-row `extracted_json` (no new LLM call) — 82 of 189 rows
  (~43%) had a wrong debit/credit side, all corrected, including the
  exact "TRF 201-54921" row the user reported (was `withdrawal: 20000.00`,
  now `deposit: 20000.00`, matching its balance delta). Pure Python change
  in `bank_statement_mapper.py`, no schema/doctype changes; latency on
  9-page documents was also raised by the user but explicitly marked "not
  a concern now," so left untouched.
