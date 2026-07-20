# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# normalize -> Capture Alias lookup -> auto-map or leave unresolved
# (docs/ARCHITECTURE.md "Capture Alias"). Reuses the doctype built in Phase 1;
# does not create new aliases — that only happens when a reviewer confirms
# one in the Phase 4 review queue.
import re

import frappe

_LEGAL_SUFFIXES = ("pvt ltd", "pvt limited", "private limited", "llp", "inc", "ltd", "limited")

# company (optional) scopes the lookup: tried first as an exact
# (entity_type, normalized_value, company) match, then falls back to
# whatever matches on (entity_type, normalized_value) alone — the same
# unscoped lookup this always did (docs/COMPETITIVE_GAP_ROADMAP.md gap #6,
# fixed as part of Phase 4 per docs/PHASE_STATUS.md's Phase 4 kickoff entry:
# "Phase 4 is exactly when a document's company first resolves onto a
# draft"). Phase 3's own mapper-time resolution still can't pass a `company`
# for the very field that identifies the company itself (company_name) —
# that one field is inherently unscoped, same as before.
#
# ponytail: the unscoped fallback still exists and can still pick an alias
# belonging to a *different* company than the one requested, when no
# company-scoped alias has been created yet for this normalized_value —
# closing that fully needs either backfilling `company` onto every existing
# alias row or dropping the fallback outright once real multi-company data
# exists to test against; not done speculatively here.


def normalize(raw_value: str) -> str:
	value = raw_value.strip().lower()
	value = re.sub(r"[^\w\s]", "", value)
	value = re.sub(r"\s+", " ", value).strip()
	for suffix in _LEGAL_SUFFIXES:
		if value.endswith(suffix):
			value = value[: -len(suffix)].strip()
			break
	return value


def resolve(entity_type: str, raw_value: str, company: str | None = None) -> dict | None:
	"""Hit -> {"mapped_doctype", "mapped_docname"}. Miss -> None (left
	unresolved for the review queue)."""
	if not raw_value:
		return None
	normalized = normalize(raw_value)
	if company:
		match = frappe.db.get_value(
			"Capture Alias",
			{"entity_type": entity_type, "normalized_value": normalized, "company": company},
			["mapped_doctype", "mapped_docname"],
			as_dict=True,
		)
		if match:
			return {"mapped_doctype": match.mapped_doctype, "mapped_docname": match.mapped_docname}
	match = frappe.db.get_value(
		"Capture Alias",
		{"entity_type": entity_type, "normalized_value": normalized},
		["mapped_doctype", "mapped_docname"],
		as_dict=True,
	)
	if not match:
		return None
	return {"mapped_doctype": match.mapped_doctype, "mapped_docname": match.mapped_docname}


def resolve_extracted(raw_fields: dict, entity_type_by_field: dict[str, str], company: str | None = None) -> dict:
	"""raw_fields: LLMParser.extract_fields()'s {dto_field: {"value", "confidence"}}.
	entity_type_by_field: which of those dto_fields are Capture Alias-resolvable,
	and under which entity_type. On a hit, confidence is raised to 1.0 and the
	resolved record is attached; on a miss the field is returned unchanged."""
	resolved = {}
	for dto_field, field_result in raw_fields.items():
		entity_type = entity_type_by_field.get(dto_field)
		value = field_result.get("value")
		match = resolve(entity_type, value, company) if entity_type and value else None
		resolved[dto_field] = {**field_result, "confidence": 1.0, **match} if match else field_result
	return resolved
