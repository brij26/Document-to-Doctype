# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.file_manager import get_file


class CapturedDocument(Document):
	def validate(self):
		self.set_content_hash()
		self.check_duplicate()

	def set_content_hash(self):
		if not self.file:
			return
		_filename, content = get_file(self.file)
		if isinstance(content, str):
			content = content.encode("utf-8")
		self.content_hash = hashlib.sha256(content).hexdigest()

	def check_duplicate(self):
		if not self.content_hash:
			return
		duplicate = frappe.db.exists(
			"Captured Document",
			{
				"content_hash": self.content_hash,
				"name": ["!=", self.name or ""],
				"status": ["not in", ["Rejected", "Failed"]],
			},
		)
		if duplicate:
			frappe.throw(
				_("This file is already captured as {0}.").format(
					frappe.utils.get_link_to_form("Captured Document", duplicate)
				),
				frappe.DuplicateEntryError,
			)
