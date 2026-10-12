"""investigation_turn: add the PLANNED status (vocabulary only)

Approval prerequisite R4 (docs/planning/ceo-approval-remediation-design.md). `orchestrator.py` used to coerce any status
outside {DELIVERED, CLARIFIED, DENIED, FAILED} to FAILED and the CHECK would have rejected a new one, so a planned turn
could never have been stored faithfully. This migration only widens the CHECK; NOTHING produces PLANNED yet (the approval
workflow is a later, separately reviewed checkpoint).

The downgrade refuses to run while a PLANNED row exists (it would otherwise have to rewrite or violate real history) and
otherwise restores the previous constraint exactly.

Revision ID: 20261011_0016
Revises: 20261011_0015
Create Date: 2026-10-11
"""
from __future__ import annotations

from alembic import op

revision = "20261011_0016"
down_revision = "20261011_0015"
branch_labels = None
depends_on = None

_OLD = "('RECEIVED','CAP_CHECKED','CLASSIFIED','PLAN_VALIDATED','DISPATCHED','GATHERED','COMPOSED','DELIVERED','CLARIFIED','DENIED','FAILED')"
_NEW = "('RECEIVED','CAP_CHECKED','CLASSIFIED','PLAN_VALIDATED','DISPATCHED','GATHERED','COMPOSED','DELIVERED','CLARIFIED','DENIED','FAILED','PLANNED')"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE investigation_turn DROP CONSTRAINT investigation_turn_status_check;
        ALTER TABLE investigation_turn ADD CONSTRAINT investigation_turn_status_check CHECK (status IN {_NEW});
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
            if probe.execute(text("SELECT 1 FROM investigation_turn WHERE status = 'PLANNED' LIMIT 1")).first() is not None:
                raise RuntimeError("cannot downgrade 20261011_0016: investigation_turn rows with status PLANNED exist")


def downgrade() -> None:
    _refuse_if_rows_exist()
    op.execute(
        f"""
        ALTER TABLE investigation_turn DROP CONSTRAINT investigation_turn_status_check;
        ALTER TABLE investigation_turn ADD CONSTRAINT investigation_turn_status_check CHECK (status IN {_OLD});
        """
    )
