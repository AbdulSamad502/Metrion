"""RAG persistence (rag-knowledge.md section 7). Tenant-scoped through `tenant_scope` (FORCE RLS beneath an explicit application filter); a derived index, never a source of truth.

R1 is the foundation only: sources, chunks, per-model embeddings, the content-free retrieval log, cost counters and the outbox. There is no ingestion pipeline, no hybrid retrieval and no agent
integration here. `nearest_chunks` is a low-level single-model vector primitive (what the benchmark and the isolation tests need); the retrieval pipeline of spec 5.3 is R3.

What this module adds to the database gates: the per-tenant document cap (serialised by an advisory lock so concurrent uploads cannot both take the last slot), atomic activation that
refuses a source whose chunks are not all embedded (AC5), atomic version supersession (AC7), delete that removes servable content in the same transaction (AC6), and the collection grid (AC14).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text

from backend.rag import grid
from backend.rag.embedding import KNOWN_MODELS, model_dim
from backend.tenant_context import tenant_scope

_SOURCE_COLS = (
    "id, tenant_id, collection, origin_kind, origin_ref, title, family_key, version, status, tags, trust_class, freshness_class, valid_from, expires_at, effective_from, "
    "effective_to, superseded_by, authoritative_version, version_checked_at, content_hash, byte_size, mime, object_key, chunker_version, normaliser_version, index_generation, "
    "screen_result, failure_reason, created_by, created_at, updated_at"
)
# a document counts against the tenant's cap while it exists in any state except DELETED / REJECTED, once per family (a new version of a document is not a new document)
_COUNTED = "('PROCESSING', 'ACTIVE', 'SUPERSEDED', 'FAILED')"


class DocumentLimitReached(Exception):
    pass


class SourceNotFound(LookupError):
    pass


class ActivationRefused(Exception):
    """The source cannot become retrievable: no chunks, or a chunk without an embedding for the model (AC5)."""


@dataclass(frozen=True, slots=True)
class ChunkIn:
    text: str
    token_count: int
    locator: Mapping[str, Any] = field(default_factory=dict)
    vectors: Mapping[str, Sequence[float]] = field(default_factory=dict)  # model_name -> embedding (dimension checked against the registry)


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _vec(values: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def count_documents(tenant_id: UUID) -> int:
    with tenant_scope(tenant_id) as conn:
        return _count_documents(conn, tenant_id)


def _count_documents(conn: Any, tenant_id: UUID) -> int:
    row = conn.execute(
        text(f"SELECT count(DISTINCT family_key) FROM rag_source WHERE tenant_id = :t AND collection = 'SELLER_DOCUMENT' AND status IN {_COUNTED}"),  # noqa: S608 - fixed literal
        {"t": str(tenant_id)},
    ).one()
    return int(row[0])


def create_source(
    tenant_id: UUID, *, collection: str, origin_kind: str, origin_ref: Mapping[str, Any] | None, title: str, family_key: str, version: int, trust_class: str,
    freshness_class: str, content_hash: str, chunker_version: str, normaliser_version: str, tags: Sequence[str] = (), byte_size: int = 0, mime: str | None = None,
    object_key: str | None = None, valid_from: date | None = None, expires_at: date | None = None, screen_result: Mapping[str, Any] | None = None,
    created_by: UUID | None = None, max_documents: int | None = None,
) -> UUID:
    """Inserts a PROCESSING source for THIS tenant (never the global collection: that is written only by the curator role). The database refuses a bad collection / origin / trust pairing.
    `max_documents` (the pilot cap) is enforced for the first version of a new document, serialised per tenant."""
    if collection == "GLOBAL_REFERENCE":
        raise ValueError("the global collection is written only by the curator role, never through the tenant repository")
    with tenant_scope(tenant_id) as conn:
        if collection == "SELLER_DOCUMENT" and max_documents is not None:
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"rag-doc-cap:{tenant_id}"})
            known = conn.execute(
                text("SELECT 1 FROM rag_source WHERE tenant_id = :t AND collection = 'SELLER_DOCUMENT' AND family_key = :f LIMIT 1"), {"t": str(tenant_id), "f": family_key}
            ).first()
            if known is None and _count_documents(conn, tenant_id) >= max_documents:
                raise DocumentLimitReached(f"the tenant already holds {max_documents} documents")
        row = conn.execute(
            text(
                """
                INSERT INTO rag_source (tenant_id, collection, origin_kind, origin_ref, title, family_key, version, tags, trust_class, freshness_class, valid_from, expires_at,
                                        content_hash, byte_size, mime, object_key, chunker_version, normaliser_version, screen_result, created_by)
                VALUES (:t, :collection, :origin_kind, CAST(:origin_ref AS jsonb), :title, :family, :version, CAST(:tags AS text[]), :trust, :fresh, :valid_from, :expires_at,
                        :hash, :bytes, :mime, :object_key, :chunker, :normaliser, CAST(:screen AS jsonb), :created_by)
                RETURNING id
                """
            ),
            {
                "t": str(tenant_id), "collection": collection, "origin_kind": origin_kind, "origin_ref": None if origin_ref is None else json.dumps(origin_ref), "title": title,
                "family": family_key, "version": version, "tags": list(tags), "trust": trust_class, "fresh": freshness_class, "valid_from": valid_from, "expires_at": expires_at,
                "hash": content_hash, "bytes": byte_size, "mime": mime, "object_key": object_key, "chunker": chunker_version, "normaliser": normaliser_version,
                "screen": json.dumps(dict(screen_result or {})), "created_by": None if created_by is None else str(created_by),
            },
        ).one()
        return UUID(str(row[0]))


def get_source(tenant_id: UUID, source_id: UUID) -> dict[str, Any] | None:
    """The tenant's own source, or a global one; a foreign or unknown id is `None` (a plain not-found, never a hint that it exists)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(f"SELECT {_SOURCE_COLS} FROM rag_source WHERE id = :id AND (tenant_id = :t OR tenant_id IS NULL)"),  # noqa: S608 - fixed literal
            {"id": str(source_id), "t": str(tenant_id)},
        ).mappings().first()
        return None if row is None else dict(row)


def list_sources(tenant_id: UUID, *, collection: str | None = None, statuses: Sequence[str] | None = None) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                f"SELECT {_SOURCE_COLS} FROM rag_source WHERE tenant_id = :t AND (CAST(:c AS text) IS NULL OR collection = :c) "  # noqa: S608 - fixed literal
                "AND (CAST(:s AS text[]) IS NULL OR status = ANY(CAST(:s AS text[]))) ORDER BY created_at, id"
            ),
            {"t": str(tenant_id), "c": collection, "s": None if statuses is None else list(statuses)},
        ).mappings().all()
        return [dict(r) for r in rows]


def insert_chunks(tenant_id: UUID, source_id: UUID, chunks: Sequence[ChunkIn], *, index_generation: int | None = None) -> list[UUID]:
    """Writes chunks and their per-model embeddings in ONE transaction: all of them or none. A vector whose length differs from its model's registered dimension is refused here
    (and again by the database) - never truncated or padded. Chunks are written for the source's current generation unless a new one is being built beside it."""
    for chunk in chunks:
        for model, vector in chunk.vectors.items():
            if len(vector) != model_dim(model):
                raise ValueError(f"{model}: expected {model_dim(model)} dimensions, got {len(vector)}")
    with tenant_scope(tenant_id) as conn:
        src = conn.execute(
            text("SELECT index_generation FROM rag_source WHERE id = :id AND tenant_id = :t FOR UPDATE"), {"id": str(source_id), "t": str(tenant_id)}
        ).first()
        if src is None:
            raise SourceNotFound("no such source for this tenant")
        generation = index_generation if index_generation is not None else int(src[0])
        start = conn.execute(
            text("SELECT coalesce(max(chunk_index) + 1, 0) FROM rag_chunk WHERE source_id = :s AND index_generation = :g AND tenant_id = :t"),
            {"s": str(source_id), "g": generation, "t": str(tenant_id)},
        ).one()[0]
        ids: list[UUID] = []
        for offset, chunk in enumerate(chunks):
            row = conn.execute(
                text(
                    "INSERT INTO rag_chunk (tenant_id, source_id, index_generation, chunk_index, text, locator, token_count, content_hash) "
                    "VALUES (:t, :s, :g, :i, :text, CAST(:loc AS jsonb), :tok, :h) RETURNING id"
                ),
                {"t": str(tenant_id), "s": str(source_id), "g": generation, "i": int(start) + offset, "text": chunk.text, "loc": json.dumps(dict(chunk.locator)),
                 "tok": chunk.token_count, "h": text_hash(chunk.text)},
            ).one()
            chunk_id = UUID(str(row[0]))
            ids.append(chunk_id)
            for model, vector in chunk.vectors.items():
                conn.execute(
                    text(
                        "INSERT INTO rag_chunk_embedding (chunk_id, tenant_id, model_name, model_dim, embedding) "
                        "VALUES (:c, :t, :m, :d, CAST(:v AS vector))"
                    ),
                    {"c": str(chunk_id), "t": str(tenant_id), "m": model, "d": model_dim(model), "v": _vec(vector)},
                )
        return ids


def activate_source(tenant_id: UUID, source_id: UUID, *, model_name: str) -> None:
    """PROCESSING -> ACTIVE in one transaction, only if the source has chunks in its current generation and EVERY one has an embedding for `model_name` (AC5: a failed or partial
    embed leaves the source retrievable by nothing). If an earlier version of the family is ACTIVE it is superseded in the same transaction, so there is never a moment with zero or two
    ACTIVE versions (AC7)."""
    model_dim(model_name)  # raises for an unregistered model
    with tenant_scope(tenant_id) as conn:
        src = conn.execute(
            text("SELECT family_key, status, index_generation FROM rag_source WHERE id = :id AND tenant_id = :t FOR UPDATE"), {"id": str(source_id), "t": str(tenant_id)}
        ).first()
        if src is None:
            raise SourceNotFound("no such source for this tenant")
        family, status, generation = src[0], src[1], int(src[2])
        if status != "PROCESSING":
            raise ActivationRefused(f"a {status} source cannot be activated")
        counts = conn.execute(
            text(
                "SELECT count(*), count(e.chunk_id) FROM rag_chunk c LEFT JOIN rag_chunk_embedding e ON e.chunk_id = c.id AND e.model_name = :m "
                "WHERE c.source_id = :s AND c.index_generation = :g AND c.tenant_id = :t"
            ),
            {"m": model_name, "s": str(source_id), "g": generation, "t": str(tenant_id)},
        ).one()
        if int(counts[0]) == 0 or int(counts[0]) != int(counts[1]):
            raise ActivationRefused(f"{counts[1]} of {counts[0]} chunks have a {model_name} embedding")
        conn.execute(
            text("UPDATE rag_source SET status = 'SUPERSEDED' WHERE tenant_id = :t AND family_key = :f AND status = 'ACTIVE' AND id <> :id"),
            {"t": str(tenant_id), "f": family, "id": str(source_id)},
        )
        conn.execute(text("UPDATE rag_source SET status = 'ACTIVE' WHERE id = :id AND tenant_id = :t"), {"id": str(source_id), "t": str(tenant_id)})


def mark_failed(tenant_id: UUID, source_id: UUID, reason: str, *, rejected: bool = False) -> None:
    """PROCESSING -> FAILED (retryable) or REJECTED (terminal, e.g. an unreadable file), with a plain reason. Nothing of it is retrievable."""
    with tenant_scope(tenant_id) as conn:
        updated = conn.execute(
            text("UPDATE rag_source SET status = :s, failure_reason = :r WHERE id = :id AND tenant_id = :t RETURNING id"),
            {"s": "REJECTED" if rejected else "FAILED", "r": reason, "id": str(source_id), "t": str(tenant_id)},
        ).first()
        if updated is None:
            raise SourceNotFound("no such source for this tenant")


def delete_source(tenant_id: UUID, source_id: UUID) -> None:
    """Seller-initiated delete (AC6): the source flips to DELETED and its chunks and embeddings are removed in the SAME transaction, so nothing of it is retrievable from the instant
    this returns. The source row stays as a content-free tombstone (title is replaced); the original file is purged by the purge job."""
    with tenant_scope(tenant_id) as conn:
        found = conn.execute(text("SELECT status FROM rag_source WHERE id = :id AND tenant_id = :t FOR UPDATE"), {"id": str(source_id), "t": str(tenant_id)}).first()
        if found is None:
            raise SourceNotFound("no such source for this tenant")
        conn.execute(
            text("DELETE FROM rag_chunk_embedding WHERE tenant_id = :t AND chunk_id IN (SELECT id FROM rag_chunk WHERE source_id = :s AND tenant_id = :t)"),
            {"t": str(tenant_id), "s": str(source_id)},
        )
        conn.execute(text("DELETE FROM rag_chunk WHERE source_id = :s AND tenant_id = :t"), {"s": str(source_id), "t": str(tenant_id)})
        if found[0] != "DELETED":
            conn.execute(text("UPDATE rag_source SET status = 'DELETED', title = 'deleted' WHERE id = :id AND tenant_id = :t"), {"id": str(source_id), "t": str(tenant_id)})


def nearest_chunks(
    tenant_id: UUID, agent: str, collections: Sequence[str], model_name: str, query_vector: Sequence[float], *, limit: int = 10
) -> list[dict[str, Any]]:
    """LOW-LEVEL single-model cosine search (not the retrieval pipeline). Only chunks that are SERVABLE (spec 7.3): source ACTIVE and the chunk of its current generation. The collections
    must all be permitted to `agent` (grid); the tenant is filtered explicitly beneath RLS; the model's partial HNSW index is used via the same cast expression. Returns ids, collection
    and distance - never ranked as truth."""
    allowed = grid.permitted(agent, list(collections))
    dim = model_dim(model_name)
    if len(query_vector) != dim:
        raise ValueError(f"{model_name}: expected {dim} dimensions, got {len(query_vector)}")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    expr = f"(e.embedding::vector({dim}))"  # dim comes from the fixed registry, never from input
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                f"SELECT c.id AS chunk_id, c.source_id, s.collection, c.text, {expr} <=> CAST(:q AS vector({dim})) AS distance "  # noqa: S608 - dim is a registry integer
                "FROM rag_chunk_embedding e JOIN rag_chunk c ON c.id = e.chunk_id JOIN rag_source s ON s.id = c.source_id "
                f"WHERE e.model_name = :m AND s.status = 'ACTIVE' AND c.index_generation = s.index_generation AND s.collection = ANY(CAST(:cols AS text[])) "
                "AND (s.tenant_id = :t OR (s.tenant_id IS NULL AND s.collection = 'GLOBAL_REFERENCE')) "
                f"ORDER BY {expr} <=> CAST(:q AS vector({dim})) LIMIT :n"
            ),
            {"q": _vec(query_vector), "m": model_name, "cols": list(allowed), "t": str(tenant_id), "n": limit},
        ).mappings().all()
        return [dict(r) for r in rows]


def query_hash(query: str) -> str:
    return text_hash(" ".join(query.split()).lower())


def log_retrieval(
    tenant_id: UUID, *, agent: str, query: str, collections: Sequence[str], status: str, item_count: int, latency_ms: int, embed_ms: int | None = None,
    fts_ms: int | None = None, embedding_model: str | None = None, run_id: UUID | None = None,
) -> UUID:
    """Content-free observability (AC17): the query is reduced to a sha256 here and never stored; no chunk text or document name has a column to land in."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "INSERT INTO rag_retrieval_log (tenant_id, agent_code, run_id, collections, status, item_count, latency_ms, embed_ms, fts_ms, embedding_model, query_hash) "
                "VALUES (:t, :a, :run, CAST(:cols AS text[]), :s, :n, :lat, :e, :f, :m, :h) RETURNING id"
            ),
            {"t": str(tenant_id), "a": agent, "run": None if run_id is None else str(run_id), "cols": list(collections), "s": status, "n": item_count, "lat": latency_ms,
             "e": embed_ms, "f": fts_ms, "m": embedding_model, "h": query_hash(query)},
        ).one()
        return UUID(str(row[0]))


def add_usage(tenant_id: UUID, day: date, *, chunks: int = 0, tokens: int = 0, queries: int = 0) -> None:
    """Embedding cost counters per tenant per day (atomic upsert)."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                "INSERT INTO rag_usage_daily (tenant_id, day, chunks_embedded, tokens_embedded, queries_embedded) VALUES (:t, :d, :c, :k, :q) "
                "ON CONFLICT (tenant_id, day) DO UPDATE SET chunks_embedded = rag_usage_daily.chunks_embedded + EXCLUDED.chunks_embedded, "
                "tokens_embedded = rag_usage_daily.tokens_embedded + EXCLUDED.tokens_embedded, queries_embedded = rag_usage_daily.queries_embedded + EXCLUDED.queries_embedded"
            ),
            {"t": str(tenant_id), "d": day, "c": chunks, "k": tokens, "q": queries},
        )


def get_usage(tenant_id: UUID, day: date) -> dict[str, int] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT chunks_embedded, tokens_embedded, queries_embedded FROM rag_usage_daily WHERE tenant_id = :t AND day = :d"), {"t": str(tenant_id), "d": day}
        ).first()
        return None if row is None else {"chunks_embedded": int(row[0]), "tokens_embedded": int(row[1]), "queries_embedded": int(row[2])}


def enqueue_event(tenant_id: UUID, kind: str, ref: Mapping[str, Any]) -> UUID:
    """Outbox row (spec 7.6), written in the caller's own unit of work in a later slice; here it is a standalone append."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("INSERT INTO rag_index_event (tenant_id, kind, ref) VALUES (:t, :k, CAST(:r AS jsonb)) RETURNING id"), {"t": str(tenant_id), "k": kind, "r": json.dumps(dict(ref))}
        ).one()
        return UUID(str(row[0]))


__all__ = [
    "ActivationRefused", "ChunkIn", "DocumentLimitReached", "KNOWN_MODELS", "SourceNotFound", "activate_source", "add_usage", "count_documents", "create_source", "delete_source",
    "enqueue_event", "get_source", "get_usage", "insert_chunks", "list_sources", "log_retrieval", "mark_failed", "nearest_chunks", "query_hash", "text_hash",
]
