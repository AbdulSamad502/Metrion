"""Issue 22 (Metrion_24_Fixes): "Import viewer cannot show per-row rejection reasons because the live ingestion path does not persist them."

The table and the viewer's read path already existed (data-foundation.md §4.4); the live upload simply never wrote to it. Now the findings on every rejected row are stored
with the rule, severity, message and source row number, per tenant, and shown by `GET /cfo/imports/{id}`. A clean file stores none, and the viewer says so."""

from __future__ import annotations

import pytest

from tests.integration.test_cfo_imports import _CSV_HEADER, _csv, _register_owner, _upload, app_client, fake_clerk  # noqa: F401  (fixtures and helpers)


@pytest.fixture(autouse=True)
def _require_the_order_number(monkeypatch):
    """No live adapter can reject a row today: the upload path runs the validation with no required identifiers and the mapped columns carry no quantity, currency or tax
    head. To exercise a real rejection through the real pipeline, the order number is declared required (V-ID-001, an ERROR rule) for these tests only."""
    from data_foundation.ingestion import persist
    from data_foundation.ingestion.pipeline import run_ingestion

    monkeypatch.setattr(persist, "run_ingestion", lambda adapter, sample, raw: run_ingestion(adapter, sample, raw, required_fields=("order_ref",), enforce_quarantine_threshold=False))


def _csv_with_blank_order_numbers(good: int, blank_rows: int) -> bytes:
    rows = "".join(f"ORD-{i},ORD-{i}_1,DELIVERED,Delivered\r\n" for i in range(1, good + 1))
    rows += "".join(f",,DELIVERED,Delivered\r\n" for _ in range(blank_rows))
    return (_CSV_HEADER + rows).encode()


def test_rejected_rows_get_their_reasons_stored_and_shown_with_the_source_row(app_client, fake_clerk, two_tenants):
    headers = _register_owner(fake_clerk, two_tenants[0])
    uploaded = _upload(app_client, headers, _csv_with_blank_order_numbers(good=20, blank_rows=1))
    assert (uploaded["rowCountRead"], uploaded["rowCountAccepted"], uploaded["rowCountRejected"]) == (21, 20, 1)

    body = app_client.get(f"/api/v1/cfo/imports/{uploaded['reportFileId']}", headers=headers).json()
    rejected = body["rejected"]
    assert rejected["count"] == 1 and rejected["diagnosticsPersisted"] is True and rejected["findingsTotal"] >= 1
    errors = [f for f in rejected["findings"] if f["severity"] == "ERROR"]
    assert [f["ruleId"] for f in errors] == ["V-ID-001"] and "order_ref" in errors[0]["message"]  # the reason the row was rejected
    assert {f["sourceRowNumber"] for f in rejected["findings"]} <= {21, 22} and errors[0]["sourceRowNumber"] in (21, 22)  # the blank row is the last data row (1-based)
    assert all(f["message"] for f in rejected["findings"])
    assert body["counts"]["persisted"] == 20  # the rejected row is not stored as a line


def test_a_clean_file_stores_no_findings_and_the_viewer_says_so(app_client, fake_clerk, two_tenants):
    headers = _register_owner(fake_clerk, two_tenants[0])
    uploaded = _upload(app_client, headers, _csv(5))
    rejected = app_client.get(f"/api/v1/cfo/imports/{uploaded['reportFileId']}", headers=headers).json()["rejected"]
    assert rejected["count"] == 0 and rejected["diagnosticsPersisted"] is False and rejected["findings"] == []


def test_another_tenant_never_sees_the_findings(app_client, fake_clerk, two_tenants):
    a, b = two_tenants
    ha, hb = _register_owner(fake_clerk, a), _register_owner(fake_clerk, b)
    uploaded = _upload(app_client, ha, _csv_with_blank_order_numbers(good=20, blank_rows=1))
    assert app_client.get(f"/api/v1/cfo/imports/{uploaded['reportFileId']}", headers=hb).status_code == 404


# --- Issue 22 follow-up: the validation gap, and read-back on a connection the request never used --------------------------------------------------------------------


def _stored_findings(tenant_id, ingestion_run_id: str) -> list[tuple[str, str, int | None]]:
    import os

    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ["DATABASE_URL_APP"])
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant_id)})
            rows = conn.execute(
                text("SELECT rule_id, severity, source_row_number FROM validation_finding WHERE ingestion_run_id = :r ORDER BY source_row_number, rule_id"), {"r": ingestion_run_id}
            )
            return [(r[0], r[1], r[2]) for r in rows]
    finally:
        engine.dispose()


def test_the_stored_reasons_are_committed_and_visible_to_an_independent_connection_for_this_tenant_only(app_client, fake_clerk, two_tenants):
    a, b = two_tenants
    headers = _register_owner(fake_clerk, a)
    uploaded = _upload(app_client, headers, _csv_with_blank_order_numbers(good=20, blank_rows=1))
    stored = _stored_findings(a, uploaded["ingestionRunId"])
    assert ("V-ID-001", "ERROR") in {(r, s) for r, s, _ in stored} and all(n is not None for _, _, n in stored)
    assert _stored_findings(b, uploaded["ingestionRunId"]) == []  # tenant B cannot read tenant A's reasons


def test_valid_rows_alone_store_no_findings_and_every_row_is_accepted(app_client, fake_clerk, two_tenants):
    headers = _register_owner(fake_clerk, two_tenants[0])
    uploaded = _upload(app_client, headers, _csv(30))
    assert (uploaded["rowCountRead"], uploaded["rowCountAccepted"], uploaded["rowCountRejected"]) == (30, 30, 0)
    assert _stored_findings(two_tenants[0], uploaded["ingestionRunId"]) == []


def test_without_a_declared_required_identifier_a_blank_order_number_is_accepted_today(app_client, fake_clerk, two_tenants, monkeypatch):
    """The gap, pinned as it is: the live path declares no required identifiers for any adapter (and the spec lists none), so a row with a blank order number is
    ACCEPTED and stored. Which identifiers each adapter requires is a validation-policy decision the spec leaves open; this test records the present behaviour, it
    does not endorse it."""
    from data_foundation.ingestion import persist
    from data_foundation.ingestion.pipeline import run_ingestion

    monkeypatch.setattr(persist, "run_ingestion", run_ingestion)  # undo the autouse declaration: the real live-path call
    headers = _register_owner(fake_clerk, two_tenants[0])
    uploaded = _upload(app_client, headers, _csv_with_blank_order_numbers(good=20, blank_rows=1))
    assert (uploaded["rowCountAccepted"], uploaded["rowCountRejected"]) == (21, 0)
    assert _stored_findings(two_tenants[0], uploaded["ingestionRunId"]) == []
