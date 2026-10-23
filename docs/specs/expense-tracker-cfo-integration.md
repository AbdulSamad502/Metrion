# Expense Tracker ↔ CFO 2.0 integration contract

**Status:** DRAFT for owner approval · 2026-10-22 · written from the code on `main` and `origin/feat/cfo-2` (read-only). Integration is **NOT complete**: CP-E and the single-source-of-truth decision (D-INT-1) are open.
**Related:** `docs/planning/expense-tracker/` (tracker specs, `15-build-notes.md`), `cfo-expense-ledger.md` and `cfo-expense-model-options.md` (CFO 2.0, on `feat/cfo-2`), `cfo-dashboard.md` §5.3, `deterministic-engine.md` (Brain 1).

## 1. Audit: what the Expense Tracker has today (main)

| Area | State |
|---|---|
| Route and navigation | Own sidebar entry `cfo-expenses` and dashboard under CFO / Profit & Finance (`frontend/components/expenses/*`). Not an agent. |
| CRUD | Append-only: create, correct, void, refund; review state (draft / pending_review / confirmed / voided) and payment status as status events. UPDATE/DELETE revoked from `metrion_app`. |
| Categories | Closed list; each has a default cost class (ADVERTISING / STORAGE / OVERHEAD / DIRECT) and treatment (incremental / already_in_settlement / informational). |
| Recurring | Templates: monthly, spread over months (AM1–AM9, refund AM7), per-order and per-unit priced from the engine's count (PT1–PT8). |
| CSV import / export | Fixed template, safe re-upload (idempotent by source reference), duplicate review; accountant export. |
| SKU allocation | `expense_assignment` (append-only): EQUAL, EXPLICIT_SHARES, NET_REVENUE, UNITS, ORDERS, computed by the engine; unassignable remainder stays visible. |
| Permissions / tenancy | `agent.cfo` + CFO entitlement; writes `financials.adjust`; FORCE RLS; no client tenant id; one `agent_run` per data-changing write; idempotency keys. |
| Money | Signed integer paise; sums only in `calc_engine.formulas.ledger_feed` (Brain 1). Missing is unavailable, never zero. |

## 2. Audit: what CFO 2.0 (`feat/cfo-2`, CP-A to CP-D) has

A **second, parallel ledger**: `expense_entry` (seven classes, holds, identity digest, paid date, GST treatment), `expense_class_assignment` (suggested vs confirmed), `expense_period_declaration`, cost-ownership arbitration, `cfo_read_model_version` bumped on every write, engine seam `ExpenseLine`, routes `/cfo/ledger/*`, entitlement `cfo.expense_ledger`. `cfo-dashboard.md` §5.3 expects the *existing* Expense Tracker to be integrated, not replaced. CP-E is not built.

## 3. Gap list (exact, before integration)

| # | Gap | Kind |
|---|---|---|
| G-1 | Two stores for one concept with different vocabularies (cost class + treatment vs seven classes + hold). No agreed single source of truth. | Decision D-INT-1 |
| G-2 | Alembic: both sides add calc-engine revisions after `20260929_0012`; two heads. One chain's first `down_revision` must be re-pointed (e.g. tracker `20261016_0013` → `20261022_0018`) at merge time, then rechecked with `alembic heads`. | Merge task |
| G-3 | Module name clash: tracker `expense_ledger_repo.py` renamed to `expense_tracker_repo.py` on `main` (done, uncommitted). | Done |
| G-4 | Entitlement code `cfo.expense_ledger` is used by both. Needs one meaning or two codes. | D-INT-2 |
| G-5 | Tracker writes do not bump `cfo_read_model_version` (the table is on the CFO branch). Cached CFO answers can be stale after a tracker write. | Needs CFO branch (CP-E) |
| G-6 | No tracker → `ExpenseLine` adapter; the ledger-to-Contribution-Profit resolver for `ALLOCATED_COST` (AC-L8) is unbuilt on the CFO side. | CP-E |
| G-7 | Textual conflicts at merge: `tenant_data_inventory.py`, `api/v1/cfo.py`, `config.py`, `deterministic-engine.md`, `frontend/test-support/requestContract.json` (regenerate, do not hand-merge). | Merge task |
| G-8 | Tracker has no class-confirmation concept; CFO classification is seller-confirmed only. A mapping needs seller confirmation or an approved table. | D-INT-3 |
| G-9 | `CONTRIBUTION_PROFIT.v2` inactive (release date Q15 unset); G4/G5 (tax and retention wording) need CA/legal. | Owner |

## 4. The smallest compatible contract (built on main)

`GET /api/v1/cfo/expense-ledger/lines?period_start&period_end[&include_voided]` → `contractVersion: "EXPENSE_TRACKER_LINES.v1"` and `lines[]`.

* **Native vocabulary, no mapping.** Each line: `id, effectiveDate, amountPaise (signed int), category, costClass, treatment, reviewState, reviewReason, paymentStatus, paidAmountPaise (null = unknown, never 0), channelScope, sku (null = account-level), assignment {basis, shares[{sku,bp}]} | null, origin, sourceValidated, sourceReference, identifier, correctsExpenseId, refundOfExpenseId, recurring, createdAt`.
* **Read-only, tenant-scoped** (RLS plus `ctx.tenant_id`), same gates as the other tracker reads. Nothing is summed or classified here; totals stay in `POST …/summary` (Brain 1, `EXPENSE_LEDGER_FEED.v1`).
* **Semantics CFO must honour:** `treatment=informational` never affects profit; `already_in_settlement` is never added again (no double counting of settlement costs); only `incremental` adds. Only `confirmed` records count; draft / pending_review are visible but excluded; `voided` is excluded unless asked for. Account-level advertising and storage (`sku = null`, no assignment) are never given to a SKU; SKU-level amounts exist only from the seller's explicit assignment, computed by the engine and flagged manual.
* **Data states:** `origin` MANUAL / IMPORT / TEMPLATE with `sourceValidated` map to user-entered / imported / estimated(template) / verified(source-validated). Edit = correct (new record, original kept); delete = void (kept, excluded). History is never overwritten.
* **Backward compatible:** additive endpoint; existing routes and schemas unchanged. Contract changes bump `contractVersion`.
* **No LLM writes.** A model or CFO chat may read this contract; it may never create, correct, void or assign.

## 5. Proposed class mapping (NOT approved, not implemented)

Tracker → CFO classes would be: ADVERTISING / STORAGE → the CFO class for allocated platform costs (`ALLOCATED_COST`) only when the tracker treatment is `incremental`; OVERHEAD → CFO `OVERHEAD`; DIRECT → decided by the seller; `informational` → excluded from both profits; `already_in_settlement` → excluded (the settlement already carries it). Anything not mapped surfaces as `OTHER_UNCLASSIFIED` (listed, makes operating profit PROVISIONAL). No GST or ITC is inferred. This table needs approval (D-INT-3) and CA review (PV-E1).

## 6. Decisions needing approval

* **D-INT-1 Single source of truth: DECIDED 2026-10-22 by the owner: (B), the tracker is authoritative and CFO reads this contract through an `ExpenseLine` adapter (CP-E).** Options were: (A) CFO ledger is authoritative and the tracker UI writes to it; (B) tracker is authoritative and CFO reads this contract via an adapter; (C) two stores with arbitration; (D) one-way bridge. Recommendation: **B** for the least change (tracker has the UI, templates, import, assignment; the contract above is ready), with an `ExpenseLine` adapter in CP-E.
* **D-INT-2** `cfo.expense_ledger` entitlement: one code for both, or a new tracker code.
* **D-INT-3** Class mapping in §5, and whether the seller confirms it per category.
* **D-INT-4** Per-order template entries are snapshots (late uploads need void + manual entry); data-driven splits leave the whole amount unassigned if any SKU lacks its figure (from `15-build-notes.md`).

## 7. CP-E dependencies (not built; integration cannot be marked complete)

1. `ExpenseLine` adapter fed from this contract (per D-INT-1), plus the AC-L8 resolver.
2. `cfo_read_model_version` bump on every tracker write (needs the CFO table).
3. Replace the CFO Expenses tab placeholder (`ExpensesTab.tsx`) with a link/embedding of the tracker dashboard, keeping its own page.
4. Entitlement code resolution and the migration-chain fix (G-2, G-4).
5. Cross-suite tests after merge: ledger-to-engine golden scenarios using tracker data, with no double counting.

## 8. Handoff checklist for the CFO developer

- [ ] Read §3 and §6; get D-INT-1..3 answered before writing an adapter.
- [ ] Consume only `GET …/expense-ledger/lines` (check `contractVersion`); never read `expense_event` directly.
- [ ] Never sum in the adapter; build `ExpenseLine`s and let Brain 1 total.
- [ ] Skip `informational` and `already_in_settlement`; skip non-`confirmed` and voided; treat `paidAmountPaise = null` as unknown.
- [ ] Do not assign account-level ads/storage to SKUs; use `assignment` only.
- [ ] At merge: rename check (`expense_tracker_repo`), re-point one migration chain, rerun `alembic heads`, regenerate `requestContract.json`, merge `tenant_data_inventory.py` by hand.
- [ ] Add the `cfo_read_model_version` bump to tracker writes in the same transaction.
- [ ] Run both suites on a scratch DB only.

## 9. Tests

`backend/tests/integration/test_expense_tracker_lines_contract.py` (version, native fields, integer paise, assignment, window and voided, backwards window 422, tenant isolation, 401).
