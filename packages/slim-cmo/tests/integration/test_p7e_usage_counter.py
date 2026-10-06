"""P7e: the platform-wide daily provider-search counter against a real Postgres (migration 20261006_0003).

The counter is global, so these tests never assume it is empty: every ceiling is relative to the current total, and a
fixture restores today's rows to exactly what they were before the test (it never deletes anything it did not create)."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from slim_cmo.repositories.tenant_context import get_engine
from slim_cmo.repositories.usage_repo import PostgresSlotStore

TODAY_SQL = "(now() AT TIME ZONE 'Asia/Kolkata')::date"


@pytest.fixture
def counters(migrate_engine):
    def snapshot():
        with migrate_engine.begin() as conn:
            return {r.provider: r.searches for r in conn.execute(text(f"SELECT provider, searches FROM cmo_provider_usage WHERE usage_day = {TODAY_SQL}"))}

    before = snapshot()
    yield type("C", (), {"before": before, "now": staticmethod(snapshot)})
    with migrate_engine.begin() as conn:
        conn.execute(text(f"DELETE FROM cmo_provider_usage WHERE usage_day = {TODAY_SQL}"))
        for provider, n in before.items():
            conn.execute(text(f"INSERT INTO cmo_provider_usage (usage_day, provider, searches) VALUES ({TODAY_SQL}, :p, :n)"), {"p": provider, "n": n})


def total(c) -> int:
    return sum(c.before.values())


# ------------------------------------------------------------------------------------------ privileges
@pytest.mark.parametrize("sql", [
    "SELECT * FROM cmo_provider_usage",
    "INSERT INTO cmo_provider_usage (usage_day, provider, searches) VALUES (current_date, 'TAVILY', 1)",
    "UPDATE cmo_provider_usage SET searches = 0",
    "DELETE FROM cmo_provider_usage",
    "TRUNCATE cmo_provider_usage",
])
def test_the_application_role_has_no_privilege_on_the_counter_table(sql):
    with pytest.raises(DBAPIError, match="permission denied"):
        with get_engine().begin() as conn:
            conn.execute(text(sql))


def test_the_application_role_can_only_execute_the_two_functions(counters):
    store = PostgresSlotStore()
    assert store.take_slot("TAVILY", total(counters) + 1) is True
    assert isinstance(store.usage_today(), dict)


def test_the_functions_are_security_definer_with_a_pinned_search_path_and_no_public_execute(migrate_engine):
    with migrate_engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT proname, prosecdef, proconfig, proacl::text FROM pg_proc WHERE proname IN ('cmo_take_provider_slot', 'cmo_provider_usage_today')"
        )).all()
    assert {r.proname for r in rows} == {"cmo_take_provider_slot", "cmo_provider_usage_today"}
    for r in rows:
        assert r.prosecdef is True
        assert any("search_path=public, pg_temp" in c for c in (r.proconfig or []))
        entries = r.proacl.strip("{}").split(",")
        assert not any(e.startswith("=") for e in entries)  # an ACL entry with an empty grantee is PUBLIC: there must be none
        assert any(e.startswith("metrion_app=X/") for e in entries)  # the app role may execute


def test_the_counter_table_holds_no_tenant_or_seller_columns(migrate_engine):
    with migrate_engine.begin() as conn:
        cols = {r[0] for r in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'cmo_provider_usage'"))}
    assert cols == {"usage_day", "provider", "searches", "updated_at"}


# ------------------------------------------------------------------------------------------ semantics
def test_the_combined_ceiling_is_enforced_across_providers_with_separate_per_provider_counts(counters):
    store, ceiling = PostgresSlotStore(), total(counters) + 5
    results = [store.take_slot(p, ceiling) for p in ["TAVILY", "TAVILY", "YOUTUBE", "TAVILY", "YOUTUBE", "TAVILY", "YOUTUBE"]]
    assert results == [True] * 5 + [False] * 2
    now = counters.now()
    assert now.get("TAVILY", 0) - counters.before.get("TAVILY", 0) == 3 and now.get("YOUTUBE", 0) - counters.before.get("YOUTUBE", 0) == 2
    assert store.usage_today() == now


def test_a_refused_request_does_not_increment_anything(counters):
    store = PostgresSlotStore()
    ceiling = total(counters) + 1
    assert store.take_slot("TAVILY", ceiling) is True
    snap = counters.now()
    assert store.take_slot("YOUTUBE", ceiling) is False and store.take_slot("TAVILY", ceiling) is False
    assert counters.now() == snap


def test_concurrent_requests_never_exceed_the_ceiling(counters):
    store, ceiling, barrier = PostgresSlotStore(), total(counters) + 7, threading.Barrier(30)

    def go(i):
        barrier.wait()
        return store.take_slot("TAVILY" if i % 2 else "YOUTUBE", ceiling)

    with ThreadPoolExecutor(30) as pool:
        granted = list(pool.map(go, range(30)))
    assert granted.count(True) == 7 and granted.count(False) == 23
    assert sum(counters.now().values()) == ceiling


def test_other_days_do_not_count_and_the_day_is_derived_inside_the_function(counters, migrate_engine):
    with migrate_engine.begin() as conn:
        for d in (date.today() - timedelta(days=3), date.today() + timedelta(days=3)):
            conn.execute(text("INSERT INTO cmo_provider_usage (usage_day, provider, searches) VALUES (:d, 'TAVILY', 1000) ON CONFLICT DO NOTHING"), {"d": d})
    try:
        assert PostgresSlotStore().take_slot("YOUTUBE", total(counters) + 1) is True  # 1000s on other days are invisible
        with migrate_engine.begin() as conn:
            today = conn.execute(text(f"SELECT {TODAY_SQL}")).scalar_one()
        assert today in {date.today() - timedelta(days=1), date.today(), date.today() + timedelta(days=1)}  # Asia/Kolkata calendar day
    finally:
        with migrate_engine.begin() as conn:
            conn.execute(text("DELETE FROM cmo_provider_usage WHERE searches = 1000 AND usage_day <> " + TODAY_SQL))


def test_the_function_has_no_day_parameter_so_a_caller_cannot_choose_one(migrate_engine):
    with migrate_engine.begin() as conn:
        args = conn.execute(text("SELECT pg_get_function_arguments(oid) FROM pg_proc WHERE proname = 'cmo_take_provider_slot'")).scalar_one()
    assert args == "p_provider text, p_ceiling integer"


@pytest.mark.parametrize("provider,ceiling", [("BING", 5), ("tavily", 5), (None, 5), ("TAVILY", 0), ("TAVILY", -3), ("TAVILY", None)])
def test_invalid_arguments_are_rejected_and_nothing_is_counted(counters, provider, ceiling):
    with pytest.raises(DBAPIError):
        PostgresSlotStore().take_slot(provider, ceiling)  # type: ignore[arg-type]
    assert counters.now() == counters.before


def test_the_table_rejects_negative_or_unknown_rows_even_for_the_owner(migrate_engine):
    with pytest.raises(DBAPIError):
        with migrate_engine.begin() as conn:
            conn.execute(text("INSERT INTO cmo_provider_usage (usage_day, provider, searches) VALUES (current_date, 'TAVILY', -1)"))
    with pytest.raises(DBAPIError):
        with migrate_engine.begin() as conn:
            conn.execute(text("INSERT INTO cmo_provider_usage (usage_day, provider, searches) VALUES (current_date, 'BING', 1)"))
