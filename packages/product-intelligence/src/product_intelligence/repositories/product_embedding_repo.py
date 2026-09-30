"""product_embedding — C13 (pgvector, not Qdrant). Derived-attribute-only embeddings
(`title_length`/`title_structure`/`keyword_themes`, theme vectors, category text — never a
paraphrase of any listing copy, D5). `model_name`/`model_dim` are stored alongside every
vector so a model swap is a detectable, scriptable re-index (E14) rather than silent
corruption.

**Checkpoint 2 — real implementation.** Every function takes `tenant_id` first and receives
its connection only via `tenant_scope()` (auth.md §7.3), matching every other repository in
this package. Nearest-neighbour lookup (`find_nearest`) uses pgvector's cosine-distance
operator `<=>` — the model this package embeds with (`nomic-embed-text`, §2) is normalised
for cosine similarity, matching `product-intelligence-agent.md` §5's "Similarity needs" list
(near-duplicate detection, theme clustering, niche-to-category matching, feasibility
comparables), none of which are money-touching figures — embedding vectors are plain floats,
never inputs to any Brain-1 calculation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from product_intelligence.repositories.tenant_context import tenant_scope


def _to_vector_literal(embedding: list[float]) -> str:
    """pgvector's text input format: `[v1,v2,...]`. `repr(float)` round-trips exactly for a
    Python float, which is all pgvector's own column type can represent — there is no paise/
    Paise equivalent for an embedding vector, so this is not a hard-rule money violation."""
    return "[" + ",".join(repr(v) for v in embedding) + "]"


def upsert_embedding(
    tenant_id: UUID,
    *,
    subject_type: str,
    subject_id: UUID,
    embedding: list[float],
    model_name: str,
    model_dim: int,
    created_at: datetime,
) -> UUID:
    """`subject_type` is `CANDIDATE` | `THEME` | `CATEGORY`. `embedding` is exactly
    `model_dim`-long; a mismatched length is rejected rather than silently truncated or
    padded. "Upsert" here means "replace the existing (tenant, subject_type, subject_id,
    model_name) row if one exists" — there is no unique constraint enforcing that in the
    migration, so this function performs the delete-then-insert itself, atomically within
    `tenant_scope`'s single transaction."""
    if len(embedding) != model_dim:
        raise ValueError(
            f"upsert_embedding: embedding length {len(embedding)} does not match "
            f"model_dim={model_dim} for model {model_name!r} — rejected, never truncated or padded"
        )

    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                "DELETE FROM product_embedding WHERE tenant_id = :tenant_id AND subject_type = :subject_type "
                "AND subject_id = :subject_id AND model_name = :model_name"
            ),
            {
                "tenant_id": str(tenant_id),
                "subject_type": subject_type,
                "subject_id": str(subject_id),
                "model_name": model_name,
            },
        )
        row = conn.execute(
            text(
                """
                INSERT INTO product_embedding
                    (tenant_id, subject_type, subject_id, embedding, model_name, model_dim, created_at)
                VALUES
                    (:tenant_id, :subject_type, :subject_id, CAST(:embedding AS vector), :model_name,
                     :model_dim, :created_at)
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "subject_type": subject_type,
                "subject_id": str(subject_id),
                "embedding": _to_vector_literal(embedding),
                "model_name": model_name,
                "model_dim": model_dim,
                "created_at": created_at,
            },
        ).one()
        return row[0]


def get_embeddings_for_subject(tenant_id: UUID, subject_type: str, subject_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT * FROM product_embedding WHERE tenant_id = :tenant_id "
                "AND subject_type = :subject_type AND subject_id = :subject_id"
            ),
            {"tenant_id": str(tenant_id), "subject_type": subject_type, "subject_id": str(subject_id)},
        ).mappings().all()
        return [dict(r) for r in rows]


def find_nearest(
    tenant_id: UUID,
    *,
    subject_type: str,
    embedding: list[float],
    model_name: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Cosine nearest-neighbour lookup via pgvector's `<=>` operator — backs near-duplicate
    candidate grouping (E12) and niche-to-category matching. Never compares across
    `model_name` values (E14) — a mismatch is a re-index precondition, not a query-time
    coercion, enforced here by always filtering on `model_name` explicitly."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT *, embedding <=> CAST(:embedding AS vector) AS distance
                FROM product_embedding
                WHERE tenant_id = :tenant_id AND subject_type = :subject_type AND model_name = :model_name
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :limit
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "subject_type": subject_type,
                "model_name": model_name,
                "embedding": _to_vector_literal(embedding),
                "limit": limit,
            },
        ).mappings().all()
        return [dict(r) for r in rows]
