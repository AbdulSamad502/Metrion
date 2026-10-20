"""CEO -> CMO delegation: the bounded missing-input loop, the plan card extras and the result footer (docs/specs/ceo-cmo-delegation.md CD1, CD2, CD11-CD13, 6.3, 6.4, 6.6, 6.7).

What this module IS: CODE that decides what the CEO asks, how often, when a pending task expires, what a plan card says beyond the frozen slots, and how a CMO result is
labelled. The seller only ever talks to the CEO; the CMO's own question list is `input_session.CMO_TITLES / CMO_HASHTAGS / CMO_GROUNDED / CMO_TRENDS` (the pure, ordered field
tables that declare what each CMO action needs), and every answer is parsed by code against the one field being asked.

What it is NOT: it asks no model anything, computes no money and no usage, and approves nothing. Typing "yes" is never approval (CD11): the only way a plan runs is the explicit
approve call bound to the plan id and hash (`approval_run.py`).

State lives on the CEO message that asks the current question (`choices.delegation`, alongside `choices.pending.collected`), so it survives a reload and is tenant-scoped like
every message; there is no new table. It holds text, counts and ISO times only - never a model output, never image bytes.

Limits (server-side configuration, read at use; ceo-cmo-delegation.md 6.3-3):
* `CMO_DELEGATION_MAX_QUESTIONS` (8): every CEO question for the task counts, re-asks included. Questions 1..8 are asked; a 9th never is.
* `CMO_DELEGATION_MAX_REASKS` (2): the same field is asked at most 1 + 2 = 3 times; the third unusable answer reaches the limit.
* `CMO_DELEGATION_IDLE_EXPIRY_SECONDS` (86400): `now - last_activity >= value` means expired (86399 live, 86400 expired). The answers are KEPT; a fresh confirmation is required.
  The confirmation message itself is not a field question and does not count toward the question limit.
A setting that is present but not a positive whole number fails CLOSED (`CONFIG_INVALID`): the CEO declines to start or continue a CMO task.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend import config
from backend.ceo import input_session
from backend.ceo.contract import LegResult, LegStatus

DELEGATED_ACTIONS: frozenset[str] = frozenset(input_session.CMO_SESSIONS)  # the CMO actions the seller can reach through the CEO, behind a plan card
IMAGE_TYPES: frozenset[str] = frozenset({"PNG", "JPEG", "WEBP"})  # attachment types (detected from content) the CMO reads as a product photo
IMAGE_ACTION = "cmo.analyze_attachment"  # the CEO -> CMO photo hand-off (by reference); always its own small plan card
IMAGE_FOLLOWUPS: frozenset[str] = DELEGATED_ACTIONS - {"cmo.market_trends"}  # the generation actions that can start from an attached product photo
CI_INFORMED: frozenset[str] = DELEGATED_ACTIONS - {"cmo.market_trends"}  # the writing actions that may be informed by the seller's saved competitor listing themes (CEO-brokered)
CI_USED_LINE = (
    "Informed by themes from {n} of your tracked competitors' saved listings (derived words only, no competitor text, no prices). "
    "Metrion writes original text from your own product facts and checks it is not a copy or close rewrite of any competitor's wording, and makes no search-volume, ranking or sales claim."
)
STATE_VERSION = 1


def ci_unused_line(note: str | None) -> str:
    return (note or "Competitor listing themes were not used.") + " This is written independently from your own product facts."

CONFIG_INVALID_TEXT = (
    "One of the settings that limits how many questions I may ask for a marketing task is not valid, so I have not started or continued it. Nothing was asked, run, sent or "
    "used up. Your operator needs to correct CMO_DELEGATION_MAX_QUESTIONS, CMO_DELEGATION_MAX_REASKS or CMO_DELEGATION_IDLE_EXPIRY_SECONDS (CONFIG_INVALID)."
)

_FIELD_LABELS = {
    "product_name": "the product", "category_hint": "the category", "marketplaces": "the marketplaces", "marketplace": "the marketplace", "seller_title": "your title",
    "niche": "the niche", "news_kind": "the kind of news",
}


@dataclass(frozen=True, slots=True)
class Limits:
    max_questions: int
    max_reasks: int
    idle_seconds: int


@dataclass(frozen=True, slots=True)
class ConfigBlocked:
    """A limit setting is invalid: nothing is asked or run, and the seller is told so."""

    text: str = CONFIG_INVALID_TEXT


def load_limits() -> Limits:
    """Reads the three settings now. Raises `config.ConfigInvalid` for a present-but-unusable value (fail closed)."""
    return Limits(config.cmo_delegation_max_questions(), config.cmo_delegation_max_reasks(), config.cmo_delegation_idle_expiry_seconds())


# ------------------------------------------------------------------------------------------------ small helpers
def _iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat()


def _parse(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _label(name: str) -> str:
    return _FIELD_LABELS.get(name, name.replace("_", " "))


def _show(value: Any) -> str:
    if value == input_session.KEEP_CONFIRMED:
        return "your confirmed niche terms"
    if isinstance(value, list):
        return ", ".join(str(v).title() if str(v).isupper() else str(v) for v in value)
    return str(value).title() if isinstance(value, str) and value.isupper() else str(value)


def _as_text(value: Any) -> str | None:
    """A collected value as the text that would parse back to it (so a previous answer can be offered as a one-click choice)."""
    if value == input_session.KEEP_CONFIRMED:
        return "use my confirmed terms"
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        return ", ".join(value)
    return None


def _summary(collected: Mapping[str, Any]) -> str:
    return "; ".join(f"{_label(k)}: {_show(v)}" for k, v in collected.items() if not k.startswith("_")) or "nothing yet"


def _collected(card: Mapping[str, Any]) -> dict[str, Any]:
    return dict((card.get("pending") or {}).get("collected") or {})


def _fresh_state(action_key: str, now: datetime, previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"version": STATE_VERSION, "id": str(uuid.uuid4()), "actionKey": action_key, "questionCount": 0, "reaskCounts": {}, "startedAt": _iso(now), "lastActivityAt": _iso(now),
            "status": "LIVE", "previous": dict(previous or {})}


def _decorate(ask: input_session.Ask, state: dict[str, Any]) -> input_session.Ask:
    """Attaches the task state to the question's card, and - after a restart - offers what the seller gave before as the first choice (never reused silently)."""
    card = ask.card
    card["delegation"] = state
    prev = (state.get("previous") or {}).get(card.get("slot"))
    text = _as_text(prev) if prev is not None else None
    if text is not None and not any(o.get("value") == text for o in card["options"]):
        real = [o for o in card["options"] if o["kind"] in ("RECOMMENDED", "ALTERNATIVE")]
        rest = [o for o in card["options"] if o["kind"] not in ("RECOMMENDED", "ALTERNATIVE")]
        for o in real:
            o["kind"] = "ALTERNATIVE"
        offered = {"key": "prev", "label": f"Use what you gave before: {_show(prev)}", "kind": "RECOMMENDED", "value": text, "reason": "You gave this earlier; choosing it confirms it again", "refs": {}}
        card["options"] = [offered, *real[: input_session.MAX_OPTIONS - 1], *rest]
    return ask


# ------------------------------------------------------------------------------------------------ the loop
def begin(ask: input_session.Ask, *, action_key: str, now: datetime) -> input_session.Ask:
    """The FIRST question of a CMO task: opens the task state (question 1 of the limit)."""
    state = _fresh_state(action_key, now)
    state["questionCount"] = 1
    return _decorate(ask, state)


def _pause_card(card: Mapping[str, Any], state: dict[str, Any], *, status: str, now: datetime, options: list[dict[str, Any]]) -> dict[str, Any]:
    playbook = str(card.get("playbook") or (card.get("pending") or {}).get("key") or "")
    st = {**state, "status": status, "lastActivityAt": _iso(now)}
    options = [*options, {"key": "cancel", "label": "Cancel", "kind": "CANCEL", "value": None, "reason": "Stop; nothing will run", "refs": {}}]
    return {"version": input_session.CARD_VERSION, "kind": "INPUT", "slot": "continue" if status == "EXPIRED" else "restart", "playbook": playbook,
            "pending": {"route": "ACTION", "key": playbook, "slots": {}, "refs": {}, "collected": _collected(card)}, "options": options, "delegation": st}


def _limit(card: Mapping[str, Any], state: dict[str, Any], *, which: str, field: str, collected: Mapping[str, Any], ctx: input_session.Ctx, now: datetime, limits: Limits) -> input_session.Ask:
    playbook = str(card.get("playbook") or (card.get("pending") or {}).get("key") or "")
    missing = [_label(n) for n in input_session.field_names(playbook, ctx, collected)]
    if which == "REASKS":
        why = f"I still could not use your answer about {_label(field)} after {limits.max_reasks + 1} tries, so I have stopped instead of guessing."
    else:
        why = f"I have already asked {limits.max_questions} questions for this request, which is the most I ask, so I have stopped before asking about {_label(field)}."
    text = (
        f"{why} What you have given me so far: {_summary(collected)}. Still missing: {', '.join(missing) or 'nothing'}. "
        "Nothing was run, sent or used up. You can start again (I will offer what you gave before, for you to confirm) or cancel."
    )
    options = [{"key": "restart", "label": "Start again", "kind": "RECOMMENDED", "value": "restart", "reason": "Begins the request afresh with the question count back at zero", "refs": {}}]
    return input_session.Ask(text, _pause_card({"playbook": playbook, "pending": {"collected": dict(collected)}}, state, status="LIMIT", now=now, options=options))


def _expired(card: Mapping[str, Any], state: dict[str, Any], now: datetime) -> input_session.Ask:
    collected = _collected(card)
    text = (
        f"It has been a while since this request was last worked on, so I need you to confirm before I go on. What you gave me: {_summary(collected)}. "
        "Nothing has run, been sent or used up. Choose Continue to keep these answers, or Start again."
    )
    options = [
        {"key": "continue", "label": "Continue with these answers", "kind": "RECOMMENDED", "value": "continue", "reason": "Keeps what you already gave", "refs": {}},
        {"key": "restart", "label": "Start again", "kind": "ALTERNATIVE", "value": "restart", "reason": "Begins afresh; I will offer your earlier answers for you to confirm", "refs": {}},
    ]
    return input_session.Ask(text, _pause_card(card, state, status="EXPIRED", now=now, options=options))


def _choice(option_key: str | None, text: str, allowed: Sequence[str]) -> str | None:
    if option_key in allowed:
        return option_key
    t = " ".join(text.casefold().split()).strip(" .!")
    words = {"continue": ("continue", "keep", "keep these", "confirm", "confirmed"), "restart": ("restart", "start again", "start over", "again", "new")}
    for name in allowed:
        if t in words.get(name, ()):
            return name
    return None


def advance(
    card: Mapping[str, Any], *, option_key: str | None, text: str, ctx: input_session.Ctx, now: datetime,
) -> input_session.Ask | input_session.Done | input_session.Cancelled | input_session.Blocked | ConfigBlocked:
    """One answer to a CMO input card. A card without task state (an older or non-CMO session) behaves exactly as `input_session.advance`."""
    state = card.get("delegation")
    if not state:
        return input_session.advance(card, option_key=option_key, text=text, ctx=ctx)
    try:
        limits = load_limits()
    except config.ConfigInvalid:
        return ConfigBlocked()
    if option_key == "cancel" or (option_key is None and text.strip().casefold() in input_session.CANCEL_WORDS):
        return input_session.Cancelled()
    status = str(state.get("status") or "LIVE")
    if status in ("LIMIT", "EXPIRED"):
        return _after_pause(card, state, status, option_key, text, ctx, now, limits)
    if (now - _parse(str(state["lastActivityAt"]))).total_seconds() >= limits.idle_seconds:
        return _expired(card, state, now)
    slot, before = str(card.get("slot")), _collected(card)
    out = input_session.advance(card, option_key=option_key, text=text, ctx=ctx)
    if not isinstance(out, input_session.Ask):
        return out
    reasks = dict(state.get("reaskCounts") or {})
    after = _collected(out.card)
    if out.card.get("slot") == slot and after == before and option_key != "back":  # the answer was unusable: the same field is asked again, with the reason
        n = int(reasks.get(slot, 0)) + 1
        if n > limits.max_reasks:
            return _limit(card, state, which="REASKS", field=slot, collected=before, ctx=ctx, now=now, limits=limits)
        reasks[slot] = n
    if int(state.get("questionCount", 0)) + 1 > limits.max_questions:
        playbook = str(card.get("playbook") or (card.get("pending") or {}).get("key") or "")
        if out.card.get("slot") != slot and input_session.only_optional_left(playbook, ctx, after):  # only skippable extra details remain: go on without them, never stop the task for them
            return input_session.finish_without_optional(playbook, after)
        return _limit(card, state, which="QUESTIONS", field=str(out.card.get("slot")), collected=after, ctx=ctx, now=now, limits=limits)
    return _decorate(out, {**state, "questionCount": int(state.get("questionCount", 0)) + 1, "reaskCounts": reasks, "lastActivityAt": _iso(now), "status": "LIVE"})


def _after_pause(
    card: Mapping[str, Any], state: dict[str, Any], status: str, option_key: str | None, text: str, ctx: input_session.Ctx, now: datetime, limits: Limits,
) -> input_session.Ask | input_session.Done | input_session.Blocked:
    playbook = str(card.get("playbook") or (card.get("pending") or {}).get("key") or "")
    allowed = ("continue", "restart") if status == "EXPIRED" else ("restart",)
    choice = _choice(option_key, text, allowed)
    collected = _collected(card)
    if choice is None:  # anything else is not an answer to this question: it is shown again, without counting
        again = _expired(card, state, now) if status == "EXPIRED" else _limit(card, state, which="QUESTIONS", field=next(iter(input_session.field_names(playbook, ctx, collected)), "this"),
                                                                           collected=collected, ctx=ctx, now=now, limits=limits)
        return again
    if choice == "restart":
        previous = {**(state.get("previous") or {}), **collected}
        fresh = _fresh_state(str(state.get("actionKey") or playbook), now, previous)
        nxt = input_session.resume_ask(playbook, ctx, {})
        if not isinstance(nxt, input_session.Ask):
            return nxt
        fresh["questionCount"] = 1
        return _decorate(nxt, fresh)
    nxt = input_session.resume_ask(playbook, ctx, collected)  # continue: the same answers, the next question
    if not isinstance(nxt, input_session.Ask):
        return nxt
    if int(state.get("questionCount", 0)) + 1 > limits.max_questions:
        return _limit(card, state, which="QUESTIONS", field=str(nxt.card.get("slot")), collected=collected, ctx=ctx, now=now, limits=limits)
    return _decorate(nxt, {**state, "questionCount": int(state.get("questionCount", 0)) + 1, "lastActivityAt": _iso(now), "status": "LIVE"})


# ------------------------------------------------------------------------------------------------ remembered product (CD2: a confirmed fact is not asked again)
def last_product(messages: Sequence[Mapping[str, Any]], plans: Sequence[Mapping[str, Any]] = ()) -> str | None:
    """The product the seller most recently gave in THIS conversation (from an input card's collected answers, else from a stored plan's frozen slots), or None."""
    for m in reversed(list(messages)):
        name = ((m.get("choices") or {}).get("pending") or {}).get("collected", {}).get("product_name")
        if isinstance(name, str) and name.strip():
            return name
    for p in reversed(list(plans)):
        for leg in (p.get("plan") or {}).get("legs", []):
            name = (leg.get("slots") or {}).get("product_name")
            if isinstance(name, str) and name.strip():
                return name
    return None


def _norm_name(v: Any) -> str:
    return " ".join(str(v or "").casefold().split())


def carried_facts(key: str, product: str | None, plans: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Details the seller already gave for THIS product earlier in the conversation (brand, size and other attributes, category, their title), read from the earlier plans' frozen slots,
    newest first. They are the seller's own statements and are carried into the new task so they are not asked again; the plan card shows them, and a different product carries nothing."""
    if key not in DELEGATED_ACTIONS or key == "cmo.market_trends" or not _norm_name(product):
        return {}
    want = _norm_name(product)
    out: dict[str, str] = {}
    for p in reversed(list(plans)):
        for leg in (p.get("plan") or {}).get("legs", []):
            slots = leg.get("slots") or {}
            if leg.get("action_key") not in DELEGATED_ACTIONS or _norm_name(slots.get("product_name")) != want:
                continue
            if isinstance(slots.get("brand"), str) and slots["brand"].strip():
                out.setdefault("fact_brand", slots["brand"])
            for a in slots.get("attributes") or []:
                if isinstance(a, Mapping) and isinstance(a.get("name"), str) and isinstance(a.get("value"), str) and a["value"].strip():
                    slug = re.sub(r"[^a-z0-9]+", "_", a["name"].casefold()).strip("_")
                    if slug:
                        out.setdefault(f"fact_{slug}", a["value"])
            for name in ("seller_title", "category_hint"):
                if isinstance(slots.get(name), str) and slots[name].strip():
                    out.setdefault(name, slots[name])
    return out


def prefill_for(key: str, slots: Mapping[str, str], messages: Sequence[Mapping[str, Any]], plans: Sequence[Mapping[str, Any]] = ()) -> dict[str, str]:
    """The classifier's slot text for a CMO task. When the seller refers to the product they already gave ("it", "this product") and there IS one earlier in the conversation,
    that product is carried forward instead of being asked again; the plan card shows it. A pronoun with nothing to refer to is dropped, so the product is asked for."""
    out = dict(slots)
    if key not in DELEGATED_ACTIONS or key == "cmo.market_trends":
        return out
    named = (out.get("product") or "").strip()
    if named and named.casefold().strip(" .!?") not in input_session._PRONOUNS:
        return out
    out.pop("product", None)
    earlier = last_product(messages, plans)
    if earlier:
        out["product"] = earlier
    return out


# ------------------------------------------------------------------------------------------------ the plan card
_WHAT = {
    "cmo.generate_title_sets": "write listing title options", "cmo.generate_hashtags": "suggest hashtags", "cmo.generate_description": "write a product description",
    "cmo.generate_keywords": "suggest search keywords", "cmo.market_trends": "research current market trends", "cmo.generate_bullets": "write the five listing bullet points",
    "cmo.generate_backend_terms": "write Amazon backend search terms", "cmo.generate_listing_copy": "write the full listing copy pack (description, bullet points and keywords)",
}
MAX_QUERIES_SHOWN = 12


def _model_line() -> str:
    try:
        return f"Model: {config.cmo_llm_model()}, on Metrion's own language-model server (operator-controlled). The product details you gave are sent to it."
    except Exception:  # noqa: BLE001 - not configured: said plainly, never a made-up name
        return "Model: the CMO language model is not configured yet, so this run would be refused and nothing would be used up."


def plan_extras(key: str, slots: Mapping[str, Any], preview: Mapping[str, Any] | None = None) -> tuple[list[str], dict[str, int]]:
    """What the plan card says beyond the frozen slots, written by code: what runs, the model, the quota effect, and for market research the exact searches. Also the unit
    count per leg (a title set costs one unit per marketplace). Nothing here is read from a model."""
    if key not in DELEGATED_ACTIONS:
        return [], {}
    mps = slots.get("marketplaces") if isinstance(slots.get("marketplaces"), list) else ([slots["marketplace"]] if slots.get("marketplace") else [])
    where = " on " + ", ".join(str(m).title() for m in mps) if mps else ""
    product = f" for {slots['product_name']}" if slots.get("product_name") else ""
    details = [f"Slim CMO (recommend-only) will {_WHAT[key]}{product}{where}. It writes text only and changes nothing on any marketplace."]
    stated = facts_line(slots)
    if stated:
        details.append(stated)
    if key != "cmo.market_trends" and is_thin(slots):
        details.append("Thin input - add brand/size/features for stronger " + ("titles." if key == "cmo.generate_title_sets" else "results."))
    units: dict[str, int] = {}
    if key == "cmo.market_trends":
        details.append("The searches below go to the web search providers; the public results are then read by Metrion's own language model.")
        queries = list((preview or {}).get("queries") or [])
        if queries:
            labels = {"NICHE": "your niche", "MARKET_NEWS": "marketplace news", "REPORTED_TACTICS": "tactics sellers report", "NEW_PRODUCTS_BUZZ": "new product buzz", "ADJACENT": "related niches"}
            details.append("Exact searches that will be sent:")
            details.extend(f"{n}. {labels.get(str(q.get('section')), str(q.get('section')).lower())}: “{q.get('query')}”" for n, q in enumerate(queries[:MAX_QUERIES_SHOWN], start=1))
            if len(queries) > MAX_QUERIES_SHOWN:
                details.append(f"(and {len(queries) - MAX_QUERIES_SHOWN} more)")
        details.append("Quota effect: 1 CMO unit and 1 shared market-research unit, counted only if the report completes.")
    else:
        details.append(_model_line())
        n = len(mps) if key == "cmo.generate_title_sets" and mps else 1
        if key == "cmo.generate_title_sets":
            units[key] = n
        details.append(f"Quota effect: {n} CMO unit{'s' if n != 1 else ''} ({'one per marketplace' if n != 1 else 'one result'}), counted only for results that complete; a failed or refused result uses nothing.")
    details.append("What is written is saved, and will also appear on the Slim CMO dashboard.")
    return details, units


_TITLE_WHAT = {
    "cmo.generate_title_sets": "Write listing titles", "cmo.generate_hashtags": "Suggest hashtags", "cmo.generate_description": "Write a product description",
    "cmo.generate_keywords": "Suggest search keywords", "cmo.market_trends": "Research market trends and news", "cmo.generate_bullets": "Write listing bullet points",
    "cmo.generate_backend_terms": "Write Amazon backend search terms", "cmo.generate_listing_copy": "Write the full listing copy pack",
}


def _detail_count(slots: Mapping[str, Any]) -> int:
    n = 1 if slots.get("brand") else 0
    return n + sum(1 for a in slots.get("attributes") or [] if isinstance(a, Mapping) and a.get("value") and str(a.get("name")).casefold() not in ("product name", "category"))


def is_thin(slots: Mapping[str, Any]) -> bool:
    """Fewer than two confirmed details beyond the product name: the same rule the CMO applies to its result, so the card and the result agree."""
    return _detail_count(slots) < 2


def plan_title(key: str, slots: Mapping[str, Any]) -> str:
    """A short human title for the plan, e.g. "Write listing titles for Thermos Bottle on Amazon" (used for the one-line approval note)."""
    mps = slots.get("marketplaces") if isinstance(slots.get("marketplaces"), list) else ([slots["marketplace"]] if slots.get("marketplace") else [])
    product = f" for {slots['product_name']}" if slots.get("product_name") else ""
    where = " on " + ", ".join(str(m).title() for m in mps) if mps else ""
    return f"{_TITLE_WHAT[key]}{product}{where}"[:160]


def compact_lines(key: str, slots: Mapping[str, Any], preview: Mapping[str, Any] | None = None, *, ttl_minutes: int = 30) -> list[str]:
    """The 4-5 short lines the plan card shows: what will run, the confirmed inputs, the model, the cost and how long the plan is valid. Written by code from the same frozen slots as the
    full details (which stay complete and unchanged in the plan for audit)."""
    if key not in DELEGATED_ACTIONS:
        return []
    lines = [plan_title(key, slots) + "."]
    if key == "cmo.market_trends":
        n = len((preview or {}).get("queries") or [])
        provs = sorted({str(q.get("provider")).title() for q in (preview or {}).get("queries") or [] if q.get("provider")})
        lines.append(f"{n} news searches (listed under Details) are sent via {' and '.join(provs) or 'the web search providers'}." if n else "Web searches go to the search providers (listed under Details).")
        lines.append("A Metrion language model reads the public results; every item shows its source and date.")
        lines.append("Cost: 1 CMO unit and 1 shared research unit, only if it completes.")
    else:
        facts = []
        if slots.get("brand"):
            facts.append(f"Brand: {slots['brand']}")
        facts.extend(f"{a['name']}: {a['value']}" for a in slots.get("attributes") or [] if isinstance(a, Mapping) and a.get("name") and a.get("value"))
        if slots.get("seller_title"):
            facts.append(f"Your title: {slots['seller_title']}")
        shown = "; ".join(facts)
        using = f"Using: {shown[:150] + ('...' if len(shown) > 150 else '')}." if facts else "Using: only the product name."
        if is_thin(slots):  # on the same line, so the card stays at five lines
            using += " Thin input - add brand/size/features for stronger " + ("titles." if key == "cmo.generate_title_sets" else "results.")
        lines.append(using)
        try:
            lines.append(f"Model: {config.cmo_llm_model()} (Metrion's own server).")
        except Exception:  # noqa: BLE001 - not configured: said plainly, never a made-up name
            lines.append("Model: not configured yet, so a run would be refused and nothing used up.")
        n = len(slots["marketplaces"]) if key == "cmo.generate_title_sets" and isinstance(slots.get("marketplaces"), list) and slots["marketplaces"] else 1
        lines.append(f"Cost: {n} CMO units, only for results that complete." if n != 1 else "Cost: 1 CMO unit, only if it completes.")
    if slots.get("ci_insight_ids"):
        lines.append(f"Uses themes from {len(slots['ci_insight_ids'])} tracked competitor listing(s); original wording only, no copying.")
    lines.append(f"Valid for {ttl_minutes} minutes.")
    return lines


def image_compact(attachment: Mapping[str, Any], *, model_label: str, ttl_minutes: int = 30) -> list[str]:
    name = " ".join(str(attachment.get("filename") or "your attachment").split())[:80]
    return [f"Read your attached photo \u201c{name}\u201d.", f"Sent only to {model_label}; location and camera data are removed first.", "Cost: 0 CMO units. The writing that follows is a separate plan.",
            f"Valid for {ttl_minutes} minutes."]


def facts_line(slots: Mapping[str, Any]) -> str | None:
    """The product facts the seller confirmed or typed, as the plan card shows them. They are the seller's own statements: a photo never supplied any of them directly."""
    parts: list[str] = []
    if slots.get("brand"):
        parts.append(f"Brand: {slots['brand']}")
    for a in slots.get("attributes") or []:
        if isinstance(a, Mapping) and a.get("name") and a.get("value"):
            parts.append(f"{a['name']}: {a['value']}")
    return ("Product facts you confirmed (your own statements, passed as you gave them): " + "; ".join(parts) + ".") if parts else None


# ------------------------------------------------------------------------------------------------ the photo hand-off (CD2, CD5, CD10, 6.4, 6.5)
def endpoint_label() -> str:
    """The receiving vision endpoint as the seller is told it: the model and that it is Metrion's own, never the host or port. Raises `config.MissingConfig` (or its subclass
    `LlmEndpointNotVerified`) unless the endpoint is attested operator-controlled right now."""
    config.cmo_vision_endpoint_verified()
    return f"Metrion's own vision model {config.cmo_vision_model_label()} (operator-controlled)"


def image_plan_details(attachment: Mapping[str, Any], *, model_label: str) -> list[str]:
    """What the small image-analysis plan card says (6.5-5), written by code: the file (escaped by the frontend, never parsed), where it goes (a LABEL, never host:port), what it costs
    and what it is not. `model_label` is the endpoint label from `cmo_attachment.endpoint_label()`."""
    name = " ".join(str(attachment.get("filename") or "your attachment").split())[:120]
    sha = str(attachment.get("sha256") or "")[:8]
    return [
        f"Slim CMO (recommend-only) will read what is visible in your attached photo “{name}” ({attachment.get('detected_type')}, fingerprint {sha}).",
        f"This photo will be sent to {model_label} to read what is visible; nothing is sent anywhere else. Its location and camera data are removed before the model sees it.",
        "Quota effect: 0 CMO units. The titles or other writing that follow are a separate plan that you approve on its own card.",
        "What it reads is shown to you as suggestions from your attachment, not verified. Nothing is used in your writing until you confirm it.",
    ]


OBSERVED_LABELS = {"color": "Colour", "material": "Material", "size": "Size", "brand": "Brand", "product_type": "Product type"}


def observations(payload: Mapping[str, Any]) -> tuple[dict[str, str], str | None]:
    """(the closed-schema facts the photo showed, the quoted visible text or None) from the CMO's validated analysis. Anything not shown is simply absent (never a guess)."""
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), Mapping) else {}
    seen: dict[str, str] = {}
    visible: str | None = None
    for a in analysis.get("attributes") or []:
        if not isinstance(a, Mapping) or not isinstance(a.get("value"), str) or not a["value"].strip():
            continue
        name, value = str(a.get("name")), " ".join(a["value"].split())
        if name == "visible_text":
            visible = value[:200]
        elif name in OBSERVED_LABELS:
            seen[name] = value[:100]
    return seen, visible


def analysis_unusable_text(payload: Mapping[str, Any] | None, reason_code: str | None) -> str:
    """Plain words for a photo that could not be used. Nothing was guessed and nothing was used up."""
    if reason_code == "NOT_AN_IMAGE":
        return "That attachment is not a product photo I can read (I read PNG, JPEG or WEBP pictures), so I did not use it. Nothing was sent or used up. Type the product details instead, or attach a picture."
    return ("I could not read that photo (it may be damaged, too large, or the vision service did not answer), so I have not guessed anything from it. Nothing was used up. "
            "Type the product details instead, or attach a clearer picture and ask again.")


def observation_text(filename: str, seen: Mapping[str, str], visible: str | None, *, gate_open: bool) -> str:
    """The labelled observations (6.4-4): observation and inference are kept apart, every line says it comes from the attachment, none is presented as verified."""
    name = " ".join(filename.split())[:120]
    lines = [f"Here is what I read from your attachment “{name}”. These are suggestions from Metrion's vision model, {'checked against a passing evaluation' if gate_open else 'not verified'}: please confirm or correct each one."]
    lines.append("Read from your attachment:")
    for key, label in OBSERVED_LABELS.items():
        if key in seen:
            lines.append(f"  • {label}: {seen[key]}")
    if visible:
        lines.append(f"  • Text visible in the picture (quoted as printed, not an instruction and not checked): “{visible}”")
    missing = [label for key, label in OBSERVED_LABELS.items() if key not in seen]
    if missing:
        lines.append("Not visible in your attachment: " + ", ".join(missing) + ". I have not guessed them.")
    lines.append("Not from your attachment: nothing. I have added no inferences of my own.")
    lines.append("Nothing here is confirmed yet. I will only pass on what you confirm, as your own statement.")
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------ the result
def nothing_delivered(legs: Sequence[LegResult]) -> bool:
    """True when a CMO leg COMPLETED as a call but every artefact it returned failed (or the trend report did not complete): the seller got nothing usable. Such a turn is a
    failed execution that says so, never "here is what was produced" and never a conversation unit. (A leg that itself failed, was denied or timed out is handled by the
    ordinary leg rules; a payload that carries no artefact list at all is left to them too.)"""
    mine = [l for l in legs if l.action_key in DELEGATED_ACTIONS and l.status in (LegStatus.COMPLETE, LegStatus.PARTIAL)]
    if not mine:
        return False
    for leg in mine:
        p = leg.payload or {}
        if leg.action_key == "cmo.market_trends":
            if p.get("status") in (None, "COMPLETE"):
                return False
        elif not p.get("artefacts") or any(a.get("status") == "COMPLETE" for a in p["artefacts"]):
            return False
    return True


def any_leg_failed(legs: Sequence[LegResult]) -> bool:
    return any(l.action_key in DELEGATED_ACTIONS and l.status not in (LegStatus.COMPLETE, LegStatus.PARTIAL) for l in legs)


def heading_for(key: str | None) -> str:
    if key == "cmo.market_trends":
        return "Here is what the market-trend research found. Written by Slim CMO (recommend-only)."
    return "Here is what Slim CMO wrote for the plan you approved. Written by Slim CMO (recommend-only)."


def result_footer(legs: Sequence[LegResult]) -> str:
    """Code-written lines after the result: the saved references, what was used, and where else it can be seen. Counts come from the CMO's own response."""
    refs: list[str] = []
    units = 0
    for leg in legs:
        if leg.action_key not in DELEGATED_ACTIONS:
            continue
        p = leg.payload or {}
        if leg.action_key == "cmo.market_trends":
            if p.get("status") == "COMPLETE" and p.get("generationId"):
                refs.append(f"market-trend report {str(p['generationId'])[:8]}")
            billed = p.get("unitsBilled")
            units += int(billed.get("cmo", 0)) if isinstance(billed, Mapping) and isinstance(billed.get("cmo", 0), int) else 0
            continue
        for a in p.get("artefacts") or []:
            if a.get("status") == "COMPLETE" and a.get("id"):
                refs.append(f"{str(a.get('outputType', 'result')).replace('_', ' ').lower()}{' (' + str(a['marketplace']).title() + ')' if a.get('marketplace') else ''} {str(a['id'])[:8]}")
        if isinstance(p.get("unitsBilled"), int):
            units += p["unitsBilled"]
    lines = []
    if refs:
        lines.append("Saved as: " + "; ".join(refs) + ".")
    lines.append(f"Used from your plan: {units} CMO unit{'s' if units != 1 else ''}.")
    lines.append("These results also appear on the Slim CMO dashboard.")
    return "\n".join(lines)
