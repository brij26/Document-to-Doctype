# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# Concrete LLMParser (llm_client.py) backed by the OpenAI API. Mappers depend
# on the LLMParser protocol, not this class — same swap point claude_client.py
# uses, picked over it for now for API-key availability (see PHASE_STATUS.md).
import json

import openai
from langsmith.wrappers import wrap_openai

from docapture.mappers import llm_client
from docapture.mappers.llm_client import (
	FieldSpec,
	build_prompt,
	build_row_prompt,
	build_row_schema,
	build_schema,
)

MODEL = "gpt-4.1"


class OpenAIParser:
	def __init__(self, client: openai.OpenAI | None = None):
		# Only the real default client is traced — a caller passing its own
		# client (tests, mainly) opted out of the default wiring on purpose.
		self._tracer = None
		if client is None:
			self._tracer = llm_client.new_tracer()
			api_key = llm_client.resolve_api_key("openai_api_key", "OPENAI_API_KEY")
			client = wrap_openai(openai.OpenAI(api_key=api_key), tracing_extra={"client": self._tracer})
		self._client = client

	def extract_fields(self, prompt_text: str, field_specs: list[FieldSpec]) -> dict[str, dict]:
		response = self._client.responses.create(
			model=MODEL,
			input=build_prompt(prompt_text, field_specs),
			text={
				"format": {
					"type": "json_schema",
					"name": "extracted_fields",
					"schema": build_schema(field_specs),
					"strict": True,
				}
			},
		)
		result = json.loads(response.output_text)
		if self._tracer:
			self._tracer.flush()
		return result

	def extract_rows(self, prompt_text: str, field_specs: list[FieldSpec]) -> list[dict[str, dict]]:
		response = self._client.responses.create(
			model=MODEL,
			input=build_row_prompt(prompt_text, field_specs),
			text={
				"format": {
					"type": "json_schema",
					"name": "extracted_rows",
					"schema": build_row_schema(field_specs),
					"strict": True,
				}
			},
		)
		result = json.loads(response.output_text)
		if self._tracer:
			self._tracer.flush()
		return result["rows"]
