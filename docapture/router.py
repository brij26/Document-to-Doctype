# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# source_type -> creator registry (docs/ARCHITECTURE.md "Router → Creator").
# Adding a target is a new creator + one registry entry here, not an edit to
# an if/else chain inside any creator (docs/DESIGN_PRINCIPLES.md "O — Open/
# Closed"). Whitelisted approve()/reject() are the review queue's two
# actions (docs/PHASED_DEVELOPMENT.md Phase 4 scope).
import json
import traceback

import frappe
from frappe import _

from docapture import notify, resolve, review
from docapture.creators import journal_entry_creator, payment_entry_creator

# ponytail: pulling one pure string helper (normalize()) from mappers/ into
# router.py bends docs/DESIGN_PRINCIPLES.md's OCR/mappers-vs-creators
# separation slightly — normalize() has no OCR/LLM coupling, so relocating
# it into a new shared module felt like ceremony for one function. Disclosed
# in the phase checkpoint per CLAUDE.md's "bent principle" rule.
from docapture.mappers.alias_resolver import normalize as _normalize_alias_value

_CREATE_BY_SOURCE_TYPE = {
	"Payment Receipt": payment_entry_creator.create,
	"Bank Statement": journal_entry_creator.create_bank_entries,
	"Supplier Bill": journal_entry_creator.create,
	"Expense Voucher": journal_entry_creator.create,
}

_REVIEWER_ROLES = {"System Manager", "Docapture Reviewer"}


@frappe.whitelist()
def approve(captured_document: str):
	_require_reviewer()
	doc = frappe.get_doc("Captured Document", captured_document)
	if doc.status != "In Review":
		frappe.throw(_("Only an 'In Review' capture can be approved."))

	create = _CREATE_BY_SOURCE_TYPE.get(doc.source_type)
	if not create:
		error = f"No creator registered for source_type {doc.source_type}"
		doc.db_set({"status": "Failed", "error_log": error}, notify=True)
		notify.notify_failure(doc.name, error)
		return

	doc.db_set("status", "Approved", notify=True)
	try:
		created_any = create(doc)
	except Exception:
		error = traceback.format_exc()
		doc.db_set({"status": "Failed", "error_log": error}, notify=True)
		notify.notify_failure(doc.name, error)
		return

	doc.status = "Posted" if created_any else "Rejected"
	doc.save(ignore_permissions=True)


@frappe.whitelist()
def preview(captured_document: str) -> dict:
	_require_reviewer()
	doc = frappe.get_doc("Captured Document", captured_document)
	if doc.status != "In Review":
		frappe.throw(_("Only an 'In Review' capture can be previewed."))
	return review.to_preview(frappe.parse_json(doc.extracted_json))


@frappe.whitelist()
def save_corrections(captured_document: str, corrections: str) -> None:
	"""`corrections` is the full current field state the frontend's Preview
	dialog is showing (not a diff) — {"header_fields": {name: value},
	"rows": [{name: value}, ...] | None} — review.apply_corrections() does
	the diffing against what's actually stored. Never touches doc.status."""
	_require_reviewer()
	doc = frappe.get_doc("Captured Document", captured_document)
	if doc.status != "In Review":
		frappe.throw(_("Only an 'In Review' capture can be corrected."))
	extracted = frappe.parse_json(doc.extracted_json)
	updated = review.apply_corrections(extracted, frappe.parse_json(corrections))
	_save_new_aliases(review.new_aliases(extracted, updated), doc.company)
	doc.db_set("extracted_json", json.dumps(updated), notify=True)


def _save_new_aliases(specs: list, company: str | None) -> None:
	"""Upserts a Capture Alias per spec ({"entity_type", "raw_value",
	"mapped_docname"}) so the next document with this same raw text
	auto-resolves. A spec whose mapped_docname isn't an actual record of
	that doctype is skipped — corrections come from the client, so this is
	a trust-boundary check, not just an optimization."""
	for spec in specs:
		if not frappe.db.exists(spec["entity_type"], spec["mapped_docname"]):
			continue
		normalized_value = _normalize_alias_value(spec["raw_value"])
		existing = frappe.db.get_value(
			"Capture Alias", {"entity_type": spec["entity_type"], "normalized_value": normalized_value, "company": company or ""}
		)
		if existing:
			frappe.db.set_value(
				"Capture Alias", existing, {"mapped_doctype": spec["entity_type"], "mapped_docname": spec["mapped_docname"], "source": "User Confirmed"}
			)
		else:
			frappe.get_doc(
				{
					"doctype": "Capture Alias",
					"entity_type": spec["entity_type"],
					"raw_value": spec["raw_value"],
					"normalized_value": normalized_value,
					"mapped_doctype": spec["entity_type"],
					"mapped_docname": spec["mapped_docname"],
					"company": company,
					"source": "User Confirmed",
				}
			).insert()


@frappe.whitelist()
def unknowns(captured_document: str) -> dict:
	"""Read-only Resolve Unknowns precheck (docapture/resolve.py) — Bank
	Statement only, empty dict for every other source_type (their DTOs have
	no variable-length row table to dedup-ask against)."""
	_require_reviewer()
	doc = frappe.get_doc("Captured Document", captured_document)
	if doc.status != "In Review":
		frappe.throw(_("Only an 'In Review' capture can be checked."))
	if doc.source_type != "Bank Statement":
		return {}
	return resolve.unknowns_summary(doc)


@frappe.whitelist()
def save_resolutions(captured_document: str, resolutions: str) -> None:
	"""`resolutions` — Resolve Unknowns dialog answers: {"bank_account",
	"parties": [{"counterparty_name", "category", "party"}], "exchange_rate",
	"row_fixes": [{"row_number", "date"?, "deposit"?, "withdrawal"?}],
	"duplicate_overrides": [row_number, ...]}. Same alias-writing path as
	save_corrections() (_save_new_aliases), so a resolved counterparty/bank
	account auto-resolves on the next document too. Never touches doc.status."""
	_require_reviewer()
	doc = frappe.get_doc("Captured Document", captured_document)
	if doc.status != "In Review":
		frappe.throw(_("Only an 'In Review' capture can be corrected."))
	resolutions = frappe.parse_json(resolutions)
	extracted = frappe.parse_json(doc.extracted_json)

	_save_new_aliases(resolve.alias_specs_from_resolutions(extracted, resolutions), doc.company)

	updated = resolve.apply_resolutions(extracted, resolutions)
	doc.db_set("extracted_json", json.dumps(updated), notify=True)
	if resolutions.get("exchange_rate"):
		doc.db_set("exchange_rate", resolutions["exchange_rate"], notify=True)


@frappe.whitelist()
def reject(captured_document: str, reason: str = ""):
	_require_reviewer()
	doc = frappe.get_doc("Captured Document", captured_document)
	if doc.status != "In Review":
		frappe.throw(_("Only an 'In Review' capture can be rejected."))
	doc.db_set({"status": "Rejected", "error_log": reason}, notify=True)


@frappe.whitelist()
def retry(captured_document: str):
	"""Sends a Failed capture back to the review queue without touching
	extracted_json — every prior correction/Resolve Unknowns answer stays
	exactly as it was, so the reviewer fixes whatever actually caused the
	failure (e.g. a missing default account) and hits Approve again, instead
	of re-uploading and re-paying for OCR/LLM extraction from scratch.
	Safe to retry a Bank Statement specifically because
	journal_entry_creator.create_bank_entries() rolls back to a savepoint on
	any row failure — a Failed capture never has partial Journal Entries
	sitting behind it for this to duplicate."""
	_require_reviewer()
	doc = frappe.get_doc("Captured Document", captured_document)
	if doc.status != "Failed":
		frappe.throw(_("Only a 'Failed' capture can be retried."))
	doc.db_set({"status": "In Review", "error_log": ""}, notify=True)


def _require_reviewer():
	if not _REVIEWER_ROLES & set(frappe.get_roles()):
		frappe.throw(_("Not permitted to review captures."), frappe.PermissionError)
