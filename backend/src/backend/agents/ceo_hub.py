"""The dummy CEO Hub — the first CEO-to-agent integration pattern in this codebase.

This is deliberately NOT `ceo-agent-orchestration.md`'s real CEO. There is no LLM
classification, no conversational routing, no multi-action turn — exactly one hardcoded
action (`ci.research_now`) is accepted and dispatched. Its purpose is to prove the
parent/child `agent_run` linkage (C7: "every fanned-out sub-agent/Brain-1 call gets
parent_run_id set to that row's id") actually works end-to-end, once, before the real CEO's
classifier/routing layer is built. Every other agent (PI/CFO/CMO) stays unconnected.

Requires `packages/competitor-intelligence` to be installed in this environment
(`pip install -e packages/competitor-intelligence`) — it is not yet declared as a pyproject
dependency of `backend`, matching this repo's existing convention of installing sibling
packages as separate steps (see `.github/workflows/ci.yml`) rather than cross-referencing
them in `pyproject.toml`; `backend` itself isn't wired into that CI workflow yet either.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from uuid import UUID

from competitor_intelligence.direct_path.research_run import ResearchSessionResult, submit_research_session
from competitor_intelligence.evidence.extraction import VisionExtractor

from backend.repositories import agent_run_repo

CI_RESEARCH_NOW = "ci.research_now"


@dataclass(frozen=True, slots=True)
class CeoHubResult:
    ceo_agent_run_id: UUID
    ci_result: ResearchSessionResult


def dispatch_ci_research_now(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    competitor_url_id: UUID,
    image_refs: Sequence[str],
    manual_fields: Mapping[str, Any] | None,
    permission_check: str,
    extractor: VisionExtractor,
    now: datetime | None = None,
) -> CeoHubResult:
    """The one action this dummy CEO knows: route a research request to CI, exactly as a
    real CEO would per the star topology (C1) — CEO is the only router, CI never gets called
    by another agent directly. `entitlement_check` is hardcoded to `"PASS"` below with a
    TODO, not silently treated as real: no entitlement/credit metering exists anywhere in
    this codebase yet (competitor-intelligence-agent.md §12 Q2/Q3) — this is a known,
    flagged gap, not a fabricated pass on a check that was actually performed.
    `permission_check`, by contrast, IS real — it's `agent.ci`, verified by `auth/context.py`'s
    six-step chain before this function is ever called (see `api/v1/ceo_hub.py`).
    """
    now = now or datetime.now(timezone.utc)

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",  # no LLM classification happened — see agent_run_repo docstring note
        trigger_ref=f"ceo_hub.{CI_RESEARCH_NOW}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check="PASS",  # TODO: no entitlement metering exists yet (Q2/Q3) — see docstring above
        status="RUNNING",
        started_at=now,
    )

    ci_result = submit_research_session(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=competitor_url_id,
        image_refs=image_refs,
        manual_fields=manual_fields,
        permission_check=permission_check,
        entitlement_check="PASS",  # same flagged gap as above — CI's own module refuses to assume this itself
        extractor=extractor,
        now=now,
        parent_run_id=ceo_agent_run_id,
    )

    agent_run_repo.finish_run(
        tenant_id,
        ceo_agent_run_id,
        status=ci_result.status.value,
        error_reason=None if ci_result.status.value != "FAILED" else "CI research session failed",
        finished_at=now,
    )

    return CeoHubResult(ceo_agent_run_id=ceo_agent_run_id, ci_result=ci_result)
