# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# Business-key dedup (party+amount+date+reference), run immediately before
# draft creation (docs/ARCHITECTURE.md "Dedup"). Checked only against
# Docapture Posting's own audit trail (docapture/postings.py) — never
# against the general ledger — so a legitimate second transaction that
# happens to share a business key with something posted through another
# path is never blocked.
import frappe
from frappe.utils import flt


def find_existing(*, party: str | None, amount: float | None, posting_date: str | None, reference: str | None) -> dict | None:
	"""None -> not enough signal to key on (amount/date missing); let it
	through rather than guess. A row already marked "Rejected" is not a live
	duplicate to collide against again — only "Draft" rows count."""
	if amount is None or posting_date is None:
		return None
	return frappe.db.get_value(
		"Docapture Posting",
		{
			"party": party or "",
			"amount": flt(amount, 2),
			"posting_date": posting_date,
			"reference": reference or "",
			"status": "Draft",
		},
		["target_doctype", "target_docname"],
		as_dict=True,
	)
