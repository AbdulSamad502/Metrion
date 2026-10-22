"""CFO 2.0 Phase 3a — the expense ledger (docs/specs/cfo-expense-ledger.md §5).

expense_entry               one typed row per seller expense (manual or from a file); signed paise; append-only
expense_class_assignment    suggested / confirmed accounting class per entry or per category; append-only
expense_period_declaration  the seller's explicit "no overhead expenses" for a period; append-only

The application role may only SELECT and INSERT (no UPDATE / DELETE / TRUNCATE): a correction is a new row that supersedes the old one and a
removal is a void row, so the history of every figure can be reproduced. ACTIVE is therefore computed (no later row names it in supersedes_id).

Revision ID: 20261021_0014
Revises: 20261021_0013
Create Date: 2026-10-21
"""
from __future__ import annotations

from alembic import op

revision = "20261021_0014"
down_revision = "20261021_0013"
branch_labels = None
depends_on = None

_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT ON {table} TO metrion_app;
-- default privileges would otherwise leave UPDATE/DELETE/TRUNCATE in place on a new table; the ledger is append-only
REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM metrion_app;
"""

_CLASSES = "('ALLOCATED_COST','OVERHEAD','OWNER_DRAWING','INVENTORY_PURCHASE','CAPITAL','TAX_ASSET','OTHER_UNCLASSIFIED')"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE expense_entry (
          id                uuid primary key default gen_random_uuid(),
          tenant_id         uuid not null,
          source            text not null,
          ingestion_run_id  uuid,                      -- the data-foundation run that produced a FILE row (no FK: separate migration chain)
          source_row_number int,
          entry_date        date not null,
          paid_date         date,
          amount_paise      bigint not null,           -- signed: a refund of an expense is negative
          gst_amount_paise  bigint,
          gst_treatment     text,
          category          text not null,
          vendor            text,
          description       text,
          payment_ref       text,
          marketplace       text,
          identity          text not null,
          hold              text not null default 'NONE',
          supersedes_id     uuid,
          is_void           boolean not null default false,
          created_by        uuid not null,
          created_at        timestamptz not null default now(),
          CONSTRAINT expense_entry_source_check CHECK (source IN ('FILE','MANUAL')),
          CONSTRAINT expense_entry_hold_check CHECK (hold IN ('NONE','POSSIBLE_DUPLICATE','MAY_OVERLAP_UNCONFIRMED')),
          CONSTRAINT expense_entry_gst_treatment_check CHECK (gst_treatment IS NULL OR gst_treatment IN ('INCLUDED_IN_COST','CREDITABLE')),
          CONSTRAINT expense_entry_category_check CHECK (length(btrim(category)) > 0),
          CONSTRAINT expense_entry_marketplace_check CHECK (marketplace IS NULL OR marketplace IN ('AMAZON','FLIPKART','MEESHO')),
          CONSTRAINT expense_entry_void_has_target CHECK (NOT is_void OR supersedes_id IS NOT NULL)
        );
        CREATE UNIQUE INDEX expense_entry_identity_uq ON expense_entry (tenant_id, identity) WHERE NOT is_void AND hold = 'NONE';
        CREATE INDEX expense_entry_date_idx ON expense_entry (tenant_id, entry_date);
        CREATE INDEX expense_entry_supersedes_idx ON expense_entry (tenant_id, supersedes_id) WHERE supersedes_id IS NOT NULL;
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="expense_entry"))

    op.execute(
        f"""
        CREATE TABLE expense_class_assignment (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null,
          scope         text not null,
          entry_id      uuid,
          category      text,
          class         text not null,
          state         text not null,
          suggested_by  text,
          reason        text,
          confirmed_by  uuid,
          confirmed_at  timestamptz,
          created_at    timestamptz not null default now(),
          supersedes_id uuid,
          CONSTRAINT expense_class_assignment_scope_check CHECK (scope IN ('ENTRY','CATEGORY')),
          CONSTRAINT expense_class_assignment_class_check CHECK (class IN {_CLASSES}),
          CONSTRAINT expense_class_assignment_state_check CHECK (state IN ('SUGGESTED','CONFIRMED')),
          CONSTRAINT expense_class_assignment_by_check CHECK (suggested_by IS NULL OR suggested_by IN ('RULE','MODEL')),
          CONSTRAINT expense_class_assignment_target_check CHECK (
            (scope = 'ENTRY' AND entry_id IS NOT NULL AND category IS NULL) OR (scope = 'CATEGORY' AND entry_id IS NULL AND category IS NOT NULL)),
          CONSTRAINT expense_class_assignment_confirm_check CHECK ((state = 'CONFIRMED') = (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL))
        );
        CREATE INDEX expense_class_assignment_entry_idx ON expense_class_assignment (tenant_id, entry_id) WHERE entry_id IS NOT NULL;
        CREATE INDEX expense_class_assignment_category_idx ON expense_class_assignment (tenant_id, category) WHERE category IS NOT NULL;
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="expense_class_assignment"))

    op.execute(
        """
        CREATE TABLE expense_period_declaration (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null,
          period_start  date not null,
          period_end    date not null,
          declaration   text not null,
          declared_by   uuid not null,
          declared_at   timestamptz not null default now(),
          supersedes_id uuid,
          CONSTRAINT expense_period_declaration_kind_check CHECK (declaration IN ('NO_OVERHEAD')),
          CONSTRAINT expense_period_declaration_order_check CHECK (period_end >= period_start)
        );
        CREATE INDEX expense_period_declaration_idx ON expense_period_declaration (tenant_id, period_start, period_end);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="expense_period_declaration"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS expense_period_declaration;")
    op.execute("DROP TABLE IF EXISTS expense_class_assignment;")
    op.execute("DROP TABLE IF EXISTS expense_entry;")
