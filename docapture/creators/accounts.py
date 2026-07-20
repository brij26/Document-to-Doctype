# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# Shared ERPNext account-resolution helpers for creators/* — wraps ERPNext's
# own party/bank-account defaulting so a creator never invents a GL account.
import frappe
from erpnext.accounts.party import get_party_account
from frappe.utils.nestedset import get_root_of

# A standing placeholder Customer/Supplier for when the counterparty never
# resolved to a real record. Both ERPNext's Journal Entry
# (validate_party) and Payment Entry (set_missing_values) require
# party_type+party together whenever the account/leg is a Receivable/
# Payable one — leaving party blank to fall back to a bare control account
# is not actually postable, discovered via a real .insert() failure while
# building this creator. A reviewer repoints `party` to the real record once
# identified; until then the entry still posts, into an identifiable bucket
# rather than a wrong specific party.
_PLACEHOLDER_PARTY_NAME = {"Customer": "Unidentified Depositor", "Supplier": "Unidentified Payee"}


def resolve_party(party_type: str, party: str | None, company: str) -> tuple[str | None, str]:
	"""Returns (account, resolved_party) — resolved_party is `party` when
	given, else the get-or-create placeholder for `party_type`."""
	resolved_party = party or _placeholder_party(party_type, company)
	try:
		account = get_party_account(party_type, resolved_party, company)
	except frappe.ValidationError:
		account = None
	return account, resolved_party


def _placeholder_party(party_type: str, company: str) -> str:
	name = _PLACEHOLDER_PARTY_NAME[party_type]
	if frappe.db.exists(party_type, name):
		return name
	if party_type == "Customer":
		doc = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_type": "Company",
				"customer_group": get_root_of("Customer Group"),
				"territory": get_root_of("Territory"),
			}
		)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": name,
				"supplier_type": "Company",
				"supplier_group": get_root_of("Supplier Group"),
			}
		)
	doc.insert(ignore_permissions=True)
	return doc.name


def bank_gl_account(company: str, bank_account_docname: str | None) -> str | None:
	"""bank_account_docname: a resolved ERPNext "Bank Account" record name
	(from Capture Alias, entity_type "Bank Account"), or None. Falls back to
	Company.default_bank_account when unresolved."""
	if bank_account_docname:
		account = frappe.db.get_value("Bank Account", bank_account_docname, "account")
		if account:
			return account
	return frappe.get_cached_value("Company", company, "default_bank_account")
