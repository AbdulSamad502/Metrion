"""manual_adjustment append-only enforcement (§7.1) — UPDATE and DELETE must be denied at the
grant level for metrion_app, not merely absent from application code, since application code
being merely absent an update() function is not a guarantee against a future caller adding
one by mistake.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import DBAPIError

from calc_engine.repositories.manual_adjustment_repo import (
    active_adjustments_for_target,
    insert_adjustment,
)
from calc_engine.repositories.tenant_context import tenant_scope

pytestmark = pytest.mark.usefixtures("_clean_engine_tables")


def test_insert_adjustment_succeeds_and_is_readable(two_tenants):
    tenant_a, _ = two_tenants
    adjustment_id = insert_adjustment(
        tenant_a,
        target_type="SKU",
        target_ref="SKU-1",
        field="cogs_per_unit",
        value={"amount_paise": 8000, "effective_from": "2026-06-01"},
        created_by=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
        reason="initial cost entry",
    )
    rows = active_adjustments_for_target(tenant_a, target_type="SKU", target_ref="SKU-1", field="cogs_per_unit")
    assert len(rows) == 1
    assert rows[0]["id"] == adjustment_id
    assert rows[0]["value"]["amount_paise"] == 8000


def test_update_is_denied_at_the_grant_level(two_tenants):
    tenant_a, _ = two_tenants
    insert_adjustment(
        tenant_a,
        target_type="SKU",
        target_ref="SKU-1",
        field="cogs_per_unit",
        value=8000,
        created_by=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )
    with pytest.raises(DBAPIError, match="permission denied"):
        with tenant_scope(tenant_a) as conn:
            from sqlalchemy import text

            conn.execute(text("UPDATE manual_adjustment SET status = 'WITHDRAWN' WHERE target_ref = 'SKU-1'"))


def test_delete_is_denied_at_the_grant_level(two_tenants):
    tenant_a, _ = two_tenants
    insert_adjustment(
        tenant_a,
        target_type="SKU",
        target_ref="SKU-1",
        field="cogs_per_unit",
        value=8000,
        created_by=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )
    with pytest.raises(DBAPIError, match="permission denied"):
        with tenant_scope(tenant_a) as conn:
            from sqlalchemy import text

            conn.execute(text("DELETE FROM manual_adjustment WHERE target_ref = 'SKU-1'"))


def test_correction_is_a_new_row_with_supersedes_id_not_an_update(two_tenants):
    tenant_a, _ = two_tenants
    original_id = insert_adjustment(
        tenant_a,
        target_type="SKU",
        target_ref="SKU-1",
        field="cogs_per_unit",
        value=8000,
        created_by=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )
    corrected_id = insert_adjustment(
        tenant_a,
        target_type="SKU",
        target_ref="SKU-1",
        field="cogs_per_unit",
        value=8500,
        created_by=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
        supersedes_id=original_id,
    )
    # both rows still exist — nothing was overwritten — §7.1 "append-only, corrections chain"
    with tenant_scope(tenant_a) as conn:
        from sqlalchemy import text

        rows = conn.execute(text("SELECT id, supersedes_id FROM manual_adjustment ORDER BY created_at")).fetchall()
    assert len(rows) == 2
    rows_by_id = {str(r[0]): r[1] for r in rows}
    assert rows_by_id[str(original_id)] is None
    assert str(rows_by_id[str(corrected_id)]) == str(original_id)
