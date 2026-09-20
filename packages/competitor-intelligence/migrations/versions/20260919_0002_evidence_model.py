"""Evidence model: competitor_evidence, competitor_snapshot_field, ci_digest_subscription
(NEW), plus additions to competitor_url, competitor_snapshot, ci_tenant_config, ci_capture_run.

competitor-intelligence-agent.md §5, §5.3 (as revised for the seller-evidence pivot). auth.md
§7.3 for the RLS pattern. Adds only what the revised spec's §5 data model requires — no extra
indexes or columns beyond what's specified there.

Pre-existing `competitor_snapshot`/`competitor_price_event`/`competitor_review_insight`/
`competitor_listing_insight` rows are cleared before adding the new NOT NULL columns. This is
a pre-launch schema pivot, not a production migration: any existing rows were written under
the retired scrape-based `capture_status` vocabulary (OK|BLOCKED|NOT_FOUND|PARSE_FAILED) and
are semantically incompatible with the new one (COMPLETE|PARTIAL|PENDING_MANUAL_ENTRY) — there
is no meaningful way to backfill `research_session_id` for them, and no real seller data
exists yet to lose. `downgrade()` reverses the DDL only, not this data clearance.

Deliberate deviation from the spec's literal DDL, flagged for spec reconciliation: §5 lists
`competitor_snapshot_field.source` as `text not null`, but §5.3 rule 3 requires a conflicted
field to have no single source ("value = null" on conflict, and evidence_id is explicitly
nullable "when conflicted across evidence" — source must be nullable for the same reason, or
a conflicted field would be forced to fabricate a source that doesn't exist). This migration
makes `source` nullable to make rule 3 representable at all; the spec's table declaration
should be corrected to match on its next revision.

Revision ID: 20260919_0002
Revises: 20260919_0001
Create Date: 2026-09-19
"""
from __future__ import annotations

from alembic import op

revision = "20260919_0002"
down_revision = "20260919_0001"
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
    # --- Clear rows written under the retired scrape-based schema (see module docstring) --
    op.execute(
        """
        DELETE FROM competitor_price_event;
        DELETE FROM competitor_review_insight;
        DELETE FROM competitor_listing_insight;
        DELETE FROM competitor_snapshot;
        """
    )

    # --- competitor_url: tags, per-URL threshold/alert overrides (closes Q5) -------------
    op.execute(
        """
        ALTER TABLE competitor_url ADD COLUMN tags text[] NOT NULL DEFAULT '{}';
        ALTER TABLE competitor_url ADD COLUMN price_threshold_pct_override numeric(5,2);
        ALTER TABLE competitor_url ADD COLUMN alert_on_availability_change_override boolean;
        """
    )

    # --- competitor_evidence (NEW) — one row per submitted screenshot --------------------
    op.execute(
        """
        CREATE TABLE competitor_evidence (
          id                    uuid primary key default gen_random_uuid(),
          tenant_id             uuid not null,
          competitor_url_id     uuid not null references competitor_url(id),
          research_session_id   uuid not null,
          image_ref             text not null,
          uploaded_by           uuid not null,
          uploaded_at           timestamptz not null,
          extraction_status     text not null,       -- PENDING | EXTRACTED | EXTRACTION_FAILED
          extraction_model      text,
          image_retained_until  timestamptz
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="competitor_evidence"))

    # --- competitor_snapshot: seller-submitted title/description/bullets (C16 carve-out), -
    # research_session_id. Added nullable then SET NOT NULL — table was just cleared above,
    # so this is always safe regardless of Postgres's ADD-COLUMN-NOT-NULL rules.
    op.execute(
        """
        ALTER TABLE competitor_snapshot ADD COLUMN research_session_id uuid;
        ALTER TABLE competitor_snapshot ALTER COLUMN research_session_id SET NOT NULL;
        ALTER TABLE competitor_snapshot ADD COLUMN title text;
        ALTER TABLE competitor_snapshot ADD COLUMN description text;
        ALTER TABLE competitor_snapshot ADD COLUMN bullets jsonb;
        """
    )

    # --- competitor_snapshot_field (NEW) — per-field provenance and merge-conflict tracking
    op.execute(
        """
        CREATE TABLE competitor_snapshot_field (
          id                uuid primary key default gen_random_uuid(),
          tenant_id         uuid not null,
          snapshot_id       uuid not null references competitor_snapshot(id),
          field_name        text not null,
          value             jsonb,
          source            text,                -- VISION_EXTRACTED | SELLER_ENTERED; null on conflict (see module docstring)
          confidence        text not null,
          evidence_id       uuid references competitor_evidence(id),
          conflict          boolean not null default false,
          conflict_values   jsonb,
          set_at            timestamptz not null,
          unique (snapshot_id, field_name)
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="competitor_snapshot_field"))

    # --- ci_tenant_config: staleness/digest defaults, separate image retention -----------
    op.execute(
        """
        ALTER TABLE ci_tenant_config ADD COLUMN raw_evidence_image_retention_days int NOT NULL DEFAULT 90;
        ALTER TABLE ci_tenant_config ADD COLUMN staleness_reminder_days int NOT NULL DEFAULT 14;
        ALTER TABLE ci_tenant_config ADD COLUMN digest_default_frequency text NOT NULL DEFAULT 'WEEKLY';
        """
    )

    # --- ci_digest_subscription (NEW) — in-app only this pass; WhatsApp deferred (§1a) ----
    op.execute(
        """
        CREATE TABLE ci_digest_subscription (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null,
          member_id     uuid not null,
          frequency     text not null,             -- NONE | DAILY | WEEKLY
          channel       text not null default 'IN_APP',
          enabled       boolean not null default true,
          last_sent_at  timestamptz,
          created_at    timestamptz not null default now(),
          unique (tenant_id, member_id)
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ci_digest_subscription"))

    # --- ci_capture_run: research_session_id, set only when trigger = EVIDENCE_UPLOAD -----
    op.execute("ALTER TABLE ci_capture_run ADD COLUMN research_session_id uuid;")


def downgrade() -> None:
    op.execute("ALTER TABLE ci_capture_run DROP COLUMN IF EXISTS research_session_id;")
    op.execute("DROP TABLE IF EXISTS ci_digest_subscription;")
    op.execute(
        """
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS digest_default_frequency;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS staleness_reminder_days;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS raw_evidence_image_retention_days;
        """
    )
    op.execute("DROP TABLE IF EXISTS competitor_snapshot_field;")
    op.execute(
        """
        ALTER TABLE competitor_snapshot DROP COLUMN IF EXISTS bullets;
        ALTER TABLE competitor_snapshot DROP COLUMN IF EXISTS description;
        ALTER TABLE competitor_snapshot DROP COLUMN IF EXISTS title;
        ALTER TABLE competitor_snapshot DROP COLUMN IF EXISTS research_session_id;
        """
    )
    op.execute("DROP TABLE IF EXISTS competitor_evidence;")
    op.execute(
        """
        ALTER TABLE competitor_url DROP COLUMN IF EXISTS alert_on_availability_change_override;
        ALTER TABLE competitor_url DROP COLUMN IF EXISTS price_threshold_pct_override;
        ALTER TABLE competitor_url DROP COLUMN IF EXISTS tags;
        """
    )
