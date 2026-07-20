# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# Normalizes a parsed `extracted_json` dict (any of PaymentEntryDTO/
# JournalEntryDTO/BankStatementDTO's to_json() shapes, docapture/mappers/
# schema.py) into one reviewer-facing contract for the Preview feature, and
# applies reviewer-supplied corrections back into that same dict shape.
# Pure functions, no DB/doc access — router.py owns loading/saving the
# Captured Document itself.
import copy


def to_preview(extracted: dict) -> dict:
	"""One contract for all 3 DTO shapes, driven by which key is present —
	no source_type branching, so a future DTO shape needs no change here as
	long as it follows the existing fields/(rows|transactions) convention."""
	if extracted.get("rows") is not None:
		row_key, row_label = "rows", "Row"
	elif extracted.get("transactions") is not None:
		row_key, row_label = "transactions", "Transaction"
	else:
		row_key, row_label = None, None

	return {
		"target_doctype": extracted.get("target_doctype"),
		"header_fields": _fields_to_list(extracted.get("fields") or {}),
		"row_label": row_label,
		"rows": [_fields_to_list(row) for row in extracted[row_key]] if row_key else None,
	}


def _fields_to_list(fields: dict) -> list[dict]:
	return [
		{
			"field_name": name,
			"value": (field_value or {}).get("value"),
			"confidence": (field_value or {}).get("confidence"),
			"mapped_doctype": (field_value or {}).get("mapped_doctype"),
			"mapped_docname": (field_value or {}).get("mapped_docname"),
		}
		for name, field_value in fields.items()
	]


def apply_corrections(extracted: dict, corrections: dict) -> dict:
	"""Reviewer-edited values, in the same {"header_fields": {name: value},
	"rows": [{name: value}, ...] | None} shape to_preview() emits, applied
	back into a copy of `extracted`. A field whose value didn't actually
	change is left byte-for-byte alone (keeps its original confidence and
	any alias-resolved mapped_docname); a changed field's confidence is
	bumped to 1.0. If the field is alias-eligible (mapped_doctype set —
	docapture/mappers/schema.py's FieldValue), the new value is trusted as
	the resolved docname itself (it came from a Preview Link picker) and
	mapped_docname is set to it; otherwise mapped_docname is dropped — a
	free-text edit is no longer a trusted alias-resolved link.

	corrections["deleted_row_indices"] (0-indexed into the original row
	list, same indexing to_preview() emits) drops those rows entirely —
	e.g. a "Balance brought forward" line the OCR/LLM extracted as a bogus
	transaction. Field corrections are applied first so an index refers to
	the same row in both."""
	result = copy.deepcopy(extracted)
	corrections = corrections or {}

	_apply_field_corrections(result.get("fields") or {}, corrections.get("header_fields") or {})

	row_key = "rows" if result.get("rows") is not None else ("transactions" if result.get("transactions") is not None else None)
	if row_key:
		for row, row_correction in zip(result[row_key], corrections.get("rows") or [], strict=False):
			_apply_field_corrections(row, row_correction or {})

		deleted = set(corrections.get("deleted_row_indices") or [])
		if deleted:
			result[row_key] = [row for i, row in enumerate(result[row_key]) if i not in deleted]

	return result


def _apply_field_corrections(fields: dict, corrected_values: dict) -> None:
	for field_name, new_value in corrected_values.items():
		field_value = fields.get(field_name)
		if field_value is None:
			# a correction for a field docapture never extracted — nothing to
			# anchor it to, so it's dropped rather than inventing a new field.
			continue
		if _normalize(new_value) == _normalize(field_value.get("value")):
			continue
		field_value["value"] = new_value
		field_value["confidence"] = 1.0
		if field_value.get("mapped_doctype"):
			field_value["mapped_docname"] = new_value
		else:
			field_value.pop("mapped_docname", None)


def new_aliases(extracted: dict, updated: dict) -> list[dict]:
	"""Fields corrected via apply_corrections() that are also alias-eligible
	(mapped_doctype set) become Capture Alias candidates — the reviewer's
	picked value becomes the mapped_docname for future documents carrying
	the same raw OCR text. Returns alias-row specs ({"entity_type",
	"raw_value", "mapped_docname"}); doesn't touch the DB — router.py owns
	creating/updating the actual Capture Alias records."""
	specs: list[dict] = []
	_collect_new_aliases(extracted.get("fields") or {}, updated.get("fields") or {}, specs)

	row_key = "rows" if updated.get("rows") is not None else ("transactions" if updated.get("transactions") is not None else None)
	if row_key:
		for old_row, new_row in zip(extracted.get(row_key) or [], updated.get(row_key) or [], strict=False):
			_collect_new_aliases(old_row, new_row, specs)

	return specs


def _collect_new_aliases(old_fields: dict, new_fields: dict, specs: list) -> None:
	for name, new_fv in new_fields.items():
		mapped_doctype = (new_fv or {}).get("mapped_doctype")
		if not mapped_doctype:
			continue
		old_fv = old_fields.get(name) or {}
		if _normalize(new_fv.get("value")) == _normalize(old_fv.get("value")):
			continue
		raw_value = old_fv.get("value") or new_fv.get("value")
		if not raw_value or not new_fv.get("mapped_docname"):
			continue
		specs.append({"entity_type": mapped_doctype, "raw_value": raw_value, "mapped_docname": new_fv["mapped_docname"]})


def _normalize(value) -> str | None:
	if value is None:
		return None
	value = str(value).strip()
	return value or None
