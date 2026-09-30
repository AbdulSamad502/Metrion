"""STAGE 4 — PI build plan §0f/§2: the second, later composite score, run only on the
smaller post-Stage-2/3 shortlist (candidates that already have `product_review_insight` and
`supplier_lead` data attached). **Never a copy of Stage 1's `proxy_score`** — it combines
three independently-weighted factors (proxy score, review-sentiment quality, supplier
availability) and is checked by Checkpoint 3's own test that this module's output isn't a
re-export.

`§0a` applies here too: `opportunity_label` stays `'CANDIDATE_OPPORTUNITY'`, and this
module's docstrings/output never use "trending"/"bestseller"/"popular".
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any, Mapping, Sequence

# Point budget — deliberately different weighting from Stage 1's, since Stage 4 has strictly
# more information available (review commentary + supplier leads) than Stage 1 ever does.
_MAX_PROXY_POINTS = 40
_MAX_SENTIMENT_POINTS = 30
_MAX_SUPPLIER_POINTS = 30
_MAX_TOTAL_POINTS = _MAX_PROXY_POINTS + _MAX_SENTIMENT_POINTS + _MAX_SUPPLIER_POINTS  # 100


def _format_fraction_for_display(value: Fraction) -> str:
    """Presentation-only rendering of an already-final `Fraction` score, mirroring
    `cfo_actions._format_fraction_as_decimal_for_narration`'s "format, don't calculate"
    boundary — `Decimal` only, never `float`. Without this, `str(Fraction(60, 7))` leaks
    `"60/7"` into a seller-facing explanation instead of `"8.57"`."""
    decimal_value = Decimal(value.numerator) / Decimal(value.denominator)
    quantized = decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = f"{quantized:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


@dataclass(frozen=True, slots=True)
class FinalScoredCandidate:
    candidate_id: Any
    final_score: str | None  # fixed 2-decimal numeric string, or None when UNAVAILABLE
    final_score_state: str  # COMPUTED | UNAVAILABLE
    final_score_explanation: dict[str, Any]


def _proxy_component(proxy_score: str | None, proxy_state: str | None) -> tuple[Fraction, dict[str, Any]]:
    if proxy_state != "COMPUTED" or proxy_score is None:
        return Fraction(0), {
            "signal": "proxy_score",
            "status": "UNAVAILABLE",
            "points": 0,
            "max_points": _MAX_PROXY_POINTS,
            "reason": "Stage 1 proxy score was UNAVAILABLE for this candidate",
        }
    try:
        stage1_out_of_100 = Decimal(proxy_score)
    except Exception:
        return Fraction(0), {
            "signal": "proxy_score",
            "status": "UNAVAILABLE",
            "points": 0,
            "max_points": _MAX_PROXY_POINTS,
            "reason": "Stage 1 proxy score could not be parsed",
        }
    points = Fraction(int(stage1_out_of_100), 1) * Fraction(_MAX_PROXY_POINTS, 100)
    return points, {
        "signal": "proxy_score",
        "status": "AVAILABLE",
        "points": _format_fraction_for_display(points),
        "max_points": _MAX_PROXY_POINTS,
        "reason": f"Stage 1 proxy score was {proxy_score}/100",
    }


def _sentiment_component(review_insights: Sequence[Mapping[str, Any]]) -> tuple[Fraction, dict[str, Any]]:
    positive_total = 0
    negative_total = 0
    considered_any = False
    for insight in review_insights:
        if insight.get("insight_state") not in ("COMPLETE", "DEGRADED"):
            continue
        considered_any = True
        positive_themes = insight.get("positive_themes") or {}
        complaint_themes = insight.get("complaint_themes") or {}
        if isinstance(positive_themes, Mapping):
            positive_total += sum(int(v) for v in positive_themes.values() if isinstance(v, (int, float)))
        if isinstance(complaint_themes, Mapping):
            negative_total += sum(int(v) for v in complaint_themes.values() if isinstance(v, (int, float)))

    if not considered_any or (positive_total == 0 and negative_total == 0):
        return Fraction(0), {
            "signal": "review_sentiment_quality",
            "status": "UNAVAILABLE",
            "points": 0,
            "max_points": _MAX_SENTIMENT_POINTS,
            "reason": "no viewer/web commentary themes were available to judge sentiment quality",
        }

    # positive:negative ratio, capped so a handful of positive mentions with zero negatives
    # doesn't saturate the score on thin data — ratio expressed as an exact Fraction.
    ratio = Fraction(positive_total, negative_total + 1)
    capped_ratio = min(ratio, Fraction(3))  # 3:1 or better earns full marks
    points = capped_ratio / Fraction(3) * Fraction(_MAX_SENTIMENT_POINTS)
    return points, {
        "signal": "review_sentiment_quality",
        "status": "AVAILABLE",
        "points": _format_fraction_for_display(points),
        "max_points": _MAX_SENTIMENT_POINTS,
        "reason": (
            f"{positive_total} positive vs {negative_total} negative theme mention(s) across "
            "viewer/web commentary"
        ),
    }


def _supplier_component(
    supplier_leads: Sequence[Mapping[str, Any]], *, budget_paise: int | None
) -> tuple[Fraction, dict[str, Any]]:
    if not supplier_leads:
        return Fraction(0), {
            "signal": "supplier_availability",
            "status": "UNAVAILABLE",
            "points": 0,
            "max_points": _MAX_SUPPLIER_POINTS,
            "reason": "no supplier lead was found for this candidate",
        }

    lead_found_points = Fraction(_MAX_SUPPLIER_POINTS, 2)  # half credit: a lead exists at all

    moq_known_leads = [lead for lead in supplier_leads if isinstance(lead.get("contact"), Mapping) and lead["contact"].get("moq") is not None]
    if not moq_known_leads or budget_paise is None:
        return lead_found_points, {
            "signal": "supplier_availability",
            "status": "AVAILABLE",
            "points": _format_fraction_for_display(lead_found_points),
            "max_points": _MAX_SUPPLIER_POINTS,
            "reason": (
                f"{len(supplier_leads)} supplier lead(s) found; MOQ-fits-budget unknown "
                "(MOQ not published, or no budget stated)"
            ),
        }

    fits_budget = any(
        _moq_fits_budget(lead["contact"].get("moq"), budget_paise) for lead in moq_known_leads
    )
    if fits_budget:
        points = Fraction(_MAX_SUPPLIER_POINTS)
        reason = f"{len(supplier_leads)} supplier lead(s) found, at least one with MOQ within stated budget"
    else:
        points = lead_found_points
        reason = f"{len(supplier_leads)} supplier lead(s) found, but no known MOQ fits stated budget"

    return points, {
        "signal": "supplier_availability",
        "status": "AVAILABLE",
        "points": _format_fraction_for_display(points),
        "max_points": _MAX_SUPPLIER_POINTS,
        "reason": reason,
    }


def _moq_fits_budget(moq: Any, budget_paise: int) -> bool:
    if not isinstance(moq, Mapping):
        return False
    unit_price_paise = moq.get("unit_price_paise")
    quantity = moq.get("quantity")
    if not isinstance(unit_price_paise, int) or not isinstance(quantity, int):
        return False
    return unit_price_paise * quantity <= budget_paise


def score_shortlist(
    candidates_with_reviews_and_suppliers: Sequence[Mapping[str, Any]],
) -> list[FinalScoredCandidate]:
    """Each item is `{"candidate_id", "proxy_score", "proxy_state", "review_insights": [...],
    "supplier_leads": [...], "budget_paise": int | None}` — assembled by the caller
    (`direct_path/pi_discover.py` or `pi_report.py`) from the three repos' already-persisted
    rows. Runs only on the smaller shortlist (§0f), never the full Stage 1 list."""
    scored: list[FinalScoredCandidate] = []
    for entry in candidates_with_reviews_and_suppliers:
        proxy_points, proxy_explanation = _proxy_component(entry.get("proxy_score"), entry.get("proxy_state"))
        sentiment_points, sentiment_explanation = _sentiment_component(entry.get("review_insights") or [])
        supplier_points, supplier_explanation = _supplier_component(
            entry.get("supplier_leads") or [], budget_paise=entry.get("budget_paise")
        )

        total_points = proxy_points + sentiment_points + supplier_points
        any_available = any(
            e["status"] == "AVAILABLE" for e in (proxy_explanation, sentiment_explanation, supplier_explanation)
        )

        explanation = {
            "signals": [proxy_explanation, sentiment_explanation, supplier_explanation],
            "summary": (
                f"combined {_format_fraction_for_display(total_points)}/{_MAX_TOTAL_POINTS} points "
                "from proxy score, review sentiment quality and supplier availability"
                if any_available
                else "no Stage 1, review-sentiment or supplier signal was available to combine"
            ),
        }

        if not any_available:
            scored.append(
                FinalScoredCandidate(
                    candidate_id=entry.get("candidate_id"),
                    final_score=None,
                    final_score_state="UNAVAILABLE",
                    final_score_explanation=explanation,
                )
            )
            continue

        scaled = (total_points * 100) / _MAX_TOTAL_POINTS
        whole = scaled.numerator // scaled.denominator
        remainder = scaled - whole
        cents = (remainder * 100).numerator // (remainder * 100).denominator if remainder != 0 else 0
        final_score_str = f"{whole}.{cents:02d}"

        scored.append(
            FinalScoredCandidate(
                candidate_id=entry.get("candidate_id"),
                final_score=final_score_str,
                final_score_state="COMPUTED",
                final_score_explanation=explanation,
            )
        )
    return scored
