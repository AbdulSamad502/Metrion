"""Turns a fetched page into observed facts. This is the one piece of the capture pipeline
this pass does NOT implement for real — see the module docstring on `UnimplementedParser`
below for why, and treat that as a flag, not an oversight.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from competitor_intelligence.capture.fetcher import RawPage
from competitor_intelligence.types import Availability, Confidence, Marketplace, Paise


@dataclass(frozen=True, slots=True)
class ParsedListing:
    """Observed facts extracted from a page — never raw title/description/bullet text
    (C16). Every field is optional except the ones the spec marks not-null on
    `competitor_snapshot`; a parser that cannot read a field returns None for it rather than
    guessing, the same "never fabricate" rule that governs capture_status (2B.1)."""

    seller_name: str | None
    observed_category: str | None
    category_confidence: Confidence | None
    listed_price_paise: Paise | None
    mrp_paise: Paise | None
    visible_discount_paise: Paise | None
    rating: Decimal | None
    rating_count: int | None
    availability: Availability | None
    variant_key: str | None


@dataclass(frozen=True, slots=True)
class ParseError:
    reason: str


class Parser(Protocol):
    def parse(self, page: RawPage, marketplace: Marketplace) -> ParsedListing | ParseError: ...


class UnimplementedParser:
    """Deliberately not a real parser. Extracting `ParsedListing` fields from actual
    amazon.in/flipkart.com/meesho.com HTML requires DOM selectors written against real,
    current page markup — the spec (§5, A1-A5) states the fields it wants but not how to
    read them off a live page, and per this session's own verification constraint we are not
    making live requests to those domains right now. Writing selectors blind would be
    inventing marketplace scraping rules the project's hard rule forbids ("no invented
    marketplace rules... thresholds, or assumptions").

    This class exists so the capture pipeline (service.py) has a concrete `Parser` to wire at
    the composition root today, with an honest, loud failure instead of silently fabricated
    field values. Building real per-marketplace parsers is follow-on work that needs someone
    to inspect actual page markup — flag it back to the user rather than guessing selectors
    here.
    """

    def parse(self, page: RawPage, marketplace: Marketplace) -> ParsedListing | ParseError:
        raise NotImplementedError(
            f"No real listing parser implemented for {marketplace.value} yet — "
            "see UnimplementedParser's docstring. Inject a fake Parser for tests; "
            "wiring a real one requires inspecting live page markup first."
        )
