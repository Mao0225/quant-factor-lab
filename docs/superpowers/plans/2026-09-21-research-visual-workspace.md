# Readable research workspace Implementation Plan

**Goal:** Let the user understand research progress, backtests and validation without reading JSON or opaque identifiers.

**Architecture:** Preserve the approved blue/white visual design and immutable research evidence. Add read-only semantic indexing of existing artifacts and modular presentation helpers. Do not retrain, access unrun T, alter rewards or change frozen kernel/scorer identities. Existing user authorization covers this presentation redesign and independent agents; no repeated scope approval.

**Tech Stack:** Existing FastAPI service, vanilla JavaScript, accessible SVG and existing CSS.

## Design and choices

Renaming identifiers alone cannot explain records; expanding JSON into generic tables still exposes implementation details. Use purpose-led summaries, charts and drill-down tables instead. Advanced evidence remains collapsed for traceability.

- Run page: batch progress, candidates and accepted changes, reward trajectory, plain-language candidate outcomes and PPO update summary. Distinguish candidate reward from E pool adoption and skipped PPO updates from real updates.
- Backtest page: open frozen T if already run, otherwise selected V, otherwise adopted E. Label records by purpose, batch and candidate, never by hash alone. Default to adopted/frozen outcomes; filter candidate comparisons and low-level F search details separately. Show dated equity/drawdown charts, metrics, monthly returns, readable holdings/orders/trades and factor weights.
- Validation page: chronological F/E/V/T usage, checkpoint objective comparison with chosen batch, clear selection reason, actual T metrics and decision limits. Unrun partitions show an honest empty state. T navigation reads existing evidence only.
- Configuration and model views: expose useful rules, fees, date ranges and weights in readable form; identifiers stay in advanced evidence.

## Tasks

- [x] Backend agent: enrich existing artifact catalogue with references/roles/labels from committed batch and selection/test evidence; add meaningful tests for shared artifacts, unrun T and missing records.
- [x] Process UI agent: implement run and validation renderers as independent static module with focused evidence tests.
- [x] Root: shared chart primitives, backtest explorer and daily trading tables, loading/selection handling, CSS and app integration.
- [x] Root: configuration/model display polish and compact advanced-only evidence.
- [x] Run API and JS checks; restart app only when no jobs run; browser-test real completed charts, semantic record selection, daily ledger, candidate drill-down and validation links; automated tests cover missing/unrun evidence. Inspect responsive CSS; no device viewport override used.
- [x] Update usage notes and report exactly what changed and any remaining limitations.

## Acceptance

No expanded JSON or bare hashes in normal research views. Every artifact option answers what it represents, for which batch/candidate and which period. Metrics/charts match stored evidence; no fabricated benchmark or claim that PPO training proves improvement. Model selection uses the registered V rule, never latest-batch assumption. Old experiments and calculations remain unchanged.

## Verification, 2026-09-21

- Backend catalogue/API: 8 tests passed. Four focused JavaScript suites passed, including compounding, zero/missing distinction, escaped labels, shared references, selected-checkpoint ties and candidate-use versus formal-adoption semantics. App script syntax passed.
- Real six-experiment render smoke checks completed. Browser checked the PPO seed 7 run: 24 candidates, 4 actual PPO updates, 3 combination changes; validation selects batch 3 over equal-scoring batch 4. Its default outcome list exposes 7 readable results instead of 224 opaque identifiers.
- Browser checked NAV, drawdown and monthly charts; daily order explanations; candidate-purpose filtering; expanded candidate quality and weight details; and batch 1 validation-to-backtest navigation. No browser console errors recorded.
- Kernel identity remains `d09ed3e0407bf2f64e51d5fc3241c5a6fbdead13bad5bafd49196d948419912b`; scorer remains `36c91e4f7dc82a14b7e2c9902d81cc8874300323b4faa16b3fb7b40f2c9756df`.
- Added `closed_loop_research/docs/研究可视化使用说明.md`; updated README and both manual formats. Historical evidence and model statuses were not changed. Responsive breakpoints are present but separate device-size browser validation was not performed.
