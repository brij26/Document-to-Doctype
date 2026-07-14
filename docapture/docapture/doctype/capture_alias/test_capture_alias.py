# Copyright (c) 2026, Frappe Bench and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
# Company's own test-record chain creates a "_Test Fiscal Year 2027" record that
# overlaps this site's real (non-test) fiscal year. Our test never touches the
# company field, so skip pulling that chain in.
IGNORE_TEST_RECORD_DEPENDENCIES = ["Company"]


class IntegrationTestCaptureAlias(IntegrationTestCase):
	"""
	Integration tests for CaptureAlias.
	Use this class for testing interactions between multiple components.
	"""

	def test_duplicate_alias_blocked(self):
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Currency",
				"raw_value": "Indian Rupee",
				"normalized_value": "inr",
				"mapped_doctype": "Currency",
				"mapped_docname": "INR",
				"source": "User Confirmed",
			}
		).insert()

		duplicate = frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Currency",
				"raw_value": "INR.",
				"normalized_value": "inr",
				"mapped_doctype": "Currency",
				"mapped_docname": "INR",
				"source": "User Confirmed",
			}
		)
		self.assertRaises(frappe.DuplicateEntryError, duplicate.insert)
