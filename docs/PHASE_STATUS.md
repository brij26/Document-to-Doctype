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
| 4 | Review queue + draft creation | Awaiting Review |
| 5+ | Future (Should / Nice-to-Have) | Not Started |

---

## Current focus

**Phase 4 — Awaiting Review.** Phase 3 stays `Awaiting Review` (unchanged,
extraction/mapper layer untouched except the one disclosed cross-phase fix
below). See the 2026-07-17 "Phase 4 build" log entry for the full summary,
exit-criteria check, and disclosed design-principle bends. Stopping here for
explicit user review before Tier 1 (docs/COMPETITIVE_GAP_ROADMAP.md) or
anything else.

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

- **2026-07-17 (Phase 4 kickoff):** user asked for a strict competitive gap
  audit against aiaccountant.com, scoped to bank statement/supplier
  bill/expense voucher/payment receipt only (GST/Tally connector parity
  explicitly out of scope) — written to
  `docs/COMPETITIVE_GAP_ROADMAP.md`. Follow-up discussion pinned down
  Phase 4's concrete bank-statement design: every transaction posts as a
  Journal Entry (no Payment Entry split for now), and all transactions on
  the same date share one JE (multi-row, one Bank+counterparty leg pair
  per transaction, batched per date) rather than one JE per transaction.
  This pulls two items the roadmap had filed under "Tier 1" (variable-length
  JE rows, bank-statement multi-row splitting) forward into Phase 4 itself,
  specifically for the Bank Statement source type. Supplier
  Bill/Expense Voucher/Payment Receipt are unaffected — they stay
  single-draft 2-row JE, matching Phase 4's original spec in
  `docs/PHASED_DEVELOPMENT.md`. User said go. Phase 4 → In Progress.

- **2026-07-17, Phase 4 build:** built review queue + draft creation for all
  four source types.

  **New files:** `docapture/dedup.py` (business-key lookup, scoped to
  `Docapture Posting`'s own audit trail — never the general ledger),
  `docapture/postings.py` (appends one `Docapture Posting` child row per
  draft created or per dedup collision skipped), `docapture/router.py`
  (whitelisted `approve()`/`reject()`, `source_type` → creator registry),
  `docapture/notify.py` (bell-icon Notification Log to every System
  Manager/Docapture Reviewer user on a pipeline failure — gap #10),
  `docapture/creators/{accounts,fields,journal_entry_creator,
  payment_entry_creator}.py`, new child doctype `Docapture Posting`
  (`istable`, fields: target_doctype/target_docname/status/posting_date/
  party/amount/reference/note) plus a `postings` Table field added to
  `Captured Document`.

  **journal_entry_mapper.py rewritten** (started as task 1, before the rest):
  `FIELDS` now holds only header fields (posting_date/cheque_no/cheque_date);
  a new `ROW_FIELDS` + `llm.extract_rows()` call (the same mechanism
  `bank_statement_mapper.py` already used) replaces the old fixed
  `row1_*/row2_*` convention — `JournalEntryDTO.rows` can now be any length.

  **Bank Statement path:** `journal_entry_creator.create_grouped_by_date()`
  groups `BankStatementDTO.transactions` by date; each date becomes one
  Journal Entry with one Bank-leg + one counterparty-leg pair per
  transaction (not one JE per transaction, not one JE for the whole
  statement) — the exact shape the user specified. Dedup is checked
  *per transaction*, before grouping, so a duplicate row is dropped rather
  than silently merged into someone else's daily entry.

  **Real ERPNext validation constraints discovered while building this**
  (not knowable from the doctype JSON alone — found via actual `.insert()`
  failures against real Journal Entry/Payment Entry validate() logic):
  - `validate_party()` requires `party_type`+`party` together whenever a
    row's account is a Receivable/Payable account — leaving `party` blank
    to fall back to a bare control account (the original design) is not
    actually postable. Fixed with a get-or-create placeholder Customer/
    Supplier (`accounts.resolve_party()`, "Unidentified Depositor"/
    "Unidentified Payee") when the counterparty never resolved to a real
    record — the entry still posts, into an identifiable bucket a reviewer
    can repoint, rather than failing outright or guessing a real party.
  - `create_remarks()` requires `cheque_date` whenever `cheque_no` is set.
    Defaulted to the entry's own `posting_date` when the LLM didn't extract
    a separate reference date.
  - Payment Entry's `set_missing_values()` requires `party_type`+`party`
    unconditionally (non-Internal-Transfer) — same placeholder fix applies.

  **Multi-company alias fix** (gap #6): `alias_resolver.resolve()`/
  `resolve_extracted()` gained an optional `company` param — tries a
  company-scoped `Capture Alias` match first, falls back to the old
  unscoped lookup so existing single-company rows keep resolving with zero
  migration. Threaded through all three mappers' `build_dto()` and
  `mappers/pipeline.py` (passes `doc.company`). ponytail-flagged residual
  gap in-code: the unscoped fallback can still pick a *different* company's
  alias when no company-scoped one exists yet — full closure needs either
  backfilling `company` onto every existing alias row or dropping the
  fallback, neither done speculatively without real multi-company data.
  This touches Phase 3 files while Phase 3 is `Awaiting Review` — sanctioned
  by the roadmap itself ("Phase 4 is exactly when a document's company
  first resolves onto a draft, so thread it through `alias_resolver.resolve()`
  at this point").

  **LLM key wiring** (gap #12): `llm_client.resolve_api_key(config_key,
  env_var)` — `bench set-config` takes priority, falls back to the process
  env (unchanged behavior when nothing's configured). Applied to both
  `openai_client.py` (active default) and `claude_client.py` (kept in sync
  for the same reason `docs/PHASE_3_MAPPER_PLAN.md` already gives for
  maintaining both: it's the vendor-swap seam).

  **Review queue UI:** `captured_document.js` gained Approve/Reject buttons
  (visible to `Docapture Reviewer`/`System Manager` when `status == "In
  Review"`) calling `docapture.router.approve`/`reject`. The "queue" itself
  is the standard List View filtered to `status = "In Review"` — no custom
  board built (YAGNI; native Frappe filtering already does this).

  **Disclosed design-principle bends** (`docs/DESIGN_PRINCIPLES.md` "name it
  in the checkpoint"):
  - Dedup lives inside each creator (`journal_entry_creator.py`,
    `payment_entry_creator.py`), not centrally in `router.py` as
    `docs/ARCHITECTURE.md`'s "Router → Creator: dedup check... then create"
    diagram implies. Bank Statement's per-transaction-before-grouping dedup
    genuinely needs DTO-shape-specific knowledge (`docapture/dedup.py` and
    `docapture/postings.py` stay the shared, doctype-agnostic primitives;
    only the *decision of what counts as one business key* is creator-side).
  - Creators are no longer pure "DTO → draft, nothing about extraction" —
    they also call `docapture/dedup.py` and append `Docapture Posting` rows.
    Still hold the actual non-negotiable (`ocr/`/`mappers/`/`creators/`
    stay separated, DTO is the only cross-layer contract); the addition is
    audit/dedup bookkeeping, not a leak of OCR/LLM internals.

  **Checks:** `bench --site erpnext.yoursite.in run-tests --app docapture`
  — 105/105 pass (51 unit + 54 integration; 23 new tests this pass:
  `test_dedup.py`, `test_router.py`, `test_notify.py`,
  `creators/test_journal_entry_creator.py`,
  `creators/test_payment_entry_creator.py`, plus additions to
  `test_journal_entry_mapper.py`/`test_alias_resolver.py`/
  `test_llm_client.py`); `ruff check .` clean; `bench migrate` clean (new
  `Docapture Posting` doctype + `Captured Document.postings` field synced).

  **Exit criteria** (`docs/PHASED_DEVELOPMENT.md` Phase 4): "approve a
  captured document → the correct Payment Entry or Journal Entry draft is
  created, linked back, respects company/currency, and a duplicate is
  blocked" — met and tested for all four source types, including the
  date-grouped Bank Statement path (a deliberate scope expansion beyond the
  original single-draft wording, per explicit user direction — see the
  kickoff entry above and `docs/COMPETITIVE_GAP_ROADMAP.md`).

  **Not done, flagged rather than silently skipped:** no manual Desk UI
  walkthrough (upload → OCR → mapper → review → Approve button → posted
  JE/PE) — same gap `docs/PHASE_STATUS.md` already flagged for Phase 3;
  worth doing for real before this phase is approved, since it's the first
  phase that writes to the ledger space. Bulk upload, failure-alert email
  (vs. the bell-icon Notification Log actually built), and the remaining
  Tier 1/2/3 roadmap items are unstarted by design — this phase stops at
  Phase 4's own exit criteria.

  Phase 4 → Awaiting Review. Stopping here for explicit user review before
  continuing to any Tier 1 work.

- **2026-07-20 (Phase 4 follow-up — amount-validation bug fix + Preview/
  Correct feature):** user reported approving a Payment Receipt threw
  `frappe.exceptions.ValidationError: Paid Amount is mandatory` from inside
  `payment_entry_creator.create()`'s `pe.insert()`, and separately that they
  had no way to see what would be created (or fix a wrong extracted value)
  before Approve/Reject.

  **Root cause:** when the LLM/OCR couldn't confidently read an amount,
  `paid_amount` is `None`; `payment_entry_creator.py:58-59` silently coerced
  that to `pe.paid_amount = paid_amount or 0`, and ERPNext's own
  `validate_mandatory()` then threw its generic message with no trace back
  to "docapture couldn't read this field." Same investigation found the
  identical shape twice more in `journal_entry_creator.py`:
  `_append_mapped_row` silently zero-filled a JE row's debit/credit (worse —
  an all-zero row can balance and insert with no error at all), and
  `create_grouped_by_date` silently dropped a bank-transaction row with an
  unparseable date/amount (previously flagged in-code with a `ponytail:`
  comment as a known gap).

  **Fixed, all 3 sites:** `payment_entry_creator.create()` and
  `journal_entry_creator._append_mapped_row()` now `frappe.throw()` a clear
  docapture-level message (the row case names the 1-based row number)
  instead of zero-coercing — `router.approve()`'s existing try/except
  already turns this into `status="Failed"` + a readable `error_log`, no
  router change needed. `create_grouped_by_date()` still skips an
  unparseable row (one bad row among ~190 must not fail the whole
  statement) but now collects skipped row numbers and `frappe.msgprint`s a
  summary once, instead of dropping them with zero trace.

  **Preview/Save Corrections feature:** new `docapture/review.py`
  (`to_preview()`/`apply_corrections()`, pure functions, DTO-shape-agnostic
  — branch on presence of `rows`/`transactions`, not `source_type`) plus two
  new whitelisted `router.py` methods (`preview()`, `save_corrections()`,
  same `_require_reviewer()` + status-guard shape as `approve()`/`reject()`).
  A reviewer-edited value is written directly back into `extracted_json`
  (`save_corrections()` → `doc.db_set`), confidence bumped to `1.0`, any
  alias-resolved `mapped_docname` dropped (an edited value is no longer a
  trusted link) — unchanged fields are left byte-for-byte alone.
  `captured_document.js` gained a "Preview" button (same visibility guard as
  Approve/Reject) opening one `frappe.ui.Dialog`: header fields as native
  Dialog inputs, row/transaction DTOs (Journal Entry, Bank Statement) as a
  hand-built HTML `<table>` of inputs inside an `HTML`-fieldtype Dialog
  field, since no Table-fieldtype/Dialog precedent existed in this app.
  Low-confidence fields (`confidence < 0.5`) get a visible hint/highlight.
  "Save Corrections" posts to `save_corrections()`, then `frm.reload_doc()`.

  **Design divergence, disclosed:** `docs/PHASE_4_REVIEW_UX_PLAN.md` already
  contained a different, previously-confirmed design for this same
  reviewer-correction problem (a persisted `Docapture Extracted Field` child
  doctype, native always-visible Table grid, `extracted_json` staying
  immutable) — never built. Explicitly surfaced to the user before writing
  any code; user chose this session's Dialog-based design over the existing
  doc's grid-based one. `PHASE_4_REVIEW_UX_PLAN.md` rewritten to mark itself
  superseded and point at this entry, rather than left contradicting what
  was actually built.

  **Checks:** `bench --site erpnext.yoursite.in run-tests --app docapture` —
  122/122 pass (56 unit + 66 integration; new: `test_review.py` (5),
  3 new tests in `test_router.py` for `preview()`, 4 for
  `save_corrections()`, 1 end-to-end correction→approve round-trip, 1 each
  in `creators/test_payment_entry_creator.py`/
  `creators/test_journal_entry_creator.py` for the amount-throw fix, 1 for
  the bank-statement skip-surfacing fix); `ruff check .` clean; `bench
  migrate` clean (no schema changes — `extracted_json` stays the existing
  Long Text field, no new doctype).

  **Not done, flagged rather than silently skipped:** no manual Desk
  walkthrough of the Preview dialog across all 4 source types (no browser
  automation available in this session) — the backend round-trip is
  covered by an automated test, but the actual dialog rendering/editing
  interaction has not been driven by a human yet. Also carried over,
  unfixed, from the superseded plan doc: `journal_entry_creator.py`'s
  `_append_mapped_row` uses the row's raw OCR `account` text instead of
  `alias_docname(...)`, ignoring Capture Alias resolution — a real,
  independent bug, explicitly out of scope for this pass.

  Phase 4 stays `Awaiting Review` — same-phase fix (review feedback fixed
  within the current phase, `CLAUDE.md` rule 3), not new scope. Stopping
  here for explicit user review — please try the Preview button on a real
  `In Review` capture (all 4 source types if possible) before this is
  considered done.

- **2026-07-20 (Phase 4 follow-up — bank-statement date forward-fill):**
  user uploaded `Bank Statement Example Final.pdf` and asked whether
  same-day transactions correctly group into one JE. Grouping logic itself
  checked out fine, but inspecting the actual PDF text (PyMuPDF) surfaced a
  separate real gap: this bank prints the date once per day, then lists
  every same-day transaction below it with no date on that transaction's
  own line. `layout.reconstruct_pages()` flattens OCR bands into
  reading-order text, discarding table/column structure (same root cause
  already documented for the withdrawal/deposit column-swap bug, follow-up
  11) — a transaction row with no date anywhere near it in the flattened
  text correctly gets `date: null` from `bank_statement_mapper`'s per-row
  extraction, not an extraction bug. Downstream, `create_grouped_by_date()`
  requires a parseable date to group a row at all, so these rows were being
  skipped (silently before today's earlier fix, now surfaced via
  `msgprint` but still dropped either way).

  **Fixed:** `bank_statement_mapper.py` gained `_forward_fill_date()`, same
  shape/placement as the existing `_correct_withdrawal_deposit()`
  balance-carry correction — deterministic post-process, no LLM/OCR change,
  called once from `build_dto()`. Carries the last-seen parseable date
  forward onto any row missing one; a row before any date has been seen
  yet is left alone. Forward-filled confidence is `0.4` — deliberately
  below the Preview dialog's `<0.5` low-confidence threshold shipped
  earlier today, so a forward-filled date automatically shows up flagged
  for reviewer double-check with zero extra plumbing. Scope stays narrow:
  only `date` is forward-filled, no evidence other row fields share this
  layout problem. No changes needed outside this one file — DTO shape is
  unchanged, so `journal_entry_creator.py`/`router.py`/Preview all pick it
  up automatically.

  **Checks:** `bench --site erpnext.yoursite.in run-tests --app docapture`
  — 126/126 pass (56 unit + 70 integration; 4 new tests in
  `test_bank_statement_mapper.py`); `ruff check .` clean; `bench migrate`
  clean (no schema changes).

  Phase 4 stays `Awaiting Review` — same-phase fix, not new scope.

- **2026-07-20 (Phase 4 follow-up — reviewer can delete a bogus row in
  Preview):** same PDF surfaced a second, unrelated gap — this bank's
  statement opens with a "Balance brought forward" line, which
  `bank_statement_mapper`'s per-row extraction has no way to distinguish
  from a real transaction, so it comes through as a bogus `transactions`
  row. Asked the user: auto-detect via a text heuristic ("balance b/f",
  "opening balance", ...) or let the reviewer manually delete any row.
  User picked manual delete — a heuristic is bank-phrasing whack-a-mole
  (same trap as the date-forward-fill problem above), manual delete is
  general and reuses the Preview/Correct feature already shipped.

  **Fixed:** `review.apply_corrections()` now accepts an optional
  `corrections["deleted_row_indices"]` (0-indexed into the original
  `rows`/`transactions` list, same indexing `to_preview()` already uses)
  and drops those rows from the returned list entirely, after field
  corrections are applied. `captured_document.js`'s Preview dialog gained
  a "Remove" button per row (`build_rows_table_html()`) that strikes/flags
  a row client-side (undoable before Save); `save_preview_corrections()`
  collects the flagged row indices and sends them alongside the existing
  `header_fields`/`rows` payload. `router.save_corrections()` needed no
  change — it already passes `corrections` straight through. Scope: row
  deletion only (Journal Entry rows, Bank Statement transactions); a flat
  (no-rows) document like Payment Receipt is still handled by the existing
  Reject button, not touched here.

  **Checks:** `bench --site erpnext.yoursite.in run-tests --app docapture`
  — 129/129 pass (57 unit + 72 integration; 1 new test in
  `test_review.py`, 2 new tests in `test_router.py`, one of which proves
  the deletion isn't cosmetic — the undeleted bogus row makes `approve()`
  throw outright since it has no debit/credit); `ruff check .` clean;
  `bench migrate` clean (no schema changes).

  Phase 4 stays `Awaiting Review` — same-phase fix, not new scope.

- **2026-07-20 (Phase 4 follow-up — Capture Alias round-trip fix + clear
  account-resolution errors + reviewer-assisted alias creation):** user hit
  a raw `TypeError: sequence item 0: expected str instance, NoneType
  found` (ERPNext's `journal_entry.py::set_against_account()`) approving a
  Bank Statement JE. Tracing it surfaced three related bugs; user asked to
  fix all three together.

  **Root cause:** `alias_resolver.resolve_extracted()` has always
  correctly returned `mapped_doctype`/`mapped_docname` on a Capture Alias
  hit, but every mapper's `build_dto()` rebuilt each field as
  `FieldValue(value=..., confidence=...)` — only 2 of the 4 keys, silently
  dropping the other two before they ever reached `extracted_json`. This
  predates this session and was untested. Consequence:
  `creators/fields.py::alias_docname()` (read by
  `journal_entry_creator.py`'s bank-leg resolution and
  `payment_entry_creator.py`'s party resolution) always returned `None` —
  a Capture Alias has never actually redirected a draft to its resolved
  record, only cosmetically bumped confidence to `1.0`. Even if the user
  had pre-created a Capture Alias for this statement's bank, it would
  never have been used.

  **Fixed (three parts):**
  1. **Round-trip.** `mappers/schema.py`'s `FieldValue` gained
     `mapped_doctype`/`mapped_docname` (optional, default `None`);
     `_fields_to_json()` includes them. Every mapper's `build_dto()`
     (`payment_entry_mapper.py`, `journal_entry_mapper.py`,
     `bank_statement_mapper.py`) now stamps `mapped_doctype` from its
     existing `_ENTITY_TYPE_BY_FIELD`/`_ROW_ENTITY_TYPE_BY_FIELD` map
     whenever a dto_field is alias-eligible at all (hit or miss), and
     `mapped_docname` from the resolver's result (hit only).
  2. **A bug this unmasked.** `journal_entry_creator.py::_append_mapped_row()`
     was using the row's raw OCR `account` text directly instead of
     `alias_docname(...)` — flagged as a known-but-unfixed gap in this
     session's earlier `PHASE_4_REVIEW_UX_PLAN.md` entry, now fixed
     (`account = _alias_docname(row.get("account")) or _value(...)`,
     mirroring `payment_entry_creator.py`'s existing pattern).
  3. **Clear errors for what alias genuinely can't fix** — a Company with
     no default Bank/Receivable/Payable account configured at all.
     `payment_entry_creator.py::create()`, `journal_entry_creator.py::
     create_grouped_by_date()`, and `_append_bank_transaction_legs()` now
     throw a specific `frappe.throw()` before `.insert()` when
     `bank_gl_account()`/`resolve_party()` returns no account, instead of
     letting ERPNext's own `set_against_account()` crash with the raw
     `TypeError`.

  **Feature (user's suggestion):** rather than requiring the user to
  pre-create every Capture Alias by hand and risk a `Failed` status if
  they forget, the reviewer can now supply an unresolved alias-eligible
  field directly in Preview and have it create the Capture Alias for
  future documents. `review.py::to_preview()` passes `mapped_doctype`/
  `mapped_docname` through per field; `_apply_field_corrections()` now
  sets `mapped_docname` to a changed value when the field is
  alias-eligible (trusting it as a Link pick) instead of always dropping
  it; new pure function `review.py::new_aliases(extracted, updated)`
  diffs before/after and returns alias-row specs for changed,
  alias-eligible fields. `router.py::save_corrections()` upserts a
  Capture Alias per spec — skipping any whose picked value isn't actually
  a real record of that doctype (`frappe.db.exists()` check, since this
  is client-supplied data), updating an existing conflicting alias rather
  than erroring on it. `captured_document.js`'s Preview dialog renders an
  alias-eligible header field as a native `Link` (`fieldtype`/`options`
  swap on the existing Dialog field, no new plumbing) with a specific
  "not mapped yet" hint when unresolved.

  **Design-principle note:** `router.py` now imports
  `mappers/alias_resolver.py::normalize()` — one pure string function, no
  OCR/LLM coupling — to compute the same lookup key `resolve()` uses. This
  bends `docs/DESIGN_PRINCIPLES.md`'s OCR/mappers-vs-creators separation
  slightly; relocating one function into a new shared module for this felt
  like ceremony, so it's disclosed here per CLAUDE.md's "bent principle"
  rule instead.

  **Scoped out (documented, not built):** Bank Statement transaction-row
  `counterparty_name`'s Customer-vs-Supplier ambiguity, and
  `payment_entry_mapper.py` always resolving `party_name` against
  `Supplier` regardless of `party_type` — pre-existing limitations, same
  shape as the already-documented "unscoped alias fallback can pick the
  wrong company" note in `alias_resolver.py`. Row/transaction table cells
  in Preview stay plain text (no Link autocomplete) — only Journal Entry
  rows' `account` field is alias-eligible at row level in practice, and
  the router's `frappe.db.exists()` check already makes a plain-text row
  correction safe either way.

  **Checks:** `bench --site erpnext.yoursite.in run-tests --app docapture`
  — 150/150 pass (63 unit + 87 integration); `ruff check .` clean; `bench
  migrate` clean (`FieldValue` is a plain dataclass, not a doctype — no
  schema change).

  Phase 4 stays `Awaiting Review` — same-phase fix, not new scope.

- **2026-07-21 (Phase 4 follow-up — Resolve Unknowns dialog + one-JE-per-row
  + Employee/Internal Transfer party categories):** user feedback on the
  existing Preview/Correction dialog — with a 190-row statement, resolving
  unknown counterparties one row at a time is bad UX; wanted a dedicated
  step, before Preview, that asks once per *distinct* unknown value instead
  of once per row, plus a plain-language party-category picker (Customer/
  Supplier/Employee/Internal Transfer) since the user has no Frappe/
  accounting background. Also asked to revert the Phase 4 kickoff's
  date-grouped Bank Statement design back to one Journal Entry per
  transaction row, and to ask before silently skipping a flagged duplicate
  instead of auto-rejecting it.

  **New:** `docapture/resolve.py` — `unknowns_summary(doc)` (read-only;
  dedups unresolved counterparties by exact text, flags forward-filled/
  low-confidence dates, unreadable rows, and dedup-flagged rows, one entry
  each regardless of row count), `alias_specs_from_resolutions()` and
  `apply_resolutions()` (pure, same `extracted_json` dict shape
  `docapture/review.py` already uses — a reviewer's answer is written
  directly onto every row sharing that counterparty text, no re-querying
  Capture Alias needed since the answer just given *is* the resolution).
  Two new whitelisted `router.py` methods, `unknowns()`/`save_resolutions()`
  (same `_require_reviewer()`/status-guard shape as `preview()`/
  `save_corrections()`; `save_resolutions()` reuses the existing
  `_save_new_aliases()` writer — same alias-spec shape `review.new_aliases()`
  already produces). `captured_document.js` gained a "Resolve Unknowns"
  button (Bank Statement only, shown before Preview) opening a dialog with
  one section per unknown-kind found (skips a section entirely when there's
  nothing of that kind); a "Skip" action goes straight to today's existing
  Preview/Approve flow unchanged — this step is soft, not a hard gate.

  **Party categories:** "Customer"/"Supplier" reuse the existing
  `resolve_party()`/Capture Alias machinery unchanged. "Employee" is a real
  ERPNext `Party Type` (confirmed via `frappe.get_all("Party Type")` against
  this bench) — added to Capture Alias's `entity_type` Select options
  (`capture_alias.json`); `get_party_account()` resolves it the same generic
  way as any party type with a configured `Party Account` row, so an
  unconfigured Employee still surfaces a clear error rather than crashing,
  same as the existing Customer/Supplier/no-default-account path.
  "Internal Transfer" isn't a party at all — a reviewer picks a plain
  Account instead (reuses Capture Alias's existing `Account` `entity_type`,
  no new option needed); `bank_statement_mapper.py`'s `_resolve_row()` now
  special-cases an `Account`-typed alias hit into a new `counter_account`
  DTO field instead of `party_type`/`party`, and `_PARTY_ENTITY_TYPES`
  extended to `(Customer, Supplier, Employee, Account)` so a future document
  with the same counterparty text auto-resolves too, not just this one.

  **One JE per row:** `journal_entry_creator.create_grouped_by_date()`
  renamed to `create_bank_entries()` and rewritten — JE creation moved
  inside the existing per-row loop (previously a second loop over a
  date-keyed `groups` dict), so every transaction row becomes its own
  Journal Entry regardless of whether another row shares its date. Also
  handles a `counter_account`-tagged row (the Internal Transfer case above)
  by posting straight to that account with no party leg at all, and a
  `force_create`-tagged row (a reviewer's "add anyway" on a flagged
  duplicate, from `resolve.py`'s `duplicate_overrides`) by skipping the
  `dedup.find_existing()` check instead of auto-rejecting.

  **Exchange rate:** `Captured Document` gained an `exchange_rate` Float
  field (document-level, not per-alias — statement currency is one thing
  for the whole file), settable via the Resolve Unknowns dialog. Both
  `create()` and `create_bank_entries()` now use `doc.exchange_rate` (falls
  back to `1`, unchanged behavior when unset) instead of the previous
  hardcoded `1`. **Real ERPNext constraint found via an actual `.insert()`
  failure while testing this:** `JournalEntry.set_exchange_rate()` forces a
  row's `exchange_rate` back to `1` whenever that row's account is already
  in the company's own currency (correct — same-currency accounts can't
  carry a real rate) and throws outright if a genuinely foreign-currency
  account appears without `multi_currency = 1` set on the entry. Fixed by
  setting `je.multi_currency = 1` whenever the resolved exchange_rate isn't
  `1`. The rate only ever has a visible effect on a row whose account is
  actually in a different currency than the company's.

  **Design-principle note:** `docapture/resolve.py` touches `frappe.db`
  (via `dedup.find_existing()`, `bank_gl_account()`) unlike
  `docapture/review.py`, which is deliberately pure — kept as a separate
  module rather than folded into `review.py` so that file's "no DB access"
  contract stays true; `apply_resolutions()`/`alias_specs_from_resolutions()`
  inside the new file are themselves still pure, same pattern as the
  Preview feature's split.

  **Checks:** `bench --site erpnext.yoursite.in run-tests --app docapture`
  — 176/176 pass (73 unit + 103 integration; new: `test_resolve.py` — 10
  unit tests for the pure `apply_resolutions()`/`alias_specs_from_resolutions()`
  functions plus 6 integration tests for `unknowns_summary()`'s dedup/
  flagging behavior; 6 new tests in `test_router.py` for `unknowns()`/
  `save_resolutions()`; `test_journal_entry_creator.py`'s date-grouping test
  replaced with a one-JE-per-row assertion, plus 3 new tests — exchange rate
  on a genuinely foreign-currency leg, Internal Transfer posting with no
  party, force-create bypassing dedup); `ruff check .` clean; `bench migrate`
  clean (`Captured Document.exchange_rate` field, `Capture Alias.entity_type`
  gained `Employee`).

  **Not done, flagged rather than silently skipped:** no manual Desk
  walkthrough of the new Resolve Unknowns dialog (no browser automation
  available in this session) — the backend round-trip (`unknowns()` →
  `save_resolutions()` → `approve()`) is covered by automated tests, but the
  actual dialog rendering/interaction has not been driven by a human yet.
  Party/account text inputs in the new dialog stay plain text, not Link/
  awesomplete widgets — same simplification already accepted for row-level
  fields in the existing Preview table; the server's `frappe.db.exists()`
  check is the real safety net either way. "Unreadable rows" and "uncertain
  dates" sections let a reviewer fill in a value per row but don't offer
  batch-fill across identical narrations — not built speculatively without
  evidence this case is common.

  Phase 4 stays `Awaiting Review` — same-phase follow-up per explicit user
  direction, not new unscoped work. Stopping here for explicit review before
  anything else — please try the Resolve Unknowns button on a real Bank
  Statement `In Review` capture (ideally the real UBI statement) before this
  is considered done.

- **2026-07-21 (Phase 4 follow-up — Preview dialog table UI too cramped):**
  user shared a screenshot of the real UBI statement (CAP-00054, ~190 rows)
  open in Preview — the modal had no `size` set (Bootstrap's narrow default,
  ~600px) so the transaction table's 7+ columns were crammed into it: the
  row-label cell ("Transaction 1") wrapped onto two lines, and values
  (Reference No, Withdrawal, Balance) were visibly clipping inside their
  inputs. Pre-existing gap from the Preview feature (2026-07-20 entry),
  surfaced now on real multi-hundred-row data.

  **Fixed, `captured_document.js` only:** `render_preview_dialog()`'s
  `frappe.ui.Dialog` gained `size: "extra-large"` (`modal-xl`, confirmed
  against `apps/frappe/frappe/public/js/frappe/ui/dialog.js:50`).
  `build_rows_table_html()`'s row-label cell shortened from
  `"{row_label} {n}"` to just `"#{n}"` — the row kind is already in the
  dialog title, doesn't need repeating on every row. Added
  `white-space: nowrap` on header cells and `min-width: 90px` on value
  inputs so long values (a 6-7 digit balance, a long reference number) stop
  clipping; the existing `table-responsive` wrapper still provides
  horizontal scroll as the fallback. Same treatment applied to the newer
  Resolve Unknowns dialog's tables (`build_parties_html`/`build_dates_html`/
  `build_unreadable_html`/`build_dupes_html`) for consistency, via one
  shared `.docapture-resolve-table` style block appended once in
  `render_resolve_dialog()`.

  Pure client-side markup/CSS change — no Python/doctype/test changes, not
  exercised by `bench run-tests` (same as the 2026-07-16 follow-up 5
  precedent for a client-only fix). **Not verified visually** — no browser
  available in this session; confirmed only that the file still parses
  (`node -e "new Function(fs.readFileSync(...))"`, syntax-only, not a
  render check) and that `ruff check .` stays clean (no Python touched).
  Needs a real look in the Desk UI before this can be called done.

  Phase 4 stays `Awaiting Review` — same-phase fix.

- **2026-07-21 (Phase 4 follow-up — Resolve Unknowns silently skipped rows
  with no counterparty_name):** user tried Resolve Unknowns for real
  (CAP-00057, first page of the UBI statement, 14 rows) and asked why only
  "GAYATRI PRIVATE LIMITED" (4 rows) showed up when the statement clearly
  has more distinct transactions. Checked the live `extracted_json`
  directly: 10 of the 14 rows have `counterparty_name = None` at all — bare
  bank reference codes ("TRF 201-54921", "AA5361070") or tax-payment
  narrations ("ePAY/To:e-DIRECT TAX COLLE/...") — and `resolve.py`'s
  `unknowns_summary()` only grouped by `counterparty_name`, so any row with
  no name text had nothing to key on and silently never appeared.

  **Fixed:** `resolve.py` gained `_row_identifier(row)` — `counterparty_name`
  when present, else `narration`, else `reference_no` — used consistently in
  `unknowns_summary()`'s grouping and `apply_resolutions()`'s row-matching
  (previously keyed on `counterparty_name` alone in both places). A row
  with no date/amount is excluded from this grouping entirely now (moved
  after the existing unreadable-row check) — asking "who is this" is
  premature until the date/amount question is answered first, and it was
  briefly double-surfacing in both sections. `bank_statement_mapper.py`'s
  `_resolve_row()` gained the same fallback — tries Capture Alias against
  narration/reference_no when counterparty_name is empty — so an answer
  given today auto-resolves the identical bank code on a future statement
  too, the same promise already made for named counterparties. Also added
  a 5th party category, **"Other (bank charge, tax, fee...)"**, alongside
  "Internal Transfer" — both route to a plain Account
  (`_ACCOUNT_ROUTED_CATEGORIES`), since real rows include tax/fee postings
  that aren't a self-transfer either and a reviewer with no accounting
  background shouldn't have to force one into the other's label.

  **New tests:** `test_bank_statement_mapper.py` — 2 (narration-only row
  resolves against an Account alias into `counter_account`, and against a
  Customer alias into `party_type`/`party`); `test_resolve.py` — 4 (2 unit:
  narration-keyed `apply_resolutions()` match, "Other" category routing; 2
  integration: `unknowns_summary()` groups by narration when
  `counterparty_name` is absent, and an unreadable row isn't also counted
  in the counterparties list).

  **Also fixed, found while re-running tests:** `test_build_dto_resolves_
  known_bank_account_alias` (pre-existing, unrelated to this fix) used a
  fixed literal account number with no salt, unlike every other test in
  this suite — collided with itself across repeated runs. Salted like the
  rest. Also caught, before committing to it: my first attempt at the two
  new fallback tests reused the literal text `"TRF 201-54921"` for realism
  — collided not with test leftovers but with **real data this site
  already has** (the user's own live Capture Alias row from testing the
  feature). Salted those too; a fixed literal that happens to resemble real
  narration text is a collision risk against genuine data, not just other
  test runs.

  **Checks:** `bench --site erpnext.yoursite.in run-tests --app docapture`
  — 182/182 pass (75 unit + 107 integration), stable across repeated runs;
  `ruff check .` clean. No doctype/schema changes, no migrate needed.

  Phase 4 stays `Awaiting Review` — same-phase fix.

- **2026-07-21 (Phase 4 follow-up — Preview table columns misaligned after
  Resolve Unknowns):** user screenshot of a real Preview dialog (CAP-00057)
  showed stray unlabeled "Customer"/"XYZ" and "Supplier"/"ABC" cells
  trailing off the end of some rows, not lined up under any column header.
  Root cause: `build_rows_table_html()` built its header from `data.rows[0]`
  only, but rows no longer share a uniform field set — Resolve Unknowns
  writes `party_type`/`party` (or `counter_account`) onto only the specific
  rows a reviewer actually answered, not every row, so a later row's extra
  fields had no matching header column and rendered as trailing unlabeled
  `<td>`s. Pre-existing latent bug (any row that happened to alias-resolve
  differently from row 0 could already trigger it), just far more visible
  now that Resolve Unknowns actively adds those fields to many rows.

  **Fixed, `captured_document.js` only:** `build_rows_table_html()` now
  unions every row's field names for the header (first-seen order) instead
  of trusting row 0 alone, and looks up each row's cell by field name,
  rendering a blank `<td>` (no input) wherever a given row doesn't have that
  field — matches `review.py::_apply_field_corrections()`'s existing
  behavior of silently dropping a correction for a field that row never had
  in the first place, so an empty cell staying non-editable isn't a new
  restriction. `save_preview_corrections()`'s submit-side reading logic
  already iterated each row's own field list (not the header), so it needed
  no change.

  Also confirmed, on user request, that Resolve Unknowns answers really do
  persist to Capture Alias: checked this site's live rows directly —
  `CALIAS-00059` (TRF 201-54921 → Customer XYZ) and `CALIAS-00060` (TRF
  312801010037001 → Supplier ABC), both `source: User Confirmed`, created
  exactly when the user answered those two rows earlier in this session.

  Pure client-side markup change — no Python/doctype/test changes, not
  exercised by `bench run-tests`. **Not verified visually** — no browser
  available in this session; confirmed only that the file parses and `ruff
  check .` stays clean (no Python touched).

  Phase 4 stays `Awaiting Review` — same-phase fix.

- **2026-07-21 (Phase 4 follow-up — Resolve Unknowns "Who exactly?" becomes
  a real Link search):** user feedback on the Resolve Unknowns dialog — once
  a category (Customer/Supplier/...) is picked, the party picker should let
  the reviewer search/select an existing record instead of typing an exact
  name by hand, to cut human error (typo → a new placeholder-ish record
  instead of the real one, or a picked value that doesn't exist at all and
  gets silently dropped by `_save_new_aliases()`'s `frappe.db.exists()`
  check with no feedback as to why).

  **Fixed, `captured_document.js` only:** `build_parties_html()`'s "Who
  exactly?" cell is now an empty container instead of a plain `<input>`.
  New `bind_party_category_controls(dialog, company)` listens for the
  category `<select>` changing and rebuilds that row's picker as a real
  Frappe Link control (`frappe.ui.form.make_control`, `only_input: true` —
  same construction `frappe/public/js/frappe/ui/filters/filter.js` uses for
  its own dynamic-doctype field) targeting whichever doctype the category
  maps to (`PARTY_CATEGORY_DOCTYPE`, mirrors `resolve.py`'s
  `_ENTITY_TYPE_BY_CATEGORY` client-side) — native search-as-you-type
  against real records, "Create a new ..." quick-entry included for free.
  The control is destroyed and rebuilt on every category change rather than
  having its `options` mutated in place, since the target doctype itself
  changes each time. `Account`/`Employee` searches are filtered to the
  capture's own `company` (`_COMPANY_SCOPED_DOCTYPES`) so a reviewer can't
  pick a record belonging to a different company; `Customer`/`Supplier`
  aren't company-scoped in ERPNext, so they get no filter, matching how
  `resolve_party()` itself already treats them. `save_resolutions()` now
  reads each row's answer via the control's `.get_value()` instead of a
  plain `.val()`. Also excluded checkboxes from the `.docapture-resolve-
  table` min-width CSS rule added in the previous entry — it was silently
  stretching the "Add anyway" duplicate-row checkbox to 90px wide too.

  Pure client-side change — no Python/doctype/test changes, not exercised
  by `bench run-tests`. **Not verified visually** — no browser available in
  this session; confirmed only that the file parses and `ruff check .`
  stays clean.

  Phase 4 stays `Awaiting Review` — same-phase fix.

- **2026-07-21 (Phase 4 follow-up — pin LLM temperature=0 for extraction
  consistency):** user re-ran the real UBI statement through the pipeline a
  second time and found row 8 ("TRF 312801010037001", already resolved via
  a saved alias) working fine, but a *different* row — row 11 ("eTXN/To:
  312801010037001") — got `counterparty_name = "312801010037001"` this run
  when it had been `None` the previous run, surfacing as a fresh unresolved
  "unknown" the user hadn't seen before. Traced it to `openai_client.py`/
  `claude_client.py` never setting `temperature` on either extraction call
  at all — API default (non-zero) sampling applies, so an ambiguous call
  ("is this bare digit string a counterparty name?") can legitimately
  answer differently across two otherwise-identical runs of the same
  document. Discussed whether row 8 and row 11 (same account number,
  different narration wording) should be merged into one question — user
  chose to keep them separate (safer; merging by embedded-number matching
  risks wrongly conflating two genuinely different parties that happen to
  share digits) — not built.

  **Fixed:** `temperature=0` added to both `extract_fields()` and
  `extract_rows()` in both `openai_client.py` and `claude_client.py` — a
  structured-extraction call has no business sampling creatively; this
  makes the model consistently pick its highest-probability answer instead.
  Doesn't *guarantee* byte-identical output across runs (model-serving-level
  noise can still exist even at temperature 0), but removes the deliberate
  randomness that was the direct cause here. Model choice (gpt-4.1 vs.
  another) was not the issue — this is a decoding-parameter gap, not a
  capability gap, so switching models alone would not have fixed it.

  **Also fixed, found while re-running tests:** a second, unrelated
  pre-existing test-collision — `test_unresolved_counterparty_name_left_
  unresolved` hardcoded the literal `"AA5360992"`, and the user's own live
  testing had since created a real Capture Alias resolving that exact text
  to Employee HR-EMP-00001, so the test's "stays unresolved" assertion
  failed against real site data, not leftover test data. Salted like the
  session's earlier fixes of the same shape.

  **Checks:** `bench --site erpnext.yoursite.in run-tests --app docapture`
  — 182/182 pass, stable across two consecutive runs; `ruff check .` clean.
  No doctype/schema changes, no migrate needed.

  Phase 4 stays `Awaiting Review` — same-phase fix.
