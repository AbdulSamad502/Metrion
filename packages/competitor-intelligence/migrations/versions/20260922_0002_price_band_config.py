"""Checkpoint 6: ci_tenant_config.min_competitors_for_price_band (§5, §6.16.3).

competitor-intelligence-agent.md §6.16.3 / deterministic-engine.md §5.15.1 rule 1 — the
per-tenant configured minimum CI passes to compute_price_band, with the engine's own floor
of 3 that this configuration may raise but never lower (enforced in
calc_engine.formulas.price_band, not here).

Revision ID: 20260922_0002
Revises: 20260922_0001
Create Date: 2026-09-22
"""
from __future__ import annotations

from alembic import op

revision = "20260922_0002"
down_revision = "20260922_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ci_tenant_config ADD COLUMN min_competitors_for_price_band int NOT NULL DEFAULT 3;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS min_competitors_for_price_band;")
