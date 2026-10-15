# Expense Tracker — implementation kickoff plan (planning only; no code)

Written 2026-10-16. **Nothing here is approved or started.** Build order, branches and slices are proposals for the product owner. No dates or effort estimates are given. Authority order is unchanged: `docs/decisions/phase1-decisions.md`, then `docs/specs/expense-tracker.md`, then the engine spec. File lists below were read from the actual tree on `feat/pnl-calculator-and-expense-tracker`; "new" means the file does not exist yet.

## Branching

- **Base:** `feat/pnl-calculator-and-expense-tracker` (the combined branch). Backup branches `feat/pnl-calculator-integration` and `spec/expense-tracker` stay untouched.
- **Status 2026-10-16:** ST-01 (Step 1) is **merged** into the combined branch (merge commit `4e5274b`); the branch `fix/expense-adv-not-entered` no longer exists. Step 2 (engine) is being done directly on the combined branch by instruction, without a separate branch.
- **One branch per step** (the default below; superseded for Step 2 as noted above), each cut from the combined branch (or from the previous step's branch once that step is merged back into the combined branch), named `type/short-description` per `CLAUDE.md`: `fix/expense-adv-not-entered` (ST-01), `feat/expense-engine-feed`, `feat/expense-ledger-form`, `feat/expense-recurring`, then `feat/expense-csv-import` and `feat/expense-chat-draft`.
- Nothing is committed to `main`; no push or deploy without a separate instruction.

## Gates in one line each (from the spec §10)

G1 design approval (owner countersign of EXP-01…08, Q1, open register items) · G2 financial integrity (engine tests, allocation suite A1–A10, reconciliation AC17/F7, total-profit invariant F5, sign mapping F1, historical-result demo) · G3 security (write routes) · G4 retention/storage · G5 tax wording · G6 draft-from-chat · G7 production validation (trial results, `is_trial=true`).

**Launch condition for the ledger feed:** the pricing, alert and what-if consumer specs must carry the unallocated-spend caveats before release (spec §6.13 rule 12, Appendix B.11). The consumer specs have **not** been edited yet.

---

## Step 1 — ST-01: show "Not entered" for absent advertising spend

*Separate small task (EXP/ST-01 approved as separate). Display only; no formula change.*

- **Done:** merged (`4e5274b`), implemented as `44a39c0`. **Prerequisites (historical):** none beyond the approved ST-01 (spec Appendix D). Does not need G1 and does not touch the ledger.
- **Files likely affected:**
  - `backend/src/backend/services/cfo_actions.py` — `compute_period_pnl` (add additive `advertising_entered`), `PeriodPnlOutcome`.
  - `backend/src/backend/api/v1/cfo.py` — the `_period_pnl_*_to_dict` mappers and `post_period_pnl` response.
  - `frontend/components/cfo/sections/PeriodPnlSection.tsx` — render "Advertising: Not entered" vs the entered amount (including an explicit ₹0.00).
  - `frontend/lib/api.ts` (response type), `frontend/test-support/responseContracts.json` and `requestContract.json` (regenerated), `frontend/lib/clientContract.test.ts`.
- **Tests required:** empty advertising list ⇒ `advertisingEntered=false`, `ContributionProfit` numerically unchanged; an explicit `amount_paise = 0` ⇒ `advertisingEntered=true`, shown ₹0.00; UI never shows ₹0.00 for absent; request-contract snapshot unchanged, response contract updated. Existing: `packages/cfo/tests/unit/test_cfo_actions_pnl.py`, `backend/tests/integration/test_cfo_pnl.py`, `frontend/app/dashboard/cfo/cfoPage.test.tsx`.
- **Gates:** none of G1–G7. Note ST-01 must not mislabel an existing-but-unallocated account-level adjustment as "Not entered" (engine §5.8 amendment); until the ledger exists the flag is simply "no advertising record supplied".

## Step 2 — Engine: ledger feed, result metadata, metric codes, allocation bases, G2 tests

*The G2 prerequisites. Everything that selects, aggregates, signs or allocates ledger rows lives in `packages/calc-engine`.*

- **Prerequisites:** G1 countersign (Q1); product owner approval of every PROPOSED engine item (list in `10-g1-approval-table.md` §B): total-profit option, storage term, basis granularity, UNITS/ORDERS definitions, reason codes, sign/class mapping, `is_trial` read mechanism, trial name, watermark location, metric codes. The ledger tables (Step 3) are needed to run the feed end to end; the engine pure functions and tests can be built first against fixtures.
- **Files likely affected (existing):**
  - `packages/calc-engine/src/calc_engine/formulas/allocation.py` (UNITS/ORDERS weight builders; `AllocationBasis` already declares all three), `formulas/expense_pools.py` (`allocate_account_level_expense_pool` hard-codes `NET_REVENUE`, has no production caller), `formulas/contribution_profit.py` (new formula version at the release date; storage term if approved).
  - `packages/calc-engine/src/calc_engine/api/compute_metric.py`, `definitions/seed_definitions.py` (new `*_V*` definitions and metric codes), `rounding.py`, `types.py`.
  - `packages/calc-engine/src/calc_engine/repositories/metric_result_repo.py` — `_GET_SQL`, `list_by_metric_code` and the save path: add `is_trial` exclusion at the read layer (`include_trial=False`); ledger watermark in `input_refs`.
  - `backend/src/backend/repositories/shared_finding_repo.py::resolve_engine_results` (must not resolve trial results).
  - `packages/cfo/src/cfo/pnl/inputs.py::resolve_expense_pool_total` and `backend/src/backend/services/cfo_actions.py::compute_period_pnl` — replace caller-supplied pool lists with the engine's feed; the summation currently lives outside `packages/calc-engine`.
- **New:** a feed module under `calc_engine/api/` or `formulas/`, a ledger read repository under `calc_engine/repositories/`, unit tests for the cases below.
- **Tests required (from the spec and engine):** total-profit invariant F5 / TP1–TP10 (zero denominator, mixed methods, period mismatch, missing sales, all bases, unavailable propagation, rounding, refund in pool, negative weights, reconciliation); sign-mapping round trip F1 in both directions; allocation suite A1–A10; SKU-level rule F6 (Q29); trial isolation F2 (`is_trial=true` absent from every seller-facing read); historical-result tests (old result preserved, version label, restatement linked and labelled); determinism (`test_ac1_determinism.py`). Existing tests to extend: `packages/calc-engine/tests/unit/test_expense_pools.py`, `test_compute_metric.py`, `test_confidence_monotonic.py`; integration `test_metric_result_repo_list_by_metric_code.py`, `test_rls_isolation.py`, `test_migration_roundtrip.py`.
- **Gates:** G1 before starting; **G2** passes only when these tests and the historical-result demonstration pass.
- **Not in this step:** the CEO/CFO/PI/anomaly/calculator caveat edits (separate spec edits, required before release).

## Step 3 — Ledger tables, manual entry/edit form, payment and review status, controlled categories, void instead of delete

- **Prerequisites:** Step 2's feed contract settled (the table shape must serve it); G1; open items decided: category list and category→cost-class mapping (Q5), review-status values (Q6/D5), legacy tracker compatibility (X1/Q7), `agent_run` for expense writes (X3/Q12), write-validation bounds (X2), entitlement check (X9). **Where the migration lives is a decision:** precedent is calc-engine-owned tables (`manual_adjustment`, `reconciliation_*` in `packages/calc-engine/migrations/versions/`) rather than backend migrations; the app-role grants/revokes need the pattern of `backend/migrations/versions/20261012_0018_app_role_least_privilege.py`. Recommended: calc-engine-owned, because the feed reads the ledger.
- **Files likely affected:**
  - **New migration** (append-only `expense_event`, status events, drafts/import/template tables as approved; `tenant_id`, `FORCE` RLS copied from `_TENANT_RLS_SQL` in `20260917_0001_engine_tables.py`, UPDATE/DELETE revoked like `manual_adjustment`).
  - `backend/src/backend/api/v1/cfo.py` (new ledger routes beside the legacy `PUT/GET /cfo/expenses`; or a new router), `backend/src/backend/services/cfo_actions.py` (`enter_expense`, `list_expenses`; legacy behaviour kept until cut-over, X1), `backend/src/backend/auth/permissions.py` (no new key — `financials.adjust` governs every write), entitlement checks (`entitlement_repo.py`).
  - `frontend/components/cfo/sections/ExpenseTrackerSection.tsx`, `frontend/lib/api.ts`, `frontend/app/dashboard/cfo/page.tsx`, contracts in `frontend/test-support/`.
- **Tests required:** S-series security and idempotency on scratch Postgres (never the live dev DB: see the dev-DB test-safety note); every-route 401/403 tests include the new routes; two-tenant isolation; append-only enforced at grant level; void-not-delete; `backend/tests/integration/test_rls_isolation.py` and `test_tenant_data_inventory.py` updated for the new tables; PARTNER without `financials.adjust` ⇒ 403 (AC8/AC8a); frontend tests for the form, statuses and "documented `financials.adjust` limitation visible to owners granting it".
- **Gates:** G1; **G3** before any write route is enabled; G5 before GST/ITC fields are displayed; G4 before any receipt reference/upload or retention statement.

## Step 4 — Monthly and per-order recurring templates and the engine feed into the P&L margin

- **Prerequisites:** Steps 2 and 3 merged; the recurring-commitment scope and materialisation rule decided (X10/Q24); approval of engine §5.18.2 (per-order/per-unit templates) and, if wanted, §5.18.1 (amortization) — both PROPOSED. "True Margin" is not a defined term in the code or the specs (it appears only in the archived root draft and the readiness review): the owner should confirm that it means the engine's `ContributionProfit`/`TotalProfit` margin, otherwise a new metric is needed.
- **Files likely affected:** engine feed and templates module (new) under `packages/calc-engine/src/calc_engine/`, `formulas/allocation.py` (count definitions shared with `ORDERS`/`UNITS`), `packages/cfo/src/cfo/pnl/inputs.py`, `backend/src/backend/services/cfo_actions.py::compute_period_pnl`, `backend/src/backend/api/v1/cfo.py`, `frontend/components/cfo/sections/PeriodPnlSection.tsx` (unallocated lines, formula-version label, total profit), contracts.
- **Tests required:** PT1–PT8 and AM1–AM9 if those items are approved; reconciliation F7 (dashboard total = P&L lines + unallocated lines) across all four value states; the unallocated-spend lines shown beside contribution profit; the formula-version label on every result; historical results not restated at the release date.
- **Gates:** **G2** in full; the consumer-spec caveat launch condition before release; Q28 trial run at G7.

## Step 5 — CSV import, draft-from-chat, then the proposed additions once approved

- **CSV import** — prerequisites: Steps 2–3; template columns (Q9/D10); **raw-file retention decided by legal/CA (Q19)** before any raw file is kept; duplicate thresholds (D6) and overlap UX (D7). Files: new import route/parser in the backend, an import-batch table (Step 3 migration), `frontend/components/cfo/sections/ImportAndGoalSections.tsx` as the pattern, ingestion adapters pattern in `data-foundation.md`. Tests: preview writes nothing, row-level errors, safe re-upload (file hash + row keys), imported rows `needs_review`, confirmation requires `financials.adjust`. Gates: G3, G4 (retention), G5.
- **Draft-from-chat** — prerequisites: Steps 2–3; implementation approval of the EXP-03 amendments (the spec text is already in `ceo-agent-orchestration.md` §6.11/§6.33; the code and tests still decline). Files: `backend/src/backend/ceo/registry.py` (new draft action key and effect class; `FORBIDDEN_ACTION_KEYS` unchanged), `ceo/effects.py`, `ceo/classifier.py` (the route), the T35/T36 tests, frontend `components/ceo/hub/DecidePanel.tsx` / `frontend/lib/ceo.ts` for opening the pre-filled form; draft table from Step 3. Tests: the draft carries vendor, category, date only; amount and description typed on the form; creation and confirmation both require `financials.adjust`; idempotency, expiry, cross-org and replay; AC21 no numeric literals in composer output; LLM evals (never states a number, never saves). **Gate: G6.**
- **Proposed additions** (amortization §5.18.1, per-order/unit templates §5.18.2, multi-SKU assignment §5.18.3, accountant CSV export §5.18.4): built only after each is approved. Multi-SKU assignment extends the Q29 single-SKU tag and needs that extension approved first; the export needs a decided permission and retention position (Q34).
- **Gate for general availability:** **G7** — 3–5 sellers reconcile output with their records; results produced as `is_trial=true` during validation; release date recorded when the first production deploy follows a pass with `is_trial=false` results.

---

## What must happen before any of this can start

1. Owner countersign of EXP-01…EXP-08 (Q1) and the decision on every PROPOSED item in `10-g1-approval-table.md`.
2. The open register items needed by Step 3 (X1, X2, X3, categories, review states) decided, or explicitly deferred.
3. The consumer-spec caveat edits scheduled (they block release of the ledger feed, not the engine build).
4. A scratch Postgres for the integration tests (the live dev database must not be used).

## Test environment note

Seven `packages/cfo` unit tests (`test_permissions.py::test_put_expense_*` and `test_cfo_actions_strategic_briefing.py`) need the **scratch-DB environment** (`eval "$(bash backend/scripts/scratch_db.sh env)"`, port 5544) **and** `LLM_OPERATOR_CONTROLLED_HOSTS=localhost:11434`. Without them they fail with `DATABASE_URL_APP is not set` and `LlmEndpointNotVerified`; with them the `packages/cfo` unit suite passes (300 passed, 3 skipped on 2026-10-16).
