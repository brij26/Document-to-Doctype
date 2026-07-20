# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.file_manager import save_file

from docapture.creators import journal_entry_creator

FIXTURE_DIR = Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/ocr/sales_order_page1"
_COMPANY = "_Test Company"


def _field(value):
	return {"value": value, "confidence": 0.9}


def _unique(prefix):
	# Business-key values (cheque_no/reference_no) must be unique per test
	# invocation — tests here aren't transactionally rolled back
	# (docs/PHASE_STATUS.md), so a literal reference would collide with a
	# leftover "Draft" Docapture Posting from a prior run and make dedup
	# block creation the test expects to succeed.
	return f"{prefix}-{frappe.generate_hash(length=8)}"


def _captured_document(dn, *, source_type, extracted: dict, company=_COMPANY):
	content = (FIXTURE_DIR / "input.jpg").read_bytes() + f"---test-marker:{dn}---".encode()
	file_doc = save_file("input.jpg", content, "Captured Document", dn, is_private=1)
	doc = frappe.get_doc(
		{"doctype": "Captured Document", "file": file_doc.file_url, "source_type": source_type, "company": company}
	).insert()
	doc.db_set({"extracted_json": json.dumps(extracted), "status": "In Review"}, notify=True)
	doc.reload()
	return doc


def _test_supplier(dn):
	group = frappe.db.get_value("Supplier Group", {}, "name")
	return frappe.get_doc(
		{"doctype": "Supplier", "supplier_name": f"Test Creator Supplier {dn}", "supplier_group": group, "supplier_type": "Company"}
	).insert()


class IntegrationTestJournalEntryCreator(IntegrationTestCase):
	def setUp(self):
		frappe.db.set_value("Company", _COMPANY, "default_bank_account", "Cash - _TC")
		self.addCleanup(lambda: frappe.db.set_value("Company", _COMPANY, "default_bank_account", None))

	def test_create_builds_two_row_journal_entry(self):
		doc = _captured_document(
			"test-jec-basic",
			source_type="Supplier Bill",
			extracted={
				"fields": {"posting_date": _field("2026-07-01"), "cheque_no": _field(_unique("UTR")), "cheque_date": _field(None)},
				"rows": [
					{
						"account": _field("Creditors - _TC"),
						"party_type": _field(None),
						"party": _field(None),
						"debit": _field(None),
						"credit": _field("5000"),
						"exchange_rate": _field(None),
					},
					{
						"account": _field("Cash - _TC"),
						"party_type": _field(None),
						"party": _field(None),
						"debit": _field("5000"),
						"credit": _field(None),
						"exchange_rate": _field(None),
					},
				],
			},
		)

		created = journal_entry_creator.create(doc)

		self.assertTrue(created)
		self.assertEqual(doc.target_doctype, "Journal Entry")
		je = frappe.get_doc("Journal Entry", doc.target_docname)
		self.assertEqual(len(je.accounts), 2)
		self.assertEqual(je.accounts[0].credit_in_account_currency, 5000)
		self.assertEqual(je.accounts[1].debit_in_account_currency, 5000)
		self.assertEqual(len(doc.postings), 1)
		self.assertEqual(doc.postings[0].status, "Draft")

	def test_create_throws_when_row_missing_both_debit_and_credit(self):
		doc = _captured_document(
			"test-jec-missing-amount",
			source_type="Supplier Bill",
			extracted={
				"fields": {"posting_date": _field("2026-07-01"), "cheque_no": _field(_unique("UTR")), "cheque_date": _field(None)},
				"rows": [
					{
						"account": _field("Creditors - _TC"),
						"party_type": _field(None),
						"party": _field(None),
						"debit": _field(None),
						"credit": _field("5000"),
						"exchange_rate": _field(None),
					},
					{
						"account": _field("Cash - _TC"),
						"party_type": _field(None),
						"party": _field(None),
						"debit": _field(None),
						"credit": _field(None),
						"exchange_rate": _field(None),
					},
				],
			},
		)
		count_before = frappe.db.count("Journal Entry")

		with self.assertRaises(frappe.ValidationError) as ctx:
			journal_entry_creator.create(doc)

		self.assertIn("Row 2", str(ctx.exception))
		self.assertEqual(frappe.db.count("Journal Entry"), count_before)

	def test_create_uses_capture_alias_resolved_account_over_raw_text(self):
		doc = _captured_document(
			"test-jec-alias-account",
			source_type="Supplier Bill",
			extracted={
				"fields": {"posting_date": _field("2026-07-01"), "cheque_no": _field(_unique("UTR")), "cheque_date": _field(None)},
				"rows": [
					{
						"account": {
							"value": "Creditors A/c (raw OCR text, not a real account)",
							"confidence": 0.6,
							"mapped_doctype": "Account",
							"mapped_docname": "Creditors - _TC",
						},
						"party_type": _field(None),
						"party": _field(None),
						"debit": _field(None),
						"credit": _field("3000"),
						"exchange_rate": _field(None),
					},
					{
						"account": _field("Cash - _TC"),
						"party_type": _field(None),
						"party": _field(None),
						"debit": _field("3000"),
						"credit": _field(None),
						"exchange_rate": _field(None),
					},
				],
			},
		)

		created = journal_entry_creator.create(doc)

		self.assertTrue(created)
		je = frappe.get_doc("Journal Entry", doc.target_docname)
		self.assertEqual(je.accounts[0].account, "Creditors - _TC")

	def test_create_grouped_by_date_throws_clear_error_when_no_bank_account_resolves(self):
		frappe.db.set_value("Company", _COMPANY, "default_bank_account", None)
		doc = _captured_document(
			"test-jec-no-bank-account",
			source_type="Bank Statement",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-08"),
						"deposit": _field("100"),
						"withdrawal": _field(None),
						"reference_no": _field(_unique("REF")),
						"counterparty_name": _field("Someone"),
					},
				],
			},
		)

		with self.assertRaises(frappe.ValidationError) as ctx:
			journal_entry_creator.create_grouped_by_date(doc)

		self.assertIn("bank account", str(ctx.exception).lower())

	def test_create_grouped_by_date_throws_clear_error_when_no_party_account_resolves(self):
		doc = _captured_document(
			"test-jec-no-party-account",
			source_type="Bank Statement",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-09"),
						"deposit": _field(None),
						"withdrawal": _field("300"),
						"reference_no": _field(_unique("REF")),
						"counterparty_name": _field("Someone"),
					},
				],
			},
		)

		with patch("docapture.creators.journal_entry_creator.resolve_party", return_value=(None, "Unidentified Payee")):
			with self.assertRaises(frappe.ValidationError) as ctx:
				journal_entry_creator.create_grouped_by_date(doc)

		self.assertIn("account", str(ctx.exception).lower())

	def test_create_blocked_by_dedup_does_not_create_second_journal_entry(self):
		reference = _unique("UTR")
		extracted = {
			"fields": {"posting_date": _field("2026-07-02"), "cheque_no": _field(reference), "cheque_date": _field(None)},
			"rows": [
				{
					"account": _field("Creditors - _TC"),
					"party_type": _field("Supplier"),
					"party": _field(None),
					"debit": _field(None),
					"credit": _field("2000"),
					"exchange_rate": _field(None),
				},
				{
					"account": _field("Cash - _TC"),
					"party_type": _field(None),
					"party": _field(None),
					"debit": _field("2000"),
					"credit": _field(None),
					"exchange_rate": _field(None),
				},
			],
		}
		first = _captured_document("test-jec-dedup-1", source_type="Supplier Bill", extracted=extracted)
		journal_entry_creator.create(first)
		first.save()  # dedup reads Docapture Posting from the DB, same as router.approve() does
		first_je_count = frappe.db.count("Journal Entry", {"company": _COMPANY, "cheque_no": reference})

		second = _captured_document("test-jec-dedup-2", source_type="Supplier Bill", extracted=extracted)
		created = journal_entry_creator.create(second)

		self.assertFalse(created)
		self.assertEqual(frappe.db.count("Journal Entry", {"company": _COMPANY, "cheque_no": reference}), first_je_count)
		self.assertEqual(second.postings[0].status, "Rejected")

	def test_create_grouped_by_date_batches_same_day_transactions_into_one_je(self):
		doc = _captured_document(
			"test-jec-grouped",
			source_type="Bank Statement",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-05"),
						"deposit": _field("1000"),
						"withdrawal": _field(None),
						"reference_no": _field(_unique("REF")),
						"counterparty_name": _field("Some Payer"),
					},
					{
						"date": _field("2026-07-05"),
						"deposit": _field(None),
						"withdrawal": _field("500"),
						"reference_no": _field(_unique("REF")),
						"counterparty_name": _field("Some Payee"),
					},
					{
						"date": _field("2026-07-06"),
						"deposit": _field("200"),
						"withdrawal": _field(None),
						"reference_no": _field(_unique("REF")),
						"counterparty_name": _field("Another Payer"),
					},
				],
			},
		)

		created = journal_entry_creator.create_grouped_by_date(doc)

		self.assertTrue(created)
		self.assertEqual(len(doc.postings), 2)
		je_5 = frappe.get_doc("Journal Entry", doc.postings[0].target_docname)
		self.assertEqual(len(je_5.accounts), 4)  # 2 transactions x 2 legs
		je_6 = frappe.get_doc("Journal Entry", doc.postings[1].target_docname)
		self.assertEqual(len(je_6.accounts), 2)

	def test_create_grouped_by_date_surfaces_skipped_rows_and_still_posts_good_ones(self):
		doc = _captured_document(
			"test-jec-skip-row",
			source_type="Bank Statement",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-10"),
						"deposit": _field("400"),
						"withdrawal": _field(None),
						"reference_no": _field(_unique("REF")),
						"counterparty_name": _field("Some Payer"),
					},
					{
						"date": _field(None),
						"deposit": _field(None),
						"withdrawal": _field(None),
						"reference_no": _field(_unique("REF")),
						"counterparty_name": _field("Unreadable Row"),
					},
				],
			},
		)
		frappe.clear_messages()

		created = journal_entry_creator.create_grouped_by_date(doc)

		self.assertTrue(created)
		self.assertEqual(len(doc.postings), 1)
		messages = [m["message"] for m in frappe.message_log]
		self.assertTrue(any("Skipped 1 transaction row" in m for m in messages))

	def test_create_grouped_by_date_uses_resolved_party_when_available(self):
		supplier = _test_supplier("resolved")
		doc = _captured_document(
			"test-jec-resolved-party",
			source_type="Bank Statement",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-07"),
						"deposit": _field(None),
						"withdrawal": _field("750"),
						"reference_no": _field(_unique("REF")),
						"counterparty_name": _field(supplier.supplier_name),
						"party_type": _field("Supplier"),
						"party": _field(supplier.name),
					},
				],
			},
		)

		journal_entry_creator.create_grouped_by_date(doc)

		je = frappe.get_doc("Journal Entry", doc.postings[0].target_docname)
		party_rows = [r for r in je.accounts if r.party]
		self.assertEqual(len(party_rows), 1)
		self.assertEqual(party_rows[0].party, supplier.name)
		self.assertEqual(party_rows[0].party_type, "Supplier")
		self.assertEqual(party_rows[0].debit_in_account_currency, 750)
