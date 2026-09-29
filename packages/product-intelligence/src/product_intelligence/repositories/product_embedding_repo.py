"""product_embedding — C13 (pgvector, not Qdrant). Derived-attribute-only embeddings
(`title_length`/`title_structure`/`keyword_themes`, theme vectors, category text — never a
paraphrase of any listing copy, D5). `model_name`/`model_dim` are stored alongside every
vector so a model swap is a detectable, scriptable re-index (E14) rather than silent
corruption.

**Checkpoint 1 scaffolding only** — every function below is a `NotImplementedError` stub.
Every function takes `tenant_id` first, per CI's convention.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID


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
    `model_dim`-long; the real implementation (Checkpoint 2) rejects a mismatched length
    rather than silently truncating or padding."""
    raise NotImplementedError("product_embedding_repo.upsert_embedding: Checkpoint 2")


def get_embeddings_for_subject(tenant_id: UUID, subject_type: str, subject_id: UUID) -> list[dict[str, Any]]:
    raise NotImplementedError("product_embedding_repo.get_embeddings_for_subject: Checkpoint 2")


def find_nearest(
    tenant_id: UUID,
    *,
    subject_type: str,
    embedding: list[float],
    model_name: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Cosine/L2 nearest-neighbour lookup via pgvector — backs near-duplicate candidate
    grouping (E12) and niche-to-category matching. Never compares across `model_name`
    values (E14) — a mismatch is a re-index precondition, not a query-time coercion."""
    raise NotImplementedError("product_embedding_repo.find_nearest: Checkpoint 2")
