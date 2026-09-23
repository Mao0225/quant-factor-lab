# Workbench UX Implementation Plan

> Execute in this session using the subagent-driven-development workflow for independent helper work and review. The user has approved implementation. This directory is not a Git checkout; do not create a repository or commit unrelated files.

**Goal:** Group the existing research functionality into coherent modules with persistent drafts, local task feedback and local results.

**Architecture:** Keep the Python 3.8 / Streamlit 1.40 runtime and existing backend. Extract reusable read/render helpers, add pure state/data adapters, and dispatch only the selected page. Keep explicit widget keys separate from persistent draft storage.

**Tech Stack:** Python, Streamlit, pandas, existing filesystem jobs and result manifests.

## Task 1 — State and data adapters

Files: create `app/workbench_state.py`, `tests/test_workbench_state.py`.

- [x] Add and run failing tests for independent draft values, valid selected IDs, deduplicated jobs across roots, malformed metadata tolerance, scoped job lookup, and copying manual history without mutation.
- [x] Implement pure helpers; no Streamlit dependency. Keep public signatures documented for page integration.
- [x] Run `F:\anaconda3\envs\alphagen\python.exe -m pytest tests/test_workbench_state.py -q` and review adapter behavior.

## Task 2 — Page shell and shared components

Files: modify `app/streamlit_app.py`; create `app/workbench.py`, `app/workbench_components.py`.

- [x] Preserve existing tested helper functions, move top-level UI into selected-page dispatch, and keep helper import free of UI execution.
- [x] Add AppTest coverage for module navigation, input persistence, parameter isolation and data source consistency; run before implementation.
- [x] Implement sidebar navigation, explicit settings, per-module drafts, local backtest form and common result history/detail display.
- [x] Reorder result detail: metrics and charts first, metadata last; use existing outputs without copying data.

## Task 3 — Business pages

Files: create `app/workbench_manual.py`, `app/workbench_research.py`, `app/workbench_data.py`.

- [x] Manual: expression help, existing-parser preflight, pool/data validation, submit, scoped progress, local history and rerun from saved configuration.
- [x] PPO: batch list, new generation form, batch-bound backtest configuration, local results and composition handoff.
- [x] Composition: experiment list, grouped parameters preserving all existing thresholds, progress and local result detail.
- [x] Data: overview, pool list/create, consistent field/stock source, import form with existing overwrite semantics.
- [x] Task center: merge configured and legacy roots, status filters, source links; refresh fragments without resetting inputs.

## Task 4 — Verification and handoff

Files: update `tests/test_streamlit_app.py`, `tests/test_workbench_ui.py`, `README.md` and this checklist.

- [x] Update obsolete source-location assertions to inspect extracted files, preserving behavioral assertions.
- [x] Run targeted UI/helper tests, then existing backend regression suite under the compatible environment.
- [x] Start the app using `app/run_streamlit.py`; inspect actual module pages in the in-app browser. Verify primary flow using small temporary fixtures, never full production jobs.
- [x] Request independent spec and quality review, resolve actionable findings, re-run affected checks.
- [x] Document startup and navigation; record verification results and any remaining limits.


## Verification record — 2026-09-17

- Full suite in alphagen Python 3.8.20 / Streamlit 1.40.1: **172 passed in 35.21s**.
- After final result-list formatting and task-origin linking: **54 UI/helper tests passed in 5.04s**.
- Browser verified real manual workspace, PPO batch list and batch-bound backtest, and composition configuration. Screenshot: `../../assets/workbench-20260917/ppo-backtest.png`.
- Backend experiment history: 24 targeted tests independently passed and reviewer approved.
- Independent UX review findings resolved: complete historical config snapshots, flat factor result config, exact task output targeting, failed-factor reporting, experiment grouping and legacy grouping fallback.
- Existing Python 3.8 annotation import failures fixed with postponed annotations in eight first-party single_factor modules. No algorithm changes.
- File-only chart export now uses matplotlib Figure directly, avoiding background Tk windows and missing Tk errors.
- Existing AI relative-root failure on Windows/Python 3.8 fixed by making the path absolute before resolve.
- Added pytest 8.3.5 test dependency to the local alphagen environment; numerical dependencies unchanged.
- Production datasets were read for visual checks; no new production PPO training, cache import, or batch backtest was submitted. Functional submissions use temporary fixtures; no full-scale performance claim.
- Existing CLI calls without experiment_id retain their old output paths. The UI opts into independent run history.
- Preview remains available on port 8502. No Git repository was present, so no commit or merge was performed.
