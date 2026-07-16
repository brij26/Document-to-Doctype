# docapture — Design Principles

SOLID, made concrete for this codebase. This is the strong default. Bending a
principle is allowed when it's genuinely the right call — but say so, and say why,
in the phase checkpoint (see `CLAUDE.md`), never silently.

The one non-negotiable: **`ocr/`, `mappers/`, and `creators/` stay separated, and
they communicate through plain data (a DTO), not through each other's internals.**

---

## S — Single Responsibility

Each layer does exactly one thing:
- `docapture/ocr/*` — bytes → normalized text/blocks. Nothing about accounting.
- `docapture/mappers/*` — text → structured DTO + confidence. Nothing about how to OCR.
- `docapture/creators/*` — DTO → `docstatus=0` draft. Nothing about extraction.

Smell test: if an OCR file imports a doctype, or a creator parses OCR text, the
responsibility has leaked. A file growing large usually means it took on a second job.

## O — Open/Closed

Adding an OCR engine, a source type, or a target doctype is a **new file plus a
registry entry**, not an edit to existing logic.
- New OCR engine → new class implementing `OCREngine`; register it.
- New target (e.g. Purchase Invoice) → new mapper + new creator + one router
  registry entry. The router itself does not change.

If adding a target forces edits to a big `if source_type == ...` block, the
abstraction is wrong — fix the seam, don't grow the block.

## L — Liskov Substitution

Any `OCREngine` is interchangeable behind the protocol; any `LLMParser` is
interchangeable behind its protocol; any creator accepts the same DTO shape. The
router must not care which concrete engine, parser, or creator it holds.

## I — Interface Segregation

Keep the protocols thin and honest:
- `OCREngine.extract(bytes) -> ocr_json`
- `LLMParser.parse(ocr_json, source_type) -> dto`
- `Creator.create(dto) -> doc`

No fat "do everything" base class. A consumer should depend only on the method it
actually calls.

## D — Dependency Inversion

**Draft creation depends on the DTO, not on OCR/LLM internals.** Creators receive a
plain, validated data structure and build the doctype from it. They never reach back
into `raw_ocr_json` or call an LLM. This is what lets us swap the OCR engine or the
LLM vendor without touching a single creator.

---

## The DTO is the contract

The structured DTO produced by the mapper layer is the seam that holds the whole
design together. It carries the fields, per-field confidence, and resolved
record links. Everything upstream produces it; everything downstream consumes it.
Keep it explicit and versionable — a sloppy DTO quietly recouples the layers.

---

## Pragmatic exceptions

Don't build an interface for a thing with exactly one implementation and no second
one on the horizon — that's over-engineering, and YAGNI wins. The OCR-engine and
target-doctype seams earn their abstraction because a second implementation is
*planned* (Tesseract fallback; Purchase Invoice target). A one-off helper does not.

When you do bend a principle, name it in the checkpoint: *"Bending Open/Closed here
because X; upgrade path is Y."* That way the user reviews the tradeoff instead of
discovering it later.
