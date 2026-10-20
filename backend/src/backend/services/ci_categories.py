"""Category-driven competitor discovery (owner decision 2026-10-20): the seller says "find my competitors", the CEO asks WHICH of the categories they gave in their business profile,
and one search runs per chosen category. A category is not one of the seller's products, so the search is built from the category name alone (identity stays UNCERTAIN, leads are
ranked by how well the title matches) and the run is tagged `category:<slug>`; competitors the seller then tracks from it show on the dashboard under that category.

Read-only for the profile; the discovery itself is the same `run_discovery` every other search uses (Tavily, lead-only, behind the same plan approval)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from competitor_intelligence.seller_product.types import FieldSource, SellerProduct

from backend.repositories import business_profile_repo

MAX_CATEGORIES = 8  # how many a profile can offer (a reading bound, not a business rule)
CATEGORY_PREFIX = "category:"
_SPLIT = re.compile(r"[,;/|\n]+|\s+&\s+|\s+and\s+", re.IGNORECASE)
_ALL = re.compile(r"\b(?:all|every|everything|both)\b", re.IGNORECASE)


def parse_categories(text: str | None) -> list[str]:
    """The profile's free-text categories ("Water bottles, polo t-shirts and sports shoes") as short, distinct names, in the order the seller wrote them."""
    seen: dict[str, str] = {}
    for part in _SPLIT.split(text or ""):
        name = " ".join(part.split()).strip(" .-")
        if 2 <= len(name) <= 60 and name.casefold() not in seen:
            seen[name.casefold()] = name[:1].upper() + name[1:]
    return list(seen.values())[:MAX_CATEGORIES]


def business_categories(tenant_id: UUID) -> list[str]:
    row = business_profile_repo.get(tenant_id)
    return parse_categories(row["categories"]) if row else []


def resolve_categories(raw: str | None, categories: list[str]) -> list[str]:
    """Which of `categories` the seller meant by "1 and 3", "water bottles", "all". Only listed categories can be chosen: nothing is invented, and text that names none gives []."""
    text = " ".join((raw or "").split())
    if not text or not categories:
        return []
    if _ALL.search(text) and not re.search(r"\bat all\b", text, re.IGNORECASE):
        return list(categories)
    chosen: list[str] = []
    for n in (int(x) for x in re.findall(r"(?<![\w.])\d{1,2}(?![\w.])", text)):
        if 1 <= n <= len(categories) and categories[n - 1] not in chosen:
            chosen.append(categories[n - 1])
    low = text.casefold()
    for c in categories:
        if c.casefold() in low and c not in chosen:
            chosen.append(c)
    return [c for c in categories if c in chosen]


def category_key(name: str) -> str:
    return CATEGORY_PREFIX + (" ".join(name.casefold().split())[:60] or "category")


def category_name(ref: str | None) -> str | None:
    """A readable name for a `category:` reference ("category:water bottles" -> "Water bottles"), else None."""
    if not ref or not str(ref).startswith(CATEGORY_PREFIX):
        return None
    name = str(ref)[len(CATEGORY_PREFIX):].strip()
    return name[:1].upper() + name[1:] if name else None


def category_seller_product(name: str) -> SellerProduct:
    """A search input made of the category name only. Nothing about the seller's price, brand or attributes is implied."""
    return SellerProduct(
        product_id=category_key(name), title=name, category=name, price_paise=None, attributes=None, keywords=None, fulfillment_type=None, review_count=None, rating=None,
        last_updated=datetime.now(timezone.utc), field_source={"title": FieldSource.SELLER_ENTERED, "category": FieldSource.SELLER_ENTERED},
    )


def discover_categories(tenant_id: UUID, *, requested_by: UUID, categories: list[str]) -> dict[str, Any]:
    """One discovery run per chosen category (each its own run, budget and cache), merged into one result of the same shape a single search returns."""
    from backend.services.ci_actions import run_discovery  # noqa: PLC0415

    outcomes = [run_discovery(tenant_id, requested_by=requested_by, seller_product=category_seller_product(c)) for c in categories]
    statuses = {o.status for o in outcomes}
    status = outcomes[0].status if len(statuses) == 1 else ("FAILED" if statuses == {"FAILED"} else "PARTIAL")
    return {
        "discoveryRunId": str(outcomes[-1].discovery_run_id), "discoveryRunIds": [str(o.discovery_run_id) for o in outcomes], "status": status, "categories": list(categories),
        "rawCandidateCount": sum(o.raw_candidate_count for o in outcomes), "analyzedCandidateCount": sum(o.analyzed_candidate_count for o in outcomes),
        "recommendedCandidateIds": [str(c) for o in outcomes for c in o.recommended_candidate_ids], "uncertainCandidateIds": [str(c) for o in outcomes for c in o.uncertain_candidate_ids],
        "partialReason": next((o.partial_reason for o in outcomes if o.partial_reason), None), "failedReason": next((o.failed_reason for o in outcomes if o.failed_reason), None),
    }
