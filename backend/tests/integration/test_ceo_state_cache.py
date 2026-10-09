"""L7 Business State cache (spec 6.26): keyed (tenant, entry, data_version), authorization before any cache read, tenant-namespaced, invalidated by any
write to the entry's source tables, off unless configured."""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from backend.auth.permissions import AGENT_CEO, AGENT_CFO
from backend.ceo import business_state as bs
from backend.ceo import state_cache
from backend.ceo.contract import EntryStatus, Fact
from tests.integration.ceo_support import ALL_AGENTS, ctx_for, partner_ctx
from tests.integration.test_ceo_state_specialists import NOW, _scope, seed  # noqa: F401  (fixture + helper)

pytestmark = [
    pytest.mark.usefixtures("two_tenants"),
    pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres"),
]


@pytest.fixture(autouse=True)
def cache_on(monkeypatch):
    monkeypatch.setenv("CEO_STATE_CACHE_MAX_ENTRIES", "50")
    state_cache.get_cache()
    yield
    monkeypatch.delenv("CEO_STATE_CACHE_MAX_ENTRIES", raising=False)
    state_cache.get_cache()  # tears the cache down


class Counting:
    """A loader that counts calls and returns a value naming the tenant that asked, so a cross-tenant mix-up would be visible."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, ctx, now):
        self.calls.append(ctx.tenant_id)
        return bs.StateRead(EntryStatus.AVAILABLE, facts=(Fact("Owner", f"tenant {ctx.tenant_id}", "SOURCE_DERIVED"),))


def entries(loader, tables=("agent_data_request",), owner=None):
    return {"BS_TEST": bs.StateEntrySpec("BS_TEST", owner, "test", "test", loader, source_tables=tables)}


def read(ctx, ents, *, at=NOW, attached=ALL_AGENTS):
    return bs.read_entry(ctx, "BS_TEST", attached=attached, now=at, entries=ents)


def add_row(migrate_engine, tenant, app_user, status="OPEN"):
    rid = uuid.uuid4()
    with _scope(migrate_engine, tenant) as c:
        c.execute(text("INSERT INTO agent_data_request (id, tenant_id, requested_field, reason, status, created_at) VALUES (:id, :t, 'cost_price', 'needed for margins', :s, :ts)"), {"id": str(rid), "t": str(tenant), "s": status, "ts": NOW})
    return rid


# --------------------------------------------------------------------------------------------- off by default / hit
def test_caching_is_off_unless_an_operator_sets_a_size(monkeypatch, two_tenants):
    a, _ = two_tenants
    monkeypatch.delenv("CEO_STATE_CACHE_MAX_ENTRIES")
    assert state_cache.get_cache() is None
    loader = Counting()
    ents = entries(loader)
    read(ctx_for(a), ents), read(ctx_for(a), ents)
    assert len(loader.calls) == 2  # every read hit the loader


def test_an_identical_second_read_is_served_from_the_cache(two_tenants):
    a, _ = two_tenants
    loader = Counting()
    ents = entries(loader)
    first, second = read(ctx_for(a), ents), read(ctx_for(a), ents)
    assert len(loader.calls) == 1 and first.facts == second.facts
    assert state_cache.get_cache().hits >= 1


# --------------------------------------------------------------------------------------------- invalidation
def test_any_write_to_a_source_table_invalidates(two_tenants, migrate_engine, app_user):
    a, _ = two_tenants
    loader = Counting()
    ents = entries(loader)
    ctx = ctx_for(a)
    read(ctx, ents)
    rid = add_row(migrate_engine, a, app_user)  # a new row (an upload, a worker, anything)
    read(ctx, ents)
    assert len(loader.calls) == 2
    read(ctx, ents)
    assert len(loader.calls) == 2  # stable again until the next write
    with _scope(migrate_engine, a) as c:  # an UPDATE with no timestamp column involved: status flip
        c.execute(text("UPDATE agent_data_request SET status = 'FULFILLED' WHERE id = :id"), {"id": str(rid)})
    read(ctx, ents)
    assert len(loader.calls) == 3
    add_row(migrate_engine, a, app_user)
    read(ctx, ents)
    assert len(loader.calls) == 4
    with _scope(migrate_engine, a) as c:  # a DELETE
        c.execute(text("DELETE FROM agent_data_request WHERE id = :id"), {"id": str(rid)})
    read(ctx, ents)
    assert len(loader.calls) == 5


def test_returning_to_an_identical_state_may_reuse_the_value_that_was_correct_for_it(two_tenants, migrate_engine, app_user):
    """The fingerprint describes the DATA, so a write followed by its exact undo (an empty table again) matches the first entry, which was correct then
    and is correct now. This is reuse of a correct value, not staleness."""
    a, _ = two_tenants
    loader = Counting()
    ents = entries(loader)
    ctx = ctx_for(a)
    read(ctx, ents)
    rid = add_row(migrate_engine, a, app_user)
    read(ctx, ents)
    with _scope(migrate_engine, a) as c:
        c.execute(text("DELETE FROM agent_data_request WHERE id = :id"), {"id": str(rid)})
    read(ctx, ents)
    assert len(loader.calls) == 2


def test_a_write_to_another_tenant_does_not_invalidate_mine(two_tenants, migrate_engine, app_user):
    a, b = two_tenants
    loader = Counting()
    ents = entries(loader)
    read(ctx_for(a), ents)
    add_row(migrate_engine, b, app_user)  # the fingerprint is RLS-scoped: it cannot even see B's rows
    read(ctx_for(a), ents)
    assert loader.calls == [a]


def test_a_new_utc_day_recomputes(two_tenants):
    a, _ = two_tenants
    loader = Counting()
    ents = entries(loader)
    read(ctx_for(a), ents, at=NOW)
    read(ctx_for(a), ents, at=NOW + timedelta(days=1))
    assert len(loader.calls) == 2


# --------------------------------------------------------------------------------------------- isolation and authorization
def test_one_tenants_cached_value_is_never_served_to_another(two_tenants):
    a, b = two_tenants
    loader = Counting()
    ents = entries(loader)
    ra, rb = read(ctx_for(a), ents), read(ctx_for(b), ents)
    assert loader.calls == [a, b]  # B missed the cache and ran its own loader
    assert str(a) in ra.facts[0].text and str(b) in rb.facts[0].text and str(a) not in rb.facts[0].text


def test_authorization_is_checked_before_any_cache_read(two_tenants):
    a, _ = two_tenants
    loader = Counting()
    ents = entries(loader, owner=bs.AgentCode.CFO)
    owner_read = bs.read_entry(ctx_for(a), "BS_TEST", attached=ALL_AGENTS, now=NOW, entries=ents)
    # the cache now holds a result; none of these callers may be served it
    no_key = bs.read_entry(partner_ctx(a, AGENT_CEO), "BS_TEST", attached=ALL_AGENTS, now=NOW, entries=ents)  # agent.ceo but not agent.cfo
    detached = bs.read_entry(ctx_for(a), "BS_TEST", attached=frozenset({"CI"}), now=NOW, entries=ents)
    assert (no_key.status, detached.status) == (EntryStatus.NOT_PERMITTED, EntryStatus.NOT_ATTACHED)
    assert not no_key.facts and not detached.facts and owner_read.status in (EntryStatus.AVAILABLE, EntryStatus.NOT_ENTITLED)


def test_a_clock_dependent_entry_is_never_cached():
    assert bs.ENTRIES["BS_COMPETITOR_SNAPSHOT"].source_tables is None  # its 'out of date' label depends on the clock, not only on stored rows
    assert all(s.source_tables for k, s in bs.ENTRIES.items() if k != "BS_COMPETITOR_SNAPSHOT")


def test_only_whitelisted_tables_can_be_fingerprinted(two_tenants):
    a, _ = two_tenants
    with pytest.raises(ValueError):
        state_cache.data_version(a, ("investigation; DROP TABLE tenant",))
    with pytest.raises(ValueError):
        state_cache.data_version(a, ("tenant",))


# --------------------------------------------------------------------------------------------- bound and concurrency
def test_the_cache_is_bounded_and_evicts_the_oldest(monkeypatch, two_tenants):
    monkeypatch.setenv("CEO_STATE_CACHE_MAX_ENTRIES", "2")
    cache = state_cache.get_cache()
    a, _ = two_tenants
    keys = [(a, "BS_X", f"v{i}", NOW.date()) for i in range(3)]
    for k in keys:
        cache.put(k, k)
    assert len(cache) == 2 and cache.get(keys[0]) is None and cache.get(keys[2]) == keys[2]


def test_concurrent_reads_are_safe_and_all_correct(two_tenants):
    a, _ = two_tenants
    loader = Counting()
    ents = entries(loader)
    out: list = []
    threads = [threading.Thread(target=lambda: out.append(read(ctx_for(a), ents).facts[0].text)) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(out) == 12 and set(out) == {f"tenant {a}"}


def test_the_real_entries_are_cached_and_return_what_the_loader_returns(two_tenants, seed):  # noqa: F811
    a, _ = two_tenants
    seed.run(a, "COMPLETE")
    ctx = ctx_for(a)
    first = bs.ENTRIES["BS_PI_REPORT_LATEST"].loader(ctx, NOW)
    cached_1 = bs.read_entry(ctx, "BS_PI_REPORT_LATEST", attached=ALL_AGENTS, now=NOW)
    cached_2 = bs.read_entry(ctx, "BS_PI_REPORT_LATEST", attached=ALL_AGENTS, now=NOW)
    assert state_cache.get_cache().hits >= 1
    assert cached_1.facts == cached_2.facts == first.facts
