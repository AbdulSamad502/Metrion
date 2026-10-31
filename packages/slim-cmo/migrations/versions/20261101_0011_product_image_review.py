"""CMO 3.0 M9: which of the seller's stored images belong to which product, and the image quality reviews run over them (docs/CMO-3.0/CMO_M9_IMAGE_QUALITY.md).

* `cmo_product_image`: append-only assignment events. One row says "this stored image (seller_image_asset) is now PRIMARY / SECONDARY / REMOVED for this SKU on this marketplace, as this kind of shot, at this
  position", by whom and when. The newest row per (sku, marketplace, asset) is current; earlier rows are the audit trail. Assigning never changes or deletes the image itself, and `seller_image_asset` and
  `product_image_analysis` are untouched by this migration.
* `cmo_image_review`: an immutable image quality report for one set of assignments, keyed by a hash of the exact set and the method version, so the same set reviewed twice is one row. The score is NULL unless
  the review was complete; the full report (dimensions, findings, recommendations, marketplace-rule status) is stored as it was shown.

Both are tenant-owned, FORCE RLS, `SELECT, INSERT` only for the application role. The composite foreign key makes it impossible for a row to point at another tenant's image.

Revision ID: 20261101_0011
Revises: 20261031_0010
Create Date: 2026-11-01
"""
from __future__ import annotations

from alembic import op

revision = "20261101_0011"
down_revision = "20261031_0010"
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
        CREATE TABLE cmo_product_image (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null,
          asset_id      uuid not null,
          sku           text not null check (length(btrim(sku)) > 0),
          marketplace   text not null check (marketplace IN ('AMAZON','FLIPKART','MEESHO')),
          role          text not null check (role IN ('PRIMARY','SECONDARY','REMOVED')),
          shot_type     text not null check (shot_type IN ('FRONT','BACK','SIDE','ANGLE','DETAIL','SIZE','USAGE','PACKAGING','OTHER')),
          position      integer not null check (position BETWEEN 1 AND 20),
          assigned_by   uuid not null,
          assigned_at   timestamptz not null default now(),
          FOREIGN KEY (tenant_id, asset_id) REFERENCES seller_image_asset (tenant_id, id)
        );
        CREATE INDEX cmo_product_image_current_idx ON cmo_product_image (tenant_id, sku, marketplace, asset_id, assigned_at DESC);

        CREATE TABLE cmo_image_review (
          id               uuid primary key default gen_random_uuid(),
          tenant_id        uuid not null,
          sku              text not null check (length(btrim(sku)) > 0),
          marketplace      text not null check (marketplace IN ('AMAZON','FLIPKART','MEESHO')),
          method_version   text not null check (length(btrim(method_version)) > 0),
          input_hash       text not null check (input_hash ~ '^[0-9a-f]{64}$'),
          score_state      text not null check (score_state IN ('COMPLETE','PARTIAL','NOT_CALCULABLE')),
          score            integer check (score BETWEEN 0 AND 100),
          image_count      integer not null check (image_count >= 0),
          report           jsonb not null,
          created_by       uuid not null,
          created_at       timestamptz not null default now(),
          check ((score_state = 'COMPLETE') = (score IS NOT NULL)),
          unique (tenant_id, sku, marketplace, input_hash)
        );
        CREATE INDEX cmo_image_review_latest_idx ON cmo_image_review (tenant_id, sku, marketplace, created_at DESC);
        """
    )
    for t in ("cmo_product_image", "cmo_image_review"):
        op.execute(_RLS.format(t=t))


def downgrade() -> None:
    # Assignments and reviews are the seller's record and are never deleted by a migration: FORCE RLS is switched off for this transaction only so they can be COUNTED; any row refuses the downgrade.
    op.execute(
        """
        DO $$
        DECLARE n bigint;
        BEGIN
          LOCK TABLE cmo_product_image, cmo_image_review IN ACCESS EXCLUSIVE MODE;
          ALTER TABLE cmo_product_image NO FORCE ROW LEVEL SECURITY;
          ALTER TABLE cmo_image_review NO FORCE ROW LEVEL SECURITY;
          SELECT (SELECT count(*) FROM cmo_product_image) + (SELECT count(*) FROM cmo_image_review) INTO n;
          IF n > 0 THEN
            RAISE EXCEPTION 'cannot downgrade: product image assignments or image reviews exist and are never deleted by a migration';
          END IF;
        END $$;
        DROP TABLE cmo_image_review;
        DROP TABLE cmo_product_image;
        """
    )
