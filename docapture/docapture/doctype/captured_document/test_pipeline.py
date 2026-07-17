# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.file_manager import save_file

from docapture.ocr import pipeline

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = ["Company"]

FIXTURE_DIR = Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/ocr/sales_order_page1"
MAPPER_FIXTURE_DIR = Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/mappers"


def _captured_document(dn, filename, content, source_type="Payment Receipt"):
	# Trailing bytes after a JPEG/PDF's real EOF marker are ignored by cv2/pymupdf, so this
	# is a safe way to give each test document a distinct content_hash (dedup is per-content,
	# see captured_document.py) without needing a separate fixture file per test.
	content = content + f"---test-marker:{dn}---".encode()
	file_doc = save_file(filename, content, "Captured Document", dn, is_private=1)
	return frappe.get_doc(
		{
			"doctype": "Captured Document",
			"file": file_doc.file_url,
			"source_type": source_type,
		}
	).insert()


class IntegrationTestPipeline(IntegrationTestCase):
	def test_born_digital_pdf_produces_native_pages(self):
		doc = _captured_document("test-ocr-pdf", "sales-order.pdf", (FIXTURE_DIR / "Sales order.pdf").read_bytes())

		pipeline.run_ocr(doc.name)
		doc.reload()

		self.assertEqual(doc.status, "OCR Done")
		raw = json.loads(doc.raw_ocr_json)
		self.assertEqual(raw["dpi"], 200)
		self.assertEqual(len(raw["pages"]), 1)
		page = raw["pages"][0]
		self.assertEqual(page["engine"], "pymupdf")
		self.assertEqual(page["confidence_source"], "native")
		self.assertGreater(len(page["lines"]), 0)

	def test_scanned_image_produces_ocr_engine_page(self):
		doc = _captured_document("test-ocr-img", "input.jpg", (FIXTURE_DIR / "input.jpg").read_bytes())

		pipeline.run_ocr(doc.name)
		doc.reload()

		self.assertEqual(doc.status, "OCR Done")
		raw = json.loads(doc.raw_ocr_json)
		page = raw["pages"][0]
		self.assertEqual(page["engine"], "paddleocr")
		self.assertEqual(page["word_tokenization"], "paddle_word_box")
		self.assertEqual(page["confidence_source"], "ocr")
		self.assertGreater(len(page["lines"]), 0)
		all_text = " ".join(line["text"] for line in page["lines"])
		self.assertIn("Sigzen", all_text)

	def test_webp_image_produces_ocr_engine_page(self):
		# First .webp fixture in the app (docs/PHASE_3_MAPPER_PLAN.md) —
		# confirms cv2.imdecode handles it end-to-end through the same
		# raster branch as jpg/png, not just that the extension is allowed.
		doc = _captured_document(
			"test-ocr-webp", "receipt.webp", (MAPPER_FIXTURE_DIR / "sample_payment_reciept.webp").read_bytes()
		)

		pipeline.run_ocr(doc.name)
		doc.reload()

		self.assertEqual(doc.status, "OCR Done")
		raw = json.loads(doc.raw_ocr_json)
		page = raw["pages"][0]
		self.assertEqual(page["engine"], "paddleocr")
		self.assertGreater(len(page["lines"]), 0)
		all_text = " ".join(line["text"] for line in page["lines"]).lower()
		self.assertIn("receipt", all_text)

	def test_run_ocr_is_a_noop_when_status_is_no_longer_uploaded(self):
		doc = _captured_document("test-ocr-stale", "input.jpg", (FIXTURE_DIR / "input.jpg").read_bytes())
		doc.status = "Rejected"
		doc.save()

		pipeline.run_ocr(doc.name)
		doc.reload()

		self.assertEqual(doc.status, "Rejected")
		self.assertFalse(doc.raw_ocr_json)

	def test_run_ocr_sets_failed_status_and_error_log_on_exception(self):
		# A genuinely corrupt upload gets rejected by Frappe's own File attach validation
		# before it ever reaches our code (PDF JS-content check, PIL decode for images) —
		# so the failure this guards against is exercised by forcing extraction itself to
		# raise, which is the actual contract run_ocr owns: catch, log, mark Failed.
		doc = _captured_document("test-ocr-corrupt", "input.jpg", (FIXTURE_DIR / "input.jpg").read_bytes())

		with patch.object(pipeline, "extract_captured_document", side_effect=RuntimeError("boom")):
			pipeline.run_ocr(doc.name)
		doc.reload()

		self.assertEqual(doc.status, "Failed")
		self.assertIn("boom", doc.error_log)
