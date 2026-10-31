"""CMO 3.0 B8: the two seller-confirmed facts a performance observation needs (docs/specs/slim-cmo-agent.md section 6.20).

Metrion cannot see a marketplace, so it can never know by itself (a) which SKU in an uploaded sales report is a given CMO product, or (b) when a saved listing version went live. Both are the SELLER'S
statement, recorded as their own rows and never inferred (not from titles, not from dates):

* `cmo_listing_sku_link`: this CMO product on this marketplace is that SKU in the seller's sales reports. Append-only; the newest row per (product, marketplace) is the current link.
* `cmo_listing_golive`: the seller says this saved version went live on this date. Append-only; the newest row per version is the current statement (a correction is a new row). Composite foreign key
  to `cmo_generation`, so a version of another tenant cannot be named.

Both are tenant-owned with FORCE RLS and `SELECT, INSERT` only for the application role. No column holds a sale, a figure or a claim of impact.

Revision ID: 20261031_0009
Revises: 20261031_0008
Create Date: 2026-10-31
"""
from __future__ import annotations

from alembic import op

revision = "20261031_0009"
down_revision = "20261031_0008"
branch_labels = None
depends_on = None

_RLS = """
ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON {t}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
REVOKE ALL ON {t} FROM metrion_app;
GRANT SELECT, INSERT ON {t} TO metrion_app;
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cmo_listing_sku_link (
          id                  uuid primary key default gen_random_uuid(),
          tenant_id           uuid not null,
          sku                 text not null check (length(btrim(sku)) > 0),
          marketplace         text not null check (marketplace IN ('AMAZON','FLIPKART','MEESHO')),
          report_sku          text not null check (length(btrim(report_sku)) > 0),
          confirmed_by        uuid not null,
          confirmed_at        timestamptz not null default now(),
          unique (tenant_id, id)
        );
        CREATE INDEX cmo_listing_sku_link_current_idx ON cmo_listing_sku_link (tenant_id, sku, marketplace, confirmed_at DESC);

        CREATE TABLE cmo_listing_golive (
          id             uuid primary key default gen_random_uuid(),
          tenant_id      uuid not null,
          generation_id  uuid not null,
          marketplace    text not null check (marketplace IN ('AMAZON','FLIPKART','MEESHO')),
          went_live_on   date not null,
          confirmed_by   uuid not null,
          confirmed_at   timestamptz not null default now(),
          unique (tenant_id, id),
          FOREIGN KEY (tenant_id, generation_id) REFERENCES cmo_generation (tenant_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
        );
        CREATE INDEX cmo_listing_golive_generation_idx ON cmo_listing_golive (tenant_id, generation_id, confirmed_at DESC);
        """
    )
    op.execute(_RLS.format(t="cmo_listing_sku_link"))
    op.execute(_RLS.format(t="cmo_listing_golive"))


def downgrade() -> None:
    # The seller's confirmations are never deleted by a migration. FORCE RLS hides every row from the migration role, so it is switched off for this transaction only (the owner then sees all rows)
    # to COUNT them; any row refuses the downgrade, and the failure rolls the whole migration back.
    op.execute(
        """
        DO $$
        DECLARE n bigint;
        BEGIN
          LOCK TABLE cmo_listing_sku_link, cmo_listing_golive IN ACCESS EXCLUSIVE MODE;
          ALTER TABLE cmo_listing_sku_link NO FORCE ROW LEVEL SECURITY;
          ALTER TABLE cmo_listing_golive NO FORCE ROW LEVEL SECURITY;
          SELECT (SELECT count(*) FROM cmo_listing_sku_link) + (SELECT count(*) FROM cmo_listing_golive) INTO n;
          IF n > 0 THEN
            RAISE EXCEPTION 'cannot downgrade: seller-confirmed SKU links or go-live dates exist and are never deleted by a migration';
          END IF;
        END $$;
        DROP TABLE cmo_listing_golive;
        DROP TABLE cmo_listing_sku_link;
        """
    )
