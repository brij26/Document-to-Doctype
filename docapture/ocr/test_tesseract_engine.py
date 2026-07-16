# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

from pathlib import Path

import cv2
import frappe
from frappe.tests import UnitTestCase

from docapture.ocr import preprocess, tesseract_engine

FIXTURE = (
	Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/ocr/sales_order_page1/input.jpg"
)


class UnitTestTesseractEngine(UnitTestCase):
	def test_extract_page_on_real_fixture(self):
		image = cv2.imread(str(FIXTURE))
		preprocessed = preprocess.preprocess_page(image)

		result = tesseract_engine.extract_page(preprocessed)

		self.assertEqual(result["engine"], "tesseract")
		self.assertEqual(result["confidence_source"], "ocr")
		self.assertEqual(result["word_tokenization"], "tesseract_word")
		self.assertGreater(len(result["lines"]), 0)

		texts = " ".join(line["text"] for line in result["lines"])
		self.assertIn("Sigzen", texts)

		for line in result["lines"]:
			self.assertEqual(len(line["bbox"]), 4)
			x0, y0, x1, y1 = line["bbox"]
			self.assertLess(x0, x1)
			self.assertLess(y0, y1)
			self.assertGreater(len(line["words"]), 0)
			if line["confidence"] is not None:
				self.assertTrue(0 <= line["confidence"] <= 1)
