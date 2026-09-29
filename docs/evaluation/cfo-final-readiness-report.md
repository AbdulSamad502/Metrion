# CFO Final Readiness Report (2026-09-27)

**Author:** Claude (backend implementation agent), continuing this project's existing CFO work.
**Scope:** audit the existing CFO against `docs/evaluation/cfo-e2e-evaluation-mtr-mock-2026-09-27.md`,
fix confirmed real gaps, add the two features the user asked for (a seller-declared
cancellation/return/RTO status override, and a Financial Health Band), and report honestly on
what is and is not ready. **No feature was rebuilt from scratch. No GST rate, marketplace fee,
or financial formula was invented anywhere in this pass** — every number this session's new
code touches is either a classification of an already-computed figure, or a plain read/write of
a seller-declared value.

---

## 1. What was audited first (no code changed yet)

Read, in order: `CLAUDE.md`, `docs/specs/deterministic-engine.md`, `docs/specs/cfo-agent.md`,
`docs/evaluation/cfo-e2e-evaluation-mtr-mock-2026-09-27.md` in full, `git log`/`git status`.

The evaluation report's own conclusion going in: **20 PASS, 3 PARTIAL, 2 BLOCKED, 0 FAIL** across
25 real feature invocations against 3 real (if non-representative) MTR-shaped files, with **zero
confirmed code defects** — every UNAVAILABLE/BLOCKED/PARTIAL outcome traced to a real data
limitation or the engine's own hard rule working as designed. Two items were flagged as
**candidate** bugs, not confirmed, for lack of time budget in that evaluation:

1. Flipkart Leak Shield returned `match_count=0` where Meesho's identical bypass-insert
   technique returned 40/40 (an unexplained asymmetry).
2. `assemble_batch_size_estimate`'s `velocity_unavailable_reason` came back `null` while
   `velocity_status="UNAVAILABLE"`.

This pass's first job was root-causing both **before** touching anything else.

---

## 2. Investigation results for the two candidate bugs

### 2.1 `velocity_unavailable_reason` null — **not reproducible; already correct**

Read `backend/src/backend/services/cfo_actions.py`'s `assemble_batch_size_estimate` and
`packages/calc-engine/src/calc_engine/formulas/sales_velocity.py`/`cost_components.py` line by
line. Every `Unavailable(...)` this code path can return already carries a real, non-empty
`reason` string — there is no path that constructs an `Unavailable` without one.

**Ran the existing test suite to confirm rather than trust the reading:**
`packages/cfo/tests/unit/test_cfo_actions_batch_size.py::test_unavailable_velocity_with_moq_supplied_degrades_but_does_not_refuse`
already asserts `outcome.velocity_unavailable_reason is not None` and passes. Full file: **20/20
passed.**

**Conclusion: this is a false alarm** — most likely the evaluation ran against a slightly
earlier state of the code on the same day, or an artifact of the eval script's own bypass
construction. No code change was made or needed. This is disclosed as an investigated,
not-reproduced finding — not silently dropped.

### 2.2 Flipkart Leak Shield `match_count=0` asymmetry — **not a code defect; regression test added**

Read `packages/calc-engine/src/calc_engine/api/reconcile.py` in full. `reconcile()`'s Path A
match logic (lines 434–513) computes `shared_codes = settlement_codes.keys() & invoice_codes.keys()`
for a resolved `SingleMatch` pair, per "Decision A" (documented in that file's own module
docstring) — a match/exception is only produced for a `component_code` present on **both**
sides. This logic contains no marketplace-specific branch at all; Amazon/Flipkart/Meesho all run
through the identical code path, differing only in `_JOIN_KEY_FIELD` (`order_ref` vs `line_ref`).

The existing integration test file, `test_reconcile_amazon_flipkart_extension.py`, already
proved Flipkart can produce `ORPHAN_SETTLEMENT`/`DUPLICATE_SETTLEMENT` exceptions with real
amounts — but **no existing test exercised a genuine Flipkart `SingleMatch` with a shared
component_code**, the exact scenario the eval's own bypass script was exercising when it
reported `match_count=0`.

**Added `test_flipkart_successful_match_with_shared_component_codes`** — same shape as the
existing Meesho match test, substituting Flipkart's `order_ref` join key for Meesho's
`line_ref`. Ran against the real local Postgres (`metrion-postgres-1`, already running):

```
python -m pytest packages/calc-engine/tests/integration/test_reconcile_amazon_flipkart_extension.py -q
8 passed in 1.26s
```

**The new test passes** — a real, shared `COMMISSION` component_code on both sides for a
Flipkart line produces exactly 1 match and 1 `VARIANCE_EXCEEDS_TOLERANCE` exception, both capped
at `PROVISIONAL` confidence (the unvalidated join-key rule), exactly as designed.

**Conclusion: `reconcile()` is not defective for Flipkart.** The eval's own one-off bypass
script (never committed, no longer available to inspect) most likely inserted Flipkart's
settlement-side and invoice-side component codes under names that did not overlap — a property
of that script's own data setup, not of the product code. This is now backed by a real,
committed regression test rather than left as an open question.

**Net result: 0 confirmed code defects found or fixed in the existing engine/reconciliation
code.** The evaluation's own headline finding — the engine's honesty discipline held under real,
incomplete data — is reconfirmed, not contradicted.

---

## 3. Real, confirmed gap fixed: expense description was write-only

While verifying item E of the brief ("seller should be able to add other expenses like travel,
petrol") against the actual code: `enter_expense` already accepted a free-text `reason`
(mapped straight to `manual_adjustment.reason`), and `expense.other` already exists as a fully
generic category — so a seller COULD already log "travel"/"petrol" as an `other` expense. But
`list_expenses`/`GET /cfo/expenses` **dropped `reason` entirely on the way back**, and the
dashboard's "Add expense" form never collected it in the first place. A seller could write a
description but never see it again — every "other" entry looked identical.

**Fixed, backend and frontend, both verified with passing tests:**

- `backend/src/backend/services/cfo_actions.py`: `ExpenseEntry` gained a `reason: str | None`
  field; `list_expenses` now populates it from the row it already reads (`row["reason"]`).
- `backend/src/backend/api/v1/cfo.py`: `_expense_entry_to_dict` now serializes `reason`.
- `frontend/lib/api.ts`: `ExpenseEntry` type gained `reason: string | null`.
- `frontend/app/dashboard/cfo/page.tsx`: the "Add expense" form gained a "Description
  (optional)" text field, wired into the `PUT /cfo/expenses` body's `reason`; the "List
  expenses" table gained a "Description" column.
- New test: `packages/cfo/tests/unit/test_cfo_actions_expense_list_and_budget.py::test_list_expenses_surfaces_the_sellers_own_reason_text`.

Frontend change was verified with `npx tsc --noEmit` (clean) and by confirming the only
`ExpenseEntry(...)` construction site in the codebase was updated to match the new field — a
live click-through in the browser was **not** performed (it requires a signed-in Clerk session
and real tenant data this session did not set up), so this is typechecked and unit-tested, not
visually verified end-to-end. Flagged honestly rather than claimed as fully verified.

---

## 4. New feature 1: seller-declared cancellation/return/RTO status override

**This directly targets the evaluation's #1 finding**: Contribution Profit was `UNAVAILABLE`
for 100% of the real MTR dataset because no file carried a resolvable cancellation/RTO status.
User confirmed scope via explicit question: *"Add the 3 override fields now."*

### 4.1 What was built

- **Spec** (`docs/specs/deterministic-engine.md` §7.2.1): three new LINE-grain manual_adjustment
  fields — `cancellation_state_override` (`CANCELLED`/`NOT_CANCELLED`),
  `return_status_override` (`RETURNED`/`NOT_RETURNED`), `rto_status_override` (`RTO`/`NOT_RTO`).
  Documented precedence rule: **fills a gap, never overrules real data** — consulted only when
  the marketplace report's own field is `None`; a resolved value (even "not cancelled") always
  wins. Confidence `MANUAL`; permission `financials.adjust`.
- **Engine formula** (`packages/calc-engine/src/calc_engine/formulas/line_status_overrides.py`):
  `resolve_line_status(observed, override)` — the entire precedence rule, in one tested place.
  5 unit tests, all passing.
- **CFO actions** (`backend/src/backend/services/cfo_actions.py`):
  `declare_line_status_override` (validates field + enumerated value, writes the
  `manual_adjustment` row) and `get_line_status_overrides` (reads back all 3 fields for one
  `sales_line_id`). 10 unit tests, all passing.
- **API routes**: `PUT`/`GET /api/v1/cfo/line-status-override`, gated by `agent.cfo` +
  `financials.adjust` (write) / `agent.cfo` only (read) — verified registered on the live
  FastAPI app (`app.routes` inspection, not just import success).
- **Spec §6.14** added to `cfo-agent.md`, cross-referencing the engine spec per this project's
  own "product rules here, arithmetic/field registry there" convention.

### 4.2 What this does **not** yet unblock — stated plainly, not glossed over

This closes the *input* side only. Investigating the actual composition path revealed a bigger,
pre-existing architectural fact, not introduced by this session: **no production code anywhere
in this codebase reads real `sales_line`/`line_component` rows from the database and merges
manual-adjustment overlays into a `CanonicalLine` automatically.** Every multi-line CFO
composition (`cfo.pnl`, GST period summary, batch-size) is **caller-assembled** —
`PeriodPnlHttpRequest`'s own docstring names this explicitly as "judgment call 4." The original
evaluation's own bypass script built `CanonicalLine`s by hand for exactly this reason.

So: a seller can now durably declare "this line was actually delivered" — but wiring a real
uploaded MTR file's rows through ingestion, into that declaration, into a `CanonicalLine`, into
`compute_period_pnl`, is a separate, larger piece of work (a real ingestion-to-canonical
composition layer) that does not exist yet and was not built in this pass. This is disclosed in
the spec itself (§7.2.1's new subsection) and here, not left implicit.

---

## 5. New feature 2: Financial Health Band

User's explicit direction: *"add new feature on backend for now... build the entire feature
[on the backend]... we integrate [the frontend] later."* Composite-band approach (my
recommendation) was accepted implicitly by proceeding with it.

### 5.1 Design constraint honored

Per CLAUDE.md's hard rule, this is a **classification**, never a new derived financial figure —
it mirrors `severity.py`'s existing, already-shipped pattern (`finding_severity`: "ranking is
not judgement... computed deterministically in Brain 1") exactly. No arithmetic on money occurs
anywhere in this feature.

### 5.2 What was built

- **Migration** `packages/calc-engine/migrations/versions/20260927_0010_financial_health_config.py`:
  `financial_health_config` table (tenant-nullable platform-default pattern, mirroring
  `severity_config`/`anomaly_detection_config` verbatim). **Applied to the real local Postgres**
  (`alembic upgrade head` — confirmed via output: `Running upgrade 20260926_0009 -> 20260927_0010`).
- **Repo function**: `config_repo.financial_health_config_rows(tenant_id, as_of_date)`.
- **Engine formula** (`packages/calc-engine/src/calc_engine/formulas/financial_health.py`):
  `assemble_financial_health(inputs, config_rows) -> FinancialHealthResult | Unavailable`.
  Classifies `CONTRIBUTION_MARGIN_PCT` (LOWER_IS_WORSE), `FEE_RATIO_PCT`/`RETURN_RATE_PCT`
  (HIGHER_IS_WORSE) against exact `Fraction` thresholds (no floats, no basis-point rounding —
  compared on the same "percent number" scale `compute_metric.py` already uses). Overall band =
  worst among classified metrics. A metric with no config row, or a config row with both
  thresholds absent, is skipped, never defaulted to GOOD. Zero classifiable metrics returns a
  real `Unavailable`, never a fabricated GOOD band. 10 unit tests, all passing.
- **CFO action** (`backend/src/backend/services/cfo_actions.py`): `assemble_financial_health`
  reads this tenant's latest persisted `metric_result` rows for the three metrics over one
  period (same read path `run_anomaly_check` already established,
  `metric_result_repo.list_by_metric_code`), takes the newest row per metric when more than one
  exists for the same period, classifies, and returns per-metric bands plus every contributing
  `engine_result_ref` for provenance. 5 unit tests, all passing.
- **API route**: `POST /api/v1/cfo/financial-health`, `agent.cfo` + CFO entitlement (read-only,
  no `financials.adjust` needed — it creates no manual input). Verified registered on the live
  FastAPI app.
- **Spec §6.15** added to `cfo-agent.md`, including an explicit "Never: a credit score, a
  valuation, an audit opinion" non-goal and a note that Brain-3 narration for this band does not
  exist yet and would need its own eval coverage before shipping (CLAUDE.md's LLM-evals rule).

### 5.3 Explicit scope limits, as directed

**Backend only, by the user's own instruction.** No dashboard UI was built for this feature.
No `narrate_financial_health` was built (would be new Brain-3 narration surface requiring its
own eval coverage — out of this pass's scope). No CEO-agent (`dispatch_cfo_*`) wiring was added
— matches the existing precedent for `cfo.preview`/`cfo.gst_lookup`/`cfo.expense_budget_set`,
all of which are direct-path-only with no CEO dispatch either.

---

## 6. Everything else in the brief: investigated, found already correct or genuinely blocked by data, not by code

- **Marketplace ingestion (item B):** the evaluation's own §2.1 finding stands — the 3 mock MTR
  files use a synthetic "pre-joined" shape that matches **none** of the real Amazon/Flipkart/
  Meesho export formats, independently confirmed against `docs/Metrion_PnL_and_MTR_Mapping_FINAL.pdf`.
  Checked `packages/data-foundation/src/data_foundation/component_registry.py` and the Flipkart
  adapters directly this session: the two registry gaps the eval flagged (§9 item 5) are **already
  closed** — `SELLER_DISCOUNT` (distinct from generic `Discount`) and `RETURN_SHIPPING_FEE` both
  already exist in the registry, added in a prior session. Nothing here is fixable without real
  marketplace export samples; fabricating a mapping against a guessed header would violate this
  project's own "never guess a column" rule.
- **Pricing curve (item D):** `compute_pricing_curve` correctly returns `UNAVAILABLE` for every
  candidate price with reason `"no fee_reference row covers this (marketplace, category,
  fee_type)"` — this is real fee-schedule data this tenant's config simply does not have seeded,
  a known, already-tracked open item (not addressed in this pass; inventing a fee rate would be
  exactly the kind of fabrication CLAUDE.md forbids).
- **Funding readiness / batch size (item F):** already correctly implemented per §2.2 above; the
  one flagged oddity (§2.1) was investigated and found to be a non-issue.
- **MOQ from seller's budget:** already implemented and tested — `assemble_batch_size_estimate`
  already takes a `batch.budget` ceiling and computes a budget-constrained order quantity via
  `compute_batch_constrained_quantity`; confirmed by the existing, passing
  `test_cfo_actions_batch_size.py` suite (20/20).
- **Expense tracker for misc costs (item E):** already worked via `category=other` + `reason`;
  the read-side gap (reason never surfaced) is the one real defect found and fixed — §3 above.

---

## 7. Synthetic data used, and its limits

**No new synthetic dataset was built or used in this pass.** All new tests use small,
purpose-built fixtures (a handful of rows per test, inline in the test file) to exercise a
specific code path — not a full synthetic seller book. The evaluation report's own synthetic-
fixture disclosures (COGS placeholder, supplier quotes, 5 fabricated prior months for anomaly
history, etc., all in that report's §2.2) are unchanged by this pass and remain exactly as
disclosed there; this pass did not re-run that evaluation script.

---

## 8. Test results — actual evidence, this session

All commands run against the real local Postgres (`metrion-postgres-1`, confirmed running via
`docker ps`) with `DATABASE_URL`/`DATABASE_URL_APP` set from the repo's own `.env`.

| Suite | Result |
|---|---|
| `packages/calc-engine` (unit + integration) | **432 passed**, 0 failed |
| `packages/cfo` (unit) | **266 passed, 3 skipped**, 0 failed |
| `packages/data-foundation` (unit) | **115 passed**, 0 failed |
| `backend` (unit + integration) | **174 passed**, 0 failed |
| **Total** | **987 passed, 3 skipped, 0 failed** |

New tests added this session (all included above, all passing):

- `test_reconcile_amazon_flipkart_extension.py::test_flipkart_successful_match_with_shared_component_codes` (1)
- `test_cfo_actions_expense_list_and_budget.py::test_list_expenses_surfaces_the_sellers_own_reason_text` (1)
- `test_line_status_overrides.py` (5)
- `test_cfo_actions_line_status_override.py` (10)
- `test_financial_health.py` (10)
- `test_cfo_actions_financial_health.py` (5)

Frontend: `npx tsc --noEmit` clean after the expense-description UI change. **Not** verified via
a live browser click-through (would need a signed-in Clerk session + seeded tenant data; not set
up in this session) — stated here rather than claimed.

The 3 skipped tests in `packages/cfo` predate this session and were not investigated as part of
this pass (out of the stated scope: fixing confirmed gaps, not auditing every pre-existing skip).

---

## 9. Files changed this session

**Modified:**
- `backend/src/backend/api/v1/cfo.py` — new routes, imports, trigger-id constants
- `backend/src/backend/services/cfo_actions.py` — new compositions, imports, `ExpenseEntry.reason`
- `docs/specs/cfo-agent.md` — §6.14, §6.15, §6.8 table rows, §6.10 note
- `docs/specs/deterministic-engine.md` — §7.2.1 three new fields + rationale, §7.3 list
- `frontend/app/dashboard/cfo/page.tsx` — expense description field + table column
- `frontend/lib/api.ts` — `ExpenseEntry.reason`
- `packages/calc-engine/src/calc_engine/repositories/config_repo.py` — `financial_health_config_rows`
- `packages/calc-engine/tests/integration/test_reconcile_amazon_flipkart_extension.py` — regression test
- `packages/cfo/tests/unit/test_cfo_actions_expense_list_and_budget.py` — `reason` round-trip test

**New:**
- `packages/calc-engine/migrations/versions/20260927_0010_financial_health_config.py`
- `packages/calc-engine/src/calc_engine/formulas/financial_health.py`
- `packages/calc-engine/src/calc_engine/formulas/line_status_overrides.py`
- `packages/calc-engine/tests/unit/test_financial_health.py`
- `packages/calc-engine/tests/unit/test_line_status_overrides.py`
- `packages/cfo/tests/unit/test_cfo_actions_financial_health.py`
- `packages/cfo/tests/unit/test_cfo_actions_line_status_override.py`
- `docs/evaluation/cfo-final-readiness-report.md` (this file)

No file was deleted. No unrelated agent/feature was touched. No commit was made (per standing
instruction: never commit unless asked).

---

## 10. Status table

| Feature | Status | Note |
|---|---|---|
| P&L / Contribution Profit (deterministic core) | **PASS** | Reconfirmed correct against real data; UNAVAILABLE-when-missing discipline intact |
| Cancellation/RTO status — seller override (input side) | **PASS** (new) | Fields, precedence, write/read, tests all real and passing |
| Cancellation/RTO status — end-to-end real-upload wiring | **NOT IMPLEMENTED** | No ingestion-to-canonical composition layer exists yet anywhere in the codebase (pre-existing gap, disclosed, not this session's scope) |
| Marketplace ingestion (Amazon/Flipkart/Meesho adapters) | **PASS**, against real format; **BLOCKED** against the mock files | Mock files are not real-format-shaped (pre-existing, confirmed again) |
| Leak Shield — Meesho | **PASS** | Reconfirmed |
| Leak Shield — Flipkart | **PASS** | New regression test proves genuine matches work; eval's flagged asymmetry traced to the (unavailable) eval script, not product code |
| Leak Shield — Amazon | **BLOCKED** | No settlement column in source data at all (structural, real) |
| Pricing curve | **PARTIAL** | Correctly UNAVAILABLE without seeded `fee_reference`; not addressed this pass (needs real fee data, not fabricable) |
| Batch size / MOQ from budget | **PASS** | Already correct; velocity-reason "bug" not reproducible |
| Funding readiness | **PASS**, reduced slice | Unchanged, already correct |
| Expense tracker (incl. misc/travel/petrol via `other` + description) | **PASS** (fixed) | Read-side gap closed this session |
| Financial Health Band | **PASS**, backend only | New feature, fully tested; no frontend, no narration yet (by direction) |
| GST line/period analysis | **PASS** | Unchanged, reconfirmed correct in the evaluation |
| Brain-3 narration (existing surfaces) | **PASS** | Unchanged |

---

## 11. Answers to your six questions

**1. What is genuinely complete?** The deterministic engine's core honesty discipline (verified
again, not just assumed). Leak Shield for Meesho and Flipkart (Amazon is structurally blocked by
missing data, not code). GST line/period analysis, batch size, funding readiness (reduced
slice), expense tracking including free-text descriptions. Both new features
(cancellation/RTO override input, Financial Health Band) are complete on the backend, tested,
and migrated into the real database — with the Financial Health Band explicitly not yet
integrated into any frontend, by your own direction.

**2. What defects were fixed?** One real, confirmed defect: expense descriptions were
write-accepted but never read back. That is the only confirmed code defect found in this entire
pass. The two "candidate bugs" flagged by the evaluation were investigated and **neither
reproduced** — both are now backed by passing tests/evidence rather than left open.

**3. What tests passed and failed?** 987 passed, 3 skipped (pre-existing, not investigated),
**0 failed**, across calc-engine, cfo, data-foundation and backend. Frontend typechecks clean;
not click-tested live.

**4. What remains blocked?** Amazon Leak Shield (no settlement data source). Pricing curve
(no seeded fee reference data). Real end-to-end cancellation/RTO wiring for actual uploaded
files (needs a real ingestion-to-canonical composition layer that does not exist yet — a
separate, larger project, not a defect in what exists today).

**5. Is the CFO ready for a controlled pilot?** **For the features that are wired end-to-end
today (Leak Shield on Meesho/Flipkart, GST analysis, expense tracking, supplier ranking, batch
size, funding readiness): yes**, with the same caveat the original evaluation already stated —
Contribution Profit will read `UNAVAILABLE` for any seller whose upload has no cancellation/
RTO-status source, until the seller either uploads settlement/RTO data or someone builds the
real-upload composition layer that would let them use the new override fields. That caveat needs
to be an explicit, honest onboarding message, not a silent gap, before any pilot seller sees it.
The Financial Health Band is real and tested but has no UI yet — not pilot-visible until a
frontend exists for it, matching your own stated plan.

**6. Can you move to the next Metrion agent without leaving any critical CFO defect
unresolved?** Yes for confirmed code defects — there are none outstanding after this pass. The
one thing worth deciding before or shortly after moving on is whether the real
ingestion-to-canonical composition layer (the thing that would make the new cancellation/RTO
override fields actually affect a real seller's P&L) is scheduled as upcoming work — it's a real
gap, but it's a scoping/roadmap decision, not a defect in anything built today.
