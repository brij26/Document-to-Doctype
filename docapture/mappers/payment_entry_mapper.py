# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# Routing (docs/PHASE_3_MAPPER_PLAN.md): Payment Receipt, Bank Statement -> here.
from docapture.mappers import alias_resolver, layout
from docapture.mappers.llm_client import LLMParser
from docapture.mappers.schema import FieldValue, PaymentEntryDTO

# FIELDS is a hand-curated superset (docs/PHASE_3_MAPPER_PLAN.md "Decision")
# — includes conditionally-mandatory ERPNext fields (party_type, exchange_rate,
# reference_no) so the LLM attempts them whenever the source document shows
# the signal, even though ERPNext itself won't always require them. A field
# absent from the document stays null with low/zero confidence; Phase 4's
# creator and the human review queue decide what's actually required.
FIELDS = [
	# dto_field,        erpnext_field,                 hint for the LLM prompt
	("posting_date", "posting_date", "the document/transaction date, as YYYY-MM-DD"),
	("party_type", "party_type", "'Customer' or 'Supplier', if identifiable from context"),
	("party_name", "party", "the counterparty name as printed on the document"),
	("company_name", "company", "the paying/receiving company's own name as printed"),
	("paid_amount", "paid_amount", "the transaction amount, as a plain number"),
	("currency", "paid_from_account_currency", "the currency code/symbol if present, e.g. INR or USD"),
	("exchange_rate", "source_exchange_rate", "only if a foreign-currency amount is shown"),
	("mode_of_payment", "mode_of_payment", "e.g. Cash, Cheque, Bank Transfer, UPI, Card"),
	("reference_no", "reference_no", "cheque/UTR/transaction reference number"),
	("reference_date", "reference_date", "date on that reference, if separate from posting_date"),
]

# Which FIELDS resolve against Capture Alias (docs/ARCHITECTURE.md).
_ENTITY_TYPE_BY_FIELD = {
	"party_name": "Supplier",
	"company_name": "Company",
	"currency": "Currency",
	"mode_of_payment": "Mode of Payment",
}


def build_dto(ocr_json: dict, llm: LLMParser, company: str | None = None) -> PaymentEntryDTO:
	text = layout.reconstruct(ocr_json)
	raw = llm.extract_fields(text, FIELDS)
	resolved = alias_resolver.resolve_extracted(raw, _ENTITY_TYPE_BY_FIELD, company)
	fields = {
		name: FieldValue(
			value=result.get("value"),
			confidence=result.get("confidence", 0.0),
			mapped_doctype=_ENTITY_TYPE_BY_FIELD.get(name),
			mapped_docname=result.get("mapped_docname"),
		)
		for name, result in resolved.items()
	}
	return PaymentEntryDTO(fields=fields)
