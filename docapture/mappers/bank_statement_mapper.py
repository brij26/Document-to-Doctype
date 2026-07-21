# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# Routing (pipeline.py): Bank Statement -> here. Unlike payment_entry_mapper /
# journal_entry_mapper (one document = a header + its own variable-length row
# extraction), a bank statement is a table of an a-priori-unknown number of
# transaction rows — this mapper extracts that table, one page at a time, into
# BankStatementDTO.transactions. journal_entry_creator.create_bank_entries()
# turns each transaction into its own Journal Entry (bank leg + counter-
# account leg), not one Journal Entry per statement or per date.
import concurrent.futures

import frappe

from docapture.mappers import alias_resolver, layout
from docapture.mappers.llm_client import LLMParser
from docapture.mappers.schema import BankStatementDTO, FieldValue

# Statement-level fields, read once from the page-1 letterhead/header.
FIELDS = [
	("company_name", "company", "the account holder's own name, as printed on the statement"),
	("bank_name", "bank_account", "the bank's name, e.g. 'Union Bank of India', 'HDFC Bank'"),
	("account_no", "bank_account", "the bank account number this statement is for"),
	("statement_period", "posting_date", "the statement period covered, e.g. '01/12/2025 to 31/12/2025'"),
]

# Per-row fields, extracted per page via extract_rows. Hints describe meaning,
# not literal source column text — a different bank's "Debit"/"Credit"/"Dr"/
# "Cr" or narration style still maps onto these same canonical fields; the LLM
# does the column-name normalization, we never hardcode a bank's own headers.
ROW_FIELDS = [
	("date", "posting_date", "the transaction date for this row, as YYYY-MM-DD"),
	(
		"narration",
		"user_remark",
		"the full remarks/description/particulars text for this row, as printed, "
		"however the bank labels that column (Remarks, Description, Particulars, Narration...)",
	),
	("reference_no", "cheque_no", "the cheque/UTR/transaction/instrument reference number for this row, if any"),
	(
		"withdrawal",
		"accounts.debit_in_account_currency",
		"the debit/withdrawal amount for this row, as a plain number with no currency "
		"symbol or thousands separators; null if this row is a deposit",
	),
	(
		"deposit",
		"accounts.credit_in_account_currency",
		"the credit/deposit amount for this row, as a plain number with no currency "
		"symbol or thousands separators; null if this row is a withdrawal",
	),
	("balance", "", "the running account balance shown after this row, as a plain number"),
	(
		"counterparty_name",
		"accounts.party",
		"the counterparty/payee/payer name mentioned in the narration, if a specific person "
		"or organization is identifiable; null if this is a bank fee/charge, tax payment code, "
		"or internal reference number with no identifiable third party",
	),
]

# Which FIELDS resolve against Capture Alias.
_ENTITY_TYPE_BY_FIELD = {
	"company_name": "Company",
	"bank_name": "Bank Account",
	"account_no": "Bank Account",
}

# ponytail: counterparty_name is tried against Customer then Supplier then
# Employee then Account, in that fixed order, regardless of whether the row
# is a deposit or withdrawal. ERPNext's own auto_match_party.py picks the
# trial order from the deposit/withdrawal sign (Customer first for money in,
# Supplier first for money out) — worth doing here too if this order causes
# real mismatches once Phase 4 starts creating Journal Entries; not done yet
# since there is no evidence either way on real data.
#
# "Account" is not a party type — a reviewer picks it via the Resolve
# Unknowns dialog for a row that isn't a real counterparty at all (a
# self-transfer between the account holder's own accounts, a suspense/
# clearing posting, ...). A hit here is handled specially in _resolve_row
# (counter_account, not party_type/party).
_PARTY_ENTITY_TYPES = ("Customer", "Supplier", "Employee", "Account")


def build_dto(ocr_json: dict, llm: LLMParser, company: str | None = None) -> BankStatementDTO:
	pages = layout.reconstruct_pages(ocr_json)
	header_text = pages[0] if pages else ""

	# extract_fields (header) and extract_rows (per page) are independent
	# blocking HTTP calls to the LLM API — run them concurrently. Rows must
	# still land in transactions in original page order regardless of which
	# page's request happens to complete first, since _correct_withdrawal_deposit
	# and _forward_fill_date both depend on document order — so futures are
	# collected by (index, future) and resolved in index order, never via
	# as_completed().
	max_workers = frappe.conf.get("docapture_llm_row_workers", 8)
	with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
		fields_future = executor.submit(llm.extract_fields, header_text, FIELDS)
		row_futures = [
			(index, executor.submit(llm.extract_rows, page_text, ROW_FIELDS))
			for index, page_text in enumerate(pages)
			if page_text.strip()
		]

		raw_fields = fields_future.result()
		rows_by_page = sorted(((index, future.result()) for index, future in row_futures), key=lambda pair: pair[0])

	resolved_fields = alias_resolver.resolve_extracted(raw_fields, _ENTITY_TYPE_BY_FIELD, company)
	parent_fields = {
		name: FieldValue(
			value=result.get("value"),
			confidence=result.get("confidence", 0.0),
			mapped_doctype=_ENTITY_TYPE_BY_FIELD.get(name),
			mapped_docname=result.get("mapped_docname"),
		)
		for name, result in resolved_fields.items()
	}

	transactions: list[dict[str, FieldValue]] = []
	for _index, rows in rows_by_page:
		for raw_row in rows:
			transactions.append(_resolve_row(raw_row, company))

	_correct_withdrawal_deposit(transactions)
	_forward_fill_date(transactions)

	return BankStatementDTO(fields=parent_fields, transactions=transactions)


def _resolve_row(raw_row: dict, company: str | None) -> dict[str, FieldValue]:
	row: dict[str, FieldValue] = {}
	for dto_field, result in raw_row.items():
		value = result.get("value")
		confidence = result.get("confidence", 0.0)
		if dto_field == "counterparty_name" and value:
			match = _resolve_party(value, company)
			if match and match["entity_type"] == "Account":
				row["counterparty_name"] = FieldValue(value=value, confidence=1.0)
				row["counter_account"] = FieldValue(value=match["mapped_docname"], confidence=1.0)
				continue
			if match:
				row["counterparty_name"] = FieldValue(value=value, confidence=1.0)
				row["party_type"] = FieldValue(value=match["entity_type"], confidence=1.0)
				row["party"] = FieldValue(value=match["mapped_docname"], confidence=1.0)
				continue
		row[dto_field] = FieldValue(value=value, confidence=confidence)

	# Many real rows have no counterparty_name at all — a bare bank reference
	# code ("TRF 201-54921", "AA5361070") or a tax/fee narration with no
	# identifiable third party — so counterparty_name alone never gets tried
	# against Capture Alias above. Once a reviewer answers for one of these
	# via the Resolve Unknowns dialog (docapture/resolve.py, keyed by the
	# same narration/reference_no fallback text), this is what makes that
	# answer auto-apply on the next document with the identical code too,
	# not just the one already on screen.
	if not (row.get("counterparty_name") and row["counterparty_name"].value):
		fallback_text = _field_value(row.get("narration")) or _field_value(row.get("reference_no"))
		if fallback_text:
			match = _resolve_party(fallback_text, company)
			if match and match["entity_type"] == "Account":
				row["counter_account"] = FieldValue(value=match["mapped_docname"], confidence=1.0)
			elif match:
				row["party_type"] = FieldValue(value=match["entity_type"], confidence=1.0)
				row["party"] = FieldValue(value=match["mapped_docname"], confidence=1.0)

	return row


def _field_value(fv: FieldValue | None) -> str | None:
	return fv.value if fv is not None else None


def _resolve_party(raw_value: str, company: str | None) -> dict | None:
	for entity_type in _PARTY_ENTITY_TYPES:
		match = alias_resolver.resolve(entity_type, raw_value, company)
		if match:
			return {"entity_type": entity_type, **match}
	return None


# Text reconstruction (layout.py) loses column position, so the LLM sometimes
# puts an amount under the wrong one of withdrawal/deposit — same failure
# mode and fix aiaccountant.com documents for its own bank-statement parsing:
# a statement's balance is a running total, so previous_balance + deposit -
# withdrawal must equal the next row's balance. Mutates transactions in place.
def _correct_withdrawal_deposit(transactions: list[dict[str, FieldValue]]) -> None:
	prev_balance = None
	for row in transactions:
		balance = _parse_amount(row.get("balance"))
		if prev_balance is not None and balance is not None:
			delta = balance - prev_balance
			if delta > 0:
				_move_if_misplaced(row, correct_field="deposit", wrong_field="withdrawal")
			elif delta < 0:
				_move_if_misplaced(row, correct_field="withdrawal", wrong_field="deposit")
		if balance is not None:
			prev_balance = balance


def _move_if_misplaced(row: dict[str, FieldValue], correct_field: str, wrong_field: str) -> None:
	correct_fv = row.get(correct_field)
	wrong_fv = row.get(wrong_field)
	correct_has_value = correct_fv is not None and correct_fv.value is not None
	wrong_has_value = wrong_fv is not None and wrong_fv.value is not None
	if wrong_has_value and not correct_has_value:
		row[correct_field] = FieldValue(value=wrong_fv.value, confidence=wrong_fv.confidence)
		row[wrong_field] = FieldValue(value=None, confidence=wrong_fv.confidence)


# Some banks print the date once per day and rely on visual grouping for
# every other same-day transaction — layout.py's flat-text reconstruction
# loses that grouping, so the LLM has no date token anywhere near those
# rows to extract. Carries the last-seen parseable date forward onto any
# row missing one; confidence 0.4 (below the Preview dialog's <0.5
# low-confidence threshold) since this is an inference, not a real read.
# Mutates transactions in place.
def _forward_fill_date(transactions: list[dict[str, FieldValue]]) -> None:
	last_date = None
	for row in transactions:
		date_fv = row.get("date")
		if date_fv is not None and date_fv.value not in (None, ""):
			last_date = date_fv.value
		elif last_date is not None:
			row["date"] = FieldValue(value=last_date, confidence=0.4)


def _parse_amount(field_value: FieldValue | None) -> float | None:
	if field_value is None or field_value.value is None:
		return None
	try:
		return float(str(field_value.value).replace(",", "").strip())
	except ValueError:
		return None
