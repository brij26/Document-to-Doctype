# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CaptureAlias(Document):
	def validate(self):
		self.check_duplicate()

	def check_duplicate(self):
		duplicate = frappe.db.exists(
			"Capture Alias",
			{
				"entity_type": self.entity_type,
				"normalized_value": self.normalized_value,
				"company": self.company or "",
				"name": ["!=", self.name or ""],
			},
		)
		if duplicate:
			frappe.throw(
				_("An alias for {0} / {1} already exists: {2}.").format(
					self.entity_type,
					self.normalized_value,
					frappe.utils.get_link_to_form("Capture Alias", duplicate),
				),
				frappe.DuplicateEntryError,
			)
