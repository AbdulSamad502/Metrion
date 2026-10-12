"""pi_research_run accounting columns (created_at, outcome_code, usage_due)

Approval prerequisite R0/R3 (docs/planning/ceo-approval-remediation-design.md). `pi_research_run` had no creation timestamp
(`started_at` is NULL while QUEUED), no outcome reason and no record of whether a run was billable, so a run could not be
classified as before/after the accounting cut-over, usage could not be decided once and stored, and failed / interrupted
/ successful runs could not be counted separately.

All three columns are NULLABLE with NO default and NO backfill: every pre-existing row keeps NULL, which is how a LEGACY
run is recognised (never billed retroactively, never reinterpreted). New runs set `created_at` in `create_run` and the
outcome / billing decision once when the run finishes.

Revision ID: 20261011_0002
Revises: 20261001_0001
Create Date: 2026-10-11
"""
from __future__ import annotations

from alembic import op

revision = "20261011_0002"
down_revision = "20261001_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE pi_research_run
          ADD COLUMN created_at   timestamptz,
          ADD COLUMN outcome_code text,
          ADD COLUMN usage_due    boolean;
        """
    )


def _refuse_if_rows_exist() -> None:
    """The tables are FORCE ROW LEVEL SECURITY, so a plain EXISTS from the migration role sees nothing: check each tenant under its own tenant context on a
    SEPARATE connection (NullPool, closed afterwards). The tenant setting must never be touched inside the migration's own transaction: `downgrade base` runs
    many downgrades in one transaction, and a leftover empty setting would make every later RLS cast fail."""
    from sqlalchemy import text

    with op.get_bind().engine.connect() as probe:
        # `tenant` belongs to the backend's migrations. In the CI order every package's up/down/up round trip runs BEFORE the backend is migrated, so on a database
        # where it does not exist yet there are no tenants, hence no stored accounting decisions to protect (this probe used to fail there: relation "tenant" does not exist).
        if probe.execute(text("SELECT to_regclass('public.tenant')")).scalar() is None:
            return
        for (tenant_id,) in probe.execute(text("SELECT id FROM tenant")).all():
            probe.execute(text("SELECT set_config('app.current_tenant_id', :t, false)"), {"t": str(tenant_id)})
            if probe.execute(text("SELECT 1 FROM pi_research_run WHERE usage_due IS NOT NULL OR outcome_code IS NOT NULL LIMIT 1")).first() is not None:
                raise RuntimeError("cannot downgrade 20261011_0002: pi_research_run rows carry stored accounting decisions that would be destroyed")


def downgrade() -> None:
    _refuse_if_rows_exist()
    op.execute(
        f"""
        ALTER TABLE pi_research_run
          DROP COLUMN IF EXISTS usage_due,
          DROP COLUMN IF EXISTS outcome_code,
          DROP COLUMN IF EXISTS created_at;
        """
    )
