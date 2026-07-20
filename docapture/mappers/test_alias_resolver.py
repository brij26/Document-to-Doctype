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

	def test_resolve_prefers_company_scoped_alias_over_unscoped(self):
		normalized = alias_resolver.normalize("Acme Supplies Co")
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Account",
				"raw_value": "Acme Supplies Co",
				"normalized_value": normalized,
				"mapped_doctype": "DocType",
				"mapped_docname": "Account",
				"company": "_Test Company 1",
				"source": "User Confirmed",
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Account",
				"raw_value": "Acme Supplies Co",
				"normalized_value": normalized,
				"mapped_doctype": "DocType",
				"mapped_docname": "Currency",
				"company": "_Test Company 2",
				"source": "User Confirmed",
			}
		).insert()

		scoped = alias_resolver.resolve("Account", "Acme Supplies Co", "_Test Company 2")

		self.assertEqual(scoped["mapped_docname"], "Currency")

	def test_resolve_falls_back_to_unscoped_when_no_company_specific_alias(self):
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Account",
				"raw_value": "Only Unscoped Vendor",
				"normalized_value": alias_resolver.normalize("Only Unscoped Vendor"),
				"mapped_doctype": "DocType",
				"mapped_docname": "Account",
				"source": "User Confirmed",
			}
		).insert()

		# A company that has no alias row of its own still falls back to
		# whatever alias exists, rather than resolving nothing.
		match = alias_resolver.resolve("Account", "Only Unscoped Vendor", "_Test Company 3")

		self.assertEqual(match["mapped_docname"], "Account")

	def test_resolve_extracted_threads_company_through(self):
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Currency",
				"raw_value": "Company Scoped Currency",
				"normalized_value": alias_resolver.normalize("Company Scoped Currency"),
				"mapped_doctype": "Currency",
				"mapped_docname": "EUR",
				"company": "_Test Company",
				"source": "User Confirmed",
			}
		).insert()

		resolved = alias_resolver.resolve_extracted(
			{"currency": {"value": "Company Scoped Currency", "confidence": 0.5}},
			{"currency": "Currency"},
			"_Test Company",
		)

		self.assertEqual(resolved["currency"]["mapped_docname"], "EUR")

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
