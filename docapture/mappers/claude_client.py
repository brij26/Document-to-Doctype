# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# Concrete LLMParser (llm_client.py) backed by the Claude API. Mappers depend
# on the LLMParser protocol, not this class, so swapping vendors later means
# a new file here, not edits to payment_entry_mapper.py / journal_entry_mapper.py.
import json

import anthropic
from langsmith.wrappers import wrap_anthropic

from docapture.mappers import llm_client
from docapture.mappers.llm_client import (
	FieldSpec,
	build_prompt,
	build_row_prompt,
	build_row_schema,
	build_schema,
)

MODEL = "claude-opus-4-8"


class ClaudeParser:
	def __init__(self, client: anthropic.Anthropic | None = None):
		# Only the real default client is traced — a caller passing its own
		# client (tests, mainly) opted out of the default wiring on purpose.
		self._tracer = None
		if client is None:
			self._tracer = llm_client.new_tracer()
			api_key = llm_client.resolve_api_key("anthropic_api_key", "ANTHROPIC_API_KEY")
			client = wrap_anthropic(anthropic.Anthropic(api_key=api_key), tracing_extra={"client": self._tracer})
		self._client = client

	def extract_fields(self, prompt_text: str, field_specs: list[FieldSpec]) -> dict[str, dict]:
		response = self._client.messages.create(
			model=MODEL,
			max_tokens=4096,
			output_config={"format": {"type": "json_schema", "schema": build_schema(field_specs)}},
			messages=[{"role": "user", "content": build_prompt(prompt_text, field_specs)}],
		)
		text = next(block.text for block in response.content if block.type == "text")
		result = json.loads(text)
		if self._tracer:
			self._tracer.flush()
		return result

	def extract_rows(self, prompt_text: str, field_specs: list[FieldSpec]) -> list[dict[str, dict]]:
		response = self._client.messages.create(
			model=MODEL,
			# Higher than extract_fields' 4096 — a bank statement page's table can
			# run to dozens of rows, each with several fields.
			max_tokens=8192,
			output_config={"format": {"type": "json_schema", "schema": build_row_schema(field_specs)}},
			messages=[{"role": "user", "content": build_row_prompt(prompt_text, field_specs)}],
		)
		text = next(block.text for block in response.content if block.type == "text")
		result = json.loads(text)
		if self._tracer:
			self._tracer.flush()
		return result["rows"]
