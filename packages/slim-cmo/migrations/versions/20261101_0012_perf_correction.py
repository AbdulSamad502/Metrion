"""CMO 3.0 (additional capability "Listing Performance Intelligence", docs CMO_M8_PERFORMANCE.md section 6c): corrections to wrongly imported performance records.

* `cmo_perf_correction`: append-only. One row says "the effective values of this imported record are now these, instead of those", with the reason, who and when, the import and row it concerns, and which earlier
  correction it supersedes. The imported row in `cmo_perf_line` is NEVER updated or deleted (the application role still has SELECT and INSERT only on it): the original stays as evidence. Both the values
  before and after are stored on the correction, so the history is readable without joining anything. A void correction sets every effective metric to NULL ("not reported", never zero).
* Two partial unique indexes make the corrections of one record a single chain: at most one first correction per record, and at most one correction superseding any given correction, so two sellers or
  two tabs correcting the same record from the same starting point cannot both succeed (the second is refused as a conflict).
* `cmo_perf_line_effective`: a `security_invoker` view of each imported row with the newest correction applied (the corrected value where a correction exists, else the imported value). The metric queries read
  this view, so every total, rate and comparison uses the effective values while the original rows stay untouched. Row-level security of the underlying tables applies to the caller.
* `cmo_perf_line (tenant_id, id)` gets a unique constraint so a correction can reference it with a composite foreign key (a correction can never point at another tenant's record).

Tenant-owned, FORCE RLS, `SELECT, INSERT` only for the application role.

Revision ID: 20261101_0012
Revises: 20261101_0011
Create Date: 2026-11-01
"""
from __future__ import annotations

from alembic import op

revision = "20261101_0012"
down_revision = "20261101_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cmo_perf_line ADD CONSTRAINT cmo_perf_line_tenant_id_id_key UNIQUE (tenant_id, id);

        CREATE TABLE cmo_perf_correction (
          id                 uuid primary key default gen_random_uuid(),
          tenant_id          uuid not null,
          line_id            uuid not null,
          import_id          uuid not null,
          marketplace        text not null check (marketplace IN ('AMAZON','FLIPKART','MEESHO')),
          report_sku         text not null check (length(btrim(report_sku)) > 0),
          report_date        date not null,
          prev_impressions   bigint check (prev_impressions >= 0),
          prev_clicks        bigint check (prev_clicks >= 0),
          prev_orders        bigint check (prev_orders >= 0),
          prev_units         bigint check (prev_units >= 0),
          prev_sales_paise   bigint check (prev_sales_paise >= 0),
          new_impressions    bigint check (new_impressions >= 0),
          new_clicks         bigint check (new_clicks >= 0),
          new_orders         bigint check (new_orders >= 0),
          new_units          bigint check (new_units >= 0),
          new_sales_paise    bigint check (new_sales_paise >= 0),
          voided             boolean not null default false,
          changed            text[] not null check (cardinality(changed) >= 1),
          reason             text not null check (length(btrim(reason)) BETWEEN 3 AND 300),
          supersedes_id      uuid,
          created_by         uuid not null,
          created_at         timestamptz not null default now(),
          check (NOT voided OR (new_impressions IS NULL AND new_clicks IS NULL AND new_orders IS NULL AND new_units IS NULL AND new_sales_paise IS NULL)),
          check (new_clicks IS NULL OR new_impressions IS NULL OR new_clicks <= new_impressions),
          unique (tenant_id, id),
          FOREIGN KEY (tenant_id, line_id) REFERENCES cmo_perf_line (tenant_id, id),
          FOREIGN KEY (tenant_id, import_id) REFERENCES cmo_perf_import (tenant_id, id),
          FOREIGN KEY (tenant_id, supersedes_id) REFERENCES cmo_perf_correction (tenant_id, id)
        );
        CREATE UNIQUE INDEX cmo_perf_correction_first_idx ON cmo_perf_correction (tenant_id, line_id) WHERE supersedes_id IS NULL;
        CREATE UNIQUE INDEX cmo_perf_correction_chain_idx ON cmo_perf_correction (tenant_id, supersedes_id) WHERE supersedes_id IS NOT NULL;
        CREATE INDEX cmo_perf_correction_latest_idx ON cmo_perf_correction (tenant_id, line_id, created_at DESC);
        CREATE INDEX cmo_perf_correction_history_idx ON cmo_perf_correction (tenant_id, marketplace, report_sku, created_at DESC);

        ALTER TABLE cmo_perf_correction ENABLE ROW LEVEL SECURITY;
        ALTER TABLE cmo_perf_correction FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON cmo_perf_correction
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        REVOKE ALL ON cmo_perf_correction FROM metrion_app;
        GRANT SELECT, INSERT ON cmo_perf_correction TO metrion_app;

        CREATE VIEW cmo_perf_line_effective WITH (security_invoker = true) AS
        SELECT l.id, l.tenant_id, l.import_id, l.marketplace, l.report_sku, l.report_date,
               CASE WHEN c.id IS NULL THEN l.impressions ELSE c.new_impressions END AS impressions,
               CASE WHEN c.id IS NULL THEN l.clicks ELSE c.new_clicks END AS clicks,
               CASE WHEN c.id IS NULL THEN l.orders ELSE c.new_orders END AS orders,
               CASE WHEN c.id IS NULL THEN l.units ELSE c.new_units END AS units,
               CASE WHEN c.id IS NULL THEN l.sales_paise ELSE c.new_sales_paise END AS sales_paise,
               (c.id IS NOT NULL) AS corrected, c.id AS correction_id, COALESCE(c.voided, false) AS voided
        FROM cmo_perf_line l
        LEFT JOIN LATERAL (
          SELECT x.* FROM cmo_perf_correction x WHERE x.tenant_id = l.tenant_id AND x.line_id = l.id ORDER BY x.created_at DESC, x.id DESC LIMIT 1
        ) c ON true;
        REVOKE ALL ON cmo_perf_line_effective FROM metrion_app;
        GRANT SELECT ON cmo_perf_line_effective TO metrion_app;
        """
    )


def downgrade() -> None:
    # Corrections are the seller's audit record and are never deleted by a migration: FORCE RLS is switched off for this transaction only so they can be COUNTED; any row refuses the downgrade.
    op.execute(
        """
        DO $$
        DECLARE n bigint;
        BEGIN
          LOCK TABLE cmo_perf_correction IN ACCESS EXCLUSIVE MODE;
          ALTER TABLE cmo_perf_correction NO FORCE ROW LEVEL SECURITY;
          SELECT count(*) INTO n FROM cmo_perf_correction;
          IF n > 0 THEN
            RAISE EXCEPTION 'cannot downgrade: performance record corrections exist and are never deleted by a migration';
          END IF;
        END $$;
        DROP VIEW cmo_perf_line_effective;
        DROP TABLE cmo_perf_correction;
        ALTER TABLE cmo_perf_line DROP CONSTRAINT cmo_perf_line_tenant_id_id_key;
        """
    )
