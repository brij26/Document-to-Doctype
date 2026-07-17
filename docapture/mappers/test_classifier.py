# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

from pathlib import Path

import cv2
import frappe
from frappe.tests import UnitTestCase

from docapture.mappers import classifier
from docapture.ocr import paddle_engine, pymupdf_extractor

FIXTURE_DIR = Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/mappers"


def _ocr_json(filename: str) -> dict:
	path = FIXTURE_DIR / filename
	image = cv2.imread(str(path))
	if image is None:
		# .webp — this bench's opencv build actually decodes it fine (see
		# docs/PHASE_3_MAPPER_PLAN.md), but fall back to PIL defensively.
		import numpy as np
		from PIL import Image

		image = np.array(Image.open(path).convert("RGB"))[:, :, ::-1].copy()
	lines = paddle_engine.extract_page(image, 200)["lines"]
	return {"pages": [{"lines": lines}]}


class _UnusedLLM:
	def extract_fields(self, prompt_text, field_specs):
		raise AssertionError("LLM fallback should not fire for a clear-signal fixture")


class _StubLLM:
	def __init__(self, source_type: str, confidence: float):
		self._result = {"value": source_type, "confidence": confidence}
		self.calls = []

	def extract_fields(self, prompt_text, field_specs):
		self.calls.append((prompt_text, field_specs))
		return {"source_type": self._result}


class UnitTestClassifier(UnitTestCase):
	def test_classifies_bank_statement_via_heuristic(self):
		result = classifier.classify(_ocr_json("sample_bank_statement.png"), _UnusedLLM())
		self.assertEqual(result, {"source_type": "Bank Statement", "confidence": 1.0, "method": "heuristic"})

	def test_classifies_expense_voucher_via_heuristic(self):
		result = classifier.classify(_ocr_json("sample_Expense_Voucher.png"), _UnusedLLM())
		self.assertEqual(result, {"source_type": "Expense Voucher", "confidence": 1.0, "method": "heuristic"})

	def test_classifies_supplier_bill_via_heuristic(self):
		result = classifier.classify(_ocr_json("sample_supplier_bill.png"), _UnusedLLM())
		self.assertEqual(result, {"source_type": "Supplier Bill", "confidence": 1.0, "method": "heuristic"})

	def test_classifies_payment_receipt_via_heuristic(self):
		# Also the .webp decode-path smoke test — see PHASE_3_MAPPER_PLAN.md.
		result = classifier.classify(_ocr_json("sample_payment_reciept.webp"), _UnusedLLM())
		self.assertEqual(result, {"source_type": "Payment Receipt", "confidence": 1.0, "method": "heuristic"})

	def test_classifies_real_ubi_bank_statement_via_heuristic(self):
		# Real-world calibration fixture (docs/PHASE_3_MAPPER_PLAN.md): a Union
		# Bank of India statement titled "Statement of Account" with no
		# "previous balance" phrase — this is what motivated the
		# ["withdrawals", "deposits"] recalibration.
		path = FIXTURE_DIR / "sample_bank_statement_ubi.pdf"
		results = pymupdf_extractor.extract_document(path.read_bytes())
		ocr_json = {"pages": [{"lines": r["lines"]} for r in results]}

		result = classifier.classify(ocr_json, _UnusedLLM())

		self.assertEqual(result["source_type"], "Bank Statement")
		self.assertEqual(result["method"], "heuristic")

	def test_falls_back_to_llm_when_no_keyword_signal(self):
		# Synthetic, deliberately ambiguous — none of the 4 fixtures exercise
		# this path by construction, so it needs its own coverage.
		ocr_json = {
			"pages": [{"lines": [{"text": "hello world, nothing distinctive here", "bbox": [0, 0, 50, 20], "words": []}]}]
		}
		llm = _StubLLM("Payment Receipt", 0.42)

		result = classifier.classify(ocr_json, llm)

		self.assertEqual(result, {"source_type": "Payment Receipt", "confidence": 0.42, "method": "llm_fallback"})
		self.assertEqual(len(llm.calls), 1)

	def test_sales_order_fixture_is_out_of_domain_and_falls_back(self):
		# Known-negative case (docs/PHASE_3_MAPPER_PLAN.md): not a docapture
		# source_type at all, so the heuristic should score it 0 across every
		# type and defer to the LLM rather than confidently misclassifying it.
		sales_order_path = (
			Path(frappe.get_app_path("docapture")).parent
			/ "tests/fixtures/ocr/sales_order_page1/input.jpg"
		)
		image = cv2.imread(str(sales_order_path))
		lines = paddle_engine.extract_page(image, 200)["lines"]
		ocr_json = {"pages": [{"lines": lines}]}
		llm = _StubLLM("Supplier Bill", 0.3)

		result = classifier.classify(ocr_json, llm)

		self.assertEqual(result["method"], "llm_fallback")
		self.assertEqual(len(llm.calls), 1)
