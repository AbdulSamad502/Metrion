# Engine step notes — kickoff Step 2 (written before coding, updated as work proceeds)

Started 2026-10-16 on `feat/pnl-calculator-and-expense-tracker` (no other branch). Documentation of the plan, discrepancies and open questions; the frozen spec and other specs are not edited. Authority: `phase1-decisions.md` (errata) over the frozen spec; engine spec §5.8.1, §5.10.1, §5.17, §5.18.3 (mechanics only if needed), §9.2, §9.3.

## Scope
Pure engine functions in `packages/calc-engine` and the read-layer fixes only, built against fixtures. **Out of scope:** ledger tables and migrations (Step 3), routes, UI, recurring templates (Step 4), CSV import, draft-from-chat, amortization, per-order templates, multi-SKU assignment, export.

## Hard rules and how each is honoured
1. **New formula versions are added but not made active or default.** No existing function, definition, caller or default changes: `CONTRIBUTION_PROFIT.v1` stays what `compute_contribution_profit` emits; `SEED_DEFINITIONS` and the migration snapshot test are untouched; the new versions live in a separate module and are not seeded into `formula_definition` (that needs a migration, which is Step 3). A test asserts old results, the default version and `SEED_DEFINITIONS` are unchanged. The release date (Q15) is not set.
2. **No arithmetic outside `packages/calc-engine`; no LLM in the money path.** All new code is in `packages/calc-engine/src/calc_engine/`.
3. **Tests first, watched failing, then code; no existing test weakened.** Existing functions (`allocate_pool`, `allocate_account_level_expense_pool`, `contribution_profit`) keep their behaviour and tests; new behaviour is added in new functions.

## Slices (each its own commit, own tests)
- **A — `is_trial` read-layer exclusion.** `include_trial: bool = False` on `metric_result_repo.get` and `list_by_metric_code` and on `shared_finding_repo.resolve_engine_results`; a static test (F2) that scans every `FROM|JOIN metric_result` read in `backend/src` and `packages/*/src` and fails if its statement lacks a `NOT is_trial`/`is_trial = false` filter (explicit opt-out marker required); DB tests for the three paths with a trial row.
- **B — allocation.** New `allocation_outcome` functions: explicit basis required (`None` → `BASIS_NOT_SELECTED`), `UNITS` (net of returns) and `ORDERS` (distinct orders per SKU) weights, outcome with reason codes (`NO_REVENUE_FOR_PERIOD`, `ZERO_DENOMINATOR`, `UNITS_UNAVAILABLE`, `ORDERS_UNAVAILABLE`, `BASIS_DATA_UNAVAILABLE`, `INVALID_BASIS` + detail `PERIOD_MISMATCH`/`SCOPE_MISMATCH`), unallocated remainder visible, conservation; regression suite A1–A10 (A8 and the authorization half are not engine-level: reported as not built).
- **C — total profit and `StorageCosts`.** `CONTRIBUTION_PROFIT.v2` (storage term, overhead not a parameter, `OtherAttributedCosts`), `FullyAllocatedProfit`, `TotalProfit` (Option A), as inactive versions; invariant F5 and TP1–TP10.
- **D — ledger feed.** Pure function over fixture event rows: treatments, review states (`draft|pending_review|confirmed|voided`, only `confirmed` counts), signed mapping both directions (F1), refunds in the period of their own date, cost-class mapping, unallocated never zero-filled, watermark, Q29 SKU-level rule (F6).
- **E — metric codes and definitions.** Metric-code constants and `mint_*` functions stamping `formula_version`, `canonical_data_version`, `as_of_date`, `manual_adjustment_set`, `input_refs` (ledger watermark) like existing results; inactive definitions in a separate module.

## Decisions taken where the spec is silent (flagged for the owner)
1. **Missing returns for `UNITS`.** The spec requires "a quantity on every in-scope line" but does not say what a missing returned quantity means. Taken conservatively: missing returned quantity ⇒ `UNITS_UNAVAILABLE` (not zero). This may make `UNITS` unusable on files that omit returns; confirm.
2. **Definitions not seeded.** New definitions are not added to `SEED_DEFINITIONS` because `test_seed_definitions_migration_snapshot.py` requires a matching migration; seeding is Step 3.
3. **`allocate_account_level_expense_pool` retained unchanged** (hard-coded `NET_REVENUE`, no production caller) so existing tests and callers behave as before; the explicit-basis behaviour is in the new functions. Recommend removing the old function when the feed replaces caller-supplied lists.
4. **Business-wide rows in a channel scope** appear only as a visible "not in scope" amount from the feed, never spread (spec §5.17 (4)).
5. **Review queue.** Unmapped identifiers count as business-level (if confirmed) and are also listed in the review queue; `pending_review` rows are never counted in pools but appear in the review-queue and "including unresolved" amounts.

## Open questions and discrepancies found
1. **Missing returns for `UNITS`.** Implemented conservatively as `UNITS_UNAVAILABLE` (a missing returned quantity is not zero). May make `UNITS` unusable on files that omit returns. **Owner decision needed.**
2. **Definitions are not seeded.** `INACTIVE_DEFINITIONS` live in `definitions/expense_definitions.py`, not in `SEED_DEFINITIONS`, because `test_seed_definitions_migration_snapshot.py` requires a matching migration. Seeding them into `formula_definition` is a Step 3 migration.
3. **The database trigger on `shared_finding` does not filter `is_trial`.** `shared_finding_repo.resolve_engine_results` now excludes trial results, but the trigger that validates figure refs (migration `20261010_0012`) still accepts a trial `metric_result` id. Closing it needs a migration (Step 3).
4. **Old allocator retained.** `expense_pools.allocate_account_level_expense_pool` (hard-coded `NET_REVENUE`, no production caller) is unchanged so its tests and callers behave as before; recommend removing it when the feed replaces caller-supplied lists. Likewise `largest_remainder_allocate` still returns an all-zero allocation for a zero weight sum; the new `allocate_with_basis` never uses that path (it returns the pool unallocated with a reason).
5. **A8 (tenant isolation and authorization of allocation) is not built.** It needs the ledger tables and routes (Step 3). **A9** is covered only as far as it is engine-level (outcomes are immutable and stamp the basis); the restatement workflow does not exist yet.
6. **Persisting `CONTRIBUTION_PROFIT.v2` results.** `mint_expense_metrics` mints a `CONTRIBUTION_PROFIT` result stamped `.v2`. If it were saved before the release date it would sit beside `.v1` rows under the same `metric_code`, and `list_by_metric_code` consumers (period comparison, anomaly checks) do not filter by `formula_version`. Do not persist these before release, or have those consumers filter by version.
7. **Placeholders in minted results.** Tenant-level rows carry `target_ref="tenant"` (the caller substitutes the tenant id when saving); the migration comment lists grains `LINE | ORDER | SKU | MARKETPLACE | ACCOUNT` while code writes `TENANT_PERIOD` (existing inconsistency, reused here).
8. **`EXPENSE_RECURRING_TOTAL`** totals a `recurring` flag on the fixture rows; how recurring entries are materialised is Step 4.
9. **Cost-class vocabulary.** `ADVERTISING | STORAGE | OVERHEAD | DIRECT` is the fixture vocabulary; the approved category-to-cost-class mapping (Q5) does not exist yet, so an unknown class goes to the review queue.
10. **The feed does not allocate.** Choosing allocation targets and weights from canonical data (and which basis is stored per pool) is the caller's job (Step 4); `ledger_feed`, `allocate_with_basis` and `compute_profit_statement` compose as shown in `test_ledger_feed.py::test_f7...`.
11. **Channel scope.** Business-wide rows queried for a single channel are reported as `business_wide_out_of_scope`, never spread.

## Results (2026-10-16, scratch Postgres on :5544, never the dev database)
Commits: A `b772a7b` · B `ce933f6` · C `7ece7ac` · D `a3c4ee0` · E `86d5923`.

| Slice | Files | Tests |
|---|---|---|
| A is_trial exclusion | `metric_result_repo.py` (`get`, `list_by_metric_code`: `include_trial=False`), `shared_finding_repo.py::resolve_engine_results` | `test_trial_read_exclusion.py` (static F2 guard over every `FROM|JOIN metric_result` read; failed red on the 3 reads), `test_metric_result_trial_exclusion.py`, `test_shared_finding_trial_exclusion.py` |
| B allocation | `formulas/allocation_outcome.py` | `test_allocation_outcome.py` (A1–A7, A9, mismatches, hypothesis conservation) — 25 |
| C total profit | `formulas/expense_profit.py` | `test_total_profit.py` (A10, F5, TP1–TP10, inactive-version proof) — 22 |
| D ledger feed | `formulas/ledger_feed.py` | `test_ledger_feed.py` (F1, F6, F7, treatments, review states, scope, watermark) — 18 |
| E metric codes | `definitions/expense_definitions.py`, `api/expense_metrics.py` | `test_expense_metrics.py` — 8 |

Actual results: `packages/calc-engine` unit 485 passed (includes `test_ac1_determinism.py` and the migration-snapshot test); calc-engine trial DB tests 6 passed (with the existing list-by-metric-code tests); backend trial/findings/pnl integration subset 35 passed; `packages/cfo` unit 300 passed, 3 skipped; backend unit 4659 passed, 6 xfailed; **full backend integration suite 2013 passed, 3 skipped, 1 xfailed in 47 min 30 s.** Caveat: the full integration suite was started before the slice A repository edits, so it exercised the code at that time; the repository paths slice A changed were re-run afterwards (the 35 and 6 above). Not run: frontend tests (no frontend change), calc-engine integration suite beyond the files named, `test_migration_roundtrip`.

Red-first evidence: A failed on the three unfiltered reads; B–E failed at collection (module absent) before their modules were written.

## Inactive formula versions (proof)
`test_total_profit.py::test_old_results_and_the_default_version_are_unchanged` and `test_expense_metrics.py::test_the_new_definitions_are_inactive_and_nothing_existing_changed` assert: `SEED_DEFINITIONS` has exactly the four existing keys, the v2/new keys are absent from it, `ACTIVE_FORMULA_VERSIONS["CONTRIBUTION_PROFIT"] == "CONTRIBUTION_PROFIT.v1"`, `TOTAL_PROFIT` is not active, and the v1 `contribution_profit` result is numerically unchanged and keeps its `other_allocated_costs` parameter. `compute_period_pnl` and the default path were not edited. The release date (Q15) is not set.
