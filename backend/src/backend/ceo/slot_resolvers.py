"""Deterministic resolvers for chat slots that name something in the seller's own data (spec §6.12 rule 1, E22).

The model may fill slot TEXT ("the Acme listing", "₹499"); only code turns that text into an id or an amount, and only from the CALLER'S OWN tenant data
(RLS-scoped reads). Nothing is guessed: an unreadable amount, an unknown competitor or an ambiguous name is a clarification, never a default.
No floats anywhere: amounts go through `Decimal` to integer paise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import UUID

from backend.services import ceo_reads

MAX_COMPETITOR_CHOICES = 5  # how many names a clarification lists (display only)
_MAX_TRACKED = 51  # read one more than the largest list the Business State shows, so "too many to match safely" is detectable
_MAX_PAISE_DIGITS = 17  # a BIGINT can hold 19 digits; this keeps the whole-paise value comfortably inside it (a technical limit, not a business one)

_PREFIX = re.compile(r"^(?:rs\.?|inr|₹|rupees?)\s*", re.IGNORECASE)
_SUFFIX = re.compile(r"\s*(?:/-|rs\.?|inr|rupees?|only)\s*$", re.IGNORECASE)
_PLAIN_NUMBER = re.compile(r"^\d+(?:\.\d{1,2})?$")


def parse_amount_paise(raw: str | None) -> int | None:
    """"₹499", "Rs. 1,299.50", "1,29,900", "499 rupees" -> integer paise. Anything else (a word like "5k" or "a lakh", a range, a percentage, a negative
    or zero amount) -> None, so the seller is asked instead of the system guessing."""
    if raw is None:
        return None
    text = raw.strip()
    for _ in range(2):
        text = _PREFIX.sub("", text).strip()
        text = _SUFFIX.sub("", text).strip()
    text = text.replace(",", "").replace(" ", "")
    if not _PLAIN_NUMBER.match(text):
        return None
    try:
        paise = int((Decimal(text) * 100).to_integral_value())
    except InvalidOperation:
        return None
    if paise <= 0 or len(str(paise)) > _MAX_PAISE_DIGITS:
        return None
    return paise


@dataclass(frozen=True, slots=True)
class CompetitorMatch:
    url_id: UUID
    label: str


@dataclass(frozen=True, slots=True)
class CompetitorUnresolved:
    reason: str  # NONE_TRACKED | NOT_FOUND | AMBIGUOUS
    choices: tuple[str, ...] = ()
    candidates: tuple[tuple[UUID, str], ...] = ()  # the real candidates behind `choices` (id, label), for a decision card


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def resolve_competitor(tenant_id: UUID, raw: str | None) -> CompetitorMatch | CompetitorUnresolved:
    """Matches the seller's words against THIS tenant's active tracked competitors by their own label: an exact (case-insensitive) label wins; otherwise a
    single label that contains the words (or that the words contain). Several candidates is AMBIGUOUS, never a pick."""
    text = _norm(raw or "")
    rows = ceo_reads.list_active_competitors(tenant_id, limit=_MAX_TRACKED)
    labelled = [(UUID(str(r["id"])), str(r["label"])) for r in rows if r.get("label")]
    if not rows:
        return CompetitorUnresolved("NONE_TRACKED")
    if not text or not labelled:
        return CompetitorUnresolved("NOT_FOUND", tuple(label for _, label in labelled[:MAX_COMPETITOR_CHOICES]), tuple(labelled[:MAX_COMPETITOR_CHOICES]))
    exact = [(i, l) for i, l in labelled if _norm(l) == text]
    if len(exact) == 1:
        return CompetitorMatch(*exact[0])
    pool = exact or [(i, l) for i, l in labelled if _norm(l) in text or text in _norm(l)]
    if len(pool) == 1:
        return CompetitorMatch(*pool[0])
    if len(pool) > 1:
        return CompetitorUnresolved("AMBIGUOUS", tuple(l for _, l in pool[:MAX_COMPETITOR_CHOICES]), tuple(pool[:MAX_COMPETITOR_CHOICES]))
    return CompetitorUnresolved("NOT_FOUND", tuple(label for _, label in labelled[:MAX_COMPETITOR_CHOICES]), tuple(labelled[:MAX_COMPETITOR_CHOICES]))


def resolve_competitor_ref(tenant_id: UUID, url_id: UUID) -> CompetitorMatch | None:
    """A competitor chosen through a control (a reference), checked against THIS tenant's active competitors. Another tenant's id, an archived one or an
    unknown one is simply not found: a reference is never trusted for existing."""
    for r in ceo_reads.list_active_competitors(tenant_id, limit=_MAX_TRACKED):
        if UUID(str(r["id"])) == url_id:
            return CompetitorMatch(url_id, str(r.get("label") or "Competitor"))
    return None
