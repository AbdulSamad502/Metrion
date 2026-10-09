"""The GST lookup invocation for the registry (spec C11, G1-G7), kept apart so `registry.py` stays the only module that imports API handlers while this one
holds the single, declared use of the CFO service function (the same precedent as `derived_reads.py`).

It runs the shared tier-3 PROVISIONAL lookup (G3): the rate in the payload is copied from the STORED `gst_lookup_result`, never generated. Route A and Route B
run the same lookup; only who may call it and what is metered differ. Nothing derived from CFO analyses is added (G5), and nothing here can apply a result
to a calculation (G4: acceptance remains CFO's own flow with `financials.adjust`)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, Field

from backend.auth.context import AuthContext
from backend.ceo.contract import LegContext


class GstSlots(BaseModel):
    """The product text the seller typed (basis SELLER_PROVIDED, G6). No category or HSN is passed from chat: an image-derived hint never is."""

    model_config = {"extra": "forbid"}
    product_title: str = Field(min_length=1, max_length=200)


def invoke(
    slots: GstSlots, ctx: AuthContext, leg: LegContext, *, result_to_dict: Callable[[Any], dict[str, object]], no_match_to_dict: Callable[[Any], dict[str, object]],
) -> Mapping[str, Any]:  # noqa: ARG001
    """The two converters are the CFO API's own (`_gst_lookup_result_to_dict` / `_gst_lookup_no_match_to_dict`), handed in by the registry, which is the
    only module allowed to import an HTTP module, so the wire shape lives in exactly one place."""
    from backend.services import cfo_actions

    assert ctx.tenant_id is not None
    outcome = cfo_actions.run_gst_applicability_lookup(
        ctx.tenant_id, cfo_actions.GstLookupRequest(product_title=slots.product_title, requested_by=ctx.app_user_id)
    )
    result = result_to_dict(outcome.result) if outcome.result is not None else None
    return {
        "result": result, "gstLookupResultId": result["id"] if result else None,
        "noMatch": no_match_to_dict(outcome.no_match) if outcome.no_match is not None else None,
    }
