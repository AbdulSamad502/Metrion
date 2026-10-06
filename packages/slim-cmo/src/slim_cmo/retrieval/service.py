"""Market Signal Retrieval, CMO side (spec §6.8, plan 7e): runs a validated `QueryPlan` against the shared providers.

Deterministic and bounded; **no LLM**. For every planned query, in plan order:

1. the egress guard (`validate_egress`) has already passed for the WHOLE plan before the first call - and it is re-run
   here, immediately before any provider call, so a plan altered after it was shown to the seller is refused;
2. a 24h (configurable) cache lookup - a hit makes NO provider call and consumes NO daily slot;
3. otherwise one daily slot is taken from the database counter BEFORE the call (fail closed: a counter error means no
   call; a refused slot means no call). Failed provider attempts keep their slot (conservative accounting);
4. the call is made inside the shared process-wide throttle (`market_signals.rate_limiter`, 3 per provider PER PROCESS:
   N server workers allow up to 3xN concurrent calls) with the CMO-only provider options, and the configured timeout is
   baked into the client the caller passes in.

A failure, a refused slot or a reached daily ceiling degrades only the affected query: its section becomes `PARTIAL`
(some queries answered) or `UNAVAILABLE` (none), with the reason; the report carries on with the other sections.

Cache isolation: keys are `(source, provider, template, normalised query text, exact provider options)`, in a source
namespace of their own (`cmo_*`), so CMO and Product Intelligence entries can never collide and a news-mode result is never
served for a differently-optioned query. The cache is deliberately NOT keyed by tenant: every key is built from template
text + confirmed terms only, never tenant data, and the payload is public search results.

This ceiling counts CMO searches only. Product Intelligence uses the same provider keys; its use is invisible here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Protocol

from market_signals.cache import QueryCache, normalize_query_text
from market_signals.rate_limiter import throttle as shared_throttle
from market_signals.tavily_client import TavilyClient
from market_signals.youtube_client import YoutubeClient

from slim_cmo.config import TrendConfig
from slim_cmo.trends.queries import OutboundQuery, Provider, QueryPlan, validate_egress
from slim_cmo.trends.sources import SourceItem, SourceType, parse_published_date
from slim_cmo.types import TrendSection

logger = logging.getLogger(__name__)

CACHE_SOURCE: Mapping[Provider, str] = {Provider.TAVILY: "cmo_tavily", Provider.YOUTUBE: "cmo_youtube"}
THROTTLE_SOURCE: Mapping[Provider, str] = {Provider.TAVILY: "tavily", Provider.YOUTUBE: "youtube"}
CEILING_REASON = "The daily research limit has been reached."


class SlotStore(Protocol):
    def take_slot(self, provider: str, ceiling: int) -> bool: ...


class QueryOutcome(str, Enum):
    OK = "OK"
    CACHE_HIT = "CACHE_HIT"
    FAILED = "FAILED"
    REFUSED_DAILY_CEILING = "REFUSED_DAILY_CEILING"
    COUNTER_ERROR = "COUNTER_ERROR"  # the slot counter could not be reached: fail closed, no provider call


class SectionStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class RetrievedItem:
    section: TrendSection
    query_id: str
    provider: Provider
    source_type: SourceType
    url: str
    title: str | None
    snippet: str | None
    published_raw: str | None  # Tavily's date string exactly as returned
    published_at: datetime | None  # None = DATE_UNKNOWN; the retrieval date is never substituted
    retrieved_at: datetime
    channel_id: str | None = None
    channel_title: str | None = None
    view_count: int | None = None

    def to_source_item(self) -> SourceItem:
        return SourceItem(
            url=self.url, source_type=self.source_type, retrieved_at=self.retrieved_at, title=self.title,
            published_at=self.published_at, channel_id=self.channel_id, channel_title=self.channel_title,
        )


@dataclass(frozen=True, slots=True)
class QueryResult:
    query_id: str
    section: TrendSection
    provider: Provider
    outcome: QueryOutcome
    reason: str | None
    items: tuple[RetrievedItem, ...]


@dataclass(frozen=True, slots=True)
class SectionResult:
    section: TrendSection
    status: SectionStatus
    reason: str | None
    items: tuple[RetrievedItem, ...]


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    sections: tuple[SectionResult, ...]
    queries: tuple[QueryResult, ...]
    unresearched_terms: tuple[str, ...]
    accounting: Mapping[str, object]

    def section(self, section: TrendSection) -> SectionResult | None:
        return next((s for s in self.sections if s.section is section), None)


class RetrievalService:
    def __init__(
        self,
        *,
        tavily: TavilyClient,
        youtube: YoutubeClient,
        cache: QueryCache,
        slots: SlotStore,
        clock: Callable[[], datetime],
        throttle: Callable[[str], AbstractContextManager[Any]] = shared_throttle,
    ) -> None:
        self._tavily, self._youtube, self._cache, self._slots, self._clock, self._throttle = tavily, youtube, cache, slots, clock, throttle

    # ---------------------------------------------------------------- public
    def run(self, plan: QueryPlan, *, config: TrendConfig, confirmed_terms: Collection[str], cache_scope: str = "") -> RetrievalResult:
        validate_egress(plan.queries, confirmed_terms=confirmed_terms, config=config)  # whole plan, before the first call
        results: list[QueryResult] = []
        ceiling_hit = False
        for query in plan.queries:
            validate_egress([query], confirmed_terms=confirmed_terms, config=config)  # and again at the choke point
            result, ceiling_hit = self._run_one(query, config, ceiling_hit, cache_scope)
            results.append(result)
        return RetrievalResult(
            sections=self._sections(plan, results), queries=tuple(results), unresearched_terms=plan.unresearched_terms,
            accounting=self._accounting(plan, results),
        )

    # ---------------------------------------------------------------- one query
    def _cache_key(self, q: OutboundQuery, scope: str = "") -> str:
        options = "&".join(f"{k}={q.params[k]}" for k in sorted(q.params))
        # A query carrying a seller's niche term is cached PER TENANT (`scope`): otherwise one seller could learn that another researched
        # the same term. Term-free queries (marketplace news, tactics, buzz) are identical for everyone and are shared.
        owner = scope if q.term is not None else ""
        return f"{q.template_id}|{normalize_query_text(q.text)}|{options}|{owner}"

    def _run_one(self, q: OutboundQuery, config: TrendConfig, ceiling_hit: bool, scope: str) -> tuple[QueryResult, bool]:
        now = self._clock()
        source, key = CACHE_SOURCE[q.provider], self._cache_key(q, scope)
        cached = self._cache.get(source, key, now=now)
        if cached is not None:
            return self._ok(q, QueryOutcome.CACHE_HIT, _from_payload(q, cached)), ceiling_hit
        if ceiling_hit:
            return self._fail(q, QueryOutcome.REFUSED_DAILY_CEILING, CEILING_REASON), True
        try:
            granted = self._slots.take_slot(q.provider.value, config.provider_daily_search_ceiling)
        except Exception:  # noqa: BLE001 - fail closed: no counter, no provider call
            logger.exception("provider slot counter unavailable")
            return self._fail(q, QueryOutcome.COUNTER_ERROR, "The research usage counter is unavailable."), ceiling_hit
        if not granted:
            return self._fail(q, QueryOutcome.REFUSED_DAILY_CEILING, CEILING_REASON), True
        try:
            with self._throttle(THROTTLE_SOURCE[q.provider]):
                items = self._call(q, now)
        except Exception as exc:  # noqa: BLE001 - a provider failure degrades this query only (the slot stays counted)
            logger.warning("provider call failed for %s: %s", q.query_id, type(exc).__name__)
            return self._fail(q, QueryOutcome.FAILED, f"{q.provider.value.title()} was unavailable ({type(exc).__name__})."), ceiling_hit
        self._cache.put(source, key, _to_payload(items), ttl_hours=config.provider_cache_ttl_hours, now=now)
        return self._ok(q, QueryOutcome.OK, items), ceiling_hit

    def _call(self, q: OutboundQuery, now: datetime) -> tuple[RetrievedItem, ...]:
        p = q.params
        if q.provider is Provider.TAVILY:
            rows = self._tavily.search(
                q.text, max_results=int(p["max_results"]), topic=str(p["topic"]), days=int(p["days"]), country=str(p["country"]),
            )
            return tuple(
                RetrievedItem(
                    section=q.section, query_id=q.query_id, provider=q.provider, source_type=SourceType.WEB, url=r.url,
                    title=r.title, snippet=r.content or None, published_raw=r.published_date,
                    published_at=parse_published_date(r.published_date), retrieved_at=r.retrieved_at,
                )
                for r in rows
            )
        videos = self._youtube.search_videos(
            q.text, max_results=int(p["max_results"]), region_code=str(p["region_code"]),
            published_after=now - timedelta(days=int(p["published_within_days"])),
        )
        return tuple(
            RetrievedItem(
                section=q.section, query_id=q.query_id, provider=q.provider, source_type=SourceType.VIDEO,
                url=f"https://www.youtube.com/watch?v={v.video_id}", title=v.title or None, snippet=None, published_raw=None,
                # the client falls back to the retrieval instant when YouTube gave no valid date: that is DATE_UNKNOWN
                published_at=None if v.published_at == v.retrieved_at else v.published_at,
                retrieved_at=v.retrieved_at, channel_id=v.channel_id, channel_title=v.channel_title or None, view_count=v.view_count,
            )
            for v in videos
        )

    # ---------------------------------------------------------------- results
    @staticmethod
    def _ok(q: OutboundQuery, outcome: QueryOutcome, items: tuple[RetrievedItem, ...]) -> QueryResult:
        return QueryResult(q.query_id, q.section, q.provider, outcome, None, items)

    @staticmethod
    def _fail(q: OutboundQuery, outcome: QueryOutcome, reason: str) -> QueryResult:
        return QueryResult(q.query_id, q.section, q.provider, outcome, reason, ())

    @staticmethod
    def _sections(plan: QueryPlan, results: list[QueryResult]) -> tuple[SectionResult, ...]:
        out: list[SectionResult] = []
        sections = list(dict.fromkeys(r.section for r in results))
        for section in sections:
            mine = [r for r in results if r.section is section]
            good = [r for r in mine if r.outcome in (QueryOutcome.OK, QueryOutcome.CACHE_HIT)]
            items = tuple(i for r in good for i in r.items)
            if len(good) == len(mine):
                out.append(SectionResult(section, SectionStatus.COMPLETE, None, items))
            else:
                reasons = "; ".join(dict.fromkeys(r.reason for r in mine if r.reason))
                out.append(SectionResult(section, SectionStatus.PARTIAL if good else SectionStatus.UNAVAILABLE, reasons, items))
        for section, reason in plan.unavailable.items():
            out.append(SectionResult(section, SectionStatus.UNAVAILABLE, reason, ()))
        return tuple(out)

    @staticmethod
    def _accounting(plan: QueryPlan, results: list[QueryResult]) -> Mapping[str, object]:
        def count(*outcomes: QueryOutcome, provider: Provider | None = None) -> int:
            return sum(1 for r in results if r.outcome in outcomes and (provider is None or r.provider is provider))

        called = (QueryOutcome.OK, QueryOutcome.FAILED)  # a slot was taken and a provider call attempted
        return {
            "planned": len(plan.queries), "cache_hits": count(QueryOutcome.CACHE_HIT),
            "provider_calls": {p.value: count(*called, provider=p) for p in Provider},
            "failed": count(QueryOutcome.FAILED), "refused_daily_ceiling": count(QueryOutcome.REFUSED_DAILY_CEILING),
            "counter_errors": count(QueryOutcome.COUNTER_ERROR), "skipped_by_budget": len(plan.skipped),
            "budget": dict(plan.budget_usage),
            "note": "Daily accounting counts CMO searches only; Product Intelligence's use of the shared provider keys is not included.",
        }


# ---------------------------------------------------------------------------------------- cache payloads
def _to_payload(items: tuple[RetrievedItem, ...]) -> list[dict[str, Any]]:
    return [
        {
            "url": i.url, "title": i.title, "snippet": i.snippet, "published_raw": i.published_raw,
            "published_at": i.published_at.isoformat() if i.published_at else None, "retrieved_at": i.retrieved_at.isoformat(),
            "channel_id": i.channel_id, "channel_title": i.channel_title, "view_count": i.view_count,
        }
        for i in items
    ]


def _from_payload(q: OutboundQuery, payload: object) -> tuple[RetrievedItem, ...]:
    assert isinstance(payload, list)
    source_type = SourceType.WEB if q.provider is Provider.TAVILY else SourceType.VIDEO
    return tuple(
        RetrievedItem(
            section=q.section, query_id=q.query_id, provider=q.provider, source_type=source_type, url=d["url"], title=d["title"],
            snippet=d["snippet"], published_raw=d["published_raw"],
            published_at=datetime.fromisoformat(d["published_at"]) if d["published_at"] else None,
            retrieved_at=datetime.fromisoformat(d["retrieved_at"]), channel_id=d["channel_id"],
            channel_title=d["channel_title"], view_count=d["view_count"],
        )
        for d in payload
    )
