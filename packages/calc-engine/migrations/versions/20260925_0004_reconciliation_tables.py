"""reconciliation_run / reconciliation_match / reconciliation_exception — calc-engine-owned
(data-foundation.md §5.7, CONFIRMED Phase C, C2: these are `reconcile()`'s own computed
OUTPUT, not raw data-foundation facts, the same precedent as `metric_result`/
`manual_adjustment`). Entity tree: `reconciliation_run` is the parent, `reconciliation_match`
and `reconciliation_exception` are its children (data-foundation.md §1.2):

```
reconciliation_run
├── reconciliation_match         (sales_line <-> settlement_line)
└── reconciliation_exception     (variance, orphan, unsettled, duplicate)
```

RLS pattern mirrored verbatim from the real-per-tenant-rows template
(`packages/data-foundation/migrations/versions/20260924_0002_settlement_line.py`'s
`_TENANT_RLS_SQL`) — these three tables carry real per-tenant rows, so they use the same
FORCE-RLS-plus-strict-tenant-match policy as `sales_line`/`settlement_line`, not
`20260917_0002_reconciliation_config.py`'s nullable-platform-default variant (which exists
for config tables where `tenant_id IS NULL` legitimately means "platform default" — that
does not apply here).

`sales_line_id`/`settlement_line_id` are deliberately bare UUID columns with no FK — they
reference data-foundation-owned tables, and this package "never authors DDL for tables it
doesn't own" (`packages/calc-engine/migrations/README.md`), the same convention
`line_component.settlement_line_id` used before its own FK existed (closed later by
`20260924_0002_settlement_line.py` once `settlement_line` existed in that package).

**Outcome/exception-type to table mapping — architect-approved this session (Phase D3),
schema documentation only; `reconcile()` itself is not implemented by this migration.**

data-foundation.md §5.2 defines seven `ReconciliationOutcome` values
(`calc_engine.formulas.leak.ReconciliationOutcome`). Only three of them ever produce a
`reconciliation_match` row; the reportable subset (plus two states that are not
`ReconciliationOutcome` values at all — `Collision` and `DUPLICATE_SETTLEMENT`) produce a
`reconciliation_exception` row instead. `UNSETTLED_WITHIN_LAG` is never persisted anywhere.

`reconciliation_match` — written ONLY when `resolve_match_candidates()` returns
`SingleMatch` AND `is_duplicate_settlement()` is `False` (exactly one resolved, non-duplicate
pair). `outcome` holds one of:
  - `MATCHED_EXACT`
  - `MATCHED_WITHIN_TOLERANCE`
  - `VARIANCE_EXCEEDS_TOLERANCE`
All three are written, including the "fine" two — for audit completeness, not only problems.

`reconciliation_exception` — written for the reportable subset. `exception_type` is one of:
  - `VARIANCE_EXCEEDS_TOLERANCE` — also has `reconciliation_match_id` set (the match row for
    the same pair); `amount_paise` = the variance (same value as that match row's
    `variance_paise`); `sales_line_id` and `settlement_line_id` both set; `component_code` set.
  - `ORPHAN_SETTLEMENT` — no `sales_line_id`; `settlement_line_id` set (the unmatched
    settlement row); `amount_paise` = that settlement row's `gross_settlement_amount`. No
    `reconciliation_match_id` (there is no match). `component_code` null.
  - `UNSETTLED_BEYOND_LAG` — from `should_report_unsettled_as_leak()` returning `True` (past
    both the lag and the grace period, data-foundation.md §5.8 Path B) — `sales_line_id` set,
    no `settlement_line_id`; `amount_paise` = that sales_line's invoice-side total. No
    `reconciliation_match_id`. `component_code` null.
  - `DUPLICATE_SETTLEMENT` — from `is_duplicate_settlement()` returning `True` —
    `settlement_line_id` set (the duplicate row), no `sales_line_id`; `amount_paise` = that
    duplicate settlement's `gross_settlement_amount`. No `reconciliation_match_id`.
    `component_code` null.
  - `AMBIGUOUS_MATCH` — from `resolve_match_candidates()` returning `Collision` —
    `settlement_line_id` set (the settlement row with the collision), no `sales_line_id`;
    `candidate_sales_line_ids` populated (a JSON array of the 2+ candidate sales_line UUIDs as
    strings); `amount_paise` = that settlement row's `gross_settlement_amount` (same
    convention as `ORPHAN_SETTLEMENT`, since there is no single candidate to compare against).
    No `reconciliation_match_id`. `component_code` null.

`UNSETTLED_WITHIN_LAG` is never persisted anywhere — no `reconciliation_match` row (there is
no settlement side at all) and no `reconciliation_exception` row (not reportable yet).

`leak_finding.reconciliation_exception_id`/`amount_paise`/`marketplace`
(`packages/cfo/migrations/versions/20260923_0001_cfo_tables.py`, already live) were designed
against this exact exception shape — `amount_paise`/`marketplace` are copied from here, never
recomputed by that table.

Revision ID: 20260925_0004
Revises: 20260917_0003
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op

revision = "20260925_0004"
down_revision = "20260917_0003"
branch_labels = None
depends_on = None

_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""


def upgrade() -> None:
    # --- reconciliation_run (parent) --------------------------------------------------------
    op.execute(
        """
        CREATE TABLE reconciliation_run (
          id                        uuid primary key default gen_random_uuid(),
          tenant_id                 uuid not null,
          marketplace               text not null,
          period_start              date not null,
          period_end                date not null,
          as_of_date                date not null,
          tolerance_config_version  int not null,
          formula_version           text not null,
          status                    text not null,
          settlement_line_count     int,
          sales_line_count          int,
          match_count               int,
          exception_count           int,
          started_at                timestamptz not null,
          finished_at               timestamptz
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="reconciliation_run"))

    # --- reconciliation_match (child) -------------------------------------------------------
    op.execute(
        """
        CREATE TABLE reconciliation_match (
          id                     uuid primary key default gen_random_uuid(),
          tenant_id              uuid not null,
          reconciliation_run_id  uuid not null references reconciliation_run(id),
          sales_line_id          uuid not null,
          settlement_line_id     uuid not null,
          component_code         text,
          outcome                text not null,
          variance_paise         bigint not null,
          confidence             text not null,
          formula_version        text not null,
          computed_at            timestamptz not null
        );
        CREATE INDEX reconciliation_match_run_idx ON reconciliation_match (reconciliation_run_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="reconciliation_match"))

    # --- reconciliation_exception (child) ---------------------------------------------------
    op.execute(
        """
        CREATE TABLE reconciliation_exception (
          id                        uuid primary key default gen_random_uuid(),
          tenant_id                 uuid not null,
          reconciliation_run_id     uuid not null references reconciliation_run(id),
          reconciliation_match_id   uuid references reconciliation_match(id),
          exception_type            text not null,
          sales_line_id             uuid,
          settlement_line_id        uuid,
          candidate_sales_line_ids  jsonb,
          marketplace               text not null,
          component_code            text,
          amount_paise              bigint not null,
          confidence                text not null,
          formula_version           text not null,
          computed_at               timestamptz not null,
          check (sales_line_id is not null or settlement_line_id is not null)
        );
        CREATE INDEX reconciliation_exception_run_idx ON reconciliation_exception (reconciliation_run_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="reconciliation_exception"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconciliation_exception;")
    op.execute("DROP TABLE IF EXISTS reconciliation_match;")
    op.execute("DROP TABLE IF EXISTS reconciliation_run;")
