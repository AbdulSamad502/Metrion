"""P4 persistence against a real Postgres (skipped automatically without DATABASE_URL / DATABASE_URL_APP)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from slim_cmo.catalog.attributes import CatalogAttribute as C
from slim_cmo.repositories.postgres_store import PostgresGenerationStore
from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.service.catalog import CatalogRequest, CatalogService
from slim_cmo.service.errors import NotFound
from slim_cmo.service.generate import Intake
from slim_cmo.service.models import Actor
from slim_cmo.types import GenerationStatus, Marketplace as M

from ._seed import insert_analysis, insert_asset

HINT = [{"name": "color", "value": "matte blue", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}]


def service():
    return CatalogService(PostgresGenerationStore())


def req(key, *questions, marketplaces=(), **intake):
    return CatalogRequest(Intake(request_key=key, sku="SKU1", **intake), tuple(questions), tuple(marketplaces))


def test_a_catalog_answer_row_passes_the_database_checks_and_is_idempotent():
    tenant = uuid.uuid4()
    actor = Actor(tenant, uuid.uuid4())
    run = service().answer(actor, req("c1", C.MATERIAL, C.WEIGHT, attributes=(("material", "steel"),)))
    assert run.units_to_bill == 1 and run.artefacts[0].status is GenerationStatus.COMPLETE
    again = service().answer(actor, req("c1", C.MATERIAL, C.WEIGHT, attributes=(("material", "steel"),)))
    assert again.artefacts[0].reused and again.units_to_bill == 0 and again.artefacts[0].generation_id == run.artefacts[0].generation_id
    with tenant_scope(tenant) as conn:
        row = conn.execute(text("SELECT marketplace, format_constraint_ref, grounding_basis, status, output_structured FROM cmo_generation "
                                "WHERE tenant_id=:t AND output_type='CATALOG_ANSWER'"), {"t": tenant}).one()
    assert (row.marketplace, row.format_constraint_ref, row.grounding_basis, row.status) == (None, None, None, "COMPLETE")
    assert {a["attribute"]: a["basis"] for a in row.output_structured["attributes"]} == {"MATERIAL": "SELLER_PROVIDED", "WEIGHT": "UNKNOWN"}


def test_one_artefact_per_marketplace_answered():
    tenant = uuid.uuid4()
    run = service().answer(Actor(tenant, uuid.uuid4()), req("c2", C.CATEGORY, marketplaces=[M.AMAZON, M.MEESHO]))
    assert run.units_to_bill == 2
    with tenant_scope(tenant) as conn:
        got = conn.execute(text("SELECT marketplace FROM cmo_generation WHERE tenant_id=:t ORDER BY marketplace"), {"t": tenant}).scalars().all()
    assert got == ["AMAZON", "MEESHO"]


def test_confirming_a_hint_inserts_a_seller_fact_linked_to_the_analysis_and_changes_nothing_else():
    tenant = uuid.uuid4()
    actor = Actor(tenant, uuid.uuid4())
    asset = insert_asset(tenant)
    analysis = insert_analysis(tenant, asset, attributes=HINT)

    def snapshot():
        with tenant_scope(tenant) as conn:
            return conn.execute(text("SELECT attributes, eval_gate_ref, analysis_state, provider, model FROM product_image_analysis WHERE tenant_id=:t AND id=:i"),
                                {"t": tenant, "i": analysis}).one()

    before = snapshot()
    res = service().confirm_image_hint(actor, analysis_id=analysis, attribute_name="color", sku="SKU1")
    assert res.created
    assert tuple(snapshot()) == tuple(before)  # the analysis row is byte-for-byte unchanged; the hint is still UNVERIFIED_HINT
    with tenant_scope(tenant) as conn:
        fact = conn.execute(text("SELECT fact_type, attribute_name, fact_value, image_analysis_id, sku FROM seller_fact WHERE tenant_id=:t"), {"t": tenant}).one()
        assert conn.execute(text("SELECT count(*) FROM cmo_generation WHERE tenant_id=:t"), {"t": tenant}).scalar_one() == 0  # zero units
    assert tuple(fact) == ("ATTRIBUTE", "color", "matte blue", analysis, "SKU1")
    assert not service().confirm_image_hint(actor, analysis_id=analysis, attribute_name="color", sku="SKU1").created  # idempotent

    out = service().answer(actor, req("c3", C.COLOR, image_analysis_id=analysis))
    with tenant_scope(tenant) as conn:
        structured = conn.execute(text("SELECT output_structured FROM cmo_generation WHERE tenant_id=:t AND id=:i"), {"t": tenant, "i": out.artefacts[0].generation_id}).scalar_one()
    color = structured["attributes"][0]
    assert (color["basis"], color["value"], color["claim_eligible"]) == ("SELLER_PROVIDED", "matte blue", True)


def test_cross_tenant_analysis_ids_are_not_found_and_cannot_be_referenced():
    a, b = uuid.uuid4(), uuid.uuid4()
    analysis = insert_analysis(a, insert_asset(a), attributes=HINT)
    actor_b = Actor(b, uuid.uuid4())
    with pytest.raises(NotFound):
        service().confirm_image_hint(actor_b, analysis_id=analysis, attribute_name="color", sku="SKU1")
    with pytest.raises(NotFound):
        service().answer(actor_b, req("x1", C.COLOR, image_analysis_id=analysis))
    with pytest.raises(IntegrityError):  # the composite FK refuses another tenant's analysis even for a hand-written insert
        with tenant_scope(b) as conn:
            conn.execute(text("INSERT INTO seller_fact (tenant_id, fact_type, fact_value, image_analysis_id, provided_by) "
                              "VALUES (:t, 'ATTRIBUTE', 'x', :a, :u)"), {"t": b, "a": analysis, "u": uuid.uuid4()})
    with tenant_scope(b) as conn:
        assert conn.execute(text("SELECT count(*) FROM cmo_generation WHERE tenant_id=:t"), {"t": b}).scalar_one() == 0
