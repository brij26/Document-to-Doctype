# Runtime errors during `.predict()`

## Model download / network failure on first run

PaddleOCR downloads model weights (detection + recognition + any enabled
optional modules like orientation classification) from a remote source on
first use, and caches them locally (typically under `~/.paddlex` or a
similar cache directory) — it does not ship the weights in the pip package.

If `.predict()` fails with a connection/timeout error, or hangs on first
call:
- Check outbound network access from wherever this is actually running.
  **This matters a lot for a bench server** — if the production/staging
  bench server has restricted egress (no general internet access), the
  model download will fail there even though it worked fine in a notebook
  with unrestricted internet. Pre-download and bundle/cache the model
  weights as part of deployment rather than relying on a live download
  happening inside a `frappe.enqueue` job.
- If it's a proxy/firewall issue rather than a hard block, PaddleOCR's docs
  mention alternate download sources (AIStudio, ModelScope, etc.) that can
  be configured — see `references/paddleocr_docs.md`.

## Device / GPU errors

`use_doc_orientation_classify`, `use_doc_unwarping`, and
`use_textline_orientation` are all set to `False` in the known-good config
specifically to keep the pipeline lean — re-enabling any of them adds
another model load and another possible device mismatch. If a device error
appears after changing these flags, that's the first thing to revert and
re-test in isolation.

For CPU-only bench deployment (the expected default) with the current
`engine="onnxruntime"` setup, don't pass a `device="gpu"` kwarg unless the
target machine actually has a supported GPU and `onnxruntime-gpu` (not
plain `onnxruntime`) installed — plain `onnxruntime` is CPU-only and will
error if asked for a GPU device.

(This section previously discussed `paddlepaddle` GPU wheels — not
applicable anymore, since `paddlepaddle` isn't part of this project's
install at all. See `install_errors.md` for why.)

## Memory errors / OOM inside a worker process

Loading `PaddleOCR(...)` instantiates multiple models into memory. If this
happens inside a `frappe.enqueue` job:
- **Don't instantiate a fresh `PaddleOCR(...)` per job/per document.** Model
  load is expensive in both time and memory; instantiate once (e.g. at
  module import time or via a cached singleton) and reuse it across jobs
  in the same worker process.
- Per Phase 2's job design notes in `PHASED_DEVELOPMENT.md`, OCR should run
  on the `long` queue (not `short`) — confirm this if OOM/timeout issues
  show up specifically under load, since the `short` queue may have
  tighter worker resource limits or run more concurrent jobs per worker.

## Shape / dimension errors on a specific input

If `.predict()` crashes only on certain files (not all), the input itself
is usually the cause, not the PaddleOCR install:
- Corrupted or zero-byte upload
- Unusual color mode (e.g., CMYK JPEG, indexed-palette PNG) that the
  preprocessing step doesn't expect
- A PDF where `pymupdf_extractor`'s digital-vs-scanned branch mis-detects
  and hands PaddleOCR something unexpected (e.g., an empty rasterized page)

Isolate by re-running `.predict()` directly against the saved intermediate
image (after `pymupdf_extractor`/`preprocess`, before it reaches PaddleOCR)
outside the job, to confirm whether the bug is in preprocessing or in
PaddleOCR itself.
