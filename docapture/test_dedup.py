# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.file_manager import save_file

from docapture import dedup

FIXTURE_DIR = Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/ocr/sales_order_page1"


def _captured_document_with_posting(dn, *, reference, status="Draft"):
	content = (FIXTURE_DIR / "input.jpg").read_bytes() + f"---test-marker:{dn}---".encode()
	file_doc = save_file("input.jpg", content, "Captured Document", dn, is_private=1)
	doc = frappe.get_doc(
		{"doctype": "Captured Document", "file": file_doc.file_url, "source_type": "Supplier Bill"}
	).insert()
	doc.append(
		"postings",
		{
			# Dynamic Link validation needs a real record; "DocType"/"Journal
			# Entry" (a real DocType record) stands in — the test only cares
			# about the business-key match, not the linked record's content.
			"target_doctype": "DocType",
			"target_docname": "Journal Entry",
			"status": status,
			"party": "Acme Supplies",
			"amount": 5000,
			"posting_date": "2026-07-01",
			"reference": reference,
		},
	)
	doc.save()
	return doc


class IntegrationTestDedup(IntegrationTestCase):
	# reference is salted per test — tests here aren't transactionally rolled
	# back (docs/PHASE_STATUS.md), so a shared business key would collide
	# with a leftover "Draft" row from another test, both within one run and
	# across repeated runs.
	def test_finds_matching_draft_posting(self):
		_captured_document_with_posting("test-dedup-hit", reference="UTR-HIT")

		match = dedup.find_existing(party="Acme Supplies", amount=5000, posting_date="2026-07-01", reference="UTR-HIT")

		self.assertEqual(match["target_doctype"], "DocType")
		self.assertEqual(match["target_docname"], "Journal Entry")

	def test_no_match_on_different_amount(self):
		_captured_document_with_posting("test-dedup-miss", reference="UTR-MISS")

		match = dedup.find_existing(party="Acme Supplies", amount=9999, posting_date="2026-07-01", reference="UTR-MISS")

		self.assertIsNone(match)

	def test_rejected_posting_is_not_a_live_duplicate(self):
		_captured_document_with_posting("test-dedup-rejected", reference="UTR-REJECTED", status="Rejected")

		match = dedup.find_existing(party="Acme Supplies", amount=5000, posting_date="2026-07-01", reference="UTR-REJECTED")

		self.assertIsNone(match)

	def test_missing_amount_or_date_returns_none_without_querying(self):
		self.assertIsNone(dedup.find_existing(party="Acme Supplies", amount=None, posting_date="2026-07-01", reference="UTR123"))
		self.assertIsNone(dedup.find_existing(party="Acme Supplies", amount=5000, posting_date=None, reference="UTR123"))
