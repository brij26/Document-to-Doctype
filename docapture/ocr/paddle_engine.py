# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

import functools

import cv2

from docapture.ocr.schema import round_bbox, to_native

# Known-good baseline per .claude/skills/paddleocr-debug and docs/OCR_MODEL_EVALUATION.md.
# use_doc_orientation_classify/use_textline_orientation are True at construction (verified
# harmless on the sales-order fixture, and paddle's purpose-trained models likely beat our
# own deskew heuristic). use_doc_unwarping stays False: UVDoc (built for photographed page
# curvature) drops/shifts leading characters on an already-flat scan (e.g. 'Sigzen Tech' ->
# 'Sigzeln Tech') — it's genuinely useful for a real curved phone photo, but there's no
# reliable signal yet for "was this actually photographed" (source_type doesn't guarantee
# it — a Payment Receipt can be scanned, a Bank Statement can be phone-photographed).
# Revisit once there's a real signal (e.g. a "captured by phone" field, or EXIF detection).
_MODEL_KWARGS = {
	"text_detection_model_name": "PP-OCRv6_medium_det",
	"text_recognition_model_name": "PP-OCRv6_medium_rec",
	"engine": "onnxruntime",
	"use_doc_orientation_classify": True,
	"use_doc_unwarping": False,
	"use_textline_orientation": True,
	"return_word_box": True,
}


@functools.lru_cache(maxsize=1)
def _get_ocr():
	# Loaded once per worker process (model load is expensive), not per job.
	from paddleocr import PaddleOCR

	return PaddleOCR(**_MODEL_KWARGS)


def _lines_from_result(data: dict) -> list[dict]:
	"""Map a PaddleOCR OCRResult's `.json["res"]` dict to our line/word schema."""
	data = to_native(data)
	rec_texts = data["rec_texts"]
	rec_scores = data["rec_scores"]
	rec_boxes = data["rec_boxes"]
	text_word = data.get("text_word")
	text_word_boxes = data.get("text_word_boxes")

	lines = []
	for i, text in enumerate(rec_texts):
		words = []
		if text_word is not None:
			for token, bbox in zip(text_word[i], text_word_boxes[i], strict=True):
				if token.strip() == "":
					# Whitespace-only tokens are noise, not words (docs/ARCHITECTURE.md decision:
					# no punctuation-normalizing pass, but whitespace is uniformly dropped).
					continue
				words.append({"text": token, "bbox": round_bbox(bbox)})
		lines.append(
			{
				"text": text,
				"bbox": round_bbox(rec_boxes[i]),
				"confidence": rec_scores[i],
				"words": words,
			}
		)
	return lines


def extract_page(image, dpi):
	if image.ndim == 2:
		# preprocess.py hands back grayscale/binarized 2D arrays; PaddleOCR's internal
		# resize step unconditionally unpacks img.shape as (H, W, C) and raises otherwise.
		image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
	ocr = _get_ocr()
	(result,) = ocr.predict(image)
	return {
		"engine": "paddleocr",
		"confidence_source": "ocr",
		"word_tokenization": "paddle_word_box",
		"lines": _lines_from_result(result.json["res"]),
	}
