"""Records the product details the seller confirmed from a photo reading, for the CEO chat (CMO 3.0 M0; docs/specs/slim-cmo-agent.md section 6.2.1, ceo-cmo-delegation.md 6.11).

It is the same zero-unit action as `POST /api/v1/cmo/image-hints/confirm` (`cmo.confirm_image_hint`): the seller's own confirmed or corrected value becomes a new SELLER_PROVIDED
`seller_fact` attached to the product and linked to the reading; the reading itself is never changed, the photo or model does not become trusted, no entitlement check, no reservation, no
metered event, and one `agent_run` for a new fact. It lives here (not in `ceo/`) because the CEO modules must not import an HTTP module.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID, uuid4

from slim_cmo import billing
from slim_cmo.service.models import Actor

from backend.services import cmo_actions, cmo_runtime

logger = logging.getLogger(__name__)


def record_confirmed_hints(tenant_id: UUID, user_id: UUID, *, analysis_id: str, sku: str, hints: Sequence[Mapping[str, Any]]) -> list[str]:
    """Returns the attribute names recorded as new facts. Best-effort: a hint that cannot be recorded is skipped and never blocks the seller's plan."""
    done: list[str] = []
    try:
        rt = cmo_runtime.build_runtime()
    except Exception:  # noqa: BLE001 - not configured: the seller's answers still reach the plan as their own inline facts
        logger.info("CMO runtime unavailable; photo confirmations not recorded separately")
        return done
    principal = cmo_actions.Principal(tenant_id, user_id)
    for h in hints:
        try:
            started, run_id = rt.clock(), uuid4()
            res = rt.catalog.confirm_image_hint(Actor(tenant_id, user_id), analysis_id=UUID(analysis_id), attribute_name=str(h["attribute"]), sku=sku, confirmed_value=str(h["value"]))
            if res.created:
                cmo_actions.record_free_run(principal, rt, billing.Action.CONFIRM_IMAGE_HINT, run_id, started)
                done.append(str(h["attribute"]))
        except Exception:  # noqa: BLE001
            logger.info("photo hint %s was not recorded", h.get("attribute"))
    return done
