"""seller_product_profile — competitor-intelligence-agent.md §5.5.1 Source 2 / §5.5.2, C31.

Every function takes tenant_id first and receives its connection only via tenant_scope(); no
function in this module opens its own connection (auth.md §7.3). This is the *only* write
path to `seller_product_profile` in the codebase — CI itself never writes it (AC22b, T73);
this repository exists to be called from the seller-product-profile API
(`backend/api/v1/ci.py`), a seller-facing surface, not from any CI agent/derivation code.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.repositories.tenant_context import tenant_scope


def get_profile(tenant_id: UUID, product_id: str) -> dict[str, Any] | None:
    """Returns the raw stored row (or `None` if the seller has never filled the form for this
    product) — callers pass this straight into `seller_product.merge.merge_seller_product`'s
    `manual_overrides` argument alongside `derive.derive_canonical`'s output."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                SELECT product_id, category, attributes, keywords, price_paise,
                       fulfillment_type, updated_by, updated_at
                FROM seller_product_profile
                WHERE tenant_id = :tenant_id AND product_id = :product_id
                """
            ),
            {"tenant_id": str(tenant_id), "product_id": product_id},
        ).mappings().first()
        return dict(row) if row is not None else None


def upsert_profile(
    tenant_id: UUID,
    product_id: str,
    *,
    category: str | None,
    attributes: list[dict[str, str]] | None,
    keywords: list[str] | None,
    price_paise: int | None,
    fulfillment_type: str | None,
    updated_by: UUID,
) -> None:
    """Full replace of every column on each call (AC22c: "editable at any time, not
    write-once") — the seller-product-profile form is small enough that the API always
    resubmits the whole profile, exactly like `competitor_url_repo.set_tags`'s full-replace
    semantics rather than a per-field PATCH. Passing `None` for a field explicitly clears it
    back to `UNKNOWN` — this is never a silent default, it is the seller (via the API layer)
    stating "this field is blank" as an explicit act."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO seller_product_profile
                    (tenant_id, product_id, category, attributes, keywords, price_paise,
                     fulfillment_type, updated_by, updated_at)
                VALUES
                    (:tenant_id, :product_id, :category, CAST(:attributes AS jsonb),
                     CAST(:keywords AS text[]), :price_paise, :fulfillment_type, :updated_by, now())
                ON CONFLICT (tenant_id, product_id) DO UPDATE SET
                    category = EXCLUDED.category,
                    attributes = EXCLUDED.attributes,
                    keywords = EXCLUDED.keywords,
                    price_paise = EXCLUDED.price_paise,
                    fulfillment_type = EXCLUDED.fulfillment_type,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = now()
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "product_id": product_id,
                "category": category,
                "attributes": json.dumps(attributes) if attributes is not None else None,
                "keywords": keywords,
                "price_paise": price_paise,
                "fulfillment_type": fulfillment_type,
                "updated_by": str(updated_by),
            },
        )


def profile_to_manual_overrides(row: dict[str, Any] | None) -> dict[str, Any]:
    """Adapts a stored row into the generic `manual_overrides` mapping
    `seller_product.merge.merge_seller_product` expects — `attributes`/`keywords` come back
    from Postgres already deserialised (jsonb -> list of dicts, text[] -> list of str) via
    SQLAlchemy, so this is a rename/reshape only, never a value transformation."""
    if row is None:
        return {}
    overrides: dict[str, Any] = {}
    if row.get("category") is not None:
        overrides["category"] = row["category"]
    if row.get("attributes") is not None:
        overrides["attributes"] = tuple((a["key"], a["value"]) for a in row["attributes"])
    if row.get("keywords") is not None:
        overrides["keywords"] = tuple(row["keywords"])
    if row.get("price_paise") is not None:
        overrides["price_paise"] = row["price_paise"]
    if row.get("fulfillment_type") is not None:
        overrides["fulfillment_type"] = row["fulfillment_type"]
    if row.get("updated_at") is not None:
        overrides["updated_at"] = row["updated_at"]
    return overrides
