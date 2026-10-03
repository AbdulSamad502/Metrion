"""slim-cmo tables: seller_image_asset, product_image_analysis, vision_eval_run,
format_constraint, cmo_platform_config, cmo_generation, cmo_title_option, cmo_title_approval,
seller_fact, cmo_niche_term, cmo_trend_report.

`docs/specs/slim-cmo-agent.md` §5 (rounds 1-3). auth.md §7.3 for the RLS pattern.

Design notes — each is a deliberate hardening beyond the spec's bare DDL, not a deviation:

* **Cross-tenant references are impossible, not merely unlikely.** Every tenant-owned parent
  carries `unique (tenant_id, id)` and every child references it through a composite
  `(tenant_id, parent_id)` foreign key, so a row can never point at another tenant's row even
  if application code is wrong. RLS remains the primary boundary; this is the second line.
* **Provenance tables are append-only for the application role.** `cmo_generation`,
  `cmo_title_option`, `cmo_title_approval`, `product_image_analysis`, `seller_fact` and
  `cmo_trend_report` grant `metrion_app` SELECT + INSERT only. An approval or a delivered
  artefact cannot be rewritten after the fact (spec §6.4 "pack row immutable"). Retention /
  erasure (spec Q6, DPDP) is undecided and will arrive as its own migration.
* **Composite FKs are `DEFERRABLE INITIALLY IMMEDIATE`.** Rows are acyclic (a copy pack cites an
  approval, which cites the title-set row), but at the *table* level `cmo_generation` and
  `cmo_title_approval` reference each other. Deferrability lets a tenant's rows be erased in
  one transaction regardless of table order (test cleanup today, DPDP erasure later) while
  checking stays immediate in normal operation.
* **Platform tables are not writable by the application role.** `format_constraint`,
  `vision_eval_run` and `cmo_platform_config` are written by the migration/admin role only
  (entitlement.md §7 rule 3 precedent). `format_constraint` and `vision_eval_run` hold no
  tenant data and carry no RLS.
* **The vision trust gate is a database constraint (spec §6.2.1, AC20).** A
  `product_image_analysis` row can only carry attributes whose raw basis is IMAGE_OBSERVED or
  UNKNOWN, and can only carry an EVAL_PASSED attribute if `eval_gate_ref` points at a
  `vision_eval_run` with `passed = true` for the *same* provider, model and schema_version.
* **Idempotency** (`request_key`) is a partial unique index over COMPLETE rows only, so a
  FAILED attempt can be retried under the same key without colliding (spec §8.3).
* `cmo_generation.agent_run_id` and `cmo_trend_report.market_signal_run_ref` carry no FK:
  the first targets backend-owned `agent_run`, the second a shared service that does not exist
  yet — neither is owned by this package. `tenant_id` columns carry no FK to `tenant(id)`,
  matching every sibling package.

Revision ID: 20261003_0001
Revises:
Create Date: 2026-10-03
"""
from __future__ import annotations

from alembic import op

revision = "20261003_0001"
down_revision = None
branch_labels = None
depends_on = None

_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
"""

# Platform-default-or-own-tenant READ, own-tenant-only WRITE. Stricter than
# reconciliation_tolerance_config's policy (which lets tenant_id IS NULL be written): the
# application role must never be able to author a platform default.
_CONFIG_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id IS NULL OR tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- FORCE RLS binds the table owner too, so without this the migration/admin role could not even
-- seed a platform default. This permissive policy applies to metrion_migrate ONLY; the
-- application role gets no write grant at all (see the grants section).
CREATE POLICY migrate_admin ON {table} FOR ALL TO metrion_migrate USING (true) WITH CHECK (true);
"""

_MARKETPLACES = "'AMAZON','FLIPKART','MEESHO'"
_OUTPUT_TYPES = (
    "'TITLE_SET','LISTING_COPY','DESCRIPTION','BULLETS','KEYWORDS','BACKEND_TERMS',"
    "'HASHTAGS','CATALOG_ANSWER','TREND_REPORT'"
)
_MARKETPLACE_SCOPED = "'TITLE_SET','LISTING_COPY','DESCRIPTION','BULLETS','KEYWORDS','BACKEND_TERMS'"
_GROUNDED = "'LISTING_COPY','DESCRIPTION','BULLETS','KEYWORDS','BACKEND_TERMS'"
_CONSTRAINT_BOUND = "'TITLE_SET','LISTING_COPY','DESCRIPTION','BULLETS','KEYWORDS','BACKEND_TERMS'"


def upgrade() -> None:
    # --- vision_eval_run (platform; §6.2.1) ------------------------------------------------
    op.execute(
        """
        CREATE TABLE vision_eval_run (
          id             uuid primary key default gen_random_uuid(),
          provider       text not null check (length(btrim(provider)) > 0),
          model          text not null check (length(btrim(model)) > 0),
          schema_version text not null check (length(btrim(schema_version)) > 0),
          dataset_ref    text not null check (length(btrim(dataset_ref)) > 0),
          metrics        jsonb not null check (jsonb_typeof(metrics) = 'object'),
          bar_ref        text not null check (length(btrim(bar_ref)) > 0),   -- the approved pass bar (a human decision, Q4)
          passed         boolean not null,
          run_at         timestamptz not null default now(),
          run_by         text not null check (length(btrim(run_by)) > 0),
          -- target of product_image_analysis's gate FK: lets the database require that a
          -- cited run both passed AND matches the analysis's provider/model/schema_version.
          unique (id, passed, provider, model, schema_version)
        );
        """
    )

    # --- format_constraint (platform; §6.3, C13) -------------------------------------------
    op.execute(
        f"""
        CREATE TABLE format_constraint (
          id                      uuid primary key default gen_random_uuid(),
          marketplace             text not null check (marketplace IN ({_MARKETPLACES})),
          category                text check (category IS NULL OR length(btrim(category)) > 0),  -- null = marketplace-wide default
          title_max_chars         int check (title_max_chars > 0),
          title_option_count      int check (title_option_count > 0),
          bullet_count            int check (bullet_count > 0),
          bullet_max_chars        int check (bullet_max_chars > 0),
          description_type        text check (description_type IS NULL OR length(btrim(description_type)) > 0),
          description_max_chars   int check (description_max_chars > 0),
          keywords_max_count      int check (keywords_max_count > 0),
          keywords_max_chars      int check (keywords_max_chars > 0),
          backend_terms_max_bytes int check (backend_terms_max_bytes > 0),
          hashtags_supported      boolean,                                  -- NULL = not established (treated as NOT supported)
          count_rule              text check (count_rule IS NULL OR count_rule IN ('UTF16_CODE_UNITS','CODE_POINTS')),
                                                                            -- how this marketplace counts characters. NULL = NOT verified: production generation is BLOCKED (C13); the UTF-16 count in code is only a conservative implementation fallback
          source_url              text not null check (source_url ~ '^https?://'),
          verified_at             timestamptz not null,
          version                 int not null check (version >= 1),
          row_kind                text not null check (row_kind IN ('VERIFIED','TEST_FIXTURE')),
          created_at              timestamptz not null default now(),
          -- Any limit left NULL is "not stated by the verified source": not enforced, not guessed (§6.4).
          check (backend_terms_max_bytes IS NULL OR marketplace = 'AMAZON'),
          unique nulls not distinct (marketplace, category, version, row_kind)
        );
        CREATE INDEX format_constraint_lookup_idx ON format_constraint (marketplace, row_kind, verified_at DESC);
        """
    )

    # --- cmo_platform_config (§6.8.5, C16) -------------------------------------------------
    op.execute(
        """
        CREATE TABLE cmo_platform_config (
          id             uuid primary key default gen_random_uuid(),
          tenant_id      uuid,                                 -- null = platform default
          key            text not null check (key ~ '^[a-z][a-z0-9_]*$'),
          value          jsonb not null,
          effective_from date not null,
          created_at     timestamptz not null default now(),
          -- NO key is seeded by any migration; absence => CONFIG_MISSING, never a code default.
          unique nulls not distinct (tenant_id, key, effective_from)
        );
        """
    )
    op.execute(_CONFIG_RLS_SQL.format(table="cmo_platform_config"))

    # --- seller_image_asset (§5, C5/OP8) ---------------------------------------------------
    op.execute(
        """
        CREATE TABLE seller_image_asset (
          id              uuid primary key default gen_random_uuid(),
          tenant_id       uuid not null,
          storage_uri     text not null check (length(btrim(storage_uri)) > 0),   -- object store; NEVER bytes in Postgres
          sha256          text not null check (sha256 ~ '^[0-9a-f]{64}$'),
          content_type    text not null check (length(btrim(content_type)) > 0),
          byte_size       bigint not null check (byte_size > 0),
          uploaded_by     uuid not null,
          created_at      timestamptz not null default now(),
          retention_until timestamptz,                                           -- policy undecided (Q6): nullable, not defaulted
          status          text not null check (status IN ('ACTIVE','PURGED')),
          unique (tenant_id, id),
          unique (tenant_id, sha256)                                             -- content-addressed, immutable once stored
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="seller_image_asset"))

    # --- product_image_analysis (§5, §6.2, §6.2.1) -----------------------------------------
    op.execute(
        """
        CREATE TABLE product_image_analysis (
          id              uuid primary key default gen_random_uuid(),
          tenant_id       uuid not null,
          image_asset_id  uuid not null,
          schema_version  text not null check (length(btrim(schema_version)) > 0),
          provider        text not null check (length(btrim(provider)) > 0),
          model           text not null check (length(btrim(model)) > 0),
          eval_gate_ref   uuid,                         -- NULL = gate NOT passed: every attribute must be UNVERIFIED_HINT
          eval_gate_passed boolean generated always as (CASE WHEN eval_gate_ref IS NULL THEN NULL ELSE true END) STORED,
          attributes      jsonb not null default '[]'::jsonb,
          analysis_state  text not null check (analysis_state IN ('COMPLETE','DEGRADED','FAILED')),
          degraded_reason text,
          created_at      timestamptz not null default now(),
          unique (tenant_id, id),
          FOREIGN KEY (tenant_id, image_asset_id) REFERENCES seller_image_asset (tenant_id, id) DEFERRABLE INITIALLY IMMEDIATE,
          -- The cited run must have passed AND match this row's provider/model/schema_version.
          -- MATCH SIMPLE: when eval_gate_ref IS NULL the generated flag is NULL and nothing is checked.
          FOREIGN KEY (eval_gate_ref, eval_gate_passed, provider, model, schema_version)
            REFERENCES vision_eval_run (id, passed, provider, model, schema_version),
          check (jsonb_typeof(attributes) = 'array'),
          check (analysis_state = 'COMPLETE' OR length(btrim(coalesce(degraded_reason, ''))) > 0),
          -- POSITIVE ALLOW-LIST in jsonpath STRICT mode: every element must be an object whose
          -- name is a string, whose basis is exactly IMAGE_OBSERVED or UNKNOWN (vision may emit
          -- nothing else, spec §6.2) and whose trust_state is exactly UNVERIFIED_HINT or
          -- EVAL_PASSED. Anything else - a missing key, a non-string, a list, a bool, a nested
          -- array, a stray case/whitespace variant - fails to match, so the matched count differs
          -- from the element count and the row is rejected. (A negative "no element is bad" form
          -- was tried first and independent verification showed type-mismatched values slip
          -- through it, because comparing a bool/list with a string is UNKNOWN, not true.)
          check (CASE WHEN jsonb_typeof(attributes) = 'array'
                 THEN jsonb_array_length(attributes) = jsonb_array_length(jsonb_path_query_array(
                        attributes,
                        'strict $[*] ? (@.name.type() == "string"
                                        && (@.basis == "IMAGE_OBSERVED" || @.basis == "UNKNOWN")
                                        && (@.trust_state == "UNVERIFIED_HINT" || @.trust_state == "EVAL_PASSED"))',
                        '{}'::jsonb, true))
                 ELSE false END),
          -- ... and nothing may be EVAL_PASSED unless a passing, matching evaluation is cited (AC20).
          check (eval_gate_ref IS NOT NULL
                 OR NOT jsonb_path_exists(attributes, 'strict $[*] ? (@.trust_state == "EVAL_PASSED")', '{}'::jsonb, true))
        );
        CREATE INDEX product_image_analysis_asset_idx ON product_image_analysis (tenant_id, image_asset_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="product_image_analysis"))

    # --- cmo_generation (§5, §8) -----------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE cmo_generation (
          id                    uuid primary key default gen_random_uuid(),
          tenant_id             uuid not null,
          sku                   text,
          marketplace           text check (marketplace IS NULL OR marketplace IN ({_MARKETPLACES})),
          output_type           text not null check (output_type IN ({_OUTPUT_TYPES})),
          input_mode            text not null check (input_mode IN ('INDEPENDENT','CEO_BROKERED_CI')),
          ci_inputs_snapshot    jsonb,                  -- set only when CI attributes were actually used (§6.7)
          image_analysis_id     uuid,
          grounding_approval_id uuid,                   -- FK added below (cmo_title_approval is created after this table)
          grounding_basis       text check (grounding_basis IS NULL OR grounding_basis IN ('APPROVED_TITLE','SELLER_SUPPLIED_TITLE')),
          output_text           text,
          output_structured     jsonb,
          format_constraint_ref uuid REFERENCES format_constraint (id),
          status                text not null check (status IN ('COMPLETE','FAILED')),
          failure_reason        text,
          request_key           text not null check (length(btrim(request_key)) > 0),
          billable_units        int not null default 1 check (billable_units = 1),
          agent_run_id          uuid,                   -- backend-owned agent_run; no cross-package FK
          generated_by          uuid not null,
          created_at            timestamptz not null default now(),
          unique (tenant_id, id),
          FOREIGN KEY (tenant_id, image_analysis_id) REFERENCES product_image_analysis (tenant_id, id) DEFERRABLE INITIALLY IMMEDIATE,
          -- marketplace-scoped artefacts must name their marketplace; backend terms are Amazon-only (§8.1.1)
          check (output_type NOT IN ({_MARKETPLACE_SCOPED}) OR marketplace IS NOT NULL),
          check (output_type <> 'BACKEND_TERMS' OR marketplace = 'AMAZON'),
          -- input mode and CI snapshot travel together (AC2)
          check ((input_mode = 'CEO_BROKERED_CI') = (ci_inputs_snapshot IS NOT NULL)),
          -- a FAILED row says why; a COMPLETE row delivered something
          check (status <> 'FAILED' OR length(btrim(coalesce(failure_reason, ''))) > 0),
          check (status <> 'COMPLETE' OR output_text IS NOT NULL OR output_structured IS NOT NULL),
          -- grounded artefacts cite their anchor (AC10); the basis and the approval id agree
          check (output_type NOT IN ({_GROUNDED}) OR status = 'FAILED' OR grounding_basis IS NOT NULL),
          check ((grounding_basis IS NOT DISTINCT FROM 'APPROVED_TITLE') = (grounding_approval_id IS NOT NULL)),
          -- constraint-bound artefacts cite the exact rule version applied (AC5)
          check (status = 'FAILED' OR output_type NOT IN ({_CONSTRAINT_BOUND}) OR format_constraint_ref IS NOT NULL)
        );
        -- Idempotency (AC15, §8.3): one COMPLETE artefact per (request_key, type, marketplace). FAILED
        -- attempts are excluded so a retry under the same key is allowed. NULL marketplace compares equal.
        CREATE UNIQUE INDEX cmo_generation_idempotency_idx
          ON cmo_generation (tenant_id, request_key, output_type, marketplace) NULLS NOT DISTINCT
          WHERE status = 'COMPLETE';
        CREATE INDEX cmo_generation_tenant_created_idx ON cmo_generation (tenant_id, created_at DESC);
        CREATE INDEX cmo_generation_tenant_type_idx ON cmo_generation (tenant_id, output_type, marketplace);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="cmo_generation"))

    # --- cmo_title_option (§5, §6.4) -------------------------------------------------------
    op.execute(
        """
        CREATE TABLE cmo_title_option (
          id               uuid primary key default gen_random_uuid(),
          tenant_id        uuid not null,
          generation_id    uuid not null,
          rank             int not null check (rank >= 1),     -- presentation order, NOT a quality claim
          title_text       text not null check (length(btrim(title_text)) > 0),
          char_count       int not null check (char_count > 0), -- computed in code, never by the LLM
          constraint_check jsonb not null check (jsonb_typeof(constraint_check) = 'object'),
          created_at       timestamptz not null default now(),
          unique (tenant_id, id),
          unique (generation_id, id),
          unique (generation_id, rank),
          FOREIGN KEY (tenant_id, generation_id) REFERENCES cmo_generation (tenant_id, id) DEFERRABLE INITIALLY IMMEDIATE
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="cmo_title_option"))

    # --- cmo_title_approval (§5, C8) -------------------------------------------------------
    op.execute(
        """
        CREATE TABLE cmo_title_approval (
          id               uuid primary key default gen_random_uuid(),
          tenant_id        uuid not null,
          generation_id    uuid not null,
          option_id        uuid,                                -- NULL when the seller supplied/edited their own text
          approved_text    text not null check (length(btrim(approved_text)) > 0),
          edited_by_seller boolean not null,
          approved_by      uuid not null,
          approved_at      timestamptz not null default now(),
          unique (tenant_id, id),
          FOREIGN KEY (tenant_id, generation_id) REFERENCES cmo_generation (tenant_id, id) DEFERRABLE INITIALLY IMMEDIATE,
          FOREIGN KEY (tenant_id, option_id) REFERENCES cmo_title_option (tenant_id, id) DEFERRABLE INITIALLY IMMEDIATE,
          -- the option must belong to the generation it is approved under
          FOREIGN KEY (generation_id, option_id) REFERENCES cmo_title_option (generation_id, id) DEFERRABLE INITIALLY IMMEDIATE,
          check ((option_id IS NULL) = edited_by_seller)
        );
        CREATE INDEX cmo_title_approval_generation_idx ON cmo_title_approval (tenant_id, generation_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="cmo_title_approval"))

    # cmo_generation.grounding_approval_id -> cmo_title_approval (circular, hence ALTER)
    op.execute(
        """
        ALTER TABLE cmo_generation
          ADD CONSTRAINT cmo_generation_grounding_approval_fk
          FOREIGN KEY (tenant_id, grounding_approval_id) REFERENCES cmo_title_approval (tenant_id, id)
          DEFERRABLE INITIALLY IMMEDIATE;
        """
    )

    # --- seller_fact (§5; round-3 amendment: nullable generation link + attribution) -------
    op.execute(
        """
        CREATE TABLE seller_fact (
          id                uuid primary key default gen_random_uuid(),
          tenant_id         uuid not null,
          cmo_generation_id uuid,                              -- null for facts confirmed outside a generation (e.g. a hint)
          image_analysis_id uuid,                              -- set when this fact confirms an image hint
          sku               text,
          attribute_name    text check (attribute_name IS NULL OR length(btrim(attribute_name)) > 0),
          fact_type         text not null check (fact_type IN ('CATEGORY','BRAND','ATTRIBUTE','NICHE','TARGET_PRICE','FREE_TEXT')),
          fact_value        text check (fact_value IS NULL OR length(btrim(fact_value)) > 0),
          value_paise       bigint check (value_paise >= 0),   -- TARGET_PRICE only: signed BIGINT paise, no floats
          provided_by       uuid not null,
          provided_at       timestamptz not null default now(),
          unique (tenant_id, id),
          FOREIGN KEY (tenant_id, cmo_generation_id) REFERENCES cmo_generation (tenant_id, id) DEFERRABLE INITIALLY IMMEDIATE,
          FOREIGN KEY (tenant_id, image_analysis_id) REFERENCES product_image_analysis (tenant_id, id) DEFERRABLE INITIALLY IMMEDIATE,
          check ((fact_type = 'TARGET_PRICE') = (value_paise IS NOT NULL)),
          check ((fact_type = 'TARGET_PRICE') = (fact_value IS NULL))
        );
        CREATE INDEX seller_fact_tenant_type_idx ON seller_fact (tenant_id, fact_type);
        CREATE INDEX seller_fact_generation_idx ON seller_fact (tenant_id, cmo_generation_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="seller_fact"))

    # --- cmo_niche_term (§6.8.3, C15) ------------------------------------------------------
    op.execute(
        """
        CREATE TABLE cmo_niche_term (
          id           uuid primary key default gen_random_uuid(),
          tenant_id    uuid not null,
          term         text not null check (length(term) > 0 AND term = btrim(term)),
          origin       text not null check (origin IN ('SELLER_STATED','CATALOG_DERIVED','SELLER_FACT')),
          origin_note  text,                                    -- e.g. 'derived from n distinct item titles'; never raw titles
          status       text not null check (status IN ('SUGGESTED','CONFIRMED','REJECTED')),
          confirmed_by uuid,
          confirmed_at timestamptz,
          created_at   timestamptz not null default now(),
          unique (tenant_id, id),
          unique (tenant_id, term),
          -- only a CONFIRMED term carries a confirmer, and it always carries both fields
          check ((status = 'CONFIRMED') = (confirmed_by IS NOT NULL)),
          check ((confirmed_by IS NULL) = (confirmed_at IS NULL))
        );
        CREATE INDEX cmo_niche_term_status_idx ON cmo_niche_term (tenant_id, status);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="cmo_niche_term"))

    # --- cmo_trend_report (§5, §6.8) -------------------------------------------------------
    op.execute(
        """
        CREATE TABLE cmo_trend_report (
          id                    uuid primary key default gen_random_uuid(),
          tenant_id             uuid not null,
          generation_id         uuid not null,
          niche_term_ids        uuid[],                          -- the CONFIRMED terms used; null/empty for a broader-only report
          sections_requested    text[] not null check (
            cardinality(sections_requested) > 0
            AND sections_requested <@ ARRAY['NICHE','MARKET_NEWS','REPORTED_TACTICS','NEW_PRODUCTS_BUZZ','ADJACENT']::text[]
          ),
          sections              jsonb not null check (jsonb_typeof(sections) = 'object'),
          interpretation        jsonb,
          evidence              jsonb not null check (jsonb_typeof(evidence) = 'object' AND evidence <> '{}'::jsonb),  -- never empty (§6.8.2 s7)
          outbound_queries      jsonb not null check (jsonb_typeof(outbound_queries) = 'array'),                      -- audit of what left Metrion (C15)
          config_snapshot       jsonb not null check (jsonb_typeof(config_snapshot) = 'object'),
          market_signal_run_ref uuid not null,                   -- shared retrieval service's run record (built in P7); no FK yet
          generated_at          timestamptz not null default now(),
          unique (tenant_id, id),
          unique (tenant_id, generation_id),                     -- one report per TREND_REPORT artefact
          FOREIGN KEY (tenant_id, generation_id) REFERENCES cmo_generation (tenant_id, id) DEFERRABLE INITIALLY IMMEDIATE
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="cmo_trend_report"))

    # --- grants -----------------------------------------------------------------------------
    # docker/postgres-init/02-roles.sql's ALTER DEFAULT PRIVILEGES already hands metrion_app
    # full DML on every table metrion_migrate creates. Narrow it explicitly, per the design
    # notes in this file's docstring, rather than relying on that default.
    for table in ("vision_eval_run", "format_constraint", "cmo_platform_config"):
        op.execute(f"REVOKE ALL ON {table} FROM metrion_app; GRANT SELECT ON {table} TO metrion_app;")
    for table in (
        "cmo_generation",
        "cmo_title_option",
        "cmo_title_approval",
        "product_image_analysis",
        "seller_fact",
        "cmo_trend_report",
    ):
        op.execute(f"REVOKE ALL ON {table} FROM metrion_app; GRANT SELECT, INSERT ON {table} TO metrion_app;")
    for table in ("seller_image_asset", "cmo_niche_term"):
        op.execute(f"REVOKE ALL ON {table} FROM metrion_app; GRANT SELECT, INSERT, UPDATE ON {table} TO metrion_app;")


def downgrade() -> None:
    # Reverse dependency order. cmo_generation's grounding FK is dropped with the table that
    # owns it; cmo_title_approval must go before cmo_title_option and cmo_generation.
    op.execute("ALTER TABLE cmo_generation DROP CONSTRAINT IF EXISTS cmo_generation_grounding_approval_fk;")
    for table in (
        "cmo_trend_report",
        "cmo_niche_term",
        "seller_fact",
        "cmo_title_approval",
        "cmo_title_option",
        "cmo_generation",
        "product_image_analysis",
        "seller_image_asset",
        "cmo_platform_config",
        "format_constraint",
        "vision_eval_run",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table};")
