# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import time
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

from docapture.mappers import alias_resolver
from docapture.mappers.bank_statement_mapper import FIELDS, ROW_FIELDS, build_dto
from docapture.ocr import pymupdf_extractor

FIXTURE = Path(frappe.get_app_path("docapture")).parent / "tests/fixtures/mappers/sample_bank_statement_ubi.pdf"

_TWO_PAGE_OCR_JSON = {
	"pages": [
		{"lines": [{"text": "page one text", "bbox": [0, 0, 10, 10], "words": []}]},
		{"lines": [{"text": "page two text", "bbox": [0, 0, 10, 10], "words": []}]},
	]
}


class _StubLLM:
	def __init__(self, field_values: dict, rows_by_page: dict[str, list[dict]] | None = None):
		self._field_values = field_values
		self._rows_by_page = rows_by_page or {}

	def extract_fields(self, prompt_text, field_specs):
		return {
			dto_field: self._field_values.get(dto_field, {"value": None, "confidence": 0.0})
			for dto_field, _erpnext_field, _hint in field_specs
		}

	def extract_rows(self, prompt_text, field_specs):
		rows = self._rows_by_page.get(prompt_text, [])
		return [
			{
				dto_field: row.get(dto_field, {"value": None, "confidence": 0.0})
				for dto_field, _erpnext_field, _hint in field_specs
			}
			for row in rows
		]


class IntegrationTestBankStatementMapper(IntegrationTestCase):
	def test_build_dto_reads_statement_fields_from_first_page_only(self):
		llm = _StubLLM({"account_no": {"value": "312805010077512", "confidence": 0.95}})

		dto = build_dto(_TWO_PAGE_OCR_JSON, llm)

		self.assertEqual(dto.fields["account_no"].value, "312805010077512")

	def test_build_dto_resolves_known_bank_account_alias(self):
		# Salted — tests here aren't transactionally rolled back
		# (docs/PHASE_STATUS.md), so a fixed literal collides with a leftover
		# Capture Alias row from a prior run of this same test.
		account_no = f"3128050100{frappe.generate_hash(length=6)}"
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Bank Account",
				"raw_value": account_no,
				"normalized_value": alias_resolver.normalize(account_no),
				"mapped_doctype": "Bank Account",
				"mapped_docname": "Test Bank Account - UBI",
				"source": "User Confirmed",
			}
		).insert(ignore_links=True)
		llm = _StubLLM({"account_no": {"value": account_no, "confidence": 0.6}})

		dto = build_dto(_TWO_PAGE_OCR_JSON, llm)

		self.assertEqual(dto.fields["account_no"].mapped_doctype, "Bank Account")
		self.assertEqual(dto.fields["account_no"].mapped_docname, "Test Bank Account - UBI")

	def test_build_dto_marks_bank_account_field_as_unresolved_on_miss(self):
		llm = _StubLLM({"account_no": {"value": "999999999", "confidence": 0.6}})

		dto = build_dto(_TWO_PAGE_OCR_JSON, llm)

		self.assertEqual(dto.fields["account_no"].mapped_doctype, "Bank Account")
		self.assertIsNone(dto.fields["account_no"].mapped_docname)

	def test_build_dto_concatenates_transactions_across_pages(self):
		llm = _StubLLM(
			{},
			rows_by_page={
				"page one text": [{"date": {"value": "2025-12-01", "confidence": 0.9}}],
				"page two text": [
					{"date": {"value": "2025-12-02", "confidence": 0.9}},
					{"date": {"value": "2025-12-03", "confidence": 0.9}},
				],
			},
		)

		dto = build_dto(_TWO_PAGE_OCR_JSON, llm)

		self.assertEqual(len(dto.transactions), 3)
		self.assertEqual(dto.transactions[0]["date"].value, "2025-12-01")
		self.assertEqual(dto.transactions[1]["date"].value, "2025-12-02")
		self.assertEqual(dto.transactions[2]["date"].value, "2025-12-03")

	def test_transactions_preserve_page_order_even_when_pages_finish_out_of_order(self):
		# Regression test for parallelizing extract_rows across a ThreadPoolExecutor:
		# pages must be stitched back together by original page index, not by
		# completion order. Page one sleeps longest, page three sleeps least, so
		# if results were collected via as_completed() (completion order) instead
		# of by index, page three's row would land first in dto.transactions --
		# this test fails under that bug and only passes under the by-index fix.
		ocr_json = {
			"pages": [
				{"lines": [{"text": "page one text", "bbox": [0, 0, 10, 10], "words": []}]},
				{"lines": [{"text": "page two text", "bbox": [0, 0, 10, 10], "words": []}]},
				{"lines": [{"text": "page three text", "bbox": [0, 0, 10, 10], "words": []}]},
			]
		}
		sleep_by_page = {"page one text": 0.3, "page two text": 0.15, "page three text": 0.0}
		rows_by_page = {
			"page one text": [{"date": {"value": "2025-12-01", "confidence": 0.9}}],
			"page two text": [{"date": {"value": "2025-12-02", "confidence": 0.9}}],
			"page three text": [{"date": {"value": "2025-12-03", "confidence": 0.9}}],
		}

		class _SlowStubLLM(_StubLLM):
			def extract_rows(self, prompt_text, field_specs):
				time.sleep(sleep_by_page.get(prompt_text, 0.0))
				return super().extract_rows(prompt_text, field_specs)

		llm = _SlowStubLLM({}, rows_by_page=rows_by_page)

		dto = build_dto(ocr_json, llm)

		self.assertEqual(
			[row["date"].value for row in dto.transactions],
			["2025-12-01", "2025-12-02", "2025-12-03"],
		)

	def test_build_dto_skips_blank_pages(self):
		ocr_json = {"pages": [{"lines": []}, _TWO_PAGE_OCR_JSON["pages"][0]]}
		llm = _StubLLM({}, rows_by_page={"page one text": [{"date": {"value": "2025-12-01", "confidence": 0.9}}]})

		dto = build_dto(ocr_json, llm)

		self.assertEqual(len(dto.transactions), 1)

	def test_counterparty_name_resolves_against_customer_alias(self):
		customer = frappe.get_doc({"doctype": "Customer", "customer_name": "GAYATRI PRIVATE LIMITED"}).insert()
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Customer",
				"raw_value": "GAYATRI PRIVATE LIMITED",
				"normalized_value": alias_resolver.normalize("GAYATRI PRIVATE LIMITED"),
				"mapped_doctype": "Customer",
				"mapped_docname": customer.name,
				"source": "User Confirmed",
			}
		).insert()
		llm = _StubLLM(
			{},
			rows_by_page={
				"page one text": [
					{"counterparty_name": {"value": "GAYATRI PRIVATE LIMITED", "confidence": 0.7}}
				]
			},
		)

		dto = build_dto({"pages": [_TWO_PAGE_OCR_JSON["pages"][0]]}, llm)

		row = dto.transactions[0]
		self.assertEqual(row["party_type"].value, "Customer")
		self.assertEqual(row["party"].value, customer.name)
		self.assertEqual(row["counterparty_name"].confidence, 1.0)

	def test_counterparty_name_falls_back_to_supplier_alias(self):
		supplier = frappe.get_doc({"doctype": "Supplier", "supplier_name": "KAVACH SECURITY SERVICE"}).insert()
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Supplier",
				"raw_value": "KAVACH SECURITY SERVICE",
				"normalized_value": alias_resolver.normalize("KAVACH SECURITY SERVICE"),
				"mapped_doctype": "Supplier",
				"mapped_docname": supplier.name,
				"source": "User Confirmed",
			}
		).insert()
		llm = _StubLLM(
			{},
			rows_by_page={
				"page one text": [
					{"counterparty_name": {"value": "KAVACH SECURITY SERVICE", "confidence": 0.7}}
				]
			},
		)

		dto = build_dto({"pages": [_TWO_PAGE_OCR_JSON["pages"][0]]}, llm)

		row = dto.transactions[0]
		self.assertEqual(row["party_type"].value, "Supplier")
		self.assertEqual(row["party"].value, supplier.name)

	def test_unresolved_counterparty_name_left_unresolved(self):
		# Salted, distinct-looking-from-any-real-bank-code text — a fixed
		# literal that happens to resemble real narration text (this test
		# used to hardcode "AA5360992") can collide with real Capture Alias
		# rows this site's own live use of the feature has since created,
		# not just leftover test data.
		reference_code = f"TEST-UNRESOLVED-{frappe.generate_hash(length=8)}"
		llm = _StubLLM(
			{},
			rows_by_page={
				"page one text": [
					{"counterparty_name": {"value": reference_code, "confidence": 0.2}}
				]
			},
		)

		dto = build_dto({"pages": [_TWO_PAGE_OCR_JSON["pages"][0]]}, llm)

		row = dto.transactions[0]
		self.assertEqual(row["counterparty_name"].value, reference_code)
		self.assertEqual(row["counterparty_name"].confidence, 0.2)
		self.assertNotIn("party_type", row)
		self.assertNotIn("party", row)

	def test_narration_resolves_via_alias_when_counterparty_name_is_missing(self):
		# Many real rows have no counterparty_name at all — a bare bank
		# reference code — so a Capture Alias saved against that narration
		# text (docapture/resolve.py's Resolve Unknowns dialog) must still
		# auto-resolve on the next document. Salted, distinct-looking-from-
		# any-real-bank-code text — tests here aren't transactionally rolled
		# back (docs/PHASE_STATUS.md) and this site also has real uploaded
		# statements with their own Capture Alias rows; a fixed literal that
		# happens to look like real narration text (e.g. "TRF 201-54921")
		# can collide with genuine data, not just a leftover test row.
		reference_code = f"TEST-REF-{frappe.generate_hash(length=8)}"
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Account",
				"raw_value": reference_code,
				"normalized_value": alias_resolver.normalize(reference_code),
				"mapped_doctype": "Account",
				"mapped_docname": "Cash - _TC",
				"source": "User Confirmed",
			}
		).insert()
		llm = _StubLLM(
			{},
			rows_by_page={
				"page one text": [
					{
						"counterparty_name": {"value": None, "confidence": 0.0},
						"narration": {"value": reference_code, "confidence": 0.9},
					}
				]
			},
		)

		dto = build_dto({"pages": [_TWO_PAGE_OCR_JSON["pages"][0]]}, llm)

		row = dto.transactions[0]
		self.assertEqual(row["counter_account"].value, "Cash - _TC")
		self.assertNotIn("party_type", row)
		self.assertNotIn("party", row)

	def test_narration_falls_back_to_customer_alias_when_counterparty_name_is_missing(self):
		reference_code = f"TEST-REF-{frappe.generate_hash(length=8)}"
		customer = frappe.get_doc({"doctype": "Customer", "customer_name": f"Narration Customer {frappe.generate_hash(length=6)}"}).insert()
		frappe.get_doc(
			{
				"doctype": "Capture Alias",
				"entity_type": "Customer",
				"raw_value": reference_code,
				"normalized_value": alias_resolver.normalize(reference_code),
				"mapped_doctype": "Customer",
				"mapped_docname": customer.name,
				"source": "User Confirmed",
			}
		).insert()
		llm = _StubLLM(
			{},
			rows_by_page={
				"page one text": [
					{
						"counterparty_name": {"value": None, "confidence": 0.0},
						"narration": {"value": reference_code, "confidence": 0.9},
					}
				]
			},
		)

		dto = build_dto({"pages": [_TWO_PAGE_OCR_JSON["pages"][0]]}, llm)

		row = dto.transactions[0]
		self.assertEqual(row["party_type"].value, "Customer")
		self.assertEqual(row["party"].value, customer.name)

	def test_real_ubi_statement_extracts_one_page_of_transactions_per_pdf_page(self):
		# Real 9-page fixture — proves extract_rows is called once per actual
		# PDF page (not once for the whole document), independent of a real
		# LLM's output: the stub returns a fixed 2 fake rows for any page text.
		results = pymupdf_extractor.extract_document(FIXTURE.read_bytes())
		self.assertEqual(len(results), 9)
		self.assertTrue(all(r["kind"] == "native" for r in results))
		ocr_json = {"pages": [{"lines": r["lines"]} for r in results]}

		class _FixedRowsLLM:
			def extract_fields(self, prompt_text, field_specs):
				return {name: {"value": None, "confidence": 0.0} for name, _erpnext_field, _hint in field_specs}

			def extract_rows(self, prompt_text, field_specs):
				return [
					{name: {"value": "x", "confidence": 0.5} for name, _erpnext_field, _hint in field_specs}
					for _ in range(2)
				]

		dto = build_dto(ocr_json, _FixedRowsLLM())

		self.assertEqual(len(dto.transactions), 9 * 2)
		self.assertEqual({f for f, _, _ in FIELDS}, set(dto.fields))
		self.assertEqual({f for f, _, _ in ROW_FIELDS}, set(dto.transactions[0]))

	def test_amount_wrongly_under_withdrawal_moved_to_deposit_when_balance_rose(self):
		llm = _StubLLM(
			{},
			rows_by_page={
				"page one text": [
					{"balance": {"value": "1000", "confidence": 0.9}},
					# Balance rose by 500 -> must be a deposit, but the LLM put it
					# under withdrawal.
					{
						"balance": {"value": "1500", "confidence": 0.9},
						"withdrawal": {"value": "500", "confidence": 0.6},
					},
				]
			},
		)

		dto = build_dto({"pages": [_TWO_PAGE_OCR_JSON["pages"][0]]}, llm)

		row = dto.transactions[1]
		self.assertEqual(row["deposit"].value, "500")
		self.assertEqual(row["deposit"].confidence, 0.6)
		self.assertIsNone(row["withdrawal"].value)

	def test_amount_wrongly_under_deposit_moved_to_withdrawal_when_balance_fell(self):
		llm = _StubLLM(
			{},
			rows_by_page={
				"page one text": [
					{"balance": {"value": "1500", "confidence": 0.9}},
					# Balance fell by 500 -> must be a withdrawal, but the LLM put
					# it under deposit.
					{
						"balance": {"value": "1000", "confidence": 0.9},
						"deposit": {"value": "500", "confidence": 0.6},
					},
				]
			},
		)

		dto = build_dto({"pages": [_TWO_PAGE_OCR_JSON["pages"][0]]}, llm)

		row = dto.transactions[1]
		self.assertEqual(row["withdrawal"].value, "500")
		self.assertIsNone(row["deposit"].value)

	def test_amount_already_on_correct_side_is_left_untouched(self):
		llm = _StubLLM(
			{},
			rows_by_page={
				"page one text": [
					{"balance": {"value": "1000", "confidence": 0.9}},
					{
						"balance": {"value": "1500", "confidence": 0.9},
						"deposit": {"value": "500", "confidence": 0.95},
					},
				]
			},
		)

		dto = build_dto({"pages": [_TWO_PAGE_OCR_JSON["pages"][0]]}, llm)

		row = dto.transactions[1]
		self.assertEqual(row["deposit"].value, "500")
		self.assertEqual(row["deposit"].confidence, 0.95)
		self.assertIsNone(row["withdrawal"].value)

	def test_row_with_unparseable_balance_is_left_uncorrected_but_chain_continues_past_it(self):
		llm = _StubLLM(
			{},
			rows_by_page={
				"page one text": [
					{"balance": {"value": "1000", "confidence": 0.9}},
					{
						# No balance of its own to diff against -> left alone.
						"balance": {"value": None, "confidence": 0.0},
						"withdrawal": {"value": "500", "confidence": 0.6},
					},
					{
						# Balance rose vs. the last *parseable* balance (1000) ->
						# still correctable even though the row before it had none.
						"balance": {"value": "1500", "confidence": 0.9},
						"withdrawal": {"value": "500", "confidence": 0.6},
					},
				]
			},
		)

		dto = build_dto({"pages": [_TWO_PAGE_OCR_JSON["pages"][0]]}, llm)

		self.assertEqual(dto.transactions[1]["withdrawal"].value, "500")
		self.assertEqual(dto.transactions[2]["deposit"].value, "500")
		self.assertIsNone(dto.transactions[2]["withdrawal"].value)

	def test_row_missing_date_is_forward_filled_from_prior_row(self):
		llm = _StubLLM(
			{},
			rows_by_page={
				"page one text": [
					{"date": {"value": "2026-02-18", "confidence": 0.9}},
					# Same bank statement layout: date printed once per day, this
					# row's own line has no date at all.
					{"date": {"value": None, "confidence": 0.0}},
				]
			},
		)

		dto = build_dto({"pages": [_TWO_PAGE_OCR_JSON["pages"][0]]}, llm)

		self.assertEqual(dto.transactions[1]["date"].value, "2026-02-18")
		self.assertEqual(dto.transactions[1]["date"].confidence, 0.4)

	def test_first_row_missing_date_with_nothing_to_carry_is_left_none(self):
		llm = _StubLLM({}, rows_by_page={"page one text": [{"date": {"value": None, "confidence": 0.0}}]})

		dto = build_dto({"pages": [_TWO_PAGE_OCR_JSON["pages"][0]]}, llm)

		self.assertIsNone(dto.transactions[0]["date"].value)

	def test_row_with_own_date_is_left_untouched(self):
		llm = _StubLLM(
			{},
			rows_by_page={
				"page one text": [
					{"date": {"value": "2026-02-18", "confidence": 0.9}},
					{"date": {"value": "2026-02-19", "confidence": 0.85}},
				]
			},
		)

		dto = build_dto({"pages": [_TWO_PAGE_OCR_JSON["pages"][0]]}, llm)

		self.assertEqual(dto.transactions[1]["date"].value, "2026-02-19")
		self.assertEqual(dto.transactions[1]["date"].confidence, 0.85)

	def test_forward_fill_chains_across_a_page_boundary(self):
		llm = _StubLLM(
			{},
			rows_by_page={
				"page one text": [{"date": {"value": "2026-02-18", "confidence": 0.9}}],
				"page two text": [{"date": {"value": None, "confidence": 0.0}}],
			},
		)

		dto = build_dto(_TWO_PAGE_OCR_JSON, llm)

		self.assertEqual(dto.transactions[1]["date"].value, "2026-02-18")
		self.assertEqual(dto.transactions[1]["date"].confidence, 0.4)

	def test_correction_chains_across_a_page_boundary(self):
		llm = _StubLLM(
			{},
			rows_by_page={
				"page one text": [{"balance": {"value": "1000", "confidence": 0.9}}],
				"page two text": [
					{
						"balance": {"value": "1500", "confidence": 0.9},
						"withdrawal": {"value": "500", "confidence": 0.6},
					}
				],
			},
		)

		dto = build_dto(_TWO_PAGE_OCR_JSON, llm)

		row = dto.transactions[1]
		self.assertEqual(row["deposit"].value, "500")
		self.assertIsNone(row["withdrawal"].value)
