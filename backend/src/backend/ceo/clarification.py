"""Clarification decision cards (spec §6.32, 2026-10-10).

When the CEO must ask, and there are REAL candidates to choose from, the question carries a card: the recommended option first, up to two alternatives,
then "Other" (the seller types it). Everything here is built by CODE from the caller's own data; the model writes nothing in a card.

* Exactly four options when at least three real candidates exist; otherwise the real ones plus "Other". A filler option is never invented, and with no real
  candidate there is no card (a plain question).
* The recommended option comes from a stated rule, shown to the seller as `reason`: a competitor, the one with the most recent usable capture; a period, the
  latest persisted period that has results. It is a suggestion, never a default: nothing runs until the seller chooses.
* A card stores the PENDING intent (route, key, the slots already understood), so choosing an option, or typing "Other", resumes it through the existing
  `UI_ACTION` path with no model call and the same closed-catalog, slot and permission checks.
"""

from __future__ import annotations

import calendar
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any
from uuid import UUID

from backend.ceo import business_state
from backend.services import ceo_reads

MAX_REAL_OPTIONS = 3  # recommended + two alternatives
CARD_VERSION = 1

# the slots a card can offer real candidates for
CARD_SLOTS = ("competitor", "period", "form")

# the decision playbooks that run only from a form (spec 6.33); a card offers to open that form
FORM_LABELS = {"COMPETITOR_PRICE_IMPACT": "Open the price-impact form", "NEW_PRODUCT_DECISION": "Open the new-product form"}


def pending_intent(route: str, key: str | None, slots: Mapping[str, str], refs: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {"route": route, "key": key, "slots": dict(slots), "refs": dict(refs or {})}


def _option(index: int, key: str, label: str, value: str, reason: str, refs: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {
        "key": key, "label": label, "kind": "RECOMMENDED" if index == 0 else "ALTERNATIVE", "value": value, "reason": reason, "refs": dict(refs or {}),
    }


def _assemble(kind: str, slot: str, pending: Mapping[str, Any], real: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    if not real:
        return None  # nothing real to offer: a plain question, never a card of fillers
    options = [*real[:MAX_REAL_OPTIONS], {"key": "other", "label": "Other", "kind": "OTHER", "value": None, "reason": "Type it in your own words", "refs": {}}]
    return {"version": CARD_VERSION, "kind": kind, "slot": slot, "pending": dict(pending), "options": options}


def period_label(period: str) -> str:
    """"2026-09-01/2026-09-30" -> "September 2026" for a whole calendar month, else "1 Sep 2026 to 15 Sep 2026". Display text only."""
    start_s, _, end_s = period.partition("/")
    start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)
    if start.day == 1 and end == date(end.year, end.month, calendar.monthrange(end.year, end.month)[1]) and (start.year, start.month) == (end.year, end.month):
        return f"{calendar.month_name[start.month]} {start.year}"
    return f"{start.day} {start:%b %Y} to {end.day} {end:%b %Y}"


def period_card(tenant_id: UUID, pending: Mapping[str, Any]) -> dict[str, Any] | None:
    """The latest persisted periods that have saved results; the newest is recommended."""
    periods = business_state.recent_periods(tenant_id, limit=MAX_REAL_OPTIONS)
    real = [
        _option(i, f"period-{p}", period_label(p), p.replace("/", " to "), "Latest period with saved results" if i == 0 else "An earlier period with saved results")
        for i, p in enumerate(periods)
    ]
    return _assemble("MISSING_INPUT", "period", pending, real)


def competitor_card(tenant_id: UUID, pending: Mapping[str, Any], candidates: Sequence[tuple[UUID, str]], now: Any) -> dict[str, Any] | None:
    """Candidates ranked by their most recent usable capture (the stated rule); one without a capture ranks last."""
    ranked: list[tuple[str, str, UUID, str]] = []
    for url_id, label in candidates:
        snap = ceo_reads.competitor_handoff(tenant_id, url_id, now=now)
        captured = None if isinstance(snap, ceo_reads.CiUnavailable) or snap.listed_price_paise is None else snap.captured_at.date().isoformat()
        ranked.append((captured or "", label, url_id, captured or ""))
    ranked.sort(key=lambda r: r[1].casefold())  # by name first, so equal captures keep a stable order,
    ranked.sort(key=lambda r: r[0], reverse=True)  # then newest capture first (an ISO date sorts chronologically; "" = no capture sorts last)
    real = [
        _option(i, f"competitor-{uid}", label, label, f"Most recent capture: {cap}" if cap else "No usable capture yet", {"competitor_url_id": str(uid)})
        for i, (_, label, uid, cap) in enumerate(ranked)
    ]
    return _assemble("AMBIGUOUS", "competitor", pending, real)


def form_card(pending: Mapping[str, Any]) -> dict[str, Any] | None:
    """A card whose one real option opens the playbook's run-form (the Hub opens it; choosing runs nothing and makes no model call). No "Other": prices and
    costs are never typed into chat."""
    key = str(pending.get("key") or "")
    label = FORM_LABELS.get(key)
    if label is None:
        return None
    option = {"key": "open-form", "label": label, "kind": "RECOMMENDED", "value": key, "reason": "Prices and costs are entered in the form, never typed into chat",
              "refs": {}, "form": key}
    return {"version": CARD_VERSION, "kind": "FORM", "slot": "form", "pending": dict(pending), "options": [option]}


def build(tenant_id: UUID, *, slot: str, pending: Mapping[str, Any], candidates: Sequence[tuple[UUID, str]], now: Any) -> dict[str, Any] | None:
    if slot == "form":
        return form_card(pending)
    if slot == "period":
        return period_card(tenant_id, pending)
    if slot == "competitor":
        cands = candidates or tuple((UUID(str(r["id"])), str(r["label"])) for r in ceo_reads.list_active_competitors(tenant_id, limit=MAX_REAL_OPTIONS + 2) if r.get("label"))
        return competitor_card(tenant_id, pending, cands, now) if cands else None
    return None


def option_for(card: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    return next((o for o in card.get("options", []) if o.get("key") == key), None)


def resume_action(card: Mapping[str, Any], *, option_key: str | None, other_text: str | None) -> tuple[str, str | None, dict[str, str], dict[str, str]]:
    """(route, key, slots, refs) to run for a chosen option or a typed 'Other': the pending intent with the asked slot filled in. Raises ValueError when
    the card has no pending intent or the choice is not one of its options."""
    pend = card.get("pending") or {}
    slot = card.get("slot")
    if not pend.get("route") or not slot:
        raise ValueError("card has no pending intent")
    slots = dict(pend.get("slots") or {})
    refs = dict(pend.get("refs") or {})
    if option_key is not None:
        opt = option_for(card, option_key)
        if opt is None or opt.get("kind") == "OTHER":
            raise ValueError("not an option of this card")
        slots[slot] = str(opt["value"])
        refs.update(opt.get("refs") or {})
    else:
        if not other_text or not other_text.strip():
            raise ValueError("an empty answer")
        slots[slot] = other_text.strip()
        if slot == "competitor":
            refs.pop("competitor_url_id", None)  # typed text is resolved by the resolvers, not by a stale ref
    return str(pend["route"]), pend.get("key"), slots, refs
