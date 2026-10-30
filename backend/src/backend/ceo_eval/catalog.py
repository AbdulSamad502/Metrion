"""The closed catalogs a classifier is offered, per scenario — harness side of spec §6.3 rules 1–2 and §6.22.

What is real and what is a harness candidate:

* **Real:** the action keys, owning agents and `GENERATE_METERED` effect come from the live registry
  (`backend.ceo.registry`), and the Business State entry ids from `backend.ceo.business_state.ENTRIES`. A fixture can
  therefore never name a key the product does not have (`tests/unit/test_ceo_eval_fixtures.py`).
* **Harness candidate (B3 owns the production versions):** the plain-language classifier descriptions, the
  classifier-level slot vocabulary, and the playbook list. Playbooks are the spec's §6.12 starter table; B4 builds the real
  ones. They are here only so the baseline has something to classify against, and are pinned to the spec table by a test.

Nothing here computes anything or touches a number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AGENTS: tuple[str, ...] = ("CFO", "CI", "PI", "CMO")

ROUTES: tuple[str, ...] = ("BUSINESS_STATE", "ACTION", "PLAYBOOK", "ADVISORY", "SYNTHESIZE", "CLARIFY", "OUT_OF_SCOPE")
EXECUTING_ROUTES: frozenset[str] = frozenset({"BUSINESS_STATE", "ACTION", "PLAYBOOK"})
KEYED_ROUTES: frozenset[str] = EXECUTING_ROUTES

# Classifier-level slot vocabulary: slots are extracted as TEXT (spec §6.3 rule 3); typed validation and rupee->paise
# parsing are deterministic code (B3), not measured here.
SLOT_VOCAB: tuple[str, ...] = (
    "period", "compare_period", "marketplace", "sku", "product", "quantity", "amount", "competitor", "niche", "option",
)
CLARIFY_TARGETS: tuple[str, ...] = (*SLOT_VOCAB, "WHICH_AGENT", "UNCLEAR_REQUEST")
MARKETPLACES: tuple[str, ...] = ("AMAZON", "FLIPKART", "MEESHO")

# Scenario = which specialists are present, i.e. attached ∩ member-permitted ∩ entitled (spec §6.22 rule 3). Attachment,
# a missing key and a missing entitlement all look the same to the classifier: the capability is simply absent.
SCENARIOS: dict[str, frozenset[str]] = {
    "FULL": frozenset(AGENTS),
    "NO_CFO": frozenset({"CI", "PI", "CMO"}),
    "NO_CI": frozenset({"CFO", "PI", "CMO"}),
    "NO_PI": frozenset({"CFO", "CI", "CMO"}),
    "NO_CMO": frozenset({"CFO", "CI", "PI"}),
    "CFO_ONLY": frozenset({"CFO"}),
    "NONE": frozenset(),
}

Kind = Literal["ACTION", "PLAYBOOK", "STATE"]


@dataclass(frozen=True, slots=True)
class CatalogItem:
    key: str
    kind: Kind
    description: str
    required_slots: tuple[str, ...] = ()
    agents_needed: frozenset[str] = frozenset()  # all must be present for the item to be offered
    metered: bool = False


# key -> (plain-language description for the classifier, classifier-level required slots)
ACTION_TEXT: dict[str, tuple[str, tuple[str, ...]]] = {
    "cfo.pnl_for_tenant": ("Compute the profit & loss for a period from the seller's reports", ("period",)),
    "cfo.pricing": ("Pricing curve: contribution margin at candidate prices for one SKU on one marketplace", ("sku", "marketplace")),
    "cfo.gst_summary": ("GST summary for a period from the seller's own reports", ("period",)),
    "cfo.query": ("Answer an open financial question about the seller's own data for a period (planned from a closed catalog)", ("period",)),
    "cfo.expense_summary": ("Answer a question about the expenses recorded in the seller's Expense Tracker for a period (totals, by category, month by month or day by day, or the entries)", ("question", "period")),
    "cfo.expense_add": ("Add an expense to the seller's Expense Tracker (the CEO asks for the details and the seller approves an exact card)", ()),
    "cfo.expense_correct": ("Change an expense the seller already recorded (the seller picks the entry and approves the change)", ()),
    "cfo.expense_void": ("Remove an expense from the seller's Expense Tracker; it stays in the history (the seller picks it, gives a reason and approves)", ()),
    "cfo.expense_paid": ("Mark an expense as paid, unpaid or partially paid (the seller picks the entry and approves)", ()),
    "cfo.performance": ("How the business performed in a period: sales, revenue, fees and profit by marketplace from the imported reports", ("period",)),
    "cfo.cash_position": ("What cash the seller expects from the marketplaces and which payables they owe (an estimate, not a bank balance)", ()),
    "cfo.import_attachments": ("Add the marketplace reports attached to the conversation to the financial records (a preview and the seller's approval first)", ()),
    "cfo.period_comparison": ("Compare two periods' results side by side", ("period", "compare_period")),
    "cfo.landed_cost": ("Landed cost of buying a quantity of one SKU from a supplier quote", ("sku", "quantity")),
    "cfo.supplier_ranking": ("Rank supplier quotes for a quantity of one SKU", ("sku", "quantity")),
    "cfo.funding_readiness": ("Is the business ready to apply for funding, over a period", ("period",)),
    "cfo.batch_size": ("How many units to order within a budget for one SKU", ("sku", "amount")),
    "cfo.reconcile": ("Reconcile marketplace settlements against orders to find leaks, for a marketplace and period", ("marketplace", "period")),
    "cfo.anomaly_check": ("Check a period for statistically unusual changes in results", ("period",)),
    "cfo.financial_health": ("Financial health bands (good / watch / at-risk) for a period", ("period",)),
    "cfo.cash_reconciliation": ("Cash reconciliation: is the marketplace paying what it owes, for a marketplace and period", ("marketplace", "period")),
    "cfo.strategic_briefing": ("CFO strategic briefing for a period", ("period",)),
    "cfo.gst_lookup": ("Which GST rate likely applies to a product, from its name (provisional lookup from a cited source)", ("product",)),
    "pi.discover": ("Run product niche discovery for a niche (METERED, costs units)", ("niche",)),
    "pi.supplier_lookup": ("Look up suppliers for chosen candidates from a finished product-research run (METERED)", ()),
    "pi.report": ("Show a finished product-research run again from saved data", ()),
    "ci.request_price_scenario": ("Competitor price positioning and a repricing scenario for one competitor", ("competitor",)),
    "ci.discover_competitors": ("Find competitors for one of the seller's products", ("product",)),
    "ci.monitor_competitors": ("Re-check the tracked competitors from saved evidence (freshness, verified changes)", ()),
    "ci.review_findings": ("What saved competitor review evidence says (recurring complaints, strengths)", ()),
    "ci.competitor_remove": ("Stop tracking one named competitor", ("competitor",)),
    "cmo.generate_title_sets": ("Write product title options for a product and marketplace (METERED)", ("product", "marketplace")),
    "cmo.analyze_titles": ("Compare the saved title options for a marketplace, with reasons (no scores or ranking)", ("marketplace",)),
    "cmo.keyword_intelligence": ("Research which keywords fit a product, with the evidence for each (no search volume)", ("product",)),
    "cmo.approve_title": ("Record the seller's choice of one generated title option", ("option",)),
    "cmo.generate_full_listing": ("Write a complete, audited listing (copy pack, Amazon backend terms, keyword map and audit) for a product and marketplace from the approved title (METERED)", ("product", "marketplace")),
    "cmo.rewrite_listing_section": ("Have the model rewrite one bullet or the description of the saved complete listing to mention a confirmed detail (METERED, 1 unit)", ("product", "marketplace")),
    "cmo.generate_listing_copy": ("Write a full listing (title, description, bullets) for a product and marketplace (METERED)", ("product", "marketplace")),
    "cmo.generate_description": ("Write a product description for a marketplace (METERED)", ("product", "marketplace")),
    "cmo.generate_bullets": ("Write bullet points for a product on a marketplace (METERED)", ("product", "marketplace")),
    "cmo.generate_keywords": ("Write search keywords for a product on a marketplace (METERED)", ("product", "marketplace")),
    "cmo.generate_backend_terms": ("Write hidden backend search terms for a product on a marketplace (METERED)", ("product", "marketplace")),
    "cmo.generate_hashtags": ("Write social hashtags for a product (METERED)", ("product",)),
    "cmo.catalog_answer": ("Answer marketplace catalog attribute questions for a product (METERED)", ("product",)),
    "cmo.confirm_image_hint": ("Confirm or correct an attribute read from a product image", ()),
    "cmo.suggest_niche_terms": ("Suggest niche search terms from the seller's catalog", ()),
    "cmo.confirm_niche_terms": ("Confirm the niche terms the seller wants researched", ()),
    "cmo.market_trends_preview": ("Preview what a market-trends report would cover and cost, for a niche (free)", ("niche",)),
    "cmo.market_trends": ("Generate the market-trends report for a niche (METERED; only after a preview)", ("niche",)),
}

# Harness candidates from spec §6.12's starter table. The two form playbooks take NO chat slots (spec 6.33: money is entered in a form), as in production: id -> (description, agents it needs, required slots)
PLAYBOOK_TEXT: dict[str, tuple[str, frozenset[str], tuple[str, ...]]] = {
    "PROFIT_DIAGNOSIS": ("Why did my profit or margin drop? Health, anomalies and a briefing for a period", frozenset({"CFO"}), ("period",)),
    "COMPETITOR_PRICE_IMPACT": ("A competitor changed their price — what does it do to my margin?", frozenset({"CI", "CFO"}), ()),
    "NEW_PRODUCT_DECISION": ("Should I stock this product, and how much? Landed cost, batch size, supplier ranking", frozenset({"CFO"}), ()),
    "CASH_AND_LEAK_CHECK": ("Am I being paid what I am owed? Cash reconciliation plus leak check", frozenset({"CFO"}), ("marketplace", "period")),
    "BUSINESS_BRIEFING": ("Give me an overview briefing of the whole business from saved results", frozenset(), ()),
}

# Business State owners (spec §6.13) — mirrored here as a fallback description source; the keys themselves are read from the module.
_STATE_ROUTE_HINT: dict[str, str] = {
    "BS_PNL_LATEST": "Latest saved profit & loss: revenue, contribution profit, marketplace fees",
    "BS_LEAK_OPEN": "Open marketplace leak findings (overcharges, short payments), biggest first",
    "BS_DATA_GAPS": "Inputs the business is still waiting on from the seller",
    "BS_HEALTH_BANDS": "Saved good / watch / at-risk health bands for the latest period",
    "BS_SELLER_CONTEXT": "What the seller has told us: their goal, priority, notes",
    "BS_INGEST_STATUS": "Which reports the seller has uploaded and their processing status",
    "BS_PNL_RECENT": "The newest saved profit & loss periods side by side: revenue, contribution profit, marketplace fees",
    "BS_SELLER_FACTS": "What the seller told us about their business: name, niche, marketplaces, goal",
    "BS_CMO_CONTENT_LATEST": "The listing titles, descriptions, keywords or hashtags Slim CMO last wrote",
    "BS_COMPETITOR_SNAPSHOT": "The latest captured listed price of each tracked competitor",
    "BS_PI_REPORT_LATEST": "The state of the most recent product research run",
    "BS_SHARED_FINDINGS": "What each agent has found and reported, labelled by trust",
    "BS_CMO_WORKFLOW": "What Slim CMO last produced and how each ended",
}


@dataclass(frozen=True, slots=True)
class Catalog:
    scenario: str
    present: frozenset[str]
    actions: tuple[CatalogItem, ...]
    playbooks: tuple[CatalogItem, ...]
    state: tuple[CatalogItem, ...]

    def items(self) -> tuple[CatalogItem, ...]:
        return (*self.state, *self.actions, *self.playbooks)

    def keys_for_route(self, route: str) -> tuple[str, ...]:
        group = {"BUSINESS_STATE": self.state, "ACTION": self.actions, "PLAYBOOK": self.playbooks}.get(route, ())
        return tuple(i.key for i in group)

    def item(self, key: str) -> CatalogItem | None:
        return next((i for i in self.items() if i.key == key), None)

    def all_keys(self) -> frozenset[str]:
        return frozenset(i.key for i in self.items())


def _registry_actions() -> dict[str, tuple[str, bool]]:
    """key -> (owning agent code, metered) for every action CEO may offer in chat: wired, attachable, not the denial surface."""
    from backend.ceo.contract import Effect
    from backend.ceo.plans import INTERNAL_ACTIONS
    from backend.ceo.registry import get_registry

    return {
        s.key: (s.agent.value, s.effect is Effect.GENERATE_METERED)
        for s in get_registry().specs()
        if s.wired and s.agent is not None and not s.denial_surface and s.key not in INTERNAL_ACTIONS  # internal hand-offs are never offered to the classifier
    }


def chat_action_keys() -> frozenset[str]:
    return frozenset(_registry_actions())


def state_entries() -> dict[str, str | None]:
    """Built Business State entry id -> owning agent code (None = CEO-owned, always readable)."""
    from backend.ceo import business_state, question_types

    owners: dict[str, str | None] = {k: (e.owner.value if e.owner is not None else None) for k, e in business_state.ENTRIES.items()}
    owners.update({qt_id: None for qt_id in question_types.QUESTION_TYPES})  # the business Q&A question types are always offered to the CEO's member
    return owners


def build_catalog(scenario: str) -> Catalog:
    from backend.ceo import question_types

    if scenario not in SCENARIOS:
        raise KeyError(f"unknown scenario {scenario!r}")
    present = SCENARIOS[scenario]
    live = _registry_actions()
    actions = tuple(
        CatalogItem(k, "ACTION", ACTION_TEXT[k][0], ACTION_TEXT[k][1], frozenset({agent}), metered)
        for k, (agent, metered) in live.items()
        if agent in present
    )
    playbooks = tuple(
        CatalogItem(pid, "PLAYBOOK", desc, slots, needs)
        for pid, (desc, needs, slots) in PLAYBOOK_TEXT.items()
        if needs <= present
    )
    state = tuple(
        CatalogItem(k, "STATE", _STATE_ROUTE_HINT.get(k) or question_types.descriptions().get(k, k), (), frozenset({owner}) if owner else frozenset())
        for k, owner in state_entries().items()
        if owner is None or owner in present
    )
    return Catalog(scenario, present, actions, playbooks, state)
