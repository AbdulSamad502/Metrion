"""Per-niche/keyword TTL cache — PI build plan §2/Context "Rate-limit/scale concern".

**Deliberately keyed by normalized query text alone, NOT by tenant/seller** — this is the one
place PI's convention diverges from CI's `discovery/search_cache.py` (which is tenant-scoped,
`(tenant_id, query_text)`, backed by Postgres tables). CI's cache exists to avoid re-fetching
a URL a *specific tenant* already researched; PI's exists to stop every tenant's concurrent
niche-discovery runs from fanning out 1:1 to Tavily/YouTube's shared, account-wide free-tier
quota (see the PI build plan's Context). Two different tenants asking about "wireless
earbuds" this hour should hit the same cache entry, not each burn their own quota — sharing
the cache *is* the fix, not a bug to guard against.

**Real implementation this checkpoint** (unlike `sources/tavily_client.py`/
`youtube_client.py`'s concrete stubs) — pure in-process logic, no external dependency, no
network, no database, so it is fully unit-testable without a live Postgres or Redis. A
Redis-backed implementation is a legitimate later swap (same `QueryCache` Protocol) if a
single process's memory turns out to be the wrong scope once this runs behind multiple
workers — not needed for Checkpoint 1 to be real and correct.

No clock is read internally, mirroring the rest of this codebase's determinism convention
(`calc_engine.api.compute_metric`'s `computed_at` pattern): every call takes `now` explicitly.

**Thread-safety (bug-fix pass, 2026-09-30):** `discovery_run.py`'s Tavily/YouTube queries now
run through a bounded `ThreadPoolExecutor` (Fix 3, concurrency), so multiple threads can call
`get`/`put` on the same `InProcessQueryCache` instance concurrently. `_store` is a plain
`dict`, not safe for concurrent read+write without a lock — `InProcessQueryCache` now guards
every access with a single `threading.Lock` so a cache read/write from one thread can never
observe or corrupt another thread's in-flight mutation.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


def normalize_query_text(query_text: str) -> str:
    """Case-folds and collapses whitespace so `"Wireless Earbuds"`, `"wireless   earbuds"`
    and `" wireless earbuds "` all land on the same cache entry — the whole point of a
    per-keyword (not per-request-string) cache."""
    return re.sub(r"\s+", " ", query_text.strip().lower())


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """One cached source response. `payload` is whatever JSON-serializable shape the calling
    source client produces (e.g. a list of `TavilySearchResult`/`YoutubeVideo` dicts) —
    `cache.py` itself is source-agnostic and never inspects `payload`'s contents."""

    payload: object
    cached_at: datetime
    expires_at: datetime


class QueryCache(Protocol):
    def get(self, source: str, query_text: str, *, now: datetime) -> object | None:
        """`None` means "no live cache entry" (miss, or expired past its TTL) — the caller
        must call the real source client and then `put()` the fresh result. Never returns a
        falsy-but-present payload to mean "cached empty" ambiguously with a miss: a cached
        empty list IS a valid hit and is returned as such, distinguished from `None` by the
        sentinel, same convention as CI's `SearchResultCache`."""
        ...

    def put(self, source: str, query_text: str, payload: object, *, ttl_hours: int, now: datetime) -> None: ...


class InProcessQueryCache:
    """The real `QueryCache` for Checkpoint 1 — a single process's in-memory store, keyed by
    `(source, normalize_query_text(query_text))`. Never keyed by `tenant_id` (see this
    module's docstring). Pure logic, no I/O, so it doubles as its own test fixture — unlike
    CI's Postgres-backed cache, no separate fake implementation is needed here."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, source: str, query_text: str, *, now: datetime) -> object | None:
        key = (source, normalize_query_text(query_text))
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if now >= entry.expires_at:
                del self._store[key]
                return None
            return entry.payload

    def put(self, source: str, query_text: str, payload: object, *, ttl_hours: int, now: datetime) -> None:
        key = (source, normalize_query_text(query_text))
        with self._lock:
            for stale in [k for k, e in self._store.items() if now >= e.expires_at]:  # sweep: an expired entry nobody re-reads must not live forever
                del self._store[stale]
            self._store[key] = CacheEntry(
                payload=payload,
                cached_at=now,
                expires_at=now + timedelta(hours=ttl_hours),
            )

    def evict(self, source: str, query_text: str) -> None:
        with self._lock:
            self._store.pop((source, normalize_query_text(query_text)), None)
