"""Phone-number and long-identifier detection (spec §6.4 CONTACT rule, §6.8.3 outbound screen).

Two different questions, deliberately answered differently:

**`contains_phone_number`** - used on GENERATED LISTING COPY. Contact details must never appear
there, but years ("2024 2025 edition"), dates ("2026-10-03"), model numbers ("1234 5678"), HSN
codes, PIN codes and barcodes (EAN-13, UPC-A) are ordinary product text and must not be
refused. So this recognises actual phone SHAPES rather than "eight digits":

* an Indian mobile: 10 digits starting 6-9, optionally prefixed `0` or `91`;
* a `0`-prefixed number (STD landline, `0` + 10 digits);
* an explicit international number: a leading `+` followed by 8-15 digits (E.164 range).

Digit groups may be separated by single spaces, dots, dashes or brackets, may begin
mid-sentence, and may follow year-looking groups (`2024 98765 43210` is still a phone number).
Runs made ONLY of year groups (19xx/20xx) or a recognised date are skipped.

**`contains_long_digit_run`** - used on OUTBOUND NICHE TERMS (the stricter gate, C15): a niche
term has no reason to hold a long number at all, and a customer/order identifier leaking to a
third party is the failure to avoid. So any run of 8+ digits counts, after discounting
year-looking groups.

Documented limits (stated in the P2 report): a 10-digit product identifier that starts 6-9 (an
ISBN-10, say) looks like an Indian mobile and is refused in copy - the privacy-first side of
the trade; a 10-digit number starting 1-5 without a leading 0 or + is NOT treated as a phone
in copy (it is far more often an identifier) but IS refused in outbound terms.
"""

from __future__ import annotations

import re

from slim_cmo.textnorm import skeleton

# >= 7 digits, up to two separator characters between digit groups ('(98765) 43210'). Group-aligned sub-sequences are examined
# afterwards, so a phone number preceded by years or other digit groups is still found.
_CANDIDATE = re.compile(r"\(?\+?\(?\d(?:[\s.\-()]{0,2}\d){6,}")
_GROUP = re.compile(r"\d+")
_YEAR = re.compile(r"(?:19|20)\d{2}")
_DATE_ONLY = re.compile(r"\d{4}[\-./]\d{1,2}[\-./]\d{1,2}|\d{1,2}[\-./]\d{1,2}[\-./](?:\d{4}|\d{2})")

_MAX_E164_DIGITS = 15
_MIN_E164_DIGITS = 8


def _is_year(group: str) -> bool:
    return _YEAR.fullmatch(group) is not None


def _looks_like_date_or_years(run: str) -> bool:
    stripped = run.strip("+() ")
    if _DATE_ONLY.fullmatch(stripped):
        return True
    groups = _GROUP.findall(run)
    return bool(groups) and all(_is_year(g) for g in groups)


def _phone_shaped(digits: str, *, plus: bool) -> bool:
    n = len(digits)
    if plus:
        return _MIN_E164_DIGITS <= n <= _MAX_E164_DIGITS
    if n == 10 and digits[0] in "6789":
        return True  # Indian mobile
    if n == 11 and digits[0] == "0":
        return True  # 0-prefixed mobile, or STD landline
    if n == 12 and digits.startswith("91") and digits[2] in "6789":
        return True  # +91 without the plus sign
    return False


def contains_phone_number(text: str) -> bool:
    """True if `text` contains a phone-number-shaped digit sequence (see module docstring)."""
    folded = skeleton(text)  # full-width / non-Latin digits are folded to ASCII first
    for match in _CANDIDATE.finditer(folded):
        run = match.group(0)
        if _looks_like_date_or_years(run):
            continue
        groups = _GROUP.findall(run)
        plus = run.lstrip("(").startswith("+")
        for i in range(len(groups)):
            acc = ""
            for j in range(i, len(groups)):
                acc += groups[j]
                if len(acc) > _MAX_E164_DIGITS:
                    break
                if all(_is_year(g) for g in groups[i : j + 1]):
                    continue  # a span of nothing but years is never a phone number
                if _phone_shaped(acc, plus=plus and i == 0):
                    return True
    return False


def contains_long_digit_run(text: str, *, min_digits: int = 8) -> bool:
    """True if `text` has a run of at least `min_digits` digits (single separators allowed
    between them), not counting year-looking groups. For the OUTBOUND screen only.
    `min_digits=8` is a privacy heuristic, not a business or marketplace rule."""
    if type(min_digits) is not int or min_digits < 7:
        raise ValueError("min_digits must be an integer >= 7 (the candidate scanner's floor)")
    folded = skeleton(text)
    for match in _CANDIDATE.finditer(folded):
        groups = [g for g in _GROUP.findall(match.group(0)) if not _is_year(g)]
        if sum(len(g) for g in groups) >= min_digits:
            return True
    return False
