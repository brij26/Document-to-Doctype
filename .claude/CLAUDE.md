# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Reference docs (read as needed, not necessarily every session):
- `docs/ARCHITECTURE.md` — Frappe/ERPNext patterns and the docapture pipeline.
- `docs/DESIGN_PRINCIPLES.md` — SOLID principles applied concretely to this codebase.
- `docs/FEATURE_LIST.md`, `docs/PHASED_DEVELOPMENT.md` — the docapture plan.
- `docs/PHASE_STATUS.md` — **read this first, every session, before any other action.**

## Phase-gate workflow — MANDATORY

Repo follows a strict phase-gate process for the `docapture` app.
`docs/PHASE_STATUS.md` is the live tracker and source of truth for current
phase/status. Rules, no exceptions:

1. **Never auto-start the next phase.** Once a phase's deliverables (per its
   exit criteria in `docs/PHASED_DEVELOPMENT.md`) are done, STOP — no
   scaffolding, stubbing, or "head start" on the next phase — until the user
   explicitly says to proceed ("start Phase 2", "go ahead", "continue").
2. **End-of-phase checkpoint required.** Before stopping: summarize what was
   built/changed (files, doctypes, key logic), run applicable tests/checks
   and report results, set the phase to `Awaiting Review` in
   `docs/PHASE_STATUS.md`, then explicitly ask the user to review this
   phase's code before anything else happens (e.g. "Phase X complete —
   please review before I continue to Phase X+1"). Silence or an unrelated
   message is NOT approval to continue.
3. **Feedback during review** gets fixed within the current phase, not folded
   into the next one — then re-request review.
4. **Only set a phase to `Approved` in `docs/PHASE_STATUS.md` after explicit
   user sign-off** — never before, even if code and tests pass. Set to
   `In Progress` when work begins.
5. **"Plan ahead" / "what's next"** requests are info-only, not permission to
   write next-phase code.

## Design principles — try to follow, pragmatic exceptions allowed

Aim to apply SOLID on every change in this app — see
`docs/DESIGN_PRINCIPLES.md` for the concrete, codebase-specific version of
each principle. In short: keep `docapture/ocr/*` and `docapture/mappers/*`
strictly separated, make new doctype targets or OCR engines addable via new
files rather than edits to existing ones, and prefer draft-creation code that
depends on mapper-output DTOs rather than building doctype fields inline.

This is a strong default, not an absolute rule. If breaking a principle is the
right call, do it — just say explicitly which principle is being bent and why,
in the phase checkpoint summary, so the user can weigh in during review. Don't
silently take a shortcut, and don't force an elaborate abstraction just to
technically satisfy SOLID on something trivial.

## What this repo is

A Frappe bench (`bench` CLI, v5.31.0) — workspace root with multiple apps and
sites, not a single-app repo.

- `apps/frappe` — the framework (metadata-driven, Python >=3.14); everything
  else depends on it.
- `apps/erpnext` — ERPNext, built on Frappe (`frappe>=16.0.0-dev,<17.0.0`).
- `sites/erpnext.yoursite.in` — the configured site (`frappe` + `erpnext`
  installed). DB is MariaDB.
- `apps/docapture` — the app being built (see docs). Does not exist until
  Phase 0 scaffolds it.

## Hard constraints

- **Use bench's own virtualenv.** No `uv`, no ad-hoc `.venv`. Install Python
  deps through bench (`bench pip install` / `apps/docapture/pyproject.toml`).
- **Dependencies go in `apps/docapture/pyproject.toml`** (and mirrored to
  `requirements.txt` if the app needs it), never installed loosely.
- **Site commands always take `--site erpnext.yoursite.in`.**
- **DB is MariaDB** — no Postgres-only SQL.

## Common commands

Run from this directory (the bench root) unless noted.

```bash
# Start all bench processes (web, socketio, worker, scheduler, redis) per Procfile
bench start

# Site-specific admin commands always take --site
bench --site erpnext.yoursite.in migrate
bench --site erpnext.yoursite.in console
bench --site erpnext.yoursite.in backup

# Create the app (Phase 0) and install it
bench new-app docapture
bench --site erpnext.yoursite.in install-app docapture

# Run tests for the app
bench --site erpnext.yoursite.in run-tests --app docapture

# Run a single test module
bench --site erpnext.yoursite.in run-tests --module <dotted.module.path>

# Build JS/CSS assets after frontend changes
bench build

# Lint (per-app, ruff)
cd apps/docapture && ruff check .
```

Linting and test config live per-app (`apps/<app>/pyproject.toml`), not at the
bench root.
