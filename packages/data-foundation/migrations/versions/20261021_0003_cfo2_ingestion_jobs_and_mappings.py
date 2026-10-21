"""CFO 2.0 data intelligence tables — docs/specs/cfo-data-intelligence.md §5.

ingestion_job            background ingestion with progress, heartbeat and a one-active-job-per-file guard
column_mapping           a per-tenant, per-file-shape mapping (PROPOSED / CONFIRMED / REJECTED / SUPERSEDED)
column_mapping_field     one row per mapped source column, with the validator's evidence and the decision taken
data_quality_report      the per-job quality summary the dashboard and CEO read
ad_report_line           advertising report rows (cfo-unified-financials.md §5), report_category ADVERTISING

Also adds the two lookup indexes the duplicate classifier needs on settlement_line (line_ref and
settlement_id are reference columns real settlement exports carry without an order_ref; the existing
natural-key index leads with order_ref and cannot serve them).

RLS mirrors `sales_line` (real tenant rows, `FORCE`, auth.md §7.3). Nothing here is seeded.

Revision ID: 20261021_0003
Revises: 20260924_0002
Create Date: 2026-10-21
"""
from __future__ import annotations

from alembic import op

revision = "20261021_0003"
down_revision = "20260924_0002"
branch_labels = None
depends_on = None

_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""

_ACTIVE_JOB_STATES = "('QUEUED','PROFILING','AWAITING_MAPPING_CONFIRMATION','PARSING','VALIDATING','COMMITTING')"


def upgrade() -> None:
    # --- ingestion_job ---------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE ingestion_job (
          id                   uuid primary key default gen_random_uuid(),
          tenant_id            uuid not null,
          report_file_id       uuid not null references report_file(id),
          adapter_id           text,                      -- set when a verified adapter was detected
          mapping_id           uuid,                      -- set when a confirmed mapping resolved the format (FK below)
          report_kind          text not null,             -- SALES | SETTLEMENT | EXPENSE | ADVERTISING
          sheet_name           text,
          status               text not null default 'QUEUED',
          progress_rows        bigint not null default 0,
          total_rows_estimate  bigint,
          error_code           text,
          error_detail         text,
          outcome              jsonb,                     -- final counts (read, accepted, rejected, duplicates, held, persisted)
          attempt              int not null default 1,
          created_by           uuid not null,
          created_at           timestamptz not null default now(),
          started_at           timestamptz,
          finished_at          timestamptz,
          heartbeat_at         timestamptz,
          CONSTRAINT ingestion_job_status_check CHECK (status IN
            ('QUEUED','PROFILING','AWAITING_MAPPING_CONFIRMATION','PARSING','VALIDATING','COMMITTING','DONE','FAILED','CANCELLED')),
          CONSTRAINT ingestion_job_kind_check CHECK (report_kind IN ('SALES','SETTLEMENT','EXPENSE','ADVERTISING')),
          CONSTRAINT ingestion_job_resolution_check CHECK (adapter_id IS NULL OR mapping_id IS NULL)
        );
        -- one active job per file: a double-click or a retry cannot start the same ingestion twice
        CREATE UNIQUE INDEX ingestion_job_one_active_per_file
          ON ingestion_job (tenant_id, report_file_id) WHERE status IN {_ACTIVE_JOB_STATES};
        CREATE INDEX ingestion_job_tenant_created_idx ON ingestion_job (tenant_id, created_at DESC);
        CREATE INDEX ingestion_job_stale_idx ON ingestion_job (heartbeat_at) WHERE status IN {_ACTIVE_JOB_STATES};
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ingestion_job"))

    # --- column_mapping --------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE column_mapping (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null,
          fingerprint   text not null,                    -- normalised header multiset + sheet name
          version       int not null,
          report_kind   text not null,
          marketplace   text,                              -- null for expense files
          sheet_name    text,
          header_row    int not null,
          status        text not null default 'PROPOSED',
          proposed_by   text not null,                    -- MODEL:<id> | ADAPTER_DERIVED | SELLER
          confirmed_by  uuid,
          confirmed_at  timestamptz,
          verified      boolean not null default false,   -- only a Metrion reviewer, against a real export, sets this
          evidence      jsonb not null default '{}'::jsonb,  -- global validator issues, missing required fields, set-aside columns
          created_at    timestamptz not null default now(),
          unique (tenant_id, fingerprint, version),
          CONSTRAINT column_mapping_status_check CHECK (status IN ('PROPOSED','CONFIRMED','REJECTED','SUPERSEDED')),
          CONSTRAINT column_mapping_kind_check CHECK (report_kind IN ('SALES','SETTLEMENT','EXPENSE','ADVERTISING')),
          CONSTRAINT column_mapping_confirmed_check CHECK (status <> 'CONFIRMED' OR (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL))
        );
        -- at most one CONFIRMED mapping per file shape
        CREATE UNIQUE INDEX column_mapping_one_confirmed
          ON column_mapping (tenant_id, fingerprint) WHERE status = 'CONFIRMED';
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="column_mapping"))
    op.execute(
        "ALTER TABLE ingestion_job ADD CONSTRAINT ingestion_job_mapping_fk FOREIGN KEY (mapping_id) REFERENCES column_mapping(id);"
    )

    # --- column_mapping_field --------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE column_mapping_field (
          id                    uuid primary key default gen_random_uuid(),
          tenant_id             uuid not null,
          mapping_id            uuid not null references column_mapping(id) ON DELETE CASCADE,
          source_column         text not null,
          source_column_index   int not null,             -- disambiguates duplicate headers
          canonical_field       text not null,
          component_code        text,
          transform             text not null,
          tax_inclusion         text,
          sign_convention       text,
          decision              text not null,
          evidence              jsonb not null default '{}'::jsonb,
          unique (mapping_id, source_column_index),
          CONSTRAINT column_mapping_field_decision_check CHECK (decision IN
            ('AUTO_ACCEPTED_BY_RULES','SELLER_CONFIRMED','SELLER_OVERRIDDEN','REJECTED','PENDING')),
          CONSTRAINT column_mapping_field_tax_check CHECK (tax_inclusion IS NULL OR tax_inclusion IN ('INCLUSIVE','EXCLUSIVE','UNKNOWN')),
          CONSTRAINT column_mapping_field_sign_check CHECK (sign_convention IS NULL OR sign_convention IN ('AS_IS','NEGATE'))
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="column_mapping_field"))

    # --- data_quality_report ---------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE data_quality_report (
          id                 uuid primary key default gen_random_uuid(),
          tenant_id          uuid not null,
          ingestion_job_id   uuid not null references ingestion_job(id),
          summary            jsonb not null,
          created_at         timestamptz not null default now(),
          unique (ingestion_job_id)
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="data_quality_report"))

    # --- ad_report_line --------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE ad_report_line (
          id                 uuid primary key default gen_random_uuid(),
          tenant_id          uuid not null,
          ingestion_run_id   uuid not null references ingestion_run(id),
          marketplace        text not null,
          campaign_ref       text,
          sku                text,
          report_date        date not null,
          spend              bigint not null,              -- signed paise
          attributed_sales   bigint,                       -- null where the report does not carry it (never zero)
          impressions        bigint,
          clicks             bigint,
          currency           char(3) not null default 'INR',
          source_row_number  int not null,
          source_row_json    jsonb not null,
          confidence         text not null                 -- VERIFIED | PROVISIONAL | DERIVED | MANUAL
        );
        CREATE INDEX ad_report_line_ingestion_run_idx ON ad_report_line (ingestion_run_id);
        CREATE INDEX ad_report_line_tenant_period_idx ON ad_report_line (tenant_id, marketplace, report_date);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ad_report_line"))

    # --- duplicate-classifier lookups on settlement_line -----------------------------------------
    op.execute(
        """
        CREATE INDEX settlement_line_tenant_line_ref_idx ON settlement_line (tenant_id, marketplace, line_ref) WHERE line_ref IS NOT NULL;
        CREATE INDEX settlement_line_tenant_settlement_id_idx ON settlement_line (tenant_id, marketplace, settlement_id) WHERE settlement_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS settlement_line_tenant_settlement_id_idx;")
    op.execute("DROP INDEX IF EXISTS settlement_line_tenant_line_ref_idx;")
    op.execute("DROP TABLE IF EXISTS ad_report_line;")
    op.execute("DROP TABLE IF EXISTS data_quality_report;")
    op.execute("DROP TABLE IF EXISTS column_mapping_field;")
    op.execute("ALTER TABLE ingestion_job DROP CONSTRAINT IF EXISTS ingestion_job_mapping_fk;")
    op.execute("DROP TABLE IF EXISTS column_mapping;")
    op.execute("DROP TABLE IF EXISTS ingestion_job;")
