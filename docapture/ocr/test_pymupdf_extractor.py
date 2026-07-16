# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

from pathlib import Path

import frappe
from frappe.tests import UnitTestCase

from docapture.ocr import pymupdf_extractor
from docapture.ocr.schema import TARGET_DPI

FIXTURE = (
	Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/ocr/sales_order_page1/Sales order.pdf"
)


class UnitTestPymupdfExtractor(UnitTestCase):
	def test_born_digital_pdf_extracts_native_lines(self):
		results = pymupdf_extractor.extract_document(FIXTURE.read_bytes())

		self.assertEqual(len(results), 1)
		page = results[0]
		self.assertEqual(page["kind"], "native")
		self.assertGreater(len(page["lines"]), 0)

		all_text = " ".join(line["text"] for line in page["lines"])
		self.assertIn("Sigzen", all_text)
		self.assertEqual(len(page["lines"]), 47)  # matches PaddleOCR's line count on the same fixture

		first_line = page["lines"][0]
		self.assertIsNone(first_line["confidence"])
		self.assertEqual(len(first_line["bbox"]), 4)
		self.assertTrue(all(isinstance(v, int) for v in first_line["bbox"]))
		self.assertGreater(len(first_line["words"]), 0)

		# 200 DPI pixel space, not the PDF's native 72 DPI point space.
		expected_width = round(594.9599609375 * TARGET_DPI / 72)
		self.assertEqual(page["width"], expected_width)

	def test_rasterized_page_has_no_text_layer(self):
		import pymupdf as fitz

		blank = fitz.open()
		blank.new_page(width=200, height=200)
		blank_bytes = blank.tobytes()

		results = pymupdf_extractor.extract_document(blank_bytes)

		self.assertEqual(results[0]["kind"], "raster")
		self.assertEqual(results[0]["image"].shape[2], 3)
