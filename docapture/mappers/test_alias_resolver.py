# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from docapture.mappers import alias_resolver


class UnitTestNormalize(IntegrationTestCase):
	def test_normalize_collapses_legal_suffix_and_punctuation_variants(self):
		variants = ["ABC pvt limited", "ABC Pvt. Ltd.", "ABC PRIVATE LIMITED", "  ABC   Ltd"]
		normalized = {alias_resolver.normalize(v) for v in variants}
		self.assertEqual(normalized, {"abc"})


class IntegrationTestAliasResolver(IntegrationTestCase):
	def test_resolve_hits_on_normalized_value(self):
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Currency",
				"raw_value": "Indian Rupee",
				"normalized_value": alias_resolver.normalize("Indian Rupee"),
				"mapped_doctype": "Currency",
				"mapped_docname": "INR",
				"source": "User Confirmed",
			}
		).insert()

		match = alias_resolver.resolve("Currency", "Indian Rupee")

		self.assertEqual(match, {"mapped_doctype": "Currency", "mapped_docname": "INR"})

	def test_resolve_misses_on_unknown_value(self):
		self.assertIsNone(alias_resolver.resolve("Currency", "Not A Real Currency Name"))

	def test_resolve_extracted_merges_hit_and_leaves_miss_untouched(self):
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Currency",
				"raw_value": "US Dollar",
				"normalized_value": alias_resolver.normalize("US Dollar"),
				"mapped_doctype": "Currency",
				"mapped_docname": "USD",
				"source": "User Confirmed",
			}
		).insert()

		raw = {
			"currency": {"value": "US Dollar", "confidence": 0.6},
			"paid_amount": {"value": "500", "confidence": 0.95},
		}

		resolved = alias_resolver.resolve_extracted(raw, {"currency": "Currency"})

		self.assertEqual(
			resolved["currency"],
			{"value": "US Dollar", "confidence": 1.0, "mapped_doctype": "Currency", "mapped_docname": "USD"},
		)
		self.assertEqual(resolved["paid_amount"], raw["paid_amount"])
