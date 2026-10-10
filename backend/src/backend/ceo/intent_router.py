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
    kind: str = "ACTION"  # a decision playbook is routed the same way (spec 6.36)
    addons: tuple[str, ...] = ()  # need keys the matching request also asks for (spec agent-needs 5.3)


def _rx(p: str) -> re.Pattern[str]:
    return re.compile(p, re.IGNORECASE)


# Business Q&A (spec agent-needs-and-shared-knowledge.md section 7.2): a plain question about the seller's own saved results routes to its QUESTION TYPE
# (`question_types`), a closed id the Business State read expands to a fixed list of entries. These come FIRST because their wording ("what product ideas
# did you FIND", "what titles did we WRITE") would otherwise match the verbs of the work rules below and start a new, possibly metered, run. They are question
# phrasings about what is already saved (past tense, "my ...", "where am I ..."); a request to DO the work still falls through to the rules below.
_NOT_A_WHY = r"^(?!.*\b(?:why|drop|dropped|fall|fell|declin\w*|decreas\w*|increas\w*|improv\w*|compar\w*)\b)"
STATE_RULES: tuple[Rule, ...] = (
    Rule("QT_PROFIT_BY_PERIOD", "CFO", _rx(
        _NOT_A_WHY + r".*(?:\b(?:what|how much)\b.*\b(?:profit|revenue|earnings|income)\b|\b(?:my|our) (?:profit|revenue|earnings|income)\b|\bhow much (?:did i|have i|did we) (?:make|made|earn|earned)\b)"), "BUSINESS_STATE"),
    Rule("QT_LEAKS", "CFO", _rx(
        r"\bwhere (?:am i|are we) (?:losing|leaking|bleeding)\b|\b(?:losing|leaking) money\b|\b(?:my|our|open) (?:leaks?|leak findings?)\b|\bwhat(?:'s| is| are) (?:my )?leaks?\b"), "BUSINESS_STATE"),
    Rule("QT_DATA_GAPS", "CFO", _rx(
        r"\bwhat (?:data|inputs?|information|reports?|details?) (?:are you|is|do you) (?:still )?(?:missing|need|needed|required)\b|\bwhat (?:are you|do you) (?:still )?(?:missing|need)\b|\bwhat(?:'s| is) missing\b|\bdata gaps?\b"), "BUSINESS_STATE"),
    Rule("QT_COMPETITORS_PRICES", "CI", _rx(
        r"^(?!.*\bmargin\b).*(?:\bwhat(?:'s| is| are)? (?:my |our |the )?competitors?\b.*\b(?:charg\w*|pric\w*|sell\w* (?:at|for))\b|\bcompetitors?'? prices?\b|\bhow much (?:are|is|do) (?:my |our |the )?competitors?\b.*\b(?:charg\w*|sell\w*)\b)"), "BUSINESS_STATE"),
    Rule("QT_PRODUCT_IDEAS", "PI", _rx(
        r"\bwhat (?:product )?(?:ideas?|products?)\b.*\b(?:did you|have you|you) (?:find|found|list|listed|come up with)\b|\bproduct ideas? (?:you|we) (?:found|listed|have)\b|\bwhat did (?:you|the research|product intelligence) (?:find|found)\b"), "BUSINESS_STATE"),
    Rule("QT_LISTING_CONTENT", "CMO", _rx(
        r"\bwhat (?:titles?|descriptions?|hashtags?|keywords?|listing (?:content|copy)|content)\b.*\b(?:did|have) (?:we|you|i)\b.*\b(?:write|wrote|written|generat\w+|made|create\w*)\b|\b(?:titles?|descriptions?|hashtags?) (?:we|you) (?:wrote|made|generated|created)\b"), "BUSINESS_STATE"),
    Rule("QT_GOALS", "CFO", _rx(r"\bwhat(?:'s| is| are) (?:my|our) (?:goals?|targets?|target margin)\b|\bwhat (?:goal|target) (?:did i|have i|did we) (?:set|give|gave)\b"), "BUSINESS_STATE"),
    Rule("QT_AGENT_FINDINGS", "CFO", _rx(
        r"\bwhat (?:has|have|did) (?:each|every|the|all)(?: of the)? (?:agents?|specialists?)\b.*\b(?:found|find|report\w*)\b|\bwhat (?:has|have) (?:the )?agents? found\b"), "BUSINESS_STATE"),
    Rule("QT_SELLER_FACTS", "CFO", _rx(
        r"\bwhat do you (?:know|remember) about (?:my|our) (?:business|store|brand|company|shop)\b|\bwhat have i told you\b|\bwhat do you know about me\b"), "BUSINESS_STATE"),
    # The seller's own operational data that no saved result covers: answered "not stored yet", never from general knowledge.
    Rule("QT_NOT_STORED", "CFO", _rx(
        r"\b(?:my|our) (?:inventory|stock levels?|ad spend|advertising spend|customers?|order count|sales volume|best[- ]?selling (?:sku|product)s?)\b|\bhow (?:much|many) (?:stock|inventory|orders?|units|customers?)\b.*\b(?:do i|have i|did i|do we|have we|did we)\b"), "BUSINESS_STATE"),
)

# Ordered: the first match wins. Each pattern needs a clear verb or noun for the work, not just a keyword anywhere.
RULES: tuple[Rule, ...] = STATE_RULES + (
    Rule("cmo.generate_description", "CMO", _rx(r"(?=.*\bdescriptions?\b)(?=.*\bgst\b)(?=.*\b(?:with|along|also|and|plus|together)\b)"), "ACTION", ("GST_RATE_FOR_PRODUCT",)),
    Rule("gst_lookup", "CFO", _rx(r"\bgst\b.*\b(?:rate|percent|percentage|%|slab|apply|applies|applicable|charge)\b|\b(?:rate|percent|percentage|slab)\b.*\bgst\b|\bgst (?:on|for|of)\b")),
    Rule("NEW_PRODUCT_DECISION", "CFO", _rx(r"\bworth (?:stocking|buying|importing|selling)\b|\bshould i (?:stock|buy|import|order)\b"), "PLAYBOOK"),
    Rule("COMPETITOR_PRICE_IMPACT", "CI", _rx(r"(?=.*\bmargin\b)(?:.*\b(?:at|match|matched|matching|beat|undercut)\b.*\bprice\b|.*\b(?:is|are|dropped|cut|lowered)\b.*\b(?:at|to)\s*(?:₹|rs\.?)?\s*\d)"), "PLAYBOOK"),
    Rule("cmo.generate_hashtags", "CMO", _rx(r"\bhash\s?tags?\b")),
    Rule("cmo.generate_title_sets", "CMO", _rx(rf"\b{_WRITE}\b.*\b(?:listing |product |amazon |flipkart |meesho )?titles?\b|\btitles? (?:options?|ideas?|for)\b")),
    Rule("cmo.generate_description", "CMO", _rx(rf"\b{_WRITE}\b.*\b(?:product |listing )?descriptions?\b")),
    Rule("cmo.generate_keywords", "CMO", _rx(rf"\b{_WRITE}\b.*\b(?:search |seo )?keywords?\b|\bkeywords? (?:for|ideas?)\b")),
    Rule("cmo.market_trends", "CMO", _rx(r"\b(?:market|niche|category|marketplace) trends?\b|\btrend (?:report|research|analysis)\b|\bwhat(?:'s| is) (?:happening|trending|new) in (?:my|the) (?:market|niche|category)\b")),
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


_ADDON_TAIL = re.compile(r"\s+(?:along\s+|together\s+)?(?:with|and|plus|also)\b.*$", re.IGNORECASE)
_GST_PRODUCT_AFTER = re.compile(r"\bgst\b.*?\b(?:on|for|of|to|in)\s+(?:my\s+|the\s+|a\s+|an\s+|our\s+)?(?P<p>[\w][\w \-']{1,80}?)(?=\s+(?:is|are|apply|applies|be)\b|[?.!,]|$)", re.IGNORECASE)
_GST_PRODUCT_BEFORE = re.compile(r"^\W*(?:ok\s+|so\s+)?(?P<p>[\w][\w \-']{1,60}?)\s+gst\b", re.IGNORECASE)
_REQUEST_WORDS = frozenset({"tell", "give", "show", "what", "which", "how", "can", "could", "please", "ok", "okay", "so", "and", "also", "now", "is", "are", "does", "do", "whats", "what's"})
_NOT_A_PRODUCT = frozenset({"this", "that", "it", "these", "those", "them", "this product", "that product", "the product", "my product", "my products", "products"})


def _product_text(raw: str | None) -> str | None:
    """A product named in the message, or None when it is a pronoun, a number or a rate (then the CEO asks which product instead of guessing)."""
    v = " ".join((raw or "").split()).strip(" .,'\"")
    if not v or v.casefold() in _NOT_A_PRODUCT or re.search(r"\d|%", v) or len(v.split()) > 8 or v.split()[0].casefold() in _REQUEST_WORDS:
        return None
    return v


_RIVAL_PRICE_OF = re.compile(r"\b(?:at|if i match(?:ed)?|matching|match|beat|undercut)\s+(?:the\s+)?(?P<c>[\w][\w \-']{1,40}?)(?:'s|\u2019s|s')\s+(?:new\s+|current\s+)?price", re.IGNORECASE)
_RIVAL_AT_PRICE = re.compile(r"^\W*(?:so\s+|ok\s+)?(?P<c>[\w][\w \-']{1,40}?)\s+(?:is|are|dropped|cut|lowered)\b.*?\b(?:at|to)\s*(?P<p>(?:₹|rs\.?)?\s*\d+(?:,\d+)*(?:\.\d+)?)", re.IGNORECASE)
_STOCK_BEFORE = re.compile(r"^\W*(?:is|are)\s+(?:the\s+|my\s+|a\s+)?(?P<p>[\w][\w \-']{1,60}?)\s+worth\s+(?:stocking|buying|importing|selling)", re.IGNORECASE)
_STOCK_AFTER = re.compile(r"\bshould i (?:stock|buy|import|order)\s+(?:the\s+|some\s+|a\s+|an\s+|my\s+)?(?P<p>[\w][\w \-']{1,60}?)(?=\s*(?:[?.!,]|or not\b|from\b|$))", re.IGNORECASE)


def _slots(rule: Rule, text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if rule.kind == "BUSINESS_STATE":
        return out  # a state read takes no slots: the question type decides what is read
    if rule.key == "COMPETITOR_PRICE_IMPACT":
        m = _RIVAL_PRICE_OF.search(text)
        if m:
            c = _product_text(m.group("c"))
            return {"competitor": c} if c else {}
        m = _RIVAL_AT_PRICE.search(text)
        c = _product_text(m.group("c")) if m else None
        return {"competitor": c, "amount": m.group("p").strip()} if m and c else {}
    if rule.key == "NEW_PRODUCT_DECISION":
        m = _STOCK_BEFORE.search(text) or _STOCK_AFTER.search(text)
        product = _product_text(m.group("p") if m else None)
        return {"product": product} if product else {}
    if rule.key == "gst_lookup":
        m = _GST_PRODUCT_AFTER.search(text) or _GST_PRODUCT_BEFORE.search(text)
        product = _product_text(m.group("p") if m else None)
        return {"product": product} if product else {}
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
        product = _PRODUCT_AFTER_FOR.search(_ADDON_TAIL.sub("", text) if rule.addons else text)  # "... for a steel bottle along with the GST %": the add-on is not part of the product
        if product:
            out["product"] = product.group(1).strip()
    return out


def route(text: str, cat: Catalog) -> Decision | None:
    """A decision when a rule recognises the request, else None (the model decides)."""
    t = " ".join(text.split())
    for rule in RULES:
        if not rule.pattern.search(t):
            continue
        if rule.kind == "PLAYBOOK" and not _slots(rule, t):
            continue  # no product named ("find products worth stocking"): the model decides, nothing is guessed
        item = cat.item(rule.kind, rule.key)
        if item is None:  # the member cannot run it here: say why, do not ask something unrelated
            payload: Mapping[str, object] = {"route": "ADVISORY", "route_key": None, "slots": {}, "needs_agent": rule.agent, "clarify_for": None}
        else:
            payload = {"route": rule.kind, "route_key": rule.key, "slots": _slots(rule, t), "needs_agent": None, "clarify_for": None}
        d = parse_decision(json.dumps(payload), cat)
        extra = {"GST_UNAVAILABLE"} if item is None and rule.key == "gst_lookup" else set()  # the wall for GST is code, never general knowledge
        return Decision(d.parse_ok, d.raw_route, d.raw_key, d.route, d.key, d.slots, d.needs_agent, d.clarify_for, frozenset({*d.flags, "RULE_ROUTED", *extra}),
                        addons=rule.addons if item is not None else ())
    return None
