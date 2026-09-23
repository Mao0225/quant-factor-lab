# Twelve-factor exploration and readable research pages Implementation Plan

> **For agentic workers:** Use subagent-driven-development for the independent interface work; root owns preregistration, actual runs, integration and acceptance.

**Goal:** Run an actual 12-factor starting-pool exploration and show clearly which factors are initialized, adopted and frozen, rather than presenting repeated 3-factor results as distinct discoveries.

**Architecture:** Preserve the existing frozen kernel and historical records. Register six independent application experiments before starting any of them, use the unchanged training/selection engine, and defer all T operations until every model is frozen. Presentation improvements are confined to the app's static files.

**Tech Stack:** Existing Python research kernel, local FastAPI API, NumPy/Pandas and vanilla JS.

## Preregistered design

- Dataset raw500_75b3494c10edbcd9; unchanged actual F/E/V/T calendar, fees, trading rules and prototype restrictions. No unverified finance.
- Twelve initial formulas: return_20, return_60, neg(return_1), neg(return_5), neg(volatility_20), neg(volatility_60), volume_ratio_5, volume_ratio_20, neg(ma_gap_5), neg(ma_gap_20), neg(range_relative), neg(intraday_return). Equal positive weights 1/12. This is a designed starting pool, not twelve PPO discoveries or independent information sources. Before registration/training, close_location failed complete eligible coverage on F (flat price range); it was replaced with neg(intraday_return), based only on input quality and never on V/T results.
- Capacity16; random and PPO arms both4 batches x6 candidates, inner Q12, perturbations [.05,.025,.01], restart_after8, selection batches[1,2,3,4], max_backtests1000, seeds7/19. Smaller steps are chosen before outcomes because original steps of1/.5/.1 overwhelm initial1/12 weights. No minimum-factor constraint; search may shrink the pool.
- Two reference experiments: original3 fixed weights and twelve-factor equal weights, generator fixed, search_mode fixed, Q1, one batch. Lower reference compute is disclosed.
- Four search experiments: random7, PPO7, random19, PPO19. Same initial pool, budgets and scoring rules. Individual V selection runs automatically per application's established lifecycle; all six protocols are registered beforehand, no V/T-based protocol adaptation. T is launched only after all six are frozen.
- Fixed hypotheses: does dense initial scoring differ from old3; does search materially change weights/pool; does PPO differ from random under matched seeds/budgets? Report every arm, including failures/negative results and actual nonzero factor counts. No best-T selection.

## Steps

- [x] Inspect old F/E traces and quantify stagnation (read-only agent).
- [x] Root writes reproducible API orchestration in closed_loop_research/scripts/run_diverse12_exploration.py; validate all six protocols and F/E initial-factor coverage. Save preregistration before starting jobs.
- [x] Submit real runs; track checkpoint progress without changing budgets. Complete registered runs or record concrete failures.
- [x] UI agent updates experiment labels, method explanations, initial/adopted/frozen composition tables, counts and focused JS tests, without kernel changes.
- [x] After all freezing, execute T once per experiment; produce comparison with factor weights, changes, V/T metrics, correlation/concentration limitations and compute counts.
- [x] Independently verify frozen scoring for a >10-factor output on F/E only. Open useful, clearly described prototype(s) under existing user authorization; don't claim learned discovery for designed baseline or select by T.
- [x] Browser-verify readable names and actual factor tables; preserve old protocols/records; document findings and explain results plainly.

## Acceptance

A genuine frozen version with more than10 nonzero formulas must be available from the designed12 baseline, with optimized counts reported separately. Random/PPO runs must retain actual trials, rewards, checkpoint updates and budgets. A negative result is acceptable and must not be hidden. The page must distinguish formula count from source field count, seed repeats from different strategies, and initial pool from selected model.

## Numerical acceptance investigation

The frozen random7 model has 11 nonzero formulas (V selected batch3). Strict 1e-12 scoring parity found four sampled numerical failures, with identical ranking and missingness. The discrepancy is confined to nested rolling standard deviation. The original failing report is retained; no scorer/kernel or threshold was silently changed. A separate full F/E daily audit measures errors and exact ranking, and an independent identical-window/prefix-length diagnosis establishes the source of floating-point drift before any availability decision.

## Final acceptance

Six registered runs and all six historical T tests completed. Evidence audit verified789 backtest artifacts,96 candidates,86 evaluated rewards plus10 fixed special rewards,8 PPO tensor updates and15 pool changes. Frozen counts3/12/11/10/10/10. Fixed12 passed18 strict scorer checks and was opened as a research baseline with a real Top50 result. Random7 remains candidate: all724 F/E daily rankings and Top50 match, but607 days fail strict1e-12 and maximum error1.197269e-9 also exceeds the separate diagnostic1e-9 bound. Both failed checks and the exact-window floating-point diagnosis are preserved; no kernel/scorer change or silent tolerance relaxation. This precision limitation is unresolved and disclosed, not marked fixed. Interface browser verification and both frontend regression checks passed. Old systems, protocols and existing model availability were preserved.
