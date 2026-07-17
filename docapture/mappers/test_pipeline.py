# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.file_manager import save_file

from docapture.mappers import llm_client, pipeline

FIXTURE_DIR = Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/ocr/sales_order_page1"

_BANK_STATEMENT_OCR_JSON = json.dumps(
	{
		"pages": [
			{
				"lines": [
					{"text": "withdrawals", "bbox": [0, 0, 100, 20], "confidence": 0.9, "words": []},
					{"text": "deposits", "bbox": [0, 30, 100, 50], "confidence": 0.9, "words": []},
				]
			}
		]
	}
)


class _StubLLM:
	def extract_fields(self, prompt_text, field_specs):
		return {name: {"value": None, "confidence": 0.0} for name, _erpnext_field, _hint in field_specs}

	def extract_rows(self, prompt_text, field_specs):
		return []


def _captured_document(dn, status="OCR Done", raw_ocr_json=_BANK_STATEMENT_OCR_JSON):
	content = (FIXTURE_DIR / "input.jpg").read_bytes() + f"---test-marker:{dn}---".encode()
	file_doc = save_file("input.jpg", content, "Captured Document", dn, is_private=1)
	doc = frappe.get_doc(
		{"doctype": "Captured Document", "file": file_doc.file_url, "source_type": "Bank Statement"}
	).insert()
	doc.db_set({"raw_ocr_json": raw_ocr_json, "status": status}, notify=True)
	doc.reload()
	return doc


class IntegrationTestMapperPipeline(IntegrationTestCase):
	def test_run_mapper_classifies_maps_and_moves_to_in_review(self):
		doc = _captured_document("test-mapper-happy")

		with patch.object(llm_client, "get_parser", return_value=_StubLLM()):
			pipeline.run_mapper(doc.name)
		doc.reload()

		self.assertEqual(doc.status, "In Review")
		extracted = json.loads(doc.extracted_json)
		self.assertEqual(extracted["target_doctype"], "Journal Entry")
		self.assertEqual(doc.confidence, 0.0)  # stub LLM returns a null value/0.0 confidence per field

	def test_run_mapper_is_a_noop_when_status_is_not_ocr_done(self):
		doc = _captured_document("test-mapper-stale", status="Uploaded", raw_ocr_json="")

		pipeline.run_mapper(doc.name)
		doc.reload()

		self.assertEqual(doc.status, "Uploaded")
		self.assertFalse(doc.extracted_json)

	def test_run_mapper_sets_failed_status_and_error_log_on_exception(self):
		doc = _captured_document("test-mapper-corrupt")

		with patch.object(llm_client, "get_parser", side_effect=RuntimeError("boom")):
			pipeline.run_mapper(doc.name)
		doc.reload()

		self.assertEqual(doc.status, "Failed")
		self.assertIn("boom", doc.error_log)
