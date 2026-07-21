# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.file_manager import save_file

from docapture import router
from docapture.mappers import alias_resolver

FIXTURE_DIR = Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/ocr/sales_order_page1"
_COMPANY = "_Test Company"


def _field(value):
	return {"value": value, "confidence": 0.9}


def _supplier_bill_extracted():
	# cheque_no is salted (part of the dedup business key) — tests here
	# aren't transactionally rolled back (docs/PHASE_STATUS.md), so a fixed
	# literal would collide with a leftover "Draft" Docapture Posting from a
	# prior run and make dedup block a creation this test expects to succeed.
	return {
		"fields": {
			"posting_date": _field("2026-07-10"),
			"cheque_no": _field(f"UTR-{frappe.generate_hash(length=8)}"),
			"cheque_date": _field(None),
		},
		"rows": [
			{
				"account": _field("Creditors - _TC"),
				"party_type": _field(None),
				"party": _field(None),
				"debit": _field(None),
				"credit": _field("1000"),
				"exchange_rate": _field(None),
			},
			{
				"account": _field("Cash - _TC"),
				"party_type": _field(None),
				"party": _field(None),
				"debit": _field("1000"),
				"credit": _field(None),
				"exchange_rate": _field(None),
			},
		],
	}


def _payment_receipt_extracted():
	return {
		"fields": {
			"posting_date": _field("2026-07-10"),
			"party_type": _field(None),
			"party_name": _field(None),
			"paid_amount": _field("3000"),
			"mode_of_payment": _field(None),
			"reference_no": _field(f"REF-{frappe.generate_hash(length=8)}"),
			"reference_date": _field(None),
		}
	}


def _captured_document(dn, *, status="In Review", extracted=None, source_type="Supplier Bill"):
	content = (FIXTURE_DIR / "input.jpg").read_bytes() + f"---test-marker:{dn}---".encode()
	file_doc = save_file("input.jpg", content, "Captured Document", dn, is_private=1)
	doc = frappe.get_doc(
		{"doctype": "Captured Document", "file": file_doc.file_url, "source_type": source_type, "company": _COMPANY}
	).insert()
	doc.db_set({"extracted_json": json.dumps(extracted or _supplier_bill_extracted()), "status": status}, notify=True)
	doc.reload()
	return doc


class IntegrationTestRouter(IntegrationTestCase):
	def setUp(self):
		frappe.db.set_value("Company", _COMPANY, "default_bank_account", "Cash - _TC")
		self.addCleanup(lambda: frappe.db.set_value("Company", _COMPANY, "default_bank_account", None))

	def test_approve_creates_draft_and_sets_posted(self):
		doc = _captured_document("test-router-approve")

		router.approve(doc.name)
		doc.reload()

		self.assertEqual(doc.status, "Posted")
		self.assertEqual(doc.target_doctype, "Journal Entry")
		self.assertEqual(len(doc.postings), 1)

	def test_approve_sets_failed_on_creator_exception(self):
		doc = _captured_document("test-router-approve-fails")

		with patch.dict(router._CREATE_BY_SOURCE_TYPE, {"Supplier Bill": lambda d: (_ for _ in ()).throw(RuntimeError("boom"))}):
			router.approve(doc.name)
		doc.reload()

		self.assertEqual(doc.status, "Failed")
		self.assertIn("boom", doc.error_log)

	def test_approve_rejects_when_not_in_review(self):
		doc = _captured_document("test-router-approve-wrong-status", status="Parsed")

		with self.assertRaises(frappe.ValidationError):
			router.approve(doc.name)

	def test_approve_blocked_without_reviewer_role(self):
		doc = _captured_document("test-router-approve-no-role")

		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				router.approve(doc.name)
		finally:
			frappe.set_user("Administrator")

	def test_reject_sets_status_and_reason(self):
		doc = _captured_document("test-router-reject")

		router.reject(doc.name, reason="Blurry scan, re-upload")
		doc.reload()

		self.assertEqual(doc.status, "Rejected")
		self.assertEqual(doc.error_log, "Blurry scan, re-upload")

	def test_retry_resets_failed_to_in_review_and_clears_error_log(self):
		doc = _captured_document("test-router-retry", status="Failed")
		frappe.db.set_value("Captured Document", doc.name, "error_log", "Traceback: boom")

		router.retry(doc.name)
		doc.reload()

		self.assertEqual(doc.status, "In Review")
		self.assertEqual(doc.error_log, "")

	def test_retry_rejects_when_not_failed(self):
		doc = _captured_document("test-router-retry-wrong-status", status="In Review")

		with self.assertRaises(frappe.ValidationError):
			router.retry(doc.name)

	def test_retry_blocked_without_reviewer_role(self):
		doc = _captured_document("test-router-retry-no-role", status="Failed")

		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				router.retry(doc.name)
		finally:
			frappe.set_user("Administrator")

	def test_preview_returns_shaped_fields_for_flat_shape(self):
		doc = _captured_document(
			"test-router-preview-flat", source_type="Payment Receipt", extracted=_payment_receipt_extracted()
		)

		result = router.preview(doc.name)

		self.assertEqual(result["target_doctype"], None)
		self.assertIsNone(result["rows"])
		self.assertIn(
			{"field_name": "paid_amount", "value": "3000", "confidence": 0.9, "mapped_doctype": None, "mapped_docname": None}, result["header_fields"]
		)

	def test_preview_returns_shaped_fields_for_rows_shape(self):
		doc = _captured_document("test-router-preview-rows")

		result = router.preview(doc.name)

		self.assertEqual(result["row_label"], "Row")
		self.assertEqual(len(result["rows"]), 2)

	def test_preview_blocked_without_reviewer_role(self):
		doc = _captured_document("test-router-preview-no-role")

		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				router.preview(doc.name)
		finally:
			frappe.set_user("Administrator")

	def test_preview_rejects_when_not_in_review(self):
		doc = _captured_document("test-router-preview-wrong-status", status="Parsed")

		with self.assertRaises(frappe.ValidationError):
			router.preview(doc.name)

	def test_save_corrections_persists_edited_value_into_extracted_json(self):
		doc = _captured_document(
			"test-router-save-corrections", source_type="Payment Receipt", extracted=_payment_receipt_extracted()
		)

		router.save_corrections(doc.name, json.dumps({"header_fields": {"paid_amount": "9999"}}))
		doc.reload()

		extracted = json.loads(doc.extracted_json)
		self.assertEqual(extracted["fields"]["paid_amount"], {"value": "9999", "confidence": 1.0})

	def test_save_corrections_does_not_change_status(self):
		doc = _captured_document(
			"test-router-save-corrections-status", source_type="Payment Receipt", extracted=_payment_receipt_extracted()
		)

		router.save_corrections(doc.name, json.dumps({"header_fields": {}}))
		doc.reload()

		self.assertEqual(doc.status, "In Review")

	def test_save_corrections_blocked_without_reviewer_role(self):
		doc = _captured_document(
			"test-router-save-corrections-no-role", source_type="Payment Receipt", extracted=_payment_receipt_extracted()
		)

		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				router.save_corrections(doc.name, json.dumps({"header_fields": {}}))
		finally:
			frappe.set_user("Administrator")

	def test_save_corrections_rejects_when_not_in_review(self):
		doc = _captured_document(
			"test-router-save-corrections-wrong-status",
			source_type="Payment Receipt",
			extracted=_payment_receipt_extracted(),
			status="Parsed",
		)

		with self.assertRaises(frappe.ValidationError):
			router.save_corrections(doc.name, json.dumps({"header_fields": {}}))

	def test_save_corrections_deletes_row_by_index(self):
		doc = _captured_document("test-router-save-corrections-delete-row")

		router.save_corrections(doc.name, json.dumps({"deleted_row_indices": [0]}))
		doc.reload()

		extracted = json.loads(doc.extracted_json)
		self.assertEqual(len(extracted["rows"]), 1)
		self.assertEqual(extracted["rows"][0]["account"]["value"], "Cash - _TC")

	def test_deleted_row_excluded_from_approved_journal_entry(self):
		# a bogus row (e.g. a "Balance brought forward" line OCR'd as a
		# transaction) has no debit/credit, which journal_entry_creator
		# rejects outright (Row N: could not determine a Debit or Credit
		# amount) — proves deletion isn't cosmetic, approve() would otherwise
		# fail on this row entirely.
		extracted = _supplier_bill_extracted()
		extracted["rows"].insert(0, {"account": _field("Balance brought forward"), "debit": _field(None), "credit": _field(None)})
		doc = _captured_document("test-router-delete-then-approve", extracted=extracted)

		router.save_corrections(doc.name, json.dumps({"deleted_row_indices": [0]}))
		router.approve(doc.name)
		doc.reload()

		self.assertEqual(doc.status, "Posted")
		je = frappe.get_doc("Journal Entry", doc.target_docname)
		self.assertEqual(len(je.accounts), 2)

	def test_save_corrections_creates_new_capture_alias_for_valid_picked_docname(self):
		raw_text = f"Creditors A/c {frappe.generate_hash(length=6)}"
		extracted = _supplier_bill_extracted()
		extracted["rows"][0]["account"] = {"value": raw_text, "confidence": 0.5, "mapped_doctype": "Account", "mapped_docname": None}
		doc = _captured_document("test-router-new-alias", extracted=extracted)

		router.save_corrections(doc.name, json.dumps({"rows": [{"account": "Creditors - _TC"}, {}]}))

		alias = frappe.db.get_value(
			"Capture Alias",
			{"entity_type": "Account", "normalized_value": alias_resolver.normalize(raw_text), "company": _COMPANY},
			["mapped_docname"],
			as_dict=True,
		)
		self.assertIsNotNone(alias)
		self.assertEqual(alias.mapped_docname, "Creditors - _TC")

	def test_save_corrections_updates_existing_conflicting_alias(self):
		raw_text = f"Creditors A/c {frappe.generate_hash(length=6)}"
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Account",
				"raw_value": raw_text,
				"normalized_value": alias_resolver.normalize(raw_text),
				"mapped_doctype": "Account",
				"mapped_docname": "Cash - _TC",
				"company": _COMPANY,
				"source": "Auto",
			}
		).insert()
		extracted = _supplier_bill_extracted()
		extracted["rows"][0]["account"] = {"value": raw_text, "confidence": 0.5, "mapped_doctype": "Account", "mapped_docname": "Cash - _TC"}
		doc = _captured_document("test-router-update-alias", extracted=extracted)
		count_before = frappe.db.count("Capture Alias", {"entity_type": "Account", "normalized_value": alias_resolver.normalize(raw_text)})

		router.save_corrections(doc.name, json.dumps({"rows": [{"account": "Creditors - _TC"}, {}]}))

		self.assertEqual(
			frappe.db.count("Capture Alias", {"entity_type": "Account", "normalized_value": alias_resolver.normalize(raw_text)}), count_before
		)
		self.assertEqual(
			frappe.db.get_value("Capture Alias", {"entity_type": "Account", "normalized_value": alias_resolver.normalize(raw_text)}, "mapped_docname"),
			"Creditors - _TC",
		)

	def test_save_corrections_skips_alias_creation_for_nonexistent_docname(self):
		raw_text = f"Creditors A/c {frappe.generate_hash(length=6)}"
		extracted = _supplier_bill_extracted()
		extracted["rows"][0]["account"] = {"value": raw_text, "confidence": 0.5, "mapped_doctype": "Account", "mapped_docname": None}
		doc = _captured_document("test-router-skip-invalid-alias", extracted=extracted)

		router.save_corrections(doc.name, json.dumps({"rows": [{"account": "Nonexistent Account XYZ"}, {}]}))

		self.assertFalse(frappe.db.exists("Capture Alias", {"entity_type": "Account", "normalized_value": alias_resolver.normalize(raw_text)}))
		extracted_after = json.loads(frappe.db.get_value("Captured Document", doc.name, "extracted_json"))
		self.assertEqual(extracted_after["rows"][0]["account"]["value"], "Nonexistent Account XYZ")

	def test_alias_created_via_save_corrections_lets_approve_succeed(self):
		raw_text = f"Unmapped Creditors Text {frappe.generate_hash(length=6)}"
		extracted = _supplier_bill_extracted()
		extracted["rows"][0]["account"] = {"value": raw_text, "confidence": 0.5, "mapped_doctype": "Account", "mapped_docname": None}
		doc = _captured_document("test-router-alias-then-approve", extracted=extracted)

		router.save_corrections(doc.name, json.dumps({"rows": [{"account": "Creditors - _TC"}, {}]}))
		router.approve(doc.name)
		doc.reload()

		self.assertEqual(doc.status, "Posted")
		je = frappe.get_doc("Journal Entry", doc.target_docname)
		self.assertEqual(je.accounts[0].account, "Creditors - _TC")
		self.assertTrue(
			frappe.db.exists(
				"Capture Alias",
				{"entity_type": "Account", "normalized_value": alias_resolver.normalize(raw_text), "mapped_docname": "Creditors - _TC"},
			)
		)

	def test_unknowns_returns_empty_for_non_bank_statement_source_type(self):
		doc = _captured_document("test-router-unknowns-not-bank")

		self.assertEqual(router.unknowns(doc.name), {})

	def test_unknowns_dedups_counterparty_for_bank_statement(self):
		extracted = {
			"fields": {"account_no": _field(None), "bank_name": _field(None)},
			"transactions": [
				{"date": _field("2026-07-01"), "deposit": _field("100"), "withdrawal": _field(None), "counterparty_name": _field("TRF 201-54921")},
				{"date": _field("2026-07-02"), "deposit": _field("200"), "withdrawal": _field(None), "counterparty_name": _field("TRF 201-54921")},
			],
		}
		doc = _captured_document("test-router-unknowns-bank", source_type="Bank Statement", extracted=extracted)
		frappe.db.set_value("Company", _COMPANY, "default_bank_account", "Cash - _TC")

		result = router.unknowns(doc.name)

		self.assertEqual(result["counterparties"], [{"counterparty_name": "TRF 201-54921", "row_count": 2}])

	def test_unknowns_blocked_without_reviewer_role(self):
		doc = _captured_document("test-router-unknowns-no-role", source_type="Bank Statement", extracted={"fields": {}, "transactions": []})

		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				router.unknowns(doc.name)
		finally:
			frappe.set_user("Administrator")

	def test_save_resolutions_creates_alias_and_applies_to_extracted_json(self):
		extracted = {
			"fields": {"account_no": _field(None), "bank_name": _field(None)},
			"transactions": [{"date": _field("2026-07-01"), "deposit": _field("100"), "withdrawal": _field(None), "counterparty_name": _field("ABC Traders")}],
		}
		doc = _captured_document("test-router-save-resolutions", source_type="Bank Statement", extracted=extracted)
		supplier_group = frappe.db.get_value("Supplier Group", {}, "name")
		supplier = frappe.get_doc(
			{"doctype": "Supplier", "supplier_name": f"Resolve Test Supplier {frappe.generate_hash(length=6)}", "supplier_group": supplier_group, "supplier_type": "Company"}
		).insert()

		router.save_resolutions(
			doc.name,
			json.dumps({"parties": [{"counterparty_name": "ABC Traders", "category": "Supplier", "party": supplier.name}]}),
		)
		doc.reload()

		extracted_after = json.loads(doc.extracted_json)
		self.assertEqual(extracted_after["transactions"][0]["party"], {"value": supplier.name, "confidence": 1.0})
		self.assertTrue(
			frappe.db.exists(
				"Capture Alias",
				{"entity_type": "Supplier", "normalized_value": alias_resolver.normalize("ABC Traders"), "mapped_docname": supplier.name},
			)
		)

	def test_save_resolutions_sets_exchange_rate_on_document(self):
		doc = _captured_document(
			"test-router-save-resolutions-rate", source_type="Bank Statement", extracted={"fields": {}, "transactions": []}
		)

		router.save_resolutions(doc.name, json.dumps({"exchange_rate": 83.5}))
		doc.reload()

		self.assertEqual(doc.exchange_rate, 83.5)

	def test_save_resolutions_blocked_without_reviewer_role(self):
		doc = _captured_document("test-router-save-resolutions-no-role", source_type="Bank Statement", extracted={"fields": {}, "transactions": []})

		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				router.save_resolutions(doc.name, json.dumps({}))
		finally:
			frappe.set_user("Administrator")

	def test_corrected_amount_flows_into_created_payment_entry(self):
		extracted = _payment_receipt_extracted()
		extracted["fields"]["paid_amount"] = _field(None)  # LLM couldn't read the amount
		doc = _captured_document("test-router-correct-then-approve", source_type="Payment Receipt", extracted=extracted)

		router.save_corrections(doc.name, json.dumps({"header_fields": {"paid_amount": "4200"}}))
		router.approve(doc.name)
		doc.reload()

		self.assertEqual(doc.status, "Posted")
		pe = frappe.get_doc("Payment Entry", doc.target_docname)
		self.assertEqual(pe.paid_amount, 4200)
