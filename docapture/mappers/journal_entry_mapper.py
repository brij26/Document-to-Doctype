# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# Routing (docs/PHASE_3_MAPPER_PLAN.md): Supplier Bill, Expense Voucher -> here.
# Bank Statement's date-grouped Journal Entry creation (Phase 4) also reuses
# ROW_FIELDS below via creators/journal_entry_creator.py, not this build_dto —
# a bank statement's rows come from bank_statement_mapper.py's own
# BankStatementDTO.transactions, extracted per-page, not from a document-level
# extract_rows call like this mapper makes.
from docapture.mappers import alias_resolver, layout
from docapture.mappers.llm_client import LLMParser
from docapture.mappers.schema import FieldValue, JournalEntryDTO

# Header-level fields, one set per document.
FIELDS = [
	# dto_field,      erpnext_field,   hint for the LLM prompt
	("posting_date", "posting_date", "the document/transaction date, as YYYY-MM-DD"),
	("cheque_no", "cheque_no", "cheque/reference number, only if this is a bank entry"),
	("cheque_date", "cheque_date", "date on the cheque/reference, if separate from posting_date"),
]

# Per-row (Journal Entry Account) fields, extracted via extract_rows — row
# count is whatever the document actually needs (2 for a simple debit/credit
# pair, 3+ for a bill with a TDS/rounding/split-cost-center leg), not fixed.
ROW_FIELDS = [
	("account", "accounts.account", "the ledger account this row affects, e.g. an expense head, Creditors, or a bank/cash account"),
	("party_type", "accounts.party_type", "'Customer' or 'Supplier', only if account is a Receivable/Payable account"),
	("party", "accounts.party", "the counterparty name for this row, if applicable"),
	("debit", "accounts.debit_in_account_currency", "the debit amount for this row, as a plain number"),
	("credit", "accounts.credit_in_account_currency", "the credit amount for this row, as a plain number"),
	("exchange_rate", "accounts.exchange_rate", "only if this row's account currency differs from the company currency"),
]

# Which ROW_FIELDS resolve against Capture Alias (docs/ARCHITECTURE.md). party
# is left unresolved for Phase 3/4 mapping — same rationale as the prior
# row1_party/row2_party: Capture Alias's entity_type options have no
# "Customer" entry, only "Supplier", so resolving it correctly needs the
# row's own party_type first; not worth the conditional plumbing yet.
_ROW_ENTITY_TYPE_BY_FIELD = {
	"account": "Account",
}


def build_dto(ocr_json: dict, llm: LLMParser, company: str | None = None) -> JournalEntryDTO:
	text = layout.reconstruct(ocr_json)

	raw_header = llm.extract_fields(text, FIELDS)
	parent_fields = {
		name: FieldValue(value=result.get("value"), confidence=result.get("confidence", 0.0))
		for name, result in raw_header.items()
	}

	rows: list[dict[str, FieldValue]] = []
	for raw_row in llm.extract_rows(text, ROW_FIELDS):
		resolved_row = alias_resolver.resolve_extracted(raw_row, _ROW_ENTITY_TYPE_BY_FIELD, company)
		rows.append(
			{
				name: FieldValue(
					value=result.get("value"),
					confidence=result.get("confidence", 0.0),
					mapped_doctype=_ROW_ENTITY_TYPE_BY_FIELD.get(name),
					mapped_docname=result.get("mapped_docname"),
				)
				for name, result in resolved_row.items()
			}
		)

	return JournalEntryDTO(fields=parent_fields, rows=rows)
