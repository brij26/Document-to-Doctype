# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

import traceback
from pathlib import Path

import cv2
import frappe
import numpy as np
from frappe.utils.file_manager import get_file

from docapture.ocr import paddle_engine, preprocess, pymupdf_extractor, tesseract_engine
from docapture.ocr.schema import TARGET_DPI, make_document, make_page


def enqueue_ocr(doc, method=None):
	frappe.enqueue(
		run_ocr,
		queue="long",
		enqueue_after_commit=True,
		captured_document=doc.name,
	)


def run_ocr(captured_document: str):
	doc = frappe.get_doc("Captured Document", captured_document)
	if doc.status != "Uploaded":
		# Stale/duplicate enqueue, or the document moved on (e.g. Rejected) before this ran.
		return
	try:
		raw_ocr_json = extract_captured_document(doc)
		doc.db_set({"raw_ocr_json": frappe.as_json(raw_ocr_json), "status": "OCR Done"}, notify=True)
	except Exception:
		doc.db_set({"error_log": traceback.format_exc(), "status": "Failed"}, notify=True)


def extract_captured_document(doc) -> dict:
	filename, content = get_file(doc.file)
	if isinstance(content, str):
		content = content.encode("utf-8")

	if Path(filename).suffix.lower() == ".pdf":
		page_results = pymupdf_extractor.extract_document(content)
	else:
		image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
		page_results = [
			{
				"kind": "raster",
				"page_number": 1,
				"image": image,
				"width": image.shape[1],
				"height": image.shape[0],
			}
		]

	pages = [_resolve_page(page_result, doc.source_type) for page_result in page_results]
	return make_document(pages)


def _resolve_page(page_result, source_type):
	if page_result["kind"] == "native":
		return make_page(
			page_result["page_number"],
			page_result["width"],
			page_result["height"],
			engine="pymupdf",
			confidence_source="native",
			word_tokenization="native",
			lines=page_result["lines"],
		)

	try:
		paddle_input = preprocess.preprocess_for_paddle(page_result["image"], source_type=source_type)
		engine_result = paddle_engine.extract_page(paddle_input, TARGET_DPI)
	except Exception:
		frappe.log_error(
			title="docapture: paddle_engine failed, falling back to tesseract",
			message=traceback.format_exc(),
		)
		tesseract_input = preprocess.preprocess_page(page_result["image"], source_type=source_type)
		engine_result = tesseract_engine.extract_page(tesseract_input, TARGET_DPI)

	return make_page(
		page_result["page_number"],
		page_result["width"],
		page_result["height"],
		engine=engine_result["engine"],
		confidence_source=engine_result["confidence_source"],
		word_tokenization=engine_result["word_tokenization"],
		lines=engine_result["lines"],
	)
