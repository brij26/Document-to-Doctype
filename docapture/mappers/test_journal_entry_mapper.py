# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from docapture.mappers import alias_resolver
from docapture.mappers.journal_entry_mapper import FIELDS, build_dto

_OCR_JSON = {"pages": [{"lines": [{"text": "irrelevant to this fake LLM", "bbox": [0, 0, 10, 10], "words": []}]}]}


class _StubLLM:
	def __init__(self, values: dict):
		self._values = values

	def extract_fields(self, prompt_text, field_specs):
		return {
			dto_field: self._values.get(dto_field, {"value": None, "confidence": 0.0})
			for dto_field, _erpnext_field, _hint in field_specs
		}


class IntegrationTestJournalEntryMapper(IntegrationTestCase):
	def test_build_dto_splits_row_prefixed_fields_into_two_rows(self):
		llm = _StubLLM(
			{
				"posting_date": {"value": "2026-07-16", "confidence": 0.9},
				"row1_account": {"value": "Office Rent", "confidence": 0.8},
				"row1_debit": {"value": "5000", "confidence": 0.85},
				"row2_account": {"value": "Cash", "confidence": 0.8},
				"row2_credit": {"value": "5000", "confidence": 0.85},
			}
		)

		dto = build_dto(_OCR_JSON, llm)

		self.assertEqual(dto.fields["posting_date"].value, "2026-07-16")
		self.assertNotIn("row1_account", dto.fields)
		self.assertEqual(len(dto.rows), 2)
		self.assertEqual(dto.rows[0]["account"].value, "Office Rent")
		self.assertEqual(dto.rows[0]["debit"].value, "5000")
		self.assertEqual(dto.rows[1]["account"].value, "Cash")
		self.assertEqual(dto.rows[1]["credit"].value, "5000")

	def test_build_dto_resolves_known_account_alias(self):
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Account",
				"raw_value": "Petty Cash A/c",
				"normalized_value": alias_resolver.normalize("Petty Cash A/c"),
				"mapped_doctype": "DocType",
				"mapped_docname": "Account",
				"source": "User Confirmed",
			}
		).insert()
		llm = _StubLLM({"row1_account": {"value": "Petty Cash A/c", "confidence": 0.5}})

		dto = build_dto(_OCR_JSON, llm)

		self.assertEqual(dto.rows[0]["account"].confidence, 1.0)

	def test_all_fields_accounted_for_across_parent_and_rows(self):
		dto = build_dto(_OCR_JSON, _StubLLM({}))

		row_field_names = {f"row{i + 1}_{name}" for i, row in enumerate(dto.rows) for name in row}
		all_names = set(dto.fields) | row_field_names
		self.assertEqual({f for f, _, _ in FIELDS}, all_names)
