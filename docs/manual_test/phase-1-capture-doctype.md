# Manual Test — Phase 1: Capture doctype + upload + status

**Status:** Approved
**Goal:** capture a document and move it through its lifecycle by hand (no OCR yet).

## Prerequisites
- A user with the `Docapture Uploader` role and a separate user with
  `Docapture Reviewer` (or a System Manager to check permission rules directly).
- Any small test file to attach (PDF or image).

## Manual test steps

### Captured Document lifecycle
- [ ] As the uploader, create a new `Captured Document`, attach a file.
- [ ] Confirm `content_hash` gets computed/populated on save.
- [ ] Manually set `status` through each value in order and confirm the field
      accepts it: `Uploaded → OCR Done → Parsed → In Review → Approved → Posted`.
- [ ] Separately, on a fresh capture, set `status` to `Rejected` — accepted.
- [ ] Separately, on another fresh capture, set `status` to `Failed` — accepted.

### Duplicate detection
- [ ] Upload the same file a second time (new `Captured Document`, identical
      content) while the first is still active (e.g. `Uploaded`) → duplicate is
      detected/blocked.
- [ ] Take a capture whose status is `Rejected`, re-upload the same file again
      → this time it is **allowed** (not blocked), per the 2026-07-14 fix.
- [ ] Repeat the same check starting from a `Failed` capture → re-upload allowed.

### Capture Alias (seam only)
- [ ] Confirm the `Capture Alias` doctype exists and can be opened from Desk.
- [ ] Create two `Capture Alias` rows with the same key value → the unique
      constraint blocks the second one.
- [ ] Confirm there is no auto-resolution behavior yet — creating a
      `Capture Alias` row has no side effect on any `Captured Document`.

### Roles
- [ ] As `Docapture Uploader`, confirm you can create/upload a `Captured Document`
      but permissions differ from a reviewer's (e.g. no approve/reject rights,
      per whatever the role definition grants).
- [ ] As `Docapture Reviewer`, confirm you have the reviewer-level access
      (e.g. can change status toward `Approved`/`Rejected`).

## Expected result
Full status lifecycle is settable by hand, duplicate uploads are blocked
except after a terminal `Rejected`/`Failed` state, `Capture Alias` behaves as
a schema-only doctype, and the two roles have distinct permissions.

## Out of scope
No OCR runs, no LLM parsing, no alias auto-resolution, no draft creation —
none of that exists yet.
