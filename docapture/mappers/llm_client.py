# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

import os
from typing import Protocol, runtime_checkable

import frappe
import langsmith

# A FIELDS entry, as defined by each mapper (payment_entry_mapper.FIELDS,
# journal_entry_mapper.FIELDS): (dto_field, erpnext_field, hint for the LLM).
FieldSpec = tuple[str, str, str]


@runtime_checkable
class LLMParser(Protocol):
	def extract_fields(self, prompt_text: str, field_specs: list[FieldSpec]) -> dict[str, dict]:
		"""prompt_text (layout.reconstruct() output), field_specs (a mapper's
		FIELDS) -> {dto_field: {"value": ..., "confidence": ...}}.

		The one vendor-swappable call — narrower than turning ocr_json straight
		into a DTO (see docs/PHASE_3_MAPPER_PLAN.md "Naming"): reconstruction,
		prompt-building, and DTO assembly stay in the mapper's build_dto().
		"""
		...

	def extract_rows(self, prompt_text: str, field_specs: list[FieldSpec]) -> list[dict[str, dict]]:
		"""Same contract as extract_fields, but for a page containing a table of
		repeated rows (bank_statement_mapper.py) instead of one set of fields —
		row count is whatever the page actually contains, not fixed ahead of
		time. Returns one extract_fields()-shaped dict per row, in document order.
		"""
		...


def get_parser() -> LLMParser:
	"""The one place pipeline.py/classifier.py get a concrete LLMParser —
	picks by `site_config.json`'s `llm_backend` ("openai" default, "claude"
	the alternative) so swapping vendors is a config change, not an edit to
	the callers that use the protocol."""
	backend = frappe.conf.get("llm_backend", "openai")
	if backend == "claude":
		from docapture.mappers.claude_client import ClaudeParser

		return ClaudeParser()
	from docapture.mappers.openai_client import OpenAIParser

	return OpenAIParser()


def resolve_api_key(config_key: str, env_var: str) -> str | None:
	"""`bench --site <site> set-config <config_key> <key>` takes priority;
	falls back to the process environment (e.g. an exported var ahead of
	`bench start`/`bench worker`, or a loaded `.env` — see this file's
	LangSmith tracing precedent) so an already-working env-var setup keeps
	working with zero migration. Shared by openai_client.py/claude_client.py
	so a vendor swap doesn't also mean reimplementing this lookup."""
	return frappe.conf.get(config_key) or os.environ.get(env_var)


def new_tracer() -> langsmith.Client:
	"""A LangSmith Client each concrete parser (claude_client.py,
	openai_client.py) holds onto so it can call `.flush()` synchronously
	after every extract_fields() call — not optional. frappe.enqueue jobs
	run under RQ, which forks a child process per job and calls
	`os._exit(0)` on it once the job returns (see rq/worker.py). That skips
	Python's atexit hooks entirely, including the one LangSmith's Client
	normally relies on to flush its background send queue — without an
	explicit flush, every trace from a background job gets stuck "pending"
	in the LangSmith UI, having recorded a start but never an end. Safe to
	call even when tracing is off (`LANGSMITH_TRACING` unset/false):
	flush() on an empty queue is a no-op."""
	return langsmith.Client()


def build_schema(field_specs: list[FieldSpec]) -> dict:
	"""JSON schema for {dto_field: {"value", "confidence"}}, shared by every
	LLMParser implementation (claude_client.py, openai_client.py) — the shape
	is a vendor-agnostic contract, not something each concrete client should
	redefine."""
	field_schema = {
		"type": "object",
		"properties": {
			"value": {"type": ["string", "null"]},
			"confidence": {"type": "number"},
		},
		"required": ["value", "confidence"],
		"additionalProperties": False,
	}
	return {
		"type": "object",
		"properties": {dto_field: field_schema for dto_field, _erpnext_field, _hint in field_specs},
		"required": [dto_field for dto_field, _erpnext_field, _hint in field_specs],
		"additionalProperties": False,
	}


def build_prompt(prompt_text: str, field_specs: list[FieldSpec]) -> str:
	field_lines = "\n".join(f"- {dto_field}: {hint}" for dto_field, _erpnext_field, hint in field_specs)
	return (
		"Extract the following fields from this OCR-scanned accounting document. "
		"For each field, return the extracted value (or null if it is not present "
		"in the document) and your confidence, from 0.0 to 1.0, that the value is "
		"correct.\n\n"
		f"Fields to extract:\n{field_lines}\n\n"
		f"Document text:\n{prompt_text}"
	)


def build_row_schema(field_specs: list[FieldSpec]) -> dict:
	"""JSON schema for {"rows": [<build_schema() shape>, ...]} — the
	table-extraction counterpart to build_schema, wrapped in an object (rather
	than a bare top-level array) since structured-output APIs expect an object
	schema at the root. Row count is unconstrained — a bank statement page can
	hold anywhere from a handful to dozens of transactions."""
	return {
		"type": "object",
		"properties": {"rows": {"type": "array", "items": build_schema(field_specs)}},
		"required": ["rows"],
		"additionalProperties": False,
	}


def build_row_prompt(prompt_text: str, field_specs: list[FieldSpec]) -> str:
	field_lines = "\n".join(f"- {dto_field}: {hint}" for dto_field, _erpnext_field, hint in field_specs)
	return (
		"This document contains a table of repeated transaction rows. Extract "
		"one entry per row, in the order they appear on the page. Return as many "
		"rows as the table actually contains — do not guess or cap the count. "
		"For each field on each row, return the extracted value (or null if not "
		"present) and your confidence, from 0.0 to 1.0, that the value is "
		"correct.\n\n"
		f"Fields to extract per row:\n{field_lines}\n\n"
		f"Document text:\n{prompt_text}"
	)
