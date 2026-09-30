"""STAGE 1 ranking — PI build plan §2/§0d/§0f, Checkpoint 0's resolution.

Ranks the full ~30-candidate discovery list on demand/engagement/diversity signal alone
(`§0f` rule 1) — this is what a seller browses first, before any review-commentary or
supplier work has happened. `shortlist_scoring.py` (Stage 4) is the later, second pass; this
module never reaches into review/supplier data and never re-derives Stage 4's number.

**Checkpoint 0's resolution, restated where it actually bites:** `demand_signal` (would-be
Google Ads keyword-volume band) is dropped from this build. `proxy_score` here composes from
`engagement_signal` (YouTube view/comment counts) and `source_diversity` (count of
independent sources mentioning the candidate) only. `demand_signal`'s absence never
suppresses the score — a candidate with real engagement+diversity signal but no demand data
still gets a fully COMPUTED score (§6.3's "COMPUTED whenever at least one base signal
exists" rule) — `demand_signal` is simply named `UNAVAILABLE` with its reason in
`score_explanation`, never silently omitted.

**No float anywhere in this module.** `proxy_score` is accumulated as a `Fraction` and only
ever rendered to the DB boundary as a fixed 2-decimal numeric string (matching
`product_candidate_repo.insert_candidate`'s own documented contract: "a numeric string per
the no-float rule ... the real implementation converts it to numeric(6,2) ... never a Python
float").

**Hard requirement (§0a):** neither this module's code nor its docstrings describing
user-facing text may contain the words "trending", "bestseller", or "popular" — enforced by
a dedicated unit test in Checkpoint 3, restated here as the acceptance bar for anyone editing
this file. `opportunity_label` is always the fixed `'CANDIDATE_OPPORTUNITY'` string — never a
caller choice, never any other value.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Mapping

OPPORTUNITY_LABEL = "CANDIDATE_OPPORTUNITY"

DEMAND_UNAVAILABLE_REASON = "Google Ads API access pending brand verification"

# Point budget per signal — deliberately small integers so every intermediate value stays an
# exact Fraction, never a float. Engagement is split evenly between view-count and
# comment-count bands so a candidate with only one of the two still gets partial credit
# rather than being penalised for a gap in a single YouTube field.
_MAX_VIEW_POINTS = 3
_MAX_COMMENT_POINTS = 3
_MAX_DIVERSITY_POINTS = 4
_MAX_TOTAL_POINTS = _MAX_VIEW_POINTS + _MAX_COMMENT_POINTS + _MAX_DIVERSITY_POINTS  # 10

_VIEW_BAND_THRESHOLDS = (1_000, 10_000, 100_000)  # -> 0,1,2,3 points
_COMMENT_BAND_THRESHOLDS = (10, 100, 1_000)  # -> 0,1,2,3 points
_DIVERSITY_CAP = 4  # a source_diversity of 4+ independent sources earns the full points


def _band_points(value: int, thresholds: tuple[int, ...], max_points: int) -> int:
    points = 0
    for threshold in thresholds:
        if value >= threshold:
            points += 1
    return min(points, max_points)


@dataclass(frozen=True, slots=True)
class SignalContribution:
    """One row of `score_explanation` (§0d) — a seller or auditor can see exactly which
    signal fired, which didn't, and why, never just a bare number."""

    signal: str
    status: str  # AVAILABLE | UNAVAILABLE
    points: int
    max_points: int
    reason: str


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate_id: Any  # opaque — this module never inspects it, only carries it through
    proxy_score: str | None  # fixed 2-decimal numeric string, or None when UNAVAILABLE
    proxy_state: str  # COMPUTED | UNAVAILABLE
    proxy_basis: dict[str, Any]
    score_explanation: dict[str, Any]
    opportunity_label: str = OPPORTUNITY_LABEL


def _engagement_contribution(engagement_signal: Mapping[str, Any] | None) -> tuple[Fraction, list[SignalContribution]]:
    if not engagement_signal or engagement_signal.get("status") != "AVAILABLE":
        reason = (
            engagement_signal.get("reason")
            if isinstance(engagement_signal, Mapping) and engagement_signal.get("reason")
            else "no YouTube video mentioning this candidate was found"
        )
        return Fraction(0), [
            SignalContribution(
                signal="engagement_signal",
                status="UNAVAILABLE",
                points=0,
                max_points=_MAX_VIEW_POINTS + _MAX_COMMENT_POINTS,
                reason=str(reason),
            )
        ]

    view_count = engagement_signal.get("view_count")
    comment_count = engagement_signal.get("comment_count")
    contributions: list[SignalContribution] = []
    total = Fraction(0)

    if isinstance(view_count, int):
        points = _band_points(view_count, _VIEW_BAND_THRESHOLDS, _MAX_VIEW_POINTS)
        total += Fraction(points)
        contributions.append(
            SignalContribution(
                signal="engagement_signal.view_count",
                status="AVAILABLE",
                points=points,
                max_points=_MAX_VIEW_POINTS,
                reason=f"{view_count} cumulative YouTube views across matched videos",
            )
        )
    else:
        contributions.append(
            SignalContribution(
                signal="engagement_signal.view_count",
                status="UNAVAILABLE",
                points=0,
                max_points=_MAX_VIEW_POINTS,
                reason="no view count reported by YouTube for this candidate",
            )
        )

    if isinstance(comment_count, int):
        points = _band_points(comment_count, _COMMENT_BAND_THRESHOLDS, _MAX_COMMENT_POINTS)
        total += Fraction(points)
        contributions.append(
            SignalContribution(
                signal="engagement_signal.comment_count",
                status="AVAILABLE",
                points=points,
                max_points=_MAX_COMMENT_POINTS,
                reason=f"{comment_count} cumulative YouTube comments across matched videos",
            )
        )
    else:
        contributions.append(
            SignalContribution(
                signal="engagement_signal.comment_count",
                status="UNAVAILABLE",
                points=0,
                max_points=_MAX_COMMENT_POINTS,
                reason="no comment count reported by YouTube for this candidate",
            )
        )

    return total, contributions


def _diversity_contribution(source_diversity: int) -> tuple[Fraction, SignalContribution]:
    if source_diversity <= 0:
        return Fraction(0), SignalContribution(
            signal="source_diversity",
            status="UNAVAILABLE",
            points=0,
            max_points=_MAX_DIVERSITY_POINTS,
            reason="no independent source mentioned this candidate",
        )
    points = min(source_diversity, _DIVERSITY_CAP)
    return Fraction(points), SignalContribution(
        signal="source_diversity",
        status="AVAILABLE",
        points=points,
        max_points=_MAX_DIVERSITY_POINTS,
        reason=f"{source_diversity} independent source(s) mentioned this candidate",
    )


def _demand_contribution() -> SignalContribution:
    # Checkpoint 0's resolution: always UNAVAILABLE this build, never omitted from the
    # explanation and never allowed to suppress the rest of the score (module docstring).
    return SignalContribution(
        signal="demand_signal",
        status="UNAVAILABLE",
        points=0,
        max_points=0,
        reason=DEMAND_UNAVAILABLE_REASON,
    )


def _contribution_to_dict(contribution: SignalContribution) -> dict[str, Any]:
    return {
        "signal": contribution.signal,
        "status": contribution.status,
        "points": contribution.points,
        "max_points": contribution.max_points,
        "reason": contribution.reason,
    }


def rank_candidate(
    candidate_id: Any,
    *,
    engagement_signal: Mapping[str, Any] | None,
    source_diversity: int,
) -> RankedCandidate:
    """Scores one already-synthesized candidate. `engagement_signal` is the
    `product_candidate.engagement_signal` shape `candidate_synthesis.py` produces —
    `{"status": "AVAILABLE", "view_count": int, "comment_count": int, ...}` or
    `{"status": "UNAVAILABLE", "reason": str}`."""
    engagement_points, engagement_contributions = _engagement_contribution(engagement_signal)
    diversity_points, diversity_contribution = _diversity_contribution(source_diversity)
    demand_contribution = _demand_contribution()

    total_points = engagement_points + diversity_points
    any_signal_available = any(
        c.status == "AVAILABLE" for c in (*engagement_contributions, diversity_contribution)
    )

    explanation_signals = [
        _contribution_to_dict(c) for c in (*engagement_contributions, diversity_contribution, demand_contribution)
    ]

    if not any_signal_available:
        return RankedCandidate(
            candidate_id=candidate_id,
            proxy_score=None,
            proxy_state="UNAVAILABLE",
            proxy_basis={
                "max_points": _MAX_TOTAL_POINTS,
                "points": 0,
                "engagement_signal": engagement_signal,
                "source_diversity": source_diversity,
            },
            score_explanation={
                "signals": explanation_signals,
                "summary": "no engagement or source-diversity signal was available for this candidate",
            },
        )

    # Fixed 2-decimal numeric string, never a float — matches product_candidate_repo's
    # documented contract for proxy_score.
    scaled = (total_points * 100) / _MAX_TOTAL_POINTS  # score out of 100, still a Fraction
    whole = scaled.numerator // scaled.denominator
    remainder = scaled - whole
    cents = (remainder * 100).numerator // (remainder * 100).denominator if remainder != 0 else 0
    proxy_score_str = f"{whole}.{cents:02d}"

    return RankedCandidate(
        candidate_id=candidate_id,
        proxy_score=proxy_score_str,
        proxy_state="COMPUTED",
        proxy_basis={
            "max_points": _MAX_TOTAL_POINTS,
            "points": str(total_points),
            "engagement_signal": engagement_signal,
            "source_diversity": source_diversity,
        },
        score_explanation={
            "signals": explanation_signals,
            "summary": (
                f"scored {total_points}/{_MAX_TOTAL_POINTS} available points from engagement and "
                "source-diversity signal; demand signal unavailable this build"
            ),
        },
    )


def rank_candidates(
    candidates: list[Mapping[str, Any]],
) -> list[RankedCandidate]:
    """Bulk entry point — each item is a mapping with at least `id`/`candidate_id`,
    `engagement_signal`, `source_diversity`, matching `product_candidate` row shape before
    scoring is written back onto it."""
    ranked: list[RankedCandidate] = []
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id", candidate.get("id"))
        ranked.append(
            rank_candidate(
                candidate_id,
                engagement_signal=candidate.get("engagement_signal"),
                source_diversity=int(candidate.get("source_diversity", 0)),
            )
        )
    return ranked
