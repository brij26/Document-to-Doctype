# Copyright (c) 2026, Frappe Bench and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.file_manager import save_file

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
# Company's own test-record chain creates a "_Test Fiscal Year 2027" record that
# overlaps this site's real (non-test) fiscal year. Our tests never touch the
# company/currency fields, so skip pulling that chain in.
IGNORE_TEST_RECORD_DEPENDENCIES = ["Company"]


def attach(dn, content):
	file_doc = save_file(f"{dn}.txt", content, "Captured Document", dn, is_private=1)
	return file_doc.file_url


class IntegrationTestCapturedDocument(IntegrationTestCase):
	"""
	Integration tests for CapturedDocument.
	Use this class for testing interactions between multiple components.
	"""

	def test_status_walk_and_duplicate_detection(self):
		doc = frappe.get_doc(
			{
				"doctype": "Captured Document",
				"file": attach("test-cap-1", b"sample invoice content"),
				"source_type": "Payment Receipt",
			}
		).insert()

		self.assertTrue(doc.content_hash)
		self.assertEqual(doc.status, "Uploaded")

		for status in ("OCR Done", "Parsed", "In Review", "Approved", "Posted"):
			doc.status = status
			doc.save()
			doc.reload()
			self.assertEqual(doc.status, status)

		duplicate = frappe.get_doc(
			{
				"doctype": "Captured Document",
				"file": attach("test-cap-2", b"sample invoice content"),
				"source_type": "Payment Receipt",
			}
		)
		self.assertRaises(frappe.DuplicateEntryError, duplicate.insert)

	def test_reupload_allowed_after_rejection(self):
		rejected = frappe.get_doc(
			{
				"doctype": "Captured Document",
				"file": attach("test-cap-3", b"rejected invoice content"),
				"source_type": "Payment Receipt",
			}
		).insert()
		rejected.status = "Rejected"
		rejected.save()

		reupload = frappe.get_doc(
			{
				"doctype": "Captured Document",
				"file": attach("test-cap-4", b"rejected invoice content"),
				"source_type": "Payment Receipt",
			}
		).insert()

		self.assertEqual(reupload.content_hash, rejected.content_hash)
