"""Seeders and contexts for the CEO integration tests. Everything goes through the real repositories as `metrion_app`
(never a test-only shortcut), so what the tests read is exactly what production code would have persisted."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from calc_engine.repositories import metric_result_repo
from calc_engine.api.compute_metric import MetricResult
from calc_engine.types import RecognitionState
from sqlalchemy import text

from backend.auth.context import AuthContext
from backend.auth.permissions import OWNER_ROLE, PARTNER_ROLE
from backend.tenant_context import tenant_scope

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
ALL_AGENTS = frozenset({"CFO", "CI", "PI", "CMO"})


def ctx_for(tenant_id: uuid.UUID, *, role: str = OWNER_ROLE, permissions: dict[str, object] | None = None, user_id: uuid.UUID | None = None) -> AuthContext:
    return AuthContext(
        app_user_id=user_id or uuid.uuid4(), clerk_user_id="user_test", email_verified=True, tenant_id=tenant_id,
        membership_status="ACTIVE", role=role, permissions=permissions or {}, onboarding_state="ACTIVE",
    )


def partner_ctx(tenant_id: uuid.UUID, *keys: str) -> AuthContext:
    return ctx_for(tenant_id, role=PARTNER_ROLE, permissions={k: True for k in keys})


def save_metric(
    tenant_id: uuid.UUID, metric_code: str, *, period: str | None, value_paise: int | None = 100000, available: bool = True,
    computed_at: datetime = T0, confidence: str = "DERIVED", fraction: tuple[int, int] | None = None, unavailable_reason: str | None = None,
) -> uuid.UUID:
    from fractions import Fraction

    result = MetricResult(
        id=uuid.uuid4(), metric_code=metric_code, value_paise=value_paise if available and fraction is None else None,
        recognition_state=RecognitionState.RECOGNISED if available else RecognitionState.UNAVAILABLE, confidence=confidence,
        calculation_basis="seeded for a CEO test", formula_version="test.v1", canonical_data_version="non-canonical",
        as_of_date=date(2026, 10, 1), input_refs=(), exclusions=(), computed_at=computed_at, is_available=available,
        value_fraction=Fraction(*fraction) if fraction is not None else None, unavailable_reason=unavailable_reason,
    )
    return metric_result_repo.save(tenant_id, result, grain="TENANT_PERIOD" if period else "SKU", target_ref=str(tenant_id), period=period, config_version="1")


def insert_leak(
    tenant_id: uuid.UUID, *, severity: str, amount_paise: int, status: str = "NEW", marketplace: str = "FLIPKART", category: str = "COMMISSION_OVERCHARGE",
    sku: str | None = None, observed: datetime = T0,
) -> uuid.UUID:
    from cfo.repositories import leak_finding_repo

    return leak_finding_repo.insert(
        tenant_id, reconciliation_exception_id=uuid.uuid4(), engine_result_ref=uuid.uuid4(), marketplace=marketplace,
        leak_category=category, severity=severity, amount_paise=amount_paise, affected_line_count=1, first_observed_at=observed,
        age_days=1, status=status, confidence="DERIVED", formula_version="test.v1", sku=sku,
    )


def row_counts(tenant_id: uuid.UUID, *tables: str) -> dict[str, int]:
    allowed = {"metric_result", "leak_finding", "agent_run", "manual_adjustment", "agent_data_request", "metered_event", "investigation",
               "investigation_turn", "investigation_finding", "investigation_message", "investigation_agent"}
    assert set(tables) <= allowed
    with tenant_scope(tenant_id) as conn:
        return {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in tables}


def seed_platform_cap(migrate_engine, *, agent_code: str, meter_code: str, cap_value: int) -> None:
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO entitlement_cap_config (id, tenant_id, agent_code, meter_code, scope, period_unit, cap_value, effective_from, version) "
                "VALUES (:id, NULL, :agent, :meter, 'TENANT', 'MONTH', :cap, :eff, 1)"
            ),
            {"id": str(uuid.uuid4()), "agent": agent_code, "meter": meter_code, "cap": cap_value, "eff": date(2026, 1, 1)},
        )


def later(hours: int) -> datetime:
    return T0 + timedelta(hours=hours)
