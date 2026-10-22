# Step 3 proposals — open items (2026-10-16)

**Everything in this file is PROPOSED. Nothing is approved.** Each item gives options, a recommendation and the evidence from the code, read-only. No code, schema, migration or spec was changed. Authority: `phase1-decisions.md` over the frozen spec.

## 1. Controlled category list and category-to-cost-class mapping (Q5) — PROPOSED

**Evidence.**
- The legacy tracker accepts exactly five categories, `advertising, packaging, storage, logistics, other` (`_EXPENSE_CATEGORIES` in `backend/src/backend/services/cfo_actions.py`; the same list in `frontend/components/cfo/sections/ExpenseTrackerSection.tsx`; the engine registry fields `expense.advertising|packaging|storage|logistics|other`, engine §7.2.1).
- The ledger spec §6.2 (approved P5) fixes the **cost classes**: marketplace-derived (settlement only, never re-entered) · direct (packaging, inward freight; SKU optional) · advertising · business overhead · COGS (stays `cogs_per_unit`, never an expense amount). The engine feed (`calc_engine/formulas/ledger_feed.py`) currently takes `ADVERTISING | STORAGE | OVERHEAD | DIRECT` as its fixture vocabulary; an unknown class goes to the review queue.
- Round 6 approved a `StorageCosts` term and **no separate packaging or logistics pools** (they enter through the ledger).
- P9: TCS is never an operating expense; GST/ITC are informational and need CA review (G5). Treatment (`incremental` / `already_in_settlement` / `informational`) is a **separate per-record field**; engine §6.4 says amount/date similarity only flags overlap.

**Principle (from the owner's brief):** a category alone must never decide deductibility or settlement overlap. So the mapping below gives only a **default `cost_class`**; treatment and overlap are decided per record (overlap candidates are flagged, never matched automatically).

**Option A (recommended): category → default cost class, seller may change the class on the record, with the category list closed in V1.0.**

| Category | Default cost class | Notes (evidence) |
|---|---|---|
| Direct product costs | **BLOCKED as written** | If it means the cost of goods, COGS "stays `cogs_per_unit`, never an expense amount" (spec §6.2, approved). Owner to clarify: either remove it, or rename to a non-COGS direct cost (for example samples, inspection) mapped to DIRECT. |
| Packaging | DIRECT | SKU optional. Matches the legacy `packaging` category. |
| Inward freight | DIRECT | Risk of double counting with landed cost inside COGS (`supplier.quote` shipping and duties); the form should warn. |
| Advertising | ADVERTISING | SKU-level only under the Q29 rule; otherwise business-level. |
| Storage / warehousing | STORAGE | **Missing from the owner's list** but needed for the approved `StorageCosts` term and present in the legacy list. |
| Operating overhead (rent, utilities) | OVERHEAD | Outside contribution margin (EXP-06). |
| Software | OVERHEAD | Typical recurring entry. |
| Personnel | OVERHEAD | |
| Financial charges (bank, interest, payment-gateway) | OVERHEAD, flagged | Payment-gateway fees can already sit in settlement data: overlap candidate. |
| Taxes | informational (not subtracted) until CA review | GST/ITC/TCS must not be an operating expense (P9); only a CA can say which taxes are costs (G5). |
| Other | OVERHEAD, flagged `needs explanation` | The legacy `other` pool reduced contribution profit; existing rows stay under their original formula version (Q16). |

Option B: a fixed, non-overridable mapping. Simpler, but a category would then decide cost class and hide errors. Option C: no categories, the seller picks the cost class directly. Loses the closed list the spec P4 requires.

**Open points for the owner:** the BLOCKED row; whether to add Storage; how the five legacy categories map at cut-over (advertising→advertising, packaging→packaging, storage→storage, logistics→? — outbound logistics is already in settlement data, so it needs a decision, other→other).

## 2. X2 write-validation bounds — what the legacy code enforces today (PROPOSED bounds derived only from it)

**What `PUT /cfo/expenses` enforces today (read from code):**
- **Route model** (`api/v1/cfo.py::EnterExpenseRequest`): `target_type` must match `^(SKU|ACCOUNT|PERIOD)$`; `target_ref` and `field` must be non-empty strings; `value` is any JSON; `reason` is any string or null; `supersedes_id` optional.
- **Permission/entitlement:** `agent.cfo`, the CFO entitlement, then `financials.adjust` (in the handler).
- **Service** (`cfo_actions.enter_expense`): `field` must be in the nine-field registry set `_ALLOWED_MANUAL_ADJUSTMENT_FIELDS`; otherwise `ValueError` → HTTP 400.
- **Repository** (`manual_adjustment_repo.insert_adjustment`): a `supersedes_id` must name an earlier row of the same tenant, target and field; the value is stored as JSON uninterpreted ("does not interpret the §7.2.1 field registry's shapes").
- **Database:** `value jsonb not null`, no CHECK on amount, field or dates (`20260917_0001_engine_tables.py`: "not a DB CHECK constraint"); append-only (UPDATE/DELETE revoked).
- **On read** (`expense_pools.parse_expense_pool_adjustment`): `amount_paise` must be an `int` and not a `bool`; a malformed value raises rather than becoming zero. `gst_amount_paise` is optional int; `marketplace` optional string.
- **Dates:** none stored. A period is inferred at read time from `target_ref` shaped `YYYY-MM-DD` or `YYYY-MM` (`_expense_period_label_range`); anything else is excluded from period-filtered lists. The budget shape (`parse_expense_budget_adjustment`) does validate ISO dates and `period_end >= period_start`.
- **Client side** (`frontend/lib/pnlText.ts::rupeesToPaise`, used by the expense form via `toPaise`): rupees only, at most **11 digits** and at most two decimals, **no sign**; the comment there says the 11-digit ceiling is "the same ceiling the API enforces" for the Profit Calculator route.

**Finding:** the legacy expense route has **no numeric bounds** on amount or on string lengths, no sign rule, no date validation and no future-date rule server-side. So there is **no existing server-side limit to derive** for those. Engineering should propose the ledger bounds; the only numbers that already exist in the code are the **11-digit rupee ceiling** and the **two-decimal rule** (client parser, calculator API).

**PROPOSED rules derived only from existing code (no new numbers):**
1. Integer paise only; reject bool/float/string amounts (as `parse_expense_pool_adjustment` does).
2. Amount ceiling = the existing 11-rupee-digit limit (₹99,99,99,99,999), applied to the magnitude on the server as well as the client. Sign: a cost is positive and a refund/credit note negative (Q21), so the legacy "no sign" client rule does not carry over; zero allowed (explicit zero is an entered zero).
3. `effective_date` required and a real ISO date (as the budget parser does); no future-date limit proposed because none exists in the code.
4. Known `category`, `cost_class`, `treatment`, review state and payment status values only (closed lists), as the legacy route restricts `field` to a registry.
5. `supersedes`-style references must name a row of the same tenant (existing rule), here the linked original expense for refunds and corrections.
6. String-length caps (vendor, description, reason) and CSV/row-count limits: **engineering to propose**; the repository contains no existing limit to copy for the expense routes.

## 3. Where the ledger migration should live — PROPOSED

**Evidence.**
- Ownership rule written down in `docs/specs/data-foundation.md` §5.7 (confirmed Phase C): raw **ingested facts** → data-foundation (`sales_line`, `settlement_*`); engine **computed output and seller manual inputs the engine reads** → calc-engine (`metric_result`, `manual_adjustment`, `reconciliation_*`: "the same precedent as `metric_result`/`manual_adjustment`, which are calc-engine-owned despite depending on `sales_line`").
- Existing per-package migrations: `packages/calc-engine/migrations/versions/` (engine tables, reconciliation, config), `packages/cfo/migrations/versions/20260923_0001_cfo_tables.py` (`agent_data_request`, `leak_finding`), `backend/migrations/versions/` (platform and app tables: `tenant`, `membership`, `agent_run`, `investigation_*`, `shared_finding`, `metered_event`, `accounting_cutover`, WhatsApp). `backend/scripts/scratch_db.sh` migrates the packages in the order calc-engine, data-foundation, competitor-intelligence, cfo, product-intelligence, slim-cmo, then backend.
- RLS pattern: `_TENANT_RLS_SQL` in `20260917_0001_engine_tables.py`; `manual_adjustment` does `REVOKE UPDATE, DELETE ... FROM metrion_app`.
- App-role grant pattern: `docker/postgres-init/02-roles.sql` hands `metrion_app` full CRUD on every table through default privileges, and `backend/migrations/versions/20261012_0018_app_role_least_privilege.py` shows the corrective pattern: lists of tables revoked for the app role (`READ_ONLY_FOR_APP`, `APPEND_ONLY_FOR_APP = ("auth_audit", "metered_event")`), every statement guarded by `to_regclass`, SELECT left in place; and `tests/integration/test_privilege_boundary.py` pins `KNOWN_APP_DELETABLE`. An append-only ledger needs its own explicit `REVOKE UPDATE, DELETE` in its creating migration (as `manual_adjustment` does) and must be added to the privilege-boundary and tenant-data-inventory tests.

**Options.**
- **A (recommended): calc-engine-owned.** The ledger is seller-entered input that Brain 1 reads through the feed, exactly like `manual_adjustment`; the feed (`ledger_feed.py`) already lives in calc-engine; the append-only/RLS/revoke pattern is local to that package.
- **B: cfo-package-owned.** The CFO owns `agent_data_request`/`leak_finding`, and EXP-07 reinstated `expense_entry` as a ledger of the CFO; but the cfo package is the consumer, not the engine, and the ledger must be readable by the engine without a dependency from calc-engine onto `cfo`.
- **C: backend-owned.** Platform/app tables only; would make the engine depend on backend tables.
- **D: data-foundation** for CSV import batches only (raw ingested files), if import is ever built — not for the manual ledger.

**Also needed (any option):** the seed of the new formula definitions into `formula_definition` and any DB-level `is_trial` filter on the `shared_finding` trigger (see `11-engine-step-notes.md`) are migrations in the same step.

## 4. Does "True Margin" mean `ContributionProfit` or `TotalProfit`? — PROPOSED

**Where the term appears (repository search):**
- `docs/planning/phase-1-readiness-review.md` line 64: "**True Margin ownership** — Brain 1 is the single source of truth for all margin and profit calculation. CI supplies competitor-observed inputs only..." (a locked decision); line 243 (CI does not own a "True Margin engine"); line 270 ("Fee-schedule source: True Margin accuracy; the entire value proposition"); line 311 ("Historical True Margin uses the fees actually charged in the reports").
- `docs/planning/expense-tracker/archive/expense-tracker.md` line 11 (the superseded root draft).
- **Not in** any spec under `docs/specs/`, **not** in `deterministic-engine.md`, **not** in code or metric codes.

**Reading:** "True Margin" is the product's **umbrella name** for the engine-computed margin/profit family, not a metric code. The engine defines `ContributionProfit` and `CONTRIBUTION_MARGIN_PCT` (percentage); `TotalProfit` is an amount and **no total-profit margin percentage exists** (`TOTAL_PROFIT` has no `_PCT` metric).

**Options.**
- **A (recommended):** "True Margin" = the contribution margin (`CONTRIBUTION_MARGIN_PCT` over `ContributionProfit`) as the headline margin, with `TotalProfit` shown beside it as "profit after all expenses". Continuity with existing results and consumers; no new metric.
- **B:** "True Margin" = total profit, which would need a new `TOTAL_PROFIT` margin percentage metric (not defined; would need an engine-spec addition).
- **C:** keep the term out of the UI; label figures by their engine names.

The owner should say which; until then the dashboard copy should name the figures by their engine definitions.
