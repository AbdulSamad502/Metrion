"""gst_lookup_result (§8.4 / §8.4.1) — G2's output table. Tenant-owned real rows (unlike
`hsn_gst_reference`/`gst_slab_reference`/`fee_reference`, which are platform-owned reference
data): each row is one seller's per-query research result, so this table gets the
real-per-tenant `FORCE ROW LEVEL SECURITY` template, copied verbatim from
`20260925_0004_reconciliation_tables.py` / `backend/migrations/versions/
20260925_0004_entitlement_tables.py`'s `_TENANT_RLS_SQL` (auth.md §7.3) — not the
nullable-platform-default variant, which does not apply here.

`tenant_id` is a deliberately bare `uuid` column with **no FK to `tenant(id)`** — `tenant` is
owned by `backend`'s own migration chain
(`backend/migrations/versions/20260917_0001_auth_tables.py`), not by this package, and
`migrations/README.md` states this package "never authors DDL for tables it doesn't own."
This mirrors `reconciliation_run`/`reconciliation_match`/`reconciliation_exception`'s own
`tenant_id uuid not null` (no FK) in `20260925_0004_reconciliation_tables.py` — not
`backend`'s own tenant-owned tables, which *can* reference `tenant(id)` because they live in
the same migration chain that creates it. (An earlier draft of this migration mistakenly added
`references tenant(id)`, which would make `calc-engine`'s own migration chain fail a
standalone `downgrade(base)`/`upgrade(head)` round-trip — corrected here before this
checkpoint's tests were run for real.)

**Append-only, per §8.4.1's L6 mechanism**: no `UPDATE` statement is ever issued against this
table by `gst_lookup_repo.py` — a fresh lookup past the 14-day TTL inserts a new row, the prior
row is retained for audit history. `GRANT` therefore omits `UPDATE`/`DELETE` for `metrion_app`
(only `SELECT, INSERT`) — a structural nudge matching `manual_adjustment`'s own append-only
precedent, not merely a docstring promise. (`status`/`verified_by`/`verified_at` do need to
change after a seller reviews a `PROVISIONAL` row — that is G3's concern, a later checkpoint
this migration does not build; when it lands, either it earns `UPDATE` explicitly or it too
becomes an appended row, a decision left to that checkpoint rather than pre-empted here.)

**No `disclaimer` or tier column.** §8.4's schema does not carry a `disclaimer` column — L5's
standing text is a fixed constant (`calc_engine.gst_lookup.types.GST_LOOKUP_DISCLAIMER`), not
per-row seller-visible content that needs to vary or be queried, so it is not persisted. Tier
is likewise not a column, per §8.4.1's explicit statement that a following checkpoint may add
one — `calc_engine.gst_lookup.allowlist.tier_for_host(source_url)` recovers it at read time.
Neither omission is silent: both are called out here and in `gst_lookup/types.py`'s own
docstring.

`alternatives` is `jsonb` (a list of `{"rate_pct": str | null, "hsn": str | null, "category":
str | null}` objects — `rate_pct` stored as text/string representation of the `Fraction`,
`gst_lookup_repo.py`'s job to (de)serialise) — the same "structured but not further typed at
the DB layer" treatment `reconciliation_exception.candidate_sales_line_ids` already gets.

Revision ID: 20260925_0008
Revises: 20260925_0007
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op

revision = "20260925_0008"
down_revision = "20260925_0007"
branch_labels = None
depends_on = None

# Real-per-tenant FORCE RLS — auth.md §7.3, identical template to
# 20260925_0004_reconciliation_tables.py's _TENANT_RLS_SQL.
_TENANT_RLS_SQL = """
ALTER TABLE gst_lookup_result ENABLE ROW LEVEL SECURITY;
ALTER TABLE gst_lookup_result FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON gst_lookup_result
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT ON gst_lookup_result TO metrion_app;
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE gst_lookup_result (
          id               uuid primary key default gen_random_uuid(),
          tenant_id        uuid not null,
          sku              text,
          query_text       text not null,
          query_hsn        text,
          likely_rate_pct  numeric(7,4),
          likely_hsn       text,
          likely_category  text,
          ambiguity_note   text,
          alternatives     jsonb not null default '[]'::jsonb,
          source_url       text not null,
          source_title     text,
          retrieved_at     timestamptz not null,
          status           text not null default 'PROVISIONAL',
          verified_by      text,
          verified_at      timestamptz,
          check (status in ('PROVISIONAL', 'SELLER_VERIFIED', 'REJECTED'))
        );
        CREATE INDEX gst_lookup_result_tenant_query_idx
          ON gst_lookup_result (tenant_id, query_text, retrieved_at DESC);
        """
    )
    op.execute(_TENANT_RLS_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS gst_lookup_result;")
