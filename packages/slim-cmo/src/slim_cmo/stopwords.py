"""Stop-word data for niche-term suggestions (spec §6.8.3), and how an operator adjusts it.

Stop words split a catalog title into the word runs that may become niche-term suggestions
(an n-gram never spans a stop word). This is LINGUISTIC data, not business policy, but it is
still configurable (P2 review decision): the built-in sets below are the starting point and
`build_stopwords` applies the operator's additions and removals from configuration
(`niche_stopwords_extra`, `niche_stopwords_exclude`).

Built-in coverage - English function words, listing filler words, Hindi (Devanagari) function
words, and Romanised Hindi ("Hinglish") function words, so mixed-language catalog titles split
sensibly. Ambiguous Romanised words that are also common English CONTENT words (`main`, as in
"main compartment") are deliberately left out. Brand names are not stop words and cannot be
recognised; a brand that ranks high is rejected by the seller at confirmation time.

This is not a language-detection feature and makes no claim of linguistic completeness; it is a
bounded, inspectable list. Regional languages other than Hindi are not covered (spec Q23).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

from slim_cmo.textnorm import collapse_whitespace, strip_invisible

ENGLISH_FUNCTION_WORDS: frozenset[str] = frozenset(
    "a an the and or nor but for with without of to in on at by from as into onto over under up down "
    "is are was were be been being this that these those it its your you yours our we they their "
    "not no yes all any each every both more most other another such only own same than too very "
    "can will just also so if then than via per".split()
)

LISTING_FILLER_WORDS: frozenset[str] = frozenset(
    "pack packs pcs pc piece pieces combo set sets kit new latest best top original genuine offer offers sale "
    "free buy online india indian quality high brand branded assorted available hot deal deals special "
    "item items product products women womens men mens kids unisex size color colour colours".split()
)

# Hindi (Devanagari) function words: postpositions, conjunctions, auxiliaries, pronouns, particles.
HINDI_FUNCTION_WORDS: frozenset[str] = frozenset(
    "का की के को में से पर और या है हैं था थी थे हो एक यह ये वह वो इस उस लिए साथ भी तो ही कि जो जैसे "
    "अपने आप हम मैं तुम नहीं बहुत सभी कुछ वाला वाली वाले".split()
)

# The same words written in Latin script, as Indian sellers commonly do in mixed titles.
HINGLISH_FUNCTION_WORDS: frozenset[str] = frozenset(
    "ka ki ke ko mein se par aur ya hai hain tha thi the ek yeh ye woh wo liye saath bhi hi jo apne aap hum "
    "tum nahi bahut sabhi kuch wala wali wale".split()
)

DEFAULT_STOPWORDS: frozenset[str] = (
    ENGLISH_FUNCTION_WORDS | LISTING_FILLER_WORDS | HINDI_FUNCTION_WORDS | HINGLISH_FUNCTION_WORDS
)


def normalise_stopword(word: object) -> str:
    """Same normal form the tokeniser compares against: NFKC, invisible characters removed,
    whitespace collapsed, case-folded. Scripts are not folded."""
    if not isinstance(word, str):
        raise ValueError(f"a stop word must be a string, got {type(word).__name__}")
    cleaned = collapse_whitespace(strip_invisible(unicodedata.normalize("NFKC", word))).casefold()
    if not cleaned or " " in cleaned:
        raise ValueError(f"a stop word must be a single non-empty word, got {word!r}")
    return cleaned


def build_stopwords(
    extra: Iterable[object] = (),
    exclude: Iterable[object] = (),
    *,
    defaults: frozenset[str] = DEFAULT_STOPWORDS,
) -> frozenset[str]:
    """`(defaults - exclude) | extra`, each word normalised. An invalid entry raises
    ValueError (the config loader reports it as invalid configuration instead). Excluding a word
    that is not a default, or adding one that already is, is harmless."""
    removed = {normalise_stopword(w) for w in exclude}
    added = {normalise_stopword(w) for w in extra}
    return frozenset((defaults - removed) | added)
