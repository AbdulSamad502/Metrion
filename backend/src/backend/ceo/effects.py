"""What each registered action REALLY does outside plain computation — approval prerequisite R1 (docs/planning/ceo-approval-remediation-design.md).

`ActionSpec.effect` (READ / COMPUTE_PERSIST / GENERATE_METERED / RECORD_CHOICE) understates real behaviour: GST lookup fetches public pages and
calls a model under COMPUTE_PERSIST; two PI actions are declared GENERATE_METERED yet record no usage today (R3 fixes that). This module is the
one reviewed table of the facts the approval gate needs: the meters an action records, whether it reaches outside Metrion, which seller data
leaves, and where it goes.

Rules (owner decisions, 2026-10-10):
* An action needs approval iff it is metered, OR it sends seller-specific confidential data to a third party (`SELLER_DATA_OUT`).
* Ordinary GST public-page lookups (`PUBLIC_FETCH`) and calls to an OPERATOR-CONTROLLED model endpoint (`MODEL`) do not independently require
  approval. Whether an endpoint is operator-controlled is decided by `config.llm_endpoint_trust` (R7); an unverified endpoint is refused outright.
* `ci.discover_competitors` is internal only while its composition root is `MockSearchProvider` (a guard test pins that; wiring a real provider
  must change its row here in the same change).
* Classification is by ACTUAL data flow, evidenced in docs/planning/ceo-approval-s0-findings.md §D / §J. A payload change (e.g. adding a SKU to a
  PI query) must reclassify: `tests/integration/test_pi_payload_pins.py` fails if the payloads change.

Nothing here runs anything or changes billing. The approval gate that will consume it is a later, separately reviewed checkpoint.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


class External(str, Enum):
    NONE = "NONE"  # nothing leaves Metrion
    MODEL = "MODEL"  # seller/figure text goes to the configured LLM endpoint (must be operator-controlled: R7)
    PUBLIC_FETCH = "PUBLIC_FETCH"  # fixed public URLs are fetched; no seller data is in the request
    SELLER_DATA_OUT = "SELLER_DATA_OUT"  # seller-specific text is sent to a third-party API


@dataclass(frozen=True, slots=True)
class ActionEffects:
    meters: tuple[str, ...] = ()  # meter codes the action ACTUALLY records usage under (empty = none recorded)
    external: External = External.NONE
    egress: tuple[str, ...] = ()  # seller data classes that leave Metrion (only for SELLER_DATA_OUT)
    destinations: tuple[str, ...] = ()  # labels for the plan card (any external other than NONE/MODEL)
    model_egress: tuple[str, ...] = ()  # what the LLM endpoint receives (any action that calls a model)
    force_approval: bool = False  # an explicit extra gate; it can only ADD approval, never remove it

    @property
    def requires_approval(self) -> bool:
        return self.force_approval or bool(self.meters) or self.external is External.SELLER_DATA_OUT

    def validate(self, key: str) -> None:
        if self.external is External.SELLER_DATA_OUT and not (self.egress and self.destinations):
            raise ValueError(f"{key}: SELLER_DATA_OUT must name the egress data classes and destinations")
        if self.external in (External.PUBLIC_FETCH,) and not self.destinations:
            raise ValueError(f"{key}: PUBLIC_FETCH must name its destinations")
        if self.egress and self.external is not External.SELLER_DATA_OUT:
            raise ValueError(f"{key}: egress is only meaningful for SELLER_DATA_OUT")


_NONE = ActionEffects()
_MODEL_NARRATION = ActionEffects(external=External.MODEL, model_egress=("FIGURES_AND_LABELS",))


def _cmo_metered(key: str) -> ActionEffects:
    return ActionEffects(meters=(key,), external=External.MODEL, model_egress=("SELLER_CATALOG_TEXT",))


ACTION_EFFECTS: Mapping[str, ActionEffects] = {
    # ---- CFO: deterministic computation over the seller's own saved data (derived results are persisted; nothing leaves) ----
    "cfo.pnl_for_tenant": _NONE,
    "cfo.pricing": _NONE,
    "cfo.gst_summary": _NONE,
    "cfo.landed_cost": _NONE,
    "cfo.supplier_ranking": _NONE,
    "cfo.funding_readiness": _NONE,
    "cfo.batch_size": _NONE,
    "cfo.reconcile": _NONE,
    "cfo.anomaly_check": _NONE,  # narration is opt-in and pinned OFF by the CEO slot (plans._anomaly)
    "cfo.cash_reconciliation": _NONE,
    "cfo.financial_health": _NONE,
    "cfo.strategic_briefing": _NONE,  # include_narration pinned False by the registry
    "cfo.preview": _NONE,
    "cfo.period_comparison": _MODEL_NARRATION,  # always calls the LLM (api/v1/cfo.py post_period_comparison)
    # ---- GST: fixed public pages + a model call over the product title; no seller data in any HTTP request ----
    "cfo.gst_lookup": ActionEffects(external=External.PUBLIC_FETCH, destinations=("Public GST reference pages",), model_egress=("PRODUCT_TITLE",)),
    "service.gst_lookup": ActionEffects(external=External.PUBLIC_FETCH, destinations=("Public GST reference pages",), model_egress=("PRODUCT_TITLE",)),
    # ---- PI ----
    # Usage is recorded by R3 (one idempotent event per usable run). pi.discover also consumes the shared research.niche_run meter.
    "pi.discover": ActionEffects(
        meters=("pi.discover", "research.niche_run"), external=External.SELLER_DATA_OUT, egress=("SELLER_NICHE_TEXT",),
        destinations=("Tavily", "YouTube Data API"), model_egress=("PUBLIC_SEARCH_RESULT_TEXT",),
    ),
    # The payload is `<public candidate title> manufacturer supplier wholesale india`: candidate titles come from public search results, not
    # seller-entered text (Q-R10), so this is not SELLER_DATA_OUT; it is approval-gated because it is metered. Reclassify if the payload changes.
    "pi.supplier_lookup": ActionEffects(meters=("pi.supplier_lookup",), external=External.PUBLIC_FETCH, destinations=("Google Places", "Tavily")),
    "pi.report": _NONE,
    # ---- CI ----
    "ci.request_price_scenario": _NONE,
    "ci.discover_competitors": _NONE,  # MockSearchProvider today; pinned (tests/unit/test_ceo_effects.py)
    "ci.research_now": _NONE,  # not wired; must be reclassified (external fetch) when it is
    # ---- CMO ----
    "cmo.generate_title_sets": _cmo_metered("cmo.generate_title_sets"),
    "cmo.generate_listing_copy": _cmo_metered("cmo.generate_listing_copy"),
    "cmo.generate_description": _cmo_metered("cmo.generate_description"),
    "cmo.generate_bullets": _cmo_metered("cmo.generate_bullets"),
    "cmo.generate_keywords": _cmo_metered("cmo.generate_keywords"),
    "cmo.generate_backend_terms": _cmo_metered("cmo.generate_backend_terms"),
    "cmo.generate_hashtags": _cmo_metered("cmo.generate_hashtags"),
    "cmo.catalog_answer": _cmo_metered("cmo.catalog_answer"),
    "cmo.market_trends": ActionEffects(
        meters=("cmo.market_trends", "research.market_trends"), external=External.SELLER_DATA_OUT, egress=("CONFIRMED_NICHE_TERMS",),
        destinations=("Tavily", "YouTube Data API"), model_egress=("PUBLIC_SEARCH_RESULT_TEXT",),
    ),
    "cmo.market_trends_preview": _NONE,  # shows the exact outbound queries; sends nothing
    "cmo.suggest_niche_terms": _NONE,
    "cmo.approve_title": _NONE,
    "cmo.confirm_niche_terms": _NONE,
    "cmo.confirm_image_hint": _NONE,
}

for _key, _fx in ACTION_EFFECTS.items():
    _fx.validate(_key)


def effects_for(key: str) -> ActionEffects:
    try:
        return ACTION_EFFECTS[key]
    except KeyError:
        raise KeyError(f"no effects entry for registered action {key!r}: classify it in ceo/effects.py") from None
