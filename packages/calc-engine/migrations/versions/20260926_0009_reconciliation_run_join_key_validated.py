"""reconciliation_run.join_key_validated — data-foundation.md §5.1.5 / §5.9 (line ~722),
deterministic-engine.md §5.12.2.

Extends `calc_engine.api.reconcile.reconcile()` from Meesho-only matching to also run against
Amazon and Flipkart (§5.1.5). Neither Amazon's nor Flipkart's join key (`order_ref` alone) has
been validated against a real populated export, unlike Meesho's `line_ref` (`sub_order_num`,
VERIFIED). This column is the explicit, queryable flag half of §5.12.2's "both a confidence cap
and an explicit flag, not one alone" mechanism — `true` only for a Meesho run, `false` for an
Amazon/Flipkart run, fixed for a run's whole lifetime (a run's `marketplace` never changes
mid-run), so it lives on the parent `reconciliation_run` row, never duplicated onto every child
`reconciliation_match`/`reconciliation_exception` row.

The spec's own column definition (`data-foundation.md` §5.9) gives no `DEFAULT` — this column
is populated explicitly by `reconcile()` on every future insert, never silently defaulted.

**Why `ADD COLUMN ... DEFAULT false` then `DROP DEFAULT`, not a separate backfill `UPDATE`.**
`reconciliation_run` carries `FORCE ROW LEVEL SECURITY` (§5.9's own migration, mirrored from
`settlement_line`'s real-per-tenant-rows pattern) — `FORCE` applies the tenant_isolation policy
to the table owner too, and `metrion_migrate` (the role this migration runs as, per this
package's `migrations/README.md`) is not `BYPASSRLS`. A plain backfill `UPDATE ... WHERE
join_key_validated IS NULL` is DML, so it is itself RLS-filtered: with no
`app.current_tenant_id` set, the policy's `USING` clause evaluates to `NULL`/false for every
row, and the `UPDATE` silently touches zero rows — invisibly leaving any real pre-existing row's
new column `NULL`, which then fails the later `SET NOT NULL`. `ADD COLUMN ... DEFAULT false` is
DDL, not DML — Postgres populates the new column at the storage/catalog level for every
existing physical row regardless of RLS, sidestepping this entirely. The immediately following
`DROP DEFAULT` removes the default from the column's definition going forward, so every future
insert (i.e. every future `reconcile()` run) must supply the value explicitly — matching the
spec's "boolean not null" (no default) column definition exactly, this is not a permanent
default left in place.

Revision ID: 20260926_0009
Revises: 20260925_0008
Create Date: 2026-09-26
"""
from __future__ import annotations

from alembic import op

revision = "20260926_0009"
down_revision = "20260925_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE reconciliation_run ADD COLUMN join_key_validated boolean NOT NULL DEFAULT false;")
    op.execute("ALTER TABLE reconciliation_run ALTER COLUMN join_key_validated DROP DEFAULT;")


def downgrade() -> None:
    op.execute("ALTER TABLE reconciliation_run DROP COLUMN IF EXISTS join_key_validated;")
