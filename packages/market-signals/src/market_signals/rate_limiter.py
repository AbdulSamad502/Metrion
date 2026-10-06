"""Process-wide outbound-call rate limiter — PI build plan Context, "Rate-limit/scale
concern": every external API (Tavily, YouTube, Google Places) is account-shared across all
of Metrion's tenants, so concurrent users must not fan out 1:1 to live calls.

`discovery_run.py`'s own `ThreadPoolExecutor` pools only bound concurrency *within* one
discovery run. They do nothing to stop many tenants' concurrently-running discovery or
supplier-lookup calls from together exceeding the shared free-tier quota — if ten tenants
research ten different niches at the same moment, nothing upstream of this module throttles
the resulting burst of concurrent Tavily/YouTube/Places calls. This module is that missing
system-wide throttle: one process-wide semaphore per source, acquired around every *real*
outbound call (never around a cache hit — a cached response costs nothing against the
shared quota and must not wait on the limiter).

A caller that has to wait reports this via `AcquireOutcome.waited` so the run orchestrator
can reflect that honestly (a `pi_research_run` row is created `QUEUED` and only moves to
`RUNNING` once it is actually making progress) rather than silently blocking inside what
looks like a `RUNNING` run.

This is a single-process, in-memory limiter — correct for Metrion's current single-worker
FastAPI deployment (same scope as `sources/cache.py`'s own in-process cache, which carries
the identical limitation in its own docstring). A multi-process/multi-instance deployment
would need a shared limiter (e.g. Redis-backed) instead; that is a real, separate upgrade,
not implemented here, and not silently assumed away — flagging it in this docstring rather
than leaving it undocumented.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

# Conservative, hand-picked caps — small enough that one tenant's run can never alone
# exhaust a free-tier quota, loose enough not to serialize a single run's own queries
# (discovery_run.py already bounds a single run to _MAX_CONCURRENT_QUERIES=5 of its own).
DEFAULT_MAX_CONCURRENT_BY_SOURCE: dict[str, int] = {
    "tavily": 3,
    "youtube": 3,
    "google_places": 3,
}

_lock = threading.Lock()
_semaphores: dict[str, threading.Semaphore] = {
    source: threading.Semaphore(limit) for source, limit in DEFAULT_MAX_CONCURRENT_BY_SOURCE.items()
}


def _semaphore_for(source: str) -> threading.Semaphore:
    with _lock:
        semaphore = _semaphores.get(source)
        if semaphore is None:
            semaphore = threading.Semaphore(DEFAULT_MAX_CONCURRENT_BY_SOURCE.get(source, 3))
            _semaphores[source] = semaphore
        return semaphore


@dataclass(frozen=True, slots=True)
class AcquireOutcome:
    waited: bool  # True when this call had to block for a free slot — a real queue wait,
    # not a cache hit or an immediately-available slot.


@contextmanager
def throttle(source: str) -> Iterator[AcquireOutcome]:
    """Wraps one real outbound call to `source` ("tavily" | "youtube" | "google_places").
    Blocks until a process-wide slot for that source is free, then releases it when the
    wrapped call completes (success or failure) — a plain bounded-concurrency gate, not a
    token-bucket/rate-over-time limiter, which is sufficient for the burst-fan-out problem
    this module exists to solve (module docstring)."""
    semaphore = _semaphore_for(source)
    acquired_immediately = semaphore.acquire(blocking=False)
    waited = not acquired_immediately
    if waited:
        semaphore.acquire(blocking=True)
    try:
        yield AcquireOutcome(waited=waited)
    finally:
        semaphore.release()
