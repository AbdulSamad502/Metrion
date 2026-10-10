"""Agent memory rules — spec agent-memory.md.

Private memory per agent and one shared memory. This module is the ONLY writer: a model never writes memory. Capture is deterministic and limited to a short closed list
of things a seller states about their own business; each is saved with the message it came from and acknowledged to the seller in the same answer. Memory is context,
never evidence: it can pre-fill a question or let the CEO say "you told me", and it is never a source of a figure. The shared profile offered to a model contains no money.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from backend.repositories import agent_memory_repo as repo

AGENTS = ("CEO", "CFO", "PI", "CMO", "CI")
SHARED_KINDS = repo.SHARED_KINDS
MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")
MAX_VALUE = 120  # a business name or niche is short; anything longer is not captured (the table allows 500)

_WORD = r"[\w][\w &.'\-]{1,%d}" % (MAX_VALUE - 1)
_NAME = re.compile(rf"\b(?:my|our) (?:business|company|brand|store|shop) (?:name\s*(?:is|=|:)|is called|called)\s*(?P<v>{_WORD}?)\s*(?=[,.;!]|\s+(?:and|but|so|because)\b|$)", re.IGNORECASE)
_NAME2 = re.compile(rf"\b(?:business|company|brand|store|shop) name\s*(?:is|=|:)\s*(?P<v>{_WORD}?)\s*(?=[,.;!]|\s+(?:and|but|so|because)\b|$)", re.IGNORECASE)
_NICHE = re.compile(rf"\b(?:my|our) (?:niche|nich|category)\s*(?:is|=|:)\s*(?P<v>{_WORD}?)\s*(?=[,.;!]|\s+(?:and|but|so|because|on)\b|$)", re.IGNORECASE)
_SELLS_ON = re.compile(r"\b(?:i|we)\s+(?:only |mostly |mainly )?sell\s+(?:mostly |mainly )?(?:only )?on\s+(?P<v>[^.;!?\n]{3,80})", re.IGNORECASE)
_NAME_Q = re.compile(r"\bmy (?:business|company|brand|store|shop) name\b|\bname of my (?:business|company|brand|store|shop)\b", re.IGNORECASE)
_NICHE_Q = re.compile(r"\bwhat(?:'s| is)? my (?:niche|category)\b|\bwhat (?:niche|category) (?:am i|do i)\b", re.IGNORECASE)
_SELLS_Q = re.compile(r"\bwhere do i sell\b|\bwhich marketplaces? do i sell\b|\bwhat marketplaces? do i sell\b", re.IGNORECASE)
_ASKING = re.compile(r"^\W*(?:what|whats|what's|which|where|do you (?:know|remember)|tell me|can you (?:tell|remind)|remind me)\b", re.IGNORECASE)
_STOP_VALUES = frozenset({"what", "which", "this", "that", "it", "none", "unknown", "n/a", "na", "not sure", "yes", "no", "ok", "okay"})
_BAD_CHARS = re.compile(r"[<>{}\[\]\\`$]")


@dataclass(frozen=True, slots=True)
class Candidate:
    kind: str
    key: str
    value: str


def _clean(raw: str) -> str | None:
    v = " ".join(raw.split()).strip(" .,'\"-")
    if not (2 <= len(v) <= MAX_VALUE) or v.casefold() in _STOP_VALUES or _BAD_CHARS.search(v):
        return None
    return v


def extract(text: str) -> list[Candidate]:
    """What the seller stated about their own business in this message, from the closed list. A question is never a statement."""
    if text.rstrip().endswith("?") or _ASKING.match(text):
        return []
    out: list[Candidate] = []
    for rx, kind, key in ((_NAME, "BUSINESS_NAME", "business_name"), (_NAME2, "BUSINESS_NAME", "business_name"), (_NICHE, "NICHE", "niche")):
        m = rx.search(text)
        v = _clean(m.group("v")) if m else None
        if v and not any(c.key == key for c in out):
            out.append(Candidate(kind, key, v))
    m = _SELLS_ON.search(text)
    if m:
        found = [mp for mp in MARKETPLACES if mp in m.group("v").upper()]
        if found:
            out.append(Candidate("MARKETPLACES", "marketplaces", ", ".join(found)))
    return out


# ------------------------------------------------------------------------------------------------ writes
def _set(tenant: UUID, *, scope: str, agent: str, kind: str, key: str, value: str, basis: str, source_ref: Mapping[str, Any] | None, created_by: UUID | None) -> bool:
    """Save a value unless it is already the active one; a different value supersedes the old one. Returns whether anything was written."""
    current = repo.list_active(tenant, scope=scope, agent=agent, kind=kind, key=key, limit=1)
    if current and current[0]["value"] == value:
        return False
    repo.insert(tenant, scope=scope, agent=agent, kind=kind, key=key, value=value, basis=basis, source_ref=source_ref, created_by=created_by,
                supersedes_id=current[0]["id"] if current else None)
    return True


def promote(tenant: UUID, *, agent: str, kind: str, key: str, value: str, basis: str, source_ref: Mapping[str, Any], created_by: UUID | None) -> bool:
    """The ONLY path into shared memory: a shared kind, a seller-stated or confirmed basis and a source. (The database enforces the same, so this is not the only guard.)"""
    if agent not in AGENTS or kind not in SHARED_KINDS or basis not in ("SELLER_STATED", "CONFIRMED_DECISION"):
        raise ValueError("not eligible for shared memory")
    return _set(tenant, scope="SHARED", agent=agent, kind=kind, key=key, value=value, basis=basis, source_ref=source_ref, created_by=created_by)


def note(tenant: UUID, *, agent: str, key: str, value: str, basis: str, source_ref: Mapping[str, Any] | None, created_by: UUID | None) -> bool:
    """An agent's own private memory (kind NOTE)."""
    if agent not in AGENTS:
        raise ValueError("unknown agent")
    return _set(tenant, scope="PRIVATE", agent=agent, kind="NOTE", key=key, value=value[:500], basis=basis, source_ref=source_ref, created_by=created_by)


def remember_from_message(tenant: UUID, user_id: UUID | None, message_id: UUID, text: str) -> list[str]:
    """Capture what the seller just stated; returns the acknowledgement lines to append to the answer (written by code, quoting the seller's own words)."""
    acks: list[str] = []
    for c in extract(text):
        if promote(tenant, agent="CEO", kind=c.kind, key=c.key, value=c.value, basis="SELLER_STATED", source_ref={"message_id": str(message_id)}, created_by=user_id):
            label = {"business_name": "your business name", "niche": "your niche", "marketplaces": "where you sell"}[c.key]
            acks.append(f"I'll remember {label}: {c.value}. You can change or remove it under “What I remember”.")
    return acks


def forget(tenant: UUID, memory_id: UUID, user_id: UUID | None) -> bool:
    """Forget one active item: a FORGOTTEN row supersedes it. A foreign, unknown or already-superseded id is simply not found."""
    row = repo.get(tenant, memory_id)
    if row is None or row["status"] != "ACTIVE" or not any(str(r["id"]) == str(memory_id) for r in repo.list_active(tenant, kind=row["kind"], key=row["key"], scope=row["scope"], agent=row["agent_code"])):
        return False
    repo.insert(tenant, scope=row["scope"], agent=row["agent_code"], kind=row["kind"], key=row["key"], value="(forgotten)", basis=row["basis"],
                source_ref={"forgot": str(memory_id)} if row["basis"] != "AGENT_NOTE" else None, created_by=user_id, supersedes_id=memory_id, status="FORGOTTEN")
    return True


# ------------------------------------------------------------------------------------------------ reads
def profile(tenant: UUID) -> dict[str, dict[str, Any]]:
    """The active shared profile by key: {key: {value, created_at, id}}."""
    return {r["key"]: {"value": r["value"], "created_at": r["created_at"], "id": r["id"]} for r in repo.list_active(tenant, scope="SHARED")}


def context_line(tenant: UUID) -> str | None:
    """One line for the classifier / composer: what the seller told us, as quoted data. Names and niches only; there is no money in shared memory by construction."""
    p = profile(tenant)
    parts = [f"{label}: “{p[k]['value']}”" for k, label in (("business_name", "business name"), ("niche", "niche"), ("marketplaces", "sells on")) if k in p]
    return ("What the seller has told us (quoted, not verified): " + "; ".join(parts) + ".") if parts else None


def answer_profile_question(tenant: UUID, text: str) -> str | None:
    """A direct answer from memory for "what is my business name / niche / where do I sell", or None when the message is not one of those questions."""
    kind = ("business_name", "your business name") if _NAME_Q.search(text) and _ASKING.match(text) else ("niche", "your niche") if _NICHE_Q.search(text) else (
        ("marketplaces", "where you sell") if _SELLS_Q.search(text) else None)
    if kind is None:
        return None
    key, label = kind
    found = profile(tenant).get(key)
    if found is None:
        return f"You have not told me {label} yet. Tell me, for example “my business name is …”, and I will remember it."
    return f"{label[0].upper()}{label[1:]} is {found['value']}. You told me this on {found['created_at'].date().isoformat()}."


_LABELS: Mapping[str, str] = {
    "business_name": "Business name", "niche": "Your niche", "marketplaces": "Where you sell",
    "last_category": "Product Intelligence: last niche you researched", "last_budget_paise": "Product Intelligence: last budget you gave",
    "last_marketplaces": "Product Intelligence: last marketplaces you chose",
}


def describe(row: Mapping[str, Any]) -> dict[str, Any]:
    """One memory item as the seller sees it: a plain label and the value as they gave it (a stored budget is shown as rupees by the same formatter as everywhere)."""
    value = str(row["value"])
    if row["key"] == "last_budget_paise":
        from backend.ceo.figure_format import format_paise

        try:
            value = format_paise(int(value))
        except ValueError:
            pass
    return {
        "id": str(row["id"]), "label": _LABELS.get(str(row["key"]), str(row["key"]).replace("_", " ").capitalize()), "value": value,
        "shared": row["scope"] == "SHARED", "agent": row["agent_code"], "basis": row["basis"], "createdAt": row["created_at"].isoformat(),
    }


def list_for_seller(tenant: UUID) -> list[dict[str, Any]]:
    return [describe(r) for r in repo.list_active(tenant)]


def pi_defaults(tenant: UUID) -> dict[str, str]:
    """What the seller confirmed for their last product research (PI's own private notes): used only to OFFER a choice next time, never filled in silently."""
    return {r["key"]: r["value"] for r in repo.list_active(tenant, scope="PRIVATE", agent="PI", kind="NOTE")}
