"""pi_research_case + history/pin columns (docs/specs/ceo-pi-research-flow.md §5.1)

`pi_research_run` gains `pinned_at`, `archived_at`, `completed_at`; `pi_tenant_config` gains `history_unpinned_limit`; a new tenant-scoped
`pi_research_case` holds what a finished CEO-driven research case needs beyond the run's own rows: the final top-5 order, the deterministic
pre-rank explanation, the recommendation snapshot, the CFO result references the CEO attached, and the named gaps.

All new run columns are NULLABLE with no backfill: every pre-existing run keeps NULL (not pinned, not archived, no case). A pinned run can never be
archived (CHECK).

Revision ID: 20261014_0001
Revises: 20261011_0002
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op

revision = "20261014_0001"
down_revision = "20261011_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE pi_research_run
          ADD COLUMN pinned_at    timestamptz,
          ADD COLUMN archived_at  timestamptz,
          ADD COLUMN completed_at timestamptz,
          ADD CONSTRAINT pi_research_run_pinned_never_archived CHECK (NOT (pinned_at IS NOT NULL AND archived_at IS NOT NULL));
        CREATE INDEX pi_research_run_history_idx ON pi_research_run (tenant_id, archived_at, pinned_at);

        ALTER TABLE pi_tenant_config
          ADD COLUMN history_unpinned_limit int NOT NULL DEFAULT 10 CHECK (history_unpinned_limit BETWEEN 5 AND 10);

        CREATE TABLE pi_research_case (
          run_id               uuid primary key references pi_research_run(id),
          tenant_id            uuid not null,
          investigation_id     uuid,
          top5_candidate_ids   uuid[] not null,
          prerank_explanation  jsonb not null,
          recommendation       jsonb,
          cfo_refs             jsonb not null default '[]'::jsonb,
          gaps                 jsonb not null default '[]'::jsonb,
          created_at           timestamptz not null default now()
        );
        ALTER TABLE pi_research_case ENABLE ROW LEVEL SECURITY;
        ALTER TABLE pi_research_case FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON pi_research_case
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        -- no DELETE: history is archive-only, and a saved case is never deleted by the application role (tests/integration/test_privilege_boundary.py)
        GRANT SELECT, INSERT, UPDATE ON pi_research_case TO metrion_app;
        REVOKE DELETE, TRUNCATE ON pi_research_case FROM metrion_app;
        """
    )


def downgrade() -> None:
    # Pinned/archived flags and case rows are seller data: refuse to destroy them silently, same posture as 20261011_0002.
    from sqlalchemy import text

    with op.get_bind().engine.connect() as probe:
        if probe.execute(text("SELECT to_regclass('public.tenant')")).scalar() is not None:
            for (tenant_id,) in probe.execute(text("SELECT id FROM tenant")).all():
                probe.execute(text("SELECT set_config('app.current_tenant_id', :t, false)"), {"t": str(tenant_id)})
                if probe.execute(text("SELECT 1 FROM pi_research_case LIMIT 1")).first() is not None or probe.execute(
                    text("SELECT 1 FROM pi_research_run WHERE pinned_at IS NOT NULL LIMIT 1")
                ).first() is not None:
                    raise RuntimeError("cannot downgrade 20261014_0001: research cases or pinned reports would be destroyed")
    op.execute(
        """
        DROP TABLE IF EXISTS pi_research_case;
        ALTER TABLE pi_tenant_config DROP COLUMN IF EXISTS history_unpinned_limit;
        DROP INDEX IF EXISTS pi_research_run_history_idx;
        ALTER TABLE pi_research_run
          DROP CONSTRAINT IF EXISTS pi_research_run_pinned_never_archived,
          DROP COLUMN IF EXISTS completed_at,
          DROP COLUMN IF EXISTS archived_at,
          DROP COLUMN IF EXISTS pinned_at;
        """
    )
