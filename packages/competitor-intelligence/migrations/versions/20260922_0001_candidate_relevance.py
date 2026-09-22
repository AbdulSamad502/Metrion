"""Discovery Checkpoint 4: ci_discovery_run, ci_candidate, ci_candidate_relevance (§5.4).

competitor-intelligence-agent.md §5.4, §6.13 (identity resolution + gating), §6.14
(relevance scoring). auth.md §7.3 for the RLS pattern, identical to every other tenant-owned
table in this package.

This migration deliberately does not add foreign keys from `ci_search_query`/
`ci_search_result` back to `ci_discovery_run` (`discovery_run_id` stays the plain,
undocumented-reference column Checkpoint 3's migration already created) — the spec's own
§5.4 DDL for those two tables has no `references` clause on `discovery_run_id` either, and
retrofitting one is out of this checkpoint's scope (it would require backfilling/validating
Checkpoint 3 data this checkpoint has no visibility into). `ci_candidate.discovery_run_id`
similarly has no FK, for the same reason and on the same textual precedent.

`ci_candidate_relevance.candidate_id` DOES reference `ci_candidate(id)` — both tables are
introduced together here, so there is no ordering hazard.

Scope note: the discovery run state machine (§6.12.2), the human-in-the-loop review API and
any frontend work are explicitly out of scope for this checkpoint (Checkpoint 5).

Revision ID: 20260922_0001
Revises: 20260921_0002
Create Date: 2026-09-22
"""
from __future__ import annotations

from alembic import op

revision = "20260922_0001"
down_revision = "20260921_0002"
branch_labels = None
depends_on = None

# auth.md §7.3 — identical boilerplate to every other tenant-owned table in this package.
_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""


def upgrade() -> None:
    # --- ci_discovery_run (NEW, §5.4) — one discovery run; state machine is §6.12.2 (later
    # checkpoint), so `status` here is a plain text column with no enforced transition logic.
    op.execute(
        """
        CREATE TABLE ci_discovery_run (
          id                        uuid primary key default gen_random_uuid(),
          tenant_id                 uuid not null,
          seller_product_ref        text not null,
          requested_by              uuid not null,
          status                    text not null default 'QUEUED',
          partial_reason            text,
          failed_reason             text,
          stale_marked_at           timestamptz,
          provider_name             text,
          queries_used              int not null default 0,
          raw_candidate_count       int not null default 0,
          analyzed_candidate_count  int not null default 0,
          ci_capture_run_id         uuid,
          started_at                timestamptz,
          finished_at               timestamptz,
          created_at                timestamptz not null default now()
        );
        CREATE INDEX ci_discovery_run_tenant_product_idx
          ON ci_discovery_run (tenant_id, seller_product_ref, created_at desc);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ci_discovery_run"))

    # --- ci_candidate (NEW, §5.4) — tier/identity_match/seller_decision/evidence_status are
    # FOUR independent fields (§5.4's own "must stay distinguishable" table) and are never
    # merged into one status column.
    op.execute(
        """
        CREATE TABLE ci_candidate (
          id                    uuid primary key default gen_random_uuid(),
          tenant_id             uuid not null,
          discovery_run_id      uuid not null,      -- documented reference to
                                                     -- ci_discovery_run.id, no FK (see module
                                                     -- docstring; matches ci_search_query's
                                                     -- own convention for the same column).
          search_result_id      uuid,               -- null when added manually by the seller
          origin                text not null default 'DISCOVERED',  -- DISCOVERED | MANUAL_URL | PROMOTED_BY_SELLER
          candidate_url         text not null,
          marketplace           text,
          tier                  text not null default 'RAW',         -- RAW | ANALYZED | RECOMMENDED
          identity_match        text,               -- EXACT_MATCH | LIKELY_VARIANT | UNCERTAIN |
                                                     -- NOT_A_MATCH | null while tier = RAW
          identity_match_basis  jsonb,              -- required whenever identity_match is set
          seller_decision       text not null default 'NONE',        -- NONE | APPROVED | REJECTED
          seller_decided_by     uuid,
          seller_decided_at     timestamptz,
          evidence_status       text not null default 'AWAITING_EVIDENCE',  -- AWAITING_EVIDENCE | EVIDENCE_BACKED
          competitor_url_id     uuid,
          created_at            timestamptz not null default now(),
          unique (tenant_id, discovery_run_id, candidate_url)
        );
        CREATE INDEX ci_candidate_run_tier_idx
          ON ci_candidate (tenant_id, discovery_run_id, tier);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ci_candidate"))

    # --- ci_candidate_relevance (NEW, §5.4) — the relevance breakdown. One row per candidate
    # per scoring pass; never collapsed into a single number on ci_candidate (§6.14.3 requires
    # the per-axis numbers be renderable with the band, always — enforced in the Python layer
    # by RelevanceBreakdown, and here by keeping axis_scores/axis_states/axis_rationale as
    # their own required-shape jsonb columns rather than folding them into `band`).
    op.execute(
        """
        CREATE TABLE ci_candidate_relevance (
          id                 uuid primary key default gen_random_uuid(),
          tenant_id          uuid not null,
          candidate_id       uuid not null references ci_candidate(id),
          scored_at          timestamptz not null default now(),
          is_provisional     boolean not null,
          band               text not null,          -- HIGH | MEDIUM | LOW
          total_score        int not null,            -- 0..16
          axis_scores        jsonb not null,
          axis_states        jsonb not null,           -- per axis: KNOWN | UNKNOWN | CONFLICTED
          axis_rationale     jsonb,
          recalculated_from  uuid references ci_candidate_relevance(id)
        );
        CREATE INDEX ci_candidate_relevance_candidate_idx
          ON ci_candidate_relevance (tenant_id, candidate_id, scored_at desc);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ci_candidate_relevance"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ci_candidate_relevance;")
    op.execute("DROP TABLE IF EXISTS ci_candidate;")
    op.execute("DROP TABLE IF EXISTS ci_discovery_run;")
