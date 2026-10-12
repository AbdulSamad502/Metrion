"""Shared fakes for the CEO unit tests — no database, no Clerk, no model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import BaseModel

from backend.auth.context import AuthContext
from backend.auth.permissions import AGENT_CEO, AGENT_CFO, INVESTIGATION_VIEW, OWNER_ROLE, PARTNER_ROLE
from backend.ceo.contract import ActionSpec, AgentCode, Effect
from backend.ceo.registry import ActionRegistry

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def make_ctx(*, role: str = PARTNER_ROLE, permissions: dict[str, object] | None = None, tenant_id: uuid.UUID | None = None) -> AuthContext:
    return AuthContext(
        app_user_id=uuid.uuid4(), clerk_user_id="user_test", email_verified=True,
        tenant_id=tenant_id or uuid.uuid4(), membership_status="ACTIVE", role=role,
        permissions=permissions if permissions is not None else {}, onboarding_state="ACTIVE",
    )


def partner(*keys: str, tenant_id: uuid.UUID | None = None) -> AuthContext:
    return make_ctx(role=PARTNER_ROLE, permissions={k: True for k in keys}, tenant_id=tenant_id)


def owner(tenant_id: uuid.UUID | None = None) -> AuthContext:
    return make_ctx(role=OWNER_ROLE, tenant_id=tenant_id)


CHAT_KEYS = (AGENT_CEO, INVESTIGATION_VIEW)


class Slots(BaseModel):
    model_config = {"extra": "forbid"}
    period: str
    include_narration: bool = True


@dataclass
class RunLog:
    """In-memory stand-in for `agent_run_repo` + `investigation_repo` writes."""

    inserted: list[dict[str, Any]] = field(default_factory=list)
    finished: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    attached: frozenset[str] = frozenset({"CFO", "CI", "PI", "CMO"})


@pytest.fixture
def runlog(monkeypatch: pytest.MonkeyPatch) -> RunLog:
    from backend.ceo import dispatch as dispatch_module
    from backend.repositories import agent_run_repo, investigation_repo

    log = RunLog()

    def insert_run(tenant_id, **kw):  # type: ignore[no-untyped-def]
        run_id = kw.pop("run_id", None) or uuid.uuid4()
        parent = kw.get("parent_run_id")
        if parent is None and kw.get("inherit_parent", True):
            parent = agent_run_repo.CURRENT_PARENT_RUN_ID.get()
        log.inserted.append({"id": run_id, "tenant_id": tenant_id, **kw, "parent_run_id": parent})
        return run_id

    def finish_run(tenant_id, run_id, **kw):  # type: ignore[no-untyped-def]
        log.finished.append({"id": run_id, "tenant_id": tenant_id, **kw})

    def finish_run_if_unfinished(tenant_id, run_id, **kw):  # type: ignore[no-untyped-def]
        # the choke point's leg write is guarded (R5 Stage A); the fake records it exactly like an unguarded finish and always wins the race
        log.finished.append({"id": run_id, "tenant_id": tenant_id, **kw})
        return True

    def insert_finding(tenant_id, investigation_id, **kw):  # type: ignore[no-untyped-def]
        finding_id = uuid.uuid4()
        log.findings.append({"id": finding_id, "tenant_id": tenant_id, "investigation_id": investigation_id, **kw})
        return finding_id

    monkeypatch.setattr(agent_run_repo, "insert_run", insert_run)
    monkeypatch.setattr(agent_run_repo, "finish_run", finish_run)
    monkeypatch.setattr(agent_run_repo, "finish_run_if_unfinished", finish_run_if_unfinished)
    monkeypatch.setattr(investigation_repo, "insert_finding", insert_finding)
    monkeypatch.setattr(investigation_repo, "attached_agents", lambda tenant_id, investigation_id: log.attached)
    monkeypatch.setattr(dispatch_module, "resolve_ceo_entitlement", lambda tenant_id, occurred_at=None: _Pass())
    return log


@dataclass
class _Pass:
    passed: bool = True
    reason: str | None = None
    meter_code: str = "ceo.chat_turn"
    evaluation_basis: str = "NO_CAP_CONFIGURED"


@dataclass
class Verdict:
    passed: bool
    reason: str | None = None
    meter_code: str = "cfo.test"
    evaluation_basis: str = "UNDER_CAP"


def spec(
    key: str = "cfo.test_read", *, agent: AgentCode | None = AgentCode.CFO, source: str = "CFO", invoke=None, entitlement=None,
    required_permissions: tuple[str, ...] = (), writes_own_run: bool = False, slot_model=Slots, fixed_params=None,
    effect: Effect = Effect.READ, not_wired_reason: str | None = None,
) -> ActionSpec:
    if invoke is None and not_wired_reason is None:
        invoke = lambda slots, ctx, leg: {"engineResultRef": str(uuid.uuid4()), "ok": True}  # noqa: E731
    return ActionSpec(
        key=key, source=source, agent=agent, effect=effect, description="test", required_permissions=required_permissions,
        slot_model=slot_model, invoke=invoke, entitlement=entitlement, fixed_params=fixed_params or {},
        writes_own_run=writes_own_run, not_wired_reason=not_wired_reason,
    )


def registry_of(*specs: ActionSpec) -> ActionRegistry:
    return ActionRegistry(specs)
