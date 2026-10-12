"""Shared findings ledger rules — spec agent-needs-and-shared-knowledge.md section 6 (tier 2 of shared memory).

This module is the ONLY writer of `shared_finding`: a model never writes a finding and an agent cannot choose its own trust label. Text is built by code from a template and
carries no digit; a number lives only in `figure_refs` and is rendered at read time through the provenance gate (not here). Findings are never part of "what the seller told
us" (`memory.profile` / `memory.context_line` never read this table). The database repeats the gate (CHECKs and a trigger), so this is not the only guard.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid as uuidlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from backend.auth.context import AuthContext
from backend.auth.permissions import AGENT_CEO
from backend.ceo.capabilities import NOT_ENTITLED, NOT_PERMITTED, compute_capabilities
from backend.ceo.contract import AgentCode
from backend.ceo.registry import ActionRegistry
from backend.repositories import shared_finding_repo as repo

AGENTS = ("CEO", "CFO", "PI", "CMO", "CI")
KIND_AGENT: Mapping[str, str] = {
    "PRODUCT_IDEA": "PI", "COMPETITOR_CHANGE": "CI", "LEAK_FOUND": "CFO", "MARGIN_ISSUE": "CFO", "DATA_GAP": "CFO", "CONTENT_READY": "CMO", "SELLER_NOTE": "CEO",
}
MAX_TEXT, MAX_SUBJECT, MAX_REFS = 300, 120, 3
DEFAULT_LIMIT, MAX_LIMIT = 100, 200
SOURCE_KINDS = tuple(repo.SOURCE_TABLES)
REF_KINDS = ("ENGINE_RESULT", "ESTIMATE")

# Number words a CHECK cannot cover (the database proves the ASCII-digit case). "one" is left out: it is an ordinary word ("no one", "one of").
_NUMBER_WORDS = re.compile(
    r"\b(?:zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy"
    r"|eighty|ninety|hundred|thousand|lakh|lakhs|crore|crores|million|billion|percent|per cent)\b", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_LABELS = {"SELLER_STATED": "You said", "ENGINE_VERIFIED": "Calculated by the engine"}
_AGENT_NAMES = {"CEO": "the CEO", "CFO": "the CFO", "PI": "Product Intelligence", "CMO": "the CMO", "CI": "Competitor Intelligence"}


class FindingError(ValueError):
    """A finding that breaks a rule is refused, never repaired or stored in a weaker form."""


def trust_label(trust: str, agent: str) -> str:
    """The fixed label text (section 6.5). An AGENT_REPORTED finding is never worded as verified."""
    return _LABELS.get(trust) or f"Reported by {_AGENT_NAMES.get(agent, agent)}, not verified"


# ------------------------------------------------------------------------------------------------ validation
def _clean_text(value: str, limit: int, what: str) -> str:
    v = unicodedata.normalize("NFKC", value or "").strip()
    if not (1 <= len(v) <= limit) or _CONTROL.search(v):
        raise FindingError(f"{what} must be 1 to {limit} characters of plain text")
    return v


def _check_no_number(value: str) -> None:
    if any(unicodedata.category(c) == "Nd" for c in value) or _NUMBER_WORDS.search(value):
        raise FindingError("finding text carries no number: a figure goes in figure_refs")


def _check_ref(ref: Mapping[str, Any], *, kinds: Iterable[str]) -> dict[str, str]:
    kind, ref_id, label = ref.get("kind"), ref.get("id"), ref.get("label")
    if kind not in tuple(kinds) or not isinstance(ref_id, str) or not isinstance(label, str):
        raise FindingError("malformed reference")
    try:
        uuidlib.UUID(ref_id)
    except ValueError:
        raise FindingError("a reference id must be a UUID") from None
    return {"kind": kind, "id": ref_id, "label": _clean_text(label, 60, "figure label")}


def _source(ref: Mapping[str, Any]) -> dict[str, str]:
    s = _check_ref({**ref, "label": "source"}, kinds=SOURCE_KINDS)
    return {"kind": s["kind"], "id": s["id"]}


def dedupe_key_for(agent: str, kind: str, source_ref: Mapping[str, Any], subject: str | None) -> str:
    """Stable key for 'the same finding from the same source' (a repeat is a no-op; a forgotten one stays forgotten)."""
    basis = "|".join((agent, kind, str(source_ref.get("kind")), str(source_ref.get("id")), (subject or "").casefold()))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------------ writes
def record(
    tenant: UUID, *, agent: str, kind: str, text: str, source_ref: Mapping[str, Any], subject: str | None = None, figure_refs: Sequence[Mapping[str, Any]] = (),
    dedupe_key: str | None = None, created_by: UUID | None = None, now: datetime | None = None,
) -> UUID | None:
    """Record one agent finding. Returns its id, or None when this source was already recorded or was forgotten. Raises FindingError for anything that breaks a rule.

    The caller never passes a trust label: ENGINE_VERIFIED is assigned here only when there is at least one figure ref, all are ENGINE_RESULT and every one resolves to a
    metric_result of this tenant now; otherwise a ref-free or ESTIMATE-bearing finding is AGENT_REPORTED. An ENGINE_RESULT that does not resolve is refused."""
    if agent not in AGENTS or KIND_AGENT.get(kind) != agent or kind == "SELLER_NOTE":
        raise FindingError("not a finding this agent may record")
    body = _clean_text(text, MAX_TEXT, "text")
    _check_no_number(body)
    subj = _clean_text(subject, MAX_SUBJECT, "subject") if subject is not None else None
    src = _source(source_ref)
    if len(figure_refs) > MAX_REFS:
        raise FindingError(f"at most {MAX_REFS} figure references")
    refs = [_check_ref(r, kinds=REF_KINDS) for r in figure_refs]
    engine_ids = [r["id"] for r in refs if r["kind"] == "ENGINE_RESULT"]
    if engine_ids and set(engine_ids) != repo.resolve_engine_results(tenant, engine_ids):
        raise FindingError("an ENGINE_RESULT ref does not resolve to an engine result of this tenant")
    trust = "ENGINE_VERIFIED" if refs and len(engine_ids) == len(refs) else "AGENT_REPORTED"
    key = dedupe_key or dedupe_key_for(agent, kind, src, subj)
    if repo.is_forgotten(tenant, key):
        return None  # tombstone: the seller forgot this source
    try:
        return repo.insert(tenant, agent=agent, kind=kind, subject=subj, body=body, trust=trust, source_ref=src, figure_refs=refs, dedupe_key=key, created_by=created_by, now=now)
    except repo.FindingRefError as exc:
        raise FindingError(str(exc)) from None


def _active_target(tenant: UUID, finding_id: UUID, visible_agents: Iterable[str]) -> dict[str, Any] | None:
    row = repo.get(tenant, finding_id)
    if row is None or row["status"] != "ACTIVE" or row["superseded"] or row["agent_code"] not in set(visible_agents):
        return None  # foreign, unknown, already superseded/forgotten, or from an agent this member cannot see: all the same "not found"
    return row


def correct(tenant: UUID, finding_id: UUID, *, text: str, message_id: UUID, visible_agents: Iterable[str], created_by: UUID | None) -> UUID | None:
    """The seller's correction: a SELLER_STATED row (their words, quoted, never a Figure or an engine input) that supersedes the finding. None when not found."""
    body = _clean_text(text, MAX_TEXT, "correction")
    old = _active_target(tenant, finding_id, visible_agents)
    if old is None:
        return None
    return repo.insert(
        tenant, agent="CEO", kind="SELLER_NOTE", subject=old["subject"], body=body, trust="SELLER_STATED", source_ref={"kind": "message", "id": str(message_id)}, figure_refs=[],
        dedupe_key=old["dedupe_key"], created_by=created_by, supersedes_id=finding_id,
    )


def forget(tenant: UUID, finding_id: UUID, *, visible_agents: Iterable[str], created_by: UUID | None) -> bool:
    """Forget one active finding: a FORGOTTEN row supersedes it and its source is never recorded again. Not found (False) for a foreign, unknown or hidden id."""
    old = _active_target(tenant, finding_id, visible_agents)
    if old is None:
        return False
    done = repo.insert(
        tenant, agent=old["agent_code"], kind=old["kind"], subject=old["subject"], body="(forgotten)", trust=old["trust"], source_ref=old["source_ref"], figure_refs=old["figure_refs"],
        dedupe_key=old["dedupe_key"], created_by=created_by, supersedes_id=finding_id, status="FORGOTTEN",
    )
    return done is not None  # False when a simultaneous correction or forget got there first: the finding was not forgotten by this call


# ------------------------------------------------------------------------------------------------ reads
def visible_agents(ctx: AuthContext, registry: ActionRegistry, *, now: datetime) -> frozenset[str]:
    """Agents whose findings this member could see by running that agent directly (D6): the agent's key AND its entitlement. An agent that is merely not attached to a
    conversation still counts (its earlier findings stay visible as history), so every agent is treated as attached. The CEO's own entries need `agent.ceo`."""
    caps = compute_capabilities(ctx, registry, frozenset(a.value for a in AgentCode), now=now)
    seen = {code for code, status in caps.agent_status.items() if status not in (NOT_PERMITTED, NOT_ENTITLED)}
    return frozenset(seen | {"CEO"}) if _can_ceo(ctx) else frozenset(seen)


def _can_ceo(ctx: AuthContext) -> bool:
    from backend.auth.permissions import has_permission

    return ctx.role is not None and has_permission(role=ctx.role, permissions=ctx.permissions, key=AGENT_CEO)


@dataclass(frozen=True, slots=True)
class FindingList:
    items: list[dict[str, Any]]
    hidden: list[dict[str, Any]]  # [{agent, count, message}]: counted, never described, never carrying a figure

    def as_dict(self) -> dict[str, Any]:
        return {"items": self.items, "hidden": self.hidden, "hiddenTotal": sum(h["count"] for h in self.hidden)}


def describe(row: Mapping[str, Any], resolvable: set[str]) -> dict[str, Any]:
    """One finding as the seller sees it. Figures are references only (label, kind, id) with `resolvable` re-checked now; the value is rendered by the provenance gate, not here."""
    refs = [{**r, "resolvable": r["kind"] == "ESTIMATE" or r["id"] in resolvable} for r in row["figure_refs"]]
    return {
        "id": str(row["id"]), "agent": row["agent_code"], "kind": row["kind"], "subject": row["subject"], "text": row["text"], "trust": row["trust"],
        "trustLabel": trust_label(row["trust"], row["agent_code"]), "figureRefs": refs, "sourceRef": row["source_ref"], "createdAt": row["created_at"].isoformat(),
    }


def list_visible(tenant: UUID, visible: Iterable[str], *, limit: int = DEFAULT_LIMIT) -> FindingList:
    """Active findings the member may see, newest first and bounded, plus a count per hidden agent (section 6.3, D6)."""
    allowed = frozenset(visible)
    rows = repo.list_active(tenant, agents=sorted(allowed), limit=max(1, min(limit, MAX_LIMIT)))
    ids = [r_["id"] for row in rows for r_ in row["figure_refs"] if r_["kind"] == "ENGINE_RESULT"]
    resolvable = repo.resolve_engine_results(tenant, ids)
    hidden = [
        {"agent": agent, "count": n, "message": f"{n} finding{'s' if n != 1 else ''} from {_AGENT_NAMES.get(agent, agent)} not shown: no access"}
        for agent, n in sorted(repo.count_active_by_agent(tenant).items()) if agent not in allowed
    ]
    return FindingList([describe(r, resolvable) for r in rows], hidden)
