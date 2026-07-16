# Works standalone, fails inside bench

If PaddleOCR runs fine in a plain script or notebook but fails (or behaves
differently) inside `bench` / a `frappe.enqueue` job, the PaddleOCR install
itself is probably fine — look at the bench-specific context first.

## Checklist, in order

1. **Confirm it's actually bench's venv running the job.** Per `CLAUDE.md`,
   this project uses bench's own venv (no `uv`/`.venv`) with deps declared
   in `pyproject.toml`/`requirements.txt`. Confirm `paddlepaddle==3.2.0` and
   `paddleocr==3.3.3` are actually installed into *that* venv, not a
   separate one used for ad-hoc testing.

2. **Working directory / relative paths.** The reference script used an
   absolute path (`/content/Sales order_page-0001.jpg`). Inside a
   `frappe.enqueue` job, the working directory and file paths (Frappe
   File doctype paths, site-specific `private`/`public` file dirs) are
   different — a relative-path assumption that worked in a notebook will
   silently fail or read the wrong file inside bench. Use Frappe's file
   path resolution (not a hardcoded/relative path) when wiring this into
   `paddle_engine.py`.

3. **Job re-enqueue / stale status.** Per Phase 2's job design notes in
   `PHASED_DEVELOPMENT.md`: each job should re-check the document's current
   `status` before doing work, guarding against a duplicate/stale run if
   enqueued twice or the doc was rejected mid-flight. If PaddleOCR appears
   to run twice on the same document, or runs on a document that should no
   longer be `Uploaded`, check this guard exists before assuming it's a
   PaddleOCR-level bug.

4. **`enqueue_after_commit`.** If the OCR job is enqueued in the same
   request/transaction that just set status to `Uploaded`, and
   `enqueue_after_commit=True` wasn't used, the job can start before that
   status write is committed — the job then reads stale state (or a
   document that doesn't look "ready" yet from its perspective). This
   presents as an intermittent, hard-to-reproduce bug, not a consistent
   PaddleOCR error — if the failure is intermittent and timing-dependent,
   suspect this before digging further into PaddleOCR itself.

5. **Queue assignment.** OCR jobs should be on the `long` queue (not
   `short`), per Phase 2 scope. If jobs are timing out or getting killed
   mid-run under load, confirm queue assignment before assuming a
   PaddleOCR performance problem.

6. **Model reload per job.** See `references/runtime_errors.md`'s memory
   section — re-instantiating `PaddleOCR(...)` inside every job function
   (rather than once per worker process) is a common cause of jobs being
   slow or memory-heavy in a way that doesn't show up when testing a single
   `.predict()` call standalone.
