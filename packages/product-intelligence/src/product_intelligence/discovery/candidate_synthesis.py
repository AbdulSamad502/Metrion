"""Merges raw Tavily/YouTube results into `product_candidate` row shapes — PI build plan §2.

A `product_candidate` is a discovered **opportunity idea** (§0a), not an observed
marketplace listing — there is no single authoritative product name to copy. This module
groups raw search/video results that appear to describe the same idea and derives each
group's `candidate_title`.

**Confirmed, deliberate deviation from the original design (bug-fix pass, 2026-09-30):**
the original approach grouped results by an exact top-3-most-frequent-token signature (which
almost never matched between genuinely different results, so nearly every result ended up
alone in its own group) and then synthesized `candidate_title` by joining the group's most
frequent words in **frequency order** — producing unreadable, near-identical mashups like
"Shoes Sole Test Red Tape Etpu" for essentially every candidate, confirmed against a real
Tavily/YouTube run. Two things changed:

1. Grouping now uses Jaccard token-overlap between two results' significant-token sets (a
   real similarity measure, not an exact-match signature) — see `_tokens_for_similarity`/
   `_jaccard_overlap`. Genuinely-similar results merge; genuinely-different ones don't.
2. `candidate_title` is now a real, lightly-cleaned title copied from the single best
   representative source in the group (see `_select_representative_title`) — **not** a
   word-frequency mashup. This is a confirmed reversal of the original "never a verbatim
   title" caution: that caution fit CI's marketplace-listing-copy concern, but does not fit
   PI's case — these are general web article/video titles, already attributed via
   `source_urls`/`primary_web_source_url`/`primary_youtube_source_url`, not scraped
   marketplace listings being passed off as this seller's own copy. A real title beats an
   over-engineered synthetic one.

**Confirmed, second deviation — two-tier grouping (precision fix, 2026-09-30):** live testing
of the fix above showed most "candidates" were still generic review-roundup article titles
("The 10 Best Running Shoes for Men in 2026"), because a roundup article's *content* actually
names several distinct products that a whole-result grouping pass can never separate. This
module now runs `discovery/product_extraction.py`'s local-Ollama extraction pass over each raw
result first, and groups on **two tiers**:

1. **Extraction-first (primary):** when a raw result's content/title literally names one or
   more specific products, each extracted product name becomes its own candidate-seed —
   grouped by normalized-name equality (`_normalize_product_name`/`_collapsed_key`), not by
   whole-text Jaccard overlap. `candidate_title` for such a group is the extracted product
   name itself, lightly cleaned — not the source's own (often roundup-shaped) title. A single
   roundup article mentioning 5 products contributes to 5 different candidate groups, each
   correctly attributed back to that same `source_url` (the same `TavilySearchResult`/
   `YoutubeVideo` object is appended to every group its content named).
2. **Jaccard-similarity fallback (unchanged from the previous fix):** whenever extraction
   was never attempted (no client supplied — full backward compatibility for existing
   callers), found nothing (a normal, expected outcome — see `product_extraction.py`'s own
   docstring), or the extractor raised `ProductExtractionUnavailable`, that raw result falls
   back to exactly the old whole-title/Jaccard-overlap grouping — **never silently dropped**.
   Such a group's `confidence` is honestly marked `"DERIVED_NO_PRODUCT_EXTRACTED"` (rather than
   plain `"DERIVED"`) whenever extraction was genuinely attempted for at least one of its
   contributing sources and came back empty/unavailable, so a roundup-shaped title that still
   occasionally surfaces is never confused with a real, extracted product identity.

`embedding/`'s near-duplicate grouping (E12, vector-based) is a separate, later refinement of
the same concern; this module's grouping is a cheap first pass at synthesis time so
degenerate 1-result-per-candidate noise doesn't reach `ranking.py` at all.

`demand_signal` is always the fixed Checkpoint-0 `UNAVAILABLE` shape — never omitted, never
computed here. `web_price_signal` (§0g) is a reference-only by-product of Tavily's result
text, extracted with a plain regex, never fed into `estimate_product_feasibility` or any
Brain-1 calculation — this module has no import of, or dependency on, `calc_engine` at all,
which is itself part of the enforcement of that rule.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlparse

from product_intelligence.discovery.product_extraction import (
    ProductExtractionClient,
    ProductExtractionUnavailable,
    extract_product_mentions,
)
from product_intelligence.discovery.ranking import DEMAND_UNAVAILABLE_REASON
from product_intelligence.sources.tavily_client import TavilyImage, TavilySearchResult
from product_intelligence.sources.youtube_client import YoutubeVideo

_STOPWORDS = frozenset(
    {
        "the", "a", "an", "for", "and", "or", "with", "of", "in", "on", "to", "by", "is",
        "are", "your", "you", "this", "that", "from", "at", "&", "best", "top", "review",
        "reviews", "unboxing", "vs", "2024", "2025", "2026", "buy", "price", "india",
    }
)

_PRICE_PATTERN = re.compile(r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    lowered = text.lower()
    tokens = [tok for tok in re.sub(r"[^a-z0-9\s]", " ", lowered).split() if len(tok) > 2]
    return [tok for tok in tokens if tok not in _STOPWORDS]


_SIMILARITY_THRESHOLD = 0.5


def _tokens_for_similarity(text: str) -> frozenset[str]:
    """Significant-token set used only for Jaccard grouping similarity — not a display
    value, only used to decide "these results are probably about the same idea." """
    return frozenset(_tokenize(text))


def _jaccard_overlap(a: frozenset[str], b: frozenset[str]) -> float:
    """Intersection-over-union of two significant-token sets. `0.0` whenever either side is
    empty (an empty set overlaps with nothing, including another empty set — that case is
    filtered out by callers before it ever reaches here)."""
    if not a or not b:
        return 0.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


def _normalize_product_name(name: str) -> str:
    """Case/whitespace-normalized form of an extracted product name, used for group-identity
    equality (module docstring's "extraction-first" tier)."""
    return re.sub(r"\s+", " ", name.strip().lower())


def _collapsed_key(name: str) -> str:
    """Strips ALL non-alphanumeric characters (including spaces) after lowercasing — a
    deliberately conservative stand-in for "light fuzzy match for near-identical spellings"
    (module docstring): it merges "Nike Pegasus 41" with "Nike  Pegasus-41", but it does
    **not** merge "Nike Pegasus 40" with "Nike Pegasus 41" (different model numbers are
    different products) the way a character-similarity-ratio fuzzy match could. Correctness
    over recall — under-merging genuinely-different models is far safer than over-merging
    them into one candidate."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _clean_extracted_name(name: str) -> str:
    """Light cleaning only — trims whitespace/surrounding quotes. No boilerplate-listicle
    stripping (`_clean_title`'s job for whole source titles) since an extracted product name
    is not expected to carry that framing."""
    cleaned = re.sub(r"\s+", " ", name.strip().strip("\"'").strip())
    return cleaned or name.strip()


_TITLE_BOILERPLATE_PATTERNS = (
    re.compile(r"\s*\|\s*[^|]+$"),  # trailing " | SiteName"
    re.compile(r"\s*[-–]\s*(Best|Top)\b.*$", re.IGNORECASE),  # trailing " - Best X in 2026"
    re.compile(r"^\s*(Best|Top)\s+\d+\s+", re.IGNORECASE),  # leading "Best 10 ..."
    re.compile(r"^\s*\d+\s+(Best|Top)\s+", re.IGNORECASE),  # leading "10 Best ..."
)


def _clean_title(title: str) -> str:
    """Lightly cleans a real source title — strips common boilerplate framing (a trailing
    " | SiteName" attribution, "- Best X in 2026" review framing, leading "Best N"/"N Best"
    list-article framing) without trying to be clever about it. A lightly-cleaned real title
    beats an over-engineered synthetic one (module docstring)."""
    cleaned = title.strip()
    for pattern in _TITLE_BOILERPLATE_PATTERNS:
        cleaned = pattern.sub("", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|–")
    return cleaned or title.strip()


def _select_representative_title(group: "_Group") -> str:
    """Picks the group's best representative real title and lightly cleans it —
    **never** a word-frequency mashup (module docstring). For an extraction-derived group
    (module docstring's tier 1), the representative title is the extracted product name
    itself, not any source's own (often roundup-shaped) title. Otherwise prefers the longest
    non-empty Tavily result title (a simple, honest proxy for "most complete, least
    clickbait-truncated," not a claim of semantic quality); falls back to the first YouTube
    video title when the group has no Tavily results at all."""
    if group.extraction_derived and group.product_name_display:
        return _clean_extracted_name(group.product_name_display)
    tavily_titles = [r.title for r in group.tavily_results if r.title and r.title.strip()]
    if tavily_titles:
        return _clean_title(max(tavily_titles, key=len))
    youtube_titles = [v.title for v in group.youtube_videos if v.title and v.title.strip()]
    if youtube_titles:
        return _clean_title(youtube_titles[0])
    return "Untitled candidate opportunity"


def _extract_prices_paise(content: str) -> list[int]:
    prices: list[int] = []
    for match in _PRICE_PATTERN.finditer(content):
        raw = match.group(1).replace(",", "")
        try:
            rupees = float(raw)
        except ValueError:
            continue
        if rupees <= 0:
            continue
        prices.append(int(round(rupees * 100)))
    return prices


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return url


@dataclass(frozen=True, slots=True)
class SynthesizedCandidate:
    candidate_title: str
    title_length: int
    title_structure: dict[str, Any]
    keyword_themes: dict[str, Any]
    observed_category: str | None
    category_confidence: str | None
    image_url: str | None
    image_source_url: str | None
    demand_signal: dict[str, Any]
    engagement_signal: dict[str, Any]
    web_price_signal: dict[str, Any]
    source_diversity: int
    source_urls: list[dict[str, Any]]
    capture_status: str
    confidence: str
    # Ephemeral only — never written to `product_candidate` (see `insert_candidate`'s own
    # parameter list, which has no slot for either). Carried through `discovery_run.py`'s
    # in-memory return only, so `direct_path/pi_discover.py` can immediately hand them to
    # `review_insight/submit.py` within the same call chain, satisfying C7/C9's "raw text
    # never persisted, never leaves the call chain it was fetched for" rule without a second
    # live fetch.
    youtube_video_ids: tuple[str, ...]
    web_snippet_texts: tuple[str, ...]
    primary_youtube_source_url: str | None
    primary_web_source_url: str | None


@dataclass
class _Group:
    titles: list[str] = field(default_factory=list)
    tavily_results: list[TavilySearchResult] = field(default_factory=list)
    youtube_videos: list[YoutubeVideo] = field(default_factory=list)
    token_set: frozenset[str] = field(default_factory=frozenset)
    # Extraction-derived (tier 1) group identity — set only when this group's candidate_title
    # is a real extracted product name, never for a Jaccard-fallback (tier 2) group.
    extraction_derived: bool = False
    product_name_norm: str | None = None
    product_collapsed_key: str | None = None
    product_name_display: str | None = None
    # Set on a tier-2 (fallback) group when extraction was genuinely attempted for at least
    # one of its contributing sources and came back empty (a real, expected negative result) —
    # drives the honest `confidence` distinction in `synthesize_candidates` (module docstring).
    no_product_extracted_attempted: bool = False
    # Set separately from the above when extraction raised `ProductExtractionUnavailable` for
    # at least one contributing source — a TECHNICAL failure (timeout, unreachable model,
    # unparseable response), never conflated with "the model looked and found nothing," per
    # CLAUDE.md's own guidance against narrating a non-result as if it were a real negative
    # result. Confirmed via live testing this distinction matters in practice: a slow local
    # model timing out on every call was previously indistinguishable from it correctly
    # finding zero products every time.
    extraction_technically_failed: bool = False


def _find_matching_group(groups: list[_Group], tokens: frozenset[str]) -> _Group | None:
    """Best-overlap group for `tokens`, or `None` if nothing clears `_SIMILARITY_THRESHOLD`
    — a real similarity measure (module docstring), not an exact-signature lookup."""
    best_group: _Group | None = None
    best_overlap = 0.0
    for group in groups:
        overlap = _jaccard_overlap(group.token_set, tokens)
        if overlap >= _SIMILARITY_THRESHOLD and overlap > best_overlap:
            best_group = group
            best_overlap = overlap
    return best_group


def _find_matching_product_group(groups: list[_Group], product_name: str) -> _Group | None:
    """Tier-1 (extraction-derived) group lookup — normalized-equality or collapsed-key match
    only (module docstring), never Jaccard overlap, and never against a tier-2 group."""
    normalized = _normalize_product_name(product_name)
    collapsed = _collapsed_key(product_name)
    for group in groups:
        if group.product_name_norm == normalized or group.product_collapsed_key == collapsed:
            return group
    return None


def _try_extract(
    text: str, *, category_text: str | None, client: ProductExtractionClient | None
) -> tuple[list[str], str]:
    """Returns `(mentions, state)` where `state` is one of `NOT_ATTEMPTED` | `SUCCESS` |
    `EMPTY` | `FAILED`. `SUCCESS` means at least one product was extracted; `EMPTY` means
    extraction ran but found nothing (a normal, expected outcome —
    `product_extraction.py`'s own docstring); `FAILED` means `ProductExtractionUnavailable`
    was raised. `NOT_ATTEMPTED` means no client was supplied at all — the pre-existing
    calling convention, preserved for full backward compatibility with callers that don't
    pass `product_extraction_client`."""
    if client is None:
        return [], "NOT_ATTEMPTED"
    try:
        mentions = extract_product_mentions(text, category_text=category_text or "", client=client)
    except ProductExtractionUnavailable:
        return [], "FAILED"
    if mentions:
        return mentions, "SUCCESS"
    return [], "EMPTY"


def _fixed_demand_signal() -> dict[str, Any]:
    return {"status": "UNAVAILABLE", "reason": DEMAND_UNAVAILABLE_REASON}


def _build_engagement_signal(videos: list[YoutubeVideo]) -> dict[str, Any]:
    if not videos:
        return {"status": "UNAVAILABLE", "reason": "no matching YouTube video found for this candidate"}
    view_counts = [v.view_count for v in videos if v.view_count is not None]
    comment_counts = [v.comment_count for v in videos if v.comment_count is not None]
    return {
        "status": "AVAILABLE",
        "video_count": len(videos),
        "view_count": sum(view_counts) if view_counts else None,
        "comment_count": sum(comment_counts) if comment_counts else None,
        "source": "youtube",
    }


def _build_web_price_signal(results: list[TavilySearchResult], *, now: datetime) -> dict[str, Any]:
    all_prices: list[int] = []
    most_recent: str | None = None
    for result in results:
        prices = _extract_prices_paise(result.content)
        all_prices.extend(prices)
        if prices and result.published_date:
            if most_recent is None or result.published_date > most_recent:
                most_recent = result.published_date

    if not all_prices:
        return {
            "status": "UNAVAILABLE",
            "reason": "no price mention found in web content about this candidate",
        }

    average_paise = sum(all_prices) // len(all_prices)
    return {
        "status": "AVAILABLE",
        "average_paise": average_paise,
        "range_low_paise": min(all_prices),
        "range_high_paise": max(all_prices),
        "sample_count": len(all_prices),
        "most_recent_mention": most_recent,
        "disclaimer": (
            "Prices mentioned in web content about this candidate — a rough reference only, "
            "not a verified marketplace price. Never used as an input to any margin or "
            "feasibility calculation; compare only against your own stated target price."
        ),
    }


def synthesize_candidates(
    *,
    tavily_results: list[TavilySearchResult],
    tavily_images: list[TavilyImage],
    youtube_videos: list[YoutubeVideo],
    now: datetime,
    tavily_degraded: bool = False,
    youtube_degraded: bool = False,
    product_extraction_client: ProductExtractionClient | None = None,
    category_text: str | None = None,
) -> list[SynthesizedCandidate]:
    """Two-tier grouping (module docstring). `product_extraction_client=None` (the default)
    preserves the exact previous whole-title/Jaccard-overlap behavior for every caller that
    hasn't been updated to pass one — full backward compatibility, not just "close enough."
    When a client is supplied, each raw result/video is extracted first (tier 1); only a
    result that yields no product mentions, or for which extraction was unavailable, falls
    back to the previous Jaccard-overlap grouping (tier 2). `tavily_degraded`/
    `youtube_degraded` name a source that errored/capped out for this run
    (`discovery_run.py`'s degrade-not-fail contract) so a group's `capture_status` honestly
    reflects a partial run rather than silently reading as complete."""
    product_groups: list[_Group] = []
    fallback_groups: list[_Group] = []

    for result in tavily_results:
        combined_text = f"{result.title}\n{result.content}".strip()
        mentions, state = _try_extract(combined_text, category_text=category_text, client=product_extraction_client)
        if state == "SUCCESS":
            for product_name in mentions:
                if not product_name.strip():
                    continue
                group = _find_matching_product_group(product_groups, product_name)
                if group is None:
                    group = _Group(
                        extraction_derived=True,
                        product_name_norm=_normalize_product_name(product_name),
                        product_collapsed_key=_collapsed_key(product_name),
                        product_name_display=product_name,
                    )
                    product_groups.append(group)
                group.titles.append(product_name)
                group.tavily_results.append(result)
                group.token_set = group.token_set | _tokens_for_similarity(product_name)
            continue

        tokens = _tokens_for_similarity(f"{result.title} {result.content}")
        if not tokens:
            continue
        group = _find_matching_group(fallback_groups, tokens)
        if group is None:
            group = _Group()
            fallback_groups.append(group)
        group.titles.append(result.title)
        group.tavily_results.append(result)
        group.token_set = group.token_set | tokens
        if state in ("EMPTY", "FAILED"):
            group.no_product_extracted_attempted = True
        if state == "FAILED":
            group.extraction_technically_failed = True

    for video in youtube_videos:
        combined_text = f"{video.title} — {video.channel_title}".strip(" —")
        mentions, state = _try_extract(combined_text, category_text=category_text, client=product_extraction_client)
        if state == "SUCCESS":
            for product_name in mentions:
                if not product_name.strip():
                    continue
                group = _find_matching_product_group(product_groups, product_name)
                if group is None:
                    group = _Group(
                        extraction_derived=True,
                        product_name_norm=_normalize_product_name(product_name),
                        product_collapsed_key=_collapsed_key(product_name),
                        product_name_display=product_name,
                    )
                    product_groups.append(group)
                group.titles.append(product_name)
                group.youtube_videos.append(video)
                group.token_set = group.token_set | _tokens_for_similarity(product_name)
            continue

        tokens = _tokens_for_similarity(video.title)
        if not tokens:
            continue
        group = _find_matching_group(fallback_groups, tokens)
        if group is None:
            group = _Group()
            fallback_groups.append(group)
        group.titles.append(video.title)
        group.youtube_videos.append(video)
        group.token_set = group.token_set | tokens
        if state in ("EMPTY", "FAILED"):
            group.no_product_extracted_attempted = True
        if state == "FAILED":
            group.extraction_technically_failed = True

    groups: list[_Group] = product_groups + fallback_groups

    image_by_group_id: dict[int, TavilyImage] = {}
    for image in tavily_images:
        tokens = _tokens_for_similarity(image.description or "")
        if not tokens:
            continue
        group = _find_matching_group(fallback_groups, tokens)
        if group is not None and id(group) not in image_by_group_id:
            image_by_group_id[id(group)] = image

    candidates: list[SynthesizedCandidate] = []
    for group in groups:
        candidate_title = _select_representative_title(group)
        tokens = _tokenize(" ".join(group.titles))
        keyword_counts = Counter(tokens)
        keyword_themes = {"top_keywords": [tok for tok, _ in keyword_counts.most_common(8)]}
        title_structure = {
            "word_count": len(candidate_title.split()),
            "source_title_count": len(group.titles),
        }

        source_urls: list[dict[str, Any]] = []
        domains: set[str] = set()
        for result in group.tavily_results:
            source_urls.append({"url": result.url, "fetched_at": result.retrieved_at.isoformat(), "source": "tavily"})
            domains.add(_domain(result.url))
        for video in group.youtube_videos:
            video_url = f"https://www.youtube.com/watch?v={video.video_id}"
            source_urls.append({"url": video_url, "fetched_at": video.retrieved_at.isoformat(), "source": "youtube"})
            domains.add("youtube.com")

        image = image_by_group_id.get(id(group))
        if image is None and group.tavily_results:
            # first result's own image, if any Tavily image at all exists in this run and no
            # group-specific match was found — reference-image-from-source, still labeled.
            image = next((img for img in tavily_images), None)

        if tavily_degraded and youtube_degraded:
            capture_status = "UNAVAILABLE"
        elif tavily_degraded or youtube_degraded:
            capture_status = "PARTIAL"
        else:
            capture_status = "OK"

        if candidate_title == "Untitled candidate opportunity":
            confidence = "UNAVAILABLE"
        elif not group.extraction_derived and group.extraction_technically_failed:
            # Extraction raised ProductExtractionUnavailable (timeout/unreachable/unparseable)
            # for at least one contributing source — a TECHNICAL failure, never presented as
            # if the model had looked and confirmed no product exists (module docstring; the
            # separate `_Group.extraction_technically_failed` field this branches on exists
            # specifically so this case is never silently folded into the genuine-negative-
            # result branch below).
            confidence = "DERIVED_EXTRACTION_UNAVAILABLE"
        elif not group.extraction_derived and group.no_product_extracted_attempted:
            # Extraction was genuinely attempted for at least one contributing source and ran
            # to completion with no failures, returning no product — this candidate's title is
            # still a real, derived title, but honestly flagged as *not* a confirmed extracted
            # product identity (module docstring's tier-2 confidence distinction).
            confidence = "DERIVED_NO_PRODUCT_EXTRACTED"
        else:
            confidence = "DERIVED"

        candidates.append(
            SynthesizedCandidate(
                candidate_title=candidate_title,
                title_length=len(candidate_title),
                title_structure=title_structure,
                keyword_themes=keyword_themes,
                observed_category=None,
                category_confidence=None,
                image_url=image.url if image else None,
                image_source_url=image.source_url if image else None,
                demand_signal=_fixed_demand_signal(),
                engagement_signal=_build_engagement_signal(group.youtube_videos),
                web_price_signal=_build_web_price_signal(group.tavily_results, now=now),
                source_diversity=len(domains),
                source_urls=source_urls,
                capture_status=capture_status,
                confidence=confidence,
                youtube_video_ids=tuple(v.video_id for v in group.youtube_videos),
                web_snippet_texts=tuple(r.content for r in group.tavily_results if r.content),
                primary_youtube_source_url=(
                    f"https://www.youtube.com/watch?v={group.youtube_videos[0].video_id}"
                    if group.youtube_videos
                    else None
                ),
                primary_web_source_url=group.tavily_results[0].url if group.tavily_results else None,
            )
        )

    return candidates


def dedupe_by_normalized_title(candidates: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """A second, cheap dedup pass over already-synthesized rows (e.g. across multiple query
    terms in the same run) — normalized `candidate_title` equality only. Vector-based
    near-duplicate grouping across genuinely different titles is `embedding/`'s job (E12),
    not this function's."""
    seen: set[str] = set()
    deduped: list[Mapping[str, Any]] = []
    for candidate in candidates:
        title = str(candidate.get("candidate_title", ""))
        normalized = re.sub(r"\s+", " ", title.strip().lower())
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(candidate)
    return deduped
