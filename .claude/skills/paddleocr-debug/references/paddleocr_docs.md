# Authoritative PaddleOCR docs and issue trackers

Use these when an error signature isn't covered by the other reference
files, or to confirm version-specific behavior before making a change.

- **Quick start / output field reference** (what each key in the predict()
  result means): https://paddlepaddle.github.io/PaddleOCR/main/en/quick_start.html
- **General OCR pipeline usage** (all constructor parameters, incl.
  `return_word_box`, `use_doc_orientation_classify`, `use_doc_unwarping`,
  `use_textline_orientation`, `device`, `lang`):
  https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html
- **PP-OCRv6 architecture/benchmarks** (for justifying model choice, or
  understanding tiny/small/medium tradeoffs):
  https://www.paddleocr.ai/main/en/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html
- **Release notes** (check here first if an error only appears after a
  version bump): https://github.com/PaddlePaddle/PaddleOCR/releases
- **GitHub Issues** (search the exact error string — most PaddleOCR errors,
  especially install/import errors, are version- and platform-specific and
  already have a reported fix):
  https://github.com/PaddlePaddle/PaddleOCR/issues
- **GitHub Discussions** (for ambiguous "is this expected behavior"
  questions rather than clear-cut bugs):
  https://github.com/PaddlePaddle/PaddleOCR/discussions

When searching issues/discussions, include the exact `paddlepaddle` and
`paddleocr` version numbers in the search — fixes are frequently
version-specific and a fix for a different version pair may not apply.
