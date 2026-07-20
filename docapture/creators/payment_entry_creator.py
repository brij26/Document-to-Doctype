# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# DTO -> docstatus=0 Payment Entry draft. Payment Receipt path only —
# depends solely on the parsed PaymentEntryDTO JSON (docapture/mappers/
# schema.py), nothing about OCR/extraction (docs/DESIGN_PRINCIPLES.md).
import frappe
from frappe import _

from docapture import dedup, postings
from docapture.creators.accounts import bank_gl_account, resolve_party
from docapture.creators.fields import alias_docname, amount, value


def create(doc) -> bool:
	"""Returns True if a draft was created, False if blocked by dedup (the
	collision is recorded on `doc` either way via postings.append)."""
	dto = frappe.parse_json(doc.extracted_json)
	fields = dto.get("fields") or {}
	company = doc.company

	# Payment Receipt implies money the company received; default to
	# Customer when the LLM couldn't identify a party_type, rather than
	# guessing Supplier.
	party_type = value(fields.get("party_type")) or "Customer"
	party = alias_docname(fields.get("party_name")) or value(fields.get("party_name"))
	paid_amount = amount(fields.get("paid_amount"))
	if paid_amount is None:
		frappe.throw(
			_("Could not determine Paid Amount from this document. Use Preview to review and correct the extracted fields before approving.")
		)
	posting_date = value(fields.get("posting_date"))
	reference = value(fields.get("reference_no"))

	existing = dedup.find_existing(party=party, amount=paid_amount, posting_date=posting_date, reference=reference)
	if existing:
		postings.append(
			doc,
			target_doctype=existing["target_doctype"],
			target_docname=existing["target_docname"],
			status="Rejected",
			party=party,
			amount=paid_amount,
			posting_date=posting_date,
			reference=reference,
			note=f"Duplicate of existing {existing['target_doctype']} {existing['target_docname']}",
		)
		return False

	payment_type = "Receive" if party_type == "Customer" else "Pay"
	bank_account = bank_gl_account(company, None)
	counter_account, resolved_party = resolve_party(party_type, party, company)
	if not bank_account:
		frappe.throw(_("Could not determine a bank account to post against. Set Company {0}'s Default Bank Account.").format(company))
	if not counter_account:
		frappe.throw(
			_("Could not determine a {0} account for {1}. Set Company {2}'s default {0} account.").format(
				party_type, resolved_party, company
			)
		)

	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = payment_type
	pe.company = company
	pe.posting_date = posting_date or frappe.utils.today()
	pe.party_type = party_type
	pe.party = resolved_party
	pe.mode_of_payment = value(fields.get("mode_of_payment"))
	pe.reference_no = reference
	pe.reference_date = value(fields.get("reference_date"))
	pe.paid_amount = paid_amount
	pe.received_amount = paid_amount
	pe.source_exchange_rate = 1
	pe.target_exchange_rate = 1
	if payment_type == "Receive":
		pe.paid_from = counter_account
		pe.paid_to = bank_account
	else:
		pe.paid_from = bank_account
		pe.paid_to = counter_account
	pe.insert()

	doc.target_doctype = "Payment Entry"
	doc.target_docname = pe.name
	postings.append(
		doc,
		target_doctype="Payment Entry",
		target_docname=pe.name,
		status="Draft",
		party=party,
		amount=paid_amount,
		posting_date=posting_date,
		reference=reference,
	)
	return True
