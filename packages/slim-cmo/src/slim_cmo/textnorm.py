"""Deterministic text normalisation shared by every validator and detector.

Pure functions, no I/O, no model. Two jobs:

1. **Robust matching.** Forbidden-content and claim detectors must not be defeated by trivial
   obfuscation - zero-width characters (`G\\u200bST`), full-width letters, case, stray
   punctuation, or Cyrillic/Greek lookalikes. `skeleton()` folds all of that away before any
   pattern runs.
2. **Counting.** Marketplace limits are enforced in code, never by the model. `count_chars()`
   is deliberately CONSERVATIVE: it counts UTF-16 code units, so an astral character (most
   emoji) counts as 2. That is >= code points >= grapheme clusters, i.e. it can only
   over-count relative to any plausible marketplace rule and never lets an over-limit title
   through. Which unit each marketplace actually uses is unverified (spec Q-open); if a
   marketplace is later verified to count differently, change it HERE, in one place.

`strip_invisible` removes ALL format characters, including the zero-width joiner/non-joiner
(U+200D/U+200C) that some Indic and Persian text uses for shaping. That is deliberate: they are
also the cheapest way to hide a word from a detector, and V1 claims English/India copy only
(spec Q23). If regional-language support is added, `clean_generated_text` must preserve them
between letters of those scripts while `skeleton` keeps stripping them.

Confusable folding is partial by design (the Latin-lookalike Cyrillic/Greek letters that
matter for English-language copy). It is not a full Unicode TR39 implementation and the
tests say so.
"""

from __future__ import annotations

import re
import unicodedata

# Cyrillic / Greek letters that render identically to Latin ones, mapped after casefold().
_CONFUSABLES: dict[str, str] = {
    # Cyrillic
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p",
    "с": "c", "т": "t", "у": "y", "х": "x", "і": "i", "ї": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "һ": "h", "ԛ": "q", "ԝ": "w", "ӏ": "l", "ё": "e",
    # Greek
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p",
    "τ": "t", "υ": "u", "χ": "x", "ϲ": "c",
    # Latin variants NFKC leaves alone
    "ı": "i", "ſ": "s",
}
_CONFUSABLE_TABLE = {ord(k): v for k, v in _CONFUSABLES.items()}

_WS_RE = re.compile(r"\s+")


def strip_invisible(text: str) -> str:
    """Remove format characters (Cf: zero-width space/joiners, bidi marks, soft hyphen, BOM...),
    unassigned, private-use and surrogate code points. Ordinary whitespace is kept."""
    return "".join(ch for ch in text if unicodedata.category(ch) not in ("Cf", "Cs", "Co", "Cn"))


def collapse_whitespace(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def to_ascii_digits(text: str) -> str:
    """Map every Unicode decimal digit (Devanagari, Arabic-Indic, full-width...) to ASCII 0-9,
    so a number cannot hide from a numeric check behind another script."""
    out = []
    for ch in text:
        if unicodedata.category(ch) == "Nd":
            out.append(str(unicodedata.decimal(ch)))
        else:
            out.append(ch)
    return "".join(out)


def skeleton(text: str) -> str:
    """The canonical matching form: NFKC -> drop invisible characters -> casefold -> fold
    Cyrillic/Greek lookalikes -> ASCII digits -> collapse whitespace. Idempotent."""
    folded = unicodedata.normalize("NFKC", text)
    folded = strip_invisible(folded)
    folded = folded.casefold().translate(_CONFUSABLE_TABLE)
    folded = to_ascii_digits(folded)
    return collapse_whitespace(folded)


def _is_word_char(ch: str) -> bool:
    """Letter, digit or COMBINING MARK. Marks matter: Indic vowel signs and nasalisation marks
    are Unicode category M*, which the regex word class does not match - treating them as
    punctuation would shred Hindi words ('बोतल' -> 'बतल') and make different words look equal."""
    return ch.isalnum() or unicodedata.category(ch)[0] == "M"


def tokens(text: str) -> list[str]:
    """Maximal runs of word characters (letters, digits, combining marks) in `text` as given -
    no case or script folding, so non-Latin words survive intact."""
    out: list[str] = []
    current: list[str] = []
    for ch in text:
        if _is_word_char(ch):
            current.append(ch)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


def dedupe_key(text: str) -> str:
    """Equality key for 'is this the same text?' (duplicate titles, bullets, keywords,
    syndicated headlines): the `skeleton` reduced to its word tokens joined by single spaces.
    Punctuation, symbols and spacing differences vanish; letters, digits and combining marks
    are kept. Two strings with the same key are the same words in the same order."""
    return " ".join(tokens(skeleton(text)))


def count_chars(text: str) -> int:
    """Conservative character count (UTF-16 code units of the NFC form). See module docstring."""
    return len(unicodedata.normalize("NFC", text).encode("utf-16-le")) // 2


def count_by_rule(text: str, rule: str) -> int:
    """Character count under a VERIFIED per-marketplace rule (`types.CountRule` values).
    `count_chars` (UTF-16 units) remains the conservative implementation fallback used by
    callers that have no verified rule; production generation does not run without one."""
    if rule == "UTF16_CODE_UNITS":
        return count_chars(text)
    if rule == "CODE_POINTS":
        return len(unicodedata.normalize("NFC", text))
    raise ValueError(f"unknown counting rule {rule!r}")


def utf8_bytes(text: str) -> int:
    return len(unicodedata.normalize("NFC", text).encode("utf-8"))


_BIDI_CONTROLS = frozenset(chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200E, 0x200F, 0x061C))


def has_bidi_controls(text: str) -> bool:
    """True if `text` carries a bidirectional override / isolate / mark. Generated text for Indian marketplaces has no use for them,
    and an override (U+202E) makes reversed letters DISPLAY as a banned word while the stored string looks harmless."""
    return any(ch in _BIDI_CONTROLS for ch in text)


def squash_spaced_characters(folded: str, *, min_run: int = 3) -> str:
    """Join runs of at least `min_run` consecutive single-character words ('t r e n d i n g', 'h t t p s : / / x . c o m') so a
    letter-spaced word cannot hide from a word-boundary match. Applied as an ADDITIONAL matching variant, never to stored text."""
    out: list[str] = []
    run: list[str] = []
    for token in folded.split(" "):
        if len(token) == 1:
            run.append(token)
            continue
        out.extend(["".join(run)] if len(run) >= min_run else run)
        run = []
        out.append(token)
    out.extend(["".join(run)] if len(run) >= min_run else run)
    return " ".join(out)


_AT = re.compile(r"\s*[\[({]\s*at\s*[\])}]\s*")
_DOT = re.compile(r"\s*[\[({]\s*dot\s*[\])}]\s*")


def deobfuscate_contact(folded: str) -> str:
    """'name [at] example [dot] com' -> 'name@example.com' (a matching variant for contact details; stored text is untouched)."""
    return _DOT.sub(".", _AT.sub("@", folded))


def has_control_characters(text: str, *, allow_newlines: bool = False) -> bool:
    """True if `text` contains any C0/C1 control character (tabs and newlines included unless
    `allow_newlines`, which permits only \\n and \\r\\n - a description may have paragraphs, a
    title may not)."""
    for ch in text:
        if unicodedata.category(ch) == "Cc":
            if allow_newlines and ch in ("\n", "\r"):
                continue
            return True
    return has_bidi_controls(text)


def clean_generated_text(text: str) -> str:
    """Tolerant first pass applied to model output before validation: NFC, strip invisible
    characters, trim the ends. Interior content is NOT rewritten - validators judge what the
    model actually produced."""
    return strip_invisible(unicodedata.normalize("NFC", text)).strip()
