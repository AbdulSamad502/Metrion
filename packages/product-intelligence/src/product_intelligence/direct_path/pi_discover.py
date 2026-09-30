"""pi.discover — the direct-path entry point for a full discovery run. Same shape as CI's
`direct_path/research_run.py`: create the `pi_research_run` row first, fail-closed on either
check != `PASS`, do the work, finish the run, return a structured result.

**Phase 1 scope (PI build plan §"Implementation plan"):** `agent_run_repo` is a `backend/`-owned
table this package must not import from. `_log_agent_run_stub` below is the locally-scoped,
no-op audit hook the plan calls for — Phase 2 replaces it with a real
`agent_run_repo.insert_agent_run` call once CEO Hub wiring is approved; nothing here assumes
that hook does anything today beyond returning a value shaped like it will.

**Concurrency (bug-fix pass, 2026-09-30):** the per-candidate review-insight extraction (up to
`_SHORTLIST_SIZE`) and per-candidate embedding generation (up to `candidate_cap`) loops were
previously sequential — pure I/O, so they now run through a bounded `ThreadPoolExecutor`
(`_MAX_CONCURRENT_CANDIDATE_TASKS` workers). Each candidate's work still degrades
independently on failure (a `YoutubeUnavailable`/extraction exception/`EmbeddingUnavailable`
only marks *that* candidate degraded, same as before) — failures are collected via each
future's own result/exception on the main thread after the pool finishes, never by mutating
shared counters from worker threads.

**Product-mention extraction (precision fix, 2026-09-30):** `product_extraction_client`, when
supplied, is threaded straight through to `discovery_run.run_discovery`, which runs the
per-result product-name extraction calls (one per raw Tavily result + one per raw YouTube
video) through their own bounded `ThreadPoolExecutor`, same concurrency discipline as above —
see `discovery/discovery_run.py`'s own docstring for that pool's detail. `None` (the default)
preserves the exact previous whole-title/Jaccard-overlap synthesis behavior end to end.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from product_intelligence.discovery.discovery_run import DEFAULT_CANDIDATE_CAP, run_discovery
from product_intelligence.discovery.product_extraction import ProductExtractionClient
from product_intelligence.embedding.embed import EmbeddingClient, EmbeddingUnavailable, embed_candidate
from product_intelligence.repositories import (
    niche_brief_repo,
    pi_research_run_repo,
    product_candidate_repo,
)
from product_intelligence.review_insight.submit import submit_candidate_review_insight
from product_intelligence.review_insight.text_extraction import TextInsightExtractor
from product_intelligence.sources.cache import QueryCache
from product_intelligence.sources.tavily_client import TavilyClient
from product_intelligence.sources.youtube_client import YoutubeClient, YoutubeUnavailable

_SHORTLIST_SIZE = 15  # top-N by Stage 1 proxy_score that get review-insight + are
# candidates for later supplier lookup — matches the plan's "shortlist (top ~10-15 by
# Stage 1 score)" instruction.
_MAX_COMMENTS_PER_CANDIDATE = 20
_MAX_CONCURRENT_CANDIDATE_TASKS = 5  # bounded deliberately — see module docstring


def _log_agent_run_stub(
    *,
    tenant_id: UUID,
    trigger_ref: str,
    requested_by: UUID,
    permission_check: str,
    entitlement_check: str,
    status: str,
    error_reason: str | None,
) -> UUID:
    """No-op audit hook — see module docstring. Returns a fresh id so callers get a
    consistently-shaped `agent_run_id` field without this package writing to a table it does
    not own."""
    return uuid4()


@dataclass(frozen=True, slots=True)
class PiRunResult:
    run_id: UUID
    agent_run_id: UUID
    status: str  # FAILED | PARTIAL | COMPLETE
    candidate_ids: tuple[UUID, ...]
    shortlisted_candidate_ids: tuple[UUID, ...]
    partial_reason: str | None
    failed_reason: str | None


def submit_pi_discover(
    tenant_id: UUID,
    niche_brief_id: UUID,
    depth: str,
    *,
    requested_by: UUID,
    permission_check: str,
    entitlement_check: str,
    tavily: TavilyClient,
    youtube: YoutubeClient,
    cache: QueryCache,
    text_extractor: TextInsightExtractor,
    embedding_client: EmbeddingClient,
    product_extraction_client: ProductExtractionClient | None = None,
    candidate_cap: int = DEFAULT_CANDIDATE_CAP,
    parent_run_id: UUID | None = None,
    now: datetime | None = None,
) -> PiRunResult:
    now = now or datetime.now(timezone.utc)

    brief = niche_brief_repo.get_brief(tenant_id, niche_brief_id)
    run_id = pi_research_run_repo.create_run(
        tenant_id,
        niche_brief_id=niche_brief_id,
        depth=depth,
        trigger="DIRECT_UI",
        candidate_cap=candidate_cap,
        status="QUEUED",
    )

    if permission_check != "PASS" or entitlement_check != "PASS" or brief is None or brief.get("status") != "READY":
        reason = (
            "permission or entitlement check did not pass"
            if permission_check != "PASS" or entitlement_check != "PASS"
            else "niche_brief not found or not READY"
        )
        pi_research_run_repo.finish_run(tenant_id, run_id, status="FAILED", finished_at=now)
        agent_run_id = _log_agent_run_stub(
            tenant_id=tenant_id,
            trigger_ref="pi.discover",
            requested_by=requested_by,
            permission_check=permission_check,
            entitlement_check=entitlement_check,
            status="FAILED",
            error_reason=reason,
        )
        return PiRunResult(
            run_id=run_id,
            agent_run_id=agent_run_id,
            status="FAILED",
            candidate_ids=(),
            shortlisted_candidate_ids=(),
            partial_reason=None,
            failed_reason=reason,
        )

    outcome = run_discovery(
        tenant_id,
        run_id=run_id,
        niche_brief=brief,
        tavily=tavily,
        youtube=youtube,
        cache=cache,
        candidate_cap=candidate_cap,
        product_extraction_client=product_extraction_client,
        now=now,
    )

    candidates = product_candidate_repo.list_candidates_for_run(tenant_id, run_id)
    shortlist = sorted(
        (c for c in candidates if c.get("proxy_state") == "COMPUTED" and c.get("proxy_score") is not None),
        key=lambda c: float(c["proxy_score"]),
        reverse=True,
    )[:_SHORTLIST_SIZE]
    shortlist_ids = tuple(UUID(str(c["id"])) for c in shortlist)

    def _run_review_insight_for_candidate(candidate: dict) -> int:
        """Runs one candidate's review-insight extraction, returning its own failure count
        (0, 1, or more — one per degraded YouTube-comment fetch plus one for a failed
        extraction/submit call) so the caller can fold it into `review_insight_failures`
        without any worker thread touching the shared counter directly."""
        candidate_id = UUID(str(candidate["id"]))
        raw = outcome.raw_signals_by_candidate.get(candidate_id)
        if raw is None:
            return 0

        failures = 0
        youtube_comments: list[str] = []
        for video_id in raw.youtube_video_ids:
            try:
                youtube_comments.extend(youtube.top_comments_for(video_id, max_comments=_MAX_COMMENTS_PER_CANDIDATE))
            except YoutubeUnavailable:
                failures += 1

        try:
            submit_candidate_review_insight(
                tenant_id,
                candidate_id=candidate_id,
                youtube_comments=youtube_comments,
                youtube_source_url=raw.primary_youtube_source_url,
                web_snippets=list(raw.web_snippet_texts),
                web_source_url=raw.primary_web_source_url,
                extractor=text_extractor,
                now=now,
            )
        except Exception:  # noqa: BLE001 — a review-insight failure degrades this candidate's
            # commentary, never the whole run (same degrade-not-fail contract as discovery).
            failures += 1

        return failures

    review_insight_failures = 0
    if shortlist:
        with ThreadPoolExecutor(max_workers=min(_MAX_CONCURRENT_CANDIDATE_TASKS, len(shortlist))) as executor:
            futures = [executor.submit(_run_review_insight_for_candidate, candidate) for candidate in shortlist]
            for future in as_completed(futures):
                review_insight_failures += future.result()

    def _run_embedding_for_candidate(candidate: dict) -> bool:
        """Returns `True` if this candidate's embedding generation failed — same
        degrade-not-fail contract as before, just evaluated off the main thread."""
        candidate_id = UUID(str(candidate["id"]))
        try:
            embed_candidate(
                tenant_id,
                candidate_id,
                title_length=candidate.get("title_length"),
                title_structure=candidate.get("title_structure"),
                keyword_themes=candidate.get("keyword_themes"),
                client=embedding_client,
                now=now,
            )
        except EmbeddingUnavailable:
            return True
        return False

    embedding_failures = 0
    if candidates:
        with ThreadPoolExecutor(max_workers=min(_MAX_CONCURRENT_CANDIDATE_TASKS, len(candidates))) as executor:
            futures = [executor.submit(_run_embedding_for_candidate, candidate) for candidate in candidates]
            for future in as_completed(futures):
                if future.result():
                    embedding_failures += 1

    partial_reason = outcome.partial_reason
    if review_insight_failures or embedding_failures:
        extra = []
        if review_insight_failures:
            extra.append(f"{review_insight_failures} candidate(s) had degraded review-commentary extraction")
        if embedding_failures:
            extra.append(f"{embedding_failures} candidate(s) had degraded embedding generation")
        partial_reason = "; ".join([p for p in (partial_reason, *extra) if p])

    final_status = "PARTIAL" if partial_reason else "COMPLETE"
    pi_research_run_repo.finish_run(tenant_id, run_id, status=final_status, finished_at=now)

    agent_run_id = _log_agent_run_stub(
        tenant_id=tenant_id,
        trigger_ref="pi.discover",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status=final_status,
        error_reason=None,
    )

    return PiRunResult(
        run_id=run_id,
        agent_run_id=agent_run_id,
        status=final_status,
        candidate_ids=outcome.candidate_ids,
        shortlisted_candidate_ids=shortlist_ids,
        partial_reason=partial_reason,
        failed_reason=None,
    )
