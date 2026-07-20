# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

import traceback

import frappe

from docapture import notify
from docapture.mappers import (
	bank_statement_mapper,
	classifier,
	journal_entry_mapper,
	llm_client,
	payment_entry_mapper,
)

# Routing (docs/PHASE_3_MAPPER_PLAN.md "Routing"): source_type -> mapper.
# Bank Statement -> bank_statement_mapper (not payment_entry_mapper): a bank
# statement's rows become Journal Entries (bank leg + counter-account leg per
# row), not Payment Entries — many rows (self-transfers, GST/TDS/bank fees)
# don't fit Payment Entry's Customer/Supplier-only model. See
# docs/PHASE_3_MAPPER_PLAN.md's Bank Statement section for the rationale.
_BUILD_DTO_BY_SOURCE_TYPE = {
	"Payment Receipt": payment_entry_mapper.build_dto,
	"Bank Statement": bank_statement_mapper.build_dto,
	"Supplier Bill": journal_entry_mapper.build_dto,
	"Expense Voucher": journal_entry_mapper.build_dto,
}


def run_mapper(captured_document: str):
	doc = frappe.get_doc("Captured Document", captured_document)
	if doc.status != "OCR Done":
		# Stale/duplicate enqueue, or the document moved on before this ran.
		return
	llm = None
	try:
		ocr_json = frappe.parse_json(doc.raw_ocr_json)
		llm = llm_client.get_parser()
		classification = classifier.classify(ocr_json, llm)
		build_dto = _BUILD_DTO_BY_SOURCE_TYPE[classification["source_type"]]
		dto = build_dto(ocr_json, llm, doc.company)
		doc.db_set({"extracted_json": dto.to_json(), "confidence": dto.confidence, "status": "Parsed"}, notify=True)
		doc.db_set({"status": "In Review"}, notify=True)
	except Exception:
		error = traceback.format_exc()
		doc.db_set({"error_log": error, "status": "Failed"}, notify=True)
		notify.notify_failure(doc.name, error)
	finally:
		if llm is not None:
			llm.flush()
