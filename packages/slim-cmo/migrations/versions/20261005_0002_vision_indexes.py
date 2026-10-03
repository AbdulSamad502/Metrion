"""P6 image analysis: idempotency and lookup indexes. No table, column or grant changes.

* `product_image_analysis_complete_triple_idx` - one COMPLETE analysis per (tenant, asset, provider, model,
  schema_version). It is PARTIAL (COMPLETE only) so a FAILED or DEGRADED attempt never blocks a retry. Concurrent
  identical analysis requests race to this index; the loser reads the winner's row (P6 decision 10: a duplicate
  provider call is accepted, no in-flight claim system).
* `vision_eval_run_latest_idx` - the trust gate and its read-time revocation ask "what is the LATEST evaluation
  for exactly this (provider, model, schema_version)?" on every analysis and every consumer read.
* `product_image_analysis_tenant_created_idx` - the per-tenant analysis rate limit counts a tenant's recent rows.

Revision ID: 20261005_0002
Revises: 20261003_0001
Create Date: 2026-10-05
"""
from __future__ import annotations

from alembic import op

revision = "20261005_0002"
down_revision = "20261003_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX product_image_analysis_complete_triple_idx
          ON product_image_analysis (tenant_id, image_asset_id, provider, model, schema_version)
          WHERE analysis_state = 'COMPLETE';
        CREATE INDEX vision_eval_run_latest_idx
          ON vision_eval_run (provider, model, schema_version, run_at DESC, id);
        CREATE INDEX product_image_analysis_tenant_created_idx
          ON product_image_analysis (tenant_id, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS product_image_analysis_tenant_created_idx;
        DROP INDEX IF EXISTS vision_eval_run_latest_idx;
        DROP INDEX IF EXISTS product_image_analysis_complete_triple_idx;
        """
    )
