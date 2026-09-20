"""ceo_hub.dispatch_ci_research_now — Step 4's dummy CEO. Verifies the parent/child
agent_run linkage (C7) actually holds against a real Postgres: the CEO's own row has
parent_run_id=NULL, and CI's row has parent_run_id set to the CEO's id.

Requires both backend's and competitor-intelligence's migrations applied to the same
database — they share one Postgres instance in this repo.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from backend.agents import ceo_hub
from backend.tenant_context import tenant_scope
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.repositories import competitor_url_repo
from competitor_intelligence.repositories.tenant_context import tenant_scope as ci_tenant_scope
from competitor_intelligence.types import Marketplace


class _FakeExtractor:
    def __init__(self) -> None:
        self.responses: dict[str, ExtractionResult] = {}
        self.calls: list[str] = []

    def extract(self, image_ref: str) -> ExtractionResult:
        self.calls.append(image_ref)
        return self.responses[image_ref]


def _make_tenant_and_url(migrate_engine, tenant_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    added_by = uuid.uuid4()
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenant (id, clerk_org_id, business_name, status, created_at) "
                "VALUES (:id, :clerk_org_id, 'Test Tenant', 'ACTIVE', now())"
            ),
            {"id": str(tenant_id), "clerk_org_id": f"org_{tenant_id}"},
        )
        conn.execute(
            text("INSERT INTO app_user (id, clerk_user_id, email, auth_provider, created_at) "
                 "VALUES (:id, :clerk_user_id, :email, 'EMAIL_PASSWORD', now())"),
            {"id": str(added_by), "clerk_user_id": f"user_{added_by}", "email": f"{added_by}@example.com"},
        )
    url_id = competitor_url_repo.create_url(
        tenant_id, marketplace=Marketplace.AMAZON, url="https://amazon.in/dp/ceo-hub-fixture", added_by=added_by
    )
    return url_id, added_by


def test_ceo_dispatches_to_ci_with_correct_parent_child_linkage(migrate_engine):
    tenant_id = uuid.uuid4()
    url_id, requested_by = _make_tenant_and_url(migrate_engine, tenant_id)
    now = datetime.now(timezone.utc)

    extractor = _FakeExtractor()
    extractor.responses["img-1"] = ExtractionResult(
        fields=(ExtractedField("listed_price_paise", 100000), ExtractedField("availability", "IN_STOCK"))
    )

    result = ceo_hub.dispatch_ci_research_now(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=url_id,
        image_refs=["img-1"],
        manual_fields=None,
        permission_check="PASS",
        extractor=extractor,
        now=now,
    )

    assert result.ci_result.snapshot_id is not None
    assert result.ci_result.capture_status.value == "COMPLETE"

    # The linkage this whole step exists to prove (C7):
    with tenant_scope(tenant_id) as conn:
        ceo_row = conn.execute(
            text("SELECT agent_id, trigger_type, parent_run_id, status FROM agent_run WHERE id = :id"),
            {"id": str(result.ceo_agent_run_id)},
        ).mappings().one()
    assert ceo_row["agent_id"] == "CEO"
    assert ceo_row["parent_run_id"] is None
    assert ceo_row["status"] == "COMPLETE"

    with ci_tenant_scope(tenant_id) as conn:
        ci_row = conn.execute(
            text("SELECT agent_id, trigger_type, parent_run_id, status FROM agent_run WHERE id = :id"),
            {"id": str(result.ci_result.agent_run_id)},
        ).mappings().one()
    assert ci_row["agent_id"] == "CI"
    assert ci_row["trigger_type"] == "DIRECT"
    assert ci_row["parent_run_id"] == result.ceo_agent_run_id
    assert ci_row["status"] == "COMPLETE"


def test_pure_direct_path_still_has_no_parent(migrate_engine):
    """Sanity check that Step 4 didn't change CI's own direct-path behavior — a
    parent_run_id is only ever set when dispatched THROUGH the CEO Hub."""
    from competitor_intelligence.direct_path.research_run import submit_research_session

    tenant_id = uuid.uuid4()
    url_id, requested_by = _make_tenant_and_url(migrate_engine, tenant_id)
    extractor = _FakeExtractor()
    extractor.responses["img-1"] = ExtractionResult(
        fields=(ExtractedField("listed_price_paise", 100000), ExtractedField("availability", "IN_STOCK"))
    )

    result = submit_research_session(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=url_id,
        image_refs=["img-1"],
        manual_fields=None,
        permission_check="PASS",
        entitlement_check="PASS",
        extractor=extractor,
    )

    with ci_tenant_scope(tenant_id) as conn:
        ci_row = conn.execute(
            text("SELECT parent_run_id FROM agent_run WHERE id = :id"), {"id": str(result.agent_run_id)}
        ).mappings().one()
    assert ci_row["parent_run_id"] is None
