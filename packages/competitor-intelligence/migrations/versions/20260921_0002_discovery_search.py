"""Discovery Checkpoint 3: ci_search_query, ci_search_result (§5.4), plus the §6.12.1
discovery-budget columns and the §6.11/D11 discovery_enabled opt-out on ci_tenant_config.

competitor-intelligence-agent.md §5.4, §6.10-§6.12, C21-C23. auth.md §7.3 for the RLS
pattern, identical to every other tenant-owned table in this package.

Scope note: this migration does NOT create `ci_discovery_run`, `ci_candidate` or
`ci_candidate_relevance` (§5.4) — the discovery run state machine (§6.12.2), identity
resolution (§6.13) and relevance scoring (§6.14) are a later checkpoint. `discovery_run_id`
on `ci_search_query` is therefore a plain `uuid not null` column with no FK, exactly as the
spec's own §5.4 DDL declares it (no `references` clause) — a documented reference, not a
foreign key, the same convention `ci_discovery_run.seller_product_ref` uses for its own
cross-boundary reference.

Revision ID: 20260921_0002
Revises: 20260921_0001
Create Date: 2026-09-21
"""
from __future__ import annotations

from alembic import op

revision = "20260921_0002"
down_revision = "20260921_0001"
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
    # --- ci_tenant_config: §6.11/D11 opt-out + §6.12.1 locked budget defaults ------------
    op.execute(
        """
        ALTER TABLE ci_tenant_config ADD COLUMN discovery_enabled boolean NOT NULL DEFAULT true;
        ALTER TABLE ci_tenant_config ADD COLUMN max_discovery_queries_per_run int NOT NULL DEFAULT 20;
        ALTER TABLE ci_tenant_config ADD COLUMN max_raw_candidates int NOT NULL DEFAULT 50;
        ALTER TABLE ci_tenant_config ADD COLUMN max_analyzed_candidates int NOT NULL DEFAULT 20;
        ALTER TABLE ci_tenant_config ADD COLUMN max_recommended_candidates int NOT NULL DEFAULT 5;
        ALTER TABLE ci_tenant_config ADD COLUMN max_followup_searches_per_candidate int NOT NULL DEFAULT 3;
        ALTER TABLE ci_tenant_config ADD COLUMN discovery_run_timeout_seconds int NOT NULL DEFAULT 120;
        ALTER TABLE ci_tenant_config ADD COLUMN search_cache_ttl_hours int NOT NULL DEFAULT 24;
        """
    )

    # --- ci_search_query (NEW, §5.4) — one externally-sent query, post-redaction text only
    op.execute(
        """
        CREATE TABLE ci_search_query (
          id                    uuid primary key default gen_random_uuid(),
          tenant_id             uuid not null,
          discovery_run_id      uuid not null,      -- documented reference to a future
                                                     -- ci_discovery_run.id — no FK yet (see
                                                     -- module docstring); spec's own DDL has
                                                     -- no `references` clause here either.
          query_text            text not null,      -- POST-REDACTION text actually sent (§6.11 rule 4)
          query_kind            text not null,       -- PRODUCT_TERM | CATEGORY_TERM | FEATURE_TERM |
                                                      -- INTENT_PHRASE | SUBSTITUTE_TERM | KEYWORD_TERM
          is_followup           boolean not null default false,
          parent_candidate_id   uuid,
          sent_at               timestamptz not null,
          provider_name         text not null,
          result_count          int,
          error_code            text
        );
        CREATE INDEX ci_search_query_tenant_text_idx
          ON ci_search_query (tenant_id, query_text, sent_at desc);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ci_search_query"))

    # --- ci_search_result (NEW, §5.4) — raw provider results, cached (§6.12.1). LEAD ONLY
    # (C23, §6.10.3): result_title/result_snippet are never rendered as competitor facts.
    op.execute(
        """
        CREATE TABLE ci_search_result (
          id                     uuid primary key default gen_random_uuid(),
          tenant_id              uuid not null,
          search_query_id        uuid not null references ci_search_query(id),
          result_rank            int not null,
          result_url             text not null,
          result_title           text,
          result_snippet         text,
          fetched_at             timestamptz not null,
          cache_expires_at       timestamptz not null,
          provider_response_ref  text
        );
        CREATE INDEX ci_search_result_query_idx
          ON ci_search_result (search_query_id, result_rank);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ci_search_result"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ci_search_result;")
    op.execute("DROP TABLE IF EXISTS ci_search_query;")
    op.execute(
        """
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS search_cache_ttl_hours;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS discovery_run_timeout_seconds;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS max_followup_searches_per_candidate;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS max_recommended_candidates;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS max_analyzed_candidates;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS max_raw_candidates;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS max_discovery_queries_per_run;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS discovery_enabled;
        """
    )
