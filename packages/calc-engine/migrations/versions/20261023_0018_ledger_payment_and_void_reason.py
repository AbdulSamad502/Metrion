"""CFO expense ledger: payment states and an auditable void reason (docs/specs/cfo-expense-ledger.md 14.5).

expense_payment_event  append-only: the seller's statement about whether one ledger entry is UNPAID, PARTIALLY_PAID or PAID (with the paid amount when partial).
                       The latest event per entry is its payment state; no event = "not stated" (never assumed unpaid or paid). Payment state is information about cash;
                       it never changes a profit figure (an expense is dated by when it was incurred).
expense_entry.void_reason  the reason the seller gave for removing an entry; required on every NEW void row (the constraint is NOT VALID so older void rows stay readable).

Revision ID: 20261023_0018
Revises: 20261023_0017
Create Date: 2026-10-23
"""
from __future__ import annotations

from alembic import op

revision = "20261023_0018"
down_revision = "20261023_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE expense_entry ADD COLUMN void_reason text;
        ALTER TABLE expense_entry ADD CONSTRAINT expense_entry_void_reason_check
          CHECK (NOT is_void OR (void_reason IS NOT NULL AND length(btrim(void_reason)) BETWEEN 3 AND 300)) NOT VALID;

        CREATE TABLE expense_payment_event (
          id                uuid primary key default gen_random_uuid(),
          tenant_id         uuid not null,
          entry_id          uuid not null,
          payment_status    text not null,
          paid_amount_paise bigint,
          created_by        uuid not null,
          created_at        timestamptz not null default now(),
          CONSTRAINT expense_payment_status_check CHECK (payment_status IN ('UNPAID','PARTIALLY_PAID','PAID')),
          CONSTRAINT expense_payment_amount_check CHECK ((payment_status = 'PARTIALLY_PAID' AND paid_amount_paise IS NOT NULL AND paid_amount_paise > 0)
                                                       OR (payment_status <> 'PARTIALLY_PAID' AND paid_amount_paise IS NULL))
        );
        CREATE INDEX expense_payment_event_entry_idx ON expense_payment_event (tenant_id, entry_id, created_at DESC);
        ALTER TABLE expense_payment_event ENABLE ROW LEVEL SECURITY;
        ALTER TABLE expense_payment_event FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON expense_payment_event
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        GRANT SELECT, INSERT ON expense_payment_event TO metrion_app;
        REVOKE UPDATE, DELETE, TRUNCATE ON expense_payment_event FROM metrion_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS expense_payment_event; ALTER TABLE expense_entry DROP CONSTRAINT IF EXISTS expense_entry_void_reason_check; ALTER TABLE expense_entry DROP COLUMN IF EXISTS void_reason;")
