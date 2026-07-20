# Review UX: editable extracted-fields (Phase 4 follow-up)

**Superseded 2026-07-20.** This document originally designed a persisted
child doctype (`Docapture Extracted Field`) rendered as a native Table grid
directly on the `Captured Document` form, with `extracted_json` staying an
immutable audit record. That design was **not built**. When the reviewer
correction problem came up again (via a real bug report — see below), the
user was asked explicitly whether to follow this document's design or a
different one, and chose the different one. The as-built design is
documented in `docs/PHASE_STATUS.md`'s 2026-07-20 log entry; the summary
below is kept for context on what changed and why, not as a spec to build
from.

## What actually shipped instead

- **No new doctype.** `docapture/review.py`'s `to_preview()`/
  `apply_corrections()` are pure functions that normalize/patch the parsed
  `extracted_json` dict directly — the same DTO shape every creator already
  reads (`docapture/mappers/schema.py`'s `to_json()` output).
- **`extracted_json` is directly editable**, not immutable — a saved
  correction overwrites it in place (`router.save_corrections()`,
  `doc.db_set("extracted_json", ...)`). A changed field's confidence is
  bumped to `1.0` and its `mapped_docname` (alias-resolved link) is dropped,
  matching this document's original reasoning on that specific point.
- **A separate "Preview" button + `frappe.ui.Dialog`**, not an always-visible
  grid on the form. Flat fields (Payment Receipt) render as native Dialog
  inputs; row-based DTOs (Journal Entry rows, Bank Statement transactions)
  render as a hand-built HTML `<table>` of `<input>`s inside an `HTML`-type
  Dialog field, since there was no existing Table-fieldtype/Dialog precedent
  in this app to build on and a new persisted child doctype for an ephemeral
  preview wasn't judged worth it.
- **Why the direction changed:** the trigger this time was a real bug
  (`payment_entry_creator.py` silently defaulting a missing `paid_amount` to
  `0`, surfacing as an unhelpful ERPNext "Paid Amount is mandatory" error),
  discussed and scoped independently of this document. By the time the
  review/correction UX came up again as part of that fix, the user chose the
  Dialog-based approach over this document's grid-based one.

## Still true, carried over from this document

- The real independent bug noted here — `journal_entry_creator.py`'s
  `_append_mapped_row` uses the row's raw OCR `account` text directly
  instead of `alias_docname(...)`, ignoring Capture Alias resolution even
  when a hit exists — **was not fixed** by the 2026-07-20 work (explicitly
  out of scope there, flagged as a separate small fix). Still open.
