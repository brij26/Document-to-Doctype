# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

from frappe.tests import UnitTestCase

from docapture import review


def _field(value, confidence=0.9):
	return {"value": value, "confidence": confidence}


class UnitTestReview(UnitTestCase):
	def test_to_preview_flat_fields_shape(self):
		extracted = {
			"target_doctype": "Payment Entry",
			"fields": {"paid_amount": _field("3000"), "party_name": _field(None, 0.0)},
		}

		preview = review.to_preview(extracted)

		self.assertEqual(preview["target_doctype"], "Payment Entry")
		self.assertEqual(preview["row_label"], None)
		self.assertIsNone(preview["rows"])
		self.assertIn(
			{"field_name": "paid_amount", "value": "3000", "confidence": 0.9, "mapped_doctype": None, "mapped_docname": None}, preview["header_fields"]
		)
		self.assertIn(
			{"field_name": "party_name", "value": None, "confidence": 0.0, "mapped_doctype": None, "mapped_docname": None}, preview["header_fields"]
		)

	def test_to_preview_rows_shape(self):
		extracted = {
			"target_doctype": "Journal Entry",
			"fields": {"posting_date": _field("2026-07-01")},
			"rows": [
				{"account": _field("Creditors - _TC"), "credit": _field("5000")},
				{"account": _field("Cash - _TC"), "debit": _field("5000")},
			],
		}

		preview = review.to_preview(extracted)

		self.assertEqual(preview["row_label"], "Row")
		self.assertEqual(len(preview["rows"]), 2)
		self.assertIn(
			{"field_name": "account", "value": "Creditors - _TC", "confidence": 0.9, "mapped_doctype": None, "mapped_docname": None},
			preview["rows"][0],
		)

	def test_to_preview_transactions_shape(self):
		extracted = {
			"target_doctype": "Journal Entry",
			"fields": {"bank_name": _field("Union Bank")},
			"transactions": [
				{"date": _field("2026-07-05"), "deposit": _field("1000")},
			],
		}

		preview = review.to_preview(extracted)

		self.assertEqual(preview["row_label"], "Transaction")
		self.assertEqual(len(preview["rows"]), 1)
		self.assertIn(
			{"field_name": "deposit", "value": "1000", "confidence": 0.9, "mapped_doctype": None, "mapped_docname": None}, preview["rows"][0]
		)

	def test_apply_corrections_changed_header_field_bumps_confidence_and_drops_alias(self):
		extracted = {
			"fields": {
				"paid_amount": {"value": None, "confidence": 0.0},
				"party_name": {"value": "ACME", "confidence": 0.8, "mapped_docname": "ACME Corp"},
			}
		}

		result = review.apply_corrections(extracted, {"header_fields": {"paid_amount": "5000", "party_name": "ACME"}})

		self.assertEqual(result["fields"]["paid_amount"], {"value": "5000", "confidence": 1.0})
		# party_name's value didn't actually change -> left byte-for-byte alone.
		self.assertEqual(result["fields"]["party_name"], {"value": "ACME", "confidence": 0.8, "mapped_docname": "ACME Corp"})

	def test_apply_corrections_row_correction_hits_only_that_row(self):
		extracted = {
			"fields": {},
			"rows": [
				{"debit": {"value": None, "confidence": 0.0}, "credit": {"value": "5000", "confidence": 0.9}},
				{"debit": {"value": "5000", "confidence": 0.9}, "credit": {"value": None, "confidence": 0.0}},
			],
		}

		result = review.apply_corrections(extracted, {"header_fields": {}, "rows": [{"debit": "0"}, {}]})

		self.assertEqual(result["rows"][0]["debit"], {"value": "0", "confidence": 1.0})
		self.assertEqual(result["rows"][0]["credit"], {"value": "5000", "confidence": 0.9})
		self.assertEqual(result["rows"][1]["debit"], {"value": "5000", "confidence": 0.9})
		self.assertEqual(result["rows"][1]["credit"], {"value": None, "confidence": 0.0})

	def test_apply_corrections_deletes_row_by_index(self):
		extracted = {
			"fields": {},
			"transactions": [
				{"narration": {"value": "Balance brought forward", "confidence": 0.9}},
				{"narration": {"value": "YourJob BiWeekly Payment", "confidence": 0.9}},
				{"narration": {"value": "Randomford's Deli", "confidence": 0.9}},
			],
		}

		result = review.apply_corrections(extracted, {"deleted_row_indices": [0]})

		self.assertEqual(len(result["transactions"]), 2)
		self.assertEqual(result["transactions"][0]["narration"]["value"], "YourJob BiWeekly Payment")
		self.assertEqual(result["transactions"][1]["narration"]["value"], "Randomford's Deli")

	def test_to_preview_passes_through_mapped_doctype_and_docname(self):
		extracted = {
			"fields": {
				"bank_name": {"value": "Union Bank", "confidence": 0.9, "mapped_doctype": "Bank Account", "mapped_docname": None},
				"posting_date": _field("2026-07-01"),
			}
		}

		preview = review.to_preview(extracted)

		self.assertIn(
			{"field_name": "bank_name", "value": "Union Bank", "confidence": 0.9, "mapped_doctype": "Bank Account", "mapped_docname": None},
			preview["header_fields"],
		)
		self.assertIn(
			{"field_name": "posting_date", "value": "2026-07-01", "confidence": 0.9, "mapped_doctype": None, "mapped_docname": None},
			preview["header_fields"],
		)

	def test_apply_corrections_sets_mapped_docname_when_alias_eligible_field_changes(self):
		extracted = {
			"fields": {
				"bank_name": {"value": "Union Bank", "confidence": 0.6, "mapped_doctype": "Bank Account", "mapped_docname": None},
			}
		}

		result = review.apply_corrections(extracted, {"header_fields": {"bank_name": "Union Bank Account - UBI"}})

		self.assertEqual(result["fields"]["bank_name"]["value"], "Union Bank Account - UBI")
		self.assertEqual(result["fields"]["bank_name"]["confidence"], 1.0)
		self.assertEqual(result["fields"]["bank_name"]["mapped_docname"], "Union Bank Account - UBI")

	def test_new_aliases_returns_spec_for_changed_alias_eligible_field(self):
		extracted = {"fields": {"bank_name": {"value": "Union Bank", "confidence": 0.6, "mapped_doctype": "Bank Account", "mapped_docname": None}}}
		updated = review.apply_corrections(extracted, {"header_fields": {"bank_name": "Union Bank Account - UBI"}})

		specs = review.new_aliases(extracted, updated)

		self.assertEqual(specs, [{"entity_type": "Bank Account", "raw_value": "Union Bank", "mapped_docname": "Union Bank Account - UBI"}])

	def test_new_aliases_skips_unchanged_field(self):
		extracted = {"fields": {"bank_name": {"value": "Union Bank", "confidence": 0.6, "mapped_doctype": "Bank Account", "mapped_docname": None}}}
		updated = review.apply_corrections(extracted, {"header_fields": {"bank_name": "Union Bank"}})

		self.assertEqual(review.new_aliases(extracted, updated), [])

	def test_new_aliases_skips_non_alias_field(self):
		extracted = {"fields": {"paid_amount": {"value": None, "confidence": 0.0}}}
		updated = review.apply_corrections(extracted, {"header_fields": {"paid_amount": "5000"}})

		self.assertEqual(review.new_aliases(extracted, updated), [])

	def test_new_aliases_covers_row_fields_too(self):
		extracted = {
			"fields": {},
			"rows": [{"account": {"value": "Creditors A/c", "confidence": 0.5, "mapped_doctype": "Account", "mapped_docname": None}}],
		}
		updated = review.apply_corrections(extracted, {"rows": [{"account": "Creditors - _TC"}]})

		specs = review.new_aliases(extracted, updated)

		self.assertEqual(specs, [{"entity_type": "Account", "raw_value": "Creditors A/c", "mapped_docname": "Creditors - _TC"}])
