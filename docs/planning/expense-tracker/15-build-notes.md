# Expense Tracker build notes (kickoff Steps 3 to 5)

Started 2026-10-16 on `feat/pnl-calculator-and-expense-tracker` (no other branch). Authority: `phase1-decisions.md` (with errata and Round 9), then the frozen spec, then the engine spec. All integration tests ran on the scratch Postgres (port 5544); the dev database was never used. The new formula versions stay inactive; the release date (Q15) is not set; G6 has not passed.

## Slice log

### S3a — ledger migration (calc-engine)
- `packages/calc-engine/migrations/versions/20261016_0013_expense_ledger.py`: `expense_event` (immutable record content) and `expense_status_event` (append-only review-state and payment-status history, separate fields). Tenant id, FORCE RLS (engine policy), UPDATE and DELETE revoked from `metrion_app`. Composite `(tenant_id, id)` foreign keys so links cannot cross tenants; a refund is negative and linked, a correction is a new linked record, a void is a review-state event with a reason. No currency column (EXP-08). GST/ITC columns not created (G5).
- Tests: `packages/calc-engine/tests/integration/test_expense_ledger_tables.py` (15: RLS isolation, no-context fail-closed, cross-tenant write refused, grant-level append-only, closed enumerations, status shape, refund rules, cross-tenant links, idempotency key, migration round trip). Red first: 14 failed / 1 passed before the migration.
- `backend/scripts/tenant_data_inventory.py`: the two tables added to `UPLOADED_FINANCIAL_DATA` (the existing `test_tenant_data_inventory.py` failed with UNCLASSIFIED until then).
- Results: calc-engine integration 112 passed, 1 skipped; backend `test_tenant_data_inventory.py` + `test_privilege_boundary.py` 25 passed (no change to `KNOWN_APP_DELETABLE`: the new tables are not deletable).

## Proposals for owner review
(X2 bounds etc. are added here as they are implemented.)

## BLOCKED / skipped
- **S5d draft-from-chat:** not built, gated by G6 (G6 has not passed). Registry, effects and classifier code were not touched.
