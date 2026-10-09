"""B4: the specialist Business State entries (spec 6.13): BS_COMPETITOR_SNAPSHOT (CI), BS_PI_REPORT_LATEST (PI), BS_CMO_WORKFLOW (CMO).

Each is a persisted read through a small read function in the OWNING package. Pinned here: tenant isolation, an absent agent / missing permission
yields no data, every CI price is DERIVED and its ref re-resolves through the provenance gate, a missing result is a named gap (never a zero), and
nothing a specialist generated as free text (CMO copy) is ever relayed."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from backend.auth.permissions import AGENT_CEO
from backend.ceo import business_state, provenance
from backend.ceo.contract import EntryStatus, Register
from tests.integration.ceo_support import ALL_AGENTS, ctx_for, partner_ctx

pytestmark = [
    pytest.mark.usefixtures("two_tenants"),
    pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres"),
]

NOW = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)


def _scope(_engine, tenant):
    """An owner-role transaction with the tenant context set: FORCE RLS applies to the owner too, so even test seeding is tenant-scoped. A NullPool engine
    is used because `set_config` would otherwise leave an empty setting on a pooled connection and break the shared cleanup fixtures."""
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    engine = create_engine(os.environ["DATABASE_URL"], poolclass=NullPool)

    @contextmanager
    def cm():
        with engine.begin() as c:
            c.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
            yield c

    return cm()


@pytest.fixture
def seed(migrate_engine, app_user):
    """Rows inserted as the table owner; removed again (children first) so a tenant purge is never blocked by them."""
    made: dict[str, list[tuple[uuid.UUID, uuid.UUID]]] = {"snap": [], "url": [], "run": [], "brief": [], "capture": [], "cmo": []}

    def url(tenant, label, marketplace="AMAZON"):
        uid = uuid.uuid4()
        with _scope(migrate_engine, tenant) as c:
            c.execute(text("INSERT INTO competitor_url (id, tenant_id, marketplace, url, label, status, added_by, created_at) VALUES (:id, :t, :m, :u, :l, 'ACTIVE', :by, :ts)"),
                      {"id": str(uid), "t": str(tenant), "m": marketplace, "u": f"https://www.amazon.in/dp/{uid.hex[:10]}", "l": label, "by": str(app_user), "ts": NOW})
        made["url"].append((tenant, uid))
        return uid

    def snapshot(tenant, url_id, price_paise, *, captured_at=NOW, status="COMPLETE"):
        sid, cap = uuid.uuid4(), uuid.uuid4()
        with _scope(migrate_engine, tenant) as c:
            c.execute(text("INSERT INTO ci_capture_run (id, tenant_id, trigger, requested_by, url_ids, status) VALUES (:id, :t, 'MANUAL', :by, :urls, 'COMPLETE')"),
                      {"id": str(cap), "t": str(tenant), "by": str(app_user), "urls": [str(url_id)]})
            c.execute(text("INSERT INTO competitor_snapshot (id, tenant_id, competitor_url_id, ci_capture_run_id, captured_at, capture_status, listed_price_paise, source_url, confidence, research_session_id) "
                           "VALUES (:id, :t, :u, :cap, :at, :st, :p, 'https://x.example', 'VISION_EXTRACTED', :rs)"),
                      {"id": str(sid), "t": str(tenant), "u": str(url_id), "cap": str(cap), "at": captured_at, "st": status, "p": price_paise, "rs": str(uuid.uuid4())})
        made["snap"].append((tenant, sid))
        made["capture"].append((tenant, cap))
        return sid

    def run(tenant, status, *, started_at=NOW):
        bid, rid = uuid.uuid4(), uuid.uuid4()
        with _scope(migrate_engine, tenant) as c:
            c.execute(text("INSERT INTO niche_brief (id, tenant_id, status, created_by) VALUES (:id, :t, 'READY', :by)"), {"id": str(bid), "t": str(tenant), "by": str(app_user)})
            c.execute(text("INSERT INTO pi_research_run (id, tenant_id, niche_brief_id, depth, trigger, candidate_cap, status, started_at, finished_at) VALUES (:id, :t, :b, 'STANDARD', 'MANUAL', 10, :st, :sa, :fa)"),
                      {"id": str(rid), "t": str(tenant), "b": str(bid), "st": status, "sa": started_at, "fa": started_at if status in ("COMPLETE", "PARTIAL", "FAILED") else None})
        made["brief"].append((tenant, bid))
        made["run"].append((tenant, rid))
        return rid

    def cmo(tenant, sku, *, copy="SECRET GENERATED COPY", created_at=NOW):
        gid = uuid.uuid4()
        with _scope(migrate_engine, tenant) as c:
            c.execute(text("INSERT INTO cmo_generation (id, tenant_id, sku, output_type, input_mode, output_text, status, request_key, generated_by, created_at) "
                           "VALUES (:id, :t, :sku, 'CATALOG_ANSWER', 'INDEPENDENT', :txt, 'COMPLETE', :rk, :by, :ts)"),
                      {"id": str(gid), "t": str(tenant), "sku": sku, "txt": copy, "rk": f"rk-{gid}", "by": str(app_user), "ts": created_at})
        made["cmo"].append((tenant, gid))
        return gid

    yield type("Seed", (), {"url": staticmethod(url), "snapshot": staticmethod(snapshot), "run": staticmethod(run), "cmo": staticmethod(cmo)})

    for table, key in (("competitor_snapshot", "snap"), ("ci_capture_run", "capture"), ("competitor_url", "url"), ("pi_research_run", "run"), ("niche_brief", "brief"), ("cmo_generation", "cmo")):
        for tenant, row_id in made[key]:
            with _scope(migrate_engine, tenant) as c:
                c.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": str(row_id)})


def _load(key, tenant):
    return business_state.ENTRIES[key].loader(ctx_for(tenant), NOW)


# --------------------------------------------------------------------------------------------- catalog
def test_the_three_entries_are_in_the_catalog_with_the_right_owners_and_only_v1_later_ones_stay_deferred():
    owners = {k: business_state.ENTRIES[k].owner.value for k in ("BS_COMPETITOR_SNAPSHOT", "BS_PI_REPORT_LATEST", "BS_CMO_WORKFLOW")}
    assert owners == {"BS_COMPETITOR_SNAPSHOT": "CI", "BS_PI_REPORT_LATEST": "PI", "BS_CMO_WORKFLOW": "CMO"}
    assert sorted(business_state.DEFERRED_ENTRIES) == ["BS_GOAL_PROGRESS", "BS_SITUATIONS"]


# --------------------------------------------------------------------------------------------- CI
def test_ci_prices_are_derived_with_a_ref_that_re_resolves_and_a_missing_result_is_a_named_gap(two_tenants, seed):
    a, _ = two_tenants
    u1, u2 = seed.url(a, "Rival One"), seed.url(a, "Rival Two")
    snap = seed.snapshot(a, u1, 49900)
    read = _load("BS_COMPETITOR_SNAPSHOT", a)
    assert read.status is EntryStatus.PARTIAL and len(read.figures) == 1
    f = read.figures[0]
    assert (f.formatted_value, f.register, f.ref.id, f.ref.source) == ("₹499.00", Register.DERIVED, snap, "competitor_snapshot")  # CI never claims VERIFIED
    assert any("Rival Two" in g.message and "no research" in g.message for g in read.gaps)  # a named gap, not a zero
    assert provenance.gate_figures(a, read.figures).kept == read.figures  # the ref resolves for THIS tenant
    assert u2 not in {f.ref.id for f in read.figures}


def test_ci_a_stale_capture_is_labelled_and_a_pending_one_is_not_a_price(two_tenants, seed):
    a, _ = two_tenants
    old, pending = seed.url(a, "Old"), seed.url(a, "Pending")
    seed.snapshot(a, old, 30000, captured_at=NOW - timedelta(days=400))
    seed.snapshot(a, pending, None, status="PENDING_MANUAL_ENTRY")
    read = _load("BS_COMPETITOR_SNAPSHOT", a)
    assert [f.note for f in read.figures] == ["This capture is out of date."]
    assert any("Pending" in g.message and "no usable price" in g.message for g in read.gaps)


def test_ci_no_competitors_is_unavailable_not_empty_success(two_tenants):
    a, _ = two_tenants
    read = _load("BS_COMPETITOR_SNAPSHOT", a)
    assert read.status is EntryStatus.UNAVAILABLE and not read.figures and read.gaps[0].code == "NO_COMPETITORS"


def test_ci_another_tenant_sees_none_of_it(two_tenants, seed):
    a, b = two_tenants
    seed.snapshot(a, seed.url(a, "Mine"), 49900)
    theirs = _load("BS_COMPETITOR_SNAPSHOT", b)
    assert theirs.status is EntryStatus.UNAVAILABLE and not theirs.figures
    mine = _load("BS_COMPETITOR_SNAPSHOT", a)
    assert provenance.gate_figures(b, mine.figures).kept == ()  # and A's refs do not resolve under B


def test_ci_unattached_or_unpermitted_members_get_no_data(two_tenants, seed):
    a, _ = two_tenants
    seed.snapshot(a, seed.url(a, "Rival"), 49900)
    detached = business_state.read_entry(ctx_for(a), "BS_COMPETITOR_SNAPSHOT", attached=frozenset({"CFO"}), now=NOW)
    assert detached.status is EntryStatus.NOT_ATTACHED and not detached.figures
    no_key = business_state.read_entry(partner_ctx(a, AGENT_CEO), "BS_COMPETITOR_SNAPSHOT", attached=ALL_AGENTS, now=NOW)  # agent.ceo but not agent.ci
    assert no_key.status is EntryStatus.NOT_PERMITTED and not no_key.figures


# --------------------------------------------------------------------------------------------- PI
@pytest.mark.parametrize("status,expected_status,phrase", [
    ("COMPLETE", EntryStatus.AVAILABLE, "report is ready"), ("PARTIAL", EntryStatus.AVAILABLE, "some parts missing"),
    ("RUNNING", EntryStatus.PARTIAL, "still running"), ("QUEUED", EntryStatus.PARTIAL, "queued"), ("FAILED", EntryStatus.PARTIAL, "did not complete"),
])
def test_pi_reports_the_state_of_the_latest_run_with_a_date_and_no_invented_numbers(two_tenants, seed, status, expected_status, phrase):
    a, _ = two_tenants
    seed.run(a, status)
    read = _load("BS_PI_REPORT_LATEST", a)
    assert read.status is expected_status and not read.figures  # no counts or scores: they have no engine ref
    assert phrase in read.facts[0].text and read.facts[0].basis == "SOURCE_DERIVED"


def test_pi_the_newest_run_wins_and_none_is_unavailable(two_tenants, seed):
    a, b = two_tenants
    assert _load("BS_PI_REPORT_LATEST", a).status is EntryStatus.UNAVAILABLE
    seed.run(a, "FAILED", started_at=NOW - timedelta(days=3))
    seed.run(a, "COMPLETE", started_at=NOW)
    assert "report is ready" in _load("BS_PI_REPORT_LATEST", a).facts[0].text
    assert _load("BS_PI_REPORT_LATEST", b).status is EntryStatus.UNAVAILABLE  # tenant isolation


# --------------------------------------------------------------------------------------------- CMO
def test_cmo_lists_what_was_generated_and_never_the_generated_copy(two_tenants, seed):
    a, b = two_tenants
    seed.cmo(a, "SKU-1")
    read = _load("BS_CMO_WORKFLOW", a)
    assert read.status is EntryStatus.AVAILABLE and "SKU-1" in read.facts[0].text and "complete" in read.facts[0].text
    assert "SECRET GENERATED COPY" not in repr(read)  # R9: specialist free text is never relayed
    assert _load("BS_CMO_WORKFLOW", b).status is EntryStatus.UNAVAILABLE


def test_cmo_shows_at_most_the_five_newest(two_tenants, seed):
    a, _ = two_tenants
    for i in range(7):
        seed.cmo(a, f"SKU-{i}", created_at=NOW - timedelta(hours=7 - i))
    facts = _load("BS_CMO_WORKFLOW", a).facts
    assert len(facts) == 5 and "SKU-6" in facts[0].text and not any("SKU-0" in f.text or "SKU-1" in f.text for f in facts)
