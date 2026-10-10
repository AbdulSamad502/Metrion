"""Explicit intent-to-action mapping — spec §6.35.

A small, ordered set of plain rules that recognise requests whose meaning is unmistakable ("hashtags for my bottle", "top trending products, my niche is mens shoes").
They run BEFORE the model: they are instant, they are the same every time, and they cannot be talked out of the closed catalog, because the result goes through
`classifier.parse_decision` exactly like a model verdict (a key outside the member's catalog becomes a clarification, never an execution).

The rules choose a route and offer slot TEXT only. Every value is still parsed by the guided input session's own parsers; a rule never supplies a number, never writes
anything, and anything it does not recognise falls through to the model. When the rule's target agent is not in this member's catalog (detached, not on the plan, no
permission) the result is an ADVISORY turn naming the agent, so the seller is told plainly why it cannot run instead of being asked an unrelated question.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from backend.ceo.classifier import Catalog, Decision, parse_decision

_MARKETPLACE = re.compile(r"\b(amazon|flipkart|meesho)\b", re.IGNORECASE)
_WRITE = r"(?:write|give|generate|create|make|suggest|need|want|get|draft|find|show)"


@dataclass(frozen=True, slots=True)
class Rule:
    key: str
    agent: str
    pattern: re.Pattern[str]


def _rx(p: str) -> re.Pattern[str]:
    return re.compile(p, re.IGNORECASE)


# Ordered: the first match wins. Each pattern needs a clear verb or noun for the work, not just a keyword anywhere.
RULES: tuple[Rule, ...] = (
    Rule("cmo.generate_hashtags", "CMO", _rx(r"\bhash\s?tags?\b")),
    Rule("cmo.generate_title_sets", "CMO", _rx(rf"\b{_WRITE}\b.*\b(?:listing |product |amazon |flipkart |meesho )?titles?\b|\btitles? (?:options?|ideas?|for)\b")),
    Rule("cmo.generate_description", "CMO", _rx(rf"\b{_WRITE}\b.*\b(?:product |listing )?descriptions?\b")),
    Rule("cmo.generate_keywords", "CMO", _rx(rf"\b{_WRITE}\b.*\b(?:search |seo )?keywords?\b|\bkeywords? (?:for|ideas?)\b")),
    Rule(
        "pi.discover", "PI",
        _rx(
            # asking to SEE an earlier run (report, status, latest, saved...) is not a request to start a new one
            r"^(?!.*\b(?:report|status|latest|last|previous|saved|earlier)\b).*(?:"
            r"\b(?:trending|top[- ]selling|best[- ]selling|best ?sellers?|winning|hot|top)\b.*\bproducts?\b"
            r"|\bproducts? (?:to|i can|i should) sell\b|\bwhat (?:should|can|do) i sell\b|\bproduct (?:ideas?|research|discovery)\b"
            r"|\b(?:find|discover|suggest|research|recommend)\b.*\b(?:products?|niche)\b|\bniche research\b)"
        ),
    ),
)

_PRODUCT_AFTER_FOR = re.compile(r"\bfor (?:my|the|a|an|our)?\s*([\w][\w \-']{1,80}?)(?=\s+(?:on|in|at)\s+(?:amazon|flipkart|meesho)\b|[.,?!]|$)", re.IGNORECASE)
_NICHE = re.compile(r"\b(?:niche|nich|category|segment)\s*(?:is|:|=|-)?\s*([\w][\w \-']{1,60}?)(?=[.,?!]|\s+(?:on|in|with|under|budget)\b|$)", re.IGNORECASE)
_BUDGET = re.compile(r"(?:under|below|within|upto|up to|budget(?: of| is)?|max(?:imum)?)\s*((?:₹|rs\.?|inr)?\s*[\d,]+(?:\.\d+)?)", re.IGNORECASE)


def _slots(rule: Rule, text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    m = _MARKETPLACE.search(text)
    if m:
        out["marketplace"] = m.group(1)
    if rule.agent == "PI":
        niche = _NICHE.search(text)
        if niche:
            out["product"] = niche.group(1).strip()
        budget = _BUDGET.search(text)
        if budget:
            out["amount"] = budget.group(1).strip()
    else:
        product = _PRODUCT_AFTER_FOR.search(text)
        if product:
            out["product"] = product.group(1).strip()
    return out


def route(text: str, cat: Catalog) -> Decision | None:
    """A decision when a rule recognises the request, else None (the model decides)."""
    t = " ".join(text.split())
    for rule in RULES:
        if not rule.pattern.search(t):
            continue
        item = cat.item("ACTION", rule.key)
        if item is None:  # the member cannot run it here: say why, do not ask something unrelated
            payload: Mapping[str, object] = {"route": "ADVISORY", "route_key": None, "slots": {}, "needs_agent": rule.agent, "clarify_for": None}
        else:
            payload = {"route": "ACTION", "route_key": rule.key, "slots": _slots(rule, t), "needs_agent": None, "clarify_for": None}
        d = parse_decision(json.dumps(payload), cat)
        return Decision(d.parse_ok, d.raw_route, d.raw_key, d.route, d.key, d.slots, d.needs_agent, d.clarify_for, frozenset({*d.flags, "RULE_ROUTED"}))
    return None
