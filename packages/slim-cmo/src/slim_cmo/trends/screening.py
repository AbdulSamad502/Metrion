"""Outbound-term screening and catalog-derived niche suggestions (spec §6.8.3, C15, AC30, AC34).

Two deterministic jobs, neither using a model:

**`screen_term`** - the last gate before a string may become part of a provider query. A term
fails if it is empty, too long, contains control characters, or LOOKS LIKE AN IDENTIFIER:
e-mail or @handle, URL/domain, Indian mobile number, GSTIN, PAN, Amazon (`123-1234567-1234567`) or
Flipkart (`OD...`) order id, a phone-like digit run, or is purely numeric. The rule is
conservative: a false positive costs the seller a manual retype; a false negative would
leak a customer or business identifier to a third party.

**`suggest_terms`** - turns the seller's own catalog item titles into candidate niche terms:
words and 1-3-word phrases, ranked by how many DISTINCT titles contain them (document
frequency), longer phrases first on ties, a shorter phrase dropped when a kept longer one
contains it with at least the same frequency. Pure frequency over text; the caller supplies the
stop-word list explicitly (it is linguistic data, not policy, but it is passed in rather than
hidden as a default so it is visible and testable) and the caps from configuration.
Suggestions are only ever SUGGESTIONS: nothing leaves Metrion until the seller confirms.
Stop words are data in `slim_cmo.stopwords` (English, listing filler, Hindi, Romanised Hindi),
adjustable per deployment through the `niche_stopwords_extra` / `niche_stopwords_exclude`
configuration keys.

Documented limits (printed in the P2 report): brand names are not recognised and may rank high
(the seller rejects them); non-Latin scripts are tokenised but get no linguistic treatment.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from slim_cmo.identifiers import contains_long_digit_run, contains_phone_number, contains_spelled_digit_run
from slim_cmo.stopwords import DEFAULT_STOPWORDS, ENGLISH_FUNCTION_WORDS, HINDI_FUNCTION_WORDS, HINGLISH_FUNCTION_WORDS, LISTING_FILLER_WORDS, build_stopwords  # noqa: F401  (re-exported)
from slim_cmo.textnorm import (
    collapse_whitespace, count_chars, dedupe_key, deobfuscate_contact, has_bidi_controls, skeleton, squash_spaced_characters, strip_invisible, tokens,
)


class ScreenReason(str, Enum):
    EMPTY = "EMPTY"
    TOO_LONG = "TOO_LONG"
    CONTROL_CHARACTERS = "CONTROL_CHARACTERS"
    EMAIL = "EMAIL"
    HANDLE = "HANDLE"
    URL_OR_DOMAIN = "URL_OR_DOMAIN"
    PHONE_NUMBER = "PHONE_NUMBER"
    GSTIN = "GSTIN"
    PAN = "PAN"
    ORDER_ID = "ORDER_ID"
    DIGIT_RUN = "DIGIT_RUN"
    NUMERIC_ONLY = "NUMERIC_ONLY"


@dataclass(frozen=True, slots=True)
class ScreenResult:
    ok: bool
    term: str  # the normalised form (what would be stored and sent)
    reasons: tuple[ScreenReason, ...]


_PATTERNS: tuple[tuple[ScreenReason, re.Pattern[str]], ...] = (
    (ScreenReason.EMAIL, re.compile(r"[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+")),
    (ScreenReason.URL_OR_DOMAIN, re.compile(
        r"https?:|(?<![a-z0-9])www\.|(?<![a-z0-9@])[a-z0-9][a-z0-9-]*\.(?:com|in|net|org|co|io|shop|store|app|biz|info|xyz|online|site)(?![a-z0-9])")),
    (ScreenReason.GSTIN, re.compile(r"(?<![a-z0-9])\d{2}[a-z]{5}\d{4}[a-z][1-9a-z]z[0-9a-z](?![a-z0-9])")),
    (ScreenReason.PAN, re.compile(r"(?<![a-z0-9])[a-z]{5}\d{4}[a-z](?![a-z0-9])")),
    (ScreenReason.ORDER_ID, re.compile(r"(?<!\d)\d{3}-\d{7}-\d{7}(?!\d)|(?<![a-z0-9])od\d{10,}(?![a-z0-9])")),
    (ScreenReason.PHONE_NUMBER, re.compile(r"(?<!\d)(?:\+?91[\s\-]?)?[6-9]\d{9}(?!\d)")),
)


def normalise_term(term: str) -> str:
    """What a term looks like once stored: NFKC, invisible characters removed, whitespace
    collapsed, case-folded. Scripts are NOT folded (a legitimate non-Latin term stays itself)."""
    return collapse_whitespace(strip_invisible(unicodedata.normalize("NFKC", term))).casefold()


def screen_term(term: object, *, max_chars: int) -> ScreenResult:
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("max_chars must be a positive integer (configuration: max_term_chars)")
    if not isinstance(term, str):
        return ScreenResult(False, "", (ScreenReason.EMPTY,))
    reasons: list[ScreenReason] = []
    if any(unicodedata.category(ch) == "Cc" for ch in term) or has_bidi_controls(term):
        reasons.append(ScreenReason.CONTROL_CHARACTERS)
    normalised = normalise_term(term)
    if not normalised:
        return ScreenResult(False, "", tuple(dict.fromkeys(reasons + [ScreenReason.EMPTY])))
    if count_chars(normalised) > max_chars:
        reasons.append(ScreenReason.TOO_LONG)
    folded = skeleton(normalised)
    variants = (folded, squash_spaced_characters(folded), deobfuscate_contact(folded))  # evasion-resistant matching forms
    for reason, pattern in _PATTERNS:
        if any(pattern.search(v) for v in variants):
            reasons.append(reason)
    if "@" in folded and ScreenReason.EMAIL not in reasons:
        reasons.append(ScreenReason.HANDLE)  # '@someone': a social handle is an identifier too
    if contains_phone_number(folded) and ScreenReason.PHONE_NUMBER not in reasons:
        reasons.append(ScreenReason.PHONE_NUMBER)
    if (contains_long_digit_run(folded) or contains_spelled_digit_run(folded)) and ScreenReason.PHONE_NUMBER not in reasons:
        reasons.append(ScreenReason.DIGIT_RUN)  # 8+ digits: an identifier-sized number, refused outbound
    if not any(ch.isalpha() for ch in folded):
        reasons.append(ScreenReason.NUMERIC_ONLY)
    unique = tuple(dict.fromkeys(reasons))
    return ScreenResult(not unique, normalised, unique)


@dataclass(frozen=True, slots=True)
class Suggestion:
    term: str
    document_frequency: int  # number of DISTINCT titles containing it
    word_count: int


_MAX_WORDS = 3


def _runs(title: str, stopwords: frozenset[str]) -> list[list[str]]:
    """Maximal runs of non-stopword tokens (an n-gram never spans a stop word)."""
    runs: list[list[str]] = []
    current: list[str] = []
    for tok in tokens(normalise_term(title)):
        if tok in stopwords or len(tok) < 2 or not any(ch.isalpha() for ch in tok):
            if current:
                runs.append(current)
                current = []
        else:
            current.append(tok)
    if current:
        runs.append(current)
    return runs


def suggest_terms(
    titles: Iterable[str],
    *,
    stopwords: frozenset[str],
    max_terms: int,
    max_term_chars: int,
) -> tuple[Suggestion, ...]:
    if type(max_terms) is not int or max_terms < 1:
        raise ValueError("max_terms must be a positive integer (configuration: max_confirmed_niche_terms)")
    seen_titles: set[str] = set()
    df: Counter[tuple[str, ...]] = Counter()
    for title in titles:
        if not isinstance(title, str):
            continue
        key = dedupe_key(title)
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)
        grams: set[tuple[str, ...]] = set()
        for run in _runs(title, stopwords):
            for n in range(1, _MAX_WORDS + 1):
                for i in range(len(run) - n + 1):
                    grams.add(tuple(run[i : i + n]))
        df.update(grams)

    ranked = sorted(df.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    chosen: list[tuple[tuple[str, ...], int]] = []
    for gram, freq in ranked:
        if len(chosen) >= max_terms:
            break
        if not screen_term(" ".join(gram), max_chars=max_term_chars).ok:
            continue
        if any(len(big) > len(gram) and freq <= bf and _contains(big, gram) for big, bf in chosen):
            continue  # a kept longer phrase already carries it
        chosen.append((gram, freq))
    return tuple(Suggestion(" ".join(g), f, len(g)) for g, f in chosen)


def _contains(big: tuple[str, ...], small: tuple[str, ...]) -> bool:
    n = len(small)
    return any(big[i : i + n] == small for i in range(len(big) - n + 1))
