# Stock Selection Implementation Plan

> **For agentic workers:** Use subagent-driven-development for the independent scoring service and review, with UI integration in the primary task.

**Goal:** Complete the fixed composition → stock ranking → explainable saved shortlist flow.

**Architecture:** Dedicated scoring service and immutable per-job strategy snapshot; Streamlit workspace submits background platform jobs and browses separate selection records.

**Tech Stack:** Python 3.8, pandas, Streamlit 1.40, existing expression evaluator and daily zscore.

- [x] Backend: create custom_bt/stock_selection.py and tests/test_stock_selection.py. Expose load_strategy(composition_dir, pools_root), run_stock_selection(master_store, strategy, outputs_root, as_of_date=None, top_n=20, min_factor_coverage=1.0, exclude_suspended=True), list_selections(outputs_root). Freeze codes and weights; hash snapshot. Reuse daily_cross_section_zscore. Test future cutoff, deterministic ranking, missing inputs, persistence, retrospective labels.
- [x] UI: create app/workbench_selection.py; register 股票筛选 in workbench.py and components. Display strategy summary, editable date/Top N, advanced coverage and suspension filters, submit once, show local task progress, saved ranked candidates and per-stock contributions/downloads. Empty state links to combination/data modules.
- [x] Integration: platform_jobs supports select_stocks; result_history composite action carries exact path to selection; task output opens exact selection record. AppTest verifies handoff, payload snapshot, empty state, history and invalid input.
- [x] Verification: run targeted tests in F:/anaconda3/envs/alphagen/python.exe then complete custom_backtester/tests suite; inspect live browser and update README/spec with limits and results. No production training/backtest jobs needed.

No Git repository is present; changes remain in the user's working directory.

## Verification
- Full suite: 196 passed before two additional provenance cases.
- Final scoring/platform/UI integration: 42 passed; final layout/UI regression: 47 passed.
- Live browser: existing two-factor composition scored 500 stocks at 2026-06-16, 499 eligible, Top 20 saved as historical preview in outputs/stock_selections/20260920_140009_618344_56b31436.
- Independent review completed; unknown source research dates, same-day formation and missing suspension-state findings fixed.

