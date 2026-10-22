"""The seller's claim lifecycle for a leak finding, real Postgres (docs/specs/cfo-phase3-scope.md AC-D2…D5)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from calc_engine.leak_claims import AMAZON_WITHHELD, ClaimRuleError, claim_draft_text, effective_state, validate_transition
from calc_engine.repositories import leak_claim_repo as claims
from calc_engine.repositories import read_model_version_repo as rmv
from cfo.repositories import leak_finding_repo

from tests.integration.test_cfo_expense_ledger import _register_owner, app_client, fake_clerk, _seed_zero_cap  # noqa: F401
from tests.integration.test_cfo_query_planner import _file_and_run

USER = uuid.uuid4()
NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


def scope(t: uuid.UUID):
    from cfo.repositories.tenant_context import tenant_scope

    return tenant_scope(t)


def finding(t: uuid.UUID, *, marketplace: str = "MEESHO", status: str = "NEW", order: str = "ORD-1", line: str = "ORD-1_1", category: str = "DUPLICATE_DEDUCTION") -> uuid.UUID:
    from data_foundation.repositories.settlement_line_repo import insert_settlement_line

    run = _file_and_run(t)
    sid = insert_settlement_line(t, ingestion_run_id=run, marketplace=marketplace,
                                 canonical_fields={"order_ref": order, "line_ref": line, "settlement_id": "S", "currency": "INR", "settlement_date": date(2026, 10, 1),
                                                   "gross_settlement_amount": -5_000, "document_type": None},
                                 source_row_number=1, source_row_json={}, confidence="PROVISIONAL")
    rid, eid = uuid.uuid4(), uuid.uuid4()
    with scope(t) as conn:
        conn.execute(text("INSERT INTO reconciliation_run (id, tenant_id, marketplace, period_start, period_end, as_of_date, tolerance_config_version, formula_version, status, started_at, join_key_validated) "
                          "VALUES (:r, :t, :m, '2026-10-01', '2026-10-31', '2026-10-20', 1, 'v1', 'COMPLETE', now(), true)"), {"r": str(rid), "t": str(t), "m": marketplace})
        conn.execute(text("INSERT INTO reconciliation_exception (id, tenant_id, reconciliation_run_id, exception_type, settlement_line_id, marketplace, amount_paise, confidence, formula_version, computed_at) "
                          "VALUES (:e, :t, :r, 'DUPLICATE_SETTLEMENT', :s, :m, 5000, 'PROVISIONAL', 'v1', now())"), {"e": str(eid), "t": str(t), "r": str(rid), "s": str(sid), "m": marketplace})
    return leak_finding_repo.insert(t, reconciliation_exception_id=eid, engine_result_ref=uuid.uuid4(), marketplace=marketplace, leak_category=category, severity="HIGH",
                                    amount_paise=5_000, affected_line_count=1, first_observed_at=NOW, age_days=3, status=status, confidence="PROVISIONAL", formula_version="v1")


# ------------------------------------------------------------------------------------------------ pure rules
@pytest.mark.parametrize("cur,to,ok", [
    ("NEW", "ACKNOWLEDGED", True), ("ACKNOWLEDGED", "CLAIM_DRAFTED", True), ("CLAIM_DRAFTED", "SELLER_REPORTED_RAISED", True), ("SELLER_REPORTED_RAISED", "SELLER_REPORTED_RESOLVED", True),
    ("NEW", "CLAIM_DRAFTED", False), ("NEW", "SELLER_REPORTED_RESOLVED", False), ("ACKNOWLEDGED", "SELLER_REPORTED_RAISED", False), ("CLAIM_DRAFTED", "ACKNOWLEDGED", False),
    ("SELLER_REPORTED_RAISED", "CLAIM_DRAFTED", False), ("NEW", "DISMISSED", True), ("CLAIM_DRAFTED", "DISMISSED", True), ("SELLER_REPORTED_RAISED", "DISMISSED", True),
    ("DISMISSED", "ACKNOWLEDGED", False), ("SELLER_REPORTED_RESOLVED", "DISMISSED", False), ("NEW", "NEW", False), ("NEW", "WHATEVER", False),
])
def test_the_lifecycle_is_forward_only_and_cannot_skip_the_sellers_own_steps(cur: str, to: str, ok: bool) -> None:
    if ok:
        validate_transition("MEESHO", cur, to)
    else:
        with pytest.raises(ClaimRuleError):
            validate_transition("MEESHO", cur, to)


def test_legacy_finding_statuses_map_conservatively() -> None:
    assert [effective_state(s, None) for s in ("NEW", "ACKNOWLEDGED", "ACTIONED", "DISMISSED", "???")] == ["NEW", "ACKNOWLEDGED", "ACKNOWLEDGED", "DISMISSED", "NEW"]
    assert effective_state("NEW", "CLAIM_DRAFTED") == "CLAIM_DRAFTED"


def test_amazon_is_withheld_for_every_step_and_for_the_draft() -> None:
    with pytest.raises(ClaimRuleError, match="match key"):
        validate_transition("AMAZON", "NEW", "ACKNOWLEDGED")
    with pytest.raises(ClaimRuleError, match="match key"):
        claim_draft_text("AMAZON", "DUPLICATE_DEDUCTION", ["A1"], "f")
    assert "withheld" in AMAZON_WITHHELD


def test_the_draft_contains_identifiers_only_and_counts_what_it_does_not_list() -> None:
    t = claim_draft_text("MEESHO", "DUPLICATE_DEDUCTION", [f"O{i:03d}" for i in range(60)] + ["O001", ""], "FIND-1")
    assert "Discrepancy identified: duplicate deduction" in t and "- O000" in t and "- O049" in t and "- O050" not in t and "and 10 more" in t and "FIND-1" in t
    assert not any(ch in t for ch in "₹$") and "recover" not in t.lower() and "refund" not in t.lower()
    with pytest.raises(ClaimRuleError):
        claim_draft_text("MEESHO", "X", [], "f")


# ------------------------------------------------------------------------------------------------ database
def test_a_full_lifecycle_is_recorded_append_only_with_history_and_a_version_bump() -> None:
    t = uuid.uuid4()
    f = finding(t)
    v0 = rmv.get(t)
    assert claims.current_view(t, f).state == "NEW"
    for step in ("ACKNOWLEDGED", "CLAIM_DRAFTED", "SELLER_REPORTED_RAISED", "SELLER_REPORTED_RESOLVED"):
        view = claims.transition(t, f, step, USER, note=f"to {step}")
    assert view.state == "SELLER_REPORTED_RESOLVED" and [(a, b) for a, b, _, _ in view.history] == [
        ("NEW", "ACKNOWLEDGED"), ("ACKNOWLEDGED", "CLAIM_DRAFTED"), ("CLAIM_DRAFTED", "SELLER_REPORTED_RAISED"), ("SELLER_REPORTED_RAISED", "SELLER_REPORTED_RESOLVED")]
    assert rmv.get(t) == v0 + 4
    with pytest.raises(ClaimRuleError, match="already"):
        claims.transition(t, f, "DISMISSED", USER)
    for sql in ("UPDATE leak_claim_event SET to_state = 'DISMISSED'", "DELETE FROM leak_claim_event"):
        with pytest.raises(Exception, match="permission denied"):
            with scope(t) as conn:
                conn.execute(text(sql))


def test_skipping_a_step_is_refused_and_writes_nothing() -> None:
    t = uuid.uuid4()
    f = finding(t)
    v0 = rmv.get(t)
    with pytest.raises(ClaimRuleError, match="next step"):
        claims.transition(t, f, "SELLER_REPORTED_RESOLVED", USER)
    assert claims.current_view(t, f).history == () and rmv.get(t) == v0


def test_the_first_draft_moves_acknowledged_to_drafted_and_lists_the_order_ids() -> None:
    t = uuid.uuid4()
    f = finding(t, order="ORD-77", line="ORD-77_1")
    with pytest.raises(ClaimRuleError, match="acknowledge"):
        claims.draft(t, f, USER)
    claims.transition(t, f, "ACKNOWLEDGED", USER)
    text_, view = claims.draft(t, f, USER)
    assert view.state == "CLAIM_DRAFTED" and "- ORD-77" in text_ and "- ORD-77_1" in text_ and "5000" not in text_ and "50.00" not in text_
    again, view2 = claims.draft(t, f, USER)  # drafting again returns the text and does not add an event
    assert again == text_ and len(view2.history) == 2


def test_legacy_status_acknowledged_findings_can_be_drafted_directly() -> None:
    t = uuid.uuid4()
    f = finding(t, status="ACKNOWLEDGED")
    assert claims.current_view(t, f).state == "ACKNOWLEDGED"
    assert claims.draft(t, f, USER)[1].state == "CLAIM_DRAFTED"


def test_amazon_findings_are_withheld_in_storage_too() -> None:
    t = uuid.uuid4()
    f = finding(t, marketplace="AMAZON")
    with pytest.raises(ClaimRuleError, match="match key"):
        claims.transition(t, f, "ACKNOWLEDGED", USER)
    assert claims.current_view(t, f).history == ()


def test_findings_are_tenant_isolated() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    f = finding(a)
    with pytest.raises(ClaimRuleError, match="does not exist"):
        claims.transition(b, f, "ACKNOWLEDGED", USER)
    with pytest.raises(ClaimRuleError, match="does not exist"):
        claims.current_view(b, f)
    assert claims.order_refs(a, f) == ["ORD-1", "ORD-1_1"]


# ------------------------------------------------------------------------------------------------ routes
def test_routes_walk_the_lifecycle_with_gates(app_client, fake_clerk, two_tenants):
    from backend.auth.permissions import AGENT_CFO
    from tests.integration.test_cfo_pnl import _register_partner_with_permissions

    tenant_a, _ = two_tenants
    h = _register_owner(fake_clerk, tenant_a)
    f = finding(tenant_a)
    base = f"/api/v1/cfo/leak-findings/{f}/claim"
    assert app_client.get(base, headers=h).json()["state"] == "NEW"
    assert app_client.post(f"{base}/draft", headers=h).status_code == 400
    assert app_client.post(f"{base}/step", json={"to": "acknowledged"}, headers=h).json()["state"] == "ACKNOWLEDGED"
    d = app_client.post(f"{base}/draft", headers=h)
    assert d.status_code == 200 and d.json()["state"] == "CLAIM_DRAFTED" and "ORD-1" in d.json()["text"]
    assert app_client.post(f"{base}/step", json={"to": "SELLER_REPORTED_RESOLVED"}, headers=h).status_code == 400
    assert app_client.post(f"{base}/step", json={"to": "SELLER_REPORTED_RAISED", "extra": 1}, headers=h).status_code == 422
    assert app_client.post(f"{base}/step", json={"to": "SELLER_REPORTED_RAISED", "note": "ticket 123"}, headers=h).json()["history"][-1]["note"] == "ticket 123"
    partner = _register_partner_with_permissions(fake_clerk, tenant_a, permissions={AGENT_CFO: True})
    assert app_client.get(base, headers=partner).status_code == 200
    assert app_client.post(f"{base}/step", json={"to": "DISMISSED"}, headers=partner).status_code == 403
    assert app_client.post(f"{base}/draft", headers=partner).status_code == 403
    assert app_client.get(f"/api/v1/cfo/leak-findings/{uuid.uuid4()}/claim", headers=h).status_code == 400


def test_capped_entitlement_denies_402_on_claims(app_client, fake_clerk, two_tenants, migrate_engine):
    tenant_a, _ = two_tenants
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.leak_claims")
    h = _register_owner(fake_clerk, tenant_a)
    assert app_client.get(f"/api/v1/cfo/leak-findings/{uuid.uuid4()}/claim", headers=h).status_code == 402
