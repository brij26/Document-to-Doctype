# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# DTO contract (see docs/PHASE_3_MAPPER_PLAN.md and docs/DESIGN_PRINCIPLES.md
# "The DTO is the contract"): every extracted field carries a value + a
# per-field confidence, so a low-confidence/missing field can surface in the
# Phase 4 review queue instead of silently becoming an empty draft field.
import json
from dataclasses import dataclass, field

SCHEMA_VERSION = 1


@dataclass
class FieldValue:
	value: object
	confidence: float


def overall_confidence(fields: dict[str, FieldValue]) -> float:
	if not fields:
		return 0.0
	return sum(f.confidence for f in fields.values()) / len(fields)


def _fields_to_json(fields: dict[str, FieldValue]) -> dict:
	return {name: {"value": fv.value, "confidence": fv.confidence} for name, fv in fields.items()}


@dataclass
class PaymentEntryDTO:
	fields: dict[str, FieldValue] = field(default_factory=dict)
	schema_version: int = SCHEMA_VERSION

	@property
	def confidence(self) -> float:
		return overall_confidence(self.fields)

	def to_json(self) -> str:
		return json.dumps(
			{
				"schema_version": self.schema_version,
				"target_doctype": "Payment Entry",
				"fields": _fields_to_json(self.fields),
			}
		)


@dataclass
class JournalEntryDTO:
	fields: dict[str, FieldValue] = field(default_factory=dict)
	# One entry per extracted "Journal Entry Account" row (account, party_type,
	# party, debit, credit, exchange_rate, ...) — see PHASE_3_MAPPER_PLAN.md.
	rows: list[dict[str, FieldValue]] = field(default_factory=list)
	schema_version: int = SCHEMA_VERSION

	@property
	def confidence(self) -> float:
		all_fields = dict(self.fields)
		for i, row in enumerate(self.rows):
			all_fields.update({f"row_{i}.{name}": fv for name, fv in row.items()})
		return overall_confidence(all_fields)

	def to_json(self) -> str:
		return json.dumps(
			{
				"schema_version": self.schema_version,
				"target_doctype": "Journal Entry",
				"fields": _fields_to_json(self.fields),
				"rows": [_fields_to_json(row) for row in self.rows],
			}
		)


@dataclass
class BankStatementDTO:
	# Statement-level fields: company_name, bank_name, account_no, statement_period.
	fields: dict[str, FieldValue] = field(default_factory=dict)
	# One entry per transaction row on the statement — length is whatever the
	# document actually contains (not fixed like JournalEntryDTO.rows), since a
	# bank statement can have anywhere from a handful to hundreds of rows.
	# Phase 4 turns each entry into its own Journal Entry (bank leg + counter
	# account leg), not one Journal Entry per statement.
	transactions: list[dict[str, FieldValue]] = field(default_factory=list)
	schema_version: int = SCHEMA_VERSION

	@property
	def confidence(self) -> float:
		all_fields = dict(self.fields)
		for i, row in enumerate(self.transactions):
			all_fields.update({f"txn_{i}.{name}": fv for name, fv in row.items()})
		return overall_confidence(all_fields)

	def to_json(self) -> str:
		return json.dumps(
			{
				"schema_version": self.schema_version,
				"target_doctype": "Journal Entry",
				"fields": _fields_to_json(self.fields),
				"transactions": [_fields_to_json(row) for row in self.transactions],
			}
		)
