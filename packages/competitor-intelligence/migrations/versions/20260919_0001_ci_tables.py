"""CI-owned tables: competitor_url, ci_capture_run, competitor_snapshot,
competitor_review_insight, competitor_listing_insight, ci_tenant_config,
competitor_price_event

competitor-intelligence-agent.md §5, §5.1. auth.md §7.3 for the RLS pattern.

Direct-path scope only (§1a): this migration does not create any estimate_ref /
competitor_estimate table — the estimated-margin-range feature (C17/§5.2/§6.7) is deferred
pending a Brain-1 extension spec and has no schema here.

`ci_capture_run.trigger`'s comment lists WHATSAPP_CONFIRM as a value the spec defines, but no
application code in this pass ever writes it (§1a: WhatsApp-confirmed and CEO-routed
invocation are deferred pending CEO agent implementation). It is a plain `text` column with
no CHECK constraint — same convention as calc-engine's enum-like columns — so listing a
currently-unused value in the comment costs nothing and avoids a migration edit later.

Revision ID: 20260919_0001
Revises:
Create Date: 2026-09-19
"""
from __future__ import annotations

from alembic import op

revision = "20260919_0001"
down_revision = None
branch_labels = None
depends_on = None

# auth.md §7.3: FORCE ROW LEVEL SECURITY, SET LOCAL app.current_tenant_id, fail-closed via
# current_setting(..., true) returning NULL -> zero rows when context is unset. Applied
# identically to every tenant-owned table created here.
_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""


def upgrade() -> None:
    # --- competitor_url (§5) -------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE competitor_url (
          id           uuid primary key default gen_random_uuid(),
          tenant_id    uuid not null,
          marketplace  text not null,             -- AMAZON | FLIPKART | MEESHO
          url          text not null,
          label        text,                      -- seller's own name for this competitor
          linked_sku   text,                       -- optional: seller SKU this competes with
          status       text not null,              -- ACTIVE | UNREACHABLE | ARCHIVED
          added_by     uuid not null,
          created_at   timestamptz not null default now(),
          unique (tenant_id, url)
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="competitor_url"))

    # --- ci_capture_run (§5) — distinct from PI's paid niche research run ----------------
    op.execute(
        """
        CREATE TABLE ci_capture_run (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null,
          trigger       text not null,             -- DIRECT_UI | CEO_REQUEST | WHATSAPP_CONFIRM
                                                    -- (WHATSAPP_CONFIRM reserved, unwired — §1a)
          requested_by  uuid not null,
          url_ids       uuid[] not null,
          status        text not null,             -- QUEUED | RUNNING | PARTIAL | COMPLETE | FAILED
          started_at    timestamptz,
          finished_at   timestamptz
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ci_capture_run"))

    # --- competitor_snapshot (§5) — observed facts only. NO raw listing text (C16): no
    # title, no description, no bullets. -------------------------------------------------
    op.execute(
        """
        CREATE TABLE competitor_snapshot (
          id                    uuid primary key default gen_random_uuid(),
          tenant_id             uuid not null,
          competitor_url_id     uuid not null references competitor_url(id),
          ci_capture_run_id     uuid not null references ci_capture_run(id),
          captured_at           timestamptz not null,
          capture_status        text not null,       -- OK | BLOCKED | NOT_FOUND | PARSE_FAILED
          seller_name           text,                 -- business identity, a fact, not expression
          observed_category     text,                 -- as shown on the listing (Q8: taxonomy mapping open)
          category_confidence   text,                 -- OBSERVED | DERIVED | UNAVAILABLE
          listed_price_paise    bigint,
          mrp_paise             bigint,
          visible_discount_paise bigint,
          rating                numeric(2,1),
          rating_count          int,
          availability          text,                 -- IN_STOCK | OUT_OF_STOCK | UNKNOWN
          variant_key           text,                 -- A5
          source_url            text not null,        -- always link back, never replace the visit
          confidence            text not null         -- §5.1 vocabulary: OBSERVED | DERIVED | UNAVAILABLE
        );
        CREATE INDEX competitor_snapshot_url_captured_idx
          ON competitor_snapshot (competitor_url_id, variant_key, captured_at desc);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="competitor_snapshot"))

    # --- competitor_review_insight (§5) — C5/C6/C14: derived only, no verbatim text ------
    # MN7: snapshot_id is nullable-on-purge (§6.8 retention) — the snapshot row is removed,
    # the derived insight and its own provenance survive.
    op.execute(
        """
        CREATE TABLE competitor_review_insight (
          id                  uuid primary key default gen_random_uuid(),
          tenant_id           uuid not null,
          snapshot_id         uuid references competitor_snapshot(id) on delete set null,
          sentiment_split     jsonb,                -- {positive, neutral, negative} proportions
          rating_distribution jsonb,                -- {1..5: count}
          complaint_themes    jsonb,                -- [{theme, weight}] — themes, never quotes
          positive_themes     jsonb,
          summarised_patterns jsonb,                -- C6: required derived output
          reviews_considered  int,
          confidence          text not null,         -- §5.1 vocabulary
          derivation_method   text not null,         -- LOCAL_MODEL | LOCAL_HEURISTIC | STRUCTURED_ONLY
          insight_state       text not null,         -- COMPLETE | DEGRADED | UNAVAILABLE
          degraded_reason     text,                  -- required when insight_state <> COMPLETE
          source_url          text not null,
          fetched_at          timestamptz not null,
          derived_at          timestamptz not null
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="competitor_review_insight"))

    # --- competitor_listing_insight (§5) — C16/M5: derived attributes only, no copied text
    op.execute(
        """
        CREATE TABLE competitor_listing_insight (
          id                          uuid primary key default gen_random_uuid(),
          tenant_id                   uuid not null,
          snapshot_id                 uuid references competitor_snapshot(id) on delete set null,
          keyword_themes              jsonb,        -- themes, never the title itself
          title_length                int,
          title_structure             jsonb,
          feature_categories          jsonb,
          benefit_term_patterns       jsonb,
          differentiation_opportunities jsonb,
          bullet_count                int,
          image_count                 int,
          confidence                  text not null,
          derivation_method           text not null,
          insight_state               text not null,
          source_url                  text not null,
          fetched_at                  timestamptz not null,
          derived_at                  timestamptz not null
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="competitor_listing_insight"))

    # --- ci_tenant_config (§5) — thresholds and retention only. No WhatsApp state here:
    # enablement lives on auth.md whatsapp_binding.enabled; cadence/scheduling belong to
    # whatsapp-integration.md §6.9. tenant_id is itself the primary key (one row per tenant).
    op.execute(
        """
        CREATE TABLE ci_tenant_config (
          tenant_id                    uuid primary key,
          price_threshold_pct          numeric(5,2) not null default 5.00,   -- D2
          alert_on_availability_change boolean not null default true,       -- D3
          snapshot_retention_days      int not null default 90,             -- C19
          updated_by                   uuid,
          updated_at                   timestamptz not null default now()
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ci_tenant_config"))

    # --- competitor_price_event (§5) — MN7: from/to snapshot ids nullable-on-purge -------
    op.execute(
        """
        CREATE TABLE competitor_price_event (
          id                  uuid primary key default gen_random_uuid(),
          tenant_id           uuid not null,
          competitor_url_id   uuid not null references competitor_url(id),
          from_snapshot_id    uuid references competitor_snapshot(id) on delete set null,
          to_snapshot_id      uuid references competitor_snapshot(id) on delete set null,
          delta_paise         bigint not null,
          delta_pct           numeric(6,2) not null,
          direction           text not null,        -- INCREASE | DECREASE
          availability_change text,                 -- null | IN_TO_OUT | OUT_TO_IN
          threshold_breached  boolean not null,
          ci_capture_run_id   uuid not null references ci_capture_run(id),  -- MN14: provenance
          created_at          timestamptz not null default now(),
          observed_span       interval not null,    -- gap between the two snapshots
          alert_eligible      boolean not null       -- false when either snapshot is stale (D6)
        );
        CREATE INDEX competitor_price_event_tenant_url_idx
          ON competitor_price_event (tenant_id, competitor_url_id, created_at desc);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="competitor_price_event"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS competitor_price_event;")
    op.execute("DROP TABLE IF EXISTS ci_tenant_config;")
    op.execute("DROP TABLE IF EXISTS competitor_listing_insight;")
    op.execute("DROP TABLE IF EXISTS competitor_review_insight;")
    op.execute("DROP TABLE IF EXISTS competitor_snapshot;")
    op.execute("DROP TABLE IF EXISTS ci_capture_run;")
    op.execute("DROP TABLE IF EXISTS competitor_url;")
