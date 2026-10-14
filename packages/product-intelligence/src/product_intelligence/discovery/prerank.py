"""PRE-RANK — docs/specs/ceo-pi-research-flow.md C4. Picks the seller-facing top 5 from the discovered list BEFORE any supplier lookup.

Uses exactly Stage 4's own proxy-score and review-sentiment components (`shortlist_scoring`, unchanged weights: 40 and 30 points) and leaves the supplier component
out, named `NOT_YET_EVALUATED` in the explanation. Stage 4 (`score_shortlist`) then produces the FINAL order of the chosen five once supplier leads exist, so this
is a defined sequence, not a new scoring rule. Deterministic: the same inputs give the same order (ties by candidate id). A candidate with neither a proxy score
nor commentary has nothing to rank on and is never padded in (fewer than five is a normal, named outcome). `§0a` applies: no "trending"/"bestseller" wording.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any, Mapping, Sequence

from product_intelligence.discovery.shortlist_scoring import (
    _MAX_PROXY_POINTS,
    _MAX_SENTIMENT_POINTS,
    _format_fraction_for_display,
    _proxy_component,
    _sentiment_component,
)

TOP_N = 5
# A discovered "product" whose title is really a deal video, a roundup or a question (live run 2026-10-14: "[BBD Sale 2026] Best Earbuds Deals Under 1000 On Flipkart...") is not
# a product to show the seller; it is used only to fill the five when fewer than five real-looking products exist.
_NOT_A_PRODUCT_TITLE = re.compile(r"\b(?:deals?|sale|offers?|discounts?|best|top\s+\d+|under\s+\d+|reviews?|vs\.?|comparison|unboxing|how to|guide)\b|\?", re.IGNORECASE)
MAX_PRODUCT_TITLE_CHARS = 80


_HASHTAG = re.compile(r"(?:^|\s)#\w+")


def clean_display_title(title: str | None) -> str:
    """A product title as the seller should see it: video hashtags (#shorts #viral ...) are social-media noise, not part of a product name, and are removed."""
    return " ".join(_HASHTAG.sub(" ", title or "").split())


def looks_like_a_product_title(title: str | None) -> bool:
    t = clean_display_title(title)
    return bool(t) and len(t) <= MAX_PRODUCT_TITLE_CHARS and not _NOT_A_PRODUCT_TITLE.search(t)
_MAX_PRERANK_POINTS = _MAX_PROXY_POINTS + _MAX_SENTIMENT_POINTS  # 70


@dataclass(frozen=True, slots=True)
class PreRanked:
    candidate_id: Any
    prerank_score: str  # fixed 2-decimal string out of 100 (points / 70), never a float
    explanation: dict[str, Any]


def _two_decimals(value: Fraction) -> str:
    d = (Decimal(value.numerator) / Decimal(value.denominator)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{d:f}"


def prerank(candidates: Sequence[Mapping[str, Any]], *, top_n: int = TOP_N) -> list[PreRanked]:
    """Each item: `{"candidate_id", "proxy_score", "proxy_state", "review_insights": [...]}` (the same shape `score_shortlist` takes, minus suppliers).
    Returns at most `top_n`, best first."""
    scored: list[tuple[int, int, Fraction, str, PreRanked]] = []
    for entry in candidates:
        proxy_points, proxy_exp = _proxy_component(entry.get("proxy_score"), entry.get("proxy_state"))
        sentiment_points, sentiment_exp = _sentiment_component(entry.get("review_insights") or [])
        if proxy_exp["status"] != "AVAILABLE" and sentiment_exp["status"] != "AVAILABLE":
            continue  # nothing to rank on: never padded in
        total = proxy_points + sentiment_points
        score_fraction = total * 100 / _MAX_PRERANK_POINTS
        explanation = {
            "signals": [
                proxy_exp,
                sentiment_exp,
                {
                    "signal": "supplier_availability",
                    "status": "NOT_YET_EVALUATED",
                    "points": 0,
                    "max_points": 0,
                    "reason": "suppliers are looked up only for the five chosen here; the final order is set afterwards by the full score",
                },
            ],
            "summary": f"pre-rank {_format_fraction_for_display(total)}/{_MAX_PRERANK_POINTS} points from proxy score and viewer/web commentary sentiment",
        }
        cid = entry.get("candidate_id")
        has_commentary = 1 if sentiment_exp["status"] == "AVAILABLE" else 0
        explanation["has_commentary"] = bool(has_commentary)
        title_ok = 1 if looks_like_a_product_title(entry.get("candidate_title")) or entry.get("candidate_title") is None else 0
        explanation["looks_like_a_product"] = bool(title_ok)
        scored.append((title_ok, has_commentary, score_fraction, str(cid), PreRanked(candidate_id=cid, prerank_score=_two_decimals(score_fraction), explanation=explanation)))
    # Products WITH viewer/web commentary come first (a seller-facing pick should carry that evidence), then by score; products without any are used only to fill the five
    # when fewer than five have it, and the case then names that gap. Ties by candidate id: the order is deterministic.
    scored.sort(key=lambda t: (-t[0], -t[1], -t[2], t[3]))
    return [p for _, _, _, _, p in scored[:top_n]]
