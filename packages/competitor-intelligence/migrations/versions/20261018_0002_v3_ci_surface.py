"""CI V3 (CP3-CP5): findings, events, confirmation requests, alert state, evidence provenance.

competitor-intelligence-agent.md §5.7 (C32-C47). Additive only — no existing column changes
meaning, no row is rewritten or back-filled with a guess.

* `ci_finding`        — stable, tenant-scoped id for anything the dashboard shows (C46).
* `ci_event`          — append-only audit/history (C47): the application role is granted
                        SELECT and INSERT only, never UPDATE or DELETE (AC56).
* `ci_info_request`   — the CI -> CEO -> seller question and its answer (C37, C38).
* `ci_alert_state`    — dedup memory (C42, §6.26.1).
* `ci_held_alert`     — quiet-hours queue: held, never dropped (§6.26.2).
* `competitor_evidence` — content hash / perceptual hash / channel / quality status (C36).
* `competitor_snapshot.price_confirmation` — consequential-field confirmation state (C37).
  Existing rows default to NOT_REQUIRED: they predate the policy and are not re-judged here.
* `competitor_url`    — soft-removal audit columns (C39). Removal reuses the existing
                        `ARCHIVED` status, which every ACTIVE-only query already excludes.
* `ci_tenant_config`  — quiet hours, dedup window, review-finding minimum sample (C42).
* `competitor_price_event.alert_suppressed_reason` — why a recorded event is not shown as an alert
                        (DEDUP, STALE_AT_DELIVERY); the observation itself is never altered.

Revision ID: 20261018_0002
Revises: 20261018_0001
Create Date: 2026-10-18
"""
from __future__ import annotations

from alembic import op

revision = "20261018_0002"
down_revision = "20261018_0001"
branch_labels = None
depends_on = None

# auth.md §7.3 — identical boilerplate to every other tenant-owned table in this package.
_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT {grants} ON {table} TO metrion_app;
"""
_RW = "SELECT, INSERT, UPDATE, DELETE"
_APPEND_ONLY = "SELECT, INSERT"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ci_finding (
          id                  uuid primary key default gen_random_uuid(),
          tenant_id           uuid not null,
          product_id          text not null,
          competitor_url_id   uuid,
          finding_type        text not null,
          evidence_refs       uuid[] not null,
          sample_size         int,
          sample_total        int,
          confidence          text not null,
          freshness           text not null,
          seller_confirmation text not null default 'NOT_REQUIRED',
          engine_result_ref   uuid,
          payload             jsonb not null default '{}'::jsonb,
          created_at          timestamptz not null,
          superseded_by       uuid,
          dedup_key           text not null,
          CONSTRAINT ci_finding_has_evidence CHECK (cardinality(evidence_refs) >= 1),
          CONSTRAINT ci_finding_type_chk CHECK (finding_type IN (
            'PRICE_CHANGE','AVAILABILITY_CHANGE','REVIEW_THEME','LISTING_GAP','DIFFERENTIATION',
            'MARKET_POSITION','FRESHNESS','DISCOVERY_CANDIDATE')),
          CONSTRAINT ci_finding_freshness_chk CHECK (freshness IN ('FRESH','STALE','UNAVAILABLE')),
          CONSTRAINT ci_finding_confirmation_chk CHECK (seller_confirmation IN
            ('NOT_REQUIRED','PENDING','CONFIRMED','DECLINED'))
        );
        CREATE INDEX ci_finding_product_idx ON ci_finding (tenant_id, product_id, created_at DESC);
        CREATE UNIQUE INDEX ci_finding_dedup_idx ON ci_finding (tenant_id, dedup_key);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ci_finding", grants=_RW))

    op.execute(
        """
        CREATE TABLE ci_event (
          id               uuid primary key default gen_random_uuid(),
          tenant_id        uuid not null,
          event_type       text not null,
          actor            text not null,
          agent_run_id     uuid,
          investigation_id uuid,
          object_type      text,
          object_id        uuid,
          detail           jsonb not null default '{}'::jsonb,
          occurred_at      timestamptz not null
        );
        CREATE INDEX ci_event_tenant_time_idx ON ci_event (tenant_id, occurred_at DESC);
        CREATE INDEX ci_event_object_idx ON ci_event (tenant_id, object_type, object_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ci_event", grants=_APPEND_ONLY))
    # Default privileges in this deployment grant the app role everything on a new table, so the grant above is not enough: take UPDATE/DELETE/TRUNCATE away explicitly (AC56).
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON ci_event FROM metrion_app;")

    op.execute(
        """
        CREATE TABLE ci_info_request (
          id                 uuid primary key default gen_random_uuid(),
          tenant_id          uuid not null,
          competitor_url_id  uuid,
          evidence_id        uuid,
          snapshot_id        uuid,
          field_name         text not null,
          reason             text not null,
          consequential      boolean not null,
          proposed_value     jsonb,
          status             text not null default 'OPEN',
          answered_value     jsonb,
          answered_by        uuid,
          answered_at        timestamptz,
          created_at         timestamptz not null,
          expires_at         timestamptz not null,
          CONSTRAINT ci_info_request_reason_chk CHECK (reason IN (
            'LOW_CONFIDENCE','CONSEQUENTIAL_FIELD','MISSING','CONFLICT','IDENTITY_UNCERTAIN','WHICH_COMPETITOR')),
          CONSTRAINT ci_info_request_status_chk CHECK (status IN ('OPEN','ANSWERED','DECLINED','EXPIRED'))
        );
        CREATE INDEX ci_info_request_open_idx ON ci_info_request (tenant_id, status, expires_at);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ci_info_request", grants=_RW))

    op.execute(
        """
        CREATE TABLE ci_alert_state (
          tenant_id                uuid not null,
          competitor_url_id        uuid not null,
          finding_type             text not null,
          direction                text not null,
          last_alerted_value_paise bigint,
          last_alerted_snapshot_id uuid,
          last_alerted_at          timestamptz not null,
          PRIMARY KEY (tenant_id, competitor_url_id, finding_type, direction)
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ci_alert_state", grants=_RW))

    op.execute(
        """
        CREATE TABLE ci_held_alert (
          id           uuid primary key default gen_random_uuid(),
          tenant_id    uuid not null,
          finding_id   uuid not null,
          hold_until   timestamptz not null,
          delivered_at timestamptz
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ci_held_alert", grants=_RW))

    op.execute(
        """
        ALTER TABLE competitor_evidence ADD COLUMN content_sha256 text;
        ALTER TABLE competitor_evidence ADD COLUMN perceptual_hash text;
        ALTER TABLE competitor_evidence ADD COLUMN intake_channel text NOT NULL DEFAULT 'DASHBOARD_UPLOAD';
        ALTER TABLE competitor_evidence ADD COLUMN quality_status text NOT NULL DEFAULT 'UNCHECKED';
        ALTER TABLE competitor_evidence ADD COLUMN duplicate_of uuid;
        ALTER TABLE competitor_evidence ADD CONSTRAINT competitor_evidence_channel_chk
          CHECK (intake_channel IN ('DASHBOARD_UPLOAD','CEO_HUB_ATTACHMENT','WHATSAPP'));
        ALTER TABLE competitor_evidence ADD CONSTRAINT competitor_evidence_quality_chk
          CHECK (quality_status IN ('ACCEPTED','REJECTED_LOW_QUALITY','REJECTED_NOT_A_LISTING','UNCHECKED'));
        CREATE INDEX competitor_evidence_sha_idx ON competitor_evidence (tenant_id, content_sha256);

        ALTER TABLE competitor_snapshot ADD COLUMN price_confirmation text NOT NULL DEFAULT 'NOT_REQUIRED';
        ALTER TABLE competitor_snapshot ADD CONSTRAINT competitor_snapshot_price_confirmation_chk
          CHECK (price_confirmation IN ('NOT_REQUIRED','PENDING','CONFIRMED','DECLINED'));

        ALTER TABLE competitor_url ADD COLUMN removed_at timestamptz;
        ALTER TABLE competitor_url ADD COLUMN removed_by uuid;
        ALTER TABLE competitor_url ADD COLUMN removal_reason text;

        ALTER TABLE competitor_price_event ADD COLUMN alert_suppressed_reason text;
        ALTER TABLE ci_tenant_config ADD COLUMN quiet_hours_start time;
        ALTER TABLE ci_tenant_config ADD COLUMN quiet_hours_end time;
        ALTER TABLE ci_tenant_config ADD COLUMN quiet_hours_tz text;
        ALTER TABLE ci_tenant_config ADD COLUMN alert_dedup_window_hours int NOT NULL DEFAULT 24;
        ALTER TABLE ci_tenant_config ADD COLUMN review_finding_min_sample int NOT NULL DEFAULT 10;
        """
    )
    # ci_tenant_config is deliberately SELECT-only for the app role (least privilege, backend migration 20261012_0018). The seller sets her own alert preferences through the
    # CEO, so grant write access on exactly those columns and nothing else (CI spec C42, §6.26).
    op.execute(
        "GRANT INSERT (tenant_id, quiet_hours_start, quiet_hours_end, quiet_hours_tz, price_threshold_pct, updated_by, updated_at) ON ci_tenant_config TO metrion_app;"
        "GRANT UPDATE (quiet_hours_start, quiet_hours_end, quiet_hours_tz, price_threshold_pct, updated_by, updated_at) ON ci_tenant_config TO metrion_app;"
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE competitor_price_event DROP COLUMN IF EXISTS alert_suppressed_reason;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS review_finding_min_sample;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS alert_dedup_window_hours;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS quiet_hours_tz;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS quiet_hours_end;
        ALTER TABLE ci_tenant_config DROP COLUMN IF EXISTS quiet_hours_start;

        ALTER TABLE competitor_url DROP COLUMN IF EXISTS removal_reason;
        ALTER TABLE competitor_url DROP COLUMN IF EXISTS removed_by;
        ALTER TABLE competitor_url DROP COLUMN IF EXISTS removed_at;

        ALTER TABLE competitor_snapshot DROP CONSTRAINT IF EXISTS competitor_snapshot_price_confirmation_chk;
        ALTER TABLE competitor_snapshot DROP COLUMN IF EXISTS price_confirmation;

        DROP INDEX IF EXISTS competitor_evidence_sha_idx;
        ALTER TABLE competitor_evidence DROP CONSTRAINT IF EXISTS competitor_evidence_quality_chk;
        ALTER TABLE competitor_evidence DROP CONSTRAINT IF EXISTS competitor_evidence_channel_chk;
        ALTER TABLE competitor_evidence DROP COLUMN IF EXISTS duplicate_of;
        ALTER TABLE competitor_evidence DROP COLUMN IF EXISTS quality_status;
        ALTER TABLE competitor_evidence DROP COLUMN IF EXISTS intake_channel;
        ALTER TABLE competitor_evidence DROP COLUMN IF EXISTS perceptual_hash;
        ALTER TABLE competitor_evidence DROP COLUMN IF EXISTS content_sha256;
        """
    )
    for table in ("ci_held_alert", "ci_alert_state", "ci_info_request", "ci_event", "ci_finding"):
        op.execute(f"DROP TABLE IF EXISTS {table};")
