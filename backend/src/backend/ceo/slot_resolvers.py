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


_NAME_STOP = frozenset({"the", "a", "an", "my", "for", "of", "and", "competitor", "competitors", "listing", "product", "this", "that", "tracked", "verified", "price", "amazon", "flipkart", "meesho"})


def _name_tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.casefold())


def label_matches(text: str, label: str) -> bool:
    """Does what the seller wrote mean this competitor? Its whole name, its name without a variant note, a SHORT phrase made only of words from the name ("CASPIAN Astra 1L"),
    or a long message that contains the name's first two distinctive words. Never a single word, so two unrelated competitors are not mistaken for each other."""
    t = _norm(text)
    if any(k in t for k in _label_keys(label)):
        return True
    label_tokens = _name_tokens(label)
    words = [w for w in _name_tokens(t) if w not in _NAME_STOP]
    if len(words) >= 2 and set(words) <= set(label_tokens):
        return True
    lead = [w for w in label_tokens if w not in _NAME_STOP][:2]
    return len(lead) == 2 and len(" ".join(lead)) >= 8 and " ".join(lead) in t


def _label_keys(label: str) -> tuple[str, ...]:
    """What the seller may say to mean this competitor: its whole name, or the name without a trailing variant note ("..., Royal Blue", "(Pack of 2)", "- Black")."""
    full = _norm(label)
    head = _norm(re.split(r"\s*(?:,|\(|\[|\s-\s|\s–\s)", label, maxsplit=1)[0])
    return (full,) if head == full or len(head) < 8 else (full, head)


def resolve_competitor(tenant_id: UUID, raw: str | None) -> CompetitorMatch | CompetitorUnresolved:
    """Matches the seller's words against THIS tenant's active tracked competitors by their own label: an exact (case-insensitive) label wins; otherwise a
    single label that contains the words (or that the words contain). Several candidates is AMBIGUOUS, never a pick."""
    text = _norm(raw or "")
    rows = ceo_reads.list_active_competitors(tenant_id, limit=_MAX_TRACKED)
    labelled = [(UUID(str(r["id"])), ceo_reads.competitor_label(r)) for r in rows]  # an unnamed competitor has a derived name, so it can still be referred to
    if not rows:
        return CompetitorUnresolved("NONE_TRACKED")
    if not text or not labelled:
        return CompetitorUnresolved("NOT_FOUND", tuple(label for _, label in labelled[:MAX_COMPETITOR_CHOICES]), tuple(labelled[:MAX_COMPETITOR_CHOICES]))
    exact = [(i, l) for i, l in labelled if _norm(l) == text]
    if len(exact) == 1:
        return CompetitorMatch(*exact[0])
    pool = exact or [(i, l) for i, l in labelled if label_matches(text, l) or text in _norm(l)]
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
            return CompetitorMatch(url_id, ceo_reads.competitor_label(r))
    return None


@dataclass(frozen=True, slots=True)
class ProductMatch:
    product_id: str
    title: str | None


@dataclass(frozen=True, slots=True)
class ProductUnresolved:
    reason: str  # NONE_KNOWN | NOT_FOUND | AMBIGUOUS
    choices: tuple[str, ...] = ()


def resolve_seller_product(tenant_id: UUID, raw: str | None) -> ProductMatch | ProductUnresolved:
    """Matches the seller's words against THIS tenant's own products (their SKU, or the title on their latest sales line). An exact SKU or title wins; otherwise a
    single product whose title contains the words (or that the words contain). Several is AMBIGUOUS, none is NOT_FOUND — never a pick."""
    text = _norm(raw or "")
    products = ceo_reads.list_seller_products(tenant_id)
    if not products:
        return ProductUnresolved("NONE_KNOWN")
    labelled = [(pid, title or pid) for pid, title in products]
    shown = tuple(label for _, label in labelled[:MAX_COMPETITOR_CHOICES])
    if not text:
        return ProductUnresolved("NOT_FOUND", shown)
    exact = [(pid, label) for pid, label in labelled if _norm(pid) == text or _norm(label) == text]
    if len(exact) == 1:
        return ProductMatch(exact[0][0], exact[0][1])
    pool = exact or [(pid, label) for pid, label in labelled if _norm(label) in text or text in _norm(label) or _norm(pid) in text]
    if len(pool) == 1:
        return ProductMatch(pool[0][0], pool[0][1])
    if len(pool) > 1:
        return ProductUnresolved("AMBIGUOUS", tuple(label for _, label in pool[:MAX_COMPETITOR_CHOICES]))
    return ProductUnresolved("NOT_FOUND", shown)
