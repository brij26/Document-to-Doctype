# Manual Test — Phase 3: Mapper / LLM layer (`docapture/mappers/*`)

**Status:** Not Started — this is a forward-looking checklist, to be executed
once the phase is built and moved to `Awaiting Review`.

**Goal:** turn OCR JSON into a structured DTO with confidence, and resolve
known entities automatically.

## Prerequisites
- Phase 2 complete: captures reaching `OCR Done` with valid `raw_ocr_json`.
- At least one `Capture Alias` row seeded ahead of time with a known value
  (e.g. a supplier name) for the auto-map check below.

## Manual test steps

### Classification
- [ ] Take a capture whose source is clearly a payment receipt → after the
      mapper job runs, confirm `source_type`/classification result matches.
- [ ] Repeat for a bank statement, a supplier bill, and an expense voucher
      fixture → each classified correctly.

### Mapping + confidence
- [ ] Confirm `extracted_json` is populated with a structured DTO (not raw
      OCR text) after the mapper runs.
- [ ] Confirm `confidence` is populated, both an overall score and per-field
      scores are visible somewhere in `extracted_json`.
- [ ] Confirm status moves `OCR Done → Parsed → In Review`.

### Alias resolution
- [ ] Run a document whose extracted party/reference value matches the
      pre-seeded `Capture Alias` row → confirm it auto-maps with no manual
      prompt needed (visible in `extracted_json` or a resolved field).
- [ ] Run a document with a value that has **no** matching alias → confirm it
      is left unresolved (flagged for review), not silently guessed or
      dropped.

## Expected result
Every fixture source type classifies correctly, `extracted_json` +
`confidence` are populated, known aliases auto-resolve, unknown ones are
left for a human, and status correctly lands on `In Review`.

## Out of scope
No review UI, no draft creation (Phase 4). No fuzzy alias matching (Future/5+).
