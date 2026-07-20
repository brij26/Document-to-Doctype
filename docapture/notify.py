# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# Pipeline failures (ocr/pipeline.py, mappers/pipeline.py, router.py) only
# wrote to frappe.log_error before this — invisible unless someone was
# watching the Error Log (docs/COMPETITIVE_GAP_ROADMAP.md gap #10). Pushes a
# bell-icon Notification Log entry instead — native to Frappe, no SMTP/email
# configuration required, unlike frappe.sendmail.
import frappe
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.utils.user import get_users_with_role

_REVIEWER_ROLES = ("System Manager", "Docapture Reviewer")


def notify_failure(captured_document: str, error: str) -> None:
	users = sorted({user for role in _REVIEWER_ROLES for user in get_users_with_role(role)})
	if not users:
		return
	first_line = (error or "").strip().splitlines()[0][:140] if error else "unknown error"
	enqueue_create_notification(
		users,
		{
			"subject": f"Docapture: {captured_document} failed — {first_line}",
			"type": "Alert",
			"document_type": "Captured Document",
			"document_name": captured_document,
			"from_user": frappe.session.user,
		},
	)
