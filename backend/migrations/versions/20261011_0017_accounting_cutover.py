"""accounting_cutover: durable, read-only records of when each accounting rule took effect

Approval prerequisite R0 (docs/planning/ceo-approval-remediation-design.md, Q-R4). Three billing rules change behaviour:
  CEO_UNIT_RULE_2    a CEO turn with any failed required leg consumes no CEO unit
  PI_USAGE_1         pi.discover / pi.supplier_lookup record one idempotent usage event per usable run
  NICHE_RUN_USAGE_1  research.niche_run usage counts successful runs only
Records created before a rule's `effective_at` are LEGACY: they are never re-evaluated, charged, refunded, repaired or
backfilled. The timestamp is the moment this migration ran on that database, so it is auditable and cannot drift with an
environment variable.

Platform-level table: no tenant_id and no RLS (like `plan`). `02-roles.sql` default privileges would hand `metrion_app`
full CRUD, so everything is revoked and only SELECT is granted back: the application can read cut-overs, never move them.

Revision ID: 20261011_0017
Revises: 20261011_0016
Create Date: 2026-10-11
"""
from __future__ import annotations

from alembic import op

revision = "20261011_0017"
down_revision = "20261011_0016"
branch_labels = None
depends_on = None

CODES = ("CEO_UNIT_RULE_2", "PI_USAGE_1", "NICHE_RUN_USAGE_1")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE accounting_cutover (
          code        text primary key CHECK (length(btrim(code)) > 0),
          effective_at timestamptz not null,
          recorded_at  timestamptz not null default now(),
          note         text not null CHECK (length(btrim(note)) > 0)
        );
        REVOKE ALL ON accounting_cutover FROM metrion_app;
        GRANT SELECT ON accounting_cutover TO metrion_app;
        INSERT INTO accounting_cutover (code, effective_at, note) VALUES
          ('CEO_UNIT_RULE_2',  now(), 'A CEO turn with any failed required leg consumes no CEO unit. Earlier turns are legacy: never re-evaluated, repaired or refunded.'),
          ('PI_USAGE_1',       now(), 'pi.discover / pi.supplier_lookup record one idempotent usage event per usable run. Earlier runs are legacy: never billed retroactively.'),
          ('NICHE_RUN_USAGE_1', now(), 'research.niche_run usage counts successful runs only. Earlier runs are legacy and are not backfilled.');
        """
    )


def _refuse_if_rows_exist() -> None:
    """The tables are FORCE ROW LEVEL SECURITY, so a plain EXISTS from the migration role sees nothing: check each tenant under its own tenant context on a
    SEPARATE connection (NullPool, closed afterwards). The tenant setting must never be touched inside the migration's own transaction: `downgrade base` runs
    many downgrades in one transaction, and a leftover empty setting would make every later RLS cast fail."""
    from sqlalchemy import text

    with op.get_bind().engine.connect() as probe:
        for (tenant_id,) in probe.execute(text("SELECT id FROM tenant")).all():
            probe.execute(text("SELECT set_config('app.current_tenant_id', :t, false)"), {"t": str(tenant_id)})
            if probe.execute(text("SELECT 1 FROM investigation_turn WHERE safety_result ? 'billing' LIMIT 1")).first() is not None:
                raise RuntimeError("cannot downgrade 20261011_0017: investigation_turn rows carry stored billing decisions")


def downgrade() -> None:
    # Refuse while stored CEO billing decisions exist: dropping the cut-over would orphan them (and a later re-upgrade would
    # stamp a NEW, later cut-over, silently turning decided turns into legacy ones).
    _refuse_if_rows_exist()
    op.execute(
        f"""
        DROP TABLE IF EXISTS accounting_cutover;
        """
    )
