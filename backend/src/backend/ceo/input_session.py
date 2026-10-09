"""Guided input for the two decision playbooks — spec §6.34.

When a playbook needs inputs, the CEO asks for them one question at a time in the conversation and the seller answers through the chat bar. Every answer, typed or
chosen from an option, is parsed BY CODE against the one field being asked (an amount in rupees, a count, a date window, a pick from real candidates). Text that
does not parse produces the same question again with the reason: a model is never asked to extract a number, and nothing is guessed or defaulted. An option is only
a shortcut for a piece of text (choosing "None (0), I confirm" is the same as typing it).

The session state is carried on the CEO message that asks the question (`choices.pending.collected`), so it survives a reload, is tenant-scoped like every message,
and is append-only. When the last field is collected the session builds exactly the `inputs` that `playbook_inputs.validate_inputs` checks for the form (§6.33).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from backend.ceo import slot_resolvers
from backend.ceo.periods import PeriodUnresolvable, resolve_period
from backend.services import ceo_reads

CARD_VERSION = 1
MAX_OPTIONS = 3  # real options at most, then "type it" (the seller's own answer), as for every decision card (§6.32)
CANCEL_WORDS = frozenset({"cancel", "stop", "never mind", "nevermind", "forget it"})


@dataclass(frozen=True, slots=True)
class Ctx:
    tenant_id: UUID
    today: date
    max_candidate_prices: int | None


@dataclass(frozen=True, slots=True)
class Option:
    label: str
    text: str  # what choosing it means: exactly the text that would be parsed if the seller typed it
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Reject:
    why: str  # plain words, shown with the question again


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    question: Callable[[Ctx, Mapping[str, Any]], str]
    parse: Callable[[str, Ctx, Mapping[str, Any]], Any | Reject]
    options: Callable[[Ctx, Mapping[str, Any]], Sequence[Option]] = lambda ctx, got: ()
    unanswerable: Callable[[Ctx, Mapping[str, Any]], str | None] = lambda ctx, got: None  # a reason the question can never be answered (nothing to choose from)


# ------------------------------------------------------------------------------------------------ parsers
def _text(max_len: int = 120) -> Callable[[str, Ctx, Mapping[str, Any]], Any]:
    def parse(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
        t = " ".join(raw.split())
        return t if 0 < len(t) <= max_len else Reject(f"Please answer in at most {max_len} characters.")

    return parse


def _amount(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    paise = slot_resolvers.parse_amount_paise(raw)
    return paise if paise is not None else Reject("I could not read that as an amount in rupees above zero. For example 499 or 1,299.50.")


def _prices(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    parts = [p for p in re.split(r"\s*(?:,|;|\band\b|\n)\s*", raw.strip()) if p]
    values = [slot_resolvers.parse_amount_paise(p) for p in parts]
    if not parts or any(v is None for v in values):
        return Reject("I could not read every price. Give them as rupee amounts separated by commas, for example 449, 479, 499.")
    ints = [v for v in values if v is not None]
    if len(set(ints)) != len(ints):
        return Reject("The prices must all be different.")
    if ctx.max_candidate_prices is not None and len(ints) > ctx.max_candidate_prices:
        return Reject(f"At most {ctx.max_candidate_prices} prices can be compared in one run. Which should I keep?")
    return ints


def _cost(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = raw.strip().casefold()
    if t in ("none", "none (0), i confirm", "nothing", "zero confirmed") or t.startswith("none"):
        return {"state": "NONE_CONFIRMED"}
    if t in ("unknown", "i do not know", "i don't know", "dont know", "don't know", "not sure"):
        return {"state": "UNKNOWN"}
    if re.fullmatch(r"(?:₹|rs\.?|inr)?\s*0+(?:\.0+)?", t):
        return Reject("A zero has to be confirmed on purpose: choose “None (0), I confirm”.")
    paise = slot_resolvers.parse_amount_paise(raw)
    if paise is None:
        return Reject("Give an amount in rupees (for example 49.50), or choose “None (0), I confirm” or “Unknown”.")
    return {"state": "AMOUNT", "amount_paise": paise}


def _gst(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = raw.strip().casefold()
    if t in ("unknown", "i do not know", "i don't know", "skip", "none", "no idea"):
        return None
    try:
        d = Decimal(t.rstrip("%").strip())
    except InvalidOperation:
        return Reject("Give the GST rate as a number such as 18, or choose “I do not know”.")
    return str(d.normalize()) if d.is_finite() and 0 <= d <= 100 else Reject("A GST rate is between 0 and 100.")


def _basis(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = raw.strip().casefold()
    if t in ("inclusive", "include", "includes gst", "including gst", "with gst", "prices include gst", "yes"):
        return "INCLUSIVE"
    if t in ("exclusive", "exclude", "excludes gst", "excluding gst", "without gst", "prices exclude gst", "no"):
        return "EXCLUSIVE"
    return Reject("Do your prices include GST or exclude it? Choose one, or type “inclusive” or “exclusive”.")


def _quantity(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = raw.strip().replace(",", "")
    return int(t) if re.fullmatch(r"\d{1,8}", t) and int(t) > 0 else Reject("Give the number of units as a whole number above zero, for example 200.")


def _competitor(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    found = slot_resolvers.resolve_competitor(ctx.tenant_id, raw)
    if isinstance(found, slot_resolvers.CompetitorMatch):
        return str(found.url_id)
    if found.reason == "NONE_TRACKED":
        return Reject("No competitors are being tracked yet. Add one on the Competitor Intelligence page first.")
    names = ", ".join(found.choices)
    lead = "That matches more than one tracked competitor" if found.reason == "AMBIGUOUS" else "I could not find that competitor"
    return Reject(f"{lead}. Which do you mean: {names}?" if names else f"{lead}.")


def _fee_options(ctx: Ctx) -> list[dict[str, str]]:
    return ceo_reads.fee_reference_options(ctx.tenant_id, as_of=ctx.today)


def _fee(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    wanted = re.sub(r"[\s·|/,-]+", " ", raw).strip().casefold()
    hits = [o for o in _fee_options(ctx) if re.sub(r"[\s·|/,-]+", " ", f"{o['marketplace']} {o['category']} {o['fee_type']}").strip().casefold() == wanted]
    if len(hits) == 1:
        return {"marketplace": hits[0]["marketplace"], "category": hits[0]["category"], "fee_type": hits[0]["fee_type"]}
    return Reject("I could not match that to a marketplace, category and fee type that has a fee rate. Choose one of the options.")


def _window(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", raw.strip())
    try:
        if m:
            start, end = date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
            if end < start or end > ctx.today:
                return Reject("The window must end on or before today and not end before it starts.")
            return {"period_start": start.isoformat(), "period_end": end.isoformat()}
        p = resolve_period(raw, today=ctx.today)
        return {"period_start": p.start.isoformat(), "period_end": p.end.isoformat()}
    except (PeriodUnresolvable, ValueError):
        return Reject("I could not read that as a period. Choose one of the options, or type a month (September) or dates like 2026-07-01 to 2026-09-30.")


# ------------------------------------------------------------------------------------------------ questions and options
def _cost_field(name: str, question: str) -> Field:
    return Field(
        name, lambda ctx, got: question, _cost,
        lambda ctx, got: (Option("None (0), I confirm", "none", "You are sure it is zero"), Option("Unknown", "unknown", "Margins that depend on it will show as unavailable")),
    )


def _competitor_options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    rows = [r for r in ceo_reads.list_active_competitors(ctx.tenant_id, limit=MAX_OPTIONS) if r.get("label")]
    return tuple(Option(str(r["label"]), str(r["label"]), "A competitor you track") for r in rows)


def _fee_choices(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    return tuple(Option(f"{o['marketplace']} · {o['category']} · {o['fee_type']}", f"{o['marketplace']} {o['category']} {o['fee_type']}", "A combination with a fee rate")
                 for o in _fee_options(ctx)[:MAX_OPTIONS])


def _window_choices(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    end = ctx.today
    return tuple(
        Option(label, f"{(end - timedelta(days=days)).isoformat()} to {end.isoformat()}", "Sales history up to today")
        for label, days in (("Last 90 days", 90), ("Last 180 days", 180), ("Last 365 days", 365))
    )


PRICE_IMPACT: tuple[Field, ...] = (
    Field("competitor", lambda c, g: "Which competitor changed their price?", _competitor, _competitor_options,
          lambda c, g: None if ceo_reads.list_active_competitors(c.tenant_id, limit=1) else "No competitors are being tracked yet. Add one on the Competitor Intelligence page first."),
    Field("sku", lambda c, g: "Which SKU is this for? Type it the way you list it.", _text()),
    Field("fee", lambda c, g: "Which marketplace, category and fee type should I price it under?", _fee, _fee_choices,
          lambda c, g: None if _fee_options(c) else "No marketplace fee rates are set up yet, so I cannot price a margin. Ask your account owner to add them."),
    Field("basis", lambda c, g: "Do the prices you will give me include GST?", _basis,
          lambda c, g: (Option("Prices include GST", "inclusive"), Option("Prices exclude GST", "exclusive"))),
    Field("gst_rate_pct", lambda c, g: "What GST rate applies? Type a number such as 18.", _gst, lambda c, g: (Option("I do not know", "unknown", "GST-dependent margins will show as unavailable"),)),
    Field("current_price_paise", lambda c, g: "What is your current selling price, in rupees?", _amount),
    Field("candidate_prices_paise", lambda c, g: "Which prices should I compare? Give rupee amounts separated by commas"
          + (f", up to {c.max_candidate_prices}." if c.max_candidate_prices else "."), _prices,
          lambda c, g: ()),
    _cost_field("shipping", "What is the shipping cost per unit? Type an amount, or choose an option."),
    _cost_field("advertising", "What is the advertising cost per unit?"),
    _cost_field("return_rto", "What do returns and RTO cost you per unit?"),
    _cost_field("other", "Any other cost per unit?"),
)

NEW_PRODUCT: tuple[Field, ...] = (
    Field("sku", lambda c, g: "Which SKU are you thinking of stocking? Type it the way you list it.", _text()),
    Field("quantity", lambda c, g: "How many units are you considering?", _quantity),
    Field("window", lambda c, g: "Which sales-history period should I look at?", _window, _window_choices),
)

SESSIONS: Mapping[str, tuple[Field, ...]] = {"COMPETITOR_PRICE_IMPACT": PRICE_IMPACT, "NEW_PRODUCT_DECISION": NEW_PRODUCT}


# ------------------------------------------------------------------------------------------------ the session
@dataclass(frozen=True, slots=True)
class Ask:
    """Ask (or re-ask) one question: the text the CEO says and the card that carries the state."""

    text: str
    card: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Done:
    playbook: str
    inputs: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Cancelled:
    pass


@dataclass(frozen=True, slots=True)
class Blocked:
    """The session cannot continue (nothing real to choose from): said plainly, nothing runs."""

    text: str


def _card(playbook: str, f: Field, ctx: Ctx, collected: Mapping[str, Any]) -> dict[str, Any]:
    opts: list[dict[str, Any]] = [{"key": f"opt-{i}", "label": o.label, "kind": "RECOMMENDED" if i == 0 else "ALTERNATIVE", "value": o.text, "reason": o.reason, "refs": {}}
            for i, o in enumerate(list(f.options(ctx, collected))[:MAX_OPTIONS])]
    opts.append({"key": "other", "label": "Other", "kind": "OTHER", "value": None, "reason": "Type your answer in the chat bar", "refs": {}})
    opts.append({"key": "cancel", "label": "Cancel", "kind": "CANCEL", "value": None, "reason": "Stop asking; nothing will run", "refs": {}})
    return {"version": CARD_VERSION, "kind": "INPUT", "slot": f.name, "playbook": playbook, "pending": {"route": "PLAYBOOK", "key": playbook, "slots": {}, "refs": {}, "collected": dict(collected)},
            "options": opts}


def _progress(fields: Sequence[Field], collected: Mapping[str, Any]) -> str:
    return f"({len(collected) + 1} of {len(fields)}) "


def start(playbook: str, ctx: Ctx) -> Ask | Blocked:
    fields = SESSIONS[playbook]
    return _ask(playbook, fields, ctx, {}, prefix="")


def _ask(playbook: str, fields: Sequence[Field], ctx: Ctx, collected: Mapping[str, Any], *, prefix: str) -> Ask | Blocked:
    f = next((x for x in fields if x.name not in collected), None)
    assert f is not None
    blocked = f.unanswerable(ctx, collected)
    if blocked is not None:
        return Blocked(blocked)
    return Ask(f"{prefix}{_progress(fields, collected)}{f.question(ctx, collected)}", _card(playbook, f, ctx, collected))


def advance(card: Mapping[str, Any], *, option_key: str | None, text: str, ctx: Ctx) -> Ask | Done | Cancelled | Blocked:
    """One answer to the card's question. `option_key` is the option the seller chose (its text is parsed exactly as if typed); None means the typed `text`."""
    playbook = str(card.get("playbook") or (card.get("pending") or {}).get("key") or "")
    fields = SESSIONS.get(playbook)
    if fields is None:
        raise ValueError("not an input session")
    collected = dict((card.get("pending") or {}).get("collected") or {})
    f = next((x for x in fields if x.name not in collected), None)
    if f is None or str(card.get("slot")) != f.name:
        raise ValueError("the card does not match the session state")
    raw = text
    if option_key is not None:
        if option_key == "cancel":
            return Cancelled()
        opt = next((o for o in card.get("options", []) if o.get("key") == option_key), None)
        if opt is None or opt.get("kind") == "OTHER" or opt.get("value") is None:
            raise ValueError("not an option of this card")
        raw = str(opt["value"])
    if raw.strip().casefold() in CANCEL_WORDS:
        return Cancelled()
    parsed = f.parse(raw, ctx, collected)
    if isinstance(parsed, Reject):
        again = _card(playbook, f, ctx, collected)
        return Ask(f"{parsed.why} {f.question(ctx, collected)}", again)
    collected[f.name] = parsed
    if len(collected) < len(fields):
        return _ask(playbook, fields, ctx, collected, prefix="")
    return Done(playbook, _to_inputs(playbook, collected))


def _to_inputs(playbook: str, c: Mapping[str, Any]) -> dict[str, Any]:
    """The same shape `playbook_inputs.validate_inputs` checks for the form (§6.33). Nothing is added that the seller did not give."""
    if playbook == "NEW_PRODUCT_DECISION":
        return {"sku": c["sku"], "quantity": c["quantity"], **c["window"]}
    fee = c["fee"]
    return {
        "competitor_url_id": c["competitor"], "sku": c["sku"], "marketplace": fee["marketplace"], "category": fee["category"], "fee_type": fee["fee_type"], "basis": c["basis"],
        "gst_rate_pct": c["gst_rate_pct"], "current_price_paise": c["current_price_paise"], "candidate_prices_paise": c["candidate_prices_paise"],
        "shipping": c["shipping"], "advertising": c["advertising"], "return_rto": c["return_rto"], "other": c["other"],
    }
