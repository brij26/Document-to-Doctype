# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

from unittest.mock import patch

from frappe.tests import UnitTestCase

from docapture import notify


class UnitTestNotifyFailure(UnitTestCase):
	def test_notifies_reviewer_and_system_manager_users(self):
		with (
			patch.object(notify, "get_users_with_role", side_effect=lambda role: {"a@example.com"} if role == "System Manager" else {"b@example.com"}),
			patch.object(notify, "enqueue_create_notification") as enqueue,
		):
			notify.notify_failure("CAP-00001", "Traceback (most recent call last):\nRuntimeError: boom")

		enqueue.assert_called_once()
		users, doc = enqueue.call_args[0]
		self.assertEqual(users, ["a@example.com", "b@example.com"])
		self.assertEqual(doc["document_type"], "Captured Document")
		self.assertEqual(doc["document_name"], "CAP-00001")
		self.assertIn("Traceback", doc["subject"])  # first line of the traceback, not the full text
		self.assertNotIn("RuntimeError", doc["subject"])

	def test_no_op_when_no_reviewer_users(self):
		with (
			patch.object(notify, "get_users_with_role", return_value=set()),
			patch.object(notify, "enqueue_create_notification") as enqueue,
		):
			notify.notify_failure("CAP-00002", "boom")

		enqueue.assert_not_called()
