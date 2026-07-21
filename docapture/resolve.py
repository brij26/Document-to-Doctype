# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# Bank Statement "Resolve Unknowns" step (docs/PHASE_STATUS.md Phase 4
# follow-up), shown before the general per-row Preview dialog. A real
# statement can have hundreds of transaction rows sharing only a handful of
# distinct unresolved counterparties/dates/duplicates — this asks once per
# *unique* unknown instead of once per row.
#
# unknowns_summary() reads (frappe.db access, same layer as router.py/
# creators/* — docapture/review.py stays the pure-functions module).
# apply_resolutions()/alias_specs_from_resolutions() are pure, operating on
# the same parsed extracted_json dict shape docapture/review.py uses.
import copy

import frappe

from docapture import dedup
from docapture.creators.accounts import bank_gl_account
from docapture.creators.fields import alias_docname as _alias_docname
from docapture.creators.fields import amount as _amount
from docapture.creators.fields import value as _value

# Capture Alias entity_type a reviewer's party-category answer maps to.
# "Internal Transfer"/"Other" aren't a party at all — they resolve against a
# plain Account instead (docapture/mappers/bank_statement_mapper.py's
# _PARTY_ENTITY_TYPES). Two labels map to the same mechanism because a real
# statement has both self-transfers and non-party postings (bank charges,
# GST/TDS/tax payments) that a reviewer with no accounting background
# shouldn't have to squeeze into a category literally named "transfer".
_ENTITY_TYPE_BY_CATEGORY = {
	"Customer": "Customer",
	"Supplier": "Supplier",
	"Employee": "Employee",
	"Internal Transfer": "Account",
	"Other": "Account",
}
_ACCOUNT_ROUTED_CATEGORIES = {"Internal Transfer", "Other"}


def _row_identifier(row: dict) -> str | None:
	"""What identifies this row to a reviewer when it has no
	counterparty_name at all — most real "unnamed" rows are a bare bank
	reference code (TRF 201-54921, AA5361070) or a tax/fee narration, not
	blank; only genuinely unreadable rows (docapture/resolve.py's
	unreadable_rows bucket) have neither. Used consistently everywhere a row
	needs grouping/matching by "the same unknown thing", so an answer given
	against a narration-keyed identifier applies to every row sharing that
	exact narration too, not just counterparty-named ones."""
	return _value(row.get("counterparty_name")) or _value(row.get("narration")) or _value(row.get("reference_no"))


def unknowns_summary(doc) -> dict:
	"""Read-only precheck over a Bank Statement's extracted_json. Returns
	what still needs a human answer, deduped by unique value where possible:
	one entry per distinct unresolved row identifier (counterparty_name when
	the row has one, else its narration/reference_no — a bare bank code like
	"TRF 201-54921" needs a decision just as much as a named counterparty),
	not per row; one entry per row with a forward-filled/low-confidence
	date; one per unreadable row; one per row that collides with an
	existing draft."""
	extracted = frappe.parse_json(doc.extracted_json)
	fields = extracted.get("fields") or {}
	transactions = extracted.get("transactions") or []

	bank_docname = _alias_docname(fields.get("account_no")) or _alias_docname(fields.get("bank_name"))
	bank_account = bank_gl_account(doc.company, bank_docname) if doc.company else None

	counterparties: dict[str, dict] = {}
	uncertain_dates = []
	unreadable_rows = []
	duplicates = []

	for row_number, row in enumerate(transactions, start=1):
		date_fv = row.get("date") or {}
		row_date = date_fv.get("value")
		if row_date and (date_fv.get("confidence") if date_fv.get("confidence") is not None else 1.0) < 0.5:
			uncertain_dates.append({"row_number": row_number, "narration": _value(row.get("narration")), "guessed_date": row_date})

		row_amount = _amount(row.get("deposit"))
		if row_amount is None:
			row_amount = _amount(row.get("withdrawal"))

		if not row_date or row_amount is None:
			# Asking "who is this" is premature when the row has no date/amount
			# to post at all — it belongs in unreadable_rows only, not also
			# cluttering the party-category section; it'll naturally show up
			# there once a row_fix supplies the missing date/amount.
			unreadable_rows.append({"row_number": row_number, "narration": _value(row.get("narration"))})
			continue

		identifier = _row_identifier(row)
		if identifier and not _value(row.get("party")) and not _value(row.get("counter_account")):
			entry = counterparties.setdefault(identifier, {"counterparty_name": identifier, "row_count": 0})
			entry["row_count"] += 1

		existing = dedup.find_existing(
			party=_value(row.get("party")) or identifier, amount=row_amount, posting_date=row_date, reference=_value(row.get("reference_no"))
		)
		if existing:
			duplicates.append(
				{
					"row_number": row_number,
					"narration": _value(row.get("narration")),
					"amount": row_amount,
					"posting_date": row_date,
					"existing_target_doctype": existing["target_doctype"],
					"existing_target_docname": existing["target_docname"],
				}
			)

	return {
		"bank_account_resolved": bool(bank_account),
		"counterparties": list(counterparties.values()),
		"uncertain_dates": uncertain_dates,
		"unreadable_rows": unreadable_rows,
		"duplicates": duplicates,
	}


def alias_specs_from_resolutions(extracted: dict, resolutions: dict) -> list[dict]:
	"""Pure — turns a reviewer's Resolve Unknowns answers into Capture Alias
	specs ({"entity_type", "raw_value", "mapped_docname"}), same shape
	docapture/review.py::new_aliases() already produces, so router.py's
	existing _save_new_aliases() writer handles both."""
	specs: list[dict] = []

	bank_account = resolutions.get("bank_account")
	if bank_account:
		fields = extracted.get("fields") or {}
		raw = _value(fields.get("account_no")) or _value(fields.get("bank_name"))
		if raw:
			specs.append({"entity_type": "Bank Account", "raw_value": raw, "mapped_docname": bank_account})

	for party in resolutions.get("parties") or []:
		if not party.get("party") or not party.get("category"):
			continue
		entity_type = _ENTITY_TYPE_BY_CATEGORY.get(party["category"])
		if not entity_type:
			continue
		specs.append({"entity_type": entity_type, "raw_value": party["counterparty_name"], "mapped_docname": party["party"]})

	return specs


def apply_resolutions(extracted: dict, resolutions: dict) -> dict:
	"""Pure — writes a reviewer's Resolve Unknowns answers directly into a
	copy of `extracted` (no re-querying Capture Alias — the answer just given
	*is* the resolution). Returns the updated dict; caller persists it."""
	result = copy.deepcopy(extracted)

	bank_account = resolutions.get("bank_account")
	if bank_account:
		for field_name in ("account_no", "bank_name"):
			fv = (result.get("fields") or {}).get(field_name)
			if fv is not None and fv.get("mapped_doctype") == "Bank Account":
				fv["mapped_docname"] = bank_account

	transactions = result.get("transactions") or []

	rows_by_identifier: dict[str, list[dict]] = {}
	for row in transactions:
		identifier = _row_identifier(row)
		if identifier:
			rows_by_identifier.setdefault(identifier, []).append(row)

	for party in resolutions.get("parties") or []:
		if not party.get("party") or not party.get("category"):
			continue
		for row in rows_by_identifier.get(party["counterparty_name"], []):
			if party["category"] in _ACCOUNT_ROUTED_CATEGORIES:
				row["counter_account"] = {"value": party["party"], "confidence": 1.0}
				row.pop("party_type", None)
				row.pop("party", None)
			else:
				row["party_type"] = {"value": party["category"], "confidence": 1.0}
				row["party"] = {"value": party["party"], "confidence": 1.0}
				row.pop("counter_account", None)

	rows_by_number = dict(enumerate(transactions, start=1))
	for fix in resolutions.get("row_fixes") or []:
		row = rows_by_number.get(fix.get("row_number"))
		if row is None:
			continue
		if fix.get("date"):
			row["date"] = {"value": fix["date"], "confidence": 1.0}
		if fix.get("deposit"):
			row["deposit"] = {"value": fix["deposit"], "confidence": 1.0}
			row["withdrawal"] = {"value": None, "confidence": 1.0}
		if fix.get("withdrawal"):
			row["withdrawal"] = {"value": fix["withdrawal"], "confidence": 1.0}
			row["deposit"] = {"value": None, "confidence": 1.0}

	for row_number in resolutions.get("duplicate_overrides") or []:
		row = rows_by_number.get(row_number)
		if row is not None:
			row["force_create"] = {"value": True, "confidence": 1.0}

	return result
