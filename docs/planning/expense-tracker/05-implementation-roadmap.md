# Expense Tracker — 05 Implementation Roadmap

> **Overlay, 2026-10-15.** D1–D3, IndiaMART (D14), the permission decision (D11: **no new key; `financials.adjust` retained**), the allocation default (D9) and the reversal of "removed by design" are **approved (product)** — see `docs/decisions/phase1-decisions.md`. Final reconciliation 2026-10-15: EXP-05 is "no new key"; the historical-result policy (no automatic restatement; release date placeholder) is in force. Phase P0 therefore shrinks to: owner countersign + the spec amendments in `docs/specs/expense-tracker.md` Appendix B + the remaining open decisions. **Absent-advertising display (ST-01) is a separate, independent task and is not a phase of this roadmap.** The allocation change (EXP-06) is an **engine behaviour change** and gets its own phase (P5). Nothing here is authorization to implement; gate G1 still applies.

**Status:** planning. **Do not start any phase until its gate is met and the decisions it depends on are approved in `docs/specs/expense-tracker.md`.** Files listed are *likely* changes, derived from the repository audit; none has been touched. Gate and test ids refer to `04-test-and-risk-matrix.md`; decision ids to `02-decision-register.md`.

Branch convention (CLAUDE.md): one branch per phase (`spec/expense-tracker`, `feat/expense-core`, …); never on `main`; commit and push only when asked.

---

## Phase P0 — Decisions and spec (no code)
**Goal.** Close the blocking decisions and merge the two drafts into one authority.
**Work.**
1. **Done (2026-10-15):** owner rulings on D1, D2, D3, D9, D11, D14 and the reversal of "removed by design" (EXP-01…07). **Remaining:** X1 (legacy tracker), D4, D5 (review values), D6, D7, D8, D10, D12, D13 and owner countersign of the Appendix B amendments.
2. Merge `expense-tracker.md` (repo root) and `docs/specs/expense-tracker.md` into the single spec under `docs/specs/`, using the repository's spec template; remove the root copy only after review.
3. Resolve citations: write or strike `legal-safeguards.md` and `docs/decisions/phase1-decisions.md`; locate the "30-day rule" or retire it.
4. Engine-spec amendments drafted by the architect agent: expense registry/feed contract in `deterministic-engine.md` §7.2.1/§5.6; overhead allocation default (D7 vs explicit selection); restatement labelling (F3).
5. CEO spec: the scoped amendment of `ceo-agent-orchestration.md` §6.33/E30/T36/§6.11/Q33 for the expense draft-to-form flow (EXP-03, EXP-05); `ceo-approval-workflow.md` only if plan/hash approval is chosen.
**Files likely to change.** `docs/specs/expense-tracker.md`, `docs/specs/deterministic-engine.md`, `docs/specs/auth.md` (optional clarification only: `financials.adjust` row includes the expense ledger; no new key), `docs/specs/cfo-agent.md`, `docs/specs/ceo-agent-orchestration.md`, `docs/planning/phase-1-readiness-review.md`.
**Acceptance.** Spec marked approved with D1–D3 resolved in writing; G1 satisfied.
**Dependencies.** None. **Owner/CA/legal input needed:** D2, D12, X6, X7.

## Phase P1 — Engine feed and data model
**Goal.** Stored expenses can reach the period P&L through Brain 1, stamped and reproducible. No UI.
**Work.** Expense tables + RLS/grants + migration (calc-engine or cfo package, per the chosen owner); `expense_feed` pure function; wire `compute_period_pnl` to read the feed instead of caller-supplied lists (keeping the old request fields working until X1 retires them); watermark stamping; restatement link; legacy-row compatibility (X1).
**Files likely to change.**
- `packages/calc-engine/migrations/versions/` (new revision), `packages/calc-engine/src/calc_engine/formulas/expense_feed.py`, `…/repositories/expense_repo.py`, `…/formulas/expense_pools.py`, `…/formulas/allocation.py` (only if a basis is added)
- `packages/cfo/src/cfo/pnl/inputs.py`, `backend/src/backend/services/cfo_actions.py`
- `backend/tests/integration/`, `packages/calc-engine/tests/`
**Acceptance.** F1–F11, S9, S10, R1–R3 pass; reconciliation worked example per class (G2 partial); no float/IO scan green; migration applied on scratch DB only.
**Dependencies.** P0 (D1, D2, D9).

## Phase P2 — Manual expense API and dashboard
**Goal.** Create/edit/void/review/list with audit; dashboard with as-of timestamps.
**Work.** Service `backend/src/backend/services/expenses.py`; routes under `/api/v1/cfo/expense-records*` and `/expense-summary` (strict models, idempotency, `agent_run` for writes); `ExpenseDashboard` section in the CFO page (monthly totals, category breakdown, recurring commitments, review queue); `CostInput` reuse; "included in margin: yes/no because…" column; request/response contracts regenerated; every-route tests extended.
**Files likely to change.** `backend/src/backend/api/v1/cfo.py` (or a new `cfo_expenses.py` router registered in `main.py`), `backend/src/backend/services/expenses.py`, `frontend/components/cfo/sections/ExpenseTrackerSection.tsx` (replace/extend), new `frontend/components/cfo/expenses/*`, `frontend/lib/expenses*.ts`, `frontend/app/dashboard/cfo/page.tsx`, `frontend/lib/navigation.ts` (copy only), `frontend/test-support/requestContract.json`, `responseContracts.json`.
**Acceptance.** S1, S1a, S2–S7, S11, S13, Q1–Q3, U1–U8, R4–R6 pass; two-tenant isolation green; G3 satisfied for these routes.
**Dependencies.** P1; D4, D5, D6, D11.

## Phase P3 — CSV import
**Goal.** Safe two-step import with duplicate handling and documented template.
**Work.** Template document (`docs/` + download), validate/preview/confirm routes, row-level error report, `expense_import_*` tables, duplicate tiers (D6), `needs_review` default, reuse of `read_upload_capped` and the file-hash pattern **without** the shared-directory storage (parse in memory; store only parsed rows and the file hash — no raw file retention decision needed).
**Files likely to change.** `backend/src/backend/services/expense_import.py`, `backend/src/backend/api/v1/cfo*.py`, `packages/calc-engine` (parse helpers stay in Brain 1 if they produce paise), frontend import section and tests, `docs/` template.
**Acceptance.** V1–V8, Q7, R4, R5 pass; two real seller files imported in a rehearsal.
**Dependencies.** P2; D10, D6, D7.

## Phase P4 — Recurring templates
**Goal.** Recurring commitments view and idempotent monthly posting.
**Work.** Template tables; commitments computed for display; "post this month" action (idempotent per `(template, period)`); optional periodic thread behind a lease only if approved.
**Acceptance.** Q6, K14 mitigations; commitments never counted in margin until posted.
**Dependencies.** P2. No new scheduler infrastructure.

## Phase P5 — Allocation engine change and profitability views (EXP-06)
**Goal.** Contribution margin and fully allocated profitability, each with its basis and gaps.
**Work.** **Engine behaviour change:** basis becomes a required argument (remove the hard-coded `NET_REVENUE` in `expense_pools.allocate_account_level_expense_pool`); add `AllocationOutcome` with reason codes; move business overhead out of the `OtherAllocatedCosts` term of Contribution Profit into a separate fully allocated figure; explicit basis selection per overhead; unallocated pool visible; period/channel rules from D9; UI labels; restatement for already-reported periods (spec Q13).
**Acceptance.** A1–A10 and F3–F5 pass; owner-countersigned D7 amendment recorded; unallocated amounts displayed with reasons.
**Dependencies.** P1, P2; D9 approved.

## Phase P6 — Draft-from-chat (EXP-03, gated)
**Goal.** Chat prepares a draft that pre-fills vendor, category and date only; the seller types description and amount and confirms on the form; no chat write.
**Work.** `expense_proposal`, propose/confirm routes, extraction schema, LLM evals, CEO registry/classifier changes only after C21 is amended.
**Acceptance.** G6; S8, S12, Q3–Q5, evals green.
**Dependencies.** P2; owner amendment of `ceo-agent-orchestration.md` §6.33/E30/T36 (spec Q2); D13; approval-workflow S2/S3 only if Q3 chooses plan/hash approval.

## Phase P7 — Hardening and launch
Tax wording CA review (G5), retention statement (G4, none claimed if undecided), accessibility pass, scale check on import, seller validation (G7), documentation, runbook, feature flag/entitlement wiring.

## Later (not in V1.0)
Receipt OCR using the `VisionProvider` slot (needs storage, evals, retention — G4); WhatsApp quick-add (reuses P6 and `whatsapp-integration.md`); bank-statement import; custom categories; CSV column mapping; validated advertising-report adapter (D8); IndiaMART adapter (D14).

## Dependency graph
`P0 → P1 → P2 → {P3, P4, P5} → P7`; `P6` after `P2` and the approval workflow; receipts only after `G4`.

## Interim safety actions that need no design decision (still require approval to execute)
1. Add server-side validation to `PUT /cfo/expenses` (X2) so one bad row cannot break a tenant's listing.
2. Show "included in margin: not yet" next to saved expenses in the shipped UI until P1 lands, so a saved expense is not presumed to affect margin.
3. Add HTTP-level 403 and duplicate-submit tests for the shipped route.
These are small, independent of D1–D3, and reduce current TRUST risk (B2, B4).

## Separate task (not a phase): ST-01 — show "Not entered" for absent advertising spend
Independent of the Expense Tracker and shippable on its own after owner approval. Display only; the formula rule (absent `expense.advertising` resolves to zero) is unchanged. Exact files, change and tests: `docs/specs/expense-tracker.md` Appendix D. Do not bundle with the ledger.
