"""Security review (C8): the forms save through the existing expense path. A tenant must not be able to supersede (retire or link to) another tenant's stored
input by naming its id, a missing id and a foreign id are refused identically (no existence oracle), and a legitimate same-target supersede still works."""

from __future__ import annotations

import os
import uuid

import pytest
from calc_engine.repositories import manual_adjustment_repo
from sqlalchemy import text

from backend.services import cfo_actions

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]


def quote(tenant, user, name, **kw):
    return cfo_actions.enter_expense(tenant, target_type="SKU", target_ref="SKU-1", field="supplier.quote", value={"supplier_name": name, "unit_cost_paise": 100}, created_by=user, **kw)


def test_a_foreign_or_missing_supersedes_id_is_refused_identically_and_writes_nothing(two_tenants, app_user, migrate_engine):
    a, b = two_tenants
    theirs = quote(b, app_user, "Rival")
    messages = []
    for target in (theirs, uuid.uuid4()):  # another tenant's row, then one that does not exist
        with pytest.raises(ValueError) as exc:
            quote(a, app_user, "Mine", supersedes_id=target)
        messages.append(str(exc.value))
    assert messages[0] == messages[1]  # no way to tell whether a foreign id exists
    assert [r["id"] for r in manual_adjustment_repo.active_adjustments_for_target(b, target_type="SKU", target_ref="SKU-1", field="supplier.quote")] == [theirs]
    with migrate_engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM manual_adjustment WHERE tenant_id = :t"), {"t": str(a)}).scalar_one() == 0  # A wrote nothing


def test_a_supersede_must_name_the_same_target_and_field(two_tenants, app_user):
    a, _ = two_tenants
    first = quote(a, app_user, "One")
    with pytest.raises(ValueError):
        cfo_actions.enter_expense(a, target_type="SKU", target_ref="SKU-2", field="supplier.quote", value={"supplier_name": "Other", "unit_cost_paise": 1}, created_by=app_user, supersedes_id=first)


def test_a_legitimate_supersede_leaves_exactly_one_active_quote(two_tenants, app_user):
    a, _ = two_tenants
    first = quote(a, app_user, "One")
    second = quote(a, app_user, "Two", supersedes_id=first)
    assert [r["id"] for r in manual_adjustment_repo.active_adjustments_for_target(a, target_type="SKU", target_ref="SKU-1", field="supplier.quote")] == [second]
