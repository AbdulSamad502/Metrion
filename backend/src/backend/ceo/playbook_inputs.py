"""The structured, code-validated inputs of the two decision playbooks — spec §6.33.

These arrive from a run-form (a deterministic control), never from the classifier or any model. They are strict (`extra=forbid`), money is integer paise,
and every cost is one of three EXPLICIT states: an amount, "none (0), I confirm", or "unknown". A cost with no state is a validation error, never a zero.
Nothing here computes a figure; it only checks shape and bounds and passes the seller's own values on.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

MAX_TEXT = 120
MAX_QUANTITY = 10_000_000
MAX_PAISE = 100_000_000_000  # a sanity bound on one money input (₹1,000,000,000), far above any real price or cost


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Amount(_Strict):
    state: Literal["AMOUNT"]
    amount_paise: int = Field(ge=0, le=MAX_PAISE)


class NoneConfirmed(_Strict):
    state: Literal["NONE_CONFIRMED"]


class Unknown(_Strict):
    state: Literal["UNKNOWN"]
    reason: str | None = Field(default=None, max_length=MAX_TEXT)


CostValue = Annotated[Amount | NoneConfirmed | Unknown, Field(discriminator="state")]


def cost_to_slot(cost: Amount | NoneConfirmed | Unknown, name: str) -> dict[str, Any]:
    """The `<name>_paise` / `<name>_unavailable_reason` pair the CFO pricing route takes: an amount (0 only when confirmed), or null = unknown."""
    if isinstance(cost, Amount):
        return {f"{name}_paise": cost.amount_paise, f"{name}_unavailable_reason": None}
    if isinstance(cost, NoneConfirmed):
        return {f"{name}_paise": 0, f"{name}_unavailable_reason": None}
    return {f"{name}_paise": None, f"{name}_unavailable_reason": cost.reason}


class PriceImpactInputs(_Strict):
    """COMPETITOR_PRICE_IMPACT: one competitor, one SKU, the seller's current price, 1..N candidate prices and every per-unit cost the margin needs."""

    competitor_url_id: UUID
    sku: str = Field(min_length=1, max_length=MAX_TEXT)
    marketplace: str = Field(min_length=1, max_length=MAX_TEXT)
    category: str = Field(min_length=1, max_length=MAX_TEXT)
    fee_type: str = Field(min_length=1, max_length=MAX_TEXT)
    basis: Literal["INCLUSIVE", "EXCLUSIVE"]
    gst_rate_pct: str | None = Field(default=None, max_length=12)
    current_price_paise: int = Field(gt=0, le=MAX_PAISE)
    candidate_prices_paise: list[Annotated[int, Field(gt=0, le=MAX_PAISE)]] = Field(min_length=1)
    shipping: CostValue
    advertising: CostValue
    return_rto: CostValue
    other: CostValue
    stance: Literal["MATCH_LOWEST", "BEAT_LOWEST_BY_PCT", "BEAT_LOWEST_BY_PAISE", "MATCH_AVERAGE", "MATCH_HIGHEST"] | None = None
    stance_param_pct: str | None = Field(default=None, max_length=12)
    stance_param_paise: int | None = Field(default=None, ge=0, le=MAX_PAISE)

    @field_validator("gst_rate_pct", "stance_param_pct")
    @classmethod
    def _decimal_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            d = Decimal(v.strip())
        except InvalidOperation:
            raise ValueError("not a decimal number") from None
        if not d.is_finite() or d < 0 or d > 1000:
            raise ValueError("out of range")
        return v.strip()

    @model_validator(mode="after")
    def _stance_parameter_matches(self) -> "PriceImpactInputs":
        if self.stance == "BEAT_LOWEST_BY_PCT" and self.stance_param_pct is None:
            raise ValueError("this stance needs a percentage")
        if self.stance == "BEAT_LOWEST_BY_PAISE" and self.stance_param_paise is None:
            raise ValueError("this stance needs an amount")
        return self


class NewProductInputs(_Strict):
    """NEW_PRODUCT_DECISION: the product (a SKU), how many units are being considered and the sales-history window. Quotes and the budget are STORED inputs."""

    sku: str = Field(min_length=1, max_length=MAX_TEXT)
    quantity: int = Field(gt=0, le=MAX_QUANTITY)
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def _ordered(self) -> "NewProductInputs":
        if self.period_end < self.period_start:
            raise ValueError("the period ends before it starts")
        return self


INPUT_MODELS: dict[str, type[_Strict]] = {"COMPETITOR_PRICE_IMPACT": PriceImpactInputs, "NEW_PRODUCT_DECISION": NewProductInputs}


class InvalidInputs(ValueError):
    """The submitted inputs do not satisfy the playbook's contract. `problems` are plain-language, never echo the raw value."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def validate_inputs(playbook: str, raw: Any, *, max_candidate_prices: int | None = None, today: date | None = None) -> PriceImpactInputs | NewProductInputs:
    """Validates one playbook's inputs. `max_candidate_prices` is the configured bound (None = not configured: the caller refuses first)."""
    model = INPUT_MODELS.get(playbook)
    if model is None:
        raise InvalidInputs(["this playbook takes no form inputs"])
    try:
        parsed: PriceImpactInputs | NewProductInputs = model.model_validate(raw)  # type: ignore[assignment]
    except ValidationError as exc:
        raise InvalidInputs([f"{'.'.join(str(p) for p in e['loc']) or 'inputs'}: {e['msg']}" for e in exc.errors()]) from None
    if isinstance(parsed, PriceImpactInputs):
        if max_candidate_prices is not None and len(parsed.candidate_prices_paise) > max_candidate_prices:
            raise InvalidInputs([f"at most {max_candidate_prices} candidate prices can be compared in one run"])
        if len(set(parsed.candidate_prices_paise)) != len(parsed.candidate_prices_paise):
            raise InvalidInputs(["candidate prices must all be different"])
    if isinstance(parsed, NewProductInputs) and today is not None and parsed.period_end > today:
        raise InvalidInputs(["the sales-history period cannot end in the future"])
    return parsed
