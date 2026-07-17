# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# Routing (docs/PHASE_3_MAPPER_PLAN.md): Supplier Bill, Expense Voucher -> here.
from docapture.mappers import alias_resolver, layout
from docapture.mappers.llm_client import LLMParser
from docapture.mappers.schema import FieldValue, JournalEntryDTO

# FIELDS is a hand-curated superset (docs/PHASE_3_MAPPER_PLAN.md "Decision"),
# same rationale as payment_entry_mapper.FIELDS. Journal Entry Account rows
# are flattened as row1_*/row2_* dto_fields here (build_dto splits them back
# into JournalEntryDTO.rows) since LLMParser.extract_fields returns a flat
# dict, not a repeated/list structure.
#
# ponytail: fixed at exactly 2 rows (the debit/credit pair a supplier-bill or
# expense-voucher JE typically needs — "PE/JE have no item table",
# docs/FEATURE_LIST.md). Upgrade to a variable row count when a fixture
# needs a 3+ row journal entry.
FIELDS = [
	# dto_field,          erpnext_field,                         hint for the LLM prompt
	("posting_date", "posting_date", "the document/transaction date, as YYYY-MM-DD"),
	("cheque_no", "cheque_no", "cheque/reference number, only if this is a bank entry"),
	("cheque_date", "cheque_date", "date on the cheque/reference, if separate from posting_date"),
	("row1_account", "accounts.account", "the first ledger account this document affects, e.g. an expense head or Creditors"),
	("row1_party_type", "accounts.party_type", "'Customer' or 'Supplier', only if row1_account is a Receivable/Payable account"),
	("row1_party", "accounts.party", "the counterparty name for row1_account, if applicable"),
	("row1_debit", "accounts.debit_in_account_currency", "the debit amount for row1_account, as a plain number"),
	("row1_credit", "accounts.credit_in_account_currency", "the credit amount for row1_account, as a plain number"),
	("row1_exchange_rate", "accounts.exchange_rate", "only if row1_account's currency differs from the company currency"),
	("row2_account", "accounts.account", "the second ledger account this document affects, e.g. a bank/cash account"),
	("row2_party_type", "accounts.party_type", "'Customer' or 'Supplier', only if row2_account is a Receivable/Payable account"),
	("row2_party", "accounts.party", "the counterparty name for row2_account, if applicable"),
	("row2_debit", "accounts.debit_in_account_currency", "the debit amount for row2_account, as a plain number"),
	("row2_credit", "accounts.credit_in_account_currency", "the credit amount for row2_account, as a plain number"),
	("row2_exchange_rate", "accounts.exchange_rate", "only if row2_account's currency differs from the company currency"),
]

# Which FIELDS resolve against Capture Alias (docs/ARCHITECTURE.md). row*_party
# is left unresolved for Phase 3 — Capture Alias's entity_type options have no
# "Customer" entry, only "Supplier", so resolving it correctly needs the
# row's own party_type first; not worth the conditional plumbing yet.
_ENTITY_TYPE_BY_FIELD = {
	"row1_account": "Account",
	"row2_account": "Account",
}

_ROW_PREFIXES = ("row1_", "row2_")


def build_dto(ocr_json: dict, llm: LLMParser) -> JournalEntryDTO:
	text = layout.reconstruct(ocr_json)
	raw = llm.extract_fields(text, FIELDS)
	resolved = alias_resolver.resolve_extracted(raw, _ENTITY_TYPE_BY_FIELD)

	parent_fields: dict[str, FieldValue] = {}
	rows: list[dict[str, FieldValue]] = [{}, {}]
	for dto_field, result in resolved.items():
		field_value = FieldValue(value=result.get("value"), confidence=result.get("confidence", 0.0))
		for row_index, prefix in enumerate(_ROW_PREFIXES):
			if dto_field.startswith(prefix):
				rows[row_index][dto_field[len(prefix) :]] = field_value
				break
		else:
			parent_fields[dto_field] = field_value

	return JournalEntryDTO(fields=parent_fields, rows=rows)
