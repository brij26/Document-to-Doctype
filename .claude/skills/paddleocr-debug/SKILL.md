---
name: paddleocr-debug
description: Debug PaddleOCR / PP-OCRv6 errors in docapture's OCR layer (docapture/ocr/paddle_engine.py). Use this any time a PaddleOCR-related traceback, install failure, or unexpected output shape shows up — import errors ("No module named 'paddle'"), pip dependency conflicts, model download failures, GPU/CPU device mismatches, missing or malformed keys in the predict() result (rec_texts, rec_scores, text_word, text_word_boxes, etc.), JSON serialization errors from numpy arrays, return_word_box not behaving as expected, or PaddleOCR behaving differently inside a bench/frappe.enqueue job than it did in a standalone script. Also use when the user mentions PP-OCRv6, PP-OCRv5, PaddleOCR, paddle_engine, or docapture's OCR layer generally, even if they haven't pasted a full error yet — ask for the traceback if it's not already in context.
---

# PaddleOCR / PP-OCRv6 debugging (docapture OCR layer)

This skill is scoped to `docapture/ocr/paddle_engine.py` — the PaddleOCR
implementation of the `OCREngine` protocol (see `docs/ARCHITECTURE.md`).
Tesseract-specific issues belong to `tesseract_engine.py` and are out of
scope here.

Known-good baseline, confirmed working (see
`docs/OCR_MODEL_EVALUATION.md` for full context — including why
`paddlepaddle` is NOT part of this install, and the historical
`paddlepaddle`-based version kept there for reference only):

```
paddleocr        # version TBD — not yet pinned, see OCR_MODEL_EVALUATION.md
onnxruntime      # version TBD — not yet pinned, see OCR_MODEL_EVALUATION.md
```

**No `paddlepaddle` install.** Bench's venv is pinned to Python 3.14 by
Frappe, and `paddlepaddle` has no `cp314` wheel — the engine is ONNX
Runtime instead, which does support `cp314`.

```python
from paddleocr import PaddleOCR

ocr = PaddleOCR(
    text_detection_model_name="PP-OCRv6_medium_det",
    text_recognition_model_name="PP-OCRv6_medium_rec",
    engine="onnxruntime",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    return_word_box=True,
)
result = ocr.predict("/path/to/file.jpg")
for res in result:
    res.print()
    res.save_to_img("output")
    res.save_to_json("output")
```

When debugging, first check: is the failing environment actually running
these exact pinned versions? Version drift is the single most common cause
of PaddleOCR breakage — check before going deeper.

```bash
pip show paddleocr onnxruntime
# paddlepaddle should NOT be listed here — if it is, that's worth
# investigating on its own (see install_errors.md), since it means
# something pulled it in despite it not being part of this project's
# supported install path.
pip show paddlepaddle 2>&1 | head -1
```

## Step 1 — classify the error

Read the traceback and match it to one of these buckets before doing
anything else. The fix path is completely different per bucket.

1. **Import/install failure** (`ModuleNotFoundError`, pip resolution error,
   wheel not found) → `references/install_errors.md`
2. **Runtime crash during `.predict()`** (device error, memory error, model
   download/network error, shape mismatch) → `references/runtime_errors.md`
3. **Output looks wrong but doesn't crash** (missing keys, `text_word` empty,
   `return_word_box` seemingly ignored, low confidence, numpy-not-JSON-
   serializable) → `references/output_shape_issues.md`
4. **Works standalone but fails inside bench** (works in a plain script /
   notebook, breaks inside `frappe.enqueue` or the bench venv) →
   `references/bench_integration_issues.md`

If genuinely unsure which bucket, read the first and last 5 lines of the
traceback — the bucket is almost always obvious from where the failure
happens (import time vs. `.predict()` call vs. after-the-fact when
handling the result vs. only failing inside a bench worker process).

## Step 2 — read the relevant reference file

Each reference file below has: known error signatures, root causes, and the
fix. Read only the one(s) that match — don't load all of them into context
for a single error.

- `references/install_errors.md`
- `references/runtime_errors.md`
- `references/output_shape_issues.md`
- `references/bench_integration_issues.md`
- `references/paddleocr_docs.md` — links to authoritative PaddleOCR docs,
  for anything not covered by the above (novel error signature, version-
  specific behavior change, etc.)

## Step 3 — verify the fix against the pipeline's actual contract

A fix that makes PaddleOCR run without crashing is not the same as a fix
that produces output `docapture/ocr/*` can actually use. After resolving
the immediate error, re-check against `docs/ARCHITECTURE.md`'s
`raw_ocr_json` contract:

- Are `rec_texts` / `rec_scores` / `rec_polys` / `rec_boxes` present and
  JSON-serializable (not raw numpy arrays)?
- If `return_word_box=True` was requested, are `text_word` and
  `text_word_boxes` both present and non-empty?
- Does the fix hold for both the digital-text-layer path and the
  rasterized/scanned-image path (Phase 2 scope explicitly covers both)?

Don't report the error "fixed" until this step passes — a change that only
suppresses the traceback but silently returns malformed OCR JSON is worse
than the original crash, since it will surface much later as a Phase 3
mapper failure instead.

## Step 4 — if genuinely stuck

Note the paddlepaddle/paddleocr version, OS, Python version, and full
traceback, then check `references/paddleocr_docs.md` for the GitHub
issues/discussions search — most PaddleOCR errors are version-specific
and already reported there. Don't guess at a fix for an unfamiliar error
signature; look it up.
