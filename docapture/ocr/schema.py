# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# raw_ocr_json contract (see docs/ARCHITECTURE.md):
# {"dpi": 200, "pages": [{"page_number", "width", "height", "engine",
#   "confidence_source", "word_tokenization", "lines": [{"text", "bbox",
#   "confidence", "words": [{"text", "bbox"}]}]}]}
TARGET_DPI = 200


def to_native(value):
	"""Recursively convert numpy scalars/arrays to plain Python types for json.dumps."""
	if hasattr(value, "tolist"):
		return to_native(value.tolist())
	if isinstance(value, dict):
		return {k: to_native(v) for k, v in value.items()}
	if isinstance(value, list | tuple):
		return [to_native(v) for v in value]
	if hasattr(value, "item"):
		return value.item()
	return value


def round_bbox(bbox):
	x0, y0, x1, y1 = bbox
	return [round(x0), round(y0), round(x1), round(y1)]


def make_page(page_number, width, height, engine, confidence_source, word_tokenization, lines):
	return {
		"page_number": page_number,
		"width": round(width),
		"height": round(height),
		"engine": engine,
		"confidence_source": confidence_source,
		"word_tokenization": word_tokenization,
		"lines": lines,
	}


def make_document(pages, dpi=TARGET_DPI):
	return {"dpi": dpi, "pages": pages}
