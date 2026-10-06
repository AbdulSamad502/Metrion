"""Deterministic narration-safety checks for CMO output (spec §7, evals 1-6, CLAUDE.md 'LLM evals').

Modelled on `product_intelligence.reasoning.narration_safety` (no dependency on it - each agent
owns its own Brain-3 call sites). These are the mechanical checks that run on every generated
string; the model-in-the-loop eval suite (P10) tests the generators against the same rules.

Two surfaces:

* `check_copy_prose` - listing copy. Forbidden categories (price, tax, demand claims, unsupported
  regulated claims, contact details), numbers that appear in no input, and the VALUE of any
  attribute that is not claim-eligible (an ESTIMATED weight, an unverified image hint).
* `check_trend_prose` - trend findings and interpretation. Attention must never be written as
  demand: "selling well", "high demand", "bestseller", "trending" stated as a fact,
  "popular", profitability promises, "will sell". PI bans the same family for the same reason
  (`product-intelligence-agent.md` §0a). Tax words are NOT banned here - news about a GST
  change is legitimate - but numeric restatement is handled separately by `trends.numeric`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from slim_cmo.claims import (
    Attribute,
    EligibilityReason,
    allowed_context_text,
    find_ineligible_values_in_text,
    find_unsupported_numbers,
)
from slim_cmo.forbidden import scan_forbidden
from slim_cmo.textnorm import skeleton, squash_spaced_characters


@dataclass(frozen=True, slots=True)
class NarrationFinding:
    kind: str  # FORBIDDEN | UNSUPPORTED_NUMBER | INELIGIBLE_ATTRIBUTE | DEMAND_CLAIM
    rule: str  # rule id / attribute name / number token - never free seller text


def check_copy_prose(
    text: str,
    *,
    eligible: Sequence[Attribute],
    ineligible: Sequence[tuple[Attribute, EligibilityReason]] = (),
    extra_allowed_text: Sequence[str] = (),
) -> tuple[NarrationFinding, ...]:
    """`extra_allowed_text` is whatever else the output is entitled to say: the approved title,
    the seller's own product description fields."""
    allowed = allowed_context_text(eligible, *extra_allowed_text)
    findings: list[NarrationFinding] = []
    for f in scan_forbidden(text, allowed_context=allowed):
        findings.append(NarrationFinding("FORBIDDEN", f"{f.category.value}:{f.rule}"))
    for number in find_unsupported_numbers(text, [allowed]):
        findings.append(NarrationFinding("UNSUPPORTED_NUMBER", number))
    for name in find_ineligible_values_in_text(text, ineligible, allowed_context=allowed):
        findings.append(NarrationFinding("INELIGIBLE_ATTRIBUTE", name))
    for rule in find_unsupported_claims(text, allowed):
        findings.append(NarrationFinding("UNSUPPORTED_CLAIM", rule))
    return tuple(findings)


def _c(pattern: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])")


# Plain-language performance / feature / contents claims a model tends to add. A claim is allowed only when the seller's own facts (or the
# approved title) already say the same thing: (rule, claim in the output, wording that would support it in the facts). Deterministic,
# no model. Deliberately narrow - ordinary descriptive wording ("durable", "stylish") is not a factual claim and is not touched.
_CLAIMS: tuple[tuple[str, re.Pattern[str], re.Pattern[str]], ...] = (
    ("duration", _c(r"(?:for|up\s+to|over|lasts?)\s+(?:\w+\s+)?(?:hours|days|years)|all[\s-]day|long[\s-]lasting|lasts?\s+long|extended\s+periods"), _c(r"hours?|days?|years?|long[\s-]lasting|all[\s-]day|durab\w+|warranty")),
    ("temperature", _c(r"(?:keeps?|keeping|stays?|maintains?|helps?\s+maintain)\s+(?:\w+\s+){0,5}(?:cold|cool|hot|warm|chilled|temperature)|(?:cold|hot)\s+for"), _c(r"cold|cool|hot|warm|thermal|temperature|chill")),
    ("energy", _c(r"efficien\w+|energy[\s-]?(?:efficient|saving)|power[\s-]?sav\w*|low[\s-]power|(?:reduces?|saves?|lower)\s+(?:\w+\s+)?(?:power|energy|electricity)|consum\w*\s+less"), _c(r"energy|efficien\w*|power[\s-]?sav\w*|watt\w*")),
    ("resistance", _c(r"leak[\s-]?proof|spill[\s-]?proof|water[\s-]?proof|water[\s-]?resistant|(?:rust|scratch|shock|fade|stain|crack)[\s-]?(?:proof|resistant|free)|unbreakable|fire[\s-]?proof"), _c(r"proof|resistan\w*|unbreakable|rust|scratch|leak|spill")),
    ("safety_grade", _c(r"bpa[\s-]?free|non[\s-]?toxic|food[\s-]?(?:grade|safe)|hypoallergenic|skin[\s-]?(?:friendly|safe)|eco[\s-]?friendly|odou?r[\s-]?free|(?:dishwasher|microwave)[\s-]?safe|machine[\s-]?wash\w*"), _c(r"bpa|toxic|food|allergen\w*|skin|eco|odou?r|dishwasher|microwave|wash\w*")),
    ("feature", _c(r"rechargeable|cordless|wireless|dimmable|foldable|adjustable|portab\w+|flicker[\s-]?free|anti[\s-]?glare|eye[\s-]?(?:care|friendly|protection)|touch[\s-]?control\w*|compact|light[\s-]?weight|plug[\s-]?and[\s-]?play|space[\s-]?saving|heavy[\s-]?duty|ultra[\s-]?(?:thin|light)"), _c(r"compact|light\w*|plug|space|heavy|thin|rechargeable|battery|cordless|wireless|dimm\w*|fold\w*|adjust\w*|portab\w+|flicker|glare|eye|touch")),
)
_INCLUDES_RE = _c(r"(?:package\s+)?(?:includes?|including|comes\s+with|contains?|packed\s+with|along\s+with)\s+([^.;:!?\n]{1,80})")
_FILLER = frozenset("with that this from your their these those also have been will each both into over only more than very suitable setup ideal perfect great overall everything various several multiple items one two three four five six seven eight nine twelve dozen pair couple".split())
_ADJ_ADV = re.compile(r"(?:able|ible|ed|ing|ly|ful|ous)$")


def find_unsupported_claims(text: str, allowed: str) -> tuple[str, ...]:
    """Rule ids of claims in `text` that the seller's facts do not support. Never returns model text."""
    out: list[str] = []
    t, a = skeleton(text), skeleton(allowed)
    for rule, claim, support in _CLAIMS:
        if claim.search(t) and not support.search(a):
            out.append(rule)
    for m in _INCLUDES_RE.finditer(t):  # "includes X": each content word of X must already be in the facts
        words = [w for w in re.findall(r"[a-z]{4,}", m.group(1)) if w not in _FILLER and not _ADJ_ADV.search(w)]
        if any(w.rstrip("s") not in a for w in words):
            out.append("contents")
            break
    return tuple(out)


def _w(pattern: str) -> str:
    return rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])"


_TREND_BANNED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (rule, re.compile(rx))
    for rule, rx in [
        ("selling_claim", _w(r"sell(?:s|ing)\s+(?:well|fast|like|out)|sold\s+out|flying\s+off")),
        ("demand_claim", _w(r"(?:in|high|huge|strong|proven|massive|rising|growing|surging)\s+demand|demand\s+(?:is|has\s+been)\s+(?:strong|high|growing|rising)")),
        ("bestseller", _w(r"best[\s-]?sell(?:er|ers|ing)|top[\s-]?sell(?:er|ers|ing)|hot\s+sell(?:er|ing)")),
        ("trending_as_fact", _w(r"trending|trends\s+now")),
        ("popularity", _w(r"popular|most\s+popular|everyone(?:'s|\s+is)\s+buying|must[\s-]have|craze")),
        ("profit_promise", _w(r"profitable|lucrative|guaranteed\s+(?:profit|returns?|sales)|easy\s+money|high[\s-]margin|money[\s-]?maker")),
        ("outcome_promise", _w(r"will\s+(?:sell|succeed|work|boom|explode)|sure[\s-]?(?:shot|fire)|can'?t\s+fail|proven\s+to")),
        ("proof_claim", _w(r"proves?\s+(?:demand|that)|proof\s+of\s+(?:demand|sales)|confirms?\s+demand")),
    ]
)


def check_trend_prose(text: str) -> tuple[NarrationFinding, ...]:
    """Attention-versus-demand wording. Returns one finding per banned rule that matches."""
    folded = skeleton(text)
    variants = (folded, squash_spaced_characters(folded))  # 't r e n d i n g' must not slip past the word-boundary match
    return tuple(NarrationFinding("DEMAND_CLAIM", rule) for rule, rx in _TREND_BANNED if any(rx.search(v) for v in variants))
