"""Slim CMO image upload and analysis requests (P6): the HTTP-boundary orchestration around `ImageService`.

Both actions are ZERO-UNIT, exactly like `cmo.approve_title` / `cmo.confirm_image_hint`: no entitlement check, no
quota reservation, no metered event, and they never reach `cmo_actions.run_billable` or `_settle`. They write an
`agent_run` for an accepted, EXECUTED call only (an idempotent replay - an already-stored image, a reused analysis -
writes none).

Because analysis is unmetered, a per-tenant RATE LIMIT is the guard on the expensive model call (spec Q4; P6 decision
2): at most `CMO_VISION_ANALYSES_PER_WINDOW` analyses per `CMO_VISION_RATE_WINDOW_SECONDS`, counted from the tenant's
own `product_image_analysis` rows (FAILED attempts included - they cost a model call). It is checked ONLY when a model
call would actually happen, so replaying an existing analysis is never throttled. It is a soft limit (no new table, no
in-flight claim system, P6 decision 15): simultaneous requests can overshoot it by the number in flight.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from slim_cmo.service.models import Actor
from slim_cmo.service.vision import AnalysisResult, UploadResult

from backend.services import cmo_actions
from backend.services.cmo_actions import Principal
from backend.services.cmo_runtime import CmoImageRuntime

CMO_UPLOAD_IMAGE = "cmo.upload_image"
CMO_ANALYZE_IMAGE = "cmo.analyze_image"
HINT_NOTE = "suggested from your photo - please confirm"


class RateLimited(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("rate limited")


def _actor(p: Principal) -> Actor:
    return Actor(p.tenant_id, p.user_id)


def upload_json(res: UploadResult, run_id: UUID | None) -> dict[str, Any]:
    """Allow-list: the asset id and what the seller supplied. No storage uri, no path, no original bytes."""
    return {
        "assetId": str(res.asset_id), "created": res.created, "sha256": res.sha256, "width": res.width, "height": res.height,
        "contentType": res.content_type, "unitsBilled": 0, "agentRunId": str(run_id) if run_id else None,
    }


def analysis_json(res: AnalysisResult, run_id: UUID | None) -> dict[str, Any]:
    """Allow-list: validated observations only. Never the raw model reply, a prompt, the image, a provider/model name,
    an evaluation id or a storage location. An unverified observation is labelled a suggestion to confirm."""
    return {
        "analysisId": str(res.analysis_id),
        "state": res.state.value,
        "reason": res.reason,
        "reused": res.reused,
        "trustGate": {"open": res.trust_gate_open},
        "attributes": [
            {
                "name": a["name"], "value": a["value"], "basis": a["basis"], "trustState": a["trust_state"],
                "note": HINT_NOTE if a["value"] is not None and a["trust_state"] != "EVAL_PASSED" else None,
            }
            for a in res.attributes
        ],
        "unitsBilled": 0,
        "agentRunId": str(run_id) if run_id else None,
    }


def upload_image(principal: Principal, rt: CmoImageRuntime, data: bytes, declared_type: str) -> dict[str, Any]:
    started, run_id = rt.clock(), uuid4()
    res = rt.images.upload(_actor(principal), data, declared_type)  # raises ImageRejected: nothing is written
    recorded: UUID | None = None
    if res.created:  # re-uploading an identical picture is a replay: one asset, no new run
        cmo_actions.record_free_run(principal, rt, CMO_UPLOAD_IMAGE, run_id, started)
        recorded = run_id
    return upload_json(res, recorded)


def analyze_image(principal: Principal, rt: CmoImageRuntime, asset_id: UUID) -> dict[str, Any]:
    actor = _actor(principal)
    started, run_id = rt.clock(), uuid4()
    if not rt.images.has_reusable_analysis(actor, asset_id):  # NotFound for an unknown / cross-tenant / purged asset
        assert rt.rate_max is not None and rt.rate_window_seconds is not None
        since = started - timedelta(seconds=rt.rate_window_seconds)
        if rt.images.recent_analysis_count(actor, since) >= rt.rate_max:
            raise RateLimited(rt.rate_window_seconds)
    res = rt.images.analyze(actor, asset_id)
    recorded: UUID | None = None
    if not res.reused:
        cmo_actions.record_free_run(principal, rt, CMO_ANALYZE_IMAGE, run_id, started, status="FAILED" if res.state.value == "FAILED" else "COMPLETE")
        recorded = run_id
    return analysis_json(res, recorded)
