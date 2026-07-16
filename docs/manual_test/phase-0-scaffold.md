# Manual Test — Phase 0: Scaffold

**Status:** Approved
**Goal:** a real, installable `docapture` app on the site.

## Prerequisites
- Bench running (`bench start` or equivalent), site `erpnext.yoursite.in` reachable.

## Manual test steps

- [ ] Run `bench --site erpnext.yoursite.in migrate` → completes with no errors.
- [ ] Confirm `docapture` is installed: `bench --site erpnext.yoursite.in list-apps`
      (or Desk → Settings → Installed Applications) shows `docapture` in the list.
- [ ] Run `bench --site erpnext.yoursite.in run-tests --app docapture` → passes
      (an empty suite passing is fine at this phase).
- [ ] Open `bench --site erpnext.yoursite.in console` and import each declared
      dependency, confirm no `ImportError`:
  ```python
  import pymupdf, paddleocr, pytesseract, cv2, PIL, rapidfuzz
  ```

## Expected result
Site boots, app is installed, migrate/tests/lint are all clean, and every
declared OCR/image dependency imports without error inside bench's venv.

## Out of scope
No doctypes, no OCR, no pipeline code exist yet — nothing to test beyond
install/migrate/import.
