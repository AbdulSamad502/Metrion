"""Mechanical forbidden-content scan for generated listing text (spec §6.4 rule 4, AC3, AC18).

Pure pattern matching over `textnorm.skeleton()` - NFKC, case, zero-width characters, full-width
forms and Cyrillic/Greek lookalikes cannot hide a word, and acronyms cannot dodge by being
spaced out (`G S T`, `g.s.t`).

This is a SAFETY NET behind the generator's own instructions, not the only defence and not a
semantic judge: it catches categories that are never acceptable in CMO copy regardless of
context. Everything it flags is a reason to regenerate, never to "fix" the text in place.

Categories
----------
PRICE          currency symbols/words, MRP, discounts, '% off', and price/discount/savings CLAIMS
               ("best price", "cheap", "on sale", "save big", "price drop"). CMO states no price
               figure (C7). The neutral word "price" ("fair price") is NOT banned: only figures
               and unsupported comparative/absolute/promotional claims about price are.
TAX            GST/IGST/CGST/SGST/UTGST/HSN/TDS/TCS/cess/VAT/tax. CMO has no GST path (C4).
DEMAND_CLAIM   'bestseller', 'trending', 'selling fast', 'in demand', '#1'... attention is not
               demand and CMO has no sales data (§6.8.7 rule 1).
REGULATED      guarantee / certified / clinically proven / FDA / ISO / cures. Unsupported claims.
               The ONLY waivable category: if the seller's own eligible facts contain the same
               trigger word, the claim is the seller's and is allowed (`allowed_context`).
CONTACT        URLs, domains, e-mail addresses, phone numbers, WhatsApp. Never emitted by CMO.

Documented conservatism (each is a deliberate trade, listed in the P2 report): what counts as a
phone number is a privacy heuristic, not a marketplace rule (see `identifiers`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from slim_cmo.identifiers import contains_phone_number
from slim_cmo.textnorm import skeleton


class ForbiddenCategory(str, Enum):
    PRICE = "PRICE"
    TAX = "TAX"
    DEMAND_CLAIM = "DEMAND_CLAIM"
    REGULATED = "REGULATED"
    CONTACT = "CONTACT"


@dataclass(frozen=True, slots=True)
class ForbiddenFinding:
    category: ForbiddenCategory
    rule: str  # stable rule id - never the matched text (no seller data in logs/violations)


def _w(pattern: str) -> str:
    """Word-bounded in the ASCII-folded skeleton (letters/digits on either side disqualify)."""
    return rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])"


def _spaced(word: str) -> str:
    """'gst' -> 'g[\\W_]{0,2}s[\\W_]{0,2}t': the acronym with up to two separator characters
    between letters, so 'G S T' and 'g.s.t' are caught but 'gist' is not."""
    return r"[\W_]{0,2}".join(re.escape(c) for c in word)


_RULES: tuple[tuple[ForbiddenCategory, str, re.Pattern[str], bool], ...] = tuple(
    (cat, rule, re.compile(rx), waivable)
    for cat, rule, rx, waivable in [
        # --- PRICE ---------------------------------------------------------------------
        (ForbiddenCategory.PRICE, "currency_symbol", r"[₹$€£¥]", False),
        (ForbiddenCategory.PRICE, "rupee_word", _w(r"rs\.?|inr|rupees?|paise|rupaye|rupaiye"), False),
        (ForbiddenCategory.PRICE, "mrp", _w(r"mrp"), False),
        # A price CLAIM (comparative, absolute or promotional), not the neutral word "price":
        # "fair price", "reasonable price", "value for money" are allowed; "best price",
        # "special offer price", "cheap", "price drop", "on sale", "save big" are not.
        (ForbiddenCategory.PRICE, "price_claim", _w(
            r"(?:lowest|best|cheapest|unbeatable|unmatched|rock[\s-]?bottom|bargain|wholesale|factory|special|offer|sale|reduced|"
            r"slashed|discounted|half|promo(?:tional)?|introductory|launch|festive|exclusive|competitive(?:ly)?|limited[\s-]time)"
            r"[\s-]+(?:price[ds]?|pricing|rates?)"
            r"|price[ds]?\s+(?:match|drop|cut|slash(?:ed)?|guarantee|off|war|reduction|starts?|starting)"
            r"|priced\s+to\s+(?:sell|move)"
            r"|cheap(?:er|est|ly)?"
            r"|on\s+sale"
            r"|(?:best|top|unbeatable|great)\s+deals?"
            r"|save\s+(?:big|more|money|up\s+to|\d+)"
            r"|savings?|money[\s-]saving"
        ), False),
        (ForbiddenCategory.PRICE, "discount_word", _w(r"discount(?:s|ed)?|cashback|clearance"), False),
        (ForbiddenCategory.PRICE, "percent_off", r"%\s*off|(?<![a-z0-9])percent\s+off(?![a-z0-9])", False),
        # --- TAX -----------------------------------------------------------------------
        (ForbiddenCategory.TAX, "tax_acronym", _w("|".join(_spaced(a) for a in ("utgst", "igst", "cgst", "sgst", "gst", "hsn", "tds", "tcs"))), False),
        (ForbiddenCategory.TAX, "tax_word", _w(r"tax(?:es|able|ed|ation)?|cess|vat|input\s+tax\s+credit"), False),
        # --- DEMAND_CLAIM --------------------------------------------------------------
        (ForbiddenCategory.DEMAND_CLAIM, "trending", _w(r"trending|trends\s+now"), False),
        (ForbiddenCategory.DEMAND_CLAIM, "bestseller", _w(r"best[\s-]?sell(?:er|ers|ing)|top[\s-]?sell(?:er|ers|ing)|hot\s+sell(?:er|ing)"), False),
        (ForbiddenCategory.DEMAND_CLAIM, "selling_claim", _w(r"sell(?:s|ing)\s+(?:fast|well|like|out)|sold\s+out|flying\s+off"), False),
        (ForbiddenCategory.DEMAND_CLAIM, "demand_claim", _w(r"(?:in|high|huge|strong|proven|massive|rising)\s+demand"), False),
        (ForbiddenCategory.DEMAND_CLAIM, "number_one", r"(?<![a-z0-9])(?:#\s?1|no\.?\s?1|number\s+(?:one|1))(?![a-z0-9])", False),
        (ForbiddenCategory.DEMAND_CLAIM, "popularity", _w(r"most\s+popular|everyone(?:'s|\s+is)\s+buying|customers?\s+favou?rite"), False),
        # --- REGULATED (waivable by the seller's own eligible facts) ---------------------
        (ForbiddenCategory.REGULATED, "guarantee", _w(r"guarantee[ds]?"), True),
        (ForbiddenCategory.REGULATED, "certified", _w(r"certified|certification|accredited|approved\s+by"), True),
        (ForbiddenCategory.REGULATED, "clinical", _w(r"clinically\s+(?:proven|tested)|dermatologist[\s-]tested|doctor[\s-]recommended"), True),
        (ForbiddenCategory.REGULATED, "authority", _w(r"fda|fssai|iso(?:\s?\d+)?|bis|ayush|cdsco"), True),
        (ForbiddenCategory.REGULATED, "cure_claim", _w(r"cures?|heals?|treats?\s+(?:disease|cancer|diabetes)"), True),
        (ForbiddenCategory.REGULATED, "best_in", _w(r"world'?s\s+best|best\s+in\s+(?:india|the\s+world|class)|india'?s\s+best"), True),
        # --- CONTACT -------------------------------------------------------------------
        (ForbiddenCategory.CONTACT, "url", r"https?:|(?<![a-z0-9])www\.", False),
        (ForbiddenCategory.CONTACT, "domain", r"(?<![a-z0-9@])[a-z0-9][a-z0-9-]*\.(?:com|in|net|org|co|io|shop|store|app|biz|info|xyz|online|site)(?![a-z0-9])", False),
        (ForbiddenCategory.CONTACT, "email", r"[a-z0-9._%+-]+@[a-z0-9-]+\.[a-z]{2,}", False),
        (ForbiddenCategory.CONTACT, "messaging_app", _w(r"whatsapp|telegram|wechat"), False),
    ]
)


# Phone detection lives in `identifiers` (real phone shapes; years, dates, model numbers and
# barcodes are not phone numbers). Re-exported under its original name for existing callers.
contains_phone_like_digits = contains_phone_number


_LETTER_DIGIT_BOUNDARY = re.compile(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])")


def _split_letters_digits(folded: str) -> str:
    """Insert a space at every letter<->digit boundary so a word boundary can fire inside
    'Rs499', 'GST18', 'MRP100', 'inr250' - the way sellers actually write prices and taxes."""
    return _LETTER_DIGIT_BOUNDARY.sub(" ", folded)


def scan_forbidden(
    text: str,
    *,
    categories: Iterable[ForbiddenCategory] | None = None,
    allowed_context: str | None = None,
) -> tuple[ForbiddenFinding, ...]:
    """Return every distinct (category, rule) that matches `text`, in rule order.

    `allowed_context` is the concatenated text of the seller's eligible facts / approved title.
    A REGULATED rule is skipped when the same rule also fires on that context (the seller
    themselves asserted it). No other category is ever waived.
    """
    wanted = frozenset(categories) if categories is not None else frozenset(ForbiddenCategory)
    folded = skeleton(text)
    split = _split_letters_digits(folded)  # 'rs499' -> 'rs 499', 'gst18' -> 'gst 18'
    context = skeleton(allowed_context) if allowed_context else ""
    context_split = _split_letters_digits(context)
    findings: list[ForbiddenFinding] = []
    for category, rule, pattern, waivable in _RULES:
        if category not in wanted:
            continue
        if pattern.search(folded) is None and pattern.search(split) is None:
            continue
        if waivable and context and (pattern.search(context) or pattern.search(context_split)):
            continue
        findings.append(ForbiddenFinding(category, rule))
    if ForbiddenCategory.CONTACT in wanted and contains_phone_number(text):
        findings.append(ForbiddenFinding(ForbiddenCategory.CONTACT, "phone_digits"))
    return tuple(findings)
