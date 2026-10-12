"""Structural worst-case durations of PI's long actions, derived from the SAME constants and client timeouts the code uses.

These are upper BOUNDS computed from code, never measurements. They exist so a configured reservation TTL / staleness threshold can be
validated against a floor that cannot silently drift from the implementation (approval prerequisites R5/R6; the measured durations
on the target host are a separate, still-open requirement). Excluded and therefore NOT covered: provider-side rate-limit waits
(`throttle(...)`) and any provider that ignores its client timeout.

`candidate_cap` is user input on `POST /pi/discover` and the route accepts ANY integer today (no lower or upper bound). A cap below 1 does not bound the work at all
(`_select_candidates_with_cap` slices with it, so a negative cap keeps most candidates), and a very large cap is only bounded by what the providers return. The bound is
therefore a function of the cap and is REFUSED (ValueError) for a cap below 1: it is a maximum only for 1 <= candidate_cap and only under the assumptions listed
above (client timeouts honoured, fixed query/result counts). It is NOT claimed to be a maximum for arbitrary caps. A public bound is a pending, separate decision.
"""

from __future__ import annotations

import dataclasses
import inspect
import math
from collections.abc import Callable
from typing import Any

from product_intelligence.direct_path import pi_discover as _pi_discover
from product_intelligence.direct_path import pi_supplier_lookup as _pi_supplier_lookup
from product_intelligence.discovery import discovery_run as _discovery_run
from product_intelligence.discovery.discovery_run import DEFAULT_CANDIDATE_CAP
from product_intelligence.discovery.product_extraction import OllamaProductExtractionClient
from product_intelligence.embedding.embed import OllamaEmbeddingClient
from product_intelligence.review_insight.text_extraction import OllamaTextInsightExtractor
from product_intelligence.sources.tavily_client import HttpTavilyClient
from product_intelligence.sources.youtube_client import HttpYoutubeClient
from product_intelligence.supplier.google_places_client import HttpPlacesClient


def _default_timeout(cls: type[Any]) -> float:
    """The class's own default `timeout_seconds` (dataclass field or __init__ parameter). Raises if it cannot be established, so a
    refactor that removes it fails the bound loudly instead of being guessed."""
    if dataclasses.is_dataclass(cls):
        for f in dataclasses.fields(cls):
            if f.name == "timeout_seconds" and f.default is not dataclasses.MISSING:
                return float(f.default)
    param = inspect.signature(cls.__init__).parameters.get("timeout_seconds")
    if param is not None and param.default is not inspect.Parameter.empty:
        return float(param.default)
    raise RuntimeError(f"cannot establish the default timeout of {cls.__name__}")


def _waves(items: int, workers: int) -> int:
    return math.ceil(items / max(1, min(workers, items))) if items > 0 else 0


def discover_worst_case_seconds(candidate_cap: int = DEFAULT_CANDIDATE_CAP) -> int:
    """Upper bound for one `pi.discover` run: search waves + product extraction + review insight + embeddings (see module docstring). Raises for a cap < 1."""
    if candidate_cap < 1:
        raise ValueError(f"candidate_cap={candidate_cap} does not bound the work; no worst-case duration can be established")
    queries = len(_discovery_run._queries_for_niche("x"))
    workers = _discovery_run._MAX_CONCURRENT_QUERIES
    tavily, youtube = _default_timeout(HttpTavilyClient), _default_timeout(HttpYoutubeClient)
    search = _waves(queries, workers) * tavily + _waves(queries, workers) * youtube
    texts = queries * _discovery_run._MAX_RESULTS_PER_TAVILY_QUERY + queries * _discovery_run._MAX_RESULTS_PER_YOUTUBE_QUERY
    extraction = _waves(texts, workers) * _default_timeout(OllamaProductExtractionClient)
    shortlist = min(_pi_discover._SHORTLIST_SIZE, candidate_cap)
    per_candidate_review = _default_timeout(OllamaTextInsightExtractor) + _discovery_run._MAX_RESULTS_PER_YOUTUBE_QUERY * youtube
    review = _waves(shortlist, _pi_discover._MAX_CONCURRENT_CANDIDATE_TASKS) * per_candidate_review
    embeddings = _waves(candidate_cap, _pi_discover._MAX_CONCURRENT_CANDIDATE_TASKS) * _default_timeout(OllamaEmbeddingClient)
    return math.ceil(search + extraction + review + embeddings)


def supplier_lookup_worst_case_seconds(candidates: int = 5) -> int:
    """Upper bound for one `pi.supplier_lookup` call: per candidate two Places requests (search + details) and one Tavily search; candidates
    run in parallel waves (excludes `throttle` waits)."""
    per_candidate = 2 * _default_timeout(HttpPlacesClient) + _default_timeout(HttpTavilyClient)
    return math.ceil(_waves(candidates, _pi_supplier_lookup._MAX_CONCURRENT_CANDIDATE_LOOKUPS) * per_candidate)


WORST_CASE: dict[str, Callable[[], int]] = {
    "pi.discover": discover_worst_case_seconds,
    "pi.supplier_lookup": supplier_lookup_worst_case_seconds,
}
