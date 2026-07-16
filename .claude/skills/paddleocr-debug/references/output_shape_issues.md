# Output looks wrong but doesn't crash

Confirmed baseline shape (from actual runs, see
`docs/OCR_MODEL_EVALUATION.md`) — compare against this before assuming
something is broken:

**With `return_word_box=False` (default):**
Top-level keys include `rec_texts`, `rec_scores`, `rec_polys`, `rec_boxes` —
all **line-level**, index-aligned lists.

**With `return_word_box=True`:**
Adds `text_word` and `text_word_boxes` — same line-count length, each entry
a list of per-line tokens (words + whitespace + punctuation, each
separately), e.g.:

```json
rec_text: "Sigzen Tech"
text_word:       ["Sigzen", " ", "Tech"]
text_word_boxes: [[32,26,83,54], [92,26,97,54], [102,26,139,54]]
```

## `text_word` / `text_word_boxes` missing or empty even though `return_word_box=True`

- Confirm `return_word_box=True` is actually reaching the `PaddleOCR(...)`
  constructor call that's executing — a common mistake is setting it on a
  different instantiation than the one actually used (e.g., a cached/module-
  level instance created before the flag was added).
- `return_word_box` is confirmed working with **`engine="onnxruntime"`** —
  this is the current project setup (see `docs/OCR_MODEL_EVALUATION.md`),
  verified to produce correctly-shaped `text_word`/`text_word_boxes` with
  the same tokenization behavior as the historical `paddle_static`-engine
  run. If `engine=` gets changed to something else (`"paddle"`,
  `"transformers"`), word-box support has NOT been verified for that engine
  in this project — don't assume it carries over silently, re-verify.

## Whitespace/punctuation tokens polluting downstream mapping

`text_word` includes literal whitespace (`" "`) as its own token, and splits
punctuation (`"`, `(`, `)`, `.`, `:`, `&`) from adjacent words. This is
expected PP-OCRv6 behavior, not a bug. If `docapture/mappers/*` is getting
noisy/unexpected word counts, filter these out at the OCR-layer boundary
(in `paddle_engine.py`, before `raw_ocr_json` is written) rather than
pushing the filtering logic into the mapper layer — keeps the OCR/mapper
separation `CLAUDE.md` calls for intact.

## `TypeError: Object of type ndarray is not JSON serializable`

`rec_scores`, `rec_polys`, `rec_boxes` (and the word-box equivalents) come
back as numpy arrays from PaddleOCR internally — `res.save_to_json(...)`
handles this conversion for PaddleOCR's own output file, but if code reads
the in-memory `result` object directly and tries to `json.dumps()` it (e.g.
to write `raw_ocr_json` onto the `Captured Document` doctype) without going
through `save_to_json`, this will fail. Convert numpy arrays to native
Python lists explicitly (`.tolist()`) before serializing.

## Confidence scores look suspiciously low across the board

If `rec_scores` are uniformly low (not just one or two problem lines) on an
otherwise legible document, suspect the input pipeline rather than the
model:
- Check `use_textline_orientation` — if text is actually rotated in the
  source image and this is `False`, recognition quality drops even though
  detection may still find the text regions.
- Check the preprocessing step (`preprocess` in Phase 2 scope) actually ran
  before PaddleOCR saw the image — a skipped or failed preprocessing step
  (bad orientation correction, no deskew) will tank recognition confidence
  even with a good model.
- Note: the known-good confidence range is avg ~0.996–0.998 depending on
  engine (`onnxruntime` vs. the historical `paddle_static` reference — see
  `docs/OCR_MODEL_EVALUATION.md`), measured on a clean,
  born-digital source document. Don't treat a lower score on a genuine
  phone-photo/scanned fixture as automatically a bug — see the validation
  gap noted in `docs/OCR_MODEL_EVALUATION.md`.
