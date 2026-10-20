"""CI: a configurable per-tenant competitor watchlist limit (owner decision 2026-10-18).

`ci_tenant_config.max_active_competitors` is NULL by default: no limit is applied and none is invented. An operator (or a future plan resolver)
sets it per tenant; the application role may read it but is never granted write access to it, so a seller cannot raise their own limit.

Revision ID: 20261019_0001
Revises: 20261018_0002
Create Date: 2026-10-19
"""
from __future__ import annotations

from alembic import op

revision = "20261019_0001"
down_revision = "20261018_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE ci_tenant_config ADD COLUMN max_active_competitors int;
        ALTER TABLE ci_tenant_config ADD CONSTRAINT ci_tenant_config_max_active_chk CHECK (max_active_competitors IS NULL OR max_active_competitors > 0);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE ci_tenant_config DROP CONSTRAINT IF EXISTS ci_tenant_config_max_active_chk;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS max_active_competitors;
        """
    )
