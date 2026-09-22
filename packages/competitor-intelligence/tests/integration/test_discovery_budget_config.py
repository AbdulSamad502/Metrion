"""ci_tenant_config's §6.12.1 discovery-budget columns and §6.11/D11 discovery_enabled
opt-out, read through repositories/ci_tenant_config_repo.py."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from competitor_intelligence.discovery.budget import DiscoveryBudget
from competitor_intelligence.repositories.ci_tenant_config_repo import (
    get_discovery_budget,
    get_discovery_enabled,
)
from competitor_intelligence.repositories.tenant_context import tenant_scope

import pytest

pytestmark = pytest.mark.usefixtures("_clean_ci_tables")


def test_defaults_when_no_config_row_exists(two_tenants) -> None:
    tenant_a, _ = two_tenants

    assert get_discovery_budget(tenant_a) == DiscoveryBudget()
    assert get_discovery_enabled(tenant_a) is True


def test_reads_overridden_values_from_the_row(two_tenants) -> None:
    tenant_a, _ = two_tenants
    with tenant_scope(tenant_a) as conn:
        conn.execute(
            text(
                """
                INSERT INTO ci_tenant_config (tenant_id, max_discovery_queries_per_run, discovery_enabled)
                VALUES (:tenant_id, 5, false)
                """
            ),
            {"tenant_id": str(tenant_a)},
        )

    budget = get_discovery_budget(tenant_a)
    assert budget.max_discovery_queries_per_run == 5
    assert get_discovery_enabled(tenant_a) is False
