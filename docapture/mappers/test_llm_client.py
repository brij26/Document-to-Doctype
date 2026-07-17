# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from docapture.mappers import llm_client
from docapture.mappers.claude_client import ClaudeParser
from docapture.mappers.openai_client import OpenAIParser

# get_parser() picks a class then calls its real constructor, which reads an
# API key from the environment — stub both so the branch-selection test
# doesn't depend on real credentials being configured.
_FAKE_ENV = {"OPENAI_API_KEY": "test-key", "ANTHROPIC_API_KEY": "test-key"}


class UnitTestGetParser(UnitTestCase):
	def tearDown(self):
		frappe.conf.pop("llm_backend", None)

	def test_defaults_to_openai(self):
		frappe.conf.pop("llm_backend", None)

		with patch.dict("os.environ", _FAKE_ENV):
			self.assertIsInstance(llm_client.get_parser(), OpenAIParser)

	def test_claude_backend_selects_claude_parser(self):
		frappe.conf.llm_backend = "claude"

		with patch.dict("os.environ", _FAKE_ENV):
			self.assertIsInstance(llm_client.get_parser(), ClaudeParser)
