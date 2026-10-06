"""P7f persistence on a real Postgres: a trend report is one generation + one report row, tenant-isolated and append-only."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.repositories.trend_repo import PostgresTrendStore
from slim_cmo.service.models import DuplicateArtefact
from slim_cmo.service.trends import TrendRecord
from slim_cmo.types import GenerationStatus as GS


def record(**kw):
    base = dict(
        niche_term_ids=(), sections_requested=("NICHE", "MARKET_NEWS"), sections={"NICHE": {"state": "COMPLETE", "findings": []}},
        interpretation={"label": "x", "items": []}, evidence={"data_gaps": ["gap"]}, outbound_queries=[{"query": "q"}],
        config_snapshot={"a": 1}, market_signal_run_ref=uuid.uuid4(),
    )
    base.update(kw)
    return TrendRecord(**base)


def save(store, tenant, key="k1", status=GS.COMPLETE, trend="default"):
    return store.save_report(
        tenant, uuid.uuid4(), request_key=key, status=status, failure_reason=None if status is GS.COMPLETE else "no citable finding",
        agent_run_id=None, summary={"findings": {"NICHE": 1}}, trend=record() if trend == "default" else trend,
    )


def test_round_trip_and_listing():
    t, store = uuid.uuid4(), PostgresTrendStore()
    gid = save(store, t)
    row = store.load_report(t, gid)
    assert row.status is GS.COMPLETE and row.report["evidence"] == {"data_gaps": ["gap"]} and row.report["outbound_queries"] == [{"query": "q"}]
    assert row.report["sections_requested"] == ["NICHE", "MARKET_NEWS"] and row.report["config_snapshot"] == {"a": 1}
    assert [r.generation_id for r in store.list_reports(t, 10)] == [gid]


def test_a_failed_report_has_no_report_row_and_does_not_block_a_retry_under_the_same_key():
    t, store = uuid.uuid4(), PostgresTrendStore()
    failed = save(store, t, status=GS.FAILED, trend=None)
    assert store.load_report(t, failed).report is None
    assert [a.status for a in store.find_artefacts(t, "k1")] == [GS.FAILED]
    ok = save(store, t)
    assert ok != failed and {a.status for a in store.find_artefacts(t, "k1")} == {GS.FAILED, GS.COMPLETE}


def test_a_second_complete_report_under_the_same_key_is_refused_and_rolls_back_both_rows():
    t, store = uuid.uuid4(), PostgresTrendStore()
    save(store, t)
    with pytest.raises(DuplicateArtefact):
        save(store, t)
    with tenant_scope(t) as conn:
        assert conn.execute(text("SELECT count(*) FROM cmo_trend_report")).scalar() == 1


def test_reports_are_invisible_across_tenants():
    a, b, store = uuid.uuid4(), uuid.uuid4(), PostgresTrendStore()
    gid = save(store, a)
    assert store.load_report(b, gid) is None and store.list_reports(b, 10) == [] and store.find_artefacts(b, "k1") == []
    with tenant_scope(b) as conn:
        assert conn.execute(text("SELECT count(*) FROM cmo_trend_report")).scalar() == 0


def test_the_application_role_cannot_rewrite_or_delete_a_delivered_report():
    t, store = uuid.uuid4(), PostgresTrendStore()
    save(store, t)
    for sql in ("UPDATE cmo_trend_report SET evidence = '{\"x\": 1}'::jsonb", "DELETE FROM cmo_trend_report", "UPDATE cmo_generation SET status = 'FAILED', failure_reason = 'x'"):
        with pytest.raises(DBAPIError, match="permission denied"):
            with tenant_scope(t) as conn:
                conn.execute(text(sql))


def test_the_database_refuses_an_empty_evidence_block():
    t, store = uuid.uuid4(), PostgresTrendStore()
    with pytest.raises(DBAPIError):
        save(store, t, trend=record(evidence={}))
