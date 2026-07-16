# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

import cv2
import numpy as np
import pymupdf

from docapture.ocr.schema import TARGET_DPI, round_bbox

POINTS_PER_INCH = 72


def has_text_layer(page) -> bool:
	return len(page.get_text("words")) > 0


def _native_lines(page, dpi):
	scale = dpi / POINTS_PER_INCH
	groups = {}
	order = []
	for x0, y0, x1, y1, word, block_no, line_no, word_no in page.get_text("words"):
		key = (block_no, line_no)
		if key not in groups:
			groups[key] = []
			order.append(key)
		groups[key].append((word_no, word, x0 * scale, y0 * scale, x1 * scale, y1 * scale))

	lines = []
	for key in order:
		entries = sorted(groups[key])
		words = [{"text": text, "bbox": round_bbox((x0, y0, x1, y1))} for _, text, x0, y0, x1, y1 in entries]
		xs0 = [w["bbox"][0] for w in words]
		ys0 = [w["bbox"][1] for w in words]
		xs1 = [w["bbox"][2] for w in words]
		ys1 = [w["bbox"][3] for w in words]
		lines.append(
			{
				"text": " ".join(w["text"] for w in words),
				"bbox": [min(xs0), min(ys0), max(xs1), max(ys1)],
				"confidence": None,
				"words": words,
			}
		)
	return lines


def rasterize_page(page, dpi=TARGET_DPI):
	pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
	image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
	return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)


def extract_document(file_bytes: bytes, dpi=TARGET_DPI):
	"""PDF bytes -> per-page results. Each is either a ready-to-use native page dict
	(text layer present) or a raster image needing preprocess + an OCREngine."""
	doc = pymupdf.open(stream=file_bytes, filetype="pdf")
	results = []
	for page_number, page in enumerate(doc, start=1):
		if has_text_layer(page):
			results.append(
				{
					"kind": "native",
					"page_number": page_number,
					"width": round(page.rect.width * dpi / POINTS_PER_INCH),
					"height": round(page.rect.height * dpi / POINTS_PER_INCH),
					"lines": _native_lines(page, dpi),
				}
			)
		else:
			image = rasterize_page(page, dpi)
			results.append(
				{
					"kind": "raster",
					"page_number": page_number,
					"image": image,
					"width": image.shape[1],
					"height": image.shape[0],
				}
			)
	return results
