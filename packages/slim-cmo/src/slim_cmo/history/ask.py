"""What the seller is asking about their listing history, read from their words (CMO 3.0 M7). Pure: no model, no I/O. It recognises a closed set of requests; anything else is None and goes on to the
rest of the CEO as before. It never decides which product or version is meant when the words leave that open: it returns what it found and the caller asks."""

from __future__ import annotations

import re
from dataclasses import dataclass

HISTORY, VERSION, COMPARE, CHANGES, KEYWORDS_ADDED, KEYWORDS_REMOVED, WHY_REVISED, AUDIT_CHANGES, IMPROVE, CLAIMS, APPROVED = (
    "HISTORY", "VERSION", "COMPARE", "CHANGES", "KEYWORDS_ADDED", "KEYWORDS_REMOVED", "WHY_REVISED", "AUDIT_CHANGES", "IMPROVE", "CLAIMS", "APPROVED")
MARKETPLACES = {"amazon": "AMAZON", "flipkart": "FLIPKART", "meesho": "MEESHO"}

_FOLD = lambda t: " ".join(re.sub(r"[?!.,;:\"“”']", " ", t.casefold()).split())  # noqa: E731
_LISTING = re.compile(r"\b(?:listing|listings|version|versions|revision|revisions|revised)\b")
_NUM = r"(?:version|v|revision)\s*#?\s*(\d{1,3})"
_PAIR = re.compile(rf"{_NUM}\s*(?:and|&|to|with|vs|versus|against|,)\s*(?:{_NUM}|(\d{{1,3}}))")
_ONE = re.compile(_NUM)
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (KEYWORDS_REMOVED, re.compile(r"\bkeywords?\b.*\b(?:removed|dropped|lost|deleted|taken out|gone)\b|\b(?:removed|dropped)\b.*\bkeywords?\b")),
    (KEYWORDS_ADDED, re.compile(r"\bkeywords?\b.*\b(?:added|new|introduced)\b|\b(?:added|new)\b.*\bkeywords?\b|\bkeywords? did i add\b")),
    (AUDIT_CHANGES, re.compile(r"\baudit\b.*\b(?:changes?|changed|differences?|history|results?)\b|\b(?:changes?|differences?)\b.*\baudit\b")),
    (CLAIMS, re.compile(r"\bclaims?\b.*\b(?:introduced|added|new|made)\b|\b(?:introduced|new)\b.*\bclaims?\b")),
    (WHY_REVISED, re.compile(r"\bwhy\b.*\b(?:revised|changed|edited|rewritten|updated)\b|\bwhy was\b.*\blisting\b")),
    (IMPROVE, re.compile(r"\b(?:what|how)\b.*\b(?:improve|optimi[sz]e|fix|better)\b|\bwhat should i (?:change|do) next\b")),
    (APPROVED, re.compile(r"\bwhich\b.*\b(?:version|listing)\b.*\bapproved\b|\bapproved for use\b.*\bversion\b|\bis my (?:latest|current) (?:listing|version) approved\b")),
    (COMPARE, re.compile(r"\bcompar(?:e|ing|ison)\b|\bdifferences? between\b|\bold(?:er)? (?:and|vs|versus|with) (?:the )?new(?:er)?\b|\bprevious\b.*\b(?:and|with|vs|versus|to)\b.*\b(?:latest|newest|current|new)\b")),
    (CHANGES, re.compile(r"\bwhat\b.*\bchanged\b|\bwhat did i (?:change|edit)\b|\b(?:listing|version) changes\b|\bchanges (?:to|in|made to) (?:my )?(?:\w+ )?listing\b|\blisting changes\b")),
    (HISTORY, re.compile(r"\b(?:listing|version|revision) history\b|\bhistory of my\b|\b(?:all|every|list) (?:of )?(?:my )?(?:\w+ )?(?:listing )?versions\b|\bshow (?:me )?(?:my )?(?:\w+ )?versions\b")),
    (VERSION, re.compile(r"\b(?:previous|last|earlier|older|original|first|latest|newest|current)\b.*\b(?:listing|version)\b|\b(?:listing|version)\b.*\b(?:before|previous)\b|\bversion\s*#?\s*\d+\b|\bshow\b.*\bmy\b.*\blisting\b")),
)
_WORDS = frozenset("""a an the of for to in on at by and or with vs versus between from since is are was were be been am do does did i me my our we you your it this that these those there their any all every each
show give tell list see display get open view pull fetch find please can could would should what whats which why how who when where have has had
latest newest recent current previous last earlier older old new newer original first second third next
listing listings version versions revision revisions revised history compare comparing comparison changed change changes changing difference differences
keyword keywords added add removed remove dropped introduced claim claims audit audits improve improvement optimise optimize optimization fix better approved approval use used marketplace
amazon flipkart meesho listed product item
edit edited edits rewrite rewritten update updated one ones""".split())


@dataclass(frozen=True, slots=True)
class Ask:
    kind: str
    product_hint: str | None
    marketplace: str | None
    versions: tuple[int, ...]   # explicit numbers the seller named (0, 1 or 2)
    relative: str | None        # "PREVIOUS", "LATEST", "ORIGINAL", "OLD_NEW" when named by position, else None


def _relative(t: str) -> str | None:
    if re.search(r"\boriginal\b|\bfirst (?:listing|version)\b|\bversion\s*1\b", t) and not _PAIR.search(t):
        return "ORIGINAL"
    if re.search(r"\bprevious\b.*\b(?:latest|newest|current|new)\b|\b(?:latest|newest|current|new)\b.*\bprevious\b", t):
        return "PREVIOUS_LATEST"
    if re.search(r"\bold(?:er)? (?:and|vs|versus|with) (?:the )?new(?:er)?\b", t):
        return "OLD_NEW"
    if re.search(r"\b(?:previous|last|earlier|older|prior)\b", t):
        return "PREVIOUS"
    if re.search(r"\b(?:latest|newest|current|recent)\b", t):
        return "LATEST"
    return None


def hint(t: str) -> str | None:
    words = [w for w in re.findall(r"[^\W\d_][\w-]*", t, flags=re.UNICODE) if w not in _WORDS and not re.fullmatch(r"v?\d+", w)]
    return " ".join(words) if words else None


def parse(text: str, *, in_context: bool = False) -> Ask | None:
    """The request, or None when the message is not about listing history. `in_context` = the last thing in this conversation was a history answer, so short follow-ups such as
    "which keywords were removed?" and "what should I improve next?" belong to it."""
    t = _FOLD(text or "")
    if not t or len(t) > 400:
        return None
    named = bool(_LISTING.search(t)) or ("audit" in t and "listing" in t)
    kind = next((k for k, rx in _RULES if rx.search(t)), None)
    if kind is None:
        return None
    if kind in (KEYWORDS_ADDED, KEYWORDS_REMOVED, AUDIT_CHANGES, CLAIMS, IMPROVE, WHY_REVISED, APPROVED) and not (named or in_context):
        return None
    if kind in (COMPARE, CHANGES, HISTORY, VERSION) and not named:
        return None
    if kind == VERSION and not (_ONE.search(t) or re.search(r"\b(?:previous|last|earlier|older|original|first|latest|newest|current)\b", t) or "show" in t):
        return None
    pair, one = _PAIR.search(t), _ONE.findall(t)
    versions: tuple[int, ...] = ()
    if pair:
        versions = tuple(int(g) for g in pair.groups() if g)[:2]
    elif one:
        versions = tuple(int(x) for x in one)[:2]
    mp = next((v for k, v in MARKETPLACES.items() if re.search(rf"\b{k}\b", t)), None)
    rest = _ONE.sub(" ", t)
    return Ask(kind, hint(rest), mp, versions, None if versions else _relative(t))
