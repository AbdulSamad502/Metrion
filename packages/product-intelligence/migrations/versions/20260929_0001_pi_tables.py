"""PI-owned tables: niche_brief, pi_research_run, product_candidate, product_review_insight,
supplier_lead, product_embedding, pi_tenant_config.

PI build plan (approved 2026-09-29) §2, §Checkpoint 1; `docs/specs/product-intelligence-agent.md`
§5, revised per the plan's Context/§0/§2 — marketplace-agnostic discovery (Tavily + YouTube,
Google Ads Keyword demand dropped at Checkpoint 0), `product_candidate`'s revised
opportunity-idea shape (no `marketplace_item_id`/`rank_position`/`rating`/`listed_price_paise`
— none obtainable without marketplace access), `score_explanation`/`opportunity_label`/
`web_price_signal` new fields, `product_review_insight.insight_source_type`. No `trend_signal`
table (Trends/keyword-trend work stays CMO's, not PI's). auth.md §7.3 for the RLS pattern.

Revision ID: 20260929_0001
Revises:
Create Date: 2026-09-29
"""
from __future__ import annotations

from alembic import op

revision = "20260929_0001"
down_revision = None
branch_labels = None
depends_on = None

# auth.md §7.3: FORCE ROW LEVEL SECURITY, SET LOCAL app.current_tenant_id, fail-closed via
# current_setting(..., true) returning NULL -> zero rows when context is unset. Applied
# identically to every tenant-owned table created here, including pi_tenant_config (its own
# tenant_id primary key does not exempt it from this pattern).
_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""


def upgrade() -> None:
    # pgvector is enabled once at the container level (docker/postgres-init/01-enable-pgvector.sql)
    # for local/dev/CI; IF NOT EXISTS makes this migration idempotent and self-sufficient against
    # any Postgres this package's history is ever replayed on, matching product_embedding's own
    # column type below.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # --- niche_brief (§6.1) --------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE niche_brief (
          id                     uuid primary key default gen_random_uuid(),
          tenant_id              uuid not null,
          status                 text not null,        -- DRAFT | READY | ARCHIVED
          category_text          text,
          budget_paise           bigint,
          target_price_min_paise bigint,
          target_price_max_paise bigint,
          marketplaces           text[],                -- subset of AMAZON|FLIPKART|MEESHO
          constraints            jsonb,
          created_by             uuid not null,
          created_at             timestamptz not null default now(),
          readied_at             timestamptz
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="niche_brief"))

    # --- pi_research_run (§6.8) -----------------------------------------------------------
    op.execute(
        """
        CREATE TABLE pi_research_run (
          id              uuid primary key default gen_random_uuid(),
          tenant_id       uuid not null,
          niche_brief_id  uuid not null references niche_brief(id),
          depth           text not null,        -- SHALLOW | COMPLETE
          trigger         text not null,        -- DIRECT_UI | CEO_REQUEST
          candidate_cap   int not null,
          status          text not null,        -- QUEUED|RUNNING|PARTIAL|COMPLETE|FAILED
          started_at      timestamptz,
          finished_at     timestamptz
        );
        CREATE INDEX pi_research_run_tenant_brief_idx
          ON pi_research_run (tenant_id, niche_brief_id, started_at desc);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="pi_research_run"))

    # --- product_candidate (PI build plan §2 — revised opportunity-idea shape, §0a/§0d/§0g) ---
    op.execute(
        """
        CREATE TABLE product_candidate (
          id                       uuid primary key default gen_random_uuid(),
          tenant_id                uuid not null,
          run_id                   uuid not null references pi_research_run(id),
          candidate_title          text not null,
          title_length             int,
          title_structure          jsonb,
          keyword_themes           jsonb,
          observed_category        text,
          category_confidence      text,
          image_url                text,
          image_source_url         text,
          demand_signal            jsonb,           -- keyword volume band; UNAVAILABLE until
                                                      -- Google Ads access exists (Checkpoint 0)
          engagement_signal        jsonb,           -- youtube view/comment counts, source=youtube
          web_price_signal         jsonb,           -- §0g: reference-only, never fed into Brain-1 math
          source_diversity         int not null default 0,
          proxy_score               numeric(6,2),
          proxy_state               text not null,   -- COMPUTED | UNAVAILABLE
          proxy_basis               jsonb not null,
          score_explanation         jsonb not null,  -- §0d: per-signal breakdown, plain-language
          opportunity_label         text not null default 'CANDIDATE_OPPORTUNITY',
          candidate_marketplaces    text[],
          source_urls               jsonb not null,
          capture_status            text not null,   -- OK|PARTIAL|UNAVAILABLE per source
          confidence                text not null    -- OBSERVED|DERIVED|UNAVAILABLE, PI-scoped
        );
        ALTER TABLE product_candidate
          ADD CONSTRAINT product_candidate_opportunity_label_check
          CHECK (opportunity_label = 'CANDIDATE_OPPORTUNITY');
        CREATE INDEX product_candidate_tenant_run_idx
          ON product_candidate (tenant_id, run_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="product_candidate"))

    # --- product_review_insight (§6.4, §0b — insight_source_type is a new required column) ---
    op.execute(
        """
        CREATE TABLE product_review_insight (
          id                    uuid primary key default gen_random_uuid(),
          tenant_id             uuid not null,
          candidate_id          uuid not null references product_candidate(id),
          insight_source_type   text not null,   -- YOUTUBE_COMMENTARY | WEB_EDITORIAL (§0b)
          sentiment_split       jsonb,
          rating_distribution   jsonb,
          complaint_themes      jsonb,
          positive_themes       jsonb,
          summarised_patterns   jsonb,
          reviews_considered    int,
          confidence            text not null,
          derivation_method     text not null,
          insight_state         text not null,   -- COMPLETE|DEGRADED|UNAVAILABLE
          degraded_reason       text,
          source_url            text not null,
          fetched_at            timestamptz not null,
          derived_at            timestamptz not null
        );
        ALTER TABLE product_review_insight
          ADD CONSTRAINT product_review_insight_source_type_check
          CHECK (insight_source_type IN ('YOUTUBE_COMMENTARY', 'WEB_EDITORIAL'));
        CREATE INDEX product_review_insight_tenant_candidate_idx
          ON product_review_insight (tenant_id, candidate_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="product_review_insight"))

    # --- supplier_lead (§6.6, unchanged from the original spec's shape) ------------------
    op.execute(
        """
        CREATE TABLE supplier_lead (
          id             uuid primary key default gen_random_uuid(),
          tenant_id      uuid not null,
          run_id         uuid not null references pi_research_run(id),
          supplier_name  text not null,
          source         text not null,   -- GOOGLE_PLACES | TAVILY | INDIAMART_LOOKUP
          contact        jsonb,
          locality       text,
          distance_km    numeric(6,2),
          category_match text,
          source_url     text,
          fetched_at     timestamptz not null
        );
        CREATE INDEX supplier_lead_tenant_run_idx
          ON supplier_lead (tenant_id, run_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="supplier_lead"))

    # --- product_embedding (C13: pgvector, no Qdrant — unchanged from the original spec) --
    op.execute(
        """
        CREATE TABLE product_embedding (
          id           uuid primary key default gen_random_uuid(),
          tenant_id    uuid not null,
          subject_type text not null,     -- CANDIDATE | THEME | CATEGORY
          subject_id   uuid not null,
          embedding    vector(768),       -- nomic-embed-text, dimension fixed
          model_name   text not null,
          model_dim    int not null,
          created_at   timestamptz not null default now()
        );
        CREATE INDEX product_embedding_tenant_subject_idx
          ON product_embedding (tenant_id, subject_type, subject_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="product_embedding"))

    # --- pi_tenant_config (§5, plus per-niche cache TTL columns per the PI build plan §2) --
    op.execute(
        """
        CREATE TABLE pi_tenant_config (
          tenant_id                    uuid primary key,
          candidate_retention_days     int not null default 90,
          supplier_lead_retention_days int not null default 90,
          tavily_cache_ttl_hours       int not null default 24,
          youtube_cache_ttl_hours      int not null default 24,
          updated_by                   uuid,
          updated_at                   timestamptz not null default now()
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="pi_tenant_config"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pi_tenant_config;")
    op.execute("DROP TABLE IF EXISTS product_embedding;")
    op.execute("DROP TABLE IF EXISTS supplier_lead;")
    op.execute("DROP TABLE IF EXISTS product_review_insight;")
    op.execute("DROP TABLE IF EXISTS product_candidate;")
    op.execute("DROP TABLE IF EXISTS pi_research_run;")
    op.execute("DROP TABLE IF EXISTS niche_brief;")
