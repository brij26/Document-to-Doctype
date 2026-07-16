# Manual Test — Phase 4: Review queue + draft creation

**Status:** Not Started — this is a forward-looking checklist, to be executed
once the phase is built and moved to `Awaiting Review`.

**Goal:** a human approves a capture and the correct draft appears, linked
and dedup-checked.

## Prerequisites
- Phase 3 complete: captures reaching `In Review` with populated
  `extracted_json`.
- At least two ERPNext companies with different currencies configured, for
  the multi-company/currency check.
- A `Docapture Reviewer` user.

## Manual test steps

### Review queue
- [ ] Open the review queue list view → confirms it shows only captures with
      status `In Review` (nothing `Uploaded`, `OCR Done`, `Parsed`,
      `Approved`, `Posted`, `Rejected`, or `Failed`).
- [ ] As reviewer, open a capture with an unresolved field (from Phase 3's
      alias-miss case) → confirm you can fix the field and confirm the alias,
      and that this writes a new `Capture Alias` row.

### Approve → draft creation
- [ ] Approve a `Payment Receipt`/`Payment Entry`-target capture → a
      `Payment Entry` draft (`docstatus = 0`) is created.
- [ ] Approve a `Bank Statement`/`Journal Entry`-target capture → a
      `Journal Entry` draft (`docstatus = 0`) is created.
- [ ] On the approved `Captured Document`, confirm `target_doctype` and
      `target_docname` link back to the created draft, and status is now
      `Approved` (then `Posted` once the draft itself is submitted, if that
      transition is wired here).

### Reject
- [ ] Reject a capture from the review queue → confirm no draft is created.

### Dedup check
- [ ] Approve a capture, then create/approve a second capture with the same
      business key (same `content_hash`, or same party + amount + date +
      reference) → the second is blocked from creating a draft. Confirm:
  - [ ] the original draft is untouched (not modified or deleted),
  - [ ] the blocked capture lands in a distinct status (not silently merged
        into the first) with `error_log` naming the colliding
        `target_doctype`/`target_docname`,
  - [ ] a human can override this (e.g. confirm it's a genuine second
        transaction) rather than being permanently stuck.

### Multi-company / multi-currency
- [ ] Approve a capture against Company A (currency X) → draft's company and
      currency fields match.
- [ ] Approve a capture against Company B (currency Y) → draft's company and
      currency fields match, independently of the first.

### Trust guarantee
- [ ] Confirm there is no path in this phase where a draft gets created or a
      document gets posted without an explicit human approval step — no
      auto-post, no auto-draft.

## Expected result
Only `In Review` captures appear in the queue; approving creates the correct
linked draft respecting company/currency; rejecting creates nothing;
duplicates are blocked without touching the original draft and without
silent auto-resolution; everything routes through manual review.

## Out of scope
No auto-draft confidence thresholds, no Purchase Invoice target, no line
items, no three-way matching (all Future/5+).
