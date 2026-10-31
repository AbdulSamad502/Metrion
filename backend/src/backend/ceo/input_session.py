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

from backend.ceo import expense_chat, import_chat, memory, slot_resolvers
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
    unknown: bool = False  # choosing it records "unknown" on purpose (dependent figures show as unavailable); the UI may offer it as "Skip"


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
    applies: Callable[[Ctx, Mapping[str, Any]], bool] = lambda ctx, got: True  # False = not asked (e.g. a quote is already stored); the field is simply absent
    optional: bool = False  # a skippable extra detail: when the question limit is reached with only these left, the task goes on without them instead of stopping


# ------------------------------------------------------------------------------------------------ parsers
def _text(max_len: int = 120) -> Callable[[str, Ctx, Mapping[str, Any]], Any]:
    def parse(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
        t = " ".join(raw.split())
        return t if 0 < len(t) <= max_len else Reject(f"Please answer in at most {max_len} characters.")

    return parse


def _sku(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    """A SKU typed the way the seller lists it. When it is (or contains) one of their own products' title or id, the product's own id is stored, so the answer is the product
    and not the seller's sentence; anything else is kept as typed (a SKU the seller has not uploaded is still theirs to name)."""
    t = " ".join(raw.split())
    if not 0 < len(t) <= 120:
        return Reject("Please answer in at most 120 characters.")
    try:
        from backend.ceo import slot_resolvers  # noqa: PLC0415

        found = slot_resolvers.resolve_seller_product(ctx.tenant_id, t)
        if isinstance(found, slot_resolvers.ProductMatch):
            return found.product_id
        if isinstance(slot_resolvers.resolve_competitor(ctx.tenant_id, t), slot_resolvers.CompetitorMatch):
            names = "; ".join(f"“{title or pid}”" for pid, title in ceo_reads.list_seller_products(ctx.tenant_id)[:6])
            return Reject("That is one of your tracked competitors, not one of your products, so I cannot use it as the SKU." + (f" Your products: {names}." if names else ""))
    except Exception:  # noqa: BLE001 - a lookup problem never blocks the answer; it is kept as typed
        pass
    return t


_FREE_TEXT_FIELDS = frozenset({"seller_title", "niche", "product_name", "category", "category_hint", "supplier_name", "notes", "expense_note", "expense_vendor", "expense_reason", "expense_pick", "title_pick"})
_CANCEL_PHRASE = re.compile(r"\b(?:cancel|abort|never ?mind|forget (?:it|this|that)|stop (?:this|the|asking)|drop (?:this|it)|no thanks|not (?:my|an?) expense|(?:that'?s|that is|it'?s|it is) not (?:mine|an expense|my expense)|(?:do not|don'?t) add (?:it|this|that))\b", re.IGNORECASE)


def is_cancel_request(text: str) -> bool:
    """"Cancel this finance calculation", "never mind", "forget it": the seller is closing the open question, in any wording (not only the bare word)."""
    return bool(_CANCEL_PHRASE.search(text)) and len(text.split()) <= 6


_NEW_REQUEST_OPENER = re.compile(
    r"^(?:what|how|which|why|when|where|who|can you|could you|would you|please (?:show|give|tell|compare|calculate|explain|check|analy[sz]e)|show|give me|tell me|compare|calculate|explain|list|analy[sz]e|"
    r"check|help me|should i|am i|do i|is my|are my|create|run|find|add|record|import|remove|delete|mark|change|update)\b", re.IGNORECASE)


def _opens_a_new_request(t: str, closed: bool) -> bool:
    """A sentence that opens like a question or a command of its own (and is long enough to be one), or that a plain routing rule reads as a request, is not an answer to an open question.
    A free-text field (a note, a vendor) only yields to a real question mark: those answers are legitimately sentences."""
    words = len(t.split())
    if not closed:
        return "?" in t and words >= 5
    if words >= 4 and (_NEW_REQUEST_OPENER.match(t) or "?" in t):
        return True
    from backend.ceo import intent_router  # noqa: PLC0415 - local: the router must not be imported while this module loads

    return words >= 3 and intent_router.matches_a_rule(t)


def is_unrelated_to_open_question(card: Mapping[str, Any], text: str, ctx: Ctx) -> bool:
    """True when what the seller typed is clearly a NEW request and not an answer to the open question: it cannot be read as an answer AND it is a sentence or a question.
    A short or readable answer, and the cancel words, are always answers. Used so an open question never swallows the seller's next request."""
    t = " ".join(text.split())
    if not t or t.casefold() in CANCEL_WORDS:
        return False
    try:
        playbook = str(card.get("playbook") or (card.get("pending") or {}).get("key") or "")
        fields = SESSIONS.get(playbook)
        if fields is None:
            return False
        collected = dict((card.get("pending") or {}).get("collected") or {})
        f = _next_field(fields, ctx, collected)
        if f is None:
            return False
        closed = f.name not in _FREE_TEXT_FIELDS and not f.name.startswith("fact_")
        if closed and len(t.split()) >= 8:
            return True  # a closed question (an amount, a product, a choice) is answered in a few words: a long sentence is a new request, whatever else it mentions
        if _opens_a_new_request(t, closed):
            return True  # "What should I focus on to grow...?" is a question of its own, never the value a half-finished form was waiting for
        if not isinstance(f.parse(t, ctx, collected), Reject):
            return False
    except Exception:  # noqa: BLE001
        return False
    return len(t.split()) >= 5 or "?" in t


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


def _optional_whole(label: str) -> Callable[[str, Ctx, Mapping[str, Any]], Any]:
    """A whole number above zero, or None when the seller skips it (a missing MOQ / lead time is absent, never zero)."""
    def parse(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
        if raw.strip().casefold() in _SKIP_WORDS:
            return None
        t = raw.strip().replace(",", "")
        return int(t) if re.fullmatch(r"\d{1,6}", t) and int(t) > 0 else Reject(f"Give {label} as a whole number above zero, or skip it.")
    return parse


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
def _costs_gate(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = " ".join(raw.strip().casefold().replace("’", "'").split())
    if t in ("enter", "yes", "i know them", "enter them") or t.startswith("i will enter"):
        return "enter"
    if t in ("unknown", "no", "skip", "not yet") or re.search(r"\b(?:do not|don't|dont|do n't) know\b", t) or "not sure" in t:
        return "unknown"
    return Reject("Choose whether you will enter your shipping, advertising, returns and other costs now, or that you do not know them yet.")


def _enters_costs(ctx: Ctx, got: Mapping[str, Any]) -> bool:
    return got.get("costs_gate") == "enter"


COSTS_GATE = Field(
    "costs_gate", lambda ctx, got: "Do you know your shipping, advertising, returns and other costs per unit? If not, I leave them out and show only what can be worked out (nothing is guessed).", _costs_gate,
    lambda ctx, got: (Option("I will enter them", "enter", "I ask for each one"), Option("I do not know them yet", "unknown", "Margins that depend on them show as unavailable", unknown=True)),
)


def _cost_field(name: str, question: str) -> Field:
    return Field(
        name, lambda ctx, got: question, _cost,
        lambda ctx, got: (Option("None (0), I confirm", "none", "You are sure it is zero"), Option("Unknown", "unknown", "Margins that depend on it will show as unavailable", unknown=True)),
        applies=_enters_costs,
    )


def _competitor_options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    rows = [r for r in ceo_reads.list_active_competitors(ctx.tenant_id, limit=MAX_OPTIONS) if r.get("label")]
    base = tuple(Option(str(r["label"]), str(r["label"]), "A competitor you track") for r in rows)
    return _with_remembered(base, _remembered_choice(ctx, "CI", "last_competitor", lambda v: Option(v, v, _LAST_TIME), valid=lambda v: _is_tracked(ctx, v)))


def _fee_choices(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    return tuple(Option(f"{o['marketplace']} · {o['category']} · {o['fee_type']}", f"{o['marketplace']} {o['category']} {o['fee_type']}", "A combination with a fee rate")
                 for o in _fee_options(ctx)[:MAX_OPTIONS])


def _window_choices(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    end = ctx.today
    return tuple(
        Option(label, f"{(end - timedelta(days=days)).isoformat()} to {end.isoformat()}", "Sales history up to today")
        for label, days in (("Last 90 days", 90), ("Last 180 days", 180), ("Last 365 days", 365))
    )


def _rival_price_option(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    """CI's last captured price for the chosen competitor, offered as ONE choice (spec 6.38): the seller picks it, it is never filled in. The figure is CI's, shown with
    its date and a plain note when it is out of date."""
    from datetime import datetime, timezone

    from backend.ceo.figure_format import format_paise

    try:
        snap = ceo_reads.competitor_handoff(ctx.tenant_id, UUID(str(got.get("competitor"))), now=datetime.now(timezone.utc))
    except Exception:  # noqa: BLE001 - an offer is a convenience; the question is still asked
        return ()
    if isinstance(snap, ceo_reads.CiUnavailable) or snap.listed_price_paise is None or snap.capture_status not in ("COMPLETE", "PARTIAL"):
        return ()
    stale = "; out of date, captured before the usual freshness window" if snap.is_stale else ""
    return (Option(f"Match {snap.label or 'their'} price ({format_paise(snap.listed_price_paise)})", format_paise(snap.listed_price_paise), f"Their last captured price, {snap.captured_at.date().isoformat()}{stale}. Not verified by the marketplace"),)


PRICE_IMPACT: tuple[Field, ...] = (
    Field("competitor", lambda c, g: "Which competitor changed their price?", _competitor, _competitor_options,
          lambda c, g: None if ceo_reads.list_active_competitors(c.tenant_id, limit=1) else "No competitors are being tracked yet. Add one on the Competitor Intelligence page first."),
    Field("sku", lambda c, g: "Which SKU is this for? Type it the way you list it.", _sku),
    Field("fee", lambda c, g: "Which marketplace, category and fee type should I price it under?", _fee, _fee_choices,
          lambda c, g: None if _fee_options(c) else "No marketplace fee rates are set up yet, so I cannot price a margin. Ask your account owner to add them."),
    Field("basis", lambda c, g: "Do the prices you will give me include GST?", _basis,
          lambda c, g: _with_remembered((Option("Prices include GST", "inclusive"), Option("Prices exclude GST", "exclusive")),
                                        _remembered_choice(c, "CFO", "last_basis", lambda v: Option("Prices include GST" if v == "INCLUSIVE" else "Prices exclude GST", v.lower(), _LAST_TIME)))),
    Field("gst_rate_pct", lambda c, g: "What GST rate applies? Type a number such as 18.", _gst, lambda c, g: (Option("I do not know", "unknown", "GST-dependent margins will show as unavailable", unknown=True),)),
    Field("current_price_paise", lambda c, g: "What is your current selling price, in rupees?", _amount),
    Field("candidate_prices_paise", lambda c, g: "Which prices should I compare? Give rupee amounts separated by commas"
          + (f", up to {c.max_candidate_prices}." if c.max_candidate_prices else "."), _prices,
          _rival_price_option),
    COSTS_GATE,
    _cost_field("shipping", "What is the shipping cost per unit? Type an amount, or choose an option."),
    _cost_field("advertising", "What is the advertising cost per unit?"),
    _cost_field("return_rto", "What do returns and RTO cost you per unit?"),
    _cost_field("other", "Any other cost per unit?"),
)

# ------------------------------------------------------------------------------------------------ CMO listing content (spec 6.35)
_MARKETPLACE_NAMES = ("AMAZON", "FLIPKART", "MEESHO")
_SKIP_WORDS = frozenset({"skip", "none", "no", "n/a", "na", "not sure", "i do not know", "i don't know"})


def _marketplaces(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = raw.upper()
    found = [m for m in _MARKETPLACE_NAMES if m in t]
    if "ALL" in re.findall(r"[A-Z]+", t) and not found:
        found = list(_MARKETPLACE_NAMES)
    return found or Reject("I could not find a marketplace in that (Amazon, Flipkart or Meesho).")


def _one_marketplace(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    found = _marketplaces(raw, ctx, got)
    if isinstance(found, Reject):
        return found
    return found[0] if len(found) == 1 else Reject("This one is written for one marketplace at a time. Which one first: " + ", ".join(m.title() for m in found) + "?")


def _optional_marketplace(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    return None if raw.strip().casefold() in _SKIP_WORDS else _one_marketplace(raw, ctx, got)


def _optional_text(max_len: int) -> Callable[[str, Ctx, Mapping[str, Any]], Any]:
    base = _text(max_len)

    def parse(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
        return None if raw.strip().casefold() in _SKIP_WORDS else base(raw, ctx, got)

    return parse


def _MARKETPLACE_OPTIONS(ctx: Ctx, got: Mapping[str, Any]) -> tuple[Option, ...]:  # noqa: N802
    """Amazon, Flipkart, Meesho: the ones in the seller's business profile first (and only those, when the profile lists any), so the seller is not offered a marketplace they do not use."""
    try:
        mine = ceo_reads.business_marketplaces(ctx.tenant_id)
    except Exception:  # noqa: BLE001 - a profile read problem only means all three are offered
        mine = []
    names = [m for m in _MARKETPLACE_NAMES if not mine or m.upper() in mine] or list(_MARKETPLACE_NAMES)
    return tuple(Option(m.title(), m.title(), "A marketplace in your business profile" if mine else "") for m in names)

_LAST_TIME = "What you chose last time"


def _remembered_choice(ctx: Ctx, agent: str, key: str, make: Callable[[str], Option], valid: Callable[[str], bool] | None = None) -> Option | None:
    """An agent's own remembered choice (spec agent-memory.md section 11) as ONE option, or None. Memory is a convenience: a failure or an invalid value offers nothing."""
    try:
        v = memory.offered(ctx.tenant_id, agent, key)
        return make(v) if v is not None and (valid is None or valid(v)) else None
    except Exception:  # noqa: BLE001
        return None


def _with_remembered(base: Sequence[Option], mine: Option | None) -> tuple[Option, ...]:
    """The remembered option first, then the existing options (one with the same text is not repeated), at most MAX_OPTIONS in all."""
    if mine is None:
        return tuple(base)[:MAX_OPTIONS]
    return (mine, *(o for o in base if o.text.casefold() != mine.text.casefold()))[:MAX_OPTIONS]


def _is_tracked(ctx: Ctx, label: str) -> bool:
    return any(str(r.get("label")) == label for r in ceo_reads.list_active_competitors(ctx.tenant_id, limit=200))


def _cmo_marketplace_options(single: bool, *, skip: bool = False) -> Callable[[Ctx, Mapping[str, Any]], Sequence[Option]]:
    """The marketplace question's options with CMO's remembered choice first. A one-marketplace question only offers a remembered single marketplace."""
    def options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
        base = (*_MARKETPLACE_OPTIONS(ctx, got), *((Option("Skip", "skip", "Not tied to one marketplace"),) if skip else ()))
        mine = _remembered_choice(ctx, "CMO", "last_marketplaces", lambda v: Option(", ".join(p.title() for p in v.split(", ")), ", ".join(p.title() for p in v.split(", ")), _LAST_TIME),
                                  valid=(lambda v: "," not in v) if single else None)
        return _with_remembered(base, mine)

    return options


_SKIP = lambda why: (lambda ctx, got: (Option("Skip", "skip", why),))  # noqa: E731
_PRONOUNS = frozenset({"it", "this", "that", "this one", "that one", "this product", "that product", "the product", "my product", "the same", "same", "same product", "the same product", "them"})


def _product_text(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    """The product the seller sells, in their own words. A pronoun ("it", "this product") is NOT a product name: it is asked for again, never stored as if it were one."""
    t = " ".join(raw.split())
    if t.casefold().strip(" .!?") in _PRONOUNS:
        return Reject("Please name the product itself, for example steel water bottle.")
    return _text(200)(raw, ctx, got)


# ---- facts read from an attached product photo (ceo-cmo-delegation.md CD2, 6.4). The hidden entries "_obs" / "_attachment" ride in `collected` (JSON, text only); they are never an
# input of the CMO action. An observation is only ever OFFERED as a one-click confirmation of the SELLER's own statement; it is never filled in, and visible text is never offered.
IMAGE_FACT_ATTRS: tuple[str, ...] = ("color", "material", "size", "brand")  # asked one by one, only when the photo showed a value; product_type is offered for the product name
_FROM_ATTACHMENT = "From your attachment: a suggestion, not verified. Choosing it confirms it as your own statement"


def observed(got: Mapping[str, Any]) -> Mapping[str, str]:
    obs = got.get("_obs")
    return {k: v for k, v in obs.items() if isinstance(k, str) and isinstance(v, str) and v.strip()} if isinstance(obs, Mapping) else {}


def _product_question(ctx: Ctx, got: Mapping[str, Any]) -> str:
    seen = observed(got).get("product_type")
    if seen:
        return f"What is the product? Your attachment looks like a {seen} (read from the photo, not verified). Confirm that, or type the product the way a buyer would search for it."
    return ("What is the product? Name it the way a buyer would search for it. If you would rather show me, attach a photo of it and ask again: I will read what is visible and "
            "ask you to confirm each detail.")


def _product_options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    seen = observed(got).get("product_type")
    return (Option(f"Yes, a {seen}", seen, _FROM_ATTACHMENT),) if seen and len(seen) <= 200 else ()


_PRODUCT = Field("product_name", _product_question, _product_text, _product_options)


def _fact_field(attr: str) -> Field:
    return Field(
        f"fact_{attr}",
        lambda c, g: f"Your attachment suggests the {attr} is \u201c{observed(g).get(attr, '')}\u201d (read from the photo, not verified). Is that right? Confirm it, type the correct {attr}, or skip.",
        _optional_text(60),
        lambda c, g: (Option(f"Yes, {observed(g).get(attr, '')}", observed(g).get(attr, ""), _FROM_ATTACHMENT), Option("Skip", "skip", f"The {attr} is not used")),
        applies=lambda c, g, a=attr: bool(observed(g).get(a)),
    )


IMAGE_FACT_FIELDS: tuple[Field, ...] = tuple(_fact_field(a) for a in IMAGE_FACT_ATTRS)
TITLE_OPTIONS = "__title_options__"  # the value of the "write title options for me first" choice; only ever arrives from that option (a typed copy of it is refused)


def _seller_title_options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    """The title the seller already approved for this product and marketplace comes first (the copy is then grounded on that approval); their product name is the fallback."""
    from backend.ceo import cmo_chat  # noqa: PLC0415

    out: list[Option] = []
    approved = cmo_chat.approved_title_text(ctx.tenant_id, got.get("product_name"), got.get("marketplace"))
    if approved:
        out.append(Option(f"Use the title you approved: “{approved[:90]}{'…' if len(approved) > 90 else ''}”", approved, "You chose this title earlier"))
    if got.get("product_name"):
        out.append(Option(f"Use “{got['product_name']}”", str(got["product_name"]), "Your product name, as you gave it"))
    if not approved and got.get("product_name"):  # N-05b: no approved title yet, so the title steps can run inside this listing request
        out.append(Option("Write title options for me first (1 CMO unit)", TITLE_OPTIONS, "I write options, you choose one, then the listing is written from it"))
    return out


def _seller_title_question(ctx: Ctx, got: Mapping[str, Any]) -> str:
    """N-05b: with no approved title for this product and marketplace the question says so plainly, and says how to get title options first. A number picks a listed choice; a title typed here is used as typed."""
    from backend.ceo import cmo_chat  # noqa: PLC0415

    base = "What title do you use for it today (or want to use)? I will write from it, so what you give me is what the copy is based on."
    if cmo_chat.approved_title_text(ctx.tenant_id, got.get("product_name"), got.get("marketplace")):
        return base
    return ("You have not approved a title for this product on this marketplace yet. " + base +
            " If you would rather choose from options, say “cancel” and ask me for titles for this product first; once you approve one, ask for the complete listing again.")


_SELLER_TITLE = Field("seller_title", _seller_title_question, _text(500), _seller_title_options)


def _typed_title_applies(ctx: Ctx, got: Mapping[str, Any]) -> bool:
    """N-05t: a title that is not the seller's approved one (one they typed, or their product name) is used only after they confirm it as it stands. An approved title needs no second step."""
    from backend.ceo import cmo_chat  # noqa: PLC0415

    t = got.get("seller_title")
    if not isinstance(t, str) or t == TITLE_OPTIONS:
        return False
    return t != cmo_chat.approved_title_text(ctx.tenant_id, got.get("product_name"), got.get("marketplace"))


def _confirm_typed_title(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = " ".join(raw.casefold().split())
    if t in ("yes", "y", "yes, use this exact title", "use it", "use this title"):
        return "yes"
    if t in ("change", "no", "no, let me change it", "change it", "no, change it"):
        return "change"
    return Reject("Say yes to use exactly this title, or no to type a different one.")


_TYPED_TITLE_OK = Field(
    "_typed_title_ok",
    lambda c, g: (f"You gave this title: “{str(g.get('seller_title'))[:200]}”. It is not an approved title option, so I will not treat it as one. Do you confirm the listing should be written from exactly this title? "
                  "This only confirms the title; nothing is written or charged until you approve the plan."),
    _confirm_typed_title,
    lambda c, g: (Option("Yes, use exactly this title", "yes", "I will write from it as typed"), Option("No, let me change it", "change", "Type a different title")),
    applies=_typed_title_applies,
)

def _fit(words: Sequence[str], limit: int = 100) -> str:
    out: list[str] = []
    for w in words:
        if len(", ".join([*out, w])) > limit:
            break
        out.append(w)
    return ", ".join(out)


def _theme_options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    """Themes the seller's other agents already hold, OFFERED as the category hint (spec 6.39): Product Intelligence's keyword themes for this idea, and the keywords of a
    tracked competitor's captured listing. Both are labelled as not verified; neither is ever filled in."""
    from datetime import datetime, timezone

    out: list[Option] = []
    try:
        pi = ceo_reads.pi_idea_keywords(ctx.tenant_id, str(got.get("product_name", "")))
        if pi:
            out.append(Option("Use Product Intelligence's themes", _fit(pi), "Keyword themes from public web sources for this idea. Not verified"))
    except Exception:  # noqa: BLE001 - an offer is a convenience; the question is still asked
        pass
    try:
        ci = ceo_reads.ci_listing_keywords(ctx.tenant_id, now=datetime.now(timezone.utc))
        if ci:
            out.append(Option(f"Use {ci[0]}'s listing keywords", _fit(ci[1]), "From a competitor listing you track; it may not match your product. Not verified"))
    except Exception:  # noqa: BLE001
        pass
    return (*out, Option("Skip", "skip", "Titles are written without a category hint"))[:MAX_OPTIONS]


def _marketplace_question(noun: str) -> str:
    return f"Which marketplace do you want {noun} for (Amazon, Flipkart, Meesho)?"


def _detail(attr: str, question: str, why: str, max_len: int = 200) -> Field:
    """An optional, skippable high-value detail the seller may add (brand, size, features...). It is the seller's own statement, never guessed and never filled in; skipping it is fine
    (the result then warns that the input was thin). Where a photo already suggested a value for the same detail, the photo-confirmation question is asked instead."""
    return Field(
        f"fact_{attr}", lambda c, g: question, _optional_text(max_len), _SKIP(why), applies=lambda c, g, a=attr: not observed(g).get(a), optional=True,
    )


_BRAND_Q = _detail("brand", "What is the brand? Skip it if it has none.", "No brand is used", 80)
_SIZE_Q = _detail("size", "What size or capacity is it (for example 1 litre, large, 500 g)? Skip it if not relevant.", "No size is used", 60)
_FEATURES_Q = _detail("key_features", "What are 1 to 3 key features buyers care about? Only what is true; I add none of my own. Skip if you would rather not say.", "No features are used")
_USE_Q = _detail("main_use", "What is it mainly used for, or who is it for (for example gym, school, office, kids)? Skip if not relevant.", "No main use is used", 120)
_KEYWORDS_Q = _detail("search_keywords", "Any 1 to 3 search words you want people to find it by? Separate them with commas, or skip.", "No extra search words are used", 120)

_COMMON_FIRST = (_PRODUCT, *IMAGE_FACT_FIELDS)
CMO_TITLES: tuple[Field, ...] = (
    *_COMMON_FIRST,
    Field("category_hint", lambda c, g: "Which category is it in? For example kitchen, apparel, electronics. Or choose themes I already hold.", _optional_text(100), _theme_options, optional=True),
    Field("marketplaces", lambda c, g: _marketplace_question("titles"), _marketplaces, _cmo_marketplace_options(False)),
    _BRAND_Q, _SIZE_Q, _FEATURES_Q,
)
CMO_HASHTAGS: tuple[Field, ...] = (
    *_COMMON_FIRST,
    Field("marketplace", lambda c, g: _marketplace_question("hashtags"), _optional_marketplace, _cmo_marketplace_options(True, skip=True)),
    _BRAND_Q, _FEATURES_Q,
)


def _grounded(noun: str) -> tuple[Field, ...]:
    return (
        *_COMMON_FIRST,
        Field("marketplace", lambda c, g: _marketplace_question(noun), _one_marketplace, _cmo_marketplace_options(True)),
        _SELLER_TITLE,
        _BRAND_Q, _SIZE_Q, _FEATURES_Q,
    )


CMO_DESCRIPTION, CMO_KEYWORDS, CMO_BULLETS, CMO_LISTING = _grounded("a description"), _grounded("keywords"), _grounded("bullets"), _grounded("the listing copy")


_YES_WORDS_HASHTAGS = frozenset({"yes", "y", "yeah", "yep", "sure", "ok", "okay", "please", "add"})


def _hashtags_yes(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = " ".join(raw.casefold().split())
    if t in _SKIP_WORDS or t in ("no hashtags", "without hashtags", "not now"):
        return None
    words = re.findall(r"[a-z']+", t)
    return True if words and words[0] in _YES_WORDS_HASHTAGS else Reject("Say yes to add hashtag suggestions (1 extra unit), or skip.")


CMO_FULL_LISTING = (
    *(x for f in _grounded("the complete listing") for x in ((f, _TYPED_TITLE_OK) if f is _SELLER_TITLE else (f,))),  # CMO 3.0 M6; a title that is not approved is confirmed by the seller first (N-05t)
    Field("include_hashtags", lambda c, g: "Do you also want marketing hashtag suggestions? They cost 1 extra CMO unit and are not a listing field on any marketplace. Say yes, or skip.",
          _hashtags_yes, lambda c, g: (Option("Yes, add hashtags (1 extra unit)", "yes", "Hashtag suggestions are added"), Option("Skip", "skip", "No hashtags")), optional=True),
)
_BULLET_REF = re.compile(r"\bbullet(?:\s*point)?s?\s*(?:#|no\.?|number)?\s*(\d{1,2})\b")


def _rewrite_target(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = " ".join(raw.casefold().split())
    if "description" in t:
        return "description"
    m = _BULLET_REF.search(t) or re.fullmatch(r"(\d{1,2})", t)
    if m and 1 <= int(m.group(1)) <= 20:
        return f"bullet:{int(m.group(1))}"
    return Reject("Which part should I rewrite: one bullet (for example bullet 3) or the description? The title and keywords are not rewritten here.")


CMO_REWRITE: tuple[Field, ...] = (  # CMO 3.0 M6 (Q26): the section and the topic; the saved version itself is found by code, never typed
    _PRODUCT,
    Field("marketplace", lambda c, g: _marketplace_question("the rewrite"), _one_marketplace, _cmo_marketplace_options(True)),
    Field("rewrite_target", lambda c, g: "Which part should I rewrite: one bullet (for example bullet 3) or the description?", _rewrite_target,
          lambda c, g: (Option("The description", "description", "Rewrites only the description"), Option("Bullet 1", "bullet 1", "Rewrites only bullet 1"), Option("Bullet 2", "bullet 2", "Rewrites only bullet 2"))),
    Field("rewrite_topic", lambda c, g: "What should it mention? Use a few words about something you have confirmed (for example \u201cwide opening\u201d). I will not write about anything you have not confirmed.",
          _text(80), lambda c, g: ()),
)
CMO_GROUNDED = CMO_BULLETS  # kept for importers that only need "the grounded shape"; each action has its own table so the question names what is being written


def _amazon_only(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    found = _one_marketplace(raw, ctx, got)
    if isinstance(found, Reject):
        return found
    return found if found == "AMAZON" else Reject("Backend search terms are an Amazon-only field, so this can only be written for Amazon. Type Amazon.")


CMO_BACKEND_TERMS: tuple[Field, ...] = (
    *_COMMON_FIRST,
    Field("marketplace", lambda c, g: "Backend search terms are an Amazon field. Confirm Amazon.", _amazon_only, lambda c, g: (Option("Amazon", "Amazon"),)),
    _SELLER_TITLE,
    _BRAND_Q, _FEATURES_Q,
)
# ---- CMO 3.0 M0: choosing one of the title options in chat (cmo.approve_title) and asking for catalog details (cmo.catalog_answer) ----
def _title_sets(ctx: Ctx) -> list[dict[str, Any]]:
    from backend.ceo import cmo_chat  # noqa: PLC0415

    return cmo_chat.title_sets(ctx.tenant_id)


def _chosen_set(ctx: Ctx, got: Mapping[str, Any]) -> Mapping[str, Any] | None:
    from backend.ceo import cmo_chat  # noqa: PLC0415

    return cmo_chat.choose_set(_title_sets(ctx), got.get("title_marketplace"))


def _title_marketplace(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    have = {s["marketplace"] for s in _title_sets(ctx)}
    found = [m for m in _MARKETPLACE_NAMES if m in raw.upper() and m in have]
    return found[0] if len(found) == 1 else Reject("Which marketplace's titles: " + ", ".join(m.title() for m in sorted(have)) + "?")


def _title_marketplace_options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    return tuple(Option(str(s["marketplace"]).title(), str(s["marketplace"]).title(), "Your newest title options for it") for s in _title_sets(ctx)[:MAX_OPTIONS])


def _title_pick_question(ctx: Ctx, got: Mapping[str, Any]) -> str:
    from backend.ceo import cmo_chat  # noqa: PLC0415

    chosen = _chosen_set(ctx, got)
    if chosen is None:
        return "Which title do you want to use?"
    return (f"Here are your {str(chosen['marketplace']).title()} title options:\n{cmo_chat.options_text(chosen)}\n"
            "Which one do you want to use? Pick one below, say its number, or type the exact title you want. Only the title you choose is saved as your choice.")


def _title_pick(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    from backend.ceo import cmo_chat  # noqa: PLC0415

    chosen = _chosen_set(ctx, got)
    if chosen is None:
        return Reject("I could not find title options to choose from. Ask me to write titles first.")
    found = cmo_chat.parse_choice(raw, chosen["options"])
    if found is None:
        return Reject(f"Say the number of the title you want (1 to {len(chosen['options'])}), or type the exact title you want to use in full.")
    kind, value = found
    return f"{chosen['generationId']}|option|{value['id']}" if kind == "OPTION" else f"{chosen['generationId']}|edit|{value}"


def _title_pick_options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    chosen = _chosen_set(ctx, got)
    if chosen is None:
        return ()
    return tuple(Option(f"Use option {o['rank']}", str(o["rank"]), o["text"][:140]) for o in chosen["options"][:MAX_OPTIONS])


def _no_titles(ctx: Ctx, got: Mapping[str, Any]) -> str | None:
    return None if _title_sets(ctx) else "You have no title options saved yet, so there is nothing to choose from. Ask me to write titles for a product first. Nothing was saved."


CMO_APPROVE_TITLE: tuple[Field, ...] = (
    Field("title_marketplace", lambda c, g: "You have title options for more than one marketplace. Which one are you choosing for?", _title_marketplace, _title_marketplace_options,
          unanswerable=_no_titles, applies=lambda c, g: len(_title_sets(c)) > 1),
    Field("title_pick", _title_pick_question, _title_pick, _title_pick_options, unanswerable=_no_titles),
)

_CATALOG_WORDS: Mapping[str, tuple[str, ...]] = {
    "CATEGORY": ("category", "categories", "browse node", "department"), "COLOR": ("colour", "color", "colours", "colors"), "MATERIAL": ("material", "made of", "made from"),
    "SIZE": ("size", "capacity", "volume"), "WEIGHT": ("weight",), "DIMENSIONS": ("dimension", "dimensions", "measurements"), "BRAND": ("brand",),
}
CATALOG_ALL = ("CATEGORY", "COLOR", "MATERIAL", "SIZE", "WEIGHT", "DIMENSIONS", "BRAND")


def _catalog_questions(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = " ".join(raw.casefold().split()).strip(" .!?")
    if t in ("all", "everything", "all of them", "all details", "all of these"):
        return ",".join(CATALOG_ALL)
    found = [name for name, words in _CATALOG_WORDS.items() if any(re.search(rf"\b{re.escape(w)}\b", t) for w in words)]
    return ",".join(found) if found else Reject("Name the details you want (category, colour, material, size, weight, dimensions, brand), or say all.")


CMO_KEYWORD_INTEL: tuple[Field, ...] = (
    _PRODUCT,
    Field("marketplace", lambda c, g: "Which marketplace is it for (Amazon, Flipkart, Meesho)? It only changes where the lower-priority keywords go. You can skip this.", _optional_marketplace,
          _cmo_marketplace_options(True, skip=True), optional=True),
)

CMO_ANALYZE_TITLES: tuple[Field, ...] = (
    Field("title_marketplace", lambda c, g: "You have title options for more than one marketplace. Which one should I compare?", _title_marketplace, _title_marketplace_options,
          unanswerable=_no_titles, applies=lambda c, g: len(_title_sets(c)) > 1),
)

CMO_CATALOG: tuple[Field, ...] = (
    *_COMMON_FIRST,
    Field("catalog_questions", lambda c, g: "Which details do you want me to work out for this product: category, colour, material, size, weight, dimensions, brand? Say all, or name them.",
          _catalog_questions, lambda c, g: (Option("All of them", "all", "Each answer says whether it is your own statement, estimated or unknown"), Option("Colour, material and size", "colour, material, size"))),
    _BRAND_Q, _SIZE_Q, _FEATURES_Q,
)


def _niche(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = " ".join(raw.split())
    if not (2 <= len(t) <= 100) or re.fullmatch(r"[\d\s.,₹-]+", t):
        return Reject("Name the niche or category in words, for example mens shoes, kitchen storage or yoga wear.")
    return t


def _price_range(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    if raw.strip().casefold() in _SKIP_WORDS:
        return None
    parts = [p for p in re.split(r"\s*(?:-|–|—|\bto\b)\s*", raw.strip()) if p]
    values = [slot_resolvers.parse_amount_paise(p) for p in parts]
    if len(values) != 2 or any(v is None for v in values) or values[0] >= values[1]:  # type: ignore[operator]
        return Reject("Give the selling price range as two rupee amounts, for example 500 to 1,500, or skip it.")
    return {"min": values[0], "max": values[1]}


_YES_WORDS = frozenset({"yes", "y", "yeah", "yep", "yup", "ok", "okay", "sure", "confirm", "confirmed", "proceed", "go", "run", "do", "save", "please", "ahead", "it", "now", "and"})
_NO_WORDS = frozenset({"no", "not", "dont", "don't", "cancel", "stop", "wait", "never", "nope"})


def _yes(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    words = re.findall(r"[a-z']+", raw.casefold())
    if words and len(words) <= 6 and not (set(words) & _NO_WORDS) and words[0] in _YES_WORDS and all(w in _YES_WORDS for w in words):
        return True  # "yes", "yes run it", "yes, run it", "ok go ahead"
    return Reject("Say yes to run it, or cancel.")


def _pi_summary(ctx: Ctx, got: Mapping[str, Any]) -> str:
    from backend.ceo.figure_format import format_paise

    where = ", ".join(str(m).title() for m in got.get("marketplaces", []))
    rng = got.get("price_range")
    span = f", selling between {format_paise(rng['min'])} and {format_paise(rng['max'])}" if rng else ""
    return (f"Here is what I will research: {got.get('category')} on {where}, with a budget of {format_paise(got.get('budget'))}{span}. "
            "I will save this as your research brief and run Product Intelligence. Shall I go ahead?")


def _remembered(key: str, label: Callable[[str], str], text: Callable[[str], str]) -> Callable[[Ctx, Mapping[str, Any]], Sequence[Option]]:
    """Offer what the seller confirmed last time (PI's private memory) as ONE choice; it is never filled in silently."""
    def options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
        try:
            v = memory.pi_defaults(ctx.tenant_id).get(key)
        except Exception:  # noqa: BLE001 - memory is a convenience; the question is still asked
            v = None
        return (Option(label(v), text(v), "What you chose last time"),) if v else ()

    return options


def _rupees(paise: str) -> str:
    from backend.ceo.figure_format import format_paise

    return format_paise(int(paise))


PI_DISCOVER: tuple[Field, ...] = (
    Field("category", lambda c, g: "Which niche or category should I find products in? For example mens shoes.", _niche, _remembered("last_category", lambda v: v, lambda v: v)),
    Field("budget", lambda c, g: "What is your budget for stocking a product, in rupees? For example 20,000.", _amount,
          _remembered("last_budget_paise", _rupees, lambda v: f"{int(v) // 100}.{int(v) % 100:02d}")),
    Field("marketplaces", lambda c, g: "Which marketplace will you sell on? You can name more than one.", _marketplaces,
          lambda c, g: (*_remembered("last_marketplaces", lambda v: v.title(), lambda v: v)(c, g), *_MARKETPLACE_OPTIONS(c, g))[:MAX_OPTIONS]),
    Field("price_range", lambda c, g: "Roughly what selling price range do you have in mind? For example 500 to 1,500. You can skip this.", _price_range, _SKIP("The search is not limited to a price range")),
    # No research-depth question: PI records quick/complete but both run the same research today (product-intelligence-agent.md D2), so asking would promise a difference that does not exist.
    Field("confirm", _pi_summary, _yes, lambda c, g: (Option("Yes, run it", "yes"),)),
)

def _optional_amount(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    return None if raw.strip().casefold() in _SKIP_WORDS else _amount(raw, ctx, got)


def _needs_quote(ctx: Ctx, got: Mapping[str, Any]) -> bool:
    try:
        return not ceo_reads.stored_quotes(ctx.tenant_id, str(got.get("sku")))
    except Exception:  # noqa: BLE001 - if the store cannot be read, ask: the confirm card still decides what is saved
        return True


def _needs_budget(ctx: Ctx, got: Mapping[str, Any]) -> bool:
    try:
        return not ceo_reads.stored_budget(ctx.tenant_id)
    except Exception:  # noqa: BLE001
        return True


def _np_summary(ctx: Ctx, got: Mapping[str, Any]) -> str:
    from backend.ceo.figure_format import format_paise

    parts: list[str] = []
    if "supplier_name" in got:
        ship = f", with {format_paise(got['order_shipping'])} shipping for the whole order" if got.get("order_shipping") else ""
        extra = "".join(f", {label} {got[k]}" for k, label in (("moq", "a minimum order of"), ("lead_time_days", "a lead time in days of")) if got.get(k))
        parts.append(f"a supplier quote from {got['supplier_name']} at {format_paise(got['unit_cost'])} per unit{ship}{extra}")
    if "budget" in got:
        parts.append(f"a batch budget of {format_paise(got['budget'])}")
    return (f"Here is what I will save as your own figures: {' and '.join(parts)}. Then I will run the numbers (landed cost, supplier ranking and batch size) for "
            f"{got.get('sku')}. Shall I go ahead?")


def _quote_applies(ctx: Ctx, got: Mapping[str, Any]) -> bool:
    return _needs_quote(ctx, got)


def _product_leads(ctx: Ctx, got: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Supplier leads Product Intelligence found for the product being stocked (best evidenced first), or [] (a read that fails just offers nothing)."""
    try:
        return list(ceo_reads.pi_product_suppliers(ctx.tenant_id, str(got.get("sku") or "")))
    except Exception:  # noqa: BLE001 - offering leads is a convenience; the question is still asked
        return []


def _supplier_options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    """The suppliers Product Intelligence already found for this product, offered as choices (never filled in): the seller must pick one or type another."""
    out: list[Option] = []
    for lead in _product_leads(ctx, got):
        name = " ".join(str(lead.get("supplier_name") or "").split())[:80]
        if name and all(o.text != name for o in out):
            where = f" ({str(lead['locality'])[:30]})" if lead.get("locality") else ""
            out.append(Option(name[:55] + where, name, "Found by Product Intelligence: a web lead, not verified"))
    return tuple(out[:3])


def _unit_cost_options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    """A price the chosen supplier PUBLISHES, offered as a choice with its source: it is the supplier's page, not a quote, so picking it is the seller's own decision."""
    chosen = " ".join(str(got.get("supplier_name") or "").split()).casefold()
    for lead in _product_leads(ctx, got):
        price = lead.get("published_price")
        if price and " ".join(str(lead.get("supplier_name") or "").split()).casefold() == chosen:
            low = int(price["low_paise"])
            return (Option(f"{_rupees(str(low))} per {price.get('unit') or 'unit'} (published by this supplier)", f"{low // 100}.{low % 100:02d}",
                           "Published on the supplier's own page; not a quote. Pick it only if the supplier confirmed it"),)
    return ()


def _budget_options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    """The budget the seller already stated in the research brief that found this product, offered as one choice (reused, never re-asked from scratch, never filled in silently)."""
    try:
        stated = ceo_reads.pi_research_budget(ctx.tenant_id, str(got.get("sku") or ""))
    except Exception:  # noqa: BLE001 - a convenience only
        return ()
    if not stated:
        return ()
    low = int(stated)
    return (Option(f"{_rupees(str(low))} (the budget you gave for this research)", f"{low // 100}.{low % 100:02d}", "Your own figure from the research brief"),)


def _lead_time(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    """Lead time in days. It may be skipped only when the minimum order quantity was given: for a product never sold, the batch-size estimate needs one of the two (the stored quote
    cannot be amended later, so it is asked now)."""
    if raw.strip().casefold() in _SKIP_WORDS:
        if got.get("moq") is None:
            return Reject("I need either the minimum order quantity or the delivery lead time, or the units estimate cannot be worked out for a product you have never sold. Type the lead time in days (for example 21), or use Back to give the minimum order quantity.")
        return None
    return _optional_whole("the lead time in days")(raw, ctx, got)


NEW_PRODUCT: tuple[Field, ...] = (
    Field("sku", lambda c, g: "Which SKU are you thinking of stocking? Type it the way you list it.", _text()),
    Field("quantity", lambda c, g: "How many units are you considering?", _quantity),
    Field("window", lambda c, g: "Which sales-history period should I look at?", _window, _window_choices),
    Field("supplier_name", lambda c, g: "I have no supplier quote saved for this product. Which supplier is it from? Pick one Product Intelligence found, or type the supplier's name.", _text(80), _supplier_options, applies=_quote_applies),
    Field("unit_cost", lambda c, g: "What is that supplier's price per unit, in rupees? (Use the price they quoted you.)", _amount, _unit_cost_options, applies=_quote_applies),
    Field("order_shipping", lambda c, g: "What is the shipping for the whole order, in rupees? Skip it if the quote does not state it.", _optional_amount,
          _SKIP("Not stated; margins that need it stay unavailable"), applies=_quote_applies),
    Field("moq", lambda c, g: "What is the supplier's minimum order quantity, in units? Skip it if the quote does not state it. (The batch-size estimate needs this or the lead time for a product you have never sold.)",
          _optional_whole("the minimum order quantity"), _SKIP("Not stated"), applies=_quote_applies),
    Field("lead_time_days", lambda c, g: "How many days does the supplier take to deliver? You can skip this only if you gave the minimum order quantity.", _lead_time, _SKIP("Not stated"), applies=_quote_applies),
    Field("budget", lambda c, g: "What is your budget for this batch, in rupees? I will fit the quantity to it.", _amount, _budget_options, applies=lambda c, g: _needs_budget(c, g)),
    Field("confirm", _np_summary, _yes, lambda c, g: (Option("Yes, save and run", "yes"),), applies=lambda c, g: _needs_quote(c, g) or _needs_budget(c, g)),
)


def _dr_summary(what: Callable[[Mapping[str, Any]], str]) -> Callable[[Ctx, Mapping[str, Any]], str]:
    def q(ctx: Ctx, got: Mapping[str, Any]) -> str:
        return f"Here is what I will save as your own figure: {what(got)}. Then I will run your question again with it. Shall I go ahead?"

    return q


def _money(paise: Any) -> str:
    from backend.ceo.figure_format import format_paise

    return format_paise(int(paise))


_DR_CONFIRM_OPTIONS = lambda c, g: (Option("Yes, save and run again", "yes"),)  # noqa: E731

DR_COGS: tuple[Field, ...] = (
    Field("sku", lambda c, g: "", _text()),
    Field("cost", lambda c, g: f"I need your cost per unit for {g.get('sku')} to work out the margin. What does one unit cost you, in rupees?", _amount),
    Field("confirm", _dr_summary(lambda g: f"a cost per unit of {_money(g['cost'])} for {g['sku']}"), _yes, _DR_CONFIRM_OPTIONS),
)
DR_QUOTE: tuple[Field, ...] = (
    Field("sku", lambda c, g: "", _text()),
    Field("supplier_name", lambda c, g: f"I need a supplier quote for {g.get('sku')}. Which supplier is it from?", _text(80)),
    Field("unit_cost", lambda c, g: "What is that supplier's price per unit, in rupees?", _amount),
    Field("order_shipping", lambda c, g: "What is the shipping for the whole order, in rupees? Skip it if the quote does not state it.", _optional_amount, _SKIP("Not stated; margins that need it stay unavailable")),
    Field("moq", lambda c, g: "What is the supplier's minimum order quantity, in units? Skip it if the quote does not state it.", _optional_whole("the minimum order quantity"), _SKIP("Not stated")),
    Field("lead_time_days", lambda c, g: "How many days does the supplier take to deliver? Skip it if the quote does not state it.", _optional_whole("the lead time in days"), _SKIP("Not stated")),
    Field("confirm", _dr_summary(lambda g: f"a supplier quote from {g['supplier_name']} at {_money(g['unit_cost'])} per unit for {g['sku']}"), _yes, _DR_CONFIRM_OPTIONS),
)
DR_BUDGET: tuple[Field, ...] = (
    Field("sku", lambda c, g: "", _text()),
    Field("budget", lambda c, g: "I need your budget for this batch. How much can you spend, in rupees?", _amount),
    Field("confirm", _dr_summary(lambda g: f"a batch budget of {_money(g['budget'])}"), _yes, _DR_CONFIRM_OPTIONS),
)

def _optional_marketplaces(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    return [] if raw.strip().casefold() in _SKIP_WORDS else _marketplaces(raw, ctx, got)


def _niche_terms(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    """The niche the seller wants researched (ceo-cmo-delegation.md CD12): "skip" -> None (marketplace news only), "use my confirmed terms" -> the marker KEEP, otherwise up to
    5 short terms separated by commas. CMO's own screening still decides whether each term may be saved and sent; nothing here is guessed."""
    t = " ".join(raw.split())
    if t.casefold() in _SKIP_WORDS:
        return None
    if t.casefold() in ("use my confirmed terms", "keep", "keep my confirmed terms", "use confirmed"):
        return KEEP_CONFIRMED
    terms = [x.strip() for x in re.split(r"[,;]", t) if x.strip()]
    if not terms or len(terms) > 5 or any(not (2 <= len(x) <= 60) for x in terms) or any(re.fullmatch(r"[\d\s.,%-]+", x) for x in terms):
        return Reject("Name the niche in words: up to five short terms separated by commas, for example steel water bottle, insulated flask. Or skip it.")
    return terms


def _niche_options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    try:
        have = ceo_reads.confirmed_niche_terms(ctx.tenant_id)
    except Exception:  # noqa: BLE001 - an offer is a convenience; the question is still asked
        have = []
    keep = (Option("Use my confirmed terms: " + ", ".join(have[:5]), "use my confirmed terms", "Terms you confirmed earlier; I will not change them"),) if have else ()
    return (*keep, Option("Skip", "skip", "Only marketplace news is researched; no niche search is sent"))[:MAX_OPTIONS]


KEEP_CONFIRMED = "KEEP_CONFIRMED"

def _news_kind(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    """The one choice question for news: A niche / B everyday trending / C both. Typed a/b/c or the words work like the buttons."""
    t = " ".join(raw.casefold().split()).strip(" .!?)(")
    if t == "c" or "both" in t:
        return "BOTH"
    if t == "a" or "niche" in t or "business" in t:
        return "NICHE"
    if t == "b" or any(w in t for w in ("trend", "everyday", "daily", "general")):
        return "TRENDING"
    return Reject("Please choose A (news for my business niche), B (everyday trending ecommerce news) or C (both).")


def _has_confirmed_niche(ctx: Ctx) -> bool:
    try:
        return bool(ceo_reads.confirmed_niche_terms(ctx.tenant_id))
    except Exception:  # noqa: BLE001 - unknown: the niche is asked rather than assumed
        return False


NEWS_SECTIONS: Mapping[str, tuple[str, ...]] = {"NICHE": ("NICHE",), "TRENDING": ("MARKET_NEWS",), "BOTH": ("NICHE", "MARKET_NEWS")}  # NICHE = confirmed terms; MARKET_NEWS = the reviewed generic marketplace-news searches (slim_cmo.trends.queries)

CMO_TRENDS: tuple[Field, ...] = (
    Field("news_kind", lambda c, g: "What news do you want? A) News for my business niche, B) Everyday trending ecommerce news (Amazon, Flipkart, Meesho, seller policy, festive-season updates), or C) Both.",
          _news_kind, lambda c, g: (Option("A) My business niche", "niche", "Searches use your confirmed niche terms"), Option("B) Everyday trending news", "trending", "Needs no niche"),
                                    Option("C) Both", "both", "Niche news and everyday trending news"))),
    # marketplaces are not asked: the generic news searches cover Amazon, Flipkart and Meesho by default
    Field("marketplaces", lambda c, g: "Which marketplace should the market research focus on?", _optional_marketplaces, applies=lambda c, g: False),
    Field("niche", lambda c, g: "Which niche should the news cover? Type up to five short terms separated by commas (for example steel water bottle, insulated flask). "
                                "I will save them as your confirmed niche terms, and only those terms are sent to the search providers.", _niche_terms, _niche_options,
          applies=lambda c, g: g.get("news_kind") in ("NICHE", "BOTH") and not _has_confirmed_niche(c)),
)
CEO_ONLY_INPUTS = frozenset({"niche", "news_kind", "image_hints", "hint_analysis_id", "listing_workflow"})  # collected by the CEO, never a slot of the CMO action
DR_TREND_RUN: tuple[Field, ...] = (
    Field("preview", lambda c, g: "", _text(4000)),
    Field("confirm", lambda c, g: str(g.get("preview", "")), _yes, lambda c, g: (Option("Yes, run the research", "yes", "Sends exactly these searches"),)),
)

# ------------------------------------------------------------------------------------------------ the expense ledger through the CEO (docs/specs/ceo-expense-tracker-chat.md)
# Every answer is parsed by code against ONE field; nothing is saved by answering. When the last field is collected the task becomes a plan card the seller approves.
def _bad(r: Any) -> Any:
    return Reject(r.why) if isinstance(r, expense_chat.Bad) else r


def _exp_amount(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    return _bad(expense_chat.parse_amount(raw))


def _exp_day(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    return _bad(expense_chat.parse_day(raw, ctx.today))


def _exp_category(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    return _bad(expense_chat.parse_category(raw))


def _exp_category_options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    hint = " ".join(str(got.get(k) or "") for k in ("expense_note", "_hint"))
    return tuple(Option(label.split(" (")[0], cid, "A category in your expense ledger") for cid, label in expense_chat.category_choices(ctx.tenant_id, hint))


def _exp_day_options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    return (Option("Today", "today"), Option("Yesterday", "yesterday"))


def _exp_optional(parse: Callable[[str, Ctx, Mapping[str, Any]], Any]) -> Callable[[str, Ctx, Mapping[str, Any]], Any]:
    """A detail of a correction the seller may leave as it is: 'skip' / 'same' / 'no change' keeps the stored value (None); anything else goes through the field's own parser."""
    def run(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
        if raw.strip().casefold() in _SKIP_WORDS | {"same", "keep", "no change", "unchanged", "keep it", "as it is"}:
            return None
        return parse(raw, ctx, got)

    return run


def _exp_vendor(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    from backend.services import expense_ledger_rules as rules  # noqa: PLC0415

    t = " ".join(raw.split())
    if t.casefold() in _SKIP_WORDS:
        return None
    err = rules.vendor_error(t) if t else "Please type a name, or skip."
    return Reject(err) if err else t


def _exp_note(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = " ".join(raw.split())
    if t.casefold() in _SKIP_WORDS:
        return None
    return t if 0 < len(t) <= 500 else Reject("Please answer in at most 500 characters, or skip.")


def _exp_reason(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = " ".join(raw.split())
    return t if 3 <= len(t) <= 300 else Reject("Please give a short reason, a few words (at most 300 characters). It is kept in the history.")


def _exp_pick(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    return _bad(expense_chat.parse_pick(raw, ctx.tenant_id, str(got.get("_hint") or "")))


def _exp_pick_options(ctx: Ctx, got: Mapping[str, Any]) -> Sequence[Option]:
    try:
        return tuple(Option(label, text, reason) for label, text, reason in expense_chat.pick_options(ctx.tenant_id, str(got.get("_hint") or "")))
    except Exception:  # noqa: BLE001 - offering is a convenience; the question is still asked
        return ()


def _exp_pick_blocked(ctx: Ctx, got: Mapping[str, Any]) -> str | None:
    try:
        return None if expense_chat.recent_entries(ctx.tenant_id, "", 1) else "You have no expenses in your expense ledger yet, so there is nothing to change. Nothing was saved."
    except Exception:  # noqa: BLE001
        return None


_PAYMENT_WORDS = {"paid": "paid", "fully paid": "paid", "unpaid": "unpaid", "not paid": "unpaid", "pending": "unpaid", "partially paid": "partially_paid", "partly paid": "partially_paid",
                  "part paid": "partially_paid", "partial": "partially_paid"}


def _exp_payment(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = " ".join(raw.casefold().replace("_", " ").split()).strip(" .")
    return _PAYMENT_WORDS.get(t) or Reject("Say paid, unpaid or partially paid.")


def _exp_mention_question(ctx: Ctx, got: Mapping[str, Any]) -> str:
    said = expense_chat.mention_summary(got)
    return (f"I noticed you mentioned an expense{f' ({said})' if said else ''}. Is this an expense of yours, and shall I add it to your expense ledger? "
            "I will ask for anything that is missing, and nothing is saved until you press Approve on the card.")


EXP_ADD: tuple[Field, ...] = (
    Field("mention", _exp_mention_question, _yes, lambda c, g: (Option("Yes, add it", "yes"),), applies=lambda c, g: bool(g.get("_mention"))),
    Field("expense_amount", lambda c, g: "How much was it, in rupees? For example 5,000 or 1,299.50.", _exp_amount),
    Field("expense_date", lambda c, g: "Which day was it for? Pick one, or type a day like 5 October.", _exp_day, _exp_day_options),
    Field("expense_category", lambda c, g: "Which category is it?", _exp_category, _exp_category_options),
    Field("expense_vendor", lambda c, g: "Who was it paid to? You can skip this.", _exp_vendor, _SKIP("Not stated"), optional=True),
    Field("expense_note", lambda c, g: "Anything to note, for example what it was for? You can skip this.", _exp_note, _SKIP("Not stated"), optional=True),
)
EXP_CORRECT: tuple[Field, ...] = (
    Field("expense_pick", lambda c, g: "Which expense do you want to change?", _exp_pick, _exp_pick_options, unanswerable=_exp_pick_blocked),
    Field("expense_amount", lambda c, g: "What is the correct amount, in rupees? Say 'same' to keep it.", _exp_optional(_exp_amount), _SKIP("Keep the current amount")),
    Field("expense_date", lambda c, g: "What is the correct day? Say 'same' to keep it.", _exp_optional(_exp_day), _SKIP("Keep the current day")),
    Field("expense_category", lambda c, g: "Which category should it be? Say 'same' to keep it.", _exp_optional(_exp_category), _exp_category_options),
    Field("expense_vendor", lambda c, g: "Who was it paid to? Say 'same' to keep it.", _exp_optional(_exp_vendor), _SKIP("Keep the current vendor"), optional=True),
)
EXP_VOID: tuple[Field, ...] = (
    Field("expense_pick", lambda c, g: "Which expense do you want to remove?", _exp_pick, _exp_pick_options, unanswerable=_exp_pick_blocked),
    Field("expense_reason", lambda c, g: "Why are you removing it? A few words are enough; it is kept in the history.", _exp_reason,
          lambda c, g: (Option("Entered by mistake", "Entered by mistake"), Option("Duplicate entry", "Duplicate entry"), Option("Not a business expense", "Not a business expense"))),
)
EXP_PAID: tuple[Field, ...] = (
    Field("expense_pick", lambda c, g: "Which expense do you want to update?", _exp_pick, _exp_pick_options, unanswerable=_exp_pick_blocked),
    Field("expense_status", lambda c, g: "Is it paid, unpaid or partially paid?", _exp_payment,
          lambda c, g: (Option("Paid", "paid"), Option("Unpaid", "unpaid"), Option("Partially paid", "partially paid"))),
    Field("expense_paid_amount", lambda c, g: "How much of it has been paid, in rupees?", _exp_amount, applies=lambda c, g: g.get("expense_status") == "partially_paid"),
)
def _import_marketplace(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    mk = import_chat.parse_marketplace(raw)
    return mk if mk is not None else Reject("Please say Amazon, Flipkart or Meesho.")


IMPORT_FIELDS: tuple[Field, ...] = (
    Field("import_marketplace", lambda c, g: "Which marketplace are these reports from? I could not tell from the file names.", _import_marketplace,
          lambda c, g: (Option("Amazon", "Amazon"), Option("Flipkart", "Flipkart"), Option("Meesho", "Meesho")), applies=lambda c, g: bool(g.get("_needs_marketplace"))),
)
IMPORT_SESSIONS = ("cfo.import_attachments",)
EXPENSE_SESSIONS = ("cfo.expense_add", "cfo.expense_correct", "cfo.expense_void", "cfo.expense_paid")


def _expense_inputs(playbook: str, c: Mapping[str, Any]) -> dict[str, Any]:
    """The frozen slots of the registry action, built only from what the seller answered (and, for a correction, the stored original)."""
    if playbook == "cfo.expense_add":
        out: dict[str, Any] = {"effective_date": c["expense_date"], "category": c["expense_category"], "amount_paise": c["expense_amount"]}
        if c.get("expense_vendor"):
            out["vendor"] = c["expense_vendor"]
        if c.get("expense_note"):
            out["description"] = c["expense_note"]
        out["request_key"] = "pending"
        return out
    pick = c["expense_pick"]
    if playbook == "cfo.expense_correct":
        out = {"expense_id": pick["id"], "effective_date": c.get("expense_date") or pick["effective_date"], "category": c.get("expense_category") or pick["category"],
               "amount_paise": c.get("expense_amount") or pick["amount_paise"], "reason": "Corrected through the CEO", "request_key": "pending"}
        vendor = c.get("expense_vendor") or pick.get("vendor")
        if vendor:
            out["vendor"] = vendor
        if pick.get("description"):
            out["description"] = pick["description"]
        return out
    if playbook == "cfo.expense_void":
        return {"expense_id": pick["id"], "reason": c["expense_reason"], "request_key": "pending"}
    out = {"expense_id": pick["id"], "status": c["expense_status"], "request_key": "pending"}
    if c.get("expense_paid_amount") is not None:
        out["paid_amount_paise"] = c["expense_paid_amount"]
    return out


CMO_SESSIONS = ("cmo.generate_title_sets", "cmo.generate_hashtags", "cmo.generate_description", "cmo.generate_keywords", "cmo.generate_bullets", "cmo.generate_backend_terms",
                "cmo.generate_listing_copy", "cmo.generate_full_listing", "cmo.rewrite_listing_section", "cmo.market_trends", "cmo.catalog_answer")
# classifier slot name -> session field it can pre-fill (the seller already said it); the answer still goes through the same parser
PREFILL: Mapping[str, tuple[str, ...]] = {"product": ("product_name", "category", "sku"), "marketplace": ("marketplace", "marketplaces", "title_marketplace"), "amount": ("budget", "candidate_prices_paise", "expense_amount"),
                                          "rewrite_target": ("rewrite_target",), "rewrite_topic": ("rewrite_topic",), "competitor": ("competitor",), "period": ("expense_date",), "category": ("expense_category",), "note": ("expense_note", "expense_pick")}
PLAYBOOK_PREFILL: Mapping[str, frozenset[str]] = {"NEW_PRODUCT_DECISION": frozenset({"sku"}), "COMPETITOR_PRICE_IMPACT": frozenset({"competitor", "candidate_prices_paise"})}  # what a decision playbook may be told up front

SESSIONS: Mapping[str, tuple[Field, ...]] = {
    "COMPETITOR_PRICE_IMPACT": PRICE_IMPACT, "NEW_PRODUCT_DECISION": NEW_PRODUCT,
    "pi.discover": PI_DISCOVER,
    "cmo.market_trends": CMO_TRENDS, "dr.trend_run": DR_TREND_RUN,
    "dr.cogs_per_unit": DR_COGS, "dr.supplier_quote": DR_QUOTE, "dr.batch_budget": DR_BUDGET,
    "cfo.import_attachments": IMPORT_FIELDS, "cfo.expense_add": EXP_ADD, "cfo.expense_correct": EXP_CORRECT, "cfo.expense_void": EXP_VOID, "cfo.expense_paid": EXP_PAID,
    "cmo.generate_title_sets": CMO_TITLES, "cmo.generate_hashtags": CMO_HASHTAGS, "cmo.generate_description": CMO_DESCRIPTION, "cmo.generate_keywords": CMO_KEYWORDS,
    "cmo.generate_bullets": CMO_BULLETS, "cmo.generate_backend_terms": CMO_BACKEND_TERMS, "cmo.generate_listing_copy": CMO_LISTING, "cmo.generate_full_listing": CMO_FULL_LISTING, "cmo.rewrite_listing_section": CMO_REWRITE,
    "cmo.catalog_answer": CMO_CATALOG, "cmo.approve_title": CMO_APPROVE_TITLE, "cmo.keyword_intelligence": CMO_KEYWORD_INTEL, "cmo.analyze_titles": CMO_ANALYZE_TITLES,
}


def route_of(session: str) -> str:
    """A session is either a decision playbook or a single specialist action (an action key always contains a dot)."""
    return "ACTION" if "." in session else "PLAYBOOK"


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
    resume: Mapping[str, Any] | None = None  # a data-request session: the original request to re-run after the save (spec 6.37)
    addons: tuple[str, ...] = ()  # add-on lookups the request also asked for, carried through the questions (spec agent-needs 5.3)


@dataclass(frozen=True, slots=True)
class Cancelled:
    pass


@dataclass(frozen=True, slots=True)
class Blocked:
    """The session cannot continue (nothing real to choose from): said plainly, nothing runs."""

    text: str


def _card(playbook: str, f: Field, ctx: Ctx, collected: Mapping[str, Any]) -> dict[str, Any]:
    opts: list[dict[str, Any]] = [{"key": f"opt-{i}", "label": o.label, "kind": "RECOMMENDED" if i == 0 and not (o.unknown or o.text == "skip") else "ALTERNATIVE", "value": o.text, "reason": o.reason, "refs": {}, **({"skip": True} if o.unknown else {})}
            for i, o in enumerate(list(f.options(ctx, collected))[:MAX_OPTIONS])]
    opts.append({"key": "other", "label": "Other", "kind": "OTHER", "value": None, "reason": "Type your answer in the chat bar", "refs": {}})
    if collected:  # not the first question: the seller may step back and answer the previous one again (the earlier answer stays visible in the thread)
        opts.append({"key": "back", "label": "Back", "kind": "BACK", "value": None, "reason": "Change my previous answer", "refs": {}})
    opts.append({"key": "cancel", "label": "Cancel", "kind": "CANCEL", "value": None, "reason": "Stop asking; nothing will run", "refs": {}})
    return {"version": CARD_VERSION, "kind": "INPUT", "slot": f.name, "playbook": playbook, "pending": {"route": route_of(playbook), "key": playbook, "slots": {}, "refs": {}, "collected": dict(collected)},
            "options": opts}


def _active(fields: Sequence[Field], ctx: Ctx, collected: Mapping[str, Any]) -> list[Field]:
    """The fields that will be asked given what is known so far: a field that does not apply (a quote is already stored) is never asked."""
    return [f for f in fields if f.name in collected or f.applies(ctx, collected)]


def _next_field(fields: Sequence[Field], ctx: Ctx, collected: Mapping[str, Any]) -> Field | None:
    return next((f for f in fields if f.name not in collected and f.applies(ctx, collected)), None)


def _progress(fields: Sequence[Field], collected: Mapping[str, Any], ctx: Ctx) -> str:
    names = {f.name for f in fields}
    answered = sum(1 for k in collected if k in names)  # hidden entries (a photo's observations) and facts carried from earlier in the conversation are not answers to this task's questions
    return f"({answered + 1} of {len(_active(fields, ctx, collected))}) "


def start(
    playbook: str, ctx: Ctx, prefill: Mapping[str, str] | None = None, hidden: Mapping[str, Any] | None = None, carry: Mapping[str, str] | None = None,
) -> Ask | Done | Blocked:
    """Begin a session. Anything the seller already said (`prefill`, classifier slot text) is parsed by the SAME field parser and skipped when it reads cleanly;
    text that does not parse is simply asked again. `hidden` seeds underscore-named entries (the observations read from the seller's photo): never answers, never inputs."""
    fields = SESSIONS[playbook]
    collected: dict[str, Any] = {k: v for k, v in (hidden or {}).items() if k.startswith("_")}
    for name, value in (carry or {}).items():  # details the seller already confirmed earlier in this conversation for the SAME product: not asked again (the plan card shows them)
        if isinstance(value, str) and value.strip() and (name.startswith("fact_") or name in {f.name for f in fields}):
            collected[name] = value
    for f in fields:
        slot = next((k for k, v in PREFILL.items() if f.name in v), None)
        raw = (prefill or {}).get(slot) if slot else None
        if raw and ("." in playbook or f.name in PLAYBOOK_PREFILL.get(playbook, frozenset())):  # a specialist session, or what a decision playbook was told up front
            parsed = f.parse(raw, ctx, collected)
            if not isinstance(parsed, Reject):
                collected[f.name] = parsed
    note = _derive_price_impact(ctx, fields, collected, named_competitor=bool((prefill or {}).get("competitor"))) if playbook == "COMPETITOR_PRICE_IMPACT" else ""
    if _next_field(fields, ctx, collected) is None:
        return Done(playbook, _to_inputs(playbook, collected))
    return _ask(playbook, fields, ctx, collected, prefix=note)


def _derive_price_impact(ctx: Ctx, fields: Sequence[Field], collected: dict[str, Any], *, named_competitor: bool = False) -> str:
    """Fills in what the seller's own verified data already says, so the CEO asks only for what is missing: the competitor (when only one is tracked), the product it is tracked for
    (or the seller's only product), the seller's own price from their product profile, the competitor's VERIFIED current price as a price to compare, the fee row when only one exists,
    and the GST basis the seller confirmed last time. Every value goes through the same parser as a typed answer; nothing the seller did not give or confirm is invented (a cost is
    never filled in). Returns a one-line note of what was filled in, shown before the next question."""
    from datetime import datetime, timezone

    from backend.ceo.figure_format import format_paise

    by = {f.name: f for f in fields}
    facts: list[str] = []

    def put(name: str, raw: str, said: str) -> bool:
        if name in collected or name not in by:
            return False
        parsed = by[name].parse(raw, ctx, collected)
        if isinstance(parsed, Reject):
            return False
        collected[name] = parsed
        facts.append(said)
        return True

    try:
        tracked = [r for r in ceo_reads.list_active_competitors(ctx.tenant_id, limit=MAX_OPTIONS)]
        if "competitor" not in collected and len(tracked) == 1 and not named_competitor:  # a name the seller gave that matched nothing is asked about, never replaced by the only one tracked
            put("competitor", ceo_reads.competitor_label(tracked[0]), f"the competitor you track, {ceo_reads.competitor_label(tracked[0])}")
        comp = next((r for r in tracked if str(r["id"]) == str(collected.get("competitor"))), None)
        products = ceo_reads.list_seller_products(ctx.tenant_id)
        sku = (comp or {}).get("linked_sku") or (products[0][0] if len(products) == 1 else None)
        if sku:
            title = next((t for p, t in products if p == sku and t), sku)
            put("sku", str(sku), f"your product {title}")
            price = ceo_reads.seller_profile_price(ctx.tenant_id, str(sku))
            if price:
                put("current_price_paise", format_paise(price), f"your selling price {format_paise(price)} from your product profile")
        if comp is not None:
            snap = ceo_reads.competitor_handoff(ctx.tenant_id, UUID(str(comp["id"])), now=datetime.now(timezone.utc))
            if not isinstance(snap, ceo_reads.CiUnavailable) and snap.listed_price_paise and snap.capture_status in ("COMPLETE", "PARTIAL") and not snap.is_stale:
                prices = list(collected.get("candidate_prices_paise") or [])
                # only beside a price the seller already named to test ("to ₹349"): with none named the seller chooses, and "match their price" is offered as an option
                if prices and int(snap.listed_price_paise) not in prices and (ctx.max_candidate_prices is None or len(prices) < ctx.max_candidate_prices):
                    collected["candidate_prices_paise"] = [*prices, int(snap.listed_price_paise)]
                    facts.append(f"{ceo_reads.competitor_label(comp)}'s verified price {format_paise(snap.listed_price_paise)}")
        options = _fee_options(ctx)
        if len(options) == 1:
            o = options[0]
            put("fee", f"{o['marketplace']} {o['category']} {o['fee_type']}", f"the fee rate for {o['marketplace'].title()}")
    except Exception:  # noqa: BLE001 - a lookup problem only means more questions are asked
        pass
    return ("From your saved data I already have: " + "; ".join(facts) + ". Only what is missing is asked. ") if facts else ""


def start_data_request(session: str, sku: str, ctx: Ctx, resume: Mapping[str, Any]) -> Ask:
    """Begin a data-request session about `sku` (known from the original question). `resume` is carried on every card until the end."""
    ask = _ask(session, SESSIONS[session], ctx, {"sku": sku}, prefix="")
    assert isinstance(ask, Ask)
    ask.card["resume"] = dict(resume)
    return ask


def start_confirm(session: str, ctx: Ctx, text: str, resume: Mapping[str, Any]) -> Ask:
    """A confirm card whose text was written by code from a preview (spec 6.40); `resume` is the request that runs when the seller says yes."""
    ask = _ask(session, SESSIONS[session], ctx, {"preview": text}, prefix="")
    assert isinstance(ask, Ask)
    ask.card["resume"] = dict(resume)
    return ask


def resume_ask(playbook: str, ctx: Ctx, collected: Mapping[str, Any]) -> Ask | Done | Blocked:
    """The question that follows what is already `collected` (used to carry on after a pause), or `Done` when nothing is left to ask."""
    fields = SESSIONS[playbook]
    if _next_field(fields, ctx, collected) is None:
        return Done(playbook, _to_inputs(playbook, dict(collected)))
    return _ask(playbook, fields, ctx, collected, prefix="")


def only_optional_left(playbook: str, ctx: Ctx, collected: Mapping[str, Any]) -> bool:
    """True when every question still to be asked is a skippable extra detail."""
    left = [f for f in SESSIONS[playbook] if f.name not in collected and f.applies(ctx, collected)]
    return bool(left) and all(f.optional for f in left)


def finish_without_optional(playbook: str, collected: Mapping[str, Any]) -> Done:
    """The task goes on with what has been given; the skippable details not yet asked are simply absent (never defaulted)."""
    return Done(playbook, _to_inputs(playbook, dict(collected)))


def field_names(playbook: str, ctx: Ctx, collected: Mapping[str, Any]) -> list[str]:
    """The names of the fields still to be asked, given `collected`, in order."""
    return [f.name for f in SESSIONS[playbook] if f.name not in collected and f.applies(ctx, collected)]


def _ask(playbook: str, fields: Sequence[Field], ctx: Ctx, collected: Mapping[str, Any], *, prefix: str) -> Ask | Blocked:
    f = _next_field(fields, ctx, collected)
    assert f is not None
    blocked = f.unanswerable(ctx, collected)
    if blocked is not None:
        return Blocked(blocked)
    return Ask(f"{prefix}{_progress(fields, collected, ctx)}{f.question(ctx, collected)}", _card(playbook, f, ctx, collected))


def _numbered_title(f: Field, card: Mapping[str, Any], raw: str, option_key: str | None, ctx: Ctx, collected: Mapping[str, Any]) -> Reject | str | None:
    """The title question lists numbered choices. A bare number typed there means that choice (its real text), never the title "1"; a number with no such choice is refused,
    and a choice whose text is no longer offered (the approved title changed since the card was shown) is refused and re-asked. None = not a numbered/stale case: parse normally."""
    if f.name != "seller_title":
        return None
    stale = Reject("That choice is no longer current (the approved title has changed), so I have not used it.")
    current = [o.text for o in list(f.options(ctx, collected))[:MAX_OPTIONS] if not o.unknown and o.text != "skip"]
    if option_key is not None:
        return None if raw in current else stale
    n = raw.strip()
    if n == TITLE_OPTIONS:
        return Reject("That is not a title.")
    if not (n.isascii() and n.isdigit()):
        return None
    shown = [o for o in card.get("options", []) if o.get("kind") in ("RECOMMENDED", "ALTERNATIVE") and o.get("value") is not None]
    i = int(n)
    if not 1 <= i <= len(shown):
        return Reject(f"There is no option {n}; a number on its own is not a title.")
    picked = str(shown[i - 1]["value"])
    if picked not in current:
        return stale
    return f.parse(picked, ctx, collected)


def advance(card: Mapping[str, Any], *, option_key: str | None, text: str, ctx: Ctx) -> Ask | Done | Cancelled | Blocked:
    """One answer to the card's question. `option_key` is the option the seller chose (its text is parsed exactly as if typed); None means the typed `text`."""
    playbook = str(card.get("playbook") or (card.get("pending") or {}).get("key") or "")
    fields = SESSIONS.get(playbook)
    if fields is None:
        raise ValueError("not an input session")
    collected = dict((card.get("pending") or {}).get("collected") or {})
    f = _next_field(fields, ctx, collected)
    if f is None or str(card.get("slot")) != f.name:
        raise ValueError("the card does not match the session state")
    raw = text
    if option_key is not None:
        if option_key == "cancel":
            return Cancelled()
        if option_key == "back":
            answered = [x for x in fields if x.name in collected]  # field ORDER, not dict order: the state round-trips through jsonb, which does not keep key order
            if not answered:
                raise ValueError("there is no previous question")
            del collected[answered[-1].name]
            return _ask(playbook, fields, ctx, collected, prefix="")
        opt = next((o for o in card.get("options", []) if o.get("key") == option_key), None)
        if opt is None or opt.get("kind") == "OTHER" or opt.get("value") is None:
            raise ValueError("not an option of this card")
        raw = str(opt["value"])
    if raw.strip().casefold() in CANCEL_WORDS:
        return Cancelled()
    parsed = _numbered_title(f, card, raw, option_key, ctx, collected)
    if parsed is None:
        parsed = f.parse(raw, ctx, collected)
    if isinstance(parsed, Reject):
        again = _card(playbook, f, ctx, collected)
        if card.get("resume"):
            again["resume"] = card["resume"]
        if card.get("addons"):
            again["addons"] = list(card["addons"])
        return Ask(f"{parsed.why} {f.question(ctx, collected)} (Say “cancel” to leave this question.)", again)
    if f.name == "seller_title" and parsed == TITLE_OPTIONS:  # N-05b: not a title, a request to write title options first (ends this session; the CEO plans the title step)
        return Done(playbook, {"title_options": True, "product_name": collected.get("product_name"), "marketplace": collected.get("marketplace")}, card.get("resume"), tuple(card.get("addons") or ()))
    if f.name == "_typed_title_ok" and parsed == "change":  # N-05t: not confirmed; the title is asked again
        collected.pop("seller_title", None)
        return _ask(playbook, fields, ctx, collected, prefix="")
    collected[f.name] = parsed
    resume = card.get("resume")
    addons = tuple(card.get("addons") or ())
    if _next_field(fields, ctx, collected) is not None:
        nxt = _ask(playbook, fields, ctx, collected, prefix="")
        if isinstance(nxt, Ask) and resume:
            nxt.card["resume"] = resume
        if isinstance(nxt, Ask) and addons:
            nxt.card["addons"] = list(addons)
        return nxt
    return Done(playbook, _to_inputs(playbook, collected), resume, addons)


def _to_inputs(playbook: str, c: Mapping[str, Any]) -> dict[str, Any]:
    """The same shape `playbook_inputs.validate_inputs` checks for the form (§6.33). Nothing is added that the seller did not give."""
    if playbook in EXPENSE_SESSIONS:
        return _expense_inputs(playbook, c)
    if playbook in IMPORT_SESSIONS:
        return import_chat.inputs_from(c)
    if playbook == "dr.trend_run":
        return {}
    if playbook == "dr.cogs_per_unit":
        return {"save": {"cost_paise": c["cost"]}, "sku": c["sku"]}
    if playbook == "dr.batch_budget":
        return {"save": {"budget_paise": c["budget"]}, "sku": c["sku"]}
    if playbook == "dr.supplier_quote":
        quote: dict[str, Any] = {"supplier_name": c["supplier_name"], "unit_cost_paise": c["unit_cost"], "sku": c["sku"]}
        if c.get("order_shipping") is not None:
            quote["shipping_paise"] = c["order_shipping"]
        for key in ("moq", "lead_time_days"):
            if c.get(key) is not None:
                quote[key] = c[key]
        return {"save": {"quote": quote}, "sku": c["sku"]}
    if playbook == "pi.discover":
        rng = c.get("price_range")
        return {
            "category_text": c["category"], "budget_paise": c["budget"], "marketplaces": c["marketplaces"], "depth": "SHALLOW",
            **({"target_price_min_paise": rng["min"], "target_price_max_paise": rng["max"]} if rng else {}),
        }
    if playbook == "cmo.analyze_titles":
        return {**({"title_marketplace": c["title_marketplace"]} if c.get("title_marketplace") else {})}  # the orchestrator resolves the saved set (it holds the tenant)
    if playbook == "cmo.keyword_intelligence":
        from backend.ceo import cmo_chat  # noqa: PLC0415

        sku = cmo_chat.product_sku(c.get("product_name"))
        return {"sku": sku or str(c.get("product_name")), **({"marketplace": c["marketplace"]} if c.get("marketplace") else {})}
    if playbook == "cmo.approve_title":
        generation_id, kind, value = str(c["title_pick"]).split("|", 2)
        return {"generation_id": generation_id, **({"option_id": value} if kind == "option" else {"edited_text": value})}
    if playbook in CMO_SESSIONS:
        out = {k: v for k, v in c.items() if v is not None and not k.startswith("_")}  # a skipped optional field is simply absent: nothing is defaulted
        if playbook == "cmo.market_trends":
            out["sections"] = list(NEWS_SECTIONS.get(str(out.get("news_kind")), NEWS_SECTIONS["BOTH"]))
            if "niche" in c and c["niche"] is None:  # the seller was asked for a niche and skipped it: no niche searches exist, so the everyday trending news is what runs (the plan card lists the searches)
                out["sections"] = [s for s in out["sections"] if s != "NICHE"] or list(NEWS_SECTIONS["TRENDING"])
            out.pop("marketplaces", None)
        if playbook != "cmo.market_trends":  # CMO 3.0 M0: a stable product identity, so what the seller confirmed is saved against the product and found again next time
            from backend.ceo import cmo_chat  # noqa: PLC0415

            sku = cmo_chat.product_sku(out.get("product_name"))
            if sku:
                out["sku"] = sku
        if playbook == "cmo.catalog_answer":
            out["questions"] = [q for q in str(out.pop("catalog_questions", "")).split(",") if q]
        obs = c.get("_obs")
        analysis = (c.get("_attachment") or {}).get("analysis_id") if isinstance(c.get("_attachment"), Mapping) else None
        if isinstance(obs, Mapping) and analysis:  # a photo hint the seller confirmed or corrected with their own answer is also recorded as their statement (zero units)
            hints = [{"attribute": a, "value": out[f"fact_{a}"]} for a in IMAGE_FACT_ATTRS if obs.get(a) and isinstance(out.get(f"fact_{a}"), str) and out[f"fact_{a}"].strip()]
            if hints:
                out["image_hints"], out["hint_analysis_id"] = hints, str(analysis)
        facts = {k[len("fact_"):]: out.pop(k) for k in list(out) if k.startswith("fact_")}  # only what the seller CONFIRMED or typed, as their own statement
        if "brand" in facts:
            out["brand"] = facts.pop("brand")
        if facts:
            out["attributes"] = [{"name": name.replace("_", " ").title(), "value": value} for name, value in facts.items()]
        return out
    if playbook == "NEW_PRODUCT_DECISION":
        out: dict[str, Any] = {"sku": c["sku"], "quantity": c["quantity"], **c["window"]}
        if "supplier_name" in c or "budget" in c:  # what the seller confirmed for saving (spec 6.36); split off before the playbook inputs are validated
            save: dict[str, Any] = {}
            if "supplier_name" in c:
                quote: dict[str, Any] = {"supplier_name": c["supplier_name"], "unit_cost_paise": c["unit_cost"], "sku": c["sku"]}
                if c.get("order_shipping") is not None:
                    quote["shipping_paise"] = c["order_shipping"]
                for key in ("moq", "lead_time_days"):
                    if c.get(key) is not None:
                        quote[key] = c[key]
                save["quote"] = quote
            if "budget" in c:
                save["budget_paise"] = c["budget"]
            out["save"] = save
        return out
    fee = c["fee"]
    return {
        "competitor_url_id": c["competitor"], "sku": c["sku"], "marketplace": fee["marketplace"], "category": fee["category"], "fee_type": fee["fee_type"], "basis": c["basis"],
        "gst_rate_pct": c["gst_rate_pct"], "current_price_paise": c["current_price_paise"], "candidate_prices_paise": c["candidate_prices_paise"],
        **{k: c.get(k, {"state": "UNKNOWN"}) for k in ("shipping", "advertising", "return_rto", "other")},  # not entered = not known: margins that need them show as unavailable
    }


def remember_confirmed(tenant: UUID, session: str, inputs: Mapping[str, Any], *, source_ref: Mapping[str, Any], user_id: UUID | None) -> None:
    """The seller finished a session with their own answers: save the short choices offered next time (CMO marketplaces, CI competitor, CFO GST basis; spec
    agent-memory.md section 11). Best-effort: never raises, never blocks the turn, stores no free text and no money."""
    try:
        picks: list[tuple[str, str, str]] = []
        if session in CMO_SESSIONS:
            mp = inputs.get("marketplaces") if "marketplaces" in inputs else inputs.get("marketplace")
            mp = [mp] if isinstance(mp, str) else mp
            if mp:
                picks.append(("CMO", "last_marketplaces", ", ".join(str(m).upper() for m in mp)))
        elif session == "COMPETITOR_PRICE_IMPACT":
            if inputs.get("basis") in memory.BASES:
                picks.append(("CFO", "last_basis", str(inputs["basis"])))
            label = next((str(r["label"]) for r in ceo_reads.list_active_competitors(tenant, limit=200) if str(r.get("id")) == str(inputs.get("competitor_url_id")) and r.get("label")), None)
            if label:
                picks.append(("CI", "last_competitor", label))
        for agent, key, value in picks:
            try:
                memory.note_choice(tenant, agent=agent, key=key, value=value, source_ref=source_ref, created_by=user_id)
            except ValueError:
                continue  # not in its closed form: not remembered
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("could not save agent memory")
