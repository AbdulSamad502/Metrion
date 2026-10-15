# Expense Tracker build notes (kickoff Steps 3 to 5)

Started 2026-10-16 on `feat/pnl-calculator-and-expense-tracker` (no other branch). Authority: `phase1-decisions.md` (with errata and Round 9), then the frozen spec, then the engine spec. All integration tests ran on the scratch Postgres (port 5544); the dev database was never used. The new formula versions stay inactive; the release date (Q15) is not set; G6 has not passed.

## Slice log

### S3a — ledger migration (calc-engine)
- `packages/calc-engine/migrations/versions/20261016_0013_expense_ledger.py`: `expense_event` (immutable record content) and `expense_status_event` (append-only review-state and payment-status history, separate fields). Tenant id, FORCE RLS (engine policy), UPDATE and DELETE revoked from `metrion_app`. Composite `(tenant_id, id)` foreign keys so links cannot cross tenants; a refund is negative and linked, a correction is a new linked record, a void is a review-state event with a reason. No currency column (EXP-08). GST/ITC columns not created (G5).
- Tests: `packages/calc-engine/tests/integration/test_expense_ledger_tables.py` (15: RLS isolation, no-context fail-closed, cross-tenant write refused, grant-level append-only, closed enumerations, status shape, refund rules, cross-tenant links, idempotency key, migration round trip). Red first: 14 failed / 1 passed before the migration.
- `backend/scripts/tenant_data_inventory.py`: the two tables added to `UPLOADED_FINANCIAL_DATA` (the existing `test_tenant_data_inventory.py` failed with UNCLASSIFIED until then).
- Results: calc-engine integration 112 passed, 1 skipped; backend `test_tenant_data_inventory.py` + `test_privilege_boundary.py` 25 passed (no change to `KNOWN_APP_DELETABLE`: the new tables are not deletable).

### S3b — repository, rules, service routes (backend)
- `packages/calc-engine/src/calc_engine/repositories/expense_ledger_repo.py` (append-only reads/writes; current state = latest status event per kind; linked correction voids the original in the same transaction; idempotency keys), `backend/src/backend/services/expense_ledger_rules.py` (pure rules), `backend/src/backend/api/v1/expense_ledger.py` (routes under `/api/v1/cfo/expense-ledger`: `categories`, create, list, detail, `correct`, `refund`, `void`, `review`, `payment`), registered in `main.py`; `frontend/test-support/requestContract.json` regenerated (additive: +453 lines, no deletions).
- Every route has `agent.cfo` + the CFO entitlement gate (codes `cfo.expense_ledger.read|write`; no cap configured, so they pass until the owner configures one); every write also needs `financials.adjust` in the handler (no new key). One `agent_run` row (`DIRECT`, `cfo.expense_ledger`) per write that changes the ledger; an idempotent replay writes nothing and no run row; a request rejected at the edge (422/403/404) writes none. A write that raises after the ledger commit leaves no run row (the run row is written after the write succeeds): a known gap, noted for review.
- Manual entries default to review state `confirmed` (the person entering it is the reviewer) and payment status `unknown`; the caller may create `draft` or `pending_review`. This default is an implementation choice for owner review.
- Tests: `test_expense_ledger_repo.py` (9), `test_expense_ledger_rules.py` (22 unit), `test_expense_ledger_api.py` (32: 403 for a partner without `financials.adjust` on every write route, 200 for reads, entitlement 402, one agent_run per write, idempotent retry, void instead of delete, linked correction and refund, Q22, bounds, two-tenant isolation, legacy routes unchanged). The repo tests were written before the module but were not run red (the module did not exist); the rules and API tests were run red first.
- Test-environment note: `packages/calc-engine/tests/integration/test_migration_roundtrip.py` downgrades and re-upgrades the calc-engine tables on the shared scratch database, which re-creates them with the default full grants and makes `test_privilege_boundary.py` fail ("new app-deletable table") until the scratch DB is rebuilt (`scratch_db.sh down` then `up`). Rebuild it after running the calc-engine integration suite and before the backend integration suite.

## Proposals for owner review (R9-5)
All limits live in `backend/src/backend/services/expense_ledger_rules.py` (single place to change) and are served to the UI by `GET /cfo/expense-ledger/categories`:
| Limit | Value | Basis |
|---|---|---|
| Amount magnitude | 9,999,999,999,999 paise (11 rupee digits) | existing: `frontend/lib/pnlText.ts` and the Profit Calculator API ceiling |
| Amount type | integer paise, not bool/float/string; zero allowed; a cost is ≥ 0, a refund < 0 | existing: `parse_expense_pool_adjustment`; Q21 |
| Vendor / description / reason | 120 / 500 / 500 characters | PROPOSED (no equivalent in the legacy route) |
| SKU / source reference / idempotency key | 120 / 200 / 120 characters | PROPOSED |
| Page size | default 50, maximum 200 | PROPOSED |
| Vendor text (Q22) | refuse a currency symbol or code, a grouped or decimal number (1,200.50), or five or more digits; allow short numerals | Q22 decision; exact pattern is the implementer's, PROPOSED for review |
| Date | a valid ISO date; no future-date or age limit | none exists in the legacy code, so none is invented |
| CSV size / rows | (S5a) see below | |
(X2 bounds etc. are added here as they are implemented.)

## BLOCKED / skipped
- **S5d draft-from-chat:** not built, gated by G6 (G6 has not passed). Registry, effects and classifier code were not touched.
