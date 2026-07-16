# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

import pytesseract

from docapture.ocr.schema import TARGET_DPI, round_bbox


def _lines_from_data(data: dict) -> list[dict]:
	groups = {}
	order = []
	n = len(data["text"])
	for i in range(n):
		text = data["text"][i].strip()
		if not text:
			continue
		key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
		if key not in groups:
			groups[key] = []
			order.append(key)
		left, top, width, height = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
		conf = int(data["conf"][i])
		groups[key].append(
			{
				"text": text,
				"bbox": round_bbox((left, top, left + width, top + height)),
				"confidence": conf / 100 if conf >= 0 else None,
			}
		)

	lines = []
	for key in order:
		words = groups[key]
		xs0 = [w["bbox"][0] for w in words]
		ys0 = [w["bbox"][1] for w in words]
		xs1 = [w["bbox"][2] for w in words]
		ys1 = [w["bbox"][3] for w in words]
		confidences = [w["confidence"] for w in words if w["confidence"] is not None]
		lines.append(
			{
				"text": " ".join(w["text"] for w in words),
				"bbox": [min(xs0), min(ys0), max(xs1), max(ys1)],
				"confidence": sum(confidences) / len(confidences) if confidences else None,
				"words": [{"text": w["text"], "bbox": w["bbox"]} for w in words],
			}
		)
	return lines


def extract_page(image, dpi=TARGET_DPI):
	data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, config=f"--dpi {dpi}")
	return {
		"engine": "tesseract",
		"confidence_source": "ocr",
		"word_tokenization": "tesseract_word",
		"lines": _lines_from_data(data),
	}
