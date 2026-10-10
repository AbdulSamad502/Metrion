"""The needs catalog - spec agent-needs-and-shared-knowledge.md section 5.

An agent never calls another agent. When a request carries an add-on ("the description along with the GST %"), the CEO fulfils it by running the PROVIDING agent's
registered action through the one choke point and shows the result beside the requester's own output. Which add-ons exist, who may ask for them, who provides and where
every slot comes from is this table, in code; no model, tenant or request can add to it. A slot is taken only from the seller's own words or a stored input - never from
specialist free text or from another leg's output.

V1 slice S1 builds one entry, `GST_RATE_FOR_PRODUCT` (CMO -> the GST lookup), in PARALLEL mode: its slot does not depend on any leg's output, so it can run in the same turn.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from backend.ceo.plans import GST_KEY

MAX_PRODUCT_TEXT_CHARS = 200  # the GST lookup's own bound (`GstSlots.product_title`): longer text is asked about, never truncated


@dataclass(frozen=True, slots=True)
class NeedSpec:
    need_key: str
    requester: str  # the agent whose action carries the add-on
    requester_actions: tuple[str, ...]  # the registry keys of that agent the add-on may ride on
    provider_key: str  # a registry key or a virtual route resolved by code (`plans.GST_KEY`)
    mode: str  # PARALLEL | OFFER (AFTER_RESULT is specified but not built)
    ui_label: str  # shown to the seller as the step the CEO took


NEEDS: Mapping[str, NeedSpec] = {
    n.need_key: n
    for n in (
        NeedSpec("GST_RATE_FOR_PRODUCT", "CMO", ("cmo.generate_description",), GST_KEY, "PARALLEL", "The CEO asked for the GST rate for your product"),
        # The next two are playbook-level links the seller starts from a PI idea ("is #3 worth stocking?") or a competitor ("what is my margin at X's price?"). They are not
        # add-ons on another action (no requester_actions), so `valid_addons` never accepts them; the orchestrator records them when those flows run (spec 5.2, S2).
        NeedSpec("LANDED_COST_FOR_IDEA", "PI", (), "NEW_PRODUCT_DECISION", "OFFER", "The CEO asked the CFO for the landed cost and batch size of this idea"),
        NeedSpec("MARGIN_AT_PRICE", "CI", (), "COMPETITOR_PRICE_IMPACT", "PARALLEL", "The CEO asked the CFO for your margin at the competitor's price"),
    )
}

# a need whose requester and provider are the same agent could loop: refused when this module loads
_PROVIDER_AGENT = {GST_KEY: "CFO", "NEW_PRODUCT_DECISION": "CFO", "COMPETITOR_PRICE_IMPACT": "CFO"}
for _n in NEEDS.values():
    assert _PROVIDER_AGENT.get(_n.provider_key) != _n.requester, f"{_n.need_key}: requester and provider are the same agent"


def valid_addons(action_key: str | None, addons: Sequence[str]) -> list[str]:
    """The add-ons that may ride on this action: in the catalog, requested by an agent that owns the action, de-duplicated and in the order asked. Anything else is dropped."""
    out: list[str] = []
    for a in addons:
        spec = NEEDS.get(a)
        if spec is not None and action_key in spec.requester_actions and a not in out:
            out.append(a)
    return out


def product_text(inputs: Mapping[str, Any] | None) -> str | None:
    """The seller's own product text for the add-on: the title they gave, else the product name. None when there is none or it is too long to pass on whole."""
    for k in ("seller_title", "product_name"):
        v = " ".join(str((inputs or {}).get(k) or "").split())
        if v:
            return v if len(v) <= MAX_PRODUCT_TEXT_CHARS else None
    return None
