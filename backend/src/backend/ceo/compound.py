"""A message that asks for more than one thing (hardening Fix 1).

The CEO's contract is ONE route per turn. That is not changed here. What is changed is that the rest of the message is never silently dropped: the explicit rules
are applied to each distinct requirement, the first one that can actually run is handled, and a code-written block says what was handled and what was not, and why.

Deterministic and conservative: it only ever splits on an explicit connector ("and also", "then", ";", or "and" followed by a request verb), it only counts a clause as a
requirement when a rule recognises it or it starts with a request verb, and it runs nothing itself. The chosen clause goes through the normal pipeline (the same rules,
the closed catalog, the approval gate, the choke point), so this module cannot make anything run that could not run before. It never calls a model.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from backend.ceo import intent_router
from backend.ceo.classifier import Catalog, Decision

_VERBS = (
    r"write|find|show|give|generate|create|make|suggest|tell|research|compare|summari[sz]e|get|check|list|upload|delete|remove|send|email|post|update|change|set|record|add|run|start|"
    r"plan|draft|analy[sz]e|what|where|how|why|which|who|when"
)
_CONNECTOR = re.compile(rf"\s*(?:;|,?\s*\band also\b|,?\s*\band then\b|,?\s*\bthen\b|,?\s*\bas well as\b|,?\s*\balso\b|,?\s+\band\b(?=\s+(?:{_VERBS})\b))\s*", re.IGNORECASE)
_STARTS_WITH_VERB = re.compile(rf"^\W*(?:please\s+)?(?:{_VERBS})\b", re.IGNORECASE)
_REFERS_BACK = re.compile(
    r"\b(?:for|about|on|of|from|using|with)\s+(?:it|that|them|those|these|this|the (?:top|first|best|last|same) (?:one|result|product|idea)s?)\b|\bthe top one\b|\bbased on (?:that|this|the (?:above|result))\b",
    re.IGNORECASE,
)
MAX_QUOTE = 100

HEADER = "Your message asked for more than one thing, and I handle one request per message. Here is exactly what happened:"

RUNNABLE, APPROVAL, UNAVAILABLE, UNMATCHED = "RUNNABLE", "APPROVAL", "UNAVAILABLE", "UNMATCHED"
_REASON_TEXT = {
    "PENDING": "it was not started. Send it as its own message and I will run it.",
    "DEPENDENT": "it depends on the result of the earlier request, so it was not started.",
    APPROVAL: "it needs an approved plan, which is not available yet. Nothing was run for it.",
    UNAVAILABLE: "that specialist is not available to you here. Nothing was run for it.",
    UNMATCHED: "I could not match it to something I can run from chat. Nothing was run for it.",
}


@dataclass(frozen=True, slots=True)
class Requirement:
    text: str
    connector: str
    decision: Decision | None
    status: str  # RUNNABLE | APPROVAL | UNAVAILABLE | UNMATCHED
    dependent: bool


@dataclass(frozen=True, slots=True)
class CompoundPlan:
    chosen_text: str | None  # the one clause to run through the normal pipeline, or None when nothing can run
    lines: tuple[str, ...]  # the code-written block (header included), appended to the seller-visible answer
    handled: str | None = None
    not_handled: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (clause text, reason code)

    def to_json(self) -> dict[str, object]:
        return {"handled": self.handled, "notHandled": [{"text": t, "reason": r} for t, r in self.not_handled]}


def _quote(text: str) -> str:
    t = " ".join(text.split()).strip(" .?!,;")
    return t if len(t) <= MAX_QUOTE else t[: MAX_QUOTE - 1].rstrip() + "…"


def split_clauses(text: str) -> list[tuple[str, str]]:
    """(connector, clause) pairs in order; the first connector is empty. Empty clauses are dropped."""
    out: list[tuple[str, str]] = []
    pos, connector = 0, ""
    for m in _CONNECTOR.finditer(text):
        clause = text[pos:m.start()].strip()
        if clause:
            out.append((connector, clause))
            connector = m.group(0).strip(" ,").lower()
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        out.append((connector, tail))
    return out


def _status(d: Decision | None, needs_approval: Callable[[Decision], bool]) -> str:
    if d is None:
        return UNMATCHED
    if "GST_UNAVAILABLE" in d.flags or (d.route == "ADVISORY" and d.needs_agent):
        return UNAVAILABLE
    if needs_approval(d):  # the approval gate is consulted by the orchestrator (one of the three places allowed to), never decided here
        return APPROVAL
    return RUNNABLE


def analyse(text: str, cat: Catalog, *, needs_approval: Callable[[Decision], bool]) -> CompoundPlan | None:
    """None when the message holds fewer than two distinct requirements (the normal single-request path is then untouched)."""
    reqs: list[Requirement] = []
    for connector, clause in split_clauses(" ".join(text.split())):
        decision = intent_router.route(clause, cat)
        if decision is None and not _STARTS_WITH_VERB.search(clause):
            continue  # not a request (a statement, a fragment): it is not a requirement of its own
        dependent = bool(reqs) and ("then" in connector or bool(_REFERS_BACK.search(clause)))
        reqs.append(Requirement(clause, connector, decision, _status(decision, needs_approval), dependent))
    if len(reqs) < 2 or not any(r.decision is not None for r in reqs):
        return None  # fewer than two requirements, or none the rules recognise: the model decides the route and this block would claim things it cannot know (documented limitation)

    chosen = next((i for i, r in enumerate(reqs) if r.status == RUNNABLE and not r.dependent), None)
    handled_line = f"• Handled: “{_quote(reqs[chosen].text)}”." if chosen is not None else "• Handled: nothing — none of these could be run from this message."
    lines: list[str] = [HEADER, handled_line]
    not_handled: list[tuple[str, str]] = []
    for i, r in enumerate(reqs):
        if i == chosen:
            continue
        code = r.status if r.status != RUNNABLE else ("DEPENDENT" if r.dependent else "PENDING")
        not_handled.append((_quote(r.text), code))
        lines.append(f"• Not handled: “{_quote(r.text)}” — {_REASON_TEXT[code]}")
    return CompoundPlan(
        chosen_text=reqs[chosen].text if chosen is not None else None, lines=tuple(lines),
        handled=_quote(reqs[chosen].text) if chosen is not None else None, not_handled=tuple(not_handled),
    )
