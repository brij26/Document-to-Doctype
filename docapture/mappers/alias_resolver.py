# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# normalize -> Capture Alias lookup -> auto-map or leave unresolved
# (docs/ARCHITECTURE.md "Capture Alias"). Reuses the doctype built in Phase 1;
# does not create new aliases — that only happens when a reviewer confirms
# one in the Phase 4 review queue.
import re

import frappe

_LEGAL_SUFFIXES = ("pvt ltd", "pvt limited", "private limited", "llp", "inc", "ltd", "limited")

# ponytail: lookups ignore `company` entirely (match on entity_type +
# normalized_value only) — Phase 3 has no resolved `company` context yet at
# extraction time (that's itself sometimes an aliased field), and Frappe
# auto-fills a Link field's `company` from the site's default Company on
# insert whenever one exists, so filtering for "company not set" would miss
# most real rows in a single-company deployment. Thread a real `company`
# through and scope this properly once Phase 4 wires up per-document company
# resolution; see Capture Alias's own `company` field for the intended
# scoping — until then, a normalized_value that's ambiguous across companies
# just resolves to one of them.


def normalize(raw_value: str) -> str:
	value = raw_value.strip().lower()
	value = re.sub(r"[^\w\s]", "", value)
	value = re.sub(r"\s+", " ", value).strip()
	for suffix in _LEGAL_SUFFIXES:
		if value.endswith(suffix):
			value = value[: -len(suffix)].strip()
			break
	return value


def resolve(entity_type: str, raw_value: str) -> dict | None:
	"""Hit -> {"mapped_doctype", "mapped_docname"}. Miss -> None (left
	unresolved for the review queue)."""
	if not raw_value:
		return None
	match = frappe.db.get_value(
		"Capture Alias",
		{"entity_type": entity_type, "normalized_value": normalize(raw_value)},
		["mapped_doctype", "mapped_docname"],
		as_dict=True,
	)
	if not match:
		return None
	return {"mapped_doctype": match.mapped_doctype, "mapped_docname": match.mapped_docname}


def resolve_extracted(raw_fields: dict, entity_type_by_field: dict[str, str]) -> dict:
	"""raw_fields: LLMParser.extract_fields()'s {dto_field: {"value", "confidence"}}.
	entity_type_by_field: which of those dto_fields are Capture Alias-resolvable,
	and under which entity_type. On a hit, confidence is raised to 1.0 and the
	resolved record is attached; on a miss the field is returned unchanged."""
	resolved = {}
	for dto_field, field_result in raw_fields.items():
		entity_type = entity_type_by_field.get(dto_field)
		value = field_result.get("value")
		match = resolve(entity_type, value) if entity_type and value else None
		resolved[dto_field] = {**field_result, "confidence": 1.0, **match} if match else field_result
	return resolved
