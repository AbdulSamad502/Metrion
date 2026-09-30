"""supplier_lead.candidate_id — closes a gap found during Checkpoint 2: the final
recommendation view needs to attribute a supplier lead to the specific candidate
`pi_supplier_lookup.py` found it for, not just the run. Nullable — a lead found via a
category-wide search with no single matching candidate is still a valid row.

Revision ID: 20260930_0001
Revises: 20260929_0001
Create Date: 2026-09-30
"""
from __future__ import annotations

from alembic import op

revision = "20260930_0001"
down_revision = "20260929_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE supplier_lead
          ADD COLUMN candidate_id uuid references product_candidate(id);
        CREATE INDEX supplier_lead_tenant_candidate_idx
          ON supplier_lead (tenant_id, candidate_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS supplier_lead_tenant_candidate_idx;
        ALTER TABLE supplier_lead DROP COLUMN IF EXISTS candidate_id;
        """
    )
