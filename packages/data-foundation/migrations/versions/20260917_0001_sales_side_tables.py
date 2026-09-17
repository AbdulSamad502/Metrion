"""sales-side canonical tables: report_file, ingestion_run, sales_line, line_component,
report_period, validation_finding

data-foundation.md §1.3, §1.4, §4.4, §6 (§4.4 and the tenant_id columns on ingestion_run/
report_period are Category C amendments — see those sections for the exact reasoning).
auth.md §7.3 for the RLS pattern. Settlement-side tables (settlement_line,
reconciliation_run/match/exception, sales_document/settlement_document) are explicitly out of
scope for this migration — no schema for them exists anywhere in data-foundation.md.

Revision ID: 20260917_0001
Revises:
Create Date: 2026-09-17
"""
from __future__ import annotations

from alembic import op

revision = "20260917_0001"
down_revision = None
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


def upgrade() -> None:
    # --- report_file (§1.3) -------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE report_file (
          id                uuid primary key default gen_random_uuid(),
          tenant_id         uuid not null,
          marketplace       text not null,          -- AMAZON | FLIPKART | MEESHO
          report_category   text not null,          -- SETTLEMENT | TAX | ORDER_STATUS | ADVERTISING
          content_sha256    char(64) not null,
          original_filename text not null,
          byte_size         bigint not null,
          storage_uri       text not null,
          uploaded_by       uuid not null,
          uploaded_at       timestamptz not null,
          unique (tenant_id, content_sha256)
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="report_file"))

    # --- ingestion_run (§1.3, + Category C tenant_id amendment) -------------------------
    op.execute(
        """
        CREATE TABLE ingestion_run (
          id                  uuid primary key default gen_random_uuid(),
          tenant_id           uuid not null,
          report_file_id      uuid not null references report_file(id),
          adapter_id          text not null,
          adapter_version     text not null,
          status              text not null,   -- PENDING|PARSING|VALIDATED|FAILED|SUPERSEDED
          row_count_read      int,
          row_count_accepted  int,
          row_count_rejected  int,
          started_at          timestamptz,
          finished_at         timestamptz
        );
        CREATE INDEX ingestion_run_report_file_idx ON ingestion_run (report_file_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ingestion_run"))

    # --- sales_line (§1.3) ---------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE sales_line (
          id                   uuid primary key default gen_random_uuid(),
          tenant_id            uuid not null,
          ingestion_run_id     uuid not null references ingestion_run(id),
          marketplace          text not null,
          order_ref            text,
          line_ref             text,
          invoice_ref          text,
          sku                  text,
          marketplace_item_id  text,
          item_title           text,
          hsn_sac              text,
          quantity             int,   -- nullable (Category C amendment) — no adapter has a
                                       -- spec-confirmed literal header for this column yet

          gross_item_amount    bigint,
          taxable_amount       bigint,
          total_invoice_amount bigint,
          currency             char(3) not null default 'INR',
          order_date           date,
          dispatch_date        date,
          invoice_date         date,
          document_type        text,
          supply_type          text,
          transaction_type     text,
          payment_method       text,
          return_status        text,
          source_row_number    int not null,
          source_row_json      jsonb not null,
          confidence           text not null   -- VERIFIED | PROVISIONAL | DERIVED | MANUAL
        );
        CREATE INDEX sales_line_ingestion_run_idx ON sales_line (ingestion_run_id);
        CREATE INDEX sales_line_tenant_natural_key_idx ON sales_line (tenant_id, marketplace, order_ref, line_ref, invoice_ref);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="sales_line"))

    # --- line_component (§1.4) ------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE line_component (
          id                  uuid primary key default gen_random_uuid(),
          tenant_id           uuid not null,
          sales_line_id       uuid references sales_line(id),
          settlement_line_id  uuid,      -- FK omitted: settlement_line has no schema yet (deferred)
          component_kind      text not null,   -- DISCOUNT | FEE | CHARGE | TAX | LEVY
          component_code      text not null,
          source_side         text not null,   -- INVOICE | SETTLEMENT
          amount              bigint not null,
          tax_amount          bigint,
          rate_pct            numeric(7,4),
          source_column       text not null,
          is_verified         boolean not null,
          note                text,
          check (sales_line_id is not null or settlement_line_id is not null)
        );
        CREATE INDEX line_component_sales_line_idx ON line_component (sales_line_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="line_component"))

    # --- report_period (§6, + Category C tenant_id amendment) --------------------------
    op.execute(
        """
        CREATE TABLE report_period (
          id                     uuid primary key default gen_random_uuid(),
          tenant_id              uuid not null,
          report_file_id         uuid not null references report_file(id),
          period_start           date not null,
          period_end             date not null,
          source                 text not null,   -- DECLARED_IN_FILE | DERIVED_FROM_ROWS
          declared_filing_month  int,
          declared_filing_year   int
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="report_period"))

    # --- validation_finding (§4.4, new table) -------------------------------------------
    op.execute(
        """
        CREATE TABLE validation_finding (
          id                  uuid primary key default gen_random_uuid(),
          tenant_id           uuid not null,
          ingestion_run_id    uuid not null references ingestion_run(id),
          sales_line_id       uuid references sales_line(id),
          rule_id             text not null,
          severity            text not null,   -- ERROR | WARNING | INFO
          message             text not null,
          source_row_number   int,
          created_at          timestamptz not null default now()
        );
        CREATE INDEX validation_finding_ingestion_run_idx ON validation_finding (ingestion_run_id);
        CREATE INDEX validation_finding_sales_line_idx ON validation_finding (sales_line_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="validation_finding"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS validation_finding;")
    op.execute("DROP TABLE IF EXISTS report_period;")
    op.execute("DROP TABLE IF EXISTS line_component;")
    op.execute("DROP TABLE IF EXISTS sales_line;")
    op.execute("DROP TABLE IF EXISTS ingestion_run;")
    op.execute("DROP TABLE IF EXISTS report_file;")
