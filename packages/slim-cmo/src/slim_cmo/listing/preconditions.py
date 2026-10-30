"""What must be true before a full listing may be written (docs/specs/slim-cmo-agent.md section 6.18.2). Pure: no I/O, no model.

Two checks that need no marketplace data: confirmed facts that contradict each other (two CURRENT values for the same single-valued detail, for example a size of 500 ml and a capacity of 1 litre
for one product) and the facts a listing still needs. The latest statement per detail already wins in the profile, so a contradiction here means two different details that both claim to be the
same thing. Nothing is ever resolved silently: the seller is asked which value is right.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from slim_cmo.claims import Attribute, assess
from slim_cmo.listing.audit import _capacities_ml
from slim_cmo.listing.text import words

_SIZE = frozenset({"size", "capacity", "volume"})
_COLOUR = frozenset({"color", "colour"})
_MATERIAL = frozenset({"material"})
_BRAND = frozenset({"brand"})
REQUIRED_FOR_A_LISTING = (("brand", "Brand"), ("size", "Size or capacity"), ("material", "Material"))


def _eligible(attrs: Sequence[Attribute]) -> list[Attribute]:
    return [a for a in attrs if a.value and assess(a).eligible]


def contradictions(attributes: Sequence[Attribute]) -> list[dict[str, object]]:
    """One entry per detail that has two or more different current values: {"detail", "values"}. Empty when the facts agree."""
    elig = _eligible(attributes)
    out: list[dict[str, object]] = []

    def values(names: frozenset[str]) -> list[Attribute]:
        return [a for a in elig if a.name.casefold() in names]

    sizes = values(_SIZE)
    caps: dict[Decimal, str] = {}
    for a in sizes:
        for ml in _capacities_ml(str(a.value)):
            caps.setdefault(ml, str(a.value))
    if len(caps) > 1:
        out.append({"detail": "capacity", "values": sorted(set(caps.values()))})
    for label, names in (("colour", _COLOUR), ("material", _MATERIAL), ("brand", _BRAND)):
        distinct = {tuple(words(str(a.value))) for a in values(names)}
        if len(distinct) > 1:
            out.append({"detail": label, "values": sorted({str(a.value) for a in values(names)})})
    return out


def missing_facts(attributes: Sequence[Attribute]) -> list[str]:
    """The details a listing needs that the seller has not confirmed, by plain name."""
    have = {a.name.casefold() for a in _eligible(attributes)}
    out = []
    for key, label in REQUIRED_FOR_A_LISTING:
        names = _SIZE if key == "size" else frozenset({key})
        if not (have & names):
            out.append(label)
    return out


def topic_supported(topic: str, attributes: Sequence[Attribute]) -> bool:
    """True when every word of `topic` is carried by ONE confirmed, claim-eligible detail (its name and value together), for example "wide opening" by the detail Opening: wide. A topic the
    seller's confirmed facts do not carry is never given to the model to write about (spec 6.18.7, N-15c)."""
    wanted = set(words(topic))
    if not wanted:
        return False
    return any(wanted <= set(words(f"{a.name} {a.value}")) for a in _eligible(attributes))
