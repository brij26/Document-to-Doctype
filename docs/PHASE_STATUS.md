# docapture — Phase Status

**Read this first, every session, before any other action.**

Source of truth for the current phase and status. Update it at every phase
transition. Status values: `Not Started` · `In Progress` · `Awaiting Review` ·
`Approved`.

Only set a phase to `Approved` after **explicit user sign-off** (see `CLAUDE.md`).

| Phase | Title | Status |
|---|---|---|
| 0 | Scaffold | Approved |
| 1 | Capture doctype + upload + status | Approved |
| 2 | OCR layer (`ocr/*`) | Not Started |
| 3 | Mapper / LLM layer (`mappers/*`) | Not Started |
| 4 | Review queue + draft creation | Not Started |
| 5+ | Future (Should / Nice-to-Have) | Not Started |

---

## Current focus

**Phase 1 — Approved.** Next: Phase 2 (OCR layer), starts only when user
says go.

## Log

- Planning complete; awaiting user go-ahead to start Phase 0.
- 2026-07-14: user said go. Phase 0 started.
- 2026-07-14: `docapture` app scaffolded, installed on `erpnext.yoursite.in`,
  deps declared and installed via bench venv, migrate clean, empty
  `run-tests` passes, `ruff check` clean. Phase 0 → Awaiting Review.
- 2026-07-14: user approved. Phase 0 → Approved.
- 2026-07-14: user said start Phase 1. Phase 1 started.
- 2026-07-14: Phase 1 built — `Captured Document` + `Capture Alias` doctypes,
  `Docapture Uploader`/`Docapture Reviewer` roles, content_hash dedup check,
  status walk + duplicate tests. `migrate`, `run-tests --app docapture`, and
  `ruff check` all clean. Phase 1 → Awaiting Review.
- 2026-07-14: review feedback — `content_hash` dedup check was blocking a
  re-upload of an identical file forever, even after the original capture was
  `Rejected`/`Failed`. Fixed: dedup check now excludes those two terminal
  states, so a re-upload after rejection reruns the chain instead of staying
  blocked. Added `test_reupload_allowed_after_rejection`; `run-tests` (3/3)
  and `ruff check` still clean. Also documented (docs-only, no code): job
  chaining/`enqueue_after_commit`/queue-split notes on Phase 2, and the
  blocked-duplicate outcome state on Phase 4.
- 2026-07-14: user approved. Phase 1 → Approved.
