"""The seller's section-edit sentence (docs/specs/slim-cmo-agent.md section 6.18.7a). Pure parsing, no model, no I/O.

    [For my <product>, ]change <target> [on <marketplace> ]to: <text>

`<target>` is exactly one of `bullet <n>`, `description`, `keywords`, `backend terms`. The title is never editable here (that is the existing re-approval). A message that is not this
sentence is NOT an edit (`NOT_AN_EDIT`): the caller routes it normally and never guesses. A recognised sentence whose content breaks a rule is `REFUSED` with a plain reason and nothing is
saved. The limits are technical parse ceilings, not marketplace rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from slim_cmo.listing import limits

EDIT, NOT_AN_EDIT, REFUSED = "EDIT", "NOT_AN_EDIT", "REFUSED"
MARKETPLACES = {"amazon": "AMAZON", "flipkart": "FLIPKART", "meesho": "MEESHO"}

_SENTENCE = re.compile(
    r"^\s*(?:for\s+my\s+(?P<product>.+?)\s*,\s*)?change\s+(?P<target>bullet\s+(?P<n>\d+)|description|keywords|backend\s+terms|title)\s*"
    r"(?:on\s+(?P<mp>amazon|flipkart|meesho)\s*)?to\s*:(?P<text>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_BAD_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class EditRequest:
    kind: str  # EDIT | NOT_AN_EDIT | REFUSED
    target: str | None = None  # bullet | description | keywords | backend_terms
    bullet_number: int | None = None
    product: str | None = None
    marketplace: str | None = None  # AMAZON | FLIPKART | MESHO, as named by the seller (None = not named)
    text: str | None = None  # bullet / description text
    terms: tuple[str, ...] = ()  # keywords / backend terms
    code: str | None = None  # refusal code
    reason: str | None = None  # plain words for the seller


def _refuse(code: str, reason: str, **kw: object) -> EditRequest:
    return EditRequest(REFUSED, code=code, reason=reason, **kw)  # type: ignore[arg-type]


def parse(message: str) -> EditRequest:
    m = _SENTENCE.match(message or "")
    if m is None:
        return EditRequest(NOT_AN_EDIT)
    raw_target = " ".join(m.group("target").lower().split())
    product = " ".join((m.group("product") or "").split()) or None
    mp = MARKETPLACES.get((m.group("mp") or "").lower())
    text = (m.group("text") or "").strip()
    common: dict[str, object] = {"product": product, "marketplace": mp}

    if raw_target == "title":
        return _refuse("TITLE_NOT_EDITABLE", "To change the title, approve a different title.", **common)
    if _BAD_CONTROL.search(text):
        return _refuse("INVALID_CHARACTERS", "That text contains characters that cannot be saved.", **common)
    if not text:
        return _refuse("EMPTY_TEXT", "There is no text after “to:”.", target=raw_target.split()[0], **common)

    if raw_target.startswith("bullet"):
        n = int(m.group("n"))
        if n < 1:
            return _refuse("BAD_BULLET_NUMBER", "Bullets are numbered from 1.", target="bullet", **common)
        if len(text) > limits.EDIT_BULLET_MAX:
            return _refuse("TOO_LONG", f"A bullet can be at most {limits.EDIT_BULLET_MAX} characters here.", target="bullet", bullet_number=n, **common)
        return EditRequest(EDIT, target="bullet", bullet_number=n, text=text, product=product, marketplace=mp)
    if raw_target == "description":
        if len(text) > limits.EDIT_DESCRIPTION_MAX:
            return _refuse("TOO_LONG", f"A description can be at most {limits.EDIT_DESCRIPTION_MAX} characters here.", target="description", **common)
        return EditRequest(EDIT, target="description", text=text, product=product, marketplace=mp)

    target = "keywords" if raw_target == "keywords" else "backend_terms"
    if target == "backend_terms" and mp is not None and mp != "AMAZON":
        return _refuse("BACKEND_TERMS_AMAZON_ONLY", "Backend search terms exist only for Amazon.", target=target, **common)
    terms = tuple(t.strip() for t in text.split(",") if t.strip())
    if not terms:
        return _refuse("EMPTY_TEXT", "There are no terms after “to:”.", target=target, **common)
    if len(terms) > limits.EDIT_LIST_MAX_TERMS:
        return _refuse("TOO_MANY_TERMS", f"At most {limits.EDIT_LIST_MAX_TERMS} terms can be set at once.", target=target, **common)
    if any(len(t) > limits.EDIT_TERM_MAX for t in terms):
        return _refuse("TERM_TOO_LONG", f"A term can be at most {limits.EDIT_TERM_MAX} characters.", target=target, **common)
    return EditRequest(EDIT, target=target, terms=terms, product=product, marketplace=mp)


_REWRITE_ASK = re.compile(
    r"\b(?:re-?write|redo|rework|reword)\s+(?:the\s+)?(?P<target>bullet(?:\s*point)?\s*(?:#|no\.?|number)?\s*(?P<n>\d{1,2})|description)\b[^.?!]*?"
    r"\b(?:to\s+(?:mention|include|cover|talk\s+about)|(?:so\s+)?(?:that\s+)?(?:it\s+)?mentions?|and\s+mention)\s+(?P<topic>[^.?!]{2,80}?)\s*[.?!]*\s*$",
    re.IGNORECASE,
)


def parse_rewrite_ask(message: str) -> tuple[str, str] | None:
    """("bullet 3" | "description", the topic to mention) from "rewrite bullet 3 to mention wide opening", else None. Pure; it only reads the sentence. Whether the topic is something the
    seller has confirmed, and whether the section exists, is checked later against their saved facts and listing."""
    m = _REWRITE_ASK.search(message or "")
    if m is None:
        return None
    topic = " ".join(m.group("topic").split()).strip(" \"'\u201c\u201d")
    if len(topic) < 2 or _BAD_CONTROL.search(topic):
        return None
    return (f"bullet {int(m.group('n'))}" if m.group("n") else "description"), topic
