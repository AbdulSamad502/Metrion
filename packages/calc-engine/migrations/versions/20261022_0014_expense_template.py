"""expense templates: recurring, amortized and per-order / per-unit expense definitions — calc-engine-owned (kickoff S4b; engine §5.18.1 / §5.18.2).

A template is the seller's standing instruction; it is NOT a ledger entry and is never counted. Entries are MATERIALISED from it into `expense_event` as `pending_review`
records (X10), one per calendar month, each with a deterministic idempotency key (`template:<template_key>:<yyyy-mm>`), so materialising twice creates nothing twice and a voided
materialised entry is not silently recreated. The amounts come from `calc_engine/formulas/expense_templates.py`.

Rows are immutable versions (`version` 1, 2, ... of one `template_key`): changing a rate, an amount or ending the template inserts a new version (`ended`); the newest
version of a key is current, and past periods keep the version that applied to them. Tenant id, FORCE row level security with the engine's strict tenant policy, and UPDATE
and DELETE revoked from `metrion_app` at the grant level (as for `expense_event`), so the privilege-boundary guard needs no change.

Revision ID: 20261022_0014
Revises: 20261016_0013
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op

revision = "20261022_0014"
down_revision = "20261016_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE expense_template (
          id                   uuid primary key,
          tenant_id            uuid not null,
          template_key         uuid not null,
          version              integer not null CHECK (version >= 1),
          kind                 text not null CHECK (kind IN ('MONTHLY', 'AMORTIZED', 'PER_ORDER', 'PER_UNIT')),
          vendor               text,
          description          text,
          category             text not null,
          cost_class           text not null CHECK (cost_class IN ('ADVERTISING', 'STORAGE', 'OVERHEAD', 'DIRECT')),
          treatment            text not null default 'incremental'
            CHECK (treatment IN ('incremental', 'already_in_settlement', 'informational')),
          amount_paise         bigint,                    -- MONTHLY: the monthly amount; AMORTIZED: the total to spread (INR paise)
          rate_paise           bigint CHECK (rate_paise IS NULL OR rate_paise >= 0),  -- PER_ORDER / PER_UNIT
          amortization_months  integer CHECK (amortization_months IS NULL OR amortization_months >= 1),
          start_month          date,                      -- AMORTIZED: first month of the schedule (first of a month)
          channel_scope        text,
          sku                  text,
          effective_from       date not null,
          effective_to         date,
          ended                boolean not null default false,
          created_by           uuid not null,
          created_at           timestamptz not null default now(),
          UNIQUE (tenant_id, id),
          UNIQUE (tenant_id, template_key, version),
          CHECK (effective_to IS NULL OR effective_to >= effective_from),
          CHECK (kind <> 'MONTHLY'   OR amount_paise IS NOT NULL),
          CHECK (kind <> 'AMORTIZED' OR (amount_paise IS NOT NULL AND amortization_months IS NOT NULL AND start_month IS NOT NULL)),
          CHECK (kind NOT IN ('PER_ORDER', 'PER_UNIT') OR rate_paise IS NOT NULL)
        );
        CREATE INDEX expense_template_key_idx ON expense_template (tenant_id, template_key, version);
        ALTER TABLE expense_template ENABLE ROW LEVEL SECURITY;
        ALTER TABLE expense_template FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON expense_template
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        GRANT SELECT, INSERT, UPDATE, DELETE ON expense_template TO metrion_app;
        REVOKE UPDATE, DELETE ON expense_template FROM metrion_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS expense_template;")
