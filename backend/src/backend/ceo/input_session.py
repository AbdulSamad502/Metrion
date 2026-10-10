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

from backend.ceo import memory, slot_resolvers
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
    applies: Callable[[Ctx, Mapping[str, Any]], bool] = lambda ctx, got: True  # False = not asked (e.g. a quote is already stored); the field is simply absent


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
    Field("sku", lambda c, g: "Which SKU is this for? Type it the way you list it.", _text()),
    Field("fee", lambda c, g: "Which marketplace, category and fee type should I price it under?", _fee, _fee_choices,
          lambda c, g: None if _fee_options(c) else "No marketplace fee rates are set up yet, so I cannot price a margin. Ask your account owner to add them."),
    Field("basis", lambda c, g: "Do the prices you will give me include GST?", _basis,
          lambda c, g: _with_remembered((Option("Prices include GST", "inclusive"), Option("Prices exclude GST", "exclusive")),
                                        _remembered_choice(c, "CFO", "last_basis", lambda v: Option("Prices include GST" if v == "INCLUSIVE" else "Prices exclude GST", v.lower(), _LAST_TIME)))),
    Field("gst_rate_pct", lambda c, g: "What GST rate applies? Type a number such as 18.", _gst, lambda c, g: (Option("I do not know", "unknown", "GST-dependent margins will show as unavailable"),)),
    Field("current_price_paise", lambda c, g: "What is your current selling price, in rupees?", _amount),
    Field("candidate_prices_paise", lambda c, g: "Which prices should I compare? Give rupee amounts separated by commas"
          + (f", up to {c.max_candidate_prices}." if c.max_candidate_prices else "."), _prices,
          _rival_price_option),
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


_MARKETPLACE_OPTIONS = lambda ctx, got: tuple(Option(m.title(), m.title()) for m in _MARKETPLACE_NAMES)  # noqa: E731
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
_PRODUCT = Field("product_name", lambda c, g: "What is the product? Name it the way a buyer would search for it.", _text(200))
_SELLER_TITLE = Field("seller_title", lambda c, g: "What title do you use for it today (or want to use)? I will write from it, so what you give me is what the copy is based on.", _text(500))

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


CMO_TITLES: tuple[Field, ...] = (
    _PRODUCT,
    Field("category_hint", lambda c, g: "Which category is it in? For example kitchen, apparel, electronics. Or choose themes I already hold.", _optional_text(100), _theme_options),
    Field("marketplaces", lambda c, g: "Which marketplace should the titles be written for? You can name more than one.", _marketplaces, _cmo_marketplace_options(False)),
)
CMO_HASHTAGS: tuple[Field, ...] = (
    _PRODUCT,
    Field("marketplace", lambda c, g: "Which marketplace are the hashtags for?", _optional_marketplace, _cmo_marketplace_options(True, skip=True)),
)
CMO_GROUNDED: tuple[Field, ...] = (
    _PRODUCT,
    Field("marketplace", lambda c, g: "Which marketplace is this for?", _one_marketplace, _cmo_marketplace_options(True)),
    _SELLER_TITLE,
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


def _depth(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    t = raw.strip().casefold()
    if t.startswith(("quick", "shallow", "fast")):
        return "SHALLOW"
    if t.startswith(("complete", "deep", "full", "thorough")):
        return "COMPLETE"
    return Reject("Choose a quick scan or a complete research run.")


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
    depth = "a complete run" if got.get("depth") == "COMPLETE" else "a quick scan"
    return (f"Here is what I will research: {got.get('category')} on {where}, with a budget of {format_paise(got.get('budget'))}{span}, as {depth}. "
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
    Field("depth", lambda c, g: "How thorough should the research be?", _depth,
          lambda c, g: (Option("Quick scan", "quick", "Faster and lighter; a good first look"), Option("Complete run", "complete", "Slower and uses more of your research allowance"))),
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
        parts.append(f"a supplier quote from {got['supplier_name']} at {format_paise(got['unit_cost'])} per unit{ship}")
    if "budget" in got:
        parts.append(f"a batch budget of {format_paise(got['budget'])}")
    return (f"Here is what I will save as your own figures: {' and '.join(parts)}. Then I will run the numbers (landed cost, supplier ranking and batch size) for "
            f"{got.get('sku')}. Shall I go ahead?")


def _quote_applies(ctx: Ctx, got: Mapping[str, Any]) -> bool:
    return _needs_quote(ctx, got)


NEW_PRODUCT: tuple[Field, ...] = (
    Field("sku", lambda c, g: "Which SKU are you thinking of stocking? Type it the way you list it.", _text()),
    Field("quantity", lambda c, g: "How many units are you considering?", _quantity),
    Field("window", lambda c, g: "Which sales-history period should I look at?", _window, _window_choices),
    Field("supplier_name", lambda c, g: "I have no supplier quote saved for this product. Which supplier is it from?", _text(80), applies=_quote_applies),
    Field("unit_cost", lambda c, g: "What is that supplier's price per unit, in rupees?", _amount, applies=_quote_applies),
    Field("order_shipping", lambda c, g: "What is the shipping for the whole order, in rupees? Skip it if the quote does not state it.", _optional_amount,
          _SKIP("Not stated; margins that need it stay unavailable"), applies=_quote_applies),
    Field("budget", lambda c, g: "What is your budget for this batch, in rupees? I will fit the quantity to it.", _amount, applies=lambda c, g: _needs_budget(c, g)),
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
    Field("confirm", _dr_summary(lambda g: f"a supplier quote from {g['supplier_name']} at {_money(g['unit_cost'])} per unit for {g['sku']}"), _yes, _DR_CONFIRM_OPTIONS),
)
DR_BUDGET: tuple[Field, ...] = (
    Field("sku", lambda c, g: "", _text()),
    Field("budget", lambda c, g: "I need your budget for this batch. How much can you spend, in rupees?", _amount),
    Field("confirm", _dr_summary(lambda g: f"a batch budget of {_money(g['budget'])}"), _yes, _DR_CONFIRM_OPTIONS),
)

def _optional_marketplaces(raw: str, ctx: Ctx, got: Mapping[str, Any]) -> Any:
    return [] if raw.strip().casefold() in _SKIP_WORDS else _marketplaces(raw, ctx, got)


CMO_TRENDS: tuple[Field, ...] = (
    Field("marketplaces", lambda c, g: "Which marketplace should the market research focus on? You can name more than one, or skip to cover all.", _optional_marketplaces,
          lambda c, g: (Option("All three", "all"), Option("Amazon", "Amazon"), Option("Flipkart", "Flipkart"))),
)
DR_TREND_RUN: tuple[Field, ...] = (
    Field("preview", lambda c, g: "", _text(4000)),
    Field("confirm", lambda c, g: str(g.get("preview", "")), _yes, lambda c, g: (Option("Yes, run the research", "yes", "Sends exactly these searches"),)),
)

CMO_SESSIONS = ("cmo.generate_title_sets", "cmo.generate_hashtags", "cmo.generate_description", "cmo.generate_keywords", "cmo.market_trends")
# classifier slot name -> session field it can pre-fill (the seller already said it); the answer still goes through the same parser
PREFILL: Mapping[str, tuple[str, ...]] = {"product": ("product_name", "category", "sku"), "marketplace": ("marketplace", "marketplaces"), "amount": ("budget", "candidate_prices_paise"),
                                          "competitor": ("competitor",)}
PLAYBOOK_PREFILL: Mapping[str, frozenset[str]] = {"NEW_PRODUCT_DECISION": frozenset({"sku"}), "COMPETITOR_PRICE_IMPACT": frozenset({"competitor", "candidate_prices_paise"})}  # what a decision playbook may be told up front

SESSIONS: Mapping[str, tuple[Field, ...]] = {
    "COMPETITOR_PRICE_IMPACT": PRICE_IMPACT, "NEW_PRODUCT_DECISION": NEW_PRODUCT,
    "pi.discover": PI_DISCOVER,
    "cmo.market_trends": CMO_TRENDS, "dr.trend_run": DR_TREND_RUN,
    "dr.cogs_per_unit": DR_COGS, "dr.supplier_quote": DR_QUOTE, "dr.batch_budget": DR_BUDGET,
    "cmo.generate_title_sets": CMO_TITLES, "cmo.generate_hashtags": CMO_HASHTAGS, "cmo.generate_description": CMO_GROUNDED, "cmo.generate_keywords": CMO_GROUNDED,
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
    opts: list[dict[str, Any]] = [{"key": f"opt-{i}", "label": o.label, "kind": "RECOMMENDED" if i == 0 else "ALTERNATIVE", "value": o.text, "reason": o.reason, "refs": {}}
            for i, o in enumerate(list(f.options(ctx, collected))[:MAX_OPTIONS])]
    opts.append({"key": "other", "label": "Other", "kind": "OTHER", "value": None, "reason": "Type your answer in the chat bar", "refs": {}})
    opts.append({"key": "cancel", "label": "Cancel", "kind": "CANCEL", "value": None, "reason": "Stop asking; nothing will run", "refs": {}})
    return {"version": CARD_VERSION, "kind": "INPUT", "slot": f.name, "playbook": playbook, "pending": {"route": route_of(playbook), "key": playbook, "slots": {}, "refs": {}, "collected": dict(collected)},
            "options": opts}


def _active(fields: Sequence[Field], ctx: Ctx, collected: Mapping[str, Any]) -> list[Field]:
    """The fields that will be asked given what is known so far: a field that does not apply (a quote is already stored) is never asked."""
    return [f for f in fields if f.name in collected or f.applies(ctx, collected)]


def _next_field(fields: Sequence[Field], ctx: Ctx, collected: Mapping[str, Any]) -> Field | None:
    return next((f for f in fields if f.name not in collected and f.applies(ctx, collected)), None)


def _progress(fields: Sequence[Field], collected: Mapping[str, Any], ctx: Ctx) -> str:
    return f"({len(collected) + 1} of {len(_active(fields, ctx, collected))}) "


def start(playbook: str, ctx: Ctx, prefill: Mapping[str, str] | None = None) -> Ask | Done | Blocked:
    """Begin a session. Anything the seller already said (`prefill`, classifier slot text) is parsed by the SAME field parser and skipped when it reads cleanly;
    text that does not parse is simply asked again."""
    fields = SESSIONS[playbook]
    collected: dict[str, Any] = {}
    for f in fields:
        slot = next((k for k, v in PREFILL.items() if f.name in v), None)
        raw = (prefill or {}).get(slot) if slot else None
        if raw and ("." in playbook or f.name in PLAYBOOK_PREFILL.get(playbook, frozenset())):  # a specialist session, or what a decision playbook was told up front
            parsed = f.parse(raw, ctx, collected)
            if not isinstance(parsed, Reject):
                collected[f.name] = parsed
    if _next_field(fields, ctx, collected) is None:
        return Done(playbook, _to_inputs(playbook, collected))
    return _ask(playbook, fields, ctx, collected, prefix="")


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


def _ask(playbook: str, fields: Sequence[Field], ctx: Ctx, collected: Mapping[str, Any], *, prefix: str) -> Ask | Blocked:
    f = _next_field(fields, ctx, collected)
    assert f is not None
    blocked = f.unanswerable(ctx, collected)
    if blocked is not None:
        return Blocked(blocked)
    return Ask(f"{prefix}{_progress(fields, collected, ctx)}{f.question(ctx, collected)}", _card(playbook, f, ctx, collected))


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
        opt = next((o for o in card.get("options", []) if o.get("key") == option_key), None)
        if opt is None or opt.get("kind") == "OTHER" or opt.get("value") is None:
            raise ValueError("not an option of this card")
        raw = str(opt["value"])
    if raw.strip().casefold() in CANCEL_WORDS:
        return Cancelled()
    parsed = f.parse(raw, ctx, collected)
    if isinstance(parsed, Reject):
        again = _card(playbook, f, ctx, collected)
        if card.get("resume"):
            again["resume"] = card["resume"]
        if card.get("addons"):
            again["addons"] = list(card["addons"])
        return Ask(f"{parsed.why} {f.question(ctx, collected)}", again)
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
        return {"save": {"quote": quote}, "sku": c["sku"]}
    if playbook == "pi.discover":
        rng = c.get("price_range")
        return {
            "category_text": c["category"], "budget_paise": c["budget"], "marketplaces": c["marketplaces"], "depth": c["depth"],
            **({"target_price_min_paise": rng["min"], "target_price_max_paise": rng["max"]} if rng else {}),
        }
    if playbook in CMO_SESSIONS:
        out = {k: v for k, v in c.items() if v is not None}  # a skipped optional field is simply absent: nothing is defaulted
        return out
    if playbook == "NEW_PRODUCT_DECISION":
        out: dict[str, Any] = {"sku": c["sku"], "quantity": c["quantity"], **c["window"]}
        if "supplier_name" in c or "budget" in c:  # what the seller confirmed for saving (spec 6.36); split off before the playbook inputs are validated
            save: dict[str, Any] = {}
            if "supplier_name" in c:
                quote: dict[str, Any] = {"supplier_name": c["supplier_name"], "unit_cost_paise": c["unit_cost"], "sku": c["sku"]}
                if c.get("order_shipping") is not None:
                    quote["shipping_paise"] = c["order_shipping"]
                save["quote"] = quote
            if "budget" in c:
                save["budget_paise"] = c["budget"]
            out["save"] = save
        return out
    fee = c["fee"]
    return {
        "competitor_url_id": c["competitor"], "sku": c["sku"], "marketplace": fee["marketplace"], "category": fee["category"], "fee_type": fee["fee_type"], "basis": c["basis"],
        "gst_rate_pct": c["gst_rate_pct"], "current_price_paise": c["current_price_paise"], "candidate_prices_paise": c["candidate_prices_paise"],
        "shipping": c["shipping"], "advertising": c["advertising"], "return_rto": c["return_rto"], "other": c["other"],
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
