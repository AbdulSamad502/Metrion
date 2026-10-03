"""Shared builders for the trend tests. All dates are relative to a fixed clock so every
boundary is exact."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from slim_cmo.trends.evidence import Thresholds
from slim_cmo.trends.sources import SourceItem, SourceType

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
T = Thresholds(fresh_window_days=7, recent_window_days=30, moderate_min_independent_sources=2, strong_min_independent_sources=4)


def item(
    url: str = "https://example.invalid/a",
    *,
    title: str | None = None,
    age: timedelta | None = None,
    published: datetime | None = None,
    kind: SourceType = SourceType.WEB,
    retrieved: datetime = NOW,
    channel_id: str | None = None,
    channel_title: str | None = None,
) -> SourceItem:
    if published is None and age is not None:
        published = retrieved - age
    return SourceItem(
        url=url, source_type=kind, retrieved_at=retrieved, title=title,
        published_at=published, channel_id=channel_id, channel_title=channel_title,
    )


def days(n: int, *, seconds: int = 0) -> timedelta:
    return timedelta(days=n, seconds=seconds)
