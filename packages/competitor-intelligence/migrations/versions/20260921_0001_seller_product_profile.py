"""seller_product_profile — competitor-intelligence-agent.md §5.5.1 Source 2 / §5.5.2, C31/D8.

The `SELLER_ENTERED` half of `SellerProduct` (§5.5): a minimal, always-editable manual
profile capturing the five fields `sales_line` cannot supply — `category`, `attributes`,
`keywords`, `price_paise`, `fulfillment_type`. `rating`/`review_count` are deliberately not
columns here — out of the form's scope by decision (C31, §5.5.2), and always `UNKNOWN`.

Tenant-owned like every other table in this package (§5 rule 15 restated for this surface,
auth.md §7.3): `tenant_id` on every row, RLS `FORCE`, no endpoint accepting a
client-supplied `tenant_id`. CI itself holds no write path to this table (AC22b, T72, T73) —
only the seller-product-profile API (`backend/api/v1/ci.py`) writes it.

One row per (tenant, product). `product_id` is the seller's own `sku` (or
`marketplace_item_id` when no `sku` exists) — a reference, not a foreign key, matching how
`ci_research_run.seller_product_ref` is documented (§5.4): `SellerProduct` is a merged
contract over a canonical view plus this table, not a single table with a shared key space.

Revision ID: 20260921_0001
Revises: 20260919_0002
Create Date: 2026-09-21
"""
from __future__ import annotations

from alembic import op

revision = "20260921_0001"
down_revision = "20260919_0002"
branch_labels = None
depends_on = None

# auth.md §7.3 — identical boilerplate to every other tenant-owned table in this package.
_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE seller_product_profile (
          id                uuid primary key default gen_random_uuid(),
          tenant_id         uuid not null,
          product_id        text not null,          -- sku, or marketplace_item_id when no sku
          category          text,
          attributes        jsonb,                  -- [{key, value}], §5.5
          keywords          text[],
          price_paise       bigint,                 -- signed BIGINT paise (C31) — never a float
          fulfillment_type  text,                   -- same enum space as competitor fulfillment_type
          updated_by        uuid not null,
          updated_at        timestamptz not null default now(),
          created_at        timestamptz not null default now(),
          unique (tenant_id, product_id)
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="seller_product_profile"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS seller_product_profile;")
