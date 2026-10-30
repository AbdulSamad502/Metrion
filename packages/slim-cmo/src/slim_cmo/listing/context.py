"""What the CEO hands generation for a FULL-LISTING request (docs/specs/slim-cmo-agent.md section 6.18). Plain data, built by the server, never taken from the client."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from slim_cmo.listing.text import norm


@dataclass(frozen=True, slots=True)
class ListingContext:
    workflow: str  # basis.FULL_LISTING - the marker that lets the rules-unavailable basis apply; absent for every other request
    keyword_vocab: tuple[str, ...] = ()  # the M2 candidates a listing may place (the ONLY source for the keywords field and the backend terms)
    do_not_claim: tuple[str, ...] = ()  # buyer-question topics the seller left unknown / unconfirmed

    def prompt_extra(self) -> dict[str, object]:
        out: dict[str, object] = {}
        if self.keyword_vocab:
            out["keywords_allowed"] = list(self.keyword_vocab)
        if self.do_not_claim:
            out["do_not_claim"] = list(self.do_not_claim)
        return out


def untraceable(items: Iterable[str], vocab: Iterable[str]) -> list[int]:
    """Positions of items that are not exactly one of the allowed keywords (compared as normalised words)."""
    allowed = {norm(v) for v in vocab}
    return [i for i, it in enumerate(items) if norm(it) not in allowed]
