# Install / import errors

# Install / import errors

## Current known-good install (ONNX Runtime engine, no `paddlepaddle`)

**Read this first.** As of the latest validation in `docs/OCR_MODEL_EVALUATION.md`,
this project does **not** install `paddlepaddle` at all — bench's venv is
pinned to Python 3.14 by Frappe, and `paddlepaddle` ships no `cp314` wheel
for any version. The working install is:

```bash
pip install paddleocr onnxruntime
```

with the pipeline constructed as:

```python
ocr = PaddleOCR(
    text_detection_model_name="PP-OCRv6_medium_det",
    text_recognition_model_name="PP-OCRv6_medium_rec",
    engine="onnxruntime",
    ...
)
```

This works because `paddleocr`'s own `pyproject.toml` does not declare
`paddlepaddle` as a dependency — the inference engine (`paddle` /
`transformers` / `onnxruntime`) is an intentionally separate install, and
`onnxruntime` has `cp314` wheels where `paddlepaddle` does not.

**TODO:** both `paddleocr` and `onnxruntime` are still unpinned as of the
last validated run — pin exact versions here and in `OCR_MODEL_EVALUATION.md`
once bench-venv confirmation (see that doc's Status section) is done, then
update this section with the pinned versions.

**If `paddlepaddle` somehow ends up installed anyway** (e.g. someone follows
an old instruction, or a dependency chain pulls it in unexpectedly),
recheck immediately — that's a regression back into the Python 3.14 blocker,
not a harmless extra package. `pip show paddlepaddle` should return nothing
in a correctly set up bench venv for this project.

## `ModuleNotFoundError: No module named 'paddle'`

**Do not "fix" this by installing `paddlepaddle`** — on this project's bench
venv (Python 3.14), that install will fail outright (no `cp314` wheel
exists), and even if it somehow succeeded, `paddlepaddle` is not part of
the current supported path here (see above). If you see this error, first
check whether the code is passing `engine="onnxruntime"` — this error
usually means something is trying to use the `paddle` engine by default
(e.g. `engine=` was left unset, or an old code path/example was copied that
predates the ONNX Runtime switch). Fix the `engine=` argument, don't chase
a `paddlepaddle` install.

This error is only actually expected/relevant if deliberately testing the
historical `engine="paddle"` path documented as a fallback reference in
`OCR_MODEL_EVALUATION.md` — and that path cannot run in bench's venv at all,
only in an external environment with a compatible Python version (see that
doc for context).

## Dependency resolution conflicts (scikit-image, opencv-python, numpy pins)

Older `paddleocr` releases pinned specific `scikit-image`/`opencv-contrib-
python` versions that can conflict with other packages already in
`pyproject.toml` (this project also declares `opencv-python-headless`,
`pillow`, `pymupdf` — watch for opencv package conflicts specifically:
`opencv-python` vs `opencv-python-headless` vs `opencv-contrib-python` are
mutually incompatible if more than one ends up installed). This applies
regardless of which inference engine is in use — it's a `paddleocr`/opencv
conflict, not a `paddlepaddle`-specific one.

Fix: pin `paddleocr` to an exact version (see TODO above — not yet pinned)
rather than a floating `>=`, and if a conflict error names a specific opencv
variant, check `pyproject.toml`/`requirements.txt` for a duplicate opencv
declaration before changing `paddleocr`'s version.

## `pip install` fails outright / `ResolutionImpossible`

If this happens on `pip install paddleocr onnxruntime` specifically inside
bench's venv, don't assume it's the same Python-3.14 wheel problem that
blocked the `paddlepaddle` path — `onnxruntime` does have `cp314` wheels, so
a resolution failure here has a different root cause. Check:
1. Whether something in `pyproject.toml`/`requirements.txt` is pinning a
   conflicting version of a shared dependency (`numpy`, `PyYAML`,
   `requests`, `typing-extensions` — all declared by `paddleocr` itself per
   its `pyproject.toml`).
2. Whether `paddlex[ocr-core]` (a `paddleocr` dependency) is pulling in
   something unexpected — inspect the actual resolved dependency tree
   (`pip install --dry-run` or `pip show paddlex`) rather than guessing.

