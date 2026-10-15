"""expense ledger: expense_event and expense_status_event — calc-engine-owned (kickoff S3a; Round 9 R9-6).

Seller-entered input that Brain 1 reads through the ledger feed (`calc_engine/formulas/ledger_feed.py`), the same footing as `manual_adjustment` (data-foundation.md
§5.7: engine computed output and seller manual inputs the engine reads are calc-engine-owned). Specified in `docs/specs/expense-tracker.md` §5.1, EXP-01, EXP-05,
EXP-08 (INR only, so there is **no currency column**), Q21 (signed amount: cost positive, refund / credit note negative), Q24, Round 6 (review states) and Round 9.

- `expense_event` is the **immutable content** of one ledger record. A correction is a NEW record that points at the one it corrects (`corrects_expense_id`); a
  refund / credit note is a NEW record with a negative amount that points at its original (`refund_of_expense_id`). Nothing is ever updated or deleted.
- `expense_status_event` is the append-only history of the two **separate** status fields: the review state (`draft`, `pending_review`, `confirmed`, `voided`)
  and the payment status (`unpaid`, `partially_paid`, `paid`, `unknown`). A void is a review-state event with a reason, never a delete.

Both tables: `tenant_id`, FORCE row level security with the engine's strict tenant policy (`_TENANT_RLS_SQL` of `20260917_0001_engine_tables.py`), and UPDATE and
DELETE revoked from `metrion_app` at the grant level (as for `manual_adjustment`), so the privilege-boundary guard needs no change. Links are composite
(`tenant_id`, id) foreign keys, so a record can never reference another tenant's record. GST/ITC columns are deliberately not created here (G5).

Revision ID: 20261016_0013
Revises: 20260929_0012
Create Date: 2026-10-16
"""
from __future__ import annotations

from alembic import op

revision = "20261016_0013"
down_revision = "20260929_0012"
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
    op.execute(
        """
        CREATE TABLE expense_event (
          id                    uuid primary key,
          tenant_id             uuid not null,
          effective_date        date not null,
          vendor                text,
          description           text,
          category              text not null,
          cost_class            text not null
            CHECK (cost_class IN ('ADVERTISING', 'STORAGE', 'OVERHEAD', 'DIRECT')),
          treatment             text not null default 'incremental'
            CHECK (treatment IN ('incremental', 'already_in_settlement', 'informational')),
          amount_paise          bigint not null,          -- INR paise, signed: cost positive, refund / credit note negative (Q21)
          channel_scope         text,                      -- NULL = business-wide
          sku                   text,                      -- optional SKU tag (a manual tag stays flagged manual via origin)
          origin                text not null default 'MANUAL' CHECK (origin IN ('MANUAL', 'IMPORT')),
          source_validated      boolean not null default false,
          identifier            text,                      -- explicit ASIN / SKU id carried by the source data (Q29)
          source_reference      text,                      -- import row key, settlement reference or 'manual'
          corrects_expense_id   uuid,
          refund_of_expense_id  uuid,
          recurring             boolean not null default false,
          idempotency_key       text,
          created_by            uuid not null,
          created_at            timestamptz not null default now(),
          UNIQUE (tenant_id, id),
          FOREIGN KEY (tenant_id, corrects_expense_id)  REFERENCES expense_event (tenant_id, id),
          FOREIGN KEY (tenant_id, refund_of_expense_id) REFERENCES expense_event (tenant_id, id),
          CHECK (refund_of_expense_id IS NULL OR amount_paise < 0),
          CHECK (NOT (corrects_expense_id IS NOT NULL AND refund_of_expense_id IS NOT NULL))
        );
        CREATE INDEX expense_event_tenant_date_idx ON expense_event (tenant_id, effective_date);
        CREATE UNIQUE INDEX expense_event_idempotency_idx ON expense_event (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="expense_event"))
    op.execute("REVOKE UPDATE, DELETE ON expense_event FROM metrion_app;")

    op.execute(
        """
        CREATE TABLE expense_status_event (
          id                 uuid primary key default gen_random_uuid(),
          tenant_id          uuid not null,
          seq                bigint generated always as identity,
          expense_id         uuid not null,
          kind               text not null CHECK (kind IN ('REVIEW', 'PAYMENT')),
          review_state       text CHECK (review_state IN ('draft', 'pending_review', 'confirmed', 'voided')),
          payment_status     text CHECK (payment_status IN ('unpaid', 'partially_paid', 'paid', 'unknown')),
          paid_amount_paise  bigint,
          reason             text,
          idempotency_key    text,
          created_by         uuid not null,
          created_at         timestamptz not null default now(),
          FOREIGN KEY (tenant_id, expense_id) REFERENCES expense_event (tenant_id, id),
          CHECK (
            (kind = 'REVIEW'  AND review_state IS NOT NULL AND payment_status IS NULL AND paid_amount_paise IS NULL)
            OR
            (kind = 'PAYMENT' AND payment_status IS NOT NULL AND review_state IS NULL)
          ),
          CHECK (review_state IS DISTINCT FROM 'voided' OR reason IS NOT NULL)
        );
        CREATE INDEX expense_status_event_expense_idx ON expense_status_event (tenant_id, expense_id, kind, seq);
        CREATE UNIQUE INDEX expense_status_event_idempotency_idx ON expense_status_event (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="expense_status_event"))
    op.execute("REVOKE UPDATE, DELETE ON expense_status_event FROM metrion_app;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS expense_status_event;")
    op.execute("DROP TABLE IF EXISTS expense_event;")
