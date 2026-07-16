---
name: docapture-phase-gate
description: Use when starting or finishing a docapture development phase — enforces the mandatory phase-gate ritual (set status, run checks, checkpoint, stop for review). Trigger when about to begin a phase's work, or when a phase's deliverables look done and you're tempted to continue.
---

# docapture Phase Gate

The phase-gate workflow is mandatory (see `.claude/CLAUDE.md`). This skill encodes
the ritual so it runs the same way every time. `docs/PHASE_STATUS.md` is the source
of truth; `docs/PHASED_DEVELOPMENT.md` defines each phase.

Turn the relevant checklist below into todos and follow it exactly.

## Starting a phase

1. Read that phase's **Goal / Scope / Exit criteria / Excluded** in
   `docs/PHASED_DEVELOPMENT.md`.
2. Set the phase to `In Progress` in `docs/PHASE_STATUS.md` (table row + Current
   focus + Log line).
3. Stay inside this phase's scope. Do **not** scaffold, stub, or "head start" any
   later phase — that is an explicit CLAUDE.md violation.

## Finishing a phase — checkpoint (do NOT skip, do NOT auto-advance)

1. **Summarize** what was built/changed: files, doctypes, key logic.
2. **Run the checks** and report the real output (never claim pass without running):
   - `bench --site erpnext.yoursite.in run-tests --app docapture`
   - `cd apps/docapture && ruff check .`
3. **Confirm exit criteria** for this phase are met (per `docs/PHASED_DEVELOPMENT.md`).
   Note any bent design principle — which one and why — per `docs/DESIGN_PRINCIPLES.md`,
   so the user can weigh in during review.
4. Set the phase to `Awaiting Review` in `docs/PHASE_STATUS.md`.
5. **Explicitly ask the user to review**, e.g. "Phase X complete — please review
   before I continue to Phase X+1." Then **STOP**.

## Hard rules

- Silence or an unrelated message is **not** approval to continue.
- Only the **user** sets a phase to `Approved` in `docs/PHASE_STATUS.md`, after
  explicit sign-off — never before, even if code and tests pass.
- Review feedback is fixed **within the current phase**, then re-request review —
  never folded into the next phase.
- "Plan ahead" / "what's next" is info-only, not permission to write next-phase code.
