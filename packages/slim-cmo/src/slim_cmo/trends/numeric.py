"""Numeric-claim detection for news and tactic text (spec §6.8.7 rule 5, AC33).

In V1 a trend finding says WHAT changed and links the source; it does not restate figures -
fee percentages, prices, thresholds, counts. Margin and fee numbers come only from Brain 1 /
CFO. This module is the mechanical check that enforces it: given a summary, it reports which
kinds of numeric claim it contains so the summary can be regenerated.

Dates are NOT claims: "effective 1 November 2026" is what news is made of. Date expressions
(ISO dates, `d/m/y`, `1 Nov 2026`, `Nov 1, 2026`, `Nov 2026`, bare years, quarters, fiscal-year
tags) are masked out first; whatever digits remain are a claim. The check is deliberately
strict - "Top 5 tips" is flagged - because a regeneration is cheap and a model-invented
statistic is not.

Limits (stated in the P2 report): number WORDS ("twelve") are not flagged except through
percent/currency/magnitude words; a date written in an unusual format may be flagged (a false
positive, never a missed claim).
"""

from __future__ import annotations

import re

from slim_cmo.textnorm import skeleton

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_ORD = r"(?:st|nd|rd|th)?"
_DATE_MASKS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"(?<!\d)\d{4}-\d{1,2}-\d{1,2}(?!\d)",
        r"(?<!\d)\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}(?!\d)",
        rf"(?<![a-z0-9])\d{{1,2}}{_ORD}\s+(?:of\s+)?{_MONTH}\b\.?(?:,?\s+\d{{4}})?",
        rf"(?<![a-z0-9]){_MONTH}\.?\s+\d{{1,2}}{_ORD}(?![0-9])(?:,?\s+\d{{4}})?",
        rf"(?<![a-z0-9]){_MONTH}\.?,?\s+\d{{4}}(?!\d)",
        r"(?<!\d)(?:19|20)\d{2}(?!\d)",
        r"(?<![a-z0-9])q[1-4](?![a-z0-9])",
        r"(?<![a-z0-9])fy\s?\d{2,4}(?!\d)",
    )
)
_PERCENT = re.compile(r"%|(?<![a-z0-9])per\s?cent(?:age)?(?![a-z0-9])|(?<![a-z0-9])percent(?:age)?(?![a-z0-9])")
_CURRENCY = re.compile(r"[₹$€£¥]|(?<![a-z0-9])(?:rs\.?|inr|rupees?|paise)(?![a-z0-9])")
_MAGNITUDE = re.compile(r"(?<![a-z0-9])(?:lakhs?|crores?|millions?|billions?|trillions?)(?![a-z0-9])")
_DIGITS = re.compile(r"\d")


def find_numeric_claims(text: str) -> tuple[str, ...]:
    """Sorted, de-duplicated rule ids present: `percent`, `currency`, `magnitude`, `number`."""
    folded = skeleton(text)
    for mask in _DATE_MASKS:
        folded = mask.sub(" ", folded)
    found: set[str] = set()
    if _PERCENT.search(folded):
        found.add("percent")
    if _CURRENCY.search(folded):
        found.add("currency")
    if _MAGNITUDE.search(folded):
        found.add("magnitude")
    if _DIGITS.search(folded):
        found.add("number")
    return tuple(sorted(found))


def contains_numeric_claim(text: str) -> bool:
    return bool(find_numeric_claims(text))
