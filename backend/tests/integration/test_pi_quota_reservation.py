"""R6: PI quota reservation. Proves that concurrent requests cannot overshoot the last available unit, that failures release it, that a crash cannot leak a free unit
before the TTL, and that a cap with an unusable reservation setting is refused rather than risked.

PI caps stay UNSEEDED in every real environment until these tests pass. Caps are seeded here only on the disposable test database."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from backend.services import pi_actions, pi_usage
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import seed_platform_cap
from tests.integration.test_pi_discover_api import (  # noqa: F401
    _FakeEmbeddingClient,
    _FakeTavilyClient,
    _FakeTextExtractor,
    _NoVideosYoutube,
    _register_owner,
    app_client,
    fake_clerk,
    tenant,
)
from tests.integration.test_pi_usage import _DownTavily, events

pytestmark = pytest.mark.usefixtures("two_tenants")
BIG_TTL = "100000"  # seconds; comfortably above the structural worst case of any PI action


@pytest.fixture(autouse=True)
def _ttl(monkeypatch):
    monkeypatch.setenv("PI_QUOTA_RESERVATION_TTL_SECONDS", BIG_TTL)


def reservations(tenant_id):
    with tenant_scope(tenant_id) as conn:
        return sorted(tuple(r) for r in conn.execute(text("SELECT agent_code, meter_code, state FROM cmo_quota_reservation")))


def fakes(monkeypatch, tavily=None):
    from product_intelligence.sources.cache import InProcessQueryCache

    monkeypatch.setattr(pi_actions, "_QUERY_CACHE", InProcessQueryCache())
    monkeypatch.setattr(pi_actions, "_tavily_client", lambda: tavily or _FakeTavilyClient())
    monkeypatch.setattr(pi_actions, "_youtube_client", lambda: _NoVideosYoutube())
    monkeypatch.setattr(pi_actions, "_text_extractor", lambda: _FakeTextExtractor())
    monkeypatch.setattr(pi_actions, "_embedding_client", lambda: _FakeEmbeddingClient())


def new_brief(client, headers, *, ready=True) -> str:
    brief = client.post("/api/v1/pi/niche-briefs", json={"category_text": "wireless earbuds", "budget_paise": 500_000, "marketplaces": ["AMAZON"]}, headers=headers).json()["nicheBriefId"]
    if ready:
        client.post(f"/api/v1/pi/niche-briefs/{brief}/mark-ready", headers=headers)
    return brief


def post(client, headers, brief):
    return client.post("/api/v1/pi/discover", json={"niche_brief_id": brief, "depth": "SHALLOW"}, headers=headers)


def now():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------------------------------------ the race for the last unit
@pytest.mark.parametrize("contenders", [8, 24])
def test_concurrent_reservations_for_the_last_unit_admit_exactly_one(two_tenants, migrate_engine, contenders):
    a, _ = two_tenants
    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.discover", cap_value=1)
    barrier = threading.Barrier(contenders)
    won, denied, other = [], [], []

    def contend(i: int) -> None:
        barrier.wait(timeout=30)
        try:
            won.append(pi_usage.reserve(a, (pi_usage.DISCOVER_METERS[1],), request_key=f"pi:discover:{uuid.uuid4()}", worst_case_seconds=1850, now=now()))
        except pi_usage.QuotaDenied as exc:
            denied.append(exc.detail)
        except Exception as exc:  # noqa: BLE001
            other.append(exc)

    threads = [threading.Thread(target=contend, args=(i,)) for i in range(contenders)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert other == []
    assert len(won) == 1 and len(denied) == contenders - 1  # exactly one unit, never two
    assert all(d["reason"] == "OVER_CAP" and d["cap"] == 1 for d in denied)
    assert reservations(a) == [("PI", "pi.discover", "RESERVED")]


def test_eight_overlapping_http_requests_for_the_last_unit_run_exactly_one_discovery_and_record_one_event_per_meter(app_client, fake_clerk, tenant, migrate_engine, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app

    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.discover", cap_value=1)
    seed_platform_cap(migrate_engine, agent_code="SHARED", meter_code="research.niche_run", cap_value=1)
    headers = _register_owner(fake_clerk, tenant)
    release, entered = threading.Event(), threading.Event()

    class HeldTavily(_FakeTavilyClient):
        calls = 0

        def search(self, query, *, include_images=False, max_results=10, **_):
            HeldTavily.calls += 1
            entered.set()
            assert release.wait(timeout=60), "the winner was never released"  # the winner holds the unit while the others compete
            return super().search(query, include_images=include_images, max_results=max_results)

    fakes(monkeypatch, tavily=HeldTavily())
    briefs = [new_brief(app_client, headers) for _ in range(8)]
    out: list[tuple[int, dict]] = []

    def go(brief: str) -> None:
        resp = post(TestClient(app), headers, brief)
        out.append((resp.status_code, resp.json()))

    threads = [threading.Thread(target=go, args=(b,)) for b in briefs]
    [t.start() for t in threads]
    deadline = time.time() + 90
    while len([o for o in out if o[0] != 200]) < 7 and time.time() < deadline:
        time.sleep(0.05)
    release.set()
    [t.join() for t in threads]
    codes = sorted(c for c, _ in out)
    assert codes == [200] + [402] * 7, out
    assert all(b["detail"]["reason"] == "OVER_CAP" for c, b in out if c == 402)
    assert HeldTavily.calls >= 1 and entered.is_set()
    winner = next(b for c, b in out if c == 200)
    assert winner["status"] == "COMPLETE"
    assert len(events(tenant)) == 2  # one pi.discover and one research.niche_run, no more
    assert reservations(tenant) == [("PI", "pi.discover", "SETTLED"), ("SHARED", "research.niche_run", "SETTLED")]


# ------------------------------------------------------------------------------------------------ what happens to the reserved unit
def test_a_failed_winner_releases_its_unit_and_the_next_request_proceeds(app_client, fake_clerk, tenant, migrate_engine, monkeypatch):
    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.discover", cap_value=1)
    headers = _register_owner(fake_clerk, tenant)
    fakes(monkeypatch)
    failed = post(app_client, headers, new_brief(app_client, headers, ready=False))  # a FAILED run (brief not READY)
    assert failed.status_code == 200 and failed.json()["status"] == "FAILED"
    assert reservations(tenant) == [("PI", "pi.discover", "RELEASED")] and events(tenant) == []
    ok = post(app_client, headers, new_brief(app_client, headers))
    assert ok.status_code == 200 and ok.json()["status"] == "COMPLETE"  # the failed run did not consume the cap


def test_a_run_row_that_cannot_be_written_releases_the_unit_it_just_reserved(app_client, fake_clerk, tenant, migrate_engine, monkeypatch):
    """The unit is reserved BEFORE the run row is written. If that write fails, no provider was called, so the unit must be freed at once; leaving it
    reserved until the TTL would lock a cap-of-1 seller out of PI for hours over a database blip."""
    from backend.repositories import agent_run_repo

    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.discover", cap_value=1)
    headers = _register_owner(fake_clerk, tenant)
    fakes(monkeypatch)
    brief = new_brief(app_client, headers)
    real = agent_run_repo.insert_run

    def broken(*args, **kwargs):
        monkeypatch.setattr(agent_run_repo, "insert_run", real)  # fail once, then behave
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(agent_run_repo, "insert_run", broken)
    with pytest.raises(RuntimeError, match="database unavailable"):
        post(app_client, headers, brief)
    assert reservations(tenant) == [("PI", "pi.discover", "RELEASED")] and events(tenant) == []
    ok = post(app_client, headers, brief)  # the same seller can use the unit straight away
    assert ok.status_code == 200 and ok.json()["status"] == "COMPLETE"


def test_a_supplier_lookup_whose_run_row_cannot_be_written_releases_its_unit(app_client, fake_clerk, tenant, migrate_engine, monkeypatch):
    from backend.repositories import agent_run_repo

    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.supplier_lookup", cap_value=1)
    headers = _register_owner(fake_clerk, tenant)

    def broken(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(agent_run_repo, "insert_run", broken)
    with pytest.raises(RuntimeError, match="database unavailable"):
        app_client.post("/api/v1/pi/supplier-lookup", json={"run_id": str(uuid.uuid4()), "candidate_ids": [str(uuid.uuid4())]}, headers=headers)
    assert reservations(tenant) == [("PI", "pi.supplier_lookup", "RELEASED")]


def test_a_failing_run_and_a_failing_row_update_still_release_the_unit_and_report_the_original_error(app_client, fake_clerk, tenant, migrate_engine, monkeypatch):
    """If the run raises AND marking its row FAILED also raises, the seller-facing error must still be the original one and the unit must still be freed."""
    from backend.api.v1 import pi as pi_api
    from backend.repositories import agent_run_repo

    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.discover", cap_value=1)
    headers = _register_owner(fake_clerk, tenant)
    fakes(monkeypatch)
    brief = new_brief(app_client, headers)

    def exploding(*args, **kwargs):
        raise RuntimeError("provider exploded")

    def broken_finish(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(pi_api, "run_discovery", exploding)
    monkeypatch.setattr(agent_run_repo, "finish_run_if_unfinished", broken_finish)
    with pytest.raises(RuntimeError, match="provider exploded"):
        post(app_client, headers, brief)
    assert reservations(tenant) == [("PI", "pi.discover", "RELEASED")] and events(tenant) == []


def test_a_failing_supplier_lookup_and_a_failing_row_update_still_release_the_unit(app_client, fake_clerk, tenant, migrate_engine, monkeypatch):
    from backend.api.v1 import pi as pi_api
    from backend.repositories import agent_run_repo

    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.supplier_lookup", cap_value=1)
    headers = _register_owner(fake_clerk, tenant)

    def exploding(*args, **kwargs):
        raise RuntimeError("lookup exploded")

    def broken_finish(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(pi_api, "run_supplier_lookup", exploding)
    monkeypatch.setattr(agent_run_repo, "finish_run_if_unfinished", broken_finish)
    with pytest.raises(RuntimeError, match="lookup exploded"):
        app_client.post("/api/v1/pi/supplier-lookup", json={"run_id": str(uuid.uuid4()), "candidate_ids": [str(uuid.uuid4())]}, headers=headers)
    assert reservations(tenant) == [("PI", "pi.supplier_lookup", "RELEASED")]


def test_a_pi_run_row_settled_by_someone_else_mid_call_keeps_its_status(app_client, fake_clerk, tenant, migrate_engine, monkeypatch):
    """R5 Stage A for PI's direct route (which the CEO's pi.discover also runs): the route's terminal write is guarded, so a row already settled
    (a future recovery mark) is not overwritten by the late success. The seller still gets the answer the call produced."""
    from backend.api.v1 import pi as pi_api
    from backend.repositories import agent_run_repo

    headers = _register_owner(fake_clerk, tenant)
    fakes(monkeypatch)
    brief = new_brief(app_client, headers)
    real = pi_api.run_discovery

    def settled_meanwhile(*args, **kwargs):
        with tenant_scope(tenant) as conn:
            run_id = conn.execute(text("SELECT id FROM agent_run WHERE trigger_ref = 'pi.discover' AND status = 'RUNNING'")).scalar_one()
        agent_run_repo.finish_run(tenant, run_id, status="FAILED", error_reason="marked by someone else", finished_at=now())
        return real(*args, **kwargs)

    monkeypatch.setattr(pi_api, "run_discovery", settled_meanwhile)
    response = post(app_client, headers, brief)
    assert response.status_code == 200 and response.json()["status"] == "COMPLETE"
    with tenant_scope(tenant) as conn:
        assert [tuple(r) for r in conn.execute(text("SELECT status, error_reason FROM agent_run WHERE trigger_ref = 'pi.discover'"))] == [("FAILED", "marked by someone else")]


def test_an_empty_run_does_not_consume_the_cap(app_client, fake_clerk, tenant, migrate_engine, monkeypatch):
    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.discover", cap_value=1)
    headers = _register_owner(fake_clerk, tenant)
    fakes(monkeypatch, tavily=_DownTavily())
    empty = post(app_client, headers, new_brief(app_client, headers))
    assert empty.json()["candidateIds"] == [] and events(tenant) == []
    fakes(monkeypatch)
    assert post(app_client, headers, new_brief(app_client, headers)).status_code == 200


def test_a_successful_run_consumes_the_unit_and_the_next_request_is_refused(app_client, fake_clerk, tenant, migrate_engine, monkeypatch):
    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.discover", cap_value=1)
    headers = _register_owner(fake_clerk, tenant)
    fakes(monkeypatch)
    assert post(app_client, headers, new_brief(app_client, headers)).status_code == 200
    second = post(app_client, headers, new_brief(app_client, headers))
    assert second.status_code == 402 and second.json()["detail"]["reason"] == "OVER_CAP"


def test_a_crashed_winner_holds_its_unit_until_the_reservation_expires_and_nobody_gets_it_free(two_tenants, migrate_engine):
    a, _ = two_tenants
    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.discover", cap_value=1)
    meters = (pi_usage.DISCOVER_METERS[1],)
    crashed = pi_usage.reserve(a, meters, request_key="pi:discover:crashed", worst_case_seconds=1850, now=now())  # reserved, then the process "dies": never settled
    assert len(crashed.ids) == 1
    with pytest.raises(pi_usage.QuotaDenied):
        pi_usage.reserve(a, meters, request_key="pi:discover:next", worst_case_seconds=1850, now=now())  # the unit is still protected
    with tenant_scope(a) as conn:  # time passes beyond the TTL
        conn.execute(text("UPDATE cmo_quota_reservation SET expires_at = now() - interval '1 second' WHERE state = 'RESERVED'"))
    again = pi_usage.reserve(a, meters, request_key="pi:discover:next", worst_case_seconds=1850, now=now())
    assert len(again.ids) == 1  # only after expiry may the next request have it (the crashed run recorded no usage, so nothing was charged)
    assert [r[2] for r in reservations(a)] == ["RELEASED", "RESERVED"]


def test_a_failed_usage_write_keeps_the_unit_reserved_so_it_cannot_be_used_to_exceed_the_cap(app_client, fake_clerk, tenant, migrate_engine, monkeypatch):
    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.discover", cap_value=1)
    headers = _register_owner(fake_clerk, tenant)
    fakes(monkeypatch)
    monkeypatch.setattr(pi_usage, "record_metered_event", lambda *a, **k: None)
    first = post(app_client, headers, new_brief(app_client, headers))
    assert first.status_code == 200 and events(tenant) == []  # delivered, but unmetered
    assert reservations(tenant) == [("PI", "pi.discover", "RESERVED")]  # still counting against the cap
    assert post(app_client, headers, new_brief(app_client, headers)).status_code == 402


def test_a_denial_on_the_second_meter_releases_the_first(two_tenants, migrate_engine):
    a, _ = two_tenants
    seed_platform_cap(migrate_engine, agent_code="SHARED", meter_code="research.niche_run", cap_value=5)
    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.discover", cap_value=1)
    pi_usage.reserve(a, (pi_usage.DISCOVER_METERS[1],), request_key="pi:discover:holder", worst_case_seconds=1850, now=now())  # someone holds the last PI unit
    with pytest.raises(pi_usage.QuotaDenied):
        pi_usage.reserve(a, pi_usage.DISCOVER_METERS, request_key="pi:discover:late", worst_case_seconds=1850, now=now())
    assert reservations(a) == [("PI", "pi.discover", "RESERVED"), ("SHARED", "research.niche_run", "RELEASED")]


def test_a_double_submit_of_the_same_request_is_in_progress_not_a_second_unit(two_tenants, migrate_engine):
    a, _ = two_tenants
    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.discover", cap_value=5)
    meters = (pi_usage.DISCOVER_METERS[1],)
    pi_usage.reserve(a, meters, request_key="pi:discover:same", worst_case_seconds=1850, now=now())
    with pytest.raises(pi_usage.RequestInProgress):
        pi_usage.reserve(a, meters, request_key="pi:discover:same", worst_case_seconds=1850, now=now())


# ------------------------------------------------------------------------------------------------ fail closed
def test_a_cap_without_a_usable_reservation_setting_is_refused_with_503(app_client, fake_clerk, tenant, migrate_engine, monkeypatch):
    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.discover", cap_value=3)
    headers = _register_owner(fake_clerk, tenant)
    fakes(monkeypatch)
    brief = new_brief(app_client, headers)
    monkeypatch.delenv("PI_QUOTA_RESERVATION_TTL_SECONDS")
    missing = post(app_client, headers, brief)
    assert missing.status_code == 503 and missing.json()["detail"]["code"] == "PI_NOT_CONFIGURED"
    monkeypatch.setenv("PI_QUOTA_RESERVATION_TTL_SECONDS", "60")  # shorter than the action's structural worst case
    short = post(app_client, headers, brief)
    assert short.status_code == 503 and short.json()["detail"]["code"] == "PI_NOT_CONFIGURED"
    assert events(tenant) == [] and reservations(tenant) == []  # nothing ran, nothing was reserved


def test_without_any_cap_nothing_is_reserved_and_no_setting_is_needed(app_client, fake_clerk, tenant, monkeypatch):
    monkeypatch.delenv("PI_QUOTA_RESERVATION_TTL_SECONDS")
    headers = _register_owner(fake_clerk, tenant)
    fakes(monkeypatch)
    assert post(app_client, headers, new_brief(app_client, headers)).status_code == 200
    assert reservations(tenant) == []  # NO_CAP_CONFIGURED: stated honestly, nothing to serialise


def test_the_supplier_lookup_is_protected_the_same_way(two_tenants, migrate_engine):
    a, _ = two_tenants
    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.supplier_lookup", cap_value=1)
    barrier = threading.Barrier(8)
    won, denied = [], []

    def contend() -> None:
        barrier.wait(timeout=30)
        try:
            won.append(pi_usage.reserve(a, pi_usage.LOOKUP_METERS, request_key=f"pi:supplier:{uuid.uuid4()}", worst_case_seconds=30, now=now()))
        except pi_usage.QuotaDenied:
            denied.append(1)

    threads = [threading.Thread(target=contend) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert (len(won), len(denied)) == (1, 7)


def test_candidate_cap_is_bounded_at_the_api_1_to_100(app_client, fake_clerk, tenant, migrate_engine, monkeypatch):
    headers = _register_owner(fake_clerk, tenant)
    fakes(monkeypatch)
    seed_platform_cap(migrate_engine, agent_code="PI", meter_code="pi.discover", cap_value=50)
    for bad in (0, -1, -100, 101, 1000):
        r = app_client.post("/api/v1/pi/discover", json={"niche_brief_id": new_brief(app_client, headers), "depth": "SHALLOW", "candidate_cap": bad}, headers=headers)
        assert r.status_code == 422, bad  # rejected before anything is reserved, run or metered
    assert reservations(tenant) == []
    for ok in (1, 100):
        r = app_client.post("/api/v1/pi/discover", json={"niche_brief_id": new_brief(app_client, headers), "depth": "SHALLOW", "candidate_cap": ok}, headers=headers)
        assert r.status_code == 200, (ok, r.text)
