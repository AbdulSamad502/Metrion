"""CMO usage events: an `APPROVED` event kind - "approved for use in Metrion" (CMO 3.0 M6; docs/specs/slim-cmo-agent.md section 6.18.7, owner decision Q29).

`cmo_usage_kind_check` is widened from GENERATED / VIEWED / COPIED / MARKED_USED to also allow APPROVED. Nothing else about `cmo_result_usage_event` changes: it stays tenant-owned, FORCE RLS,
`SELECT, INSERT` only for the application role (append-only), tied to one immutable `cmo_generation` row, and the SYSTEM-only rule for GENERATED is untouched, so APPROVED can never be written
by the system surface and can never be forged as a GENERATED. The event consumes no unit and creates no metered event; it records that the seller approved that exact saved version for use in
Metrion. It does not mean the listing is published, live, accepted or verified by any marketplace, and no column or status for that exists.

Downgrade restores the narrower check and REFUSES, with a clear message and nothing half-applied, while any APPROVED event exists: a seller's recorded approval is never deleted by a migration.

Revision ID: 20261030_0028
Revises: 20261030_0027
Create Date: 2026-10-30
"""
from __future__ import annotations

from alembic import op

revision = "20261030_0028"
down_revision = "20261030_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cmo_result_usage_event DROP CONSTRAINT IF EXISTS cmo_usage_kind_check;
        ALTER TABLE cmo_result_usage_event ADD CONSTRAINT cmo_usage_kind_check
          CHECK (event_kind IN ('GENERATED','VIEWED','COPIED','MARKED_USED','APPROVED'));
        """
    )


def downgrade() -> None:
    # FORCE ROW LEVEL SECURITY hides the rows from the migration role, so this DELETE is blind. APPROVED rows are the seller's own recorded approvals; they are never deleted by a migration:
    # the narrower check cannot be added while any exist and the downgrade refuses clearly (one transaction, nothing half-applied).
    op.execute("ALTER TABLE cmo_result_usage_event DROP CONSTRAINT IF EXISTS cmo_usage_kind_check;")
    op.execute(
        """
        DO $$
        BEGIN
          ALTER TABLE cmo_result_usage_event ADD CONSTRAINT cmo_usage_kind_check CHECK (event_kind IN ('GENERATED','VIEWED','COPIED','MARKED_USED'));
        EXCEPTION WHEN check_violation THEN
          RAISE EXCEPTION 'cannot downgrade: APPROVED usage events exist and are never deleted by a migration';
        END $$;
        """
    )
