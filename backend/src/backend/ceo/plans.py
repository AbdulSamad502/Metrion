"""The fixed, code-reviewed execution plans B3 can run: single actions and playbooks (spec §6.4, §6.11, §6.12).

Everything the classifier may select lives here and nowhere else. A plan names registry keys and the deterministic function that
builds each leg's slots from already-validated values; the model can fill declared slot TEXT but cannot add, drop, reorder or
parameterise a leg (§6.12 rule 1). Legs are independent: no leg consumes another's output in the same turn (AC4).

Actions and playbooks whose slots can be built from seller text alone run from chat. The two decision playbooks (COMPETITOR_PRICE_IMPACT,
NEW_PRODUCT_DECISION; spec 6.33) need money inputs a chat message cannot supply safely, so they run only from a form's structured inputs
(`resolve_playbook_run`); from chat the seller is offered the form. The rest of the registry (PI discovery, CMO writers/trends, ...) stays
reachable only through its direct surface until its own slot resolution is specified; such requests are declined plainly (never mis-routed).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from backend.ceo import slot_resolvers
from backend.ceo.figure_format import format_paise
from backend.ceo.periods import PeriodUnresolvable, ResolvedPeriod, resolve_period
from backend.ceo.playbook_inputs import NewProductInputs, PriceImpactInputs, cost_to_slot, validate_inputs
from backend.services import ceo_reads

MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")
SLOT_VOCAB: tuple[str, ...] = (
    "period", "compare_period", "marketplace", "sku", "product", "quantity", "amount", "competitor", "niche", "option",
)


@dataclass(frozen=True, slots=True)
class Clarification:
    slot: str  # a SLOT_VOCAB name, or UNCLEAR_REQUEST / WHICH_AGENT
    question: str
    candidates: tuple[tuple[UUID, str], ...] = ()  # real candidates (id, label) behind an ambiguous or unknown name, for a decision card


@dataclass(frozen=True, slots=True)
class PlaybookRun:
    """The validated, tenant-checked inputs of one decision playbook run (spec 6.33) plus what code read back for it: the stored cost, or the assembled sales history."""

    playbook: str
    inputs: PriceImpactInputs | NewProductInputs
    competitor_label: str | None = None
    cogs: ceo_reads.StoredCogs | None = None
    history: ceo_reads.SalesHistory | None = None


@dataclass(frozen=True, slots=True)
class ResolvedSlots:
    tenant_id: UUID
    today: date
    run: PlaybookRun | None = None
    period: ResolvedPeriod | None = None
    marketplace: str | None = None
    competitor_url_id: UUID | None = None
    competitor_label: str | None = None
    seller_price_paise: int | None = None
    pi_run_id: UUID | None = None
    product_text: str | None = None
    product_id: str | None = None  # a seller product resolved by code from the seller's own words (CI)
    categories: tuple[str, ...] | None = None  # business-profile categories the seller chose for a competitor search
    direct: Mapping[str, Any] | None = None  # slots collected by a guided input session and already parsed by code (spec 6.35): passed to the specialist as they are

    def echoes(self) -> tuple[str, ...]:
        """What the system understood, in the seller's terms, so a wrong reading is visible before it is acted on (AC17)."""
        out = []
        if self.period is not None:
            out.append(self.period.echo)
        if self.marketplace is not None:
            out.append(f"Marketplace: {self.marketplace.title()}.")
        if self.competitor_label is not None:
            out.append(f"Competitor: {self.competitor_label}.")
        if self.seller_price_paise is not None:
            out.append(f"Your current price taken as {format_paise(self.seller_price_paise)}.")
        if self.product_text is not None:
            out.append(f"Looked up for the product you named: {self.product_text}.")
        if self.run is not None:
            out.extend(_run_echoes(self.run))
        if self.direct is not None:
            if self.direct.get("product_name"):
                out.append(f"Product: {self.direct['product_name']}.")
            named = self.direct.get("marketplaces") or ([self.direct["marketplace"]] if self.direct.get("marketplace") else [])
            if named:
                out.append("Marketplace: " + ", ".join(str(m).title() for m in named) + ".")
        return tuple(out)


def normalise_marketplace(raw: str | None) -> str | None:
    text = (raw or "").strip().upper()
    return next((m for m in MARKETPLACES if m in text), None)


SLOT_QUESTIONS: Mapping[str, str] = {
    "period": "Which period do you mean? For example a month name (September), 'last month', or a date range like 2026-09-01 to 2026-09-30.",
    "marketplace": "Which marketplace: Amazon, Flipkart or Meesho?",
    "amount": "What is your current selling price, in rupees? For example 499 or 1,299.50.",
    "competitor": "Which of your tracked competitors do you mean?",
    "product": "Which product? Tell me its name the way you list it.",
    "pi_run": "No finished product research run exists yet, so there is no report to show. Start one from the Product Intelligence page first.",
}


def resolve_slots(
    raw: Mapping[str, str], required: tuple[str, ...], *, tenant_id: UUID, today: date, resolves: tuple[str, ...] = (), refs: Mapping[str, UUID] | None = None,
) -> ResolvedSlots | Clarification:
    """Validates classifier slot TEXT. A missing or unrecognisable required slot is a `Clarification` — nothing is defaulted (E22). `resolves` names
    values code looks up itself from the caller's own tenant data (never asked of the model)."""
    period: ResolvedPeriod | None = None
    marketplace: str | None = None
    competitor_id: UUID | None = None
    competitor_label: str | None = None
    price: int | None = None
    pi_run: UUID | None = None
    product_text: str | None = None
    product_id: str | None = None
    if "period" in required:
        try:
            period = resolve_period(raw.get("period"), today=today)
        except PeriodUnresolvable:
            return Clarification("period", SLOT_QUESTIONS["period"])
    if "marketplace" in required:
        marketplace = normalise_marketplace(raw.get("marketplace"))
        if marketplace is None:
            return Clarification("marketplace", SLOT_QUESTIONS["marketplace"])
    if "competitor" in required:
        chosen = refs.get("competitor_url_id") if refs else None
        found: slot_resolvers.CompetitorMatch | slot_resolvers.CompetitorUnresolved | None = (
            slot_resolvers.resolve_competitor_ref(tenant_id, chosen) if chosen is not None else None
        )
        if found is None:
            found = slot_resolvers.resolve_competitor(tenant_id, raw.get("competitor"))
            if not isinstance(found, slot_resolvers.CompetitorMatch) and not (raw.get("competitor") or "").strip():
                from backend.ceo import ci_conversation  # noqa: PLC0415 - the competitor the conversation is about answers "which competitor?" instead of asking again

                fid, flabel = ci_conversation.focus_competitor(tenant_id)
                if fid:
                    found = slot_resolvers.CompetitorMatch(UUID(fid), flabel or "that competitor")
        if isinstance(found, slot_resolvers.CompetitorMatch):
            competitor_id, competitor_label = found.url_id, found.label
        elif found.reason == "NONE_TRACKED":
            return Clarification("competitor", "No competitors are being tracked yet. Add one on the Competitor Intelligence page first.")
        else:
            names = ", ".join(found.choices)
            lead = "That matches more than one tracked competitor" if found.reason == "AMBIGUOUS" else "I could not find that competitor"
            return Clarification("competitor", f"{lead}. Which do you mean: {names}?" if names else f"{lead}. Which of your tracked competitors do you mean?", found.candidates)
    if "amount" in required:
        price = slot_resolvers.parse_amount_paise(raw.get("amount"))
        if price is None:
            return Clarification("amount", SLOT_QUESTIONS["amount"])
    if "product" in required:
        product_text = " ".join((raw.get("product") or "").split())
        if "category" in resolves:  # a competitor search: the seller's business-profile categories are offered first, and a reply that names some is the answer
            cats = ceo_reads.business_categories(tenant_id)
            picked = ceo_reads.resolve_categories(product_text, cats) if product_text else []
            if picked:
                return ResolvedSlots(tenant_id=tenant_id, today=today, categories=tuple(picked), product_text="; ".join(picked))
            if not product_text and cats:
                return Clarification("product", category_choice_question(cats))
        if not product_text or len(product_text) > MAX_PRODUCT_TEXT_CHARS:
            if "seller_product" in resolves:  # the seller is shown their own products to pick from, never asked to guess a name
                return Clarification("product", product_choice_question(tenant_id))
            return Clarification("product", SLOT_QUESTIONS["product"])
    if "seller_product" in resolves or ("seller_product_if_named" in resolves and (raw.get("product") or "").strip()):
        found_product = slot_resolvers.resolve_seller_product(tenant_id, raw.get("product"))
        if isinstance(found_product, slot_resolvers.ProductMatch):
            product_id = found_product.product_id
            product_text = found_product.title or found_product.product_id
        elif found_product.reason == "NONE_KNOWN" and "seller_product" not in resolves:
            product_id, product_text = None, None  # a read that only filters by product: with none known it simply covers everything
        elif found_product.reason == "NONE_KNOWN":
            return Clarification("product", NO_PRODUCTS_TEXT)
        elif "seller_product" not in resolves and isinstance(slot_resolvers.resolve_competitor(tenant_id, raw.get("product")), slot_resolvers.CompetitorMatch):
            product_id, product_text = None, None  # "for CASPIAN Astra 1L" named a tracked competitor, not a product: no product filter
        else:
            names = ", ".join(found_product.choices)
            lead = "That matches more than one of your products" if found_product.reason == "AMBIGUOUS" else "I could not find that product"
            return Clarification("product", f"{lead}. Which do you mean: {names}?" if names else f"{lead}. Which of your products do you mean?")
    if "pi_run" in resolves:
        latest = ceo_reads.latest_pi_run(tenant_id, finished_only=True)
        if latest is None:
            return Clarification("pi_run", SLOT_QUESTIONS["pi_run"])
        pi_run = UUID(str(latest["id"]))
    return ResolvedSlots(
        tenant_id=tenant_id, today=today, period=period, marketplace=marketplace, competitor_url_id=competitor_id, competitor_label=competitor_label,
        seller_price_paise=price, pi_run_id=pi_run, product_text=product_text, product_id=product_id,
    )


# ------------------------------------------------------------------------------------------------ slot builders
CATEGORY_MARKER = "Which category should I find competitors for?"


def category_choice_question(categories: list[str]) -> str:
    """The competitor-search question when the seller's business profile lists categories: pick one or more (numbers, names or ALL)."""
    lines = [f"{CATEGORY_MARKER} Your categories:"] + [f"{i}. {c}" for i, c in enumerate(categories, start=1)]
    lines.append("Reply with one or more numbers (for example “1 and 2”), a category name, or ALL. You can also name one of your products instead.")
    return "\n".join(lines)


def discovery_question(tenant_id: UUID) -> str:
    """The question for a competitor search that names nothing: the seller's business-profile categories when they gave some, else their products."""
    cats = ceo_reads.business_categories(tenant_id)
    return category_choice_question(cats) if cats else product_choice_question(tenant_id)


def product_choice_question(tenant_id: UUID) -> str:
    """The question for a request that needs one of the seller's own products and was not told which: it lists their products, or says there are none."""
    known = ceo_reads.list_seller_products(tenant_id)
    if not known:
        return NO_PRODUCTS_TEXT
    names = "; ".join(f"“{title or pid}”" for pid, title in known[: slot_resolvers.MAX_COMPETITOR_CHOICES])
    return f"Which of your products is this for? Your products: {names}. Tell me which one."


NO_PRODUCTS_TEXT = (
    "I do not have any of your products yet, so I cannot link competitors to one. Upload a sales report so your products appear, or add a product profile, then ask me again. "
    "Nothing was searched or added."
)


def _dates(s: ResolvedSlots) -> dict[str, str]:
    assert s.period is not None
    return {"period_start": s.period.start.isoformat(), "period_end": s.period.end.isoformat(), "as_of_date": s.period.as_of.isoformat()}


def _period_only(s: ResolvedSlots) -> dict[str, object]:
    return dict(_dates(s))


def _period_marketplace(s: ResolvedSlots) -> dict[str, object]:
    assert s.marketplace is not None
    return {**_dates(s), "marketplace": s.marketplace}


def _anomaly(s: ResolvedSlots) -> dict[str, object]:
    # Tenant-level series: the engine persists TENANT_PERIOD metrics with target_ref = the tenant id (derived from the real
    # AuthContext, never from the request). Narration stays off — the CEO composes (§6.4).
    return {**_dates(s), "target_ref": str(s.tenant_id), "include_narration": False}


MAX_PRODUCT_TEXT_CHARS = 200  # the slot model's own length limit, so an over-long text is asked about, not truncated


def _gst_lookup(s: ResolvedSlots) -> dict[str, object]:
    assert s.product_text is not None
    return {"product_title": s.product_text}


def _price_scenario(s: ResolvedSlots) -> dict[str, object]:
    assert s.competitor_url_id is not None and s.seller_price_paise is not None
    return {"competitor_url_id": str(s.competitor_url_id), "seller_price_paise": s.seller_price_paise}


def _discover(s: ResolvedSlots) -> dict[str, object]:
    if s.categories:
        return {"categories": list(s.categories)}
    assert s.product_id is not None
    return {"product_id": s.product_id}


def _no_slots(s: ResolvedSlots) -> dict[str, object]:
    return {}


def _optional_product(s: ResolvedSlots) -> dict[str, object]:
    # CI spec C33: a dashboard shortcut or the seller's own words may name the product; with none named, every product with tracked competitors is covered.
    return {"product_id": s.product_id} if s.product_id else {}


def _competitor_remove(s: ResolvedSlots) -> dict[str, object]:
    assert s.competitor_url_id is not None
    return {"competitor_url_id": str(s.competitor_url_id)}


def _direct(s: ResolvedSlots) -> dict[str, object]:
    assert s.direct is not None
    return dict(s.direct)


def _preview_defaults(s: ResolvedSlots) -> dict[str, object]:
    # The zero-cost trend preview takes the route's own defaults when nothing was collected: a catalog-offered action must never fail building its slots.
    return dict(s.direct or {})


def _pi_report(s: ResolvedSlots) -> dict[str, object]:
    assert s.pi_run_id is not None
    return {"run_id": str(s.pi_run_id)}


# GST is ONE action to the model. Which route runs it (A: CFO's own `cfo.gst_lookup`; B: the shared `service.gst_lookup`) is decided by CODE from the
# member's permissions and the attached agents (spec C11), never by the model.
GST_KEY = "gst_lookup"
GST_ROUTE_KEYS: tuple[str, ...] = ("cfo.gst_lookup", "service.gst_lookup")
VIRTUAL_ROUTES: Mapping[str, tuple[str, ...]] = {GST_KEY: GST_ROUTE_KEYS}


def gst_route_key(entitled_registry_keys: frozenset[str]) -> str | None:
    """Route A when the member can use it (agent.cfo attached + permitted + both entitlements + service.gst_lookup), else Route B, else none."""
    for key in GST_ROUTE_KEYS:
        if key in entitled_registry_keys:
            return key
    return None


@dataclass(frozen=True, slots=True)
class ActionPlan:
    key: str  # a registry key
    description: str  # plain language, shown to the classifier
    required_slots: tuple[str, ...]
    build_slots: Callable[[ResolvedSlots], dict[str, object]]
    resolves: tuple[str, ...] = ()  # values code looks up itself from the caller's own data (not asked of the model, not shown as slots)
    session: bool = False  # the inputs are collected by a guided input session in chat (spec 6.35); the model never supplies them


ACTIONS: Mapping[str, ActionPlan] = {
    p.key: p
    for p in (
        ActionPlan("cfo.financial_health", "Financial health bands (good / watch / at-risk) for a period", ("period",), _period_only),
        ActionPlan("cfo.anomaly_check", "Check a period for statistically unusual changes in results", ("period",), _anomaly),
        ActionPlan("cfo.strategic_briefing", "CFO strategic briefing for a period: health, leaks and open data requests ranked", ("period",), _period_only),
        ActionPlan("cfo.reconcile", "Reconcile marketplace settlements against orders to find leaks, for a marketplace and period", ("marketplace", "period"), _period_marketplace),
        ActionPlan(
            "ci.request_price_scenario",
            "Where the seller's current price stands against ONE named tracked competitor (price positioning), for a stated selling price",
            ("competitor", "amount"), _price_scenario,
        ),
        ActionPlan(
            "ci.discover_competitors",
            "Find competitors for ONE of the seller's own products by searching the marketplaces (Competitor Intelligence). The results are leads to review, not verified prices",
            ("product",), _discover, resolves=("seller_product", "category"),
        ),
        ActionPlan(
            "ci.monitor_competitors",
            "Re-check the tracked competitors from the evidence already saved: how fresh it is and any verified price or stock change. It does not watch or fetch anything live",
            (), _optional_product, resolves=("seller_product_if_named",),
        ),
        ActionPlan(
            "ci.review_findings", "What the saved competitor review evidence says: recurring complaints and strengths, with how many reviews were sampled", (), _optional_product,
            resolves=("seller_product_if_named",),
        ),
        ActionPlan("ci.competitor_remove", "Stop tracking ONE named competitor (its history is kept)", ("competitor",), _competitor_remove),
        ActionPlan(
            GST_KEY,
            "Which GST rate likely applies to a product, from its name (a provisional lookup from a cited public source, never a ruling)",
            ("product",), _gst_lookup,
        ),
        ActionPlan(
            "pi.report", "Show the report of the latest finished product research run (re-rendered from saved data; no new research)", (), _pi_report,
            resolves=("pi_run",),
        ),
        ActionPlan("pi.discover", "Find trending or top products to sell in a niche, within the seller's budget (Product Intelligence research run). The CEO asks the seller for niche, budget and marketplaces", (), _direct, session=True),
        ActionPlan("cmo.generate_title_sets", "Write listing title options for a product on one or more marketplaces (CMO). The CEO asks the seller for the product details", (), _direct, session=True),
        ActionPlan("cmo.generate_hashtags", "Suggest hashtags for a product (CMO). The CEO asks the seller for the product details", (), _direct, session=True),
        ActionPlan("cmo.generate_description", "Write a product description for a marketplace from the seller's own title (CMO). The CEO asks for the details", (), _direct, session=True),
        ActionPlan("cmo.generate_keywords", "Suggest search keywords for a product on a marketplace from the seller's own title (CMO). The CEO asks for the details", (), _direct, session=True),
        ActionPlan("cmo.generate_bullets", "Write the five bullet points of a listing for a marketplace from the seller's own title (CMO). The CEO asks for the details", (), _direct, session=True),
        ActionPlan("cmo.generate_backend_terms", "Write Amazon backend search terms for a product from the seller's own title (CMO). The CEO asks for the details", (), _direct, session=True),
        ActionPlan("cmo.generate_listing_copy", "Write the full listing copy pack (description, bullet points and keywords) for a marketplace from the seller's own title (CMO). The CEO asks for the details", (), _direct, session=True),
        ActionPlan("cmo.market_trends", "Research current market trends for the seller's niche (marketplace news, tactics sellers report, new product buzz) from public web search (CMO). The CEO first shows the exact searches and asks the seller to confirm", (), _direct, session=True),
        ActionPlan("cmo.market_trends_preview", "Preview the exact web searches a market-trends run would send; nothing is sent and nothing is used up", (), _preview_defaults),
        ActionPlan("cfo.cash_reconciliation", "Cash reconciliation: is the marketplace paying what it owes, for a marketplace and period", ("marketplace", "period"), _period_marketplace),
    )
}


# Actions the CEO runs ITSELF in the course of a delegated task, never offered to the classifier (not in ACTIONS, so a model can neither pick nor name one): the seller reaches
# them only through the CEO flow that builds their slots from validated references.
INTERNAL_ACTIONS: Mapping[str, ActionPlan] = {
    "cmo.analyze_attachment": ActionPlan("cmo.analyze_attachment", "CMO reads an attached product photo (by reference; internal)", (), _direct),
    # CI: id-bearing steps of the CEO's own CI flows (CI spec 6.21.3). Slots are ids the CEO validated, never text a model supplied.
    "ci.evidence_intake": ActionPlan("ci.evidence_intake", "CI reads an attached competitor screenshot (by reference; internal)", (), _direct),
    "ci.confirm_field": ActionPlan("ci.confirm_field", "CI records the seller's answers to its confirmation questions (internal)", (), _direct),
    "ci.competitor_add": ActionPlan("ci.competitor_add", "Track a competitor from a marketplace link the seller gave (internal)", (), _direct),
    "ci.competitor_approve": ActionPlan("ci.competitor_approve", "Approve a discovered competitor candidate (internal)", (), _direct),
    "ci.competitor_reject": ActionPlan("ci.competitor_reject", "Reject a discovered competitor candidate (internal)", (), _direct),
    "ci.alert_settings_set": ActionPlan("ci.alert_settings_set", "Save the seller's own competitor alert preferences (internal; the CEO parses the seller's words itself)", (), _direct),
    "ci.explain_finding": ActionPlan("ci.explain_finding", "Re-read one stored CI finding and its evidence (internal; the id comes from a dashboard control)", (), _direct),
    "ci.review_intake": ActionPlan("ci.review_intake", "CI reads an attached competitor reviews screenshot (by reference; internal)", (), _direct),
}


@dataclass(frozen=True, slots=True)
class LegPlan:
    key: str
    required: bool


@dataclass(frozen=True, slots=True)
class Playbook:
    id: str
    description: str
    required_slots: tuple[str, ...]
    legs: tuple[LegPlan, ...]
    state_reads: tuple[str, ...] = ()
    extra: Mapping[str, str] = field(default_factory=dict)
    needs_form: bool = False  # runs only from a form's structured inputs (spec 6.33); without them the seller is offered the form


PLAYBOOKS: Mapping[str, Playbook] = {
    p.id: p
    for p in (
        Playbook(
            "PROFIT_DIAGNOSIS", "Why did my profit or margin drop? Health bands, anomaly check and CFO briefing for a period", ("period",),
            (LegPlan("cfo.financial_health", True), LegPlan("cfo.anomaly_check", False), LegPlan("cfo.strategic_briefing", False)),
            ("BS_PNL_LATEST", "BS_LEAK_OPEN", "BS_DATA_GAPS"),
        ),
        Playbook(
            "CASH_AND_LEAK_CHECK", "Am I being paid what I am owed? Cash reconciliation plus a leak check, for a marketplace and period",
            ("marketplace", "period"), (LegPlan("cfo.cash_reconciliation", True), LegPlan("cfo.reconcile", True)), ("BS_LEAK_OPEN",),
        ),
        Playbook(
            "COMPETITOR_PRICE_IMPACT",
            "A competitor changed their price: what would different selling prices do to my margin? Runs from a form where the prices and per-unit costs are entered, never typed into chat",
            (), (LegPlan("ci.request_price_scenario", True), LegPlan("cfo.pricing", True)), ("BS_COMPETITOR_SNAPSHOT", "BS_SELLER_CONTEXT"), needs_form=True,
        ),
        Playbook(
            "NEW_PRODUCT_DECISION",
            "Should I stock this product, and how many units? Compares the supplier quotes I saved and fits a batch to my saved budget. Runs from a form",
            (), (LegPlan("cfo.landed_cost", True), LegPlan("cfo.supplier_ranking", True), LegPlan("cfo.batch_size", True)), ("BS_PI_REPORT_LATEST", "BS_DATA_GAPS"), needs_form=True,
        ),
        Playbook(
            "BUSINESS_BRIEFING", "Give me an overview briefing of the whole business from saved results", (), (),
            ("BS_PNL_LATEST", "BS_LEAK_OPEN", "BS_DATA_GAPS", "BS_HEALTH_BANDS", "BS_SELLER_CONTEXT", "BS_INGEST_STATUS"),
        ),
    )
}


# ------------------------------------------------------------------------------------------------ the two decision playbooks (spec 6.33)
def _run_echoes(run: PlaybookRun) -> list[str]:
    """What the system took from the form and read back, in the seller's terms (AC17). Stored values are shown with their date; unknown costs are named."""
    out: list[str] = []
    if isinstance(run.inputs, PriceImpactInputs):
        i = run.inputs
        if run.competitor_label:
            out.append(f"Competitor: {run.competitor_label}.")
        out.append(f"{len(i.candidate_prices_paise)} candidate {'price' if len(i.candidate_prices_paise) == 1 else 'prices'} compared for {i.sku} on {i.marketplace.title()}.")
        if run.cogs is not None:
            if run.cogs.amount_paise is not None:
                out.append(f"Cost per unit taken from your saved cost of {format_paise(run.cogs.amount_paise)}"
                           + (f", effective {run.cogs.effective_from.isoformat()}." if run.cogs.effective_from else "."))
            else:
                out.append("No saved cost per unit was found for this SKU, so margins are shown as unavailable until you save one.")
        for label, cost in (("Shipping", i.shipping), ("Advertising", i.advertising), ("Return and RTO losses", i.return_rto), ("Other costs", i.other)):
            if cost.state == "UNKNOWN":
                out.append(f"{label} were marked unknown, so the margins that depend on them are shown as unavailable.")
            elif cost.state == "NONE_CONFIRMED":
                out.append(f"{label}: you confirmed none (zero).")
        if i.gst_rate_pct is None:
            out.append("No GST rate was given, so GST-dependent margins are shown as unavailable.")
    else:
        n = run.inputs
        if run.history is not None:
            out.append(f"Sales history: {len(run.history.lines)} {'line' if len(run.history.lines) == 1 else 'lines'} for {n.sku} between {n.period_start.isoformat()} and {n.period_end.isoformat()}.")
            if run.history.blocked_count:
                out.append(f"{run.history.blocked_count} sales {'line' if run.history.blocked_count == 1 else 'lines'} could not be used: {'; '.join(run.history.blocked_reasons)}.")
    return out


def resolve_playbook_run(
    playbook: str, raw_inputs: object, *, tenant_id: UUID, today: date, max_candidate_prices: int | None,
) -> ResolvedSlots | Clarification:
    """Validates one playbook's form inputs and reads back what code owns (the stored cost; the assembled sales history). Raises `InvalidInputs` for a form that
    breaks the contract. A competitor that is not one of the caller's tracked competitors is a `Clarification`, never a guess."""
    parsed = validate_inputs(playbook, raw_inputs, max_candidate_prices=max_candidate_prices, today=today)
    if isinstance(parsed, PriceImpactInputs):
        match = slot_resolvers.resolve_competitor_ref(tenant_id, parsed.competitor_url_id)
        if not isinstance(match, slot_resolvers.CompetitorMatch):
            return Clarification("competitor", "That competitor is not one of your tracked competitors. Which of them do you mean?")
        run = PlaybookRun(playbook, parsed, competitor_label=match.label, cogs=ceo_reads.stored_cogs(tenant_id, parsed.sku, today))
    else:
        run = PlaybookRun(playbook, parsed, history=ceo_reads.sales_history(tenant_id, parsed.sku, period_start=parsed.period_start, period_end=parsed.period_end))
    return ResolvedSlots(tenant_id=tenant_id, today=today, run=run)


def _impact_scenario(s: ResolvedSlots) -> dict[str, object]:
    assert s.run is not None and isinstance(s.run.inputs, PriceImpactInputs)
    i = s.run.inputs
    return {
        "competitor_url_id": str(i.competitor_url_id), "seller_price_paise": i.current_price_paise, "stance": i.stance,
        "stance_param_pct": i.stance_param_pct, "stance_param_paise": i.stance_param_paise,
    }


def _impact_pricing(s: ResolvedSlots) -> dict[str, object]:
    assert s.run is not None and isinstance(s.run.inputs, PriceImpactInputs) and s.run.cogs is not None
    i, cogs = s.run.inputs, s.run.cogs
    return {
        "sku": i.sku, "candidate_prices_paise": list(i.candidate_prices_paise), "basis": i.basis, "gst_rate_pct": i.gst_rate_pct, "marketplace": i.marketplace,
        "category": i.category, "fee_type": i.fee_type, "as_of_date": s.today.isoformat(),
        "cogs_paise": cogs.amount_paise, "cogs_unavailable_reason": cogs.reason,
        **cost_to_slot(i.shipping, "shipping_logistics"), **cost_to_slot(i.advertising, "advertising_costs"),
        **cost_to_slot(i.return_rto, "return_rto_losses"), **cost_to_slot(i.other, "other_allocated_costs"),
        "active_adjustment_ids": list(cogs.adjustment_ids),
    }


def _product_landed_cost(s: ResolvedSlots) -> dict[str, object]:
    assert s.run is not None and isinstance(s.run.inputs, NewProductInputs)
    i = s.run.inputs
    return {"sku": i.sku, "supplier_quote_target_type": "SKU", "supplier_quote_target_ref": i.sku, "quantity": i.quantity, "as_of_date": s.today.isoformat()}


def _product_ranking(s: ResolvedSlots) -> dict[str, object]:
    assert s.run is not None and isinstance(s.run.inputs, NewProductInputs)
    i = s.run.inputs
    return {"sku": i.sku, "quantity": i.quantity, "as_of_date": s.today.isoformat()}


def _product_batch_size(s: ResolvedSlots) -> dict[str, object]:
    assert s.run is not None and isinstance(s.run.inputs, NewProductInputs) and s.run.history is not None
    i, h = s.run.inputs, s.run.history
    return {
        "sku": i.sku, "supplier_quote_target_type": "SKU", "supplier_quote_target_ref": i.sku, "budget_target_type": "ACCOUNT", "budget_target_ref": str(s.tenant_id),
        "canonical_lines": list(h.lines), "period_start": i.period_start.isoformat(), "period_end": i.period_end.isoformat(), "as_of_date": s.today.isoformat(),
        "active_adjustment_ids": list(h.active_adjustment_ids),
    }


# (playbook id, registry key) -> the slot builder for that leg. These legs are NOT standalone chat actions: they take structured form inputs (spec 6.33).
PLAYBOOK_LEG_SLOTS: Mapping[tuple[str, str], Callable[[ResolvedSlots], dict[str, object]]] = {
    ("COMPETITOR_PRICE_IMPACT", "ci.request_price_scenario"): _impact_scenario,
    ("COMPETITOR_PRICE_IMPACT", "cfo.pricing"): _impact_pricing,
    ("NEW_PRODUCT_DECISION", "cfo.landed_cost"): _product_landed_cost,
    ("NEW_PRODUCT_DECISION", "cfo.supplier_ranking"): _product_ranking,
    ("NEW_PRODUCT_DECISION", "cfo.batch_size"): _product_batch_size,
}
