"""expense assignment: a seller-chosen split of one ledger record across several SKUs — calc-engine-owned (kickoff S5c; engine §5.18.3, Q33).

Append-only: assigning (or re-assigning) inserts a new row; the newest row of a record is the current assignment, earlier rows stay as history. The split itself is computed
by the engine (`calc_engine/formulas/expense_assignment.py`) when the ledger feed is built; this table stores only the seller's choice: the basis (`EQUAL` or
`EXPLICIT_SHARES`) and the SKUs with, under `EXPLICIT_SHARES`, their basis points. Tenant id, FORCE row level security with the engine's strict tenant policy, a composite
(`tenant_id`, `expense_id`) foreign key so an assignment can never point at another tenant's record, and UPDATE and DELETE revoked from `metrion_app`.

Revision ID: 20261022_0015
Revises: 20261022_0014
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op

revision = "20261022_0015"
down_revision = "20261022_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE expense_assignment (
          id          uuid primary key default gen_random_uuid(),
          tenant_id   uuid not null,
          seq         bigint generated always as identity,
          expense_id  uuid not null,
          basis       text not null CHECK (basis IN ('EQUAL', 'EXPLICIT_SHARES')),
          shares      jsonb not null CHECK (jsonb_typeof(shares) = 'array' AND jsonb_array_length(shares) >= 1),  -- [{"sku": "...", "bp": 2500 | null}]
          created_by  uuid not null,
          created_at  timestamptz not null default now(),
          FOREIGN KEY (tenant_id, expense_id) REFERENCES expense_event (tenant_id, id)
        );
        CREATE INDEX expense_assignment_expense_idx ON expense_assignment (tenant_id, expense_id, seq);
        ALTER TABLE expense_assignment ENABLE ROW LEVEL SECURITY;
        ALTER TABLE expense_assignment FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON expense_assignment
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        GRANT SELECT, INSERT, UPDATE, DELETE ON expense_assignment TO metrion_app;
        REVOKE UPDATE, DELETE ON expense_assignment FROM metrion_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS expense_assignment;")
