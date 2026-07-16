# OCR Model Evaluation — PP-OCRv6_medium (for `docapture/ocr/paddle_engine`)

Status: candidate selected, pending Phase 2 integration. Not yet wired into
`OCREngine` protocol or `paddle_engine.py`.

## Decision

Adopting **`PP-OCRv6_medium`** (`PP-OCRv6_medium_det` for detection and `PP-OCRv6_medium_rec` for recognition) as the primary engine for `docapture/ocr/paddle_engine`, replacing whatever default/prior version was assumed during planning.

Rationale from manual testing (see Fixtures/Results below):
- Avg recognition confidence 0.9984 across 47 lines on a clean digital source
  document, min score 0.9763 — no low-confidence outliers.
- `return_word_box=True` produces genuine word-level bounding boxes
  (`text_word`, `text_word_boxes`), which is what our `word_boxes` schema
  field in `Captured Document` was designed to accommodate for later
  confidence scoring (see `ARCHITECTURE.md` / Phase 1 schema notes).
- Per PaddleOCR's own release notes, `PP-OCRv6_medium` reports +5.1%
  recognition / +4.6% detection Hmean over `PP-OCRv5_server` on their
  internal multi-scenario benchmark, at 34.5M params — relevant if we care
  about CPU-only bench-server inference cost.

## ⚠️ Open validation gap — flag before locking this in at Phase 2

The test fixture used (`Sales_order_page-0001.jpg`) is a **clean, born-digital
sales order** — sharp text, no skew, no lighting variance, no perspective
distortion. `PHASED_DEVELOPMENT.md` Phase 2 explicitly calls out that
`Expense Voucher`/`Payment Receipt` sources are commonly **phone photos**,
not flatbed scans, with keystone/perspective distortion and low effective
DPI — failure modes a clean digital PDF doesn't exercise at all.

**Do not treat this result as proof the model handles the hard case.**
Before sign-off on Phase 2's OCR layer, re-run the same model + same
`return_word_box=True` config against:
- a genuinely skewed/rotated phone photo of a receipt
- a low-DPI (<150-200 dpi effective) scan
- a document with visible perspective distortion (angled shot)

and confirm confidence scores and word-box output hold up before assuming
`PP-OCRv6_medium` is the final answer for the fallback-heavy real-world path.

## Code used

Environment: pinned install:

```python
!pip install paddlepaddle==3.2.0
!pip install paddleocr==3.7.0

from paddleocr import PaddleOCR

ocr = PaddleOCR(
    text_detection_model_name="PP-OCRv6_medium_det",
    text_recognition_model_name="PP-OCRv6_medium_rec",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    return_word_box=True
)

result = ocr.predict("/content/Sales order_page-0001.jpg")

for res in result:
    res.print()
    res.save_to_img("output")
    res.save_to_json("output")
```

Note: The detection and recognition models are selected explicitly using
`text_detection_model_name` and `text_recognition_model_name` instead of
relying on PaddleOCR's default model selection.

## Input

- File: `Sales order_page-0001.jpg` — single-page sales order, born-digital
  rendering (not scanned/photographed).

## Output shape (confirmed from actual JSON, 2 runs)

**Run 1 — default (`return_word_box=False`):**

Top-level keys: `input_path`, `page_index`, `model_settings`, `dt_polys`,
`text_det_params`, `text_type`, `textline_orientation_angles`,
`text_rec_score_thresh`, `return_word_box`, `rec_texts`, `rec_scores`,
`rec_polys`, `rec_boxes`.

- `rec_texts[i]` / `rec_scores[i]` / `rec_polys[i]` / `rec_boxes[i]` are all
  **line-level**, index-aligned, 47 entries for this fixture.
- Avg `rec_scores`: 0.9984, min: 0.9763.
- No word-level data present in this mode — line-level box only.

**Run 2 — `return_word_box=True`:**

Adds two new top-level keys: `text_word_boxes`, `text_word`. Same 47-line
length, each entry now a **list of tokens per line**, e.g.:

```json
rec_text: "Sigzen Tech"
text_word:       ["Sigzen", " ", "Tech"]
text_word_boxes: [[32,26,83,54], [92,26,97,54], [102,26,139,54]]
```

Notes for the mapper layer (`docapture/mappers/*`) integration:
- Whitespace (`" "`) is tokenized as its own entry — filter before use.
- Punctuation (`"`, `(`, `)`, `.`, `:`, `&`) is tokenized separately from
  adjacent words — decide whether to fold into neighboring word or drop.
- **No word-level confidence score exists** — `rec_scores` remains
  line-level only even with `return_word_box=True`. If per-field confidence
  scoring assumed word-level scores, that assumption needs revisiting: either
  approximate by assigning the parent line's score to each word, or find a
  different confidence signal.

## Docs to hand to Claude Code for debugging

- PaddleOCR quick start / output field reference:
  https://paddlepaddle.github.io/PaddleOCR/main/en/quick_start.html
- General OCR pipeline usage (parameters incl. `return_word_box`,
  `use_doc_orientation_classify`, `use_doc_unwarping`,
  `use_textline_orientation`):
  https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html
- PP-OCRv6 architecture/benchmarks (for justifying model choice in review):
  https://www.paddleocr.ai/main/en/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html
- PP-OCRv6 release notes (v3.7.0, June 2026):
  https://github.com/PaddlePaddle/PaddleOCR/releases

## Next steps for Phase 2 integration

1. Paste real inference code above (see TODO).
2. Validate against phone-photo / low-DPI / perspective-distorted fixtures
   per the flag above — don't skip this before sign-off.
3. Decide word/punctuation filtering rule for `text_word` before it feeds
   `docapture/mappers`.
4. Decide how (or whether) to approximate word-level confidence given only
   line-level `rec_scores` exist.
5. Wire into `OCREngine` protocol: confirm `paddle_engine.py`'s return
   contract matches what `raw_ocr_json` expects per `ARCHITECTURE.md`.
