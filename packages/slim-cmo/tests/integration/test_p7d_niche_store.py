"""P7d persistence against a real Postgres: the catalog read returns titles only and only the caller's, niche changes are
atomic and serialised per tenant, and RLS isolates terms (skipped automatically without DATABASE_URL / DATABASE_URL_APP)."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from slim_cmo.repositories.niche_repo import PostgresNicheStore
from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.service.models import Actor
from slim_cmo.service.niche import Decision, DecisionKind, NicheService, Plan, TermInsert, TooManyConfirmedTerms
from slim_cmo.types import NicheTermOrigin as O
from slim_cmo.types import NicheTermStatus as S



def service(clock=lambda: datetime(2026, 10, 4, tzinfo=UTC)):
    return NicheService(PostgresNicheStore(), clock=clock)


def put_config(migrate_engine, tenant, values):
    import json

    with migrate_engine.begin() as conn:
        for k, v in values.items():
            conn.execute(text("INSERT INTO cmo_platform_config (tenant_id, key, value, effective_from) VALUES (:t, :k, CAST(:v AS jsonb), '2026-01-01')"),
                         {"t": str(tenant), "k": k, "v": json.dumps(v)})


def put_sales_lines(tenant, titles, extra_columns=True):
    run, file_ = uuid.uuid4(), uuid.uuid4()
    with tenant_scope(tenant) as conn:
        conn.execute(text("INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at) "
                          "VALUES (:id, :t, 'MEESHO', 'TAX', :sha, 'a.csv', 1, 's3://x', :u, now())"),
                     {"id": file_, "t": tenant, "sha": uuid.uuid4().hex + uuid.uuid4().hex, "u": uuid.uuid4()})
        conn.execute(text("INSERT INTO ingestion_run (id, tenant_id, report_file_id, adapter_id, adapter_version, status) VALUES (:id, :t, :f, 'm.v1', 'v1', 'PENDING')"),
                     {"id": run, "t": tenant, "f": file_})
        for i, t in enumerate(titles, start=1):
            conn.execute(text("INSERT INTO sales_line (tenant_id, ingestion_run_id, marketplace, item_title, order_ref, quantity, gross_item_amount, source_row_number, source_row_json, confidence) "
                              "VALUES (:t, :r, 'MEESHO', :title, 'ORDER-SECRET', 7, 99900, :n, '{}'::jsonb, 'PROVISIONAL')"),
                         {"t": tenant, "r": run, "title": t, "n": i})


# ------------------------------------------------------------------------------------------- the catalog read
def test_catalog_read_returns_distinct_titles_only_most_frequent_first_and_bounded(migrate_engine):
    tenant = uuid.uuid4()
    put_sales_lines(tenant, ["Steel Bottle"] * 3 + ["Yoga Mat"] * 2 + ["Lunch Box"] + [None, "", "   "])
    store = PostgresNicheStore()
    assert store.read_catalog_titles(tenant, 10) == ["Steel Bottle", "Yoga Mat", "Lunch Box"]
    assert store.read_catalog_titles(tenant, 2) == ["Steel Bottle", "Yoga Mat"]
    assert all(isinstance(t, str) for t in store.read_catalog_titles(tenant, 10))  # strings only: no amount/qty/order columns


def test_catalog_read_never_returns_another_tenants_titles(migrate_engine):
    a, b = uuid.uuid4(), uuid.uuid4()
    put_sales_lines(a, ["Alpha Product"])
    put_sales_lines(b, ["Beta Product"])
    store = PostgresNicheStore()
    assert store.read_catalog_titles(a, 10) == ["Alpha Product"] and store.read_catalog_titles(b, 10) == ["Beta Product"]


def test_the_catalog_select_list_contains_only_the_title_column():
    from slim_cmo.repositories import niche_repo

    sql = str(niche_repo._TITLES).lower()
    select_list = sql.split("from")[0]
    assert "item_title" in select_list
    for forbidden in ("amount", "quantity", "order_ref", "invoice", "source_row_json", "customer", "payment", "total"):
        assert forbidden not in select_list


# ------------------------------------------------------------------------------------------- terms: RLS + checks
def test_terms_are_isolated_per_tenant_by_rls_and_by_the_service(migrate_engine):
    a, b = uuid.uuid4(), uuid.uuid4()
    put_config(migrate_engine, a, {"max_confirmed_niche_terms": 5, "max_term_chars": 40, "catalog_titles_read_cap": 50})
    put_config(migrate_engine, b, {"max_confirmed_niche_terms": 5, "max_term_chars": 40, "catalog_titles_read_cap": 50})
    service().confirm(Actor(a, uuid.uuid4()), [], ["only for a"])
    assert [t.term for t in service().list_terms(Actor(a, uuid.uuid4()))] == ["only for a"]
    assert service().list_terms(Actor(b, uuid.uuid4())) == ()
    assert service().confirmed_terms(Actor(b, uuid.uuid4())) == ()
    with tenant_scope(b) as conn:  # even a raw, unfiltered query under B's context sees nothing of A's
        assert conn.execute(text("SELECT count(*) FROM cmo_niche_term")).scalar() == 0


def test_a_confirmed_term_row_always_carries_its_confirmer_and_time(migrate_engine):
    t = uuid.uuid4()
    put_config(migrate_engine, t, {"max_confirmed_niche_terms": 5, "max_term_chars": 40, "catalog_titles_read_cap": 50})
    user = uuid.uuid4()
    service().confirm(Actor(t, user), [], ["tracked term"])
    with tenant_scope(t) as conn:
        row = conn.execute(text("SELECT status, confirmed_by, confirmed_at FROM cmo_niche_term")).one()
    assert row.status == "CONFIRMED" and row.confirmed_by == user and row.confirmed_at is not None


def test_unconfirming_clears_the_confirmer_so_the_database_check_holds(migrate_engine):
    t = uuid.uuid4()
    put_config(migrate_engine, t, {"max_confirmed_niche_terms": 5, "max_term_chars": 40, "catalog_titles_read_cap": 50})
    actor = Actor(t, uuid.uuid4())
    out = service().confirm(actor, [], ["flip term"])
    service().confirm(actor, [Decision(DecisionKind.REJECT, out.confirmed[0].id)])
    with tenant_scope(t) as conn:
        row = conn.execute(text("SELECT status, confirmed_by, confirmed_at FROM cmo_niche_term")).one()
    assert (row.status, row.confirmed_by, row.confirmed_at) == ("REJECTED", None, None)


# ------------------------------------------------------------------------------------------- atomicity / serialisation
def test_a_failing_plan_rolls_the_whole_transaction_back(migrate_engine):
    t = uuid.uuid4()
    store = PostgresNicheStore()

    def plan(existing):
        raise RuntimeError("boom")

    store.apply_plan(t, uuid.uuid4(), lambda existing: Plan(inserts=(TermInsert("kept term", O.SELLER_STATED, None, S.SUGGESTED),)))
    with pytest.raises(RuntimeError):
        store.apply_plan(t, uuid.uuid4(), plan)
    assert [x.term for x in store.list_terms(t)] == ["kept term"]

    def two_rows_second_violates(existing):
        return Plan(inserts=(TermInsert("fresh term", O.SELLER_STATED, None, S.SUGGESTED), TermInsert("kept term", O.SELLER_STATED, None, S.SUGGESTED)))

    with pytest.raises(IntegrityError):  # duplicate (tenant_id, term): the unique constraint is the backstop
        store.apply_plan(t, uuid.uuid4(), two_rows_second_violates)
    assert [x.term for x in store.list_terms(t)] == ["kept term"]  # "fresh term" was rolled back with it


def test_concurrent_confirmations_are_serialised_and_never_exceed_the_cap(migrate_engine):
    t = uuid.uuid4()
    put_config(migrate_engine, t, {"max_confirmed_niche_terms": 3, "max_term_chars": 40, "catalog_titles_read_cap": 50})
    actor = Actor(t, uuid.uuid4())
    barrier = threading.Barrier(10)

    def go(i):
        barrier.wait()
        try:
            service().confirm(actor, [], [f"concurrent term {chr(97 + i)}"])
            return "ok"
        except TooManyConfirmedTerms:
            return "cap"

    with ThreadPoolExecutor(10) as pool:
        results = list(pool.map(go, range(10)))
    assert results.count("ok") == 3 and results.count("cap") == 7
    assert len(service().confirmed_terms(actor)) == 3


def test_suggest_from_real_titles_end_to_end_then_confirm_and_only_confirmed_are_egress_eligible(migrate_engine):
    t = uuid.uuid4()
    put_config(migrate_engine, t, {"max_confirmed_niche_terms": 6, "max_term_chars": 40, "catalog_titles_read_cap": 100})
    put_sales_lines(t, ["Steel Water Bottle 1 Litre", "Steel Water Bottle Gym", "Copper Water Bottle", "Call 9876543210 Steel Bottle", "Yoga Mat Anti Skid"])
    actor = Actor(t, uuid.uuid4())
    out = service().suggest(actor)
    assert out.status == "OK" and out.suggestions and out.confirmed == ()
    assert not any("9876543210" in s.term for s in out.suggestions)
    assert service().confirmed_terms(actor) == ()  # nothing is egress-eligible until the seller confirms
    wb = next(s for s in out.suggestions if s.term == "water bottle")
    service().confirm(actor, [Decision(DecisionKind.CONFIRM, wb.id)])
    assert service().confirmed_terms(actor) == ("water bottle",)
    with tenant_scope(t) as conn:
        notes = [r[0] for r in conn.execute(text("SELECT origin_note FROM cmo_niche_term WHERE origin_note IS NOT NULL"))]
    assert notes and not any("Steel Water Bottle" in n or "9876543210" in n for n in notes)  # counts only, never raw titles
