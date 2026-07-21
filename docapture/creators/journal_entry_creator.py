# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# DTO -> docstatus=0 Journal Entry draft(s). Depends only on the parsed DTO
# JSON (docapture/mappers/schema.py's JournalEntryDTO/BankStatementDTO
# to_json() shape) — nothing about OCR/extraction (docs/DESIGN_PRINCIPLES.md
# "D — Dependency Inversion").
import frappe
from frappe import _
from frappe.utils import flt

from docapture import dedup, postings
from docapture.creators.accounts import bank_gl_account, resolve_party
from docapture.creators.fields import alias_docname as _alias_docname
from docapture.creators.fields import amount as _amount
from docapture.creators.fields import value as _value


def create(doc) -> bool:
	"""Single Journal Entry per document — Supplier Bill / Expense Voucher
	path. Returns True if a draft was created, False if blocked by dedup
	(the collision is recorded on `doc` either way via postings.append)."""
	dto = frappe.parse_json(doc.extracted_json)
	rows = dto.get("rows") or []
	party, amount = _business_key(rows)
	posting_date = _value(dto["fields"].get("posting_date"))
	reference = _value(dto["fields"].get("cheque_no"))

	existing = dedup.find_existing(party=party, amount=amount, posting_date=posting_date, reference=reference)
	if existing:
		postings.append(
			doc,
			target_doctype=existing["target_doctype"],
			target_docname=existing["target_docname"],
			status="Rejected",
			party=party,
			amount=amount,
			posting_date=posting_date,
			reference=reference,
			note=f"Duplicate of existing {existing['target_doctype']} {existing['target_docname']}",
		)
		return False

	je = frappe.new_doc("Journal Entry")
	je.company = doc.company
	je.voucher_type = "Journal Entry"
	je.posting_date = posting_date or frappe.utils.today()
	je.cheque_no = reference
	# ERPNext's create_remarks() requires cheque_date whenever cheque_no is
	# set (discovered via a real .insert() failure) — default to the
	# posting date when the LLM didn't extract a separate reference date.
	je.cheque_date = _value(dto["fields"].get("cheque_date")) or (je.posting_date if reference else None)
	exchange_rate = flt(doc.get("exchange_rate")) or 1
	# ERPNext's own set_exchange_rate() forces exchange_rate back to 1 for any
	# row whose account is already in the company's own currency (correct —
	# a same-currency row can't have a real rate) and throws outright if a
	# foreign-currency row appears without this flag, discovered via a real
	# .insert() failure while adding this.
	if exchange_rate != 1:
		je.multi_currency = 1
	for row_number, row in enumerate(rows, start=1):
		_append_mapped_row(je, row, row_number, exchange_rate)
	je.insert()

	doc.target_doctype = "Journal Entry"
	doc.target_docname = je.name
	postings.append(
		doc,
		target_doctype="Journal Entry",
		target_docname=je.name,
		status="Draft",
		party=party,
		amount=amount,
		posting_date=posting_date,
		reference=reference,
	)
	return True


def create_bank_entries(doc) -> bool:
	"""Bank Statement path — one Journal Entry per transaction row (one Bank
	+ counterparty leg pair each), per explicit user direction superseding
	the earlier date-grouped design (docs/PHASE_STATUS.md). Dedup is checked
	per row; a row the reviewer force-created over a flagged duplicate in the
	Resolve Unknowns dialog (docapture/resolve.py's duplicate_overrides,
	row["force_create"]) skips the check instead of being auto-rejected.
	Returns True if at least one draft was created.

	The whole per-row loop runs inside one savepoint: if row N throws (e.g.
	no default Supplier account configured), rows 1..N-1 already had real
	Journal Entries inserted, but router.approve()'s failure path only
	db_sets status/error_log — it never persists this call's in-memory
	Docapture Posting appends, so without this rollback those earlier JEs
	would be real, un-audited postings a later retry (docapture/router.py's
	retry()) would then duplicate, since dedup only checks the (unsaved,
	lost) audit trail. Rolling back on any failure keeps this call
	all-or-nothing — a Failed capture always has zero side effects to clean
	up before it's safe to just retry from scratch."""
	dto = frappe.parse_json(doc.extracted_json)
	company = doc.company
	bank_docname = _alias_docname(dto["fields"].get("account_no")) or _alias_docname(dto["fields"].get("bank_name"))
	bank_account = bank_gl_account(company, bank_docname)
	if not bank_account:
		frappe.throw(
			_("Could not determine a bank account to post against. Set Company {0}'s Default Bank Account, or map this statement's bank via Capture Alias.").format(
				company
			)
		)

	exchange_rate = flt(doc.get("exchange_rate")) or 1
	skipped_rows: list[int] = []
	created_any = False
	save_point = frappe.generate_hash(length=10)
	frappe.db.savepoint(save_point)
	try:
		for row_number, row in enumerate(dto.get("transactions") or [], start=1):
			date = _value(row.get("date"))
			_is_deposit, amount = _txn_direction_amount(row)
			reference = _value(row.get("reference_no"))
			party = _value(row.get("party")) or _value(row.get("counterparty_name"))
			if not date or amount is None:
				# ponytail: a row missing a parseable date/amount can't be keyed,
				# so it's skipped rather than guessed at — surfaced to the
				# reviewer via a msgprint below (and, before this point, via
				# Resolve Unknowns' "unreadable rows" section), not silent.
				skipped_rows.append(row_number)
				continue

			force_create = bool(_value(row.get("force_create")))
			existing = None if force_create else dedup.find_existing(party=party, amount=amount, posting_date=date, reference=reference)
			if existing:
				postings.append(
					doc,
					target_doctype=existing["target_doctype"],
					target_docname=existing["target_docname"],
					status="Rejected",
					party=party,
					amount=amount,
					posting_date=date,
					reference=reference,
					note=f"Duplicate of existing {existing['target_doctype']} {existing['target_docname']}",
				)
				continue

			je = frappe.new_doc("Journal Entry")
			je.company = company
			je.voucher_type = "Bank Entry"
			je.posting_date = date
			# ERPNext's own Journal Entry doctype marks cheque_no/cheque_date
			# ("Reference Number"/"Reference Date" on the form) mandatory
			# whenever voucher_type == "Bank Entry" — reference_no is already
			# extracted per row, just falls back to narration/a synthesized
			# value on the rare row that has neither, since the field can't
			# be left blank regardless.
			je.cheque_no = reference or _value(row.get("narration")) or f"BANK-{date}"
			je.cheque_date = date
			if exchange_rate != 1:
				je.multi_currency = 1
			_append_bank_transaction_legs(je, row, company, bank_account, exchange_rate)
			je.insert()
			created_any = True
			postings.append(
				doc,
				target_doctype="Journal Entry",
				target_docname=je.name,
				status="Draft",
				party=party,
				amount=amount,
				posting_date=date,
				reference=reference,
			)
	except Exception:
		frappe.db.rollback(save_point=save_point)
		raise

	if skipped_rows:
		frappe.msgprint(
			_("Skipped {0} transaction row(s) with no parseable date/amount: row {1}. Use Resolve Unknowns or Preview to review and correct these before approving.").format(
				len(skipped_rows), ", ".join(str(n) for n in skipped_rows)
			),
			indicator="orange",
			alert=True,
		)
	return created_any


def _append_mapped_row(je, row: dict, row_number: int, exchange_rate: float = 1) -> None:
	debit = _amount(row.get("debit"))
	credit = _amount(row.get("credit"))
	if debit is None and credit is None:
		frappe.throw(
			_("Row {0}: could not determine a Debit or Credit amount from this document. Use Preview to review and correct the extracted fields before approving.").format(
				row_number
			)
		)
	account = _alias_docname(row.get("account")) or _value(row.get("account"))
	party_type = _value(row.get("party_type")) or None
	party = _value(row.get("party")) or None
	# ERPNext's own validate_party() requires party_type+party together
	# whenever the row's account is a Receivable/Payable account (discovered
	# via a real .insert() failure while building this creator) — infer
	# party_type from the account when the LLM didn't extract one, and
	# resolve a placeholder party when it never resolved to a real record.
	if account:
		account_type = frappe.db.get_value("Account", account, "account_type")
		if account_type in ("Receivable", "Payable"):
			party_type = party_type or ("Customer" if account_type == "Receivable" else "Supplier")
			_unused_account, party = resolve_party(party_type, party, je.company)
	je.append(
		"accounts",
		{
			"account": account,
			"party_type": party_type,
			"party": party,
			"debit_in_account_currency": debit if debit is not None else 0,
			"credit_in_account_currency": credit if credit is not None else 0,
			"exchange_rate": exchange_rate,
		},
	)


def _append_bank_transaction_legs(je, row: dict, company: str, bank_account: str | None, exchange_rate: float = 1) -> None:
	is_deposit, amount = _txn_direction_amount(row)

	je.append(
		"accounts",
		{
			"account": bank_account,
			"debit_in_account_currency": amount if is_deposit else 0,
			"credit_in_account_currency": 0 if is_deposit else amount,
			"exchange_rate": exchange_rate,
			"user_remark": _value(row.get("narration")),
		},
	)

	# A reviewer-picked "Internal Transfer" (docapture/resolve.py) means this
	# row isn't a real counterparty at all — post straight to the picked
	# account, no party_type/party.
	counter_account_docname = _value(row.get("counter_account"))
	if counter_account_docname:
		je.append(
			"accounts",
			{
				"account": counter_account_docname,
				"debit_in_account_currency": 0 if is_deposit else amount,
				"credit_in_account_currency": amount if is_deposit else 0,
				"exchange_rate": exchange_rate,
			},
		)
		return

	resolved_party_type = _value(row.get("party_type"))
	resolved_party = _value(row.get("party"))
	# Direction decides the fallback party_type/account when the counterparty
	# itself never resolved to a real record (docs/COMPETITIVE_GAP_ROADMAP.md
	# gap #4) — deposits default to the company's receivable control account,
	# withdrawals to payable (ERPNext owns the accounting from here).
	party_type = resolved_party_type or ("Customer" if is_deposit else "Supplier")
	counter_account, party = resolve_party(party_type, resolved_party, company)
	if not counter_account:
		frappe.throw(
			_("Could not determine a {0} account for {1}. Set Company {2}'s default {0} account.").format(
				party_type, party, company
			)
		)

	je.append(
		"accounts",
		{
			"account": counter_account,
			"party_type": party_type,
			"party": party,
			"debit_in_account_currency": 0 if is_deposit else amount,
			"credit_in_account_currency": amount if is_deposit else 0,
			"exchange_rate": exchange_rate,
		},
	)


def _txn_direction_amount(row: dict) -> tuple[bool, float | None]:
	"""(is_deposit, amount) — deposit/withdrawal are mutually exclusive per
	row (docs/PHASE_3_MAPPER_PLAN.md "Bank Statement"), so whichever one
	actually carries a value decides both."""
	deposit = _amount(row.get("deposit"))
	if deposit is not None:
		return True, deposit
	return False, _amount(row.get("withdrawal"))


def _business_key(rows: list[dict]) -> tuple[str | None, float | None]:
	"""Supplier Bill/Expense Voucher business key: the row carrying a party
	(the Creditors/Debtors leg) gives the party + amount; falls back to the
	first row's amount when no row has a resolved party (a pure expense JE
	with no Customer/Supplier leg at all)."""
	amount = None
	party = None
	for row in rows:
		row_amount = _amount(row.get("debit")) or _amount(row.get("credit"))
		if row_amount is not None and amount is None:
			amount = row_amount
		row_party = _value(row.get("party"))
		if row_party:
			party = row_party
			amount = row_amount if row_amount is not None else amount
			break
	return party, amount
