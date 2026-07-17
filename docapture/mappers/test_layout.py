# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

from pathlib import Path

import frappe
from frappe.tests import UnitTestCase

from docapture.mappers import layout
from docapture.ocr import pymupdf_extractor

FIXTURE = (
	Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/ocr/sales_order_page1/Sales order.pdf"
)


def _line(text, x0, y0, x1, y1):
	return {"text": text, "bbox": [x0, y0, x1, y1], "confidence": None, "words": []}


class UnitTestLayout(UnitTestCase):
	def test_two_column_rows_are_not_interleaved(self):
		# Two rows of a label-left/value-right layout, plus a third row further
		# down. A naive top-to-bottom sort by each line's own y0 would emit
		# "Row1 Label", "Row1 Value", "Row2 Label", "Row2 Value", "Row3 Label",
		# "Row3 Value" only if their y0s happen to already sort that way — this
		# fixture's y0s are deliberately shuffled to catch that bug.
		ocr_json = {
			"pages": [
				{
					"lines": [
						_line("Row1 Value", 300, 12, 400, 30),
						_line("Row1 Label", 10, 10, 100, 28),
						_line("Row3 Label", 10, 110, 100, 128),
						_line("Row2 Value", 300, 62, 400, 80),
						_line("Row2 Label", 10, 60, 100, 78),
						_line("Row3 Value", 300, 112, 400, 130),
					]
				}
			]
		}

		text = layout.reconstruct(ocr_json)

		self.assertEqual(
			text,
			"Row1 Label  Row1 Value\nRow2 Label  Row2 Value\nRow3 Label  Row3 Value",
		)

	def test_joins_multiple_pages_with_blank_line(self):
		page = {"lines": [_line("Only line", 0, 0, 50, 20)]}
		ocr_json = {"pages": [page, page]}

		text = layout.reconstruct(ocr_json)

		self.assertEqual(text, "Only line\n\nOnly line")

	def test_empty_document_reconstructs_to_empty_string(self):
		self.assertEqual(layout.reconstruct({"pages": []}), "")

	def test_reconstruct_pages_returns_one_entry_per_page_unjoined(self):
		page_a = {"lines": [_line("Page A line", 0, 0, 50, 20)]}
		page_b = {"lines": [_line("Page B line", 0, 0, 50, 20)]}
		ocr_json = {"pages": [page_a, page_b]}

		pages = layout.reconstruct_pages(ocr_json)

		self.assertEqual(pages, ["Page A line", "Page B line"])
		self.assertEqual(layout.reconstruct(ocr_json), "\n\n".join(pages))

	def test_reconstruct_pages_of_empty_document_is_empty_list(self):
		self.assertEqual(layout.reconstruct_pages({"pages": []}), [])

	def test_sales_order_fixture_keeps_letterhead_columns_ungarbled(self):
		# Real multi-column fixture (see PHASE_3_MAPPER_PLAN.md "Fixtures"):
		# "Sigzen Tech"/address on the left, "Sales Order"/order number on the
		# right, at the same vertical band. Reconstruction should keep each
		# column's own lines in their own top-to-bottom order, not scatter them.
		page = pymupdf_extractor.extract_document(FIXTURE.read_bytes())[0]
		ocr_json = {"pages": [{"lines": page["lines"]}]}

		text = layout.reconstruct(ocr_json)

		self.assertIn("Sigzen Tech", text)
		self.assertIn("Sales Order", text)
		left_column_order = ["Sigzen Tech", "ahmedabad"]
		positions = [text.find(phrase) for phrase in left_column_order]
		self.assertTrue(all(p != -1 for p in positions))
		self.assertEqual(positions, sorted(positions))
