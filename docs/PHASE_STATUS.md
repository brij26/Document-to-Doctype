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
| 3 | Mapper / LLM layer (`mappers/*`) | Not Started |
| 4 | Review queue + draft creation | Not Started |
| 5+ | Future (Should / Nice-to-Have) | Not Started |

---

## Current focus

**Phase 2 — Approved.** OCR layer (`ocr/*`) built: `OCREngine` protocol,
`pymupdf_extractor`, `preprocess`, `paddle_engine`, `tesseract_engine`, and the
`frappe.enqueue` job writing `raw_ocr_json`. Phase 3 not started — awaiting
explicit go-ahead.

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
