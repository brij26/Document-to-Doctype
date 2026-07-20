# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.file_manager import save_file

from docapture.creators import payment_entry_creator

FIXTURE_DIR = Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/ocr/sales_order_page1"
_COMPANY = "_Test Company"


def _field(value):
	return {"value": value, "confidence": 0.9}


def _unique(prefix):
	# Business-key values (reference_no) must be unique per test invocation —
	# tests here aren't transactionally rolled back (docs/PHASE_STATUS.md),
	# so a literal reference would collide with a leftover "Draft" Docapture
	# Posting from a prior run and make dedup block creation the test expects
	# to succeed.
	return f"{prefix}-{frappe.generate_hash(length=8)}"


def _test_customer(dn):
	group = frappe.db.get_value("Customer Group", {}, "name")
	territory = frappe.db.get_value("Territory", {}, "name")
	return frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": f"Test Creator Customer {dn}",
			"customer_group": group,
			"territory": territory,
			"customer_type": "Company",
		}
	).insert()


def _captured_document(dn, *, extracted: dict, company=_COMPANY):
	content = (FIXTURE_DIR / "input.jpg").read_bytes() + f"---test-marker:{dn}---".encode()
	file_doc = save_file("input.jpg", content, "Captured Document", dn, is_private=1)
	doc = frappe.get_doc(
		{"doctype": "Captured Document", "file": file_doc.file_url, "source_type": "Payment Receipt", "company": company}
	).insert()
	doc.db_set({"extracted_json": json.dumps(extracted), "status": "In Review"}, notify=True)
	doc.reload()
	return doc


class IntegrationTestPaymentEntryCreator(IntegrationTestCase):
	def setUp(self):
		frappe.db.set_value("Company", _COMPANY, "default_bank_account", "Cash - _TC")
		self.addCleanup(lambda: frappe.db.set_value("Company", _COMPANY, "default_bank_account", None))

	def test_create_defaults_to_receive_from_customer_when_party_type_unresolved(self):
		doc = _captured_document(
			"test-pec-basic",
			extracted={
				"fields": {
					"posting_date": _field("2026-07-08"),
					"party_type": _field(None),
					"party_name": _field(None),
					"paid_amount": _field("3000"),
					"mode_of_payment": _field(None),
					"reference_no": _field(_unique("REF-PAY")),
					"reference_date": _field(None),
				}
			},
		)

		created = payment_entry_creator.create(doc)

		self.assertTrue(created)
		self.assertEqual(doc.target_doctype, "Payment Entry")
		pe = frappe.get_doc("Payment Entry", doc.target_docname)
		self.assertEqual(pe.payment_type, "Receive")
		self.assertEqual(pe.party_type, "Customer")
		self.assertEqual(pe.paid_to, "Cash - _TC")
		self.assertEqual(pe.paid_from, "Debtors - _TC")
		self.assertEqual(pe.paid_amount, 3000)

	def test_create_throws_clear_error_when_amount_missing(self):
		doc = _captured_document(
			"test-pec-missing-amount",
			extracted={
				"fields": {
					"posting_date": _field("2026-07-08"),
					"party_type": _field(None),
					"party_name": _field(None),
					"paid_amount": _field(None),
					"mode_of_payment": _field(None),
					"reference_no": _field(_unique("REF-PAY")),
					"reference_date": _field(None),
				}
			},
		)
		count_before = frappe.db.count("Payment Entry")

		with self.assertRaises(frappe.ValidationError) as ctx:
			payment_entry_creator.create(doc)

		self.assertIn("Paid Amount", str(ctx.exception))
		self.assertEqual(frappe.db.count("Payment Entry"), count_before)

	def test_create_uses_capture_alias_resolved_party_over_raw_text(self):
		customer = _test_customer("alias-party")
		doc = _captured_document(
			"test-pec-alias-party",
			extracted={
				"fields": {
					"posting_date": _field("2026-07-08"),
					"party_type": _field("Customer"),
					"party_name": {
						"value": "Some Customer Name As Printed",
						"confidence": 0.6,
						"mapped_doctype": "Customer",
						"mapped_docname": customer.name,
					},
					"paid_amount": _field("3000"),
					"mode_of_payment": _field(None),
					"reference_no": _field(_unique("REF-PAY")),
					"reference_date": _field(None),
				}
			},
		)

		created = payment_entry_creator.create(doc)

		self.assertTrue(created)
		pe = frappe.get_doc("Payment Entry", doc.target_docname)
		self.assertEqual(pe.party, customer.name)

	def test_create_throws_clear_error_when_no_bank_account_resolves(self):
		frappe.db.set_value("Company", _COMPANY, "default_bank_account", None)
		doc = _captured_document(
			"test-pec-no-bank-account",
			extracted={
				"fields": {
					"posting_date": _field("2026-07-08"),
					"party_type": _field(None),
					"party_name": _field(None),
					"paid_amount": _field("3000"),
					"mode_of_payment": _field(None),
					"reference_no": _field(_unique("REF-PAY")),
					"reference_date": _field(None),
				}
			},
		)

		with self.assertRaises(frappe.ValidationError) as ctx:
			payment_entry_creator.create(doc)

		self.assertIn("bank account", str(ctx.exception).lower())

	def test_create_throws_clear_error_when_no_party_account_resolves(self):
		doc = _captured_document(
			"test-pec-no-party-account",
			extracted={
				"fields": {
					"posting_date": _field("2026-07-08"),
					"party_type": _field(None),
					"party_name": _field(None),
					"paid_amount": _field("3000"),
					"mode_of_payment": _field(None),
					"reference_no": _field(_unique("REF-PAY")),
					"reference_date": _field(None),
				}
			},
		)

		with patch("docapture.creators.payment_entry_creator.resolve_party", return_value=(None, "Unidentified Depositor")):
			with self.assertRaises(frappe.ValidationError) as ctx:
				payment_entry_creator.create(doc)

		self.assertIn("account", str(ctx.exception).lower())

	def test_create_blocked_by_dedup(self):
		reference = _unique("REF-PAY")
		extracted = {
			"fields": {
				"posting_date": _field("2026-07-09"),
				"party_type": _field(None),
				"party_name": _field(None),
				"paid_amount": _field("1500"),
				"mode_of_payment": _field(None),
				"reference_no": _field(reference),
				"reference_date": _field(None),
			}
		}
		first = _captured_document("test-pec-dedup-1", extracted=extracted)
		payment_entry_creator.create(first)
		first.save()  # dedup reads Docapture Posting from the DB, same as router.approve() does
		count_before = frappe.db.count("Payment Entry", {"reference_no": reference})

		second = _captured_document("test-pec-dedup-2", extracted=extracted)
		created = payment_entry_creator.create(second)

		self.assertFalse(created)
		self.assertEqual(frappe.db.count("Payment Entry", {"reference_no": reference}), count_before)
		self.assertEqual(second.postings[0].status, "Rejected")
