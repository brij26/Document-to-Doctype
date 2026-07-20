# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# Appends a "Docapture Posting" child row (docapture/docapture/doctype/
# docapture_posting) onto a Captured Document — one row per draft actually
# created (status "Draft") or per business-key collision skipped (status
# "Rejected"). This is the audit trail dedup.py checks against, and what
# lets a single Captured Document link back to many drafts (a date-grouped
# bank statement) instead of only the one target_doctype/target_docname pair
# the doctype already carries for the single-draft case.
from frappe.utils import flt


def append(
	doc,
	*,
	target_doctype: str,
	target_docname: str,
	status: str,
	party: str | None = None,
	amount: float | None = None,
	posting_date: str | None = None,
	reference: str | None = None,
	note: str | None = None,
) -> None:
	doc.append(
		"postings",
		{
			"target_doctype": target_doctype,
			"target_docname": target_docname,
			"status": status,
			# "" not None for party/reference — dedup.find_existing queries
			# with the same "" normalization, and a NULL column in MariaDB
			# never equality-matches a query filter of "" (or of NULL itself,
			# without an explicit IS NULL query Frappe's ORM doesn't build
			# from a plain equality filter dict).
			"party": party or "",
			"amount": flt(amount, 2) if amount is not None else None,
			"posting_date": posting_date,
			"reference": reference or "",
			"note": note,
		},
	)
