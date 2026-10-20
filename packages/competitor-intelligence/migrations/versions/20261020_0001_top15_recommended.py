"""CI: a competitor search surfaces the top 15 matches (owner decision 2026-10-20), of which the seller picks up to their free slots (at most 5 tracked).

`ci_tenant_config.max_recommended_candidates` defaulted to 5; it becomes 15, and rows still holding the old default are moved with it. A tenant whose operator set another value keeps it.

Revision ID: 20261020_0001
Revises: 20261019_0001
Create Date: 2026-10-20
"""
from __future__ import annotations

from alembic import op

revision = "20261020_0001"
down_revision = "20261019_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE ci_tenant_config ALTER COLUMN max_recommended_candidates SET DEFAULT 15;
        UPDATE ci_tenant_config SET max_recommended_candidates = 15 WHERE max_recommended_candidates = 5;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE ci_tenant_config ALTER COLUMN max_recommended_candidates SET DEFAULT 5;
        UPDATE ci_tenant_config SET max_recommended_candidates = 5 WHERE max_recommended_candidates = 15;
        """
    )
