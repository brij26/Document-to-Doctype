# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# Small readers over a parsed DTO's {"value": ..., "confidence": ...} field
# shape (docapture/mappers/schema.py's FieldValue, after to_json()/
# frappe.parse_json() round-tripping) — shared by every creators/* module so
# each one doesn't reimplement the same three lookups.


def value(field_value: dict | None):
	if not field_value:
		return None
	return field_value.get("value")


def amount(field_value: dict | None) -> float | None:
	raw = value(field_value)
	if raw is None:
		return None
	try:
		return float(str(raw).replace(",", "").strip())
	except ValueError:
		return None


def alias_docname(field_value: dict | None) -> str | None:
	"""A resolved Capture Alias hit keeps "value" as the raw OCR text but
	adds mapped_docname for the real record (alias_resolver.resolve_extracted)
	— only present on a hit."""
	if not field_value:
		return None
	return field_value.get("mapped_docname")
