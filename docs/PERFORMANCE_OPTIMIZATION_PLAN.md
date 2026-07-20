# Speed up Bank Statement OCR + LLM processing

## Context

User reported unacceptable UX: 1-page document takes 30-40s before preview is
available; an 8-9 page Bank Statement takes 7-8 minutes, during which the user
has no feedback and must sit and wait. Confirmed via investigation (all
file:line refs below) that the slowness has two independent root causes of
similar magnitude, both from **sequential per-page work inside a single
background job**, not from GPU/CPU choice (already CPU-only, correctly so) or
from any queueable-but-missing infra. User confirmed the slow documents are
specifically Bank Statements. Goal: cut wall-clock time without changing OCR
model, DPI, preprocessing flags, LLM model, or prompts — i.e. zero accuracy
impact, pure parallelization + waste removal.

Note: this repo's phase-gate workflow (`docs/PHASE_STATUS.md`) doesn't cover
this work — it sits outside the phase tracker (not Phase 4/5 work). Treat it
as its own tracked unit: implement, checkpoint, get review, rather than
folding into whatever phase is currently in flight.

**Status: plan only — implementation not started. Do not begin coding
without explicit go-ahead.**

## Root causes (confirmed)

1. **OCR pages processed sequentially** — `docapture/ocr/pipeline.py:69`,
   `pages = [_resolve_page(page_result, doc.source_type) for page_result in page_results]`.
   Model itself is already cached correctly per worker process
   (`paddle_engine.py:30-35`, `functools.lru_cache` around `_get_ocr()`), so
   the cost is pure serialization of independent page inferences, not
   redundant model loads.

2. **LLM row-extraction sequential per page, for Bank Statements specifically**
   — `mappers/bank_statement_mapper.py:91-96`, a plain `for page_text in pages:`
   loop calling `llm.extract_rows(...)` (blocking HTTP call to OpenAI
   `gpt-4.1`, `openai_client.py:53-69`) once per page. For a 9-page statement
   that's ~9-11 sequential blocking network calls in one job. Each call is
   independent (no shared state, page order only matters for the final output
   order).

3. **Synchronous LangSmith trace flush on every LLM call** —
   `openai_client.py:49-50` / `claude_client.py:44-45`, `self._tracer.flush()`
   called after every single `extract_fields`/`extract_rows`. Comment in
   `llm_client.py:61-73` explains *why* it's synchronous (RQ workers
   `os._exit(0)` and skip atexit hooks, so it can't just rely on
   normal process-exit flushing) — but it doesn't need to run after *every*
   call, just once before the job ends. This adds an extra network
   round-trip on the critical path per call, ~9-11 times per bank statement.

4. **No progress feedback** — `Captured Document.status` only has
   document-level states (`Uploaded → OCR Done → Parsed → In Review`), and
   `captured_document.js` doesn't subscribe to Frappe's already-firing
   realtime `doc_update` events (`ocr/pipeline.py:33,46`,
   `mappers/pipeline.py` `db_set(..., notify=True)`). User has no visibility
   into progress and no reason to believe waiting will pay off soon.

5. **`background_workers: 1`** in `sites/common_site_config.json:2` — one
   worker process serves every queue in the whole bench, so concurrent
   uploads from different users serialize behind each other regardless of
   per-document fixes. Confirmed present, unrelated to `gunicorn_workers: 25`
   (web-only).

## Approach

Implement in order **C → B → A → D** (each independently testable; C first
because it removes one variable — synchronous flush — before B introduces
concurrent LLM calls that also go through the same tracer).

### C. Batch the tracer flush (`mappers/openai_client.py`, `claude_client.py`, `llm_client.py`, `mappers/pipeline.py`)

- Add a `flush()` method to `OpenAIParser`/`ClaudeParser` (each wraps its own
  `self._tracer.flush()`), remove the per-call `flush()` from inside
  `extract_fields`/`extract_rows`.
- Add `flush()` to the `LLMParser` Protocol in `llm_client.py` so it's part of
  the documented contract.
- In `mappers/pipeline.py` `run_mapper`, get the parser once, wrap the
  existing try/except body, call `llm.flush()` in a `finally` block — covers
  both the success path and the existing `except Exception` failure path,
  still before the RQ worker's `os._exit(0)`.
- Update `mappers/test_pipeline.py`'s `_StubLLM` with a no-op `flush()`.

### B. Parallelize LLM row-extraction for Bank Statements (`mappers/bank_statement_mapper.py:75-101`)

- In `build_dto`, submit the header `extract_fields` call and every page's
  `extract_rows` call to a `concurrent.futures.ThreadPoolExecutor` (I/O-bound
  network calls — GIL isn't a constraint). Collect row-extraction futures by
  index (not `as_completed`) so `transactions` is rebuilt in original
  page/row order regardless of which call finishes first — required, since
  downstream logic (`_correct_withdrawal_deposit`, `_forward_fill_date`)
  depends on transaction order.
- Worker count: expose via `frappe.conf.get("docapture_llm_row_workers", 8)`
  — sized for concurrent-request headroom against the OpenAI org's rate
  limit, not CPU count (this is network I/O, not compute).
- No retry/backoff logic added speculatively — only add if 429s are actually
  observed in testing.

### A. Parallelize OCR pages (`docapture/ocr/pipeline.py`, `paddle_engine.py`)

- Wrap the loop at `pipeline.py:69` in a `ThreadPoolExecutor`, using
  `executor.map` (preserves input order automatically) over `_resolve_page`.
  Do **not** touch `pymupdf_extractor.py`'s internal per-page rasterization
  loop — it shares one `pymupdf.Document` handle across iterations, not
  safely fannable across threads, and rasterization is cheap relative to OCR
  inference.
- Worker count: CPU-bound this time (onnxruntime inference) — size via
  `os.cpu_count()`, capped at a small default (e.g. 4) and overridable via
  `frappe.conf.get("docapture_ocr_page_workers")`.
- **Must verify before shipping** (not assumed): that onnxruntime's
  `intra_op_num_threads` is actually controllable via a `PaddleOCR(...)`
  kwarg passthrough (avoids N-pages × full-core-count oversubscription when
  running pages concurrently), and that the single cached `PaddleOCR`
  instance (`_get_ocr()`, `lru_cache(maxsize=1)`) is safe to call from
  multiple threads concurrently — confirm by running a small script that
  fires concurrent `.predict()` calls on the same cached instance against a
  known fixture image and diffing output against a sequential baseline.

### D. Progress UI + worker concurrency

- Add `frappe.publish_realtime("docapture_progress", {...}, doctype=,
  docname=)` calls at the same page-completion points A and B already touch
  (no new doctype field — progress is transient, not worth persisting).
- In `captured_document.js`, subscribe once via `frappe.realtime.on(...)` and
  show progress via `frm.dashboard.set_headline_alert(...)` (existing Frappe
  API, no new UI library).
- Raise `background_workers` in `sites/common_site_config.json` from `1` to
  `3` (not to core count) — each additional worker process loads its own
  separate PaddleOCR model copy in memory on first use (the `lru_cache` is
  per-process), so this is a memory-bound choice on a box with limited spare
  RAM, not a CPU-bound one. Bigger jump only worth revisiting if monitoring
  later shows real throughput limits under concurrent load.

## Critical files

- `apps/docapture/docapture/ocr/pipeline.py`
- `apps/docapture/docapture/ocr/paddle_engine.py`
- `apps/docapture/docapture/mappers/bank_statement_mapper.py`
- `apps/docapture/docapture/mappers/pipeline.py`
- `apps/docapture/docapture/mappers/openai_client.py`, `claude_client.py`, `llm_client.py`
- `apps/docapture/docapture/docapture/doctype/captured_document/captured_document.js`
- `sites/common_site_config.json`

## Verification

- `cd apps/docapture && ruff check .`
- `bench --site erpnext.yoursite.in run-tests --app docapture` (extend
  `mappers/test_pipeline.py`, `test_bank_statement_mapper.py`, add new
  `ocr/test_pipeline.py` — assert output order is preserved under reversed
  completion timing, per the existing `UnitTestCase` pattern in this app)
- Manual: real multi-page Bank Statement fixture
  (`tests/fixtures/mappers/sample_bank_statement_ubi.pdf`) through the full
  pipeline before/after — diff extracted transactions for identical
  values/order (accuracy unaffected), time the wall-clock difference.
- Manual: `bench start`, upload a real multi-page Bank Statement, confirm the
  form shows live progress without `frm.reload_doc()`.
- Manual: after raising `background_workers`, confirm 3 worker processes
  exist and `free -h` / per-process RSS stays within budget under 2-3
  concurrent uploads (no swap growth).
- Concurrent-safety check for A (not optional): script that fires N threads
  calling the cached `PaddleOCR` instance's `.predict()` concurrently on a
  fixture image, diff each thread's output against a known-good
  single-threaded baseline.
