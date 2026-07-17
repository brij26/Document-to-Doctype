# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import json

from frappe.tests import UnitTestCase

from docapture.mappers.schema import BankStatementDTO, FieldValue, JournalEntryDTO, PaymentEntryDTO


class UnitTestSchema(UnitTestCase):
	def test_payment_entry_dto_confidence_and_json(self):
		dto = PaymentEntryDTO(
			fields={
				"posting_date": FieldValue(value="2026-07-16", confidence=0.9),
				"paid_amount": FieldValue(value="1000", confidence=0.7),
			}
		)

		self.assertAlmostEqual(dto.confidence, 0.8)

		data = json.loads(dto.to_json())
		self.assertEqual(data["target_doctype"], "Payment Entry")
		self.assertEqual(data["fields"]["posting_date"], {"value": "2026-07-16", "confidence": 0.9})

	def test_payment_entry_dto_with_no_fields_has_zero_confidence(self):
		self.assertEqual(PaymentEntryDTO().confidence, 0.0)

	def test_journal_entry_dto_confidence_includes_rows(self):
		dto = JournalEntryDTO(
			fields={"posting_date": FieldValue(value="2026-07-16", confidence=1.0)},
			rows=[
				{"account": FieldValue(value="Creditors", confidence=0.5)},
				{"account": FieldValue(value="Cash", confidence=0.5)},
			],
		)

		self.assertAlmostEqual(dto.confidence, (1.0 + 0.5 + 0.5) / 3)

		data = json.loads(dto.to_json())
		self.assertEqual(data["target_doctype"], "Journal Entry")
		self.assertEqual(len(data["rows"]), 2)

	def test_bank_statement_dto_confidence_includes_variable_length_transactions(self):
		dto = BankStatementDTO(
			fields={"account_no": FieldValue(value="312805010077512", confidence=1.0)},
			transactions=[
				{"date": FieldValue(value="2025-12-01", confidence=0.9)},
				{"date": FieldValue(value="2025-12-02", confidence=0.7)},
				{"date": FieldValue(value="2025-12-03", confidence=0.5)},
			],
		)

		self.assertAlmostEqual(dto.confidence, (1.0 + 0.9 + 0.7 + 0.5) / 4)

		data = json.loads(dto.to_json())
		self.assertEqual(data["target_doctype"], "Journal Entry")
		self.assertEqual(len(data["transactions"]), 3)

	def test_bank_statement_dto_with_no_transactions_has_zero_confidence(self):
		self.assertEqual(BankStatementDTO().confidence, 0.0)
