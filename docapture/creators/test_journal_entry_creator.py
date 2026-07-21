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

	def test_create_bank_entries_throws_clear_error_when_no_bank_account_resolves(self):
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
			journal_entry_creator.create_bank_entries(doc)

		self.assertIn("bank account", str(ctx.exception).lower())

	def test_create_bank_entries_throws_clear_error_when_no_party_account_resolves(self):
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
				journal_entry_creator.create_bank_entries(doc)

		self.assertIn("account", str(ctx.exception).lower())

	def test_create_bank_entries_rolls_back_all_rows_when_a_later_row_fails(self):
		# Row 1 is an Internal Transfer (posts via counter_account, never
		# calls resolve_party) so it succeeds and inserts a real Journal
		# Entry; row 2 is a normal withdrawal that goes through resolve_party,
		# patched here to fail — proves a later row's failure rolls back an
		# earlier row's already-inserted JE too (docapture/router.py's
		# retry() depends on this: a Failed capture must have zero partial
		# side effects, or retrying would duplicate row 1).
		doc = _captured_document(
			"test-jec-rollback",
			source_type="Bank Statement",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-14"),
						"deposit": _field(None),
						"withdrawal": _field("500"),
						"reference_no": _field(_unique("REF")),
						"counterparty_name": _field("Internal Sweep"),
						"counter_account": _field("Cash - _TC"),
					},
					{
						"date": _field("2026-07-15"),
						"deposit": _field(None),
						"withdrawal": _field("300"),
						"reference_no": _field(_unique("REF")),
						"counterparty_name": _field("Row Two Payee"),
					},
				],
			},
		)
		count_before = frappe.db.count("Journal Entry", {"company": _COMPANY, "voucher_type": "Bank Entry"})

		with patch("docapture.creators.journal_entry_creator.resolve_party", return_value=(None, "Unidentified Payee")):
			with self.assertRaises(frappe.ValidationError):
				journal_entry_creator.create_bank_entries(doc)

		self.assertEqual(frappe.db.count("Journal Entry", {"company": _COMPANY, "voucher_type": "Bank Entry"}), count_before)

	def test_create_bank_entries_sets_reference_number_and_date(self):
		# ERPNext's own Journal Entry doctype marks Reference Number/Date
		# mandatory whenever voucher_type == "Bank Entry" — a created entry
		# with these blank can't even be submitted.
		reference = _unique("REF")
		doc = _captured_document(
			"test-jec-reference",
			source_type="Bank Statement",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-16"),
						"deposit": _field("450"),
						"withdrawal": _field(None),
						"reference_no": _field(reference),
						"counterparty_name": _field("Some Payer"),
					},
				],
			},
		)

		journal_entry_creator.create_bank_entries(doc)

		je = frappe.get_doc("Journal Entry", doc.postings[0].target_docname)
		self.assertEqual(je.cheque_no, reference)
		self.assertEqual(je.cheque_date, je.posting_date)

	def test_create_bank_entries_falls_back_to_narration_when_reference_no_missing(self):
		doc = _captured_document(
			"test-jec-reference-fallback",
			source_type="Bank Statement",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-17"),
						"deposit": _field("100"),
						"withdrawal": _field(None),
						"reference_no": _field(None),
						"narration": _field(_unique("NARR")),
						"counterparty_name": _field("Some Payer"),
					},
				],
			},
		)

		journal_entry_creator.create_bank_entries(doc)

		je = frappe.get_doc("Journal Entry", doc.postings[0].target_docname)
		self.assertTrue(je.cheque_no)
		self.assertTrue(je.cheque_date)

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

	def test_create_bank_entries_creates_one_je_per_row_not_grouped_by_date(self):
		doc = _captured_document(
			"test-jec-one-per-row",
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

		created = journal_entry_creator.create_bank_entries(doc)

		self.assertTrue(created)
		self.assertEqual(len(doc.postings), 3)  # one JE per row, even though 2 rows share a date
		for posting in doc.postings:
			je = frappe.get_doc("Journal Entry", posting.target_docname)
			self.assertEqual(len(je.accounts), 2)  # bank leg + counterparty leg, nothing batched in

	def test_create_bank_entries_applies_document_exchange_rate_to_foreign_currency_leg(self):
		# ERPNext's own set_exchange_rate() forces exchange_rate back to 1 for
		# any row whose account is already in the company's own currency (INR
		# for _Test Company) — a real rate only ever applies to a genuinely
		# foreign-currency account, and needs multi_currency=1 on the Journal
		# Entry or ERPNext throws outright.
		usd_account = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": f"USD Suspense {frappe.generate_hash(length=6)}",
				"parent_account": frappe.db.get_value("Account", {"company": _COMPANY, "is_group": 1, "root_type": "Asset"}, "name"),
				"company": _COMPANY,
				"account_currency": "USD",
			}
		).insert()
		doc = _captured_document(
			"test-jec-exchange-rate",
			source_type="Bank Statement",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-11"),
						"deposit": _field("100"),
						"withdrawal": _field(None),
						"reference_no": _field(_unique("REF")),
						"counterparty_name": _field("Foreign Payer"),
						"counter_account": _field(usd_account.name),
					},
				],
			},
		)
		doc.db_set("exchange_rate", 83.5, notify=True)
		doc.reload()

		journal_entry_creator.create_bank_entries(doc)

		je = frappe.get_doc("Journal Entry", doc.postings[0].target_docname)
		self.assertEqual(je.accounts[0].exchange_rate, 1)  # bank leg stays in company currency
		self.assertEqual(je.accounts[1].exchange_rate, 83.5)  # foreign-currency counter leg gets the document rate

	def test_create_bank_entries_posts_internal_transfer_row_to_picked_account_with_no_party(self):
		doc = _captured_document(
			"test-jec-internal-transfer",
			source_type="Bank Statement",
			extracted={
				"fields": {"account_no": _field(None), "bank_name": _field(None)},
				"transactions": [
					{
						"date": _field("2026-07-12"),
						"deposit": _field(None),
						"withdrawal": _field("600"),
						"reference_no": _field(_unique("REF")),
						"counterparty_name": _field("TRF 201-54921"),
						"counter_account": _field("Cash - _TC"),
					},
				],
			},
		)

		journal_entry_creator.create_bank_entries(doc)

		je = frappe.get_doc("Journal Entry", doc.postings[0].target_docname)
		counter_leg = je.accounts[1]
		self.assertEqual(counter_leg.account, "Cash - _TC")
		self.assertFalse(counter_leg.party_type)
		self.assertFalse(counter_leg.party)

	def test_create_bank_entries_force_create_skips_dedup(self):
		reference = _unique("REF")
		extracted = {
			"fields": {"account_no": _field(None), "bank_name": _field(None)},
			"transactions": [
				{
					"date": _field("2026-07-13"),
					"deposit": _field("900"),
					"withdrawal": _field(None),
					"reference_no": _field(reference),
					"counterparty_name": _field("Repeat Payer"),
				},
			],
		}
		first = _captured_document("test-jec-force-1", source_type="Bank Statement", extracted=extracted)
		journal_entry_creator.create_bank_entries(first)
		first.save()  # dedup reads Docapture Posting from the DB, same as router.approve() does

		second_extracted = json.loads(json.dumps(extracted))
		second_extracted["transactions"][0]["force_create"] = _field(True)
		second = _captured_document("test-jec-force-2", source_type="Bank Statement", extracted=second_extracted)

		created = journal_entry_creator.create_bank_entries(second)

		self.assertTrue(created)
		self.assertEqual(second.postings[0].status, "Draft")

	def test_create_bank_entries_surfaces_skipped_rows_and_still_posts_good_ones(self):
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

		created = journal_entry_creator.create_bank_entries(doc)

		self.assertTrue(created)
		self.assertEqual(len(doc.postings), 1)
		messages = [m["message"] for m in frappe.message_log]
		self.assertTrue(any("Skipped 1 transaction row" in m for m in messages))

	def test_create_bank_entries_uses_resolved_party_when_available(self):
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

		journal_entry_creator.create_bank_entries(doc)

		je = frappe.get_doc("Journal Entry", doc.postings[0].target_docname)
		party_rows = [r for r in je.accounts if r.party]
		self.assertEqual(len(party_rows), 1)
		self.assertEqual(party_rows[0].party, supplier.name)
		self.assertEqual(party_rows[0].party_type, "Supplier")
		self.assertEqual(party_rows[0].debit_in_account_currency, 750)
