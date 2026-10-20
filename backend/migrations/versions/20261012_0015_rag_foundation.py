"""rag foundation: rag_source, rag_chunk, rag_chunk_embedding, rag_retrieval_log, rag_usage_daily, rag_index_event

Spec rag-knowledge.md section 7 (R1, 2026-10-12). Shared evidence-retrieval storage: a DERIVED index, never a source of truth. Every tenant-owned table is FORCE ROW LEVEL SECURITY on
tenant_id, so a session with no tenant context sees nothing. What the database enforces (so it cannot be bypassed from code):
  * a source belongs to exactly one collection, with a fixed origin and trust class; tenant_id is NULL only for the read-only GLOBAL_REFERENCE collection;
  * the identity of a source (tenant, collection, origin, family, version, content hash, trust) is immutable and its status can only move along the allowed lifecycle;
  * a chunk and an embedding carry the SAME tenant as their source/chunk (trigger, runs under RLS, so a foreign source id is simply not found);
  * embeddings of different models coexist in one untyped `vector` column, each model with its OWN partial HNSW index (dimension-compatible, never mixed), and
    vector_dims(embedding) must equal the declared model_dim of a registered (model, dim) pair;
  * GLOBAL_REFERENCE rows are readable by the app role and writable only by the migration/curator role (policy TO metrion_migrate); the app role can never write one;
  * the retrieval log holds no query text, chunk text or document name (a sha256 of the query only), and is append-only for the app role.
The cluster's default privileges hand every new table full DML to the app role: the grants below are narrowed explicitly (the agent_memory lesson, 20261010_0014).

Revision ID: 20261012_0015
Revises: 20261010_0014
Create Date: 2026-10-12
"""
from __future__ import annotations

from alembic import op

revision = "20261012_0015"
down_revision = "20261012_0018"
branch_labels = None
depends_on = None

_TENANT = "tenant_id = current_setting('app.current_tenant_id', true)::uuid"
_ZERO = "'00000000-0000-0000-0000-000000000000'::uuid"


def _rls(table: str, *, global_rows: bool) -> str:
    sql = f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON {table} USING ({_TENANT}) WITH CHECK ({_TENANT});
    """
    if global_rows:
        # the read-only global collection: everyone may read it; only the migration/curator role may write it
        sql += f"""
        CREATE POLICY global_read ON {table} FOR SELECT USING (tenant_id IS NULL);
        CREATE POLICY global_curate ON {table} FOR ALL TO metrion_migrate USING (tenant_id IS NULL) WITH CHECK (tenant_id IS NULL);
        """
    return sql


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # ------------------------------------------------------------------ rag_source
    op.execute(
        f"""
        CREATE TABLE rag_source (
          id                    uuid primary key default gen_random_uuid(),
          tenant_id             uuid references tenant(id),
          collection            text not null,
          origin_kind           text not null,
          origin_ref            jsonb,
          title                 text not null,
          family_key            text not null,
          version               int not null default 1,
          status                text not null default 'PROCESSING',
          tags                  text[] not null default '{{}}',
          trust_class           text not null,
          freshness_class       text not null,
          valid_from            date,
          expires_at            date,
          effective_from        date,
          effective_to          date,
          superseded_by         uuid references rag_source(id),
          authoritative_version text,
          version_checked_at    timestamptz,
          content_hash          text not null,
          byte_size             bigint not null default 0,
          mime                  text,
          object_key            text,
          chunker_version       text not null,
          normaliser_version    text not null,
          index_generation      int not null default 1,
          screen_result         jsonb not null default '{{}}'::jsonb,
          failure_reason        text,
          created_by            uuid,
          created_at            timestamptz not null default now(),
          updated_at            timestamptz not null default now(),
          CONSTRAINT rag_source_collection_check CHECK (collection IN ('SELLER_DOCUMENT', 'APPROVED_FINDING', 'APPROVED_MEMORY', 'GLOBAL_REFERENCE')),
          CONSTRAINT rag_source_origin_check CHECK (origin_kind IN ('UPLOAD', 'SHARED_FINDING', 'AGENT_MEMORY', 'GLOBAL')),
          CONSTRAINT rag_source_status_check CHECK (status IN ('PROCESSING', 'ACTIVE', 'SUPERSEDED', 'DELETED', 'FAILED', 'REJECTED')),
          CONSTRAINT rag_source_trust_check CHECK (trust_class IN ('SELLER_DOCUMENT', 'SELLER_STATED', 'ENGINE_VERIFIED', 'AGENT_REPORTED', 'GLOBAL_CURATED')),
          CONSTRAINT rag_source_freshness_class_check CHECK (freshness_class IN
            ('CI_PRICE', 'CI_FINDING', 'PI_FINDING', 'BRAND_GUIDELINE', 'FINDING_OTHER', 'DOCUMENT_PRICE', 'DOCUMENT_OTHER', 'MEMORY', 'MARKETPLACE_POLICY')),
          CONSTRAINT rag_source_tags_check CHECK (tags <@ ARRAY['brand', 'product', 'cost', 'supplier', 'policy']::text[]),
          CONSTRAINT rag_source_title_check CHECK (char_length(title) BETWEEN 1 AND 300),
          CONSTRAINT rag_source_family_check CHECK (char_length(family_key) BETWEEN 1 AND 200),
          CONSTRAINT rag_source_version_check CHECK (version >= 1 AND index_generation >= 1 AND byte_size >= 0),
          CONSTRAINT rag_source_hash_check CHECK (content_hash ~ '^[0-9a-f]{{64}}$'),
          -- tenant_id is NULL exactly for the read-only global collection
          CONSTRAINT rag_source_tenant_check CHECK ((collection = 'GLOBAL_REFERENCE') = (tenant_id IS NULL)),
          -- collection, origin and trust move together (a document is never presented under a ledger trust, and vice versa)
          CONSTRAINT rag_source_pairing_check CHECK (
            (collection = 'SELLER_DOCUMENT'  AND origin_kind = 'UPLOAD'         AND trust_class = 'SELLER_DOCUMENT')
            OR (collection = 'APPROVED_FINDING' AND origin_kind = 'SHARED_FINDING' AND trust_class IN ('SELLER_STATED', 'ENGINE_VERIFIED', 'AGENT_REPORTED'))
            OR (collection = 'APPROVED_MEMORY'  AND origin_kind = 'AGENT_MEMORY'   AND trust_class = 'SELLER_STATED')
            OR (collection = 'GLOBAL_REFERENCE' AND origin_kind = 'GLOBAL'         AND trust_class = 'GLOBAL_CURATED')
          ),
          -- a ledger-derived source must name the exact ledger row it projects (re-read at retrieval time)
          CONSTRAINT rag_source_origin_ref_check CHECK (
            origin_kind IN ('UPLOAD', 'GLOBAL')
            OR (jsonb_typeof(origin_ref) = 'object' AND origin_ref->>'kind' = lower(origin_kind) AND coalesce(origin_ref->>'id', '') <> '')
          ),
          CONSTRAINT rag_source_freshness_pairing_check CHECK (
            (freshness_class = 'MARKETPLACE_POLICY') = (collection = 'GLOBAL_REFERENCE')
            AND (collection <> 'APPROVED_MEMORY' OR freshness_class = 'MEMORY')
            AND (collection <> 'SELLER_DOCUMENT' OR freshness_class IN ('DOCUMENT_PRICE', 'BRAND_GUIDELINE', 'DOCUMENT_OTHER'))
            AND (collection <> 'APPROVED_FINDING' OR freshness_class IN ('CI_PRICE', 'CI_FINDING', 'PI_FINDING', 'FINDING_OTHER'))
          ),
          -- marketplace-policy fields exist only on the global collection (effective dates, explicit supersession, authoritative version check; spec 5.5)
          CONSTRAINT rag_source_policy_fields_check CHECK (
            collection = 'GLOBAL_REFERENCE'
            OR (effective_from IS NULL AND effective_to IS NULL AND superseded_by IS NULL AND authoritative_version IS NULL AND version_checked_at IS NULL)
          ),
          CONSTRAINT rag_source_policy_window_check CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from),
          CONSTRAINT rag_source_policy_required_check CHECK (collection <> 'GLOBAL_REFERENCE' OR effective_from IS NOT NULL),
          CONSTRAINT rag_source_failure_check CHECK ((status IN ('FAILED', 'REJECTED')) = (failure_reason IS NOT NULL))
        );
        CREATE UNIQUE INDEX rag_source_version_uidx ON rag_source (coalesce(tenant_id, {_ZERO}), family_key, version);
        -- never two ACTIVE versions of one family (the swap is old -> SUPERSEDED, then new -> ACTIVE, in one transaction)
        CREATE UNIQUE INDEX rag_source_one_active_uidx ON rag_source (coalesce(tenant_id, {_ZERO}), family_key) WHERE status = 'ACTIVE';
        CREATE INDEX rag_source_lookup_idx ON rag_source (tenant_id, collection, status);
        -- one ledger row is projected at most once per version
        CREATE UNIQUE INDEX rag_source_ledger_origin_uidx ON rag_source (tenant_id, collection, (origin_ref->>'id'), version) WHERE origin_kind IN ('SHARED_FINDING', 'AGENT_MEMORY');

        CREATE FUNCTION rag_source_guard() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
          -- identity is immutable: a source can never be moved to another tenant, collection, origin, version or trust class
          IF NEW.id <> OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.collection <> OLD.collection OR NEW.origin_kind <> OLD.origin_kind
             OR NEW.origin_ref IS DISTINCT FROM OLD.origin_ref OR NEW.family_key <> OLD.family_key OR NEW.version <> OLD.version OR NEW.content_hash <> OLD.content_hash
             OR NEW.trust_class <> OLD.trust_class OR NEW.created_at <> OLD.created_at OR NEW.created_by IS DISTINCT FROM OLD.created_by THEN
            RAISE EXCEPTION 'rag_source: identity columns are immutable' USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.status <> OLD.status AND NOT (
               (OLD.status = 'PROCESSING' AND NEW.status IN ('ACTIVE', 'FAILED', 'REJECTED', 'DELETED'))
            OR (OLD.status = 'ACTIVE'     AND NEW.status IN ('SUPERSEDED', 'DELETED'))
            OR (OLD.status = 'SUPERSEDED' AND NEW.status = 'DELETED')
            OR (OLD.status = 'FAILED'     AND NEW.status IN ('PROCESSING', 'DELETED'))
            OR (OLD.status = 'REJECTED'   AND NEW.status = 'DELETED')) THEN
            RAISE EXCEPTION 'rag_source: status % -> % is not an allowed transition', OLD.status, NEW.status USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.index_generation < OLD.index_generation THEN
            RAISE EXCEPTION 'rag_source: index_generation never goes back' USING ERRCODE = 'check_violation';
          END IF;
          NEW.updated_at := now();
          RETURN NEW;
        END
        $fn$;
        CREATE TRIGGER rag_source_guard BEFORE UPDATE ON rag_source FOR EACH ROW EXECUTE FUNCTION rag_source_guard();
        """
    )
    op.execute(_rls("rag_source", global_rows=True))
    op.execute("REVOKE ALL ON rag_source FROM metrion_app; GRANT SELECT, INSERT, UPDATE ON rag_source TO metrion_app;")

    # ------------------------------------------------------------------ rag_chunk
    op.execute(
        """
        CREATE TABLE rag_chunk (
          id               uuid primary key default gen_random_uuid(),
          tenant_id        uuid references tenant(id),
          source_id        uuid not null references rag_source(id),
          index_generation int not null default 1,
          chunk_index      int not null,
          text             text not null,
          locator          jsonb not null default '{}'::jsonb,
          token_count      int not null,
          content_hash     text not null,
          -- 'simple': language-neutral, so Hinglish / mixed script is not mis-stemmed
          tsv              tsvector generated always as (to_tsvector('simple', text)) stored,
          created_at       timestamptz not null default now(),
          CONSTRAINT rag_chunk_text_check CHECK (char_length(text) BETWEEN 1 AND 8000),
          CONSTRAINT rag_chunk_index_check CHECK (chunk_index >= 0 AND index_generation >= 1 AND token_count > 0),
          CONSTRAINT rag_chunk_hash_check CHECK (content_hash ~ '^[0-9a-f]{64}$'),
          CONSTRAINT rag_chunk_unique UNIQUE (source_id, index_generation, chunk_index)
        );
        CREATE INDEX rag_chunk_tsv_idx ON rag_chunk USING gin (tsv);
        CREATE INDEX rag_chunk_source_idx ON rag_chunk (tenant_id, source_id, index_generation);

        CREATE FUNCTION rag_chunk_gate() RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
          src_tenant uuid;
          src_status text;
        BEGIN
          -- the source is looked up under the caller's RLS: another tenant's source is simply not found
          SELECT s.tenant_id, s.status INTO src_tenant, src_status FROM rag_source s WHERE s.id = NEW.source_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'rag_chunk: source not found' USING ERRCODE = 'check_violation';
          END IF;
          IF src_tenant IS DISTINCT FROM NEW.tenant_id THEN
            RAISE EXCEPTION 'rag_chunk: tenant_id must equal the source tenant_id' USING ERRCODE = 'check_violation';
          END IF;
          IF src_status NOT IN ('PROCESSING', 'ACTIVE') THEN
            RAISE EXCEPTION 'rag_chunk: a % source accepts no new chunks', src_status USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END
        $fn$;
        CREATE TRIGGER rag_chunk_gate BEFORE INSERT ON rag_chunk FOR EACH ROW EXECUTE FUNCTION rag_chunk_gate();
        """
    )
    op.execute(_rls("rag_chunk", global_rows=True))
    # chunks are immutable: a change is a new generation (insert) and a delete of the old one
    op.execute("REVOKE ALL ON rag_chunk FROM metrion_app; GRANT SELECT, INSERT, DELETE ON rag_chunk TO metrion_app;")

    # ------------------------------------------------------------------ rag_chunk_embedding
    op.execute(
        """
        CREATE TABLE rag_chunk_embedding (
          chunk_id   uuid not null references rag_chunk(id),
          tenant_id  uuid references tenant(id),
          model_name text not null,
          model_dim  int not null,
          embedding  vector not null,
          created_at timestamptz not null default now(),
          PRIMARY KEY (chunk_id, model_name),
          -- a registered (model, dimension) pair: adding a model is a migration that adds its entry here and its index below
          CONSTRAINT rag_embedding_model_check CHECK ((model_name, model_dim) IN (('nomic-embed-text', 768), ('bge-m3', 1024))),
          CONSTRAINT rag_embedding_dims_check CHECK (vector_dims(embedding) = model_dim)
        );
        -- one partial HNSW index PER MODEL: each is dimension-compatible and separate, so a benchmark compares like with like and a model swap is a re-index.
        -- A query must filter model_name and use the same cast expression to use its index.
        CREATE INDEX rag_embedding_nomic_hnsw ON rag_chunk_embedding USING hnsw ((embedding::vector(768)) vector_cosine_ops) WHERE model_name = 'nomic-embed-text';
        CREATE INDEX rag_embedding_bge_m3_hnsw ON rag_chunk_embedding USING hnsw ((embedding::vector(1024)) vector_cosine_ops) WHERE model_name = 'bge-m3';
        CREATE INDEX rag_embedding_tenant_idx ON rag_chunk_embedding (tenant_id, model_name);

        CREATE FUNCTION rag_embedding_gate() RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
          ch_tenant uuid;
        BEGIN
          SELECT c.tenant_id INTO ch_tenant FROM rag_chunk c WHERE c.id = NEW.chunk_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'rag_chunk_embedding: chunk not found' USING ERRCODE = 'check_violation';
          END IF;
          IF ch_tenant IS DISTINCT FROM NEW.tenant_id THEN
            RAISE EXCEPTION 'rag_chunk_embedding: tenant_id must equal the chunk tenant_id' USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END
        $fn$;
        CREATE TRIGGER rag_embedding_gate BEFORE INSERT ON rag_chunk_embedding FOR EACH ROW EXECUTE FUNCTION rag_embedding_gate();
        """
    )
    op.execute(_rls("rag_chunk_embedding", global_rows=True))
    op.execute("REVOKE ALL ON rag_chunk_embedding FROM metrion_app; GRANT SELECT, INSERT, DELETE ON rag_chunk_embedding TO metrion_app;")

    # ------------------------------------------------------------------ rag_retrieval_log (content-free)
    op.execute(
        """
        CREATE TABLE rag_retrieval_log (
          id              uuid primary key default gen_random_uuid(),
          tenant_id       uuid not null references tenant(id),
          agent_code      text not null,
          run_id          uuid,
          collections     text[] not null,
          status          text not null,
          item_count      int not null,
          latency_ms      int not null,
          embed_ms        int,
          fts_ms          int,
          embedding_model text,
          -- sha256 of the normalised query: never the query text, a chunk or a document name (spec 7.5, AC17)
          query_hash      text not null,
          created_at      timestamptz not null default now(),
          CONSTRAINT rag_log_agent_check  CHECK (agent_code IN ('CEO', 'CFO', 'PI', 'CMO', 'CI')),
          CONSTRAINT rag_log_status_check CHECK (status IN ('OK', 'NO_EVIDENCE', 'PARTIAL', 'UNAVAILABLE')),
          CONSTRAINT rag_log_counts_check CHECK (item_count >= 0 AND latency_ms >= 0 AND coalesce(embed_ms, 0) >= 0 AND coalesce(fts_ms, 0) >= 0),
          CONSTRAINT rag_log_hash_check   CHECK (query_hash ~ '^[0-9a-f]{64}$')
        );
        CREATE INDEX rag_retrieval_log_idx ON rag_retrieval_log (tenant_id, created_at DESC);
        """
    )
    op.execute(_rls("rag_retrieval_log", global_rows=False))
    op.execute("REVOKE ALL ON rag_retrieval_log FROM metrion_app; GRANT SELECT, INSERT ON rag_retrieval_log TO metrion_app;")

    # ------------------------------------------------------------------ rag_usage_daily (cost counters)
    op.execute(
        """
        CREATE TABLE rag_usage_daily (
          tenant_id         uuid not null references tenant(id),
          day               date not null,
          chunks_embedded   bigint not null default 0,
          tokens_embedded   bigint not null default 0,
          queries_embedded  bigint not null default 0,
          PRIMARY KEY (tenant_id, day),
          CONSTRAINT rag_usage_nonneg_check CHECK (chunks_embedded >= 0 AND tokens_embedded >= 0 AND queries_embedded >= 0)
        );
        """
    )
    op.execute(_rls("rag_usage_daily", global_rows=False))
    op.execute("REVOKE ALL ON rag_usage_daily FROM metrion_app; GRANT SELECT, INSERT, UPDATE ON rag_usage_daily TO metrion_app;")

    # ------------------------------------------------------------------ rag_index_event (outbox)
    op.execute(
        """
        CREATE TABLE rag_index_event (
          id         uuid primary key default gen_random_uuid(),
          tenant_id  uuid not null references tenant(id),
          kind       text not null,
          ref        jsonb not null,
          status     text not null default 'PENDING',
          attempts   int not null default 0,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          CONSTRAINT rag_event_kind_check   CHECK (kind IN ('UPSERT_LEDGER', 'REMOVE_LEDGER', 'PURGE_SOURCE', 'REINDEX_SOURCE')),
          CONSTRAINT rag_event_status_check CHECK (status IN ('PENDING', 'DONE', 'DEAD')),
          CONSTRAINT rag_event_ref_check    CHECK (jsonb_typeof(ref) = 'object'),
          CONSTRAINT rag_event_attempts_check CHECK (attempts >= 0)
        );
        CREATE INDEX rag_index_event_pending_idx ON rag_index_event (tenant_id, status, created_at);
        """
    )
    op.execute(_rls("rag_index_event", global_rows=False))
    op.execute("REVOKE ALL ON rag_index_event FROM metrion_app; GRANT SELECT, INSERT, UPDATE ON rag_index_event TO metrion_app;")


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS rag_index_event;
        DROP TABLE IF EXISTS rag_usage_daily;
        DROP TABLE IF EXISTS rag_retrieval_log;
        DROP TABLE IF EXISTS rag_chunk_embedding;
        DROP FUNCTION IF EXISTS rag_embedding_gate();
        DROP TABLE IF EXISTS rag_chunk;
        DROP FUNCTION IF EXISTS rag_chunk_gate();
        DROP TABLE IF EXISTS rag_source;
        DROP FUNCTION IF EXISTS rag_source_guard();
        """
    )
