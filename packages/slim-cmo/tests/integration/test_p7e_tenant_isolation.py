"""P7e privacy and tenant isolation end to end on a real Postgres: real niche terms -> `confirmed_terms` -> query plan ->
retrieval with fake providers. Only the caller's CONFIRMED terms may reach a provider; catalog titles, SUGGESTED / REJECTED
terms, another tenant's terms and seller facts never do."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from market_signals.cache import InProcessQueryCache
from sqlalchemy import text

from slim_cmo.repositories.niche_repo import PostgresNicheStore
from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.retrieval.service import RetrievalService
from slim_cmo.service.models import Actor
from slim_cmo.service.niche import Decision, DecisionKind, NicheService
from slim_cmo.trends.queries import EgressViolation, build_plan
from slim_cmo.types import Marketplace as M
from slim_cmo.types import TrendSection as S

from ..unit.factories import trend_config
from ..unit.retrieval.test_service import FakeSlots, FakeTavily, FakeYoutube
from ..unit.trends.test_queries import LAUNCH
from .test_p7d_niche_store import put_config, put_sales_lines

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
CFG = trend_config(**LAUNCH)
NICHE_CFG = {"max_confirmed_niche_terms": 5, "max_term_chars": 40, "catalog_titles_read_cap": 100}


def service():
    return NicheService(PostgresNicheStore(), clock=lambda: NOW)


def retrieval(t, y, slots=None):
    from contextlib import contextmanager

    @contextmanager
    def throttle(_):
        yield

    return RetrievalService(tavily=t, youtube=y, cache=InProcessQueryCache(), slots=slots or FakeSlots(), clock=lambda: NOW, throttle=throttle)


def sent(t, y):
    return {c["query"] for c in t.calls} | {c["query"] for c in y.calls}


def test_only_confirmed_terms_of_the_callers_tenant_reach_the_providers(migrate_engine):
    a, b = Actor(uuid.uuid4(), uuid.uuid4()), Actor(uuid.uuid4(), uuid.uuid4())
    for actor in (a, b):
        put_config(migrate_engine, actor.tenant_id, NICHE_CFG)
    put_sales_lines(a.tenant_id, ["Steel Water Bottle 1 Litre", "Steel Water Bottle Gym", "Copper Water Bottle", "Yoga Mat Anti Skid", "Yoga Mat Thick"])
    put_sales_lines(b.tenant_id, ["Wooden Chess Board Set", "Wooden Chess Board Large"])

    sa = service().suggest(a)
    service().suggest(b)
    confirm_term = next(s for s in sa.suggestions if s.term == "water bottle")
    reject_term = next(s for s in sa.suggestions if s.term == "yoga mat")
    service().confirm(a, [Decision(DecisionKind.CONFIRM, confirm_term.id), Decision(DecisionKind.REJECT, reject_term.id)])
    service().confirm(b, [], ["wooden chess board"])

    terms_a = service().confirmed_terms(a)
    assert terms_a == ("water bottle",)
    plan = build_plan(config=CFG, sections=tuple(S), confirmed_terms=terms_a, marketplaces=tuple(M))
    t, y = FakeTavily(), FakeYoutube()
    retrieval(t, y).run(plan, config=CFG, confirmed_terms=terms_a)

    out = " | ".join(sent(t, y)).lower()
    assert "water bottle" in out
    for forbidden in ("yoga mat", "chess", "steel water bottle 1 litre", "copper", "anti skid", "wooden"):
        assert forbidden not in out  # rejected, suggested-but-unconfirmed, other-tenant and raw catalog titles never leave
    assert service().confirmed_terms(b) == ("wooden chess board",)


def test_a_suggested_but_unconfirmed_term_is_refused_if_someone_tries_to_send_it(migrate_engine):
    a = Actor(uuid.uuid4(), uuid.uuid4())
    put_config(migrate_engine, a.tenant_id, NICHE_CFG)
    put_sales_lines(a.tenant_id, ["Steel Water Bottle 1 Litre", "Steel Water Bottle Gym"])
    service().suggest(a)  # SUGGESTED rows exist; nothing confirmed
    assert service().confirmed_terms(a) == ()
    suggested = [t.term for t in service().list_terms(a)]
    assert suggested
    plan = build_plan(config=CFG, sections=tuple(S), confirmed_terms=suggested, marketplaces=tuple(M))  # a caller passing the wrong list
    t, y, s = FakeTavily(), FakeYoutube(), FakeSlots()
    with pytest.raises(EgressViolation):
        retrieval(t, y, s).run(plan, config=CFG, confirmed_terms=service().confirmed_terms(a))  # the guard checks against CONFIRMED rows
    assert t.calls == [] and y.calls == [] and s.taken == []


def test_seller_facts_notes_and_other_columns_cannot_reach_a_provider(migrate_engine):
    a = Actor(uuid.uuid4(), uuid.uuid4())
    put_config(migrate_engine, a.tenant_id, NICHE_CFG)
    put_sales_lines(a.tenant_id, ["Steel Water Bottle 1 Litre"])
    with tenant_scope(a.tenant_id) as conn:  # a SELLER_PROVIDED fact and a target price: stored data, not confirmed niche terms
        conn.execute(text("INSERT INTO seller_fact (tenant_id, sku, attribute_name, fact_type, fact_value, provided_by) VALUES (:t, 'SKU1', 'brand', 'BRAND', 'AquaKeepSecretBrand', :u)"),
                     {"t": a.tenant_id, "u": a.user_id})
        conn.execute(text("INSERT INTO seller_fact (tenant_id, sku, fact_type, value_paise, provided_by) VALUES (:t, 'SKU1', 'TARGET_PRICE', 49900, :u)"), {"t": a.tenant_id, "u": a.user_id})
    service().confirm(a, [], ["steel bottle"])
    terms = service().confirmed_terms(a)
    plan = build_plan(config=CFG, sections=tuple(S), confirmed_terms=terms, marketplaces=tuple(M))
    t, y = FakeTavily(), FakeYoutube()
    retrieval(t, y).run(plan, config=CFG, confirmed_terms=terms)
    out = json.dumps(sorted(sent(t, y))).lower() + json.dumps(plan.preview()).lower()
    for secret in ("aquakeepsecretbrand", "49900", "499", "sku1", "order-secret", "9990"):
        assert secret not in out


def test_the_outbound_preview_persisted_for_audit_equals_what_the_provider_received(migrate_engine):
    a = Actor(uuid.uuid4(), uuid.uuid4())
    put_config(migrate_engine, a.tenant_id, NICHE_CFG)
    service().confirm(a, [], ["steel bottle", "yoga mat"])
    terms = service().confirmed_terms(a)
    plan = build_plan(config=CFG, sections=tuple(S), confirmed_terms=terms, marketplaces=(M.AMAZON,))
    t, y = FakeTavily(), FakeYoutube()
    retrieval(t, y).run(plan, config=CFG, confirmed_terms=terms)
    assert sent(t, y) == {p["query"] for p in plan.preview()}
    json.dumps(plan.preview())  # JSON-able as `cmo_trend_report.outbound_queries`
