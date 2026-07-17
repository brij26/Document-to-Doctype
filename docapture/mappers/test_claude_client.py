# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import json
from unittest.mock import MagicMock

from frappe.tests import UnitTestCase

from docapture.mappers.claude_client import ClaudeParser

FIELD_SPECS = [
	("posting_date", "posting_date", "the document date"),
	("paid_amount", "paid_amount", "the transaction amount"),
]


class UnitTestClaudeParser(UnitTestCase):
	def test_extract_fields_sends_json_schema_and_parses_response(self):
		fake_response = MagicMock()
		fake_response.content = [
			MagicMock(
				type="text",
				text=json.dumps(
					{
						"posting_date": {"value": "2026-07-16", "confidence": 0.95},
						"paid_amount": {"value": "1000.00", "confidence": 0.9},
					}
				),
			)
		]
		fake_client = MagicMock()
		fake_client.messages.create.return_value = fake_response

		result = ClaudeParser(client=fake_client).extract_fields("some document text", FIELD_SPECS)

		self.assertEqual(
			result,
			{
				"posting_date": {"value": "2026-07-16", "confidence": 0.95},
				"paid_amount": {"value": "1000.00", "confidence": 0.9},
			},
		)

		call_kwargs = fake_client.messages.create.call_args.kwargs
		self.assertEqual(call_kwargs["model"], "claude-opus-4-8")
		schema = call_kwargs["output_config"]["format"]["schema"]
		self.assertEqual(set(schema["required"]), {"posting_date", "paid_amount"})
		self.assertEqual(schema["additionalProperties"], False)

		prompt = call_kwargs["messages"][0]["content"]
		self.assertIn("some document text", prompt)
		self.assertIn("the document date", prompt)

	def test_extract_rows_sends_array_schema_and_parses_response(self):
		fake_response = MagicMock()
		fake_response.content = [
			MagicMock(
				type="text",
				text=json.dumps(
					{
						"rows": [
							{
								"posting_date": {"value": "2025-12-01", "confidence": 0.95},
								"paid_amount": {"value": "5000000.00", "confidence": 0.9},
							},
							{
								"posting_date": {"value": "2025-12-02", "confidence": 0.9},
								"paid_amount": {"value": "50000.00", "confidence": 0.85},
							},
						]
					}
				),
			)
		]
		fake_client = MagicMock()
		fake_client.messages.create.return_value = fake_response

		result = ClaudeParser(client=fake_client).extract_rows("some table text", FIELD_SPECS)

		self.assertEqual(len(result), 2)
		self.assertEqual(result[0]["posting_date"], {"value": "2025-12-01", "confidence": 0.95})
		self.assertEqual(result[1]["paid_amount"], {"value": "50000.00", "confidence": 0.85})

		call_kwargs = fake_client.messages.create.call_args.kwargs
		self.assertEqual(call_kwargs["model"], "claude-opus-4-8")
		schema = call_kwargs["output_config"]["format"]["schema"]
		self.assertEqual(schema["required"], ["rows"])
		row_schema = schema["properties"]["rows"]["items"]
		self.assertEqual(set(row_schema["required"]), {"posting_date", "paid_amount"})

		prompt = call_kwargs["messages"][0]["content"]
		self.assertIn("some table text", prompt)
		self.assertIn("the document date", prompt)
