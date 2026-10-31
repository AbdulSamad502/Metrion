"""CMO 3.0 M8: the seller's imported marketplace performance reports and the comparison-window setting (docs/specs/slim-cmo-agent.md section 6.21).

* `cmo_perf_import`: one row per imported file (who, when, which marketplace, the period the rows cover, the file's SHA-256). Unique per (tenant, sha256), so the same file can never be imported twice.
* `cmo_perf_line`: one row per (marketplace, report SKU, date). Every metric column is NULLABLE: a metric the report does not carry is NULL, never zero. Unique per (tenant, marketplace, report SKU, date),
  so a duplicate reporting record is never stored twice and an existing record is never overwritten.
* `cmo_perf_setting`: the seller's chosen comparison-window length (days), append-only, newest row is current. Bounded 7..90 by a CHECK.

All three are tenant-owned, FORCE RLS, `SELECT, INSERT` only for the application role (append-only: nothing is updated or deleted by the application). No column holds an inferred or estimated figure.

Revision ID: 20261031_0010
Revises: 20261031_0009
Create Date: 2026-10-31
"""
from __future__ import annotations

from alembic import op

revision = "20261031_0010"
down_revision = "20261031_0009"
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
        CREATE TABLE cmo_perf_import (
          id             uuid primary key default gen_random_uuid(),
          tenant_id      uuid not null,
          marketplace    text not null check (marketplace IN ('AMAZON','FLIPKART','MEESHO')),
          source_name    text not null check (length(btrim(source_name)) > 0),
          sha256         text not null check (sha256 ~ '^[0-9a-f]{64}$'),
          period_start   date not null,
          period_end     date not null,
          rows_saved     integer not null check (rows_saved >= 0),
          rows_skipped   integer not null check (rows_skipped >= 0),
          metrics        text[] not null,
          imported_by    uuid not null,
          imported_at    timestamptz not null default now(),
          check (period_end >= period_start),
          unique (tenant_id, id),
          unique (tenant_id, sha256)
        );
        CREATE INDEX cmo_perf_import_tenant_idx ON cmo_perf_import (tenant_id, marketplace, period_start);

        CREATE TABLE cmo_perf_line (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null,
          import_id     uuid not null,
          marketplace   text not null check (marketplace IN ('AMAZON','FLIPKART','MEESHO')),
          report_sku    text not null check (length(btrim(report_sku)) > 0),
          report_date   date not null,
          impressions   bigint check (impressions >= 0),
          clicks        bigint check (clicks >= 0),
          orders        bigint check (orders >= 0),
          units         bigint check (units >= 0),
          sales_paise   bigint check (sales_paise >= 0),
          unique (tenant_id, marketplace, report_sku, report_date),
          FOREIGN KEY (tenant_id, import_id) REFERENCES cmo_perf_import (tenant_id, id)
        );
        CREATE INDEX cmo_perf_line_range_idx ON cmo_perf_line (tenant_id, marketplace, report_date);

        CREATE TABLE cmo_perf_setting (
          id             uuid primary key default gen_random_uuid(),
          tenant_id      uuid not null,
          window_days    integer not null check (window_days BETWEEN 7 AND 90),
          set_by         uuid not null,
          set_at         timestamptz not null default now()
        );
        CREATE INDEX cmo_perf_setting_current_idx ON cmo_perf_setting (tenant_id, set_at DESC);
        """
    )
    for t in ("cmo_perf_import", "cmo_perf_line", "cmo_perf_setting"):
        op.execute(_RLS.format(t=t))


def downgrade() -> None:
    # Imported reports and the seller's setting are never deleted by a migration (see 0009): FORCE RLS is switched off for this transaction only so they can be COUNTED; any row refuses the downgrade.
    op.execute(
        """
        DO $$
        DECLARE n bigint;
        BEGIN
          LOCK TABLE cmo_perf_line, cmo_perf_import, cmo_perf_setting IN ACCESS EXCLUSIVE MODE;
          ALTER TABLE cmo_perf_line NO FORCE ROW LEVEL SECURITY;
          ALTER TABLE cmo_perf_import NO FORCE ROW LEVEL SECURITY;
          ALTER TABLE cmo_perf_setting NO FORCE ROW LEVEL SECURITY;
          SELECT (SELECT count(*) FROM cmo_perf_line) + (SELECT count(*) FROM cmo_perf_import) + (SELECT count(*) FROM cmo_perf_setting) INTO n;
          IF n > 0 THEN
            RAISE EXCEPTION 'cannot downgrade: imported performance reports or the seller window setting exist and are never deleted by a migration';
          END IF;
        END $$;
        DROP TABLE cmo_perf_line;
        DROP TABLE cmo_perf_import;
        DROP TABLE cmo_perf_setting;
        """
    )
