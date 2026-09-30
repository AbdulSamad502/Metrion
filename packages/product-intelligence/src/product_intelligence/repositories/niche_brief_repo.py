"""niche_brief — `product-intelligence-agent.md` §5, §6.1. DRAFT/READY/ARCHIVED lifecycle;
authoring is never a direct execution path (§6.1 rule 1) — this repository only persists
what a plain CRUD form or a CEO conversation already composed.

**Checkpoint 2 — real implementation.** Mirrors
`competitor_intelligence.repositories.ci_discovery_run_repo`'s `tenant_scope()`-per-call
pattern: every function opens its own `tenant_scope(tenant_id)`, every statement filters on
`tenant_id` in addition to RLS (defence in depth, `auth.md` §7.3), all queries are
parameterized via SQLAlchemy `text()`.

`mark_ready`'s §6.1 rule 2 precondition (budget, category, at least one marketplace present)
is the caller's to check before calling — but this function ALSO re-checks it against the
row's actual persisted state before transitioning, the same defence-in-depth discipline this
package already applies to tenant isolation (RLS *and* an explicit `WHERE tenant_id` clause):
a caller's own validation bug must not be able to leave a `READY` brief missing a field the
transition itself requires.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from product_intelligence.repositories.tenant_context import tenant_scope


def create_draft(
    tenant_id: UUID,
    *,
    created_by: UUID,
    category_text: str | None = None,
    budget_paise: int | None = None,
    target_price_min_paise: int | None = None,
    target_price_max_paise: int | None = None,
    marketplaces: list[str] | None = None,
    constraints: dict[str, Any] | None = None,
) -> UUID:
    """Inserts a `DRAFT` `niche_brief` row. Returns the new row's id."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO niche_brief
                    (tenant_id, status, category_text, budget_paise, target_price_min_paise,
                     target_price_max_paise, marketplaces, constraints, created_by)
                VALUES
                    (:tenant_id, 'DRAFT', :category_text, :budget_paise, :target_price_min_paise,
                     :target_price_max_paise, CAST(:marketplaces AS text[]), CAST(:constraints AS jsonb),
                     :created_by)
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "category_text": category_text,
                "budget_paise": budget_paise,
                "target_price_min_paise": target_price_min_paise,
                "target_price_max_paise": target_price_max_paise,
                "marketplaces": marketplaces,
                "constraints": json.dumps(constraints) if constraints is not None else None,
                "created_by": str(created_by),
            },
        ).one()
        return row[0]


def get_brief(tenant_id: UUID, brief_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT * FROM niche_brief WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(brief_id)},
        ).mappings().first()
        return dict(row) if row is not None else None


def list_briefs(tenant_id: UUID, *, status: str | None = None) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        if status is not None:
            rows = conn.execute(
                text(
                    "SELECT * FROM niche_brief WHERE tenant_id = :tenant_id AND status = :status "
                    "ORDER BY created_at DESC"
                ),
                {"tenant_id": str(tenant_id), "status": status},
            ).mappings().all()
        else:
            rows = conn.execute(
                text("SELECT * FROM niche_brief WHERE tenant_id = :tenant_id ORDER BY created_at DESC"),
                {"tenant_id": str(tenant_id)},
            ).mappings().all()
        return [dict(r) for r in rows]


def update_draft(
    tenant_id: UUID,
    brief_id: UUID,
    *,
    category_text: str | None = None,
    budget_paise: int | None = None,
    target_price_min_paise: int | None = None,
    target_price_max_paise: int | None = None,
    marketplaces: list[str] | None = None,
    constraints: dict[str, Any] | None = None,
) -> None:
    """§6.1 rule 2: only a `DRAFT` (or a `READY` brief with no `QUEUED`/`RUNNING` run against
    it, which is moved back to `DRAFT` first) may be edited."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT status FROM niche_brief WHERE tenant_id = :tenant_id AND id = :id FOR UPDATE"),
            {"tenant_id": str(tenant_id), "id": str(brief_id)},
        ).first()
        if row is None:
            raise ValueError(f"niche_brief {brief_id} not found for tenant {tenant_id}")
        if row[0] != "DRAFT":
            raise ValueError(
                f"niche_brief {brief_id} is {row[0]!r}, not DRAFT — only a DRAFT brief may be "
                "edited via update_draft (§6.1 rule 2); move it back to DRAFT first"
            )

        conn.execute(
            text(
                """
                UPDATE niche_brief
                SET category_text = COALESCE(:category_text, category_text),
                    budget_paise = COALESCE(:budget_paise, budget_paise),
                    target_price_min_paise = COALESCE(:target_price_min_paise, target_price_min_paise),
                    target_price_max_paise = COALESCE(:target_price_max_paise, target_price_max_paise),
                    marketplaces = COALESCE(CAST(:marketplaces AS text[]), marketplaces),
                    constraints = COALESCE(CAST(:constraints AS jsonb), constraints)
                WHERE tenant_id = :tenant_id AND id = :id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "id": str(brief_id),
                "category_text": category_text,
                "budget_paise": budget_paise,
                "target_price_min_paise": target_price_min_paise,
                "target_price_max_paise": target_price_max_paise,
                "marketplaces": marketplaces,
                "constraints": json.dumps(constraints) if constraints is not None else None,
            },
        )


def mark_ready(tenant_id: UUID, brief_id: UUID, *, readied_at: datetime) -> None:
    """§6.1 rule 2: only when budget, category and at least one marketplace are present —
    the caller enforces that precondition; this function re-checks it against the row's
    actual persisted state before transitioning (defence in depth, same discipline this
    package already applies to tenant isolation)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT status, category_text, budget_paise, marketplaces "
                "FROM niche_brief WHERE tenant_id = :tenant_id AND id = :id FOR UPDATE"
            ),
            {"tenant_id": str(tenant_id), "id": str(brief_id)},
        ).mappings().first()
        if row is None:
            raise ValueError(f"niche_brief {brief_id} not found for tenant {tenant_id}")
        if row["status"] not in ("DRAFT", "READY"):
            raise ValueError(
                f"niche_brief {brief_id} is {row['status']!r} — only DRAFT or READY may "
                "transition to READY"
            )
        missing = []
        if not row["category_text"]:
            missing.append("category_text")
        if row["budget_paise"] is None:
            missing.append("budget_paise")
        if not row["marketplaces"]:
            missing.append("marketplaces")
        if missing:
            raise ValueError(
                f"niche_brief {brief_id} cannot transition to READY — missing required field(s): "
                f"{', '.join(missing)} (§6.1 rule 2)"
            )

        conn.execute(
            text(
                "UPDATE niche_brief SET status = 'READY', readied_at = :readied_at "
                "WHERE tenant_id = :tenant_id AND id = :id"
            ),
            {"tenant_id": str(tenant_id), "id": str(brief_id), "readied_at": readied_at},
        )


def mark_draft(tenant_id: UUID, brief_id: UUID) -> None:
    """§6.1 rule 2: a `READY` brief may be edited back to `DRAFT` at any time before a run
    starts against it; blocked while a `pi_research_run` referencing it is `QUEUED`/`RUNNING`
    — that check is the caller's (`pi_research_run_repo`), not this function's."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT status FROM niche_brief WHERE tenant_id = :tenant_id AND id = :id FOR UPDATE"),
            {"tenant_id": str(tenant_id), "id": str(brief_id)},
        ).first()
        if row is None:
            raise ValueError(f"niche_brief {brief_id} not found for tenant {tenant_id}")
        if row[0] not in ("READY", "DRAFT"):
            raise ValueError(f"niche_brief {brief_id} is {row[0]!r} — only READY may move back to DRAFT")

        conn.execute(
            text(
                "UPDATE niche_brief SET status = 'DRAFT', readied_at = NULL "
                "WHERE tenant_id = :tenant_id AND id = :id"
            ),
            {"tenant_id": str(tenant_id), "id": str(brief_id)},
        )


def archive(tenant_id: UUID, brief_id: UUID) -> None:
    with tenant_scope(tenant_id) as conn:
        result = conn.execute(
            text(
                "UPDATE niche_brief SET status = 'ARCHIVED' WHERE tenant_id = :tenant_id AND id = :id"
            ),
            {"tenant_id": str(tenant_id), "id": str(brief_id)},
        )
        if result.rowcount == 0:
            raise ValueError(f"niche_brief {brief_id} not found for tenant {tenant_id}")
