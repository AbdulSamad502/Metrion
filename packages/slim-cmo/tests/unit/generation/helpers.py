"""Shared builders for the P3 generation tests. Every value is a TEST value."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from slim_cmo.claims import Attribute
from slim_cmo.constraints import ResolvedConstraint, resolve_constraint
from slim_cmo.generation.facts import FactContext, FactInput, build_fact_context
from slim_cmo.types import AttributeBasis as B
from slim_cmo.types import Marketplace, OutputType, SellerFactType as F, TrustState as T

from ..factories import NOW, constraint

MODEL = "test-model"
ANCHOR = "AquaKeep Steel Bottle 750 ml"


def resolved(mp: Marketplace = Marketplace.AMAZON, out: OutputType = OutputType.TITLE_SET, **limits: Any) -> ResolvedConstraint:
    r = resolve_constraint([constraint(mp, **limits)], marketplace=mp, category=None, output_type=out, now=NOW, max_age_days=30)
    assert isinstance(r, ResolvedConstraint), r
    return r


def at(day: int) -> datetime:
    return datetime(2026, 9, day, tzinfo=UTC)


BASE_FACTS = [
    FactInput(F.BRAND, "AquaKeep", fact_id="f-brand"),
    FactInput(F.ATTRIBUTE, "stainless steel", "material", fact_id="f-material"),
    FactInput(F.ATTRIBUTE, "750 ml", "capacity", fact_id="f-capacity"),
]

ESTIMATED_WEIGHT = Attribute("weight", "350 g", B.ESTIMATED)
HINT_COLOR = Attribute("color", "matte blue", B.IMAGE_OBSERVED, T.UNVERIFIED_HINT)


def ctx(extra: list[FactInput] | None = None, *, with_ineligible: bool = True) -> FactContext:
    image = [ESTIMATED_WEIGHT, HINT_COLOR] if with_ineligible else []
    return build_fact_context([*BASE_FACTS, *(extra or [])], image)


def j(**kw: Any) -> str:
    return json.dumps(kw)


GOOD_TITLES = ["AquaKeep Steel Bottle 750 ml", "AquaKeep Insulated Flask 750 ml", "AquaKeep Stainless Water Bottle"]

GOOD_PACK = j(
    description="A 750 ml stainless steel bottle from AquaKeep for everyday use.",
    bullets=["Stainless steel build", "750 ml capacity", "Easy to carry"],
    keywords=["steel bottle", "water bottle", "750 ml"],
)
