"""P3 persistence against a real Postgres (skipped automatically when DATABASE_URL_APP / DATABASE_URL
are unset). Touches only rows of freshly generated tenants plus TEST_FIXTURE constraint rows and
`test_`-prefixed platform config keys, all of which conftest cleans up."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from slim_cmo.generation.provider import ScriptedLlmProvider
from slim_cmo.repositories import config_repo, constraint_repo
from slim_cmo.repositories.postgres_store import PostgresGenerationStore
from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.service.approve import Approved, ApprovalService
from slim_cmo.service.generate import GenerationService, GroundingRequest, Intake
from slim_cmo.service.models import Actor, DuplicateArtefact, GenerationRecord, NewFact
from slim_cmo.types import ConstraintRowKind as K
from slim_cmo.types import GenerationStatus, Marketplace as M, OutputType as O, SellerFactType as F

from ._seed import NOW, insert_format_constraint

CLOCK = lambda: NOW + timedelta(days=1)  # noqa: E731
TITLES = ["AquaKeep Steel Bottle 750 ml", "AquaKeep Insulated Flask 750 ml", "AquaKeep Stainless Water Bottle",
          "AquaKeep 750 ml Steel Flask", "AquaKeep Steel Water Bottle"]
PACK = json.dumps({
    "description": "A 750 ml stainless steel bottle from AquaKeep for everyday use.",
    "bullets": ["Stainless steel build", "750 ml capacity", "Easy to carry", "Leak resistant lid", "Simple to clean"],
    "keywords": ["steel bottle", "water bottle"],
})


def seed_config(migrate_engine, tenant: uuid.UUID, values: dict, effective: str = "2026-01-01", key_prefix: str = "") -> None:
    with migrate_engine.begin() as conn:
        for k, v in values.items():
            conn.execute(
                text("INSERT INTO cmo_platform_config (tenant_id, key, value, effective_from) VALUES (:t, :k, CAST(:v AS jsonb), :e)"),
                {"t": tenant, "k": f"{key_prefix}{k}", "v": json.dumps(v), "e": effective},
            )


@pytest.fixture
def tenant(migrate_engine):
    t = uuid.uuid4()
    seed_config(migrate_engine, t, {"format_constraint_max_age_days": 30, "internal_retry_bound": 1, "hashtag_set_size": 3})
    yield t
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM cmo_platform_config WHERE tenant_id = :t"), {"t": t})


@pytest.fixture
def fixtures(migrate_engine):
    return {mp: insert_format_constraint(migrate_engine, marketplace=mp.value, title_option_count=5, bullet_count=5) for mp in M}


def service(replies, **kw):
    return GenerationService(PostgresGenerationStore(), ScriptedLlmProvider(replies), model="m", clock=CLOCK,
                             accepted_row_kinds=frozenset({K.TEST_FIXTURE}), **kw)


def intake(key, **kw):
    return Intake(request_key=key, sku="SKU1", brand="AquaKeep", attributes=(("capacity", "750 ml"), ("material", "stainless steel")), **kw)


def count(conn, table, tenant):
    return conn.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": tenant}).scalar_one()


def test_production_path_never_reads_fixture_rows_and_tests_must_ask_for_them(fixtures):
    with tenant_scope(uuid.uuid4()) as conn:
        default_ids = {c.id for c in constraint_repo.list_constraints(conn, M.AMAZON)}
        fixture_ids = {c.id for c in constraint_repo.list_constraints(conn, M.AMAZON, [K.TEST_FIXTURE])}
    assert fixtures[M.AMAZON] in fixture_ids and fixtures[M.AMAZON] not in default_ids


def test_config_resolution_latest_effective_wins_future_ignored_and_tenants_are_isolated(migrate_engine, tenant):
    other = uuid.uuid4()
    seed_config(migrate_engine, tenant, {"hashtag_set_size": 9}, effective="2026-06-01")
    seed_config(migrate_engine, tenant, {"hashtag_set_size": 99}, effective="2099-01-01")
    seed_config(migrate_engine, other, {"hashtag_set_size": 5})
    try:
        with tenant_scope(tenant) as conn:
            got = config_repo.load_config_values(conn, tenant, ["hashtag_set_size", "internal_retry_bound", "nope"], date(2026, 10, 4))
        assert got == {"hashtag_set_size": 9, "internal_retry_bound": 1}  # absent key stays absent: no default
        with tenant_scope(other) as conn:
            assert config_repo.load_config_values(conn, other, ["internal_retry_bound"], date(2026, 10, 4)) == {}
    finally:
        with migrate_engine.begin() as conn:
            conn.execute(text("DELETE FROM cmo_platform_config WHERE tenant_id = :t"), {"t": other})


def test_platform_default_is_beaten_by_the_tenant_row(migrate_engine, tenant):
    with migrate_engine.begin() as conn:
        conn.execute(text("INSERT INTO cmo_platform_config (tenant_id, key, value, effective_from) VALUES (NULL, 'test_precedence', '1'::jsonb, '2026-01-01')"))
    seed_config(migrate_engine, tenant, {"precedence": 2}, key_prefix="test_")
    with tenant_scope(tenant) as conn:
        assert config_repo.load_config_values(conn, tenant, ["test_precedence"], date(2026, 10, 4)) == {"test_precedence": 2}


def test_title_set_pack_and_approval_round_trip_with_rows_options_and_idempotency(migrate_engine, tenant, fixtures):
    actor = Actor(tenant, uuid.uuid4())
    store = PostgresGenerationStore()
    run = service([json.dumps({"titles": TITLES})]).generate_title_sets(actor, intake("k1"), [M.AMAZON])
    assert run.units_to_bill == 1
    gid = run.artefacts[0].generation_id
    with tenant_scope(tenant) as conn:
        assert count(conn, "cmo_title_option", tenant) == 5 and count(conn, "cmo_generation", tenant) == 1
    again = service([]).generate_title_sets(actor, intake("k1"), [M.AMAZON])  # no replies scripted: no model call allowed
    assert again.artefacts[0].reused and again.artefacts[0].generation_id == gid and again.units_to_bill == 0

    opts = store.load_title_set(tenant, gid).options
    res = ApprovalService(store, clock=CLOCK, accepted_row_kinds=frozenset({K.TEST_FIXTURE})).approve_title(actor, gid, option_id=opts[0].id)
    assert isinstance(res, Approved)

    pack = service([PACK]).generate_listing_copy(actor, intake("k2"), M.AMAZON, GroundingRequest(approval_id=res.approval_id))
    assert pack.artefacts[0].status is GenerationStatus.COMPLETE
    with tenant_scope(tenant) as conn:
        row = conn.execute(text("SELECT grounding_basis, grounding_approval_id, format_constraint_ref, input_mode FROM cmo_generation WHERE tenant_id=:t AND output_type='LISTING_COPY'"), {"t": tenant}).one()
    assert (row.grounding_basis, row.grounding_approval_id, row.format_constraint_ref, row.input_mode) == ("APPROVED_TITLE", res.approval_id, fixtures[M.AMAZON], "INDEPENDENT")


def test_failed_rows_persist_and_do_not_block_a_retry_but_a_second_complete_is_a_duplicate(migrate_engine, tenant, fixtures):
    actor = Actor(tenant, uuid.uuid4())
    bad = json.dumps({"titles": ["z" * 300]})
    first = service([bad, bad]).generate_title_sets(actor, intake("kf"), [M.AMAZON])
    assert first.artefacts[0].status is GenerationStatus.FAILED
    ok = service([json.dumps({"titles": TITLES})]).generate_title_sets(actor, intake("kf"), [M.AMAZON])
    assert ok.artefacts[0].status is GenerationStatus.COMPLETE
    with tenant_scope(tenant) as conn:
        assert count(conn, "cmo_generation", tenant) == 2
    rec = GenerationRecord(O.HASHTAGS, None, None, GenerationStatus.COMPLETE, "dup", actor.user_id, None, "#a", {"hashtags": ["#a"]},
                           None, None, None, None, None)
    store = PostgresGenerationStore()
    store.save_generation(tenant, rec)
    with pytest.raises(DuplicateArtefact):
        store.save_generation(tenant, rec)
    with tenant_scope(tenant) as conn:
        assert conn.execute(text("SELECT count(*) FROM cmo_generation WHERE tenant_id=:t AND request_key='dup'"), {"t": tenant}).scalar_one() == 1


def test_facts_are_stored_per_exact_sku_and_target_price_is_integer_paise(tenant):
    actor = Actor(tenant, uuid.uuid4())
    store = PostgresGenerationStore()
    store.save_facts(tenant, actor.user_id, [NewFact(F.ATTRIBUTE, "S1", "material", "steel"), NewFact(F.TARGET_PRICE, "S1", None, None, 49900),
                                             NewFact(F.BRAND, None, None, "NoSku")])
    loaded = store.load_facts(tenant, "S1")
    assert {(f.fact_type, f.value) for f in loaded} == {(F.ATTRIBUTE, "steel"), (F.TARGET_PRICE, None)}
    assert store.load_facts(tenant, "S2") == [] and store.load_facts(tenant, None) == []
    with tenant_scope(tenant) as conn:
        assert conn.execute(text("SELECT value_paise FROM seller_fact WHERE tenant_id=:t AND fact_type='TARGET_PRICE'"), {"t": tenant}).scalar_one() == 49900


def test_cross_tenant_ids_are_invisible_and_cannot_be_referenced(migrate_engine, tenant, fixtures):
    actor = Actor(tenant, uuid.uuid4())
    store = PostgresGenerationStore()
    run = service([json.dumps({"titles": TITLES})]).generate_title_sets(actor, intake("kx"), [M.AMAZON])
    gid = run.artefacts[0].generation_id
    opt = store.load_title_set(tenant, gid).options[0]
    approval = ApprovalService(store, clock=CLOCK, accepted_row_kinds=frozenset({K.TEST_FIXTURE})).approve_title(actor, gid, option_id=opt.id)
    intruder = uuid.uuid4()
    assert store.load_title_set(intruder, gid) is None and store.load_approval(intruder, approval.approval_id) is None
    assert list(store.find_artefacts(intruder, "kx")) == [] and store.load_facts(intruder, "SKU1") == []
    with pytest.raises(IntegrityError):  # composite FK: an approval cannot point at another tenant's generation
        store.save_approval(intruder, generation_id=gid, option_id=opt.id, approved_text="x", edited_by_seller=False, approved_by=uuid.uuid4())


def test_simultaneous_identical_requests_leave_exactly_one_complete_row(migrate_engine, tenant, fixtures):
    actor = Actor(tenant, uuid.uuid4())
    results: list = []

    def go():
        results.append(service([json.dumps({"titles": TITLES})]).generate_title_sets(actor, intake("race"), [M.AMAZON]))

    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with tenant_scope(tenant) as conn:
        n = conn.execute(text("SELECT count(*) FROM cmo_generation WHERE tenant_id=:t AND request_key='race' AND status='COMPLETE'"), {"t": tenant}).scalar_one()
        assert n == 1
    assert sum(r.units_to_bill for r in results) == 1 and len({r.artefacts[0].generation_id for r in results}) == 1
