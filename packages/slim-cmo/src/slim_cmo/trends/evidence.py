"""Deterministic trend-evidence logic (spec §6.8.4, C14, AC27, AC28).

Given the items found for one theme, compute - in code, from configured thresholds, never by
the model - how many INDEPENDENT sources back it, how recent they are, and how strongly the
attention is corroborated. The model writes prose around these results; it may not assign,
edit or round any of them.

Pipeline for one finding's items:

1. Drop items with no citable URL (counted, reported).
2. `mention_count` = citable items. Shown to the seller, but NEVER used for strength.
3. Syndication collapse: items whose normalised titles are identical are one story. The
   representative is the earliest-published (a dated item beats an undated one; ties broken by
   URL so the choice never depends on input order). Different domains republishing one wire
   story therefore count once.
4. Independence: representatives are grouped by `sources.independence_key`; the number of
   distinct keys is `independent_source_count`.
5. Recency per representative; the finding's recency is its FRESHEST representative's class.
6. Corroboration from the independent count and the finding's recency.

Corroboration describes how widely ATTENTION is reported. It is never evidence of demand,
sales or profitability (§6.8.7 rule 1) and every consumer must say so.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from slim_cmo.config import TrendConfig
from slim_cmo.trends.sources import SourceItem, independence_key, is_citable, normalise_title


class RecencyClass(str, Enum):
    FRESH = "FRESH"
    RECENT = "RECENT"
    OLDER = "OLDER"
    DATE_UNKNOWN = "DATE_UNKNOWN"


class Corroboration(str, Enum):
    """Ordered weakest -> strongest. SINGLE_SOURCE means exactly one independent source and is
    never produced by a downgrade (a downgrade floors at WEAK for 2+ sources)."""

    SINGLE_SOURCE = "SINGLE_SOURCE"
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"


_RECENCY_RANK = {RecencyClass.FRESH: 0, RecencyClass.RECENT: 1, RecencyClass.OLDER: 2, RecencyClass.DATE_UNKNOWN: 3}


@dataclass(frozen=True, slots=True)
class Thresholds:
    fresh_window_days: int
    recent_window_days: int
    moderate_min_independent_sources: int
    strong_min_independent_sources: int

    def __post_init__(self) -> None:
        # Re-asserts the invariants config.load_trend_config already enforces, so a caller that
        # builds Thresholds by hand cannot create a nonsensical scale.
        for name in ("fresh_window_days", "recent_window_days", "moderate_min_independent_sources", "strong_min_independent_sources"):
            v = getattr(self, name)
            if type(v) is not int or v < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.fresh_window_days > self.recent_window_days:
            raise ValueError("fresh_window_days must be <= recent_window_days")
        if self.moderate_min_independent_sources < 2:
            raise ValueError("moderate_min_independent_sources must be >= 2 (one source is SINGLE_SOURCE by definition)")
        if self.strong_min_independent_sources <= self.moderate_min_independent_sources:
            raise ValueError("strong_min_independent_sources must exceed moderate_min_independent_sources")

    @classmethod
    def from_config(cls, config: TrendConfig) -> "Thresholds":
        return cls(
            config.fresh_window_days,
            config.recent_window_days,
            config.moderate_min_independent_sources,
            config.strong_min_independent_sources,
        )


def _require_aware(dt: datetime, name: str) -> None:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RecencyResult:
    recency: RecencyClass
    future_date: bool  # published_at is after retrieved_at: treated as unknown, never as 'fresh'


def classify_recency(published_at: datetime | None, retrieved_at: datetime, t: Thresholds) -> RecencyResult:
    """FRESH if age <= fresh_window_days; RECENT if <= recent_window_days; else OLDER. The
    boundary is inclusive: an age of exactly the window is still inside it. No publication date
    -> DATE_UNKNOWN (the retrieval date is NEVER substituted). A publication date after the
    retrieval date is clock-skew or bad data -> DATE_UNKNOWN, flagged."""
    _require_aware(retrieved_at, "retrieved_at")
    if published_at is None:
        return RecencyResult(RecencyClass.DATE_UNKNOWN, False)
    _require_aware(published_at, "published_at")
    age = retrieved_at - published_at
    if age < timedelta(0):
        return RecencyResult(RecencyClass.DATE_UNKNOWN, True)
    if age <= timedelta(days=t.fresh_window_days):
        return RecencyResult(RecencyClass.FRESH, False)
    if age <= timedelta(days=t.recent_window_days):
        return RecencyResult(RecencyClass.RECENT, False)
    return RecencyResult(RecencyClass.OLDER, False)


def corroboration_level(independent_sources: int, freshest: RecencyClass, t: Thresholds) -> Corroboration:
    if type(independent_sources) is not int or independent_sources < 1:
        raise ValueError("a finding needs at least one independent source")
    if independent_sources == 1:
        return Corroboration.SINGLE_SOURCE
    if independent_sources >= t.strong_min_independent_sources:
        level = Corroboration.STRONG
    elif independent_sources >= t.moderate_min_independent_sources:
        level = Corroboration.MODERATE
    else:
        level = Corroboration.WEAK
    if freshest is RecencyClass.OLDER:  # one level down, never below WEAK
        level = {Corroboration.STRONG: Corroboration.MODERATE}.get(level, Corroboration.WEAK)
    elif freshest is RecencyClass.DATE_UNKNOWN:  # every source undated: capped at WEAK
        level = Corroboration.WEAK
    return level


@dataclass(frozen=True, slots=True)
class ItemEvidence:
    url: str
    independence_key: str
    recency: RecencyClass
    published_at: datetime | None
    future_date: bool
    collapsed_into: str | None  # url of the representative this syndicated copy folded into


@dataclass(frozen=True, slots=True)
class Evidence:
    mention_count: int
    independent_source_count: int
    independence_keys: tuple[str, ...]
    representatives: tuple[SourceItem, ...]
    collapsed_duplicates: int
    uncitable_dropped: int
    freshest_published_at: datetime | None
    oldest_published_at: datetime | None
    recency: RecencyClass
    corroboration: Corroboration | None  # None only when there is no citable evidence at all
    is_stale: bool
    items: tuple[ItemEvidence, ...]

    @property
    def has_citable_evidence(self) -> bool:
        return self.independent_source_count > 0


def _representative_order(item: SourceItem) -> tuple[int, datetime, str]:
    """Dated before undated; earliest first; URL as the final, input-order-independent tie-break."""
    if item.published_at is None:
        return (1, datetime.max.replace(tzinfo=item.retrieved_at.tzinfo), item.url)
    return (0, item.published_at, item.url)


def collapse_syndicated(items: Sequence[SourceItem]) -> tuple[tuple[SourceItem, ...], dict[str, str]]:
    """Collapse items whose normalised titles are identical. Returns (representatives sorted by
    URL, {collapsed item url: representative url}). Items with no comparable title are never
    collapsed."""
    groups: dict[str, list[SourceItem]] = {}
    untitled: list[SourceItem] = []
    for item in items:
        key = normalise_title(item.title)
        (groups.setdefault(key, []) if key else untitled).append(item)
    representatives: list[SourceItem] = list(untitled)
    folded: dict[str, str] = {}
    for members in groups.values():
        ordered = sorted(members, key=_representative_order)
        representatives.append(ordered[0])
        for other in ordered[1:]:
            if other.url != ordered[0].url:
                folded[other.url] = ordered[0].url
    # the same URL listed twice is one item, not a syndicated copy of itself
    unique: dict[str, SourceItem] = {}
    for r in representatives:
        unique.setdefault(r.url, r)
    return tuple(sorted(unique.values(), key=lambda i: i.url)), folded


def evaluate_evidence(items: Sequence[SourceItem], t: Thresholds) -> Evidence:
    citable = [i for i in items if is_citable(i)]
    dropped = len(items) - len(citable)
    if not citable:
        return Evidence(0, 0, (), (), 0, dropped, None, None, RecencyClass.DATE_UNKNOWN, None, True, ())

    reps, folded = collapse_syndicated(citable)

    per_item: list[ItemEvidence] = []
    rep_recency: list[tuple[SourceItem, RecencyClass]] = []
    for item in sorted(citable, key=lambda i: i.url):
        result = classify_recency(item.published_at, item.retrieved_at, t)
        per_item.append(
            ItemEvidence(
                url=item.url,
                independence_key=independence_key(item),
                recency=result.recency,
                published_at=item.published_at,
                future_date=result.future_date,
                collapsed_into=folded.get(item.url),
            )
        )
        if item in reps:
            rep_recency.append((item, result.recency))

    keys = tuple(sorted({independence_key(r) for r in reps}))
    freshest_class = min((c for _, c in rep_recency), key=lambda c: _RECENCY_RANK[c])
    dated = [i.published_at for i, c in rep_recency if i.published_at is not None and c is not RecencyClass.DATE_UNKNOWN]
    n = len(keys)
    return Evidence(
        mention_count=len(citable),
        independent_source_count=n,
        independence_keys=keys,
        representatives=reps,
        collapsed_duplicates=len(folded),
        uncitable_dropped=dropped,
        freshest_published_at=max(dated) if dated else None,
        oldest_published_at=min(dated) if dated else None,
        recency=freshest_class,
        corroboration=corroboration_level(n, freshest_class, t),
        is_stale=freshest_class in (RecencyClass.OLDER, RecencyClass.DATE_UNKNOWN),
        items=tuple(per_item),
    )
