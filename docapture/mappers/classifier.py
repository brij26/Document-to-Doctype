# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# Heuristic-first classifier (docs/PHASE_3_MAPPER_PLAN.md "Classifier"): a
# keyword scorer over layout.reconstruct() output picks source_type for the
# common case at zero extra LLM cost — an LLM classification call would
# double API cost per document (one to classify, one to extract) for a
# 4-way decision keyword scoring can handle. Only a low-signal/ambiguous
# document falls back to one LLM call. KEYWORDS and CLASSIFICATION_THRESHOLD
# are calibrated against the 5 documents in tests/fixtures/{mappers,
# ocr/sales_order_page1} — see docs/PHASE_3_MAPPER_PLAN.md's threshold
# section for what that calibration set does and doesn't prove.
from docapture.mappers import layout
from docapture.mappers.llm_client import LLMParser

SOURCE_TYPES = ["Payment Receipt", "Bank Statement", "Supplier Bill", "Expense Voucher"]

# Two phrases per type, both drawn from real fixture text (not assumed
# vocabulary) — see docs/PHASE_3_MAPPER_PLAN.md for the corrections this
# went through. Kept short and highly-distinguishing on purpose: a real
# match should score 1.0 (both phrases present), not require tuning a long
# list to cross a threshold.
#
# Bank Statement was originally ["previous balance", "withdrawals"] —
# recalibrated after a real Union Bank of India statement (title "Statement
# of Account", no "previous balance" phrase anywhere) scored only 0.5 and
# fell through to an LLM fallback that misclassified it as Payment Receipt.
# "withdrawals"/"deposits" are the transaction table's own column headers —
# confirmed present in both the original calibration fixture and the UBI
# statement, so this doesn't regress the fixture that was already passing.
KEYWORDS = {
	"Bank Statement": ["withdrawals", "deposits"],
	"Payment Receipt": ["payment receipt", "receipt number"],
	"Supplier Bill": ["invoice", "bill to"],
	"Expense Voucher": ["expense voucher", "payment method"],
}

CLASSIFICATION_THRESHOLD = 0.6


def classify(ocr_json: dict, llm: LLMParser) -> dict:
	"""-> {"source_type", "confidence", "method": "heuristic" | "llm_fallback"}."""
	text = layout.reconstruct(ocr_json).lower()
	scores = {source_type: _score(text, keywords) for source_type, keywords in KEYWORDS.items()}
	best_type = max(scores, key=scores.get)
	best_score = scores[best_type]

	if best_score >= CLASSIFICATION_THRESHOLD:
		return {"source_type": best_type, "confidence": best_score, "method": "heuristic"}

	return _classify_with_llm(text, llm)


def _score(text: str, keywords: list[str]) -> float:
	hits = sum(1 for keyword in keywords if keyword in text)
	return hits / len(keywords)


def _classify_with_llm(text: str, llm: LLMParser) -> dict:
	field_specs = [("source_type", "source_type", f"exactly one of: {', '.join(SOURCE_TYPES)}")]
	result = llm.extract_fields(text, field_specs)["source_type"]
	return {"source_type": result["value"], "confidence": result["confidence"], "method": "llm_fallback"}
