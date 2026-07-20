# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from docapture.mappers import alias_resolver
from docapture.mappers.journal_entry_mapper import FIELDS, ROW_FIELDS, build_dto

_OCR_JSON = {"pages": [{"lines": [{"text": "irrelevant to this fake LLM", "bbox": [0, 0, 10, 10], "words": []}]}]}


class _StubLLM:
	def __init__(self, field_values: dict, rows: list[dict] | None = None):
		self._field_values = field_values
		self._rows = rows or []

	def extract_fields(self, prompt_text, field_specs):
		return {
			dto_field: self._field_values.get(dto_field, {"value": None, "confidence": 0.0})
			for dto_field, _erpnext_field, _hint in field_specs
		}

	def extract_rows(self, prompt_text, field_specs):
		return [
			{
				dto_field: row.get(dto_field, {"value": None, "confidence": 0.0})
				for dto_field, _erpnext_field, _hint in field_specs
			}
			for row in self._rows
		]


class IntegrationTestJournalEntryMapper(IntegrationTestCase):
	def test_build_dto_extracts_header_fields_and_two_rows(self):
		llm = _StubLLM(
			{"posting_date": {"value": "2026-07-16", "confidence": 0.9}},
			rows=[
				{"account": {"value": "Office Rent", "confidence": 0.8}, "debit": {"value": "5000", "confidence": 0.85}},
				{"account": {"value": "Cash", "confidence": 0.8}, "credit": {"value": "5000", "confidence": 0.85}},
			],
		)

		dto = build_dto(_OCR_JSON, llm)

		self.assertEqual(dto.fields["posting_date"].value, "2026-07-16")
		self.assertEqual(len(dto.rows), 2)
		self.assertEqual(dto.rows[0]["account"].value, "Office Rent")
		self.assertEqual(dto.rows[0]["debit"].value, "5000")
		self.assertEqual(dto.rows[1]["account"].value, "Cash")
		self.assertEqual(dto.rows[1]["credit"].value, "5000")

	def test_build_dto_extracts_more_than_two_rows(self):
		llm = _StubLLM(
			{},
			rows=[
				{"account": {"value": "Office Rent", "confidence": 0.8}},
				{"account": {"value": "TDS Payable", "confidence": 0.8}},
				{"account": {"value": "Cash", "confidence": 0.8}},
			],
		)

		dto = build_dto(_OCR_JSON, llm)

		self.assertEqual(len(dto.rows), 3)
		self.assertEqual(dto.rows[1]["account"].value, "TDS Payable")

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
		llm = _StubLLM({}, rows=[{"account": {"value": "Petty Cash A/c", "confidence": 0.5}}])

		dto = build_dto(_OCR_JSON, llm)

		self.assertEqual(dto.rows[0]["account"].confidence, 1.0)
		self.assertEqual(dto.rows[0]["account"].mapped_doctype, "Account")
		self.assertEqual(dto.rows[0]["account"].mapped_docname, "Account")

	def test_build_dto_marks_row_account_as_unresolved_on_miss(self):
		llm = _StubLLM({}, rows=[{"account": {"value": "Unknown Ledger", "confidence": 0.5}}])

		dto = build_dto(_OCR_JSON, llm)

		self.assertEqual(dto.rows[0]["account"].mapped_doctype, "Account")
		self.assertIsNone(dto.rows[0]["account"].mapped_docname)

	def test_all_header_and_row_fields_accounted_for(self):
		dto = build_dto(_OCR_JSON, _StubLLM({}, rows=[{}]))

		self.assertEqual({f for f, _, _ in FIELDS}, set(dto.fields))
		self.assertEqual({f for f, _, _ in ROW_FIELDS}, set(dto.rows[0]))
