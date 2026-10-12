"""`POST /api/v1/cfo/cash-reconciliation` as the Profit & Finance screen uses it: who may call it, what it refuses, what it persists, and how the figures it cannot
compute are reported. Real Postgres on the scratch database; only Clerk is faked. The settlement rows are controlled test rows inserted for a test tenant, never real
data. No model, e-mail, marketplace or other external call is involved: it is a deterministic read of persisted settlement rows plus a persisted engine result."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from backend.repositories import app_user_repo, membership_repo
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import row_counts
from tests.integration.test_cfo_cash_reconciliation import (  # noqa: F401  (fixtures and helpers)
    _body,
    _clean_tables,
    _insert_report_file_and_run,
    _insert_settlement_line,
    _register_owner,
    app_client,
    fake_clerk,
)

URL = "/api/v1/cfo/cash-reconciliation"


def _partner_without_the_cfo_key(fake_clerk, tenant) -> dict[str, str]:
    user = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(clerk_user_id=user, email=f"{user}@example.com", email_verified=True, auth_provider="GOOGLE", display_name="Partner")
    row = app_user_repo.get_by_clerk_user_id(user)
    membership_repo.upsert_partner(tenant, row["id"], role="PARTNER", status="ACTIVE")
    token = f"tok_{uuid.uuid4()}"
    fake_clerk.tokens[token] = (user, f"org_{tenant}")
    return {"Authorization": f"Bearer {token}"}


def test_it_needs_a_signed_in_member_with_the_cfo_key(app_client, fake_clerk, two_tenants):
    a, _ = two_tenants
    assert app_client.post(URL, json=_body()).status_code == 401
    assert app_client.post(URL, json=_body(), headers={"Authorization": "Bearer nope"}).status_code == 401
    assert app_client.post(URL, json=_body(), headers=_partner_without_the_cfo_key(fake_clerk, a)).status_code == 403


@pytest.mark.parametrize("name,change", [
    ("no marketplace", lambda b: b.pop("marketplace")),
    ("no period start", lambda b: b.pop("period_start")),
    ("no as-of date", lambda b: b.pop("as_of_date")),
    ("a date that is not a date", lambda b: b.update(period_end="31/01/2026")),
    ("a number for the marketplace", lambda b: b.update(marketplace=5)),
])
def test_an_invalid_request_is_refused_before_anything_is_read_or_saved(app_client, fake_clerk, two_tenants, name, change):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    body = _body()
    change(body)
    before = row_counts(a, "metric_result")
    resp = app_client.post(URL, json=body, headers=headers)
    assert resp.status_code == 422, (name, resp.text)
    assert row_counts(a, "metric_result") == before


def test_with_no_settlement_rows_the_screen_gets_an_honest_answer_never_a_zero_it_made_up(app_client, fake_clerk, two_tenants):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    body = app_client.post(URL, json=_body("MEESHO"), headers=headers).json()
    received = body["cashReceived"]
    # whatever the engine says for "no rows", the figure is either absent or explicitly available with a stored basis; it is never silently available-and-zero without one
    assert received["isAvailable"] is False or received["calculationBasis"]
    for key in ("cashExpected", "cashVariance", "tdsDeducted"):
        assert body[key]["isAvailable"] is False and body[key]["unavailableReason"], key
        assert body[key]["valuePaise"] is None, key


def test_expected_cash_variance_and_tds_stay_unavailable_with_the_backends_own_reason_when_the_inputs_are_absent(app_client, fake_clerk, two_tenants):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    run = _insert_report_file_and_run(a, marketplace="MEESHO")
    _insert_settlement_line(a, ingestion_run_id=run, marketplace="MEESHO")
    body = app_client.post(URL, json=_body(), headers=headers).json()
    assert body["cashReceived"]["isAvailable"] is True and body["cashReceived"]["valuePaise"] == 5000
    for key in ("cashExpected", "cashVariance", "tdsDeducted"):
        assert body[key]["isAvailable"] is False and body[key]["valuePaise"] is None
        assert isinstance(body[key]["unavailableReason"], str) and len(body[key]["unavailableReason"]) > 10, key  # a stated reason, shown to the seller verbatim
    assert body["cashExpected"]["unavailableReason"] != body["tdsDeducted"]["unavailableReason"]  # each says what it is missing, not one generic line


def test_one_tenants_settlements_never_reach_anothers_figure(app_client, fake_clerk, two_tenants):
    a, b = two_tenants
    ha, hb = _register_owner(fake_clerk, a), _register_owner(fake_clerk, b)
    _insert_settlement_line(a, ingestion_run_id=_insert_report_file_and_run(a, marketplace="MEESHO"), marketplace="MEESHO")
    only_a = app_client.post(URL, json=_body(), headers=ha).json()["cashReceived"]
    for_b = app_client.post(URL, json=_body(), headers=hb).json()["cashReceived"]
    assert only_a["valuePaise"] == 5000
    assert for_b["valuePaise"] != 5000  # B has no rows: A's money is not B's
    _insert_settlement_line(b, ingestion_run_id=_insert_report_file_and_run(b, marketplace="MEESHO"), marketplace="MEESHO")
    assert app_client.post(URL, json=_body(), headers=ha).json()["cashReceived"]["valuePaise"] == 5000  # and B's row did not change A's total


def test_asking_again_gives_the_same_figure_and_does_not_double_count(app_client, fake_clerk, two_tenants):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    _insert_settlement_line(a, ingestion_run_id=_insert_report_file_and_run(a, marketplace="MEESHO"), marketplace="MEESHO")
    first = app_client.post(URL, json=_body(), headers=headers).json()
    second = app_client.post(URL, json=_body(), headers=headers).json()
    assert first["cashReceived"]["valuePaise"] == second["cashReceived"]["valuePaise"] == 5000  # a retry or a double click reads the same rows
    ref = first["cashReceived"]["engineResultRef"]
    with tenant_scope(a) as conn:
        row = conn.execute(text("SELECT metric_code, value_paise FROM metric_result WHERE id = CAST(:id AS uuid)"), {"id": ref}).one_or_none()
    assert row is not None and row[1] == 5000  # the figure the screen shows has a stored record behind its engineResultRef
