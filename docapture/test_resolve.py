# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import json
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils.file_manager import save_file

from docapture import resolve

FIXTURE_DIR = Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/ocr/sales_order_page1"
_COMPANY = "_Test Company"


def _field(value, confidence=0.9):
	return {"value": value, "confidence": confidence}


class UnitTestResolve(UnitTestCase):
	def test_alias_specs_from_resolutions_includes_bank_account(self):
		extracted = {"fields": {"account_no": _field("1234567890"), "bank_name": _field("Union Bank")}}

		specs = resolve.alias_specs_from_resolutions(extracted, {"bank_account": "UBI Account - _TC"})

		self.assertEqual(specs, [{"entity_type": "Bank Account", "raw_value": "1234567890", "mapped_docname": "UBI Account - _TC"}])

	def test_alias_specs_from_resolutions_maps_party_category_to_entity_type(self):
		extracted = {"fields": {}}
		resolutions = {
			"parties": [
				{"counterparty_name": "ABC Traders", "category": "Supplier", "party": "ABC Traders - _TC"},
				{"counterparty_name": "TRF 201-54921", "category": "Internal Transfer", "party": "Cash - _TC"},
			]
		}

		specs = resolve.alias_specs_from_resolutions(extracted, resolutions)

		self.assertIn({"entity_type": "Supplier", "raw_value": "ABC Traders", "mapped_docname": "ABC Traders - _TC"}, specs)
		self.assertIn({"entity_type": "Account", "raw_value": "TRF 201-54921", "mapped_docname": "Cash - _TC"}, specs)

	def test_alias_specs_from_resolutions_skips_incomplete_party_answers(self):
		extracted = {"fields": {}}
		resolutions = {"parties": [{"counterparty_name": "Unanswered", "category": "", "party": ""}]}

		self.assertEqual(resolve.alias_specs_from_resolutions(extracted, resolutions), [])

	def test_apply_resolutions_sets_party_type_and_party_on_every_matching_row(self):
		extracted = {
			"fields": {},
			"transactions": [
				{"counterparty_name": _field("ABC Traders")},
				{"counterparty_name": _field("ABC Traders")},
				{"counterparty_name": _field("Someone Else")},
			],
		}
		resolutions = {"parties": [{"counterparty_name": "ABC Traders", "category": "Supplier", "party": "ABC Traders - _TC"}]}

		result = resolve.apply_resolutions(extracted, resolutions)

		self.assertEqual(result["transactions"][0]["party_type"], {"value": "Supplier", "confidence": 1.0})
		self.assertEqual(result["transactions"][0]["party"], {"value": "ABC Traders - _TC", "confidence": 1.0})
		self.assertEqual(result["transactions"][1]["party"], {"value": "ABC Traders - _TC", "confidence": 1.0})
		self.assertNotIn("party", result["transactions"][2])

	def test_apply_resolutions_internal_transfer_sets_counter_account_not_party(self):
		extracted = {"fields": {}, "transactions": [{"counterparty_name": _field("TRF 201-54921")}]}
		resolutions = {"parties": [{"counterparty_name": "TRF 201-54921", "category": "Internal Transfer", "party": "Cash - _TC"}]}

		result = resolve.apply_resolutions(extracted, resolutions)

		self.assertEqual(result["transactions"][0]["counter_account"], {"value": "Cash - _TC", "confidence": 1.0})
		self.assertNotIn("party_type", result["transactions"][0])
		self.assertNotIn("party", result["transactions"][0])

	def test_apply_resolutions_matches_row_by_narration_when_no_counterparty_name(self):
		# Most real "unknown" rows have no counterparty_name at all — a bare
		# bank reference code sits in narration instead — so matching must
		# fall back to narration, not just counterparty_name.
		extracted = {
			"fields": {},
			"transactions": [{"counterparty_name": _field(None), "narration": _field("TRF 201-54921")}],
		}
		resolutions = {"parties": [{"counterparty_name": "TRF 201-54921", "category": "Internal Transfer", "party": "Cash - _TC"}]}

		result = resolve.apply_resolutions(extracted, resolutions)

		self.assertEqual(result["transactions"][0]["counter_account"], {"value": "Cash - _TC", "confidence": 1.0})

	def test_apply_resolutions_other_category_routes_to_account_like_internal_transfer(self):
		extracted = {"fields": {}, "transactions": [{"counterparty_name": _field("ePAY/To:e-DIRECT TAX COLLE/533917763/")}]}
		resolutions = {
			"parties": [{"counterparty_name": "ePAY/To:e-DIRECT TAX COLLE/533917763/", "category": "Other", "party": "Direct Tax Paid - _TC"}]
		}

		result = resolve.apply_resolutions(extracted, resolutions)

		self.assertEqual(result["transactions"][0]["counter_account"], {"value": "Direct Tax Paid - _TC", "confidence": 1.0})
		self.assertNotIn("party_type", result["transactions"][0])

	def test_apply_resolutions_sets_bank_account_mapped_docname(self):
		extracted = {"fields": {"account_no": {"value": "123", "confidence": 0.6, "mapped_doctype": "Bank Account", "mapped_docname": None}}}

		result = resolve.apply_resolutions(extracted, {"bank_account": "UBI Account - _TC"})

		self.assertEqual(result["fields"]["account_no"]["mapped_docname"], "UBI Account - _TC")

	def test_apply_resolutions_row_fix_sets_date(self):
		extracted = {"fields": {}, "transactions": [{"date": _field(None, 0.4)}]}

		result = resolve.apply_resolutions(extracted, {"row_fixes": [{"row_number": 1, "date": "2026-07-01"}]})

		self.assertEqual(result["transactions"][0]["date"], {"value": "2026-07-01", "confidence": 1.0})

	def test_apply_resolutions_row_fix_sets_deposit_and_clears_withdrawal(self):
		extracted = {"fields": {}, "transactions": [{}]}

		result = resolve.apply_resolutions(extracted, {"row_fixes": [{"row_number": 1, "deposit": "500"}]})

		self.assertEqual(result["transactions"][0]["deposit"], {"value": "500", "confidence": 1.0})
		self.assertEqual(result["transactions"][0]["withdrawal"], {"value": None, "confidence": 1.0})

	def test_apply_resolutions_duplicate_override_tags_force_create(self):
		extracted = {"fields": {}, "transactions": [{}, {}]}

		result = resolve.apply_resolutions(extracted, {"duplicate_overrides": [2]})

		self.assertNotIn("force_create", result["transactions"][0])
		self.assertEqual(result["transactions"][1]["force_create"], {"value": True, "confidence": 1.0})

	def test_apply_resolutions_does_not_mutate_input(self):
		extracted = {"fields": {}, "transactions": [{"counterparty_name": _field("ABC Traders")}]}
		resolve.apply_resolutions(extracted, {"parties": [{"counterparty_name": "ABC Traders", "category": "Supplier", "party": "X"}]})

		self.assertNotIn("party", extracted["transactions"][0])


def _captured_document(dn, *, extracted: dict, company=_COMPANY):
	content = (FIXTURE_DIR / "input.jpg").read_bytes() + f"---test-marker:{dn}---".encode()
	file_doc = save_file("input.jpg", content, "Captured Document", dn, is_private=1)
	doc = frappe.get_doc(
		{"doctype": "Captured Document", "file": file_doc.file_url, "source_type": "Bank Statement", "company": company}
	).insert()
	doc.db_set({"extracted_json": json.dumps(extracted), "status": "In Review"}, notify=True)
	doc.reload()
	return doc


class IntegrationTestResolveUnknownsSummary(IntegrationTestCase):
	def setUp(self):
		frappe.db.set_value("Company", _COMPANY, "default_bank_account", "Cash - _TC")
		self.addCleanup(lambda: frappe.db.set_value("Company", _COMPANY, "default_bank_account", None))

	def test_unknowns_summary_dedups_counterparty_across_many_rows(self):
		doc = _captured_document(
			"test-resolve-dedup-counterparty",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-01"),
						"deposit": _field("100"),
						"withdrawal": _field(None),
						"counterparty_name": _field("TRF 201-54921"),
					},
					{
						"date": _field("2026-07-02"),
						"deposit": _field("200"),
						"withdrawal": _field(None),
						"counterparty_name": _field("TRF 201-54921"),
					},
					{
						"date": _field("2026-07-03"),
						"deposit": _field("300"),
						"withdrawal": _field(None),
						"counterparty_name": _field("TRF 201-54921"),
					},
				],
			},
		)

		summary = resolve.unknowns_summary(doc)

		self.assertEqual(summary["counterparties"], [{"counterparty_name": "TRF 201-54921", "row_count": 3}])

	def test_unknowns_summary_skips_already_resolved_counterparty(self):
		doc = _captured_document(
			"test-resolve-already-resolved",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-01"),
						"deposit": _field("100"),
						"withdrawal": _field(None),
						"counterparty_name": _field("ABC Traders"),
						"party_type": _field("Supplier"),
						"party": _field("ABC Traders - _TC"),
					},
				],
			},
		)

		summary = resolve.unknowns_summary(doc)

		self.assertEqual(summary["counterparties"], [])

	def test_unknowns_summary_groups_rows_with_no_counterparty_name_by_narration(self):
		# Real bug: a bare bank reference code ("TRF 201-54921") has no
		# counterparty_name at all, so it must still surface via narration —
		# silently skipping these was the whole point of this fix.
		doc = _captured_document(
			"test-resolve-narration-fallback",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-01"),
						"deposit": _field("100"),
						"withdrawal": _field(None),
						"counterparty_name": _field(None),
						"narration": _field("TRF 201-54921"),
					},
					{
						"date": _field("2026-07-02"),
						"deposit": _field("200"),
						"withdrawal": _field(None),
						"counterparty_name": _field(None),
						"narration": _field("TRF 201-54921"),
					},
					{
						"date": _field("2026-07-03"),
						"deposit": _field(None),
						"withdrawal": _field("50"),
						"counterparty_name": _field(None),
						"narration": _field("ePAY/To:e-DIRECT TAX COLLE/533917763/"),
					},
				],
			},
		)

		summary = resolve.unknowns_summary(doc)

		self.assertIn({"counterparty_name": "TRF 201-54921", "row_count": 2}, summary["counterparties"])
		self.assertIn({"counterparty_name": "ePAY/To:e-DIRECT TAX COLLE/533917763/", "row_count": 1}, summary["counterparties"])

	def test_unknowns_summary_does_not_double_count_unreadable_row_in_counterparties(self):
		doc = _captured_document(
			"test-resolve-unreadable-not-in-parties",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{"date": _field(None), "deposit": _field(None), "withdrawal": _field(None), "narration": _field("illegible row")},
				],
			},
		)

		summary = resolve.unknowns_summary(doc)

		self.assertEqual(summary["counterparties"], [])
		self.assertEqual(len(summary["unreadable_rows"]), 1)

	def test_unknowns_summary_bank_account_resolved_true_when_default_configured(self):
		doc = _captured_document(
			"test-resolve-bank-resolved",
			extracted={"fields": {"account_no": _field(None), "bank_name": _field(None)}, "transactions": []},
		)

		summary = resolve.unknowns_summary(doc)

		self.assertTrue(summary["bank_account_resolved"])

	def test_unknowns_summary_flags_low_confidence_date(self):
		doc = _captured_document(
			"test-resolve-uncertain-date",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{"date": _field("2026-07-01", 0.4), "deposit": _field("100"), "withdrawal": _field(None), "narration": _field("NEFT XYZ")},
				],
			},
		)

		summary = resolve.unknowns_summary(doc)

		self.assertEqual(len(summary["uncertain_dates"]), 1)
		self.assertEqual(summary["uncertain_dates"][0]["guessed_date"], "2026-07-01")

	def test_unknowns_summary_flags_unreadable_row(self):
		doc = _captured_document(
			"test-resolve-unreadable",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [{"date": _field(None), "deposit": _field(None), "withdrawal": _field(None), "narration": _field("???")}],
			},
		)

		summary = resolve.unknowns_summary(doc)

		self.assertEqual(len(summary["unreadable_rows"]), 1)

	def test_unknowns_summary_flags_duplicate_against_existing_posting(self):
		doc = _captured_document(
			"test-resolve-dup-1",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-04"),
						"deposit": _field("400"),
						"withdrawal": _field(None),
						"reference_no": _field("REF-DUP-1"),
						"counterparty_name": _field("Dup Payer"),
					}
				],
			},
		)
		from docapture.creators import journal_entry_creator

		journal_entry_creator.create_bank_entries(doc)
		doc.save()

		second = _captured_document(
			"test-resolve-dup-2",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-04"),
						"deposit": _field("400"),
						"withdrawal": _field(None),
						"reference_no": _field("REF-DUP-1"),
						"counterparty_name": _field("Dup Payer"),
					}
				],
			},
		)

		summary = resolve.unknowns_summary(second)

		self.assertEqual(len(summary["duplicates"]), 1)
		self.assertEqual(summary["duplicates"][0]["existing_target_doctype"], "Journal Entry")
