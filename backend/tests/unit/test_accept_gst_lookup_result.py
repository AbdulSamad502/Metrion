"""G4 — `accept_gst_lookup_result` (deterministic-engine.md §7.2.1 `gst_rate_override` /
§8.4's updated L2 rule): the seller-acceptance act that turns one specific, already-persisted
`gst_lookup_result` row into a real `gst_rate_override` manual_adjustment.

Pure unit tests — `gst_lookup_repo.get_by_id` and `insert_adjustment` are monkeypatched to
fakes, never touching a real database, mirroring `test_entitlement.py`'s own
monkeypatch-the-repository-function discipline. Covers:

1. Happy path: a real stored lookup row -> a real `insert_adjustment` call with the correct
   `field`/`target_type`/`target_ref`/`value`/`created_by`.
2. Rejection when `gst_lookup_result_id` does not exist for this tenant (`get_by_id` -> `None`).
3. Rejection when the row exists but has no `likely_rate_pct` (a `GstLookupNoMatch`-shaped or
   empty result somehow persisted).
4. The accepted `rate_pct`/`hsn`/`category` are read from the STORED row, never from any
   client-supplied value on the request — proven by supplying request-level `rate_pct`/`hsn`/
   `category` that deliberately DIFFER from the stored row's real values and asserting the
   created manual_adjustment uses the stored values.
5. Supersession: when an ACTIVE `gst_rate_override` already exists for the SKU,
   `active_adjustments_for_target` is consulted and its id becomes the new row's
   `supersedes_id` automatically.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from backend.services import cfo_actions
from backend.services.cfo_actions import AcceptGstLookupRequest, accept_gst_lookup_result


@dataclass
class _CapturedInsert:
    tenant_id: uuid.UUID
    kwargs: dict[str, object]


def _install_fake_insert_adjustment(monkeypatch, *, returns: uuid.UUID | None = None) -> list[_CapturedInsert]:
    captured: list[_CapturedInsert] = []
    new_id = returns or uuid.uuid4()

    def fake_insert_adjustment(tenant_id: uuid.UUID, **kwargs: object) -> uuid.UUID:
        captured.append(_CapturedInsert(tenant_id=tenant_id, kwargs=kwargs))
        return new_id

    monkeypatch.setattr(cfo_actions, "insert_adjustment", fake_insert_adjustment)
    return captured


def _install_fake_get_by_id(monkeypatch, row_by_id: dict[uuid.UUID, dict[str, object] | None]) -> None:
    def fake_get_by_id(tenant_id: uuid.UUID, result_id: uuid.UUID) -> dict[str, object] | None:
        return row_by_id.get(result_id)

    monkeypatch.setattr(cfo_actions.gst_lookup_repo, "get_by_id", fake_get_by_id)


def _install_fake_active_adjustments_for_target(monkeypatch, rows: list[dict[str, object]]) -> None:
    def fake_active_adjustments_for_target(
        tenant_id: uuid.UUID, *, target_type: str, target_ref: str, field: str
    ) -> list[dict[str, object]]:
        return rows

    monkeypatch.setattr(
        cfo_actions.manual_adjustment_repo, "active_adjustments_for_target", fake_active_adjustments_for_target
    )


def test_accept_gst_lookup_result_happy_path_creates_correct_manual_adjustment(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    lookup_id = uuid.uuid4()
    accepted_by = uuid.uuid4()
    stored_row = {
        "id": lookup_id,
        "tenant_id": tenant_id,
        "sku": None,
        "likely_rate_pct": Decimal("18.0000"),
        "likely_hsn": "8517",
        "likely_category": "mobile phones",
        "status": "PROVISIONAL",
    }
    _install_fake_get_by_id(monkeypatch, {lookup_id: stored_row})
    _install_fake_active_adjustments_for_target(monkeypatch, [])
    captured = _install_fake_insert_adjustment(monkeypatch)

    request = AcceptGstLookupRequest(
        gst_lookup_result_id=lookup_id,
        sku="SKU-1",
        accepted_by=accepted_by,
        accepted_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
    )
    outcome = accept_gst_lookup_result(tenant_id, request)

    assert outcome.rejected_reason is None
    assert outcome.manual_adjustment_id is not None
    assert len(captured) == 1
    insert = captured[0]
    assert insert.tenant_id == tenant_id
    assert insert.kwargs["target_type"] == "SKU"
    assert insert.kwargs["target_ref"] == "SKU-1"
    assert insert.kwargs["field"] == "gst_rate_override"
    assert insert.kwargs["created_by"] == accepted_by
    assert insert.kwargs["supersedes_id"] is None
    value = insert.kwargs["value"]
    assert value["rate_pct"] == "18.0000"
    assert value["hsn"] == "8517"
    assert value["category"] == "mobile phones"
    assert value["gst_lookup_result_id"] == str(lookup_id)
    assert value["effective_from"] == date(2026, 9, 26).isoformat()


def test_accept_gst_lookup_result_rejects_nonexistent_row(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    missing_id = uuid.uuid4()
    _install_fake_get_by_id(monkeypatch, {})
    captured = _install_fake_insert_adjustment(monkeypatch)

    request = AcceptGstLookupRequest(gst_lookup_result_id=missing_id, sku="SKU-1", accepted_by=uuid.uuid4())
    outcome = accept_gst_lookup_result(tenant_id, request)

    assert outcome.manual_adjustment_id is None
    assert outcome.rejected_reason is not None
    assert str(missing_id) in outcome.rejected_reason
    assert captured == []  # never inserted anything


def test_accept_gst_lookup_result_rejects_row_with_no_likely_rate_pct(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    lookup_id = uuid.uuid4()
    stored_row = {
        "id": lookup_id,
        "tenant_id": tenant_id,
        "sku": None,
        "likely_rate_pct": None,
        "likely_hsn": None,
        "likely_category": None,
        "status": "PROVISIONAL",
    }
    _install_fake_get_by_id(monkeypatch, {lookup_id: stored_row})
    captured = _install_fake_insert_adjustment(monkeypatch)

    request = AcceptGstLookupRequest(gst_lookup_result_id=lookup_id, sku="SKU-1", accepted_by=uuid.uuid4())
    outcome = accept_gst_lookup_result(tenant_id, request)

    assert outcome.manual_adjustment_id is None
    assert outcome.rejected_reason is not None
    assert "likely_rate_pct" in outcome.rejected_reason
    assert captured == []


def test_accept_gst_lookup_result_ignores_client_supplied_rate_hsn_category(monkeypatch) -> None:
    """The accepted values must come from the STORED row, never from the request body — this
    test deliberately supplies WRONG rate/hsn/category on the request and asserts the created
    manual_adjustment still carries the stored row's real values."""
    tenant_id = uuid.uuid4()
    lookup_id = uuid.uuid4()
    stored_row = {
        "id": lookup_id,
        "tenant_id": tenant_id,
        "sku": None,
        "likely_rate_pct": Decimal("18.0000"),
        "likely_hsn": "8517",
        "likely_category": "mobile phones",
        "status": "PROVISIONAL",
    }
    _install_fake_get_by_id(monkeypatch, {lookup_id: stored_row})
    _install_fake_active_adjustments_for_target(monkeypatch, [])
    captured = _install_fake_insert_adjustment(monkeypatch)

    request = AcceptGstLookupRequest(
        gst_lookup_result_id=lookup_id,
        sku="SKU-1",
        accepted_by=uuid.uuid4(),
        rate_pct="0.0100",  # deliberately WRONG — must be ignored
        hsn="0000",
        category="definitely-not-the-real-category",
    )
    outcome = accept_gst_lookup_result(tenant_id, request)

    assert outcome.manual_adjustment_id is not None
    value = captured[0].kwargs["value"]
    assert value["rate_pct"] == "18.0000"
    assert value["hsn"] == "8517"
    assert value["category"] == "mobile phones"


def test_accept_gst_lookup_result_supersedes_existing_active_override(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    lookup_id = uuid.uuid4()
    existing_override_id = uuid.uuid4()
    stored_row = {
        "id": lookup_id,
        "tenant_id": tenant_id,
        "sku": None,
        "likely_rate_pct": Decimal("12.0000"),
        "likely_hsn": "6109",
        "likely_category": "t-shirts",
        "status": "PROVISIONAL",
    }
    _install_fake_get_by_id(monkeypatch, {lookup_id: stored_row})
    _install_fake_active_adjustments_for_target(
        monkeypatch, [{"id": existing_override_id, "field": "gst_rate_override"}]
    )
    captured = _install_fake_insert_adjustment(monkeypatch)

    request = AcceptGstLookupRequest(gst_lookup_result_id=lookup_id, sku="SKU-1", accepted_by=uuid.uuid4())
    outcome = accept_gst_lookup_result(tenant_id, request)

    assert outcome.manual_adjustment_id is not None
    assert captured[0].kwargs["supersedes_id"] == existing_override_id
