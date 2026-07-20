# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from docapture.mappers import alias_resolver, payment_entry_mapper
from docapture.mappers.payment_entry_mapper import FIELDS, build_dto

_OCR_JSON = {"pages": [{"lines": [{"text": "irrelevant to this fake LLM", "bbox": [0, 0, 10, 10], "words": []}]}]}


class _StubLLM:
	def __init__(self, values: dict):
		self._values = values

	def extract_fields(self, prompt_text, field_specs):
		self.last_prompt_text = prompt_text
		self.last_field_specs = field_specs
		return {
			dto_field: self._values.get(dto_field, {"value": None, "confidence": 0.0})
			for dto_field, _erpnext_field, _hint in field_specs
		}


class IntegrationTestPaymentEntryMapper(IntegrationTestCase):
	def test_build_dto_assembles_extracted_fields(self):
		llm = _StubLLM(
			{
				"posting_date": {"value": "2026-07-16", "confidence": 0.95},
				"paid_amount": {"value": "1000", "confidence": 0.9},
			}
		)

		dto = build_dto(_OCR_JSON, llm)

		self.assertEqual(dto.fields["posting_date"].value, "2026-07-16")
		self.assertEqual(dto.fields["paid_amount"].value, "1000")
		self.assertIn("party_type", dto.fields)  # present with null value, low confidence
		self.assertEqual(dto.fields["party_type"].value, None)
		self.assertEqual({f for f, _, _ in FIELDS}, set(dto.fields))

	def test_build_dto_resolves_known_currency_alias(self):
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Currency",
				"raw_value": "Indian Rupee",
				"normalized_value": alias_resolver.normalize("Indian Rupee"),
				"mapped_doctype": "Currency",
				"mapped_docname": "INR",
				"source": "User Confirmed",
			}
		).insert()
		llm = _StubLLM({"currency": {"value": "Indian Rupee", "confidence": 0.5}})

		dto = build_dto(_OCR_JSON, llm)

		self.assertEqual(dto.fields["currency"].confidence, 1.0)
		self.assertEqual(dto.fields["currency"].mapped_doctype, "Currency")
		self.assertEqual(dto.fields["currency"].mapped_docname, "INR")

	def test_build_dto_marks_alias_eligible_field_as_unresolved_on_miss(self):
		llm = _StubLLM({"currency": {"value": "Some Unknown Currency", "confidence": 0.5}})

		dto = build_dto(_OCR_JSON, llm)

		self.assertEqual(dto.fields["currency"].mapped_doctype, "Currency")
		self.assertIsNone(dto.fields["currency"].mapped_docname)

	def test_build_dto_leaves_non_alias_field_unmapped(self):
		llm = _StubLLM({"posting_date": {"value": "2026-07-16", "confidence": 0.95}})

		dto = build_dto(_OCR_JSON, llm)

		self.assertIsNone(dto.fields["posting_date"].mapped_doctype)
		self.assertIsNone(dto.fields["posting_date"].mapped_docname)

	def test_build_dto_calls_llm_with_reconstructed_text(self):
		llm = _StubLLM({})
		ocr_json = {"pages": [{"lines": [{"text": "Sigzen Tech", "bbox": [0, 0, 50, 20], "words": []}]}]}

		payment_entry_mapper.build_dto(ocr_json, llm)

		self.assertEqual(llm.last_prompt_text, "Sigzen Tech")
		self.assertEqual(llm.last_field_specs, FIELDS)
