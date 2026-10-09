"""What THIS member may be offered in THIS investigation right now — spec §6.22 rule 3: attached ∩ member-permitted ∩ entitled.

Advisory for the classifier (so the model is not shown what can never run) and the source of the plain-language reason a capability
is absent. It grants nothing: `dispatch` and `business_state.read_entry` re-check permission, attachment and entitlement on every
call (R2, R13), so a stale or wrong catalog can at worst produce a refusal, never an execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.auth.context import AuthContext
from backend.auth.permissions import AGENT_CEO, has_permission
from backend.ceo import business_state
from backend.ceo.contract import AGENT_PERMISSION_KEY, AgentCode
from backend.ceo.plans import ACTIONS, PLAYBOOKS, VIRTUAL_ROUTES
from backend.ceo.registry import ActionRegistry

STATE_DESCRIPTIONS: dict[str, str] = {
    "BS_PNL_LATEST": "Latest saved profit & loss: revenue, contribution profit, marketplace fees",
    "BS_LEAK_OPEN": "Open marketplace leak findings (overcharges, short payments), biggest first",
    "BS_DATA_GAPS": "Inputs the business is still waiting on from the seller",
    "BS_HEALTH_BANDS": "Saved good / watch / at-risk health bands for the latest period",
    "BS_SELLER_CONTEXT": "What the seller has told us: their goal, priority, notes",
    "BS_INGEST_STATUS": "Which reports the seller has uploaded and their processing status",
}

PRESENT, NOT_ATTACHED, NOT_PERMITTED, NOT_ENTITLED = "PRESENT", "NOT_ATTACHED", "NOT_PERMITTED", "NOT_ENTITLED"


@dataclass(frozen=True, slots=True)
class Capabilities:
    attached: frozenset[str]
    allowed_actions: tuple[str, ...]
    allowed_playbooks: tuple[str, ...]
    allowed_state: dict[str, str]
    agent_status: dict[str, str]  # agent code -> PRESENT | NOT_ATTACHED | NOT_PERMITTED | NOT_ENTITLED
    entitled_registry_keys: frozenset[str] = frozenset()  # registry keys this member may run now (used to pick the GST route in code, spec C11)


def compute_capabilities(ctx: AuthContext, registry: ActionRegistry, attached: frozenset[str], *, now: datetime) -> Capabilities:
    assert ctx.role is not None and ctx.tenant_id is not None

    def permitted(key: str) -> bool:
        return has_permission(role=ctx.role, permissions=ctx.permissions, key=key)  # type: ignore[arg-type]

    entitled_keys = set(registry.catalog_for(ctx, attached=attached, check_entitlement=True, now=now))
    permitted_keys = set(registry.catalog_for(ctx, attached=attached, check_entitlement=False, now=now))
    actions = tuple(k for k in ACTIONS if k in entitled_keys or any(r in entitled_keys for r in VIRTUAL_ROUTES.get(k, ())))
    playbooks = tuple(pid for pid, p in PLAYBOOKS.items() if all(leg.key in entitled_keys for leg in p.legs if leg.required))

    state: dict[str, str] = {}
    if permitted(AGENT_CEO):
        for key, spec in business_state.ENTRIES.items():
            if spec.owner is not None and (spec.owner.value not in attached or not permitted(AGENT_PERMISSION_KEY[spec.owner])):
                continue
            if all(permitted(k) for k in spec.extra_permissions):
                state[key] = STATE_DESCRIPTIONS.get(key, key)

    status: dict[str, str] = {}
    for agent in AgentCode:
        if agent.value not in attached:
            status[agent.value] = NOT_ATTACHED
        elif not (permitted(AGENT_CEO) and permitted(AGENT_PERMISSION_KEY[agent])):
            status[agent.value] = NOT_PERMITTED
        else:
            keys = [s.key for s in registry.specs() if s.wired and s.agent is agent and not s.denial_surface]
            has_permitted = any(k in permitted_keys for k in keys)
            has_entitled = any(k in entitled_keys for k in keys)
            status[agent.value] = NOT_ENTITLED if has_permitted and not has_entitled else PRESENT
    return Capabilities(attached, actions, playbooks, state, status, frozenset(entitled_keys))
