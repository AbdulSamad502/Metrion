"""expense assignment: allow the data-driven bases NET_REVENUE, UNITS and ORDERS — calc-engine-owned (engine §5.18.3, Q33).

`expense_assignment.basis` accepted only `EQUAL` and `EXPLICIT_SHARES`. The data-driven bases split a record across the assigned SKUs in proportion to each SKU's own net revenue,
net units or order count for the period (section 5.10.1); the engine computes the split when the ledger feed is built, so the table still stores only the seller's choice (the
SKUs, with basis points only under `EXPLICIT_SHARES`). Only the check constraint changes: no row is touched, the table stays append-only.

Revision ID: 20261023_0016
Revises: 20261022_0015
Create Date: 2026-10-23
"""
from __future__ import annotations

from alembic import op

revision = "20261023_0016"
down_revision = "20261022_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE expense_assignment DROP CONSTRAINT IF EXISTS expense_assignment_basis_check;
        ALTER TABLE expense_assignment ADD CONSTRAINT expense_assignment_basis_check
          CHECK (basis IN ('EQUAL', 'EXPLICIT_SHARES', 'NET_REVENUE', 'UNITS', 'ORDERS'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM expense_assignment WHERE basis IN ('NET_REVENUE', 'UNITS', 'ORDERS');
        ALTER TABLE expense_assignment DROP CONSTRAINT IF EXISTS expense_assignment_basis_check;
        ALTER TABLE expense_assignment ADD CONSTRAINT expense_assignment_basis_check CHECK (basis IN ('EQUAL', 'EXPLICIT_SHARES'));
        """
    )
