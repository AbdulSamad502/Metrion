"""The fixed catalog question vocabulary (spec §6.5, P4).

Only these questions are answerable; there is no free-form "ask about any attribute" in V1.
Aliases are LINGUISTIC synonyms used to recognise the seller's own attribute names ("colour" vs
"color"); they are not catalog facts and never supply a value.

* `image_observable` - whether a passed-gate image observation may answer it. Weight and
  dimensions are never observable from a photo (§6.5, AC12). Category and vertical are marketplace
  taxonomy, not something a photo establishes (Q5).
* `estimate_kind` - the ONLY attributes that may ever be `ESTIMATED`, and in what shape: a numeric
  RANGE (weight, dimensions - never a point value) or a plain-words PATH (category, vertical).
  Colour, material, size and brand are never estimated: inventing them is exactly what C9 forbids.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from slim_cmo.textnorm import skeleton


class CatalogAttribute(str, Enum):
    CATEGORY = "CATEGORY"
    VERTICAL = "VERTICAL"
    COLOR = "COLOR"
    MATERIAL = "MATERIAL"
    SIZE = "SIZE"
    WEIGHT = "WEIGHT"
    DIMENSIONS = "DIMENSIONS"
    BRAND = "BRAND"


class EstimateKind(str, Enum):
    RANGE = "RANGE"
    PATH = "PATH"


@dataclass(frozen=True, slots=True)
class AttributeSpec:
    attribute: CatalogAttribute
    aliases: frozenset[str]
    image_observable: bool
    estimate_kind: EstimateKind | None
    marketplace_specific: bool = False


def normalise_name(name: str) -> str:
    """Case, spacing, separators and Unicode form folded: 'Net_Weight' == 'net weight'."""
    return " ".join(skeleton(name).replace("_", " ").replace("-", " ").split())


def _spec(a: CatalogAttribute, aliases: set[str], *, image: bool, est: EstimateKind | None, mp: bool = False) -> AttributeSpec:
    return AttributeSpec(a, frozenset(normalise_name(x) for x in aliases), image, est, mp)


A = CatalogAttribute
SPECS: dict[CatalogAttribute, AttributeSpec] = {
    A.CATEGORY: _spec(A.CATEGORY, {"category", "product category", "item category"}, image=False, est=EstimateKind.PATH, mp=True),
    A.VERTICAL: _spec(A.VERTICAL, {"vertical", "product vertical"}, image=False, est=EstimateKind.PATH, mp=True),
    A.COLOR: _spec(A.COLOR, {"color", "colour", "colors", "colours", "product color", "product colour"}, image=True, est=None),
    A.MATERIAL: _spec(A.MATERIAL, {"material", "materials", "product material"}, image=True, est=None),
    A.SIZE: _spec(A.SIZE, {"size", "product size", "item size"}, image=True, est=None),
    A.WEIGHT: _spec(A.WEIGHT, {"weight", "net weight", "item weight", "product weight", "approximate weight"}, image=False, est=EstimateKind.RANGE),
    A.DIMENSIONS: _spec(A.DIMENSIONS, {"dimensions", "dimension", "item dimensions", "product dimensions"}, image=False, est=EstimateKind.RANGE),
    A.BRAND: _spec(A.BRAND, {"brand", "brand name"}, image=True, est=None),
}
assert set(SPECS) == set(CatalogAttribute)
