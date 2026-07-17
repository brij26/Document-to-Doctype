# Copyright (c) 2026, Frappe Bench and Contributors
# See license.txt

from pathlib import Path

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

FIXTURE_DIR = Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/ocr/sales_order_page1"
SAMPLE_PDF = (FIXTURE_DIR / "Sales order.pdf").read_bytes()
SAMPLE_JPG = (FIXTURE_DIR / "input.jpg").read_bytes()
SAMPLE_WEBP = (
	Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/mappers/sample_payment_reciept.webp"
).read_bytes()


def attach(dn, content, extension="pdf"):
	# Since check_file_type() validates the extension and Frappe's own File doctype
	# validates real PDF/image structure at attach time (pdf_contains_js,
	# strip_exif_data), placeholder text can no longer stand in for file content —
	# content must be genuinely valid bytes for whichever extension is used.
	file_doc = save_file(f"{dn}.{extension}", content, "Captured Document", dn, is_private=1)
	return file_doc.file_url


class IntegrationTestCapturedDocument(IntegrationTestCase):
	"""
	Integration tests for CapturedDocument.
	Use this class for testing interactions between multiple components.
	"""

	def test_status_walk_and_duplicate_detection(self):
		# Salted per test run (not per dn): these two docs must share a content_hash
		# to exercise the duplicate check, but the shared content must still be
		# unique across runs, or it collides with a leftover row from a previous
		# `bench run-tests` invocation (tests here aren't transactionally rolled back).
		content = SAMPLE_PDF + frappe.generate_hash(length=8).encode()
		doc = frappe.get_doc(
			{
				"doctype": "Captured Document",
				"file": attach("test-cap-1", content),
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
				"file": attach("test-cap-2", content),
				"source_type": "Payment Receipt",
			}
		)
		self.assertRaises(frappe.DuplicateEntryError, duplicate.insert)

	def test_reupload_allowed_after_rejection(self):
		content = SAMPLE_JPG + frappe.generate_hash(length=8).encode()
		rejected = frappe.get_doc(
			{
				"doctype": "Captured Document",
				"file": attach("test-cap-3", content, extension="jpg"),
				"source_type": "Payment Receipt",
			}
		).insert()
		rejected.status = "Rejected"
		rejected.save()

		reupload = frappe.get_doc(
			{
				"doctype": "Captured Document",
				"file": attach("test-cap-4", content, extension="jpg"),
				"source_type": "Payment Receipt",
			}
		).insert()

		self.assertEqual(reupload.content_hash, rejected.content_hash)

	def test_webp_upload_accepted(self):
		# .webp joined ALLOWED_EXTENSIONS once tests/fixtures/mappers/*.webp
		# proved the rest of the ingestion path already handles it (see
		# docs/PHASE_3_MAPPER_PLAN.md). This is the attach-time half of that
		# guarantee; docapture.ocr.test_pipeline covers the OCR half.
		doc = frappe.get_doc(
			{
				"doctype": "Captured Document",
				"file": attach("test-cap-webp", SAMPLE_WEBP, extension="webp"),
				"source_type": "Payment Receipt",
			}
		).insert()

		self.assertTrue(doc.content_hash)
		self.assertEqual(doc.status, "Uploaded")

	def test_unsupported_file_type_rejected(self):
		doc = frappe.get_doc(
			{
				"doctype": "Captured Document",
				"file": attach("test-cap-5", b"not a real document", extension="txt"),
				"source_type": "Payment Receipt",
			}
		)
		with self.assertRaises(frappe.ValidationError) as context:
			doc.insert()
		self.assertIn(".txt", str(context.exception))
