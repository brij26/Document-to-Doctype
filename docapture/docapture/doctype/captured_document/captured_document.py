# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

import hashlib
from pathlib import Path

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.file_manager import get_file

# Matches what docapture/ocr/pipeline.py handles: .pdf via the native pymupdf path,
# the rest via cv2.imdecode.
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


class CapturedDocument(Document):
	def validate(self):
		self.check_file_type()
		self.set_content_hash()
		self.check_duplicate()

	def check_file_type(self):
		if not self.file:
			return
		extension = Path(self.file).suffix.lower()
		if extension not in ALLOWED_EXTENSIONS:
			frappe.throw(
				_("Unsupported file type {0}. Supported: PDF, JPG, PNG, TIFF, BMP, WEBP.").format(extension),
				frappe.ValidationError,
			)

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
