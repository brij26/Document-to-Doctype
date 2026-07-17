# Competitive gap roadmap — vs. aiaccountant.com

Scope: bank statement, supplier bill, expense voucher, payment receipt only —
the four `source_type`s docapture actually targets. GST/tax reconciliation and
Tally-connector parity are explicitly out of scope (we're ERPNext-native, not
building GST).

Audited 2026-07-17 against [aiaccountant.com](https://www.aiaccountant.com/)
(a Tally-integrated AI accounting product) — verified by fetching their site
and blog for actual workflow claims, and by reading docapture's code directly
(not just docs) to confirm every gap below with file:line evidence.

## Competitor workflow (bank statement / bill scope only)

- **Bank/credit card statements**: bulk upload (PDF/Excel/image) → OCR →
  automatic ledger prediction per transaction → matched to existing
  ledgers/vendor bills (e.g. "UPI-483 · Office rent → Rent Ledger",
  "NEFT-921 · Acme Supplies → Bill #1042") → maker-checker approval → pushed
  to Tally as vouchers.
- **Vendor bills**: OCR (claims 95% accuracy on handwritten bills) →
  automatic line-item mapping → matched/associated with existing
  bills/invoices → approval → push to Tally.
- Sync back to Tally is incremental (`AlterID`/`LastAlterID`) and
  bidirectional — corrections made in Tally are read back, not just written.
- Conflict handling: voucher locks, edits-after-sync, and duplicates are
  explicitly handled; idempotency keys prevent duplicate writebacks on retry.
- No confidence-score thresholds or auto-post-without-review disclosed —
  everything appears to gate through maker-checker, same posture docapture's
  own docs already commit to.

Not independently verifiable (marketing copy, no published technical spec):
the 95% OCR figure, exact matching algorithm internals, real-world
reliability of the connector.

## docapture today (verified in code)

Pipeline for all four source types: Desk upload (`Captured Document`, one
file at a time, System Users only) → OCR (PyMuPDF native text, else
PaddleOCR PP-OCRv6 with Tesseract fallback) → LLM extraction (OpenAI GPT-4.1
active, Claude available as swap) into a typed DTO → alias resolution →
**status = "In Review" → pipeline stops.**

Phases 0–2 (scaffold, capture doctype, OCR) are Approved. Phase 3 (LLM
mapper layer) is Awaiting Review, real-fixture tested (76/76 tests),
including a live-verified extraction of a real 189-row bank statement PDF.
Extraction itself is genuinely solid — comparable in spirit to the
competitor's OCR+mapping step.

## Strict gap list

1. **Nothing ever gets posted — the headline gap.** Phase 4 (router → draft
   creation → approve/reject → post) is "Not Started" per
   `PHASED_DEVELOPMENT.md`. No code creates a Payment Entry or Journal Entry
   for any of the four source types, ever. The DTO already carries
   `target_doctype` (`mappers/schema.py`) and nothing consumes it.
   Competitor's loop closes (document in → posted Tally voucher out); ours
   stops at "JSON a human can read."
2. **No approve/reject action, no maker-checker.** A reviewer today can
   only hand-edit doctype fields; there's no whitelisted approve/reject
   method. Competitor gates every posting through this exact step — same
   posture, but only they actually built the gate.
3. **Bank statement → many entries isn't even scoped for the next phase.**
   `PHASED_DEVELOPMENT.md` line 169 explicitly defers "Bank-statement
   multi-line splitting (one statement → many Payment Entries)" to Phase
   5+, while Phase 4's exit criteria only cover single-draft creation. So
   even once Phase 4 ships, a 189-row bank statement extraction still won't
   produce 189 postable entries. Sharpest contrast with the competitor,
   whose core pitch is per-transaction auto ledger prediction on exactly
   this document type.
4. **Bank statement counterparty resolution ignores transaction
   direction.** `mappers/bank_statement_mapper.py:64-71` tries
   Customer-then-Supplier in a fixed order regardless of deposit vs.
   withdrawal — unlike ERPNext's own `auto_match_party.py`. Competitor's
   "automatic ledger prediction" is necessarily direction-aware.
5. **No dedup-at-posting.** Only `content_hash` (exact file re-upload)
   dedup exists (`captured_document.py`). Business-key dedup
   (party+amount+date+reference) is spec'd for Phase 4 but not built.
   Competitor handles this with idempotency keys on writeback.
6. **Multi-company alias resolution is silently broken.**
   `mappers/alias_resolver.py` ignores the `company` field entirely by its
   own admission (`ponytail:` comment): "a normalized_value that's
   ambiguous across companies just resolves to one of them." Competitor
   explicitly supports multi-company.
7. **Journal Entry is hardcoded to exactly 2 rows**
   (`mappers/journal_entry_mapper.py:15-18`), the target for Supplier Bill
   and Expense Voucher. Any bill needing a 3rd leg (TDS, rounding, split
   cost center) is unrepresentable. Competitor's line-item mapping implies
   arbitrary line counts.
8. **No line-item support for supplier bills at all.** Bills book as a flat
   2-row JE-to-Creditors — no item table, no per-line amount/account.
   Materially richer extraction target than what we do today.
9. **No dedicated matching-to-existing-record step.** Competitor's core
   pitch for bank statements is matching each transaction against existing
   bills/ledgers — reconciliation, not just classification. `alias_resolver`
   only resolves party/account names to master records; it never looks for
   an existing open bill/invoice to settle a transaction against.
10. **No failure alerting.** Pipeline errors go to `frappe.log_error` only —
    invisible unless someone's watching the Error Log. Competitor has
    email/Slack alerts on failures and stale imports.
11. **No bulk upload.** One file per `Captured Document`, Desk-only, System
    Users. Competitor bulk-uploads statements and bills.
12. **Incomplete LLM key wiring** — `OpenAIParser()` reads a bare env var,
    no `bench set-config` path. Will bite in any fresh environment before
    anything above can even be tested live.
13. **Classifier calibrated on only 5 documents total** (`classifier.py`,
    self-flagged in-code). Fine for now, not a production robustness claim.

## Roadmap (priority order, GST/Tally out of scope)

### Tier 0 — ship Phase 4 exactly as already spec'd
Closes #1, #2, #5, #6, #12.

- `docapture/router/` reading `target_doctype` off the DTO;
  `creators/payment_entry_creator.py`, `creators/journal_entry_creator.py`
  (DTO → `docstatus=0` draft) — scoped to single-draft Payment
  Entry/Journal Entry only, per the existing spec.
- Dedup-at-posting (business-key collision → `Rejected` + `error_log`,
  never auto-merge/delete).
- Review queue + approve/reject action, reusing the existing `Docapture
  Uploader`/`Docapture Reviewer` roles.
- Fix multi-company alias resolution inline here — Phase 4 is exactly when
  a document's `company` first resolves onto a draft, so thread it through
  `alias_resolver.resolve()` at this point rather than separately.
- Wire `OpenAIParser` to `frappe.conf` with env-var fallback — trivial, but
  blocks reliable end-to-end testing of everything else.
- Add failure notifications (Frappe `Notification` doctype or one-line
  `frappe.sendmail` in each pipeline's `except`) — cheap, do alongside
  Phase 4.

### Tier 1 — close the sharpest contrast with the competitor's actual product
Closes #3, #4, #7, #8.

- Decide and schedule bank-statement multi-row splitting (one statement →
  many Journal/Payment Entries) as a real, dated phase rather than an
  open-ended "Phase 5+" — the single feature most directly comparable to
  the competitor's headline capability, and today it isn't even scheduled.
- Fix bank statement counterparty resolution to use transaction direction
  (deposit vs. withdrawal), mirroring ERPNext's own `auto_match_party.py`
  logic instead of a fixed try-order.
- Variable-length Journal Entry rows (`JournalEntryDTO.rows` is already
  `list[dict]` in `schema.py` — only the mapper's flattened
  `row1_*/row2_*` convention is fixed; can likely reuse
  `LLMParser.extract_rows` already built for bank statements).
- Line-item extraction for supplier bills, once row-count is no longer
  fixed at 2 — this is what makes bill handling comparable to the
  competitor's "automatic line-item mapping," independent of any Purchase
  Invoice doctype decision.

### Tier 2 — reconciliation-to-existing-records
Closes #9, after Tier 0/1.

- Add a "match against open Supplier Bill / Sales Invoice / outstanding
  entry" step before draft creation for bank statements and payment
  receipts, rather than only resolving master-data names. This is what
  actually makes the product function like a reconciliation tool instead
  of a classifier — currently the single largest capability gap versus
  what the competitor demonstrably does for this exact document type.

### Tier 3 — quality-of-life, lower urgency
Closes #10, #11, #13.

- Failure alerting can also fold into Tier 0 above; if deferred, do it
  before Tier 1 ships since Tier 1 adds more pipeline surface that can
  fail silently.
- Bulk upload — operational, not blocking correctness.
- Expand classifier calibration set as real documents flow through Phase 4
  in practice.

## Verification

- After Tier 0 lands: `bench --site erpnext.yoursite.in run-tests --app
  docapture` (existing suite 76/76 today, must stay green) plus new tests
  for router/creators/dedup, following the existing test-file pattern
  (`test_captured_document.py`, `test_pipeline.py`).
- Manual Desk walkthrough end-to-end (upload → OCR → mapper → review →
  approve → posted PE/JE) for all four source types — `PHASE_STATUS.md`
  already flags this as never having been done even for Phase 3; do it for
  real once Tier 0 closes the loop, using the existing bank-statement and
  supplier-bill fixtures in `tests/fixtures/`.
- For the multi-company fix: create two `Company` records with a colliding
  vendor alias, confirm resolution no longer picks one arbitrarily.
- For counterparty direction fix: run the existing UBI bank-statement
  fixture and confirm deposit rows resolve against Customer records and
  withdrawal rows against Supplier records where ambiguous, instead of a
  fixed try-order.
