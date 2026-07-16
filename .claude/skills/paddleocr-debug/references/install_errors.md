# Install / import errors

## `ModuleNotFoundError: No module named 'paddle'`

The most common PaddleOCR error by far. `paddleocr` imports `paddle`
(from the separate `paddlepaddle` package) at import time — if `paddlepaddle`
didn't actually install (or installed into a different environment/venv
than the one running the script), this is what you get.

Causes, in order of likelihood:
1. **`paddlepaddle` install silently failed or was skipped.**
   `paddleocr` imports `paddle` (from the separate `paddlepaddle` package) at
   import time. If `paddlepaddle` didn't install successfully (or was installed
   into a different environment/venv than the one running the script), you'll
   get this error.

   The confirmed-working installation used during testing is:

   ```bash
   pip install paddlepaddle==3.2.0
   pip install paddleocr==3.7.0
   ```

   Ensure both packages are installed in the same Python environment.
2. **Wrong environment.** Script run outside the venv `paddlepaddle` was
   installed into. In this project specifically: bench uses its own venv
   (no `uv`/`.venv` — see `CLAUDE.md`), so check the job/worker process is
   actually using bench's venv Python, not a system Python or a stray venv.
   `which python` / `python -c "import paddle; print(paddle.__file__)"`
   inside the exact process context that's failing.
3. **Platform/CUDA mismatch wheel.** `paddlepaddle` ships different wheels
   per OS/CPU/GPU/CUDA version. Installing the wrong one can silently
   produce an unimportable package on some platforms. If on Linux CPU-only
   (the expected case for a bench server), use the plain
   `pip install paddlepaddle==3.2.0` — don't reach for a GPU/CUDA-specific
   index URL unless the target actually has a supported GPU.

## Dependency resolution conflicts (scikit-image, opencv-python, numpy pins)

Older `paddleocr` releases pinned specific `scikit-image`/`opencv-contrib-
python` versions that can conflict with other packages already in
`pyproject.toml` (this project also declares `opencv-python-headless`,
`pillow`, `pymupdf` — watch for opencv package conflicts specifically:
`opencv-python` vs `opencv-python-headless` vs `opencv-contrib-python` are
mutually incompatible if more than one ends up installed).

Fix: pin `paddleocr==3.7.0` explicitly (not a floating `>=`) together with `paddlepaddle==3.2.0` as already
recorded in `docs/OCR_MODEL_EVALUATION.md`, and if a conflict error names a
specific opencv variant, check `pyproject.toml`/`requirements.txt` for a
duplicate opencv declaration before changing paddleocr's version.

## `pip install` fails outright / `ResolutionImpossible`

Usually means an unpinned or too-old `paddleocr` version is being resolved
against an incompatible Python version. Confirm the target Python version
bench's venv is running, and use the exact pins
(`paddlepaddle==3.2.0` and `paddleocr==3.7.0`) rather than an unpinned install —
this project already validated that combination.


## `NotImplementedError: ConvertPirAttribute2RuntimeAttribute`

Example:

```
NotImplementedError:
ConvertPirAttribute2RuntimeAttribute not support
[pir::ArrayAttribute<pir::DoubleAttribute>]
```

Observed while running PP-OCRv6 on Google Colab CPU.

Notes:
- The error occurs inside PaddlePaddle's inference runtime (`predictor.run()`),
  before OCR inference begins.
- It is not caused by the input image.
- It also reproduces with PaddleOCR's official demo image.
- If encountered, first verify the runtime (CPU vs GPU) and PaddlePaddle /
  PaddleOCR version compatibility before debugging application code.
