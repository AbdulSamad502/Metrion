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
from slim_cmo.textnorm import skeleton


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
    return tuple(findings)


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
    return tuple(NarrationFinding("DEMAND_CLAIM", rule) for rule, rx in _TREND_BANNED if rx.search(folded))
