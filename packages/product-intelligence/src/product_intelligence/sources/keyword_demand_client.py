"""The seam between discovery and Google Ads API's `KeywordPlanIdeaService` — same
Protocol + frozen dataclass shape as `tavily_client.py`/`youtube_client.py`.

**Dropped from this build at Checkpoint 0 (2026-09-30 in the PI build plan's own dating).**
`KeywordPlanIdeaService` requires Basic-tier developer-token access, which requires brand
verification (an owned, verifiable domain + Google Cloud project) Metrion doesn't have ready
yet. No spend requirement, so this is not a permanent block — just not ready now. Checkpoint 1
onward proceeds with Tavily + YouTube only (`sources/tavily_client.py`,
`sources/youtube_client.py`); `product_candidate.demand_signal` stays in the schema
(`migrations/versions/20260929_0001_pi_tables.py`) but is `UNAVAILABLE`-populated for every
candidate until this client is wired up. `ranking.py`'s Stage 1 `proxy_score` (Checkpoint 2)
composes from `engagement_signal` + `source_diversity` only for now — `demand_signal` is
named `UNAVAILABLE` in `score_explanation` with reason "Google Ads API access pending brand
verification," never silently omitted.

**Checkpoint 1 scaffolding only, additive-later per Checkpoint 0's resolution.** The Protocol
and result shape are real and complete so the schema field they'd eventually populate has a
concrete contract to point at; `HttpKeywordDemandClient` is a stub raising
`NotImplementedError` and is not called anywhere in this build.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class KeywordDemandUnavailable(Exception):
    """The Google Ads API could not be reached, access was not yet granted, or the call hit
    its own rate limit — never a reason to fabricate a demand figure."""


@dataclass(frozen=True, slots=True)
class KeywordDemandBand:
    """A search-volume RANGE for a keyword/category — Google Ads Keyword Plan Idea Service
    never returns an exact count for accounts below a spend threshold, so this shape is a
    band, not a point value, matching the honest-range discipline the rest of this codebase
    uses for any estimate."""

    keyword: str
    avg_monthly_searches_low: int | None
    avg_monthly_searches_high: int | None
    competition_level: str | None
    retrieved_at: datetime


class KeywordDemandClient(Protocol):
    def demand_for(self, keywords: list[str]) -> list[KeywordDemandBand]: ...


class HttpKeywordDemandClient:
    """The real client, wired up only once Google Ads Basic-tier access is confirmed (see
    this module's docstring). Not constructed anywhere in this build."""

    def __init__(self, *, developer_token: str, customer_id: str, timeout_seconds: float = 10.0) -> None:
        self._developer_token = developer_token
        self._customer_id = customer_id
        self._timeout_seconds = timeout_seconds

    def demand_for(self, keywords: list[str]) -> list[KeywordDemandBand]:
        raise NotImplementedError(
            "HttpKeywordDemandClient.demand_for: Google Ads Keyword Plan Idea Service access "
            "is dropped from this build (PI build plan Checkpoint 0 — pending brand "
            "verification). This client is scaffolded for the future, not called anywhere "
            "in Checkpoint 1 or Checkpoint 2."
        )
