"""`compute_competitor_effective_price` — deterministic-engine.md §5.15.2.

The engine entry point CI calls for the delivery / offer / effective-price comparison (competitor-intelligence-agent.md
C44, §6.27.3). It returns `metric_result` rows exactly like `compute_price_band` does — `DERIVED`, non-canonical,
never margin-aware — and CI renders them unchanged, citing the returned `engine_result_ref`. CI contains no
effective-price arithmetic of its own for this surface.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Sequence
from uuid import uuid4

from calc_engine.api.compute_metric import MetricResult
from calc_engine.formulas.effective_price import ObservedOffer, compute_effective_price
from calc_engine.types import RecognitionState, Unavailable

FORMULA_VERSION = "EFFECTIVE_PRICE.v1"


def _row(code: str, value: int | None, basis: str, *, input_refs: tuple[str, ...], exclusions: tuple[dict, ...], computed_at: datetime,
         as_of_date: date | None, reason: str | None = None) -> MetricResult:
    available = value is not None
    return MetricResult(
        id=uuid4(),
        metric_code=code,
        value_paise=value,
        recognition_state=RecognitionState.RECOGNISED if available else RecognitionState.UNAVAILABLE,
        confidence="DERIVED",
        calculation_basis=basis,
        formula_version=FORMULA_VERSION,
        canonical_data_version="non-canonical",
        as_of_date=as_of_date,
        input_refs=input_refs,
        exclusions=exclusions,
        computed_at=computed_at,
        is_available=available,
        unavailable_reason=reason,
    )


def compute_competitor_effective_price(
    *,
    competitor_ref: str,
    source_ref: str,
    listed_paise: int | None,
    visible_discount_paise: int | None,
    delivery_charge_paise: int | None,
    offers: Sequence[ObservedOffer] = (),
    computed_at: datetime,
    as_of_date: date | None = None,
) -> list[MetricResult]:
    scope = f"competitor_ref={competitor_ref}"
    result = compute_effective_price(
        listed_paise=listed_paise, visible_discount_paise=visible_discount_paise, delivery_charge_paise=delivery_charge_paise, offers=offers
    )
    if isinstance(result, Unavailable):
        return [
            _row("EFFECTIVE_PRICE", None, f"EffectivePrice ({scope}) — UNAVAILABLE, see unavailable_reason — deterministic-engine.md §5.15.2",
                 input_refs=(source_ref,), exclusions=(), computed_at=computed_at, as_of_date=as_of_date, reason=result.reason)
        ]

    exclusions = tuple({"kind": e.offer.kind, "reason": e.reason, "condition": e.offer.condition_text} for e in result.excluded_offers)
    note = "a visible discount was observed" if result.discount_observed else "no visible discount was observed"
    rows = [
        _row(
            "EFFECTIVE_PRICE", result.effective.value,
            f"EffectivePrice ({scope}): listed price less the visible discount and unconditional offers; {note}; conditional offers are excluded — deterministic-engine.md §5.15.2",
            input_refs=(source_ref,), exclusions=exclusions, computed_at=computed_at, as_of_date=as_of_date,
        )
    ]
    if result.buyer_total is not None:
        rows.append(
            _row("BUYER_TOTAL", result.buyer_total.value, f"EffectivePrice BUYER_TOTAL ({scope}): effective price plus the observed delivery charge — deterministic-engine.md §5.15.2",
                 input_refs=(source_ref,), exclusions=exclusions, computed_at=computed_at, as_of_date=as_of_date)
        )
    else:
        rows.append(
            _row("BUYER_TOTAL", None, f"EffectivePrice BUYER_TOTAL ({scope}) — UNAVAILABLE — deterministic-engine.md §5.15.2",
                 input_refs=(source_ref,), exclusions=exclusions, computed_at=computed_at, as_of_date=as_of_date, reason="DELIVERY_CHARGE_NOT_OBSERVED")
        )
    return rows
