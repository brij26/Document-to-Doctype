# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import json
from pathlib import Path

import cv2
import frappe
from frappe.tests import UnitTestCase

from docapture.ocr import paddle_engine, preprocess
from docapture.ocr.paddle_engine import _lines_from_result

FIXTURE_DIR = Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/ocr/sales_order_page1"


class UnitTestPaddleEngine(UnitTestCase):
	def test_extract_page_on_preprocess_for_paddle_output(self):
		# The real path: preprocess_for_paddle() keeps color (DPI upscale + phone-photo
		# perspective correction only — paddle's own orientation/unwarping models handle
		# the rest, see paddle_engine.py's model kwargs).
		image = cv2.imread(str(FIXTURE_DIR / "input.jpg"))
		preprocessed = preprocess.preprocess_for_paddle(image, source_type="Payment Receipt")
		self.assertEqual(preprocessed.ndim, 3)

		result = paddle_engine.extract_page(preprocessed, 200)

		self.assertEqual(result["engine"], "paddleocr")
		self.assertGreater(len(result["lines"]), 0)

	def test_extract_page_accepts_grayscale_2d_input(self):
		# Defensive: extract_page() is only ever called with preprocess_for_paddle()'s
		# color output in this pipeline, but PaddleOCR's internal resize step unpacks
		# img.shape as (H, W, C) and raises ValueError on anything 2D — adapt it anyway
		# so a caller that hands it a grayscale array doesn't hit that crash.
		image = cv2.imread(str(FIXTURE_DIR / "input.jpg"))
		gray = preprocess.to_grayscale(image)
		self.assertEqual(gray.ndim, 2)

		result = paddle_engine.extract_page(gray, 200)

		self.assertEqual(result["engine"], "paddleocr")
		self.assertGreater(len(result["lines"]), 0)

	def test_maps_line_level_result_without_word_box(self):
		data = json.loads((FIXTURE_DIR / "default.json").read_text())

		lines = _lines_from_result(data)

		self.assertEqual(len(lines), 47)
		self.assertEqual(lines[0]["text"], "Sigzen Tech")
		self.assertAlmostEqual(lines[0]["confidence"], 0.999957799911499, places=6)
		self.assertEqual(lines[0]["bbox"], [19, 26, 141, 52])
		self.assertEqual(lines[0]["words"], [])

	def test_maps_word_box_result_and_drops_whitespace_tokens(self):
		data = json.loads((FIXTURE_DIR / "word_box.json").read_text())

		lines = _lines_from_result(data)

		first = lines[0]
		self.assertEqual(first["text"], "Sigzen Tech")
		self.assertEqual([w["text"] for w in first["words"]], ["Sigzen", "Tech"])
		for word in first["words"]:
			self.assertEqual(len(word["bbox"]), 4)
			self.assertTrue(all(isinstance(v, int) for v in word["bbox"]))

	def test_bboxes_and_confidence_are_json_serializable(self):
		data = json.loads((FIXTURE_DIR / "word_box.json").read_text())

		lines = _lines_from_result(data)

		json.dumps({"lines": lines})  # raises TypeError if anything is still numpy
