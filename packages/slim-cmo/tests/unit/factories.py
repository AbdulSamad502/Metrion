"""Builders for unit tests. Every value here is a TEST value - none is a verified marketplace
rule, a production default or a recommended threshold. The numbers are deliberately unlike any
real marketplace limit so a test can never be mistaken for documentation of one."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from slim_cmo.config import TrendConfig, load_trend_config
from slim_cmo.constraints import FormatConstraint
from slim_cmo.types import ConstraintRowKind, CountRule, Marketplace

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def constraint(
    marketplace: Marketplace = Marketplace.AMAZON,
    *,
    category: str | None = None,
    version: int = 1,
    row_kind: ConstraintRowKind = ConstraintRowKind.VERIFIED,
    verified_at: datetime | None = None,
    **limits: Any,
) -> FormatConstraint:
    base: dict[str, Any] = dict(
        title_max_chars=40,
        title_option_count=3,
        bullet_count=3,
        bullet_max_chars=60,
        description_type="plain",
        description_max_chars=300,
        keywords_max_count=5,
        keywords_max_chars=20,
        backend_terms_max_bytes=50 if marketplace is Marketplace.AMAZON else None,
        hashtags_supported=None,
        count_rule=CountRule.UTF16_CODE_UNITS,  # a TEST value; real rules are verified per marketplace
    )
    base.update(limits)
    return FormatConstraint(
        id=uuid.uuid4(),
        marketplace=marketplace,
        category=category,
        version=version,
        row_kind=row_kind,
        source_url="https://example.invalid/test-fixture",
        verified_at=verified_at if verified_at is not None else NOW - timedelta(days=1),
        **base,
    )


VALID_TREND_VALUES: dict[str, Any] = {
    "max_queries_per_report": 20,
    "section_query_budgets": {"NICHE": 5, "MARKET_NEWS": 5, "REPORTED_TACTICS": 4, "NEW_PRODUCTS_BUZZ": 3, "ADJACENT": 3},
    "section_priority": ["NICHE", "MARKET_NEWS", "NEW_PRODUCTS_BUZZ", "REPORTED_TACTICS", "ADJACENT"],
    "max_results_per_query": 7,
    "max_sources_per_report": 30,
    "max_findings_per_section": 4,
    "fresh_window_days": 7,
    "recent_window_days": 30,
    "news_window_days": 14,
    "moderate_min_independent_sources": 2,
    "strong_min_independent_sources": 4,
    "max_confirmed_niche_terms": 6,
    "max_term_chars": 30,
    "catalog_titles_read_cap": 100,
    "provider_call_timeout_seconds": 11,
}


def trend_values(**overrides: Any) -> dict[str, Any]:
    values = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in VALID_TREND_VALUES.items()}
    values.update(overrides)
    return values


def trend_config(**overrides: Any) -> TrendConfig:
    result = load_trend_config(trend_values(**overrides))
    assert isinstance(result, TrendConfig), result
    return result
