"""agent_run — ceo-agent-orchestration.md §5, C7. Table is owned/migrated by `backend`, not
this package, but it's GRANTed to `metrion_app` and RLS-scoped the same way every tenant
table in this project is, so writing to it from here is just another tenant_scope() call.

`permission_check`/`entitlement_check` are REQUIRED parameters, not something this function
computes. CI holds no opinion on auth.md §7.1's permission/entitlement chain — that decision
belongs to whatever caller sits in front of this package (eventually a FastAPI route wired to
the real chain). Hardcoding 'PASS' here would fabricate an audit record for a check that
never ran, which is worse than not recording one at all.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.types import RunStatus


def insert_agent_run(
    tenant_id: UUID,
    *,
    trigger_ref: str,
    requested_by: UUID,
    permission_check: str,
    entitlement_check: str,
    status: RunStatus,
    output_refs: list[str] | None,
    error_reason: str | None,
    started_at: datetime,
    finished_at: datetime | None,
    parent_run_id: UUID | None = None,
) -> UUID:
    """`parent_run_id` is `None` for a pure direct-path invocation (C20 — the user triggered
    CI directly, no CEO involved) and set to the CEO Hub's own row id when CI was dispatched
    by it (Step 4's dummy CEO). `trigger_type` stays `'DIRECT'` in both cases — it describes
    *how CI itself was invoked* (never through an LLM classification step, which is what
    `'CONVERSATIONAL'` actually means, C4 ceo-agent-orchestration.md), not who dispatched it;
    `parent_run_id` is the field that carries that distinction (C7)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO agent_run (
                  tenant_id, agent_id, trigger_type, trigger_ref, investigation_id, parent_run_id,
                  requested_by, permission_check, entitlement_check, status, output_refs,
                  error_reason, started_at, finished_at
                ) VALUES (
                  :tenant_id, 'CI', 'DIRECT', :trigger_ref, NULL, :parent_run_id,
                  :requested_by, :permission_check, :entitlement_check, :status,
                  CAST(:output_refs AS jsonb), :error_reason, :started_at, :finished_at
                )
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "trigger_ref": trigger_ref,
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "requested_by": str(requested_by),
                "permission_check": permission_check,
                "entitlement_check": entitlement_check,
                "status": status.value,
                "output_refs": json.dumps(output_refs) if output_refs is not None else None,
                "error_reason": error_reason,
                "started_at": started_at,
                "finished_at": finished_at,
            },
        ).one()
        return cast(UUID, row[0])
