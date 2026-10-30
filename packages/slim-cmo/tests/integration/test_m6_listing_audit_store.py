"""CMO 3.0 M6 on a real Postgres (migration 20261030_0007; acceptance N-05m, N-05v, N-14a, N-15f, N-05r, R-12, R-16): the widened constraint-reference check (verified vs unverified basis, present vs NULL
reference, malformed / missing / NULL output_structured), the listing-audit table (RLS, grants, foreign key, idempotency, no score column), and the migration round trip with rows present."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from slim_cmo.listing import audit
from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.service.errors import NotFound
from slim_cmo.service.listing_audit import ListingAuditStore
from slim_cmo.service.models import Actor

from . import _seed
from .test_schema_constraints import _constraint, _violates

PACK = dict(output_type="LISTING_COPY", marketplace="AMAZON", grounding_basis="SELLER_SUPPLIED_TITLE")
HASH_A, HASH_B = "a" * 64, "b" * 64
RESULT = {"verdict": audit.CHECKED_NOT_VERIFIED, "method": "listing-audit-v1", "checks": [{"id": "A01", "status": "PASS"}], "findings": [], "measured": {"title": {"codePoints": 5}}}


def pack(tenant, structured, **kw):
    return _seed.insert_generation(tenant, output_structured=structured, **{**PACK, **kw})


# ---------------------------------------------------------------- the widened constraint-reference check
def test_an_unverified_basis_artefact_may_omit_the_constraint_reference(two_tenants):
    tenant, _ = two_tenants
    assert pack(tenant, {"rules_basis": "UNVERIFIED", "bullets": ["a"]})
    assert _seed.insert_generation(tenant, output_type="TITLE_SET", marketplace="AMAZON", output_structured={"rules_basis": "UNVERIFIED", "workflow": "FULL_LISTING"})
    assert _seed.insert_generation(tenant, output_type="BACKEND_TERMS", marketplace="AMAZON", grounding_basis="SELLER_SUPPLIED_TITLE", output_structured={"rules_basis": "UNVERIFIED"})


@pytest.mark.parametrize("structured", [
    {"rules_basis": "VERIFIED"},  # a verified-basis artefact must cite its row
    {"delivered": True},  # no basis recorded: every pre-M6 row
    {},
    {"rules_basis": "unverified"}, {"rules_basis": " UNVERIFIED"}, {"rules_basis": "UNVERIFIED "}, {"rules_basis": None}, {"rules_basis": ["UNVERIFIED"]}, {"rules_basis": {"v": "UNVERIFIED"}},
    {"rules_basis": 1}, {"RULES_BASIS": "UNVERIFIED"}, {"nested": {"rules_basis": "UNVERIFIED"}},
    ["rules_basis", "UNVERIFIED"],  # a JSON array
    "UNVERIFIED",  # a JSON string
    123, True,  # JSON scalars
])
def test_anything_but_the_exact_server_marker_still_requires_the_reference(two_tenants, structured):
    tenant, _ = two_tenants
    _violates(lambda: pack(tenant, structured))


def test_a_null_output_structured_cannot_open_the_exception(two_tenants):
    tenant, _ = two_tenants
    _violates(lambda: pack(tenant, None, output_text="some text"))  # COMPLETE with text only and no reference
    assert pack(tenant, None, output_text="x", status="FAILED", failure_reason="why")  # a FAILED row never needed one


def test_a_verified_basis_artefact_with_its_reference_is_accepted_and_failed_rows_never_needed_one(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    ref = _constraint(migrate_engine)
    assert pack(tenant, {"rules_basis": "VERIFIED"}, format_constraint_ref=ref)
    assert pack(tenant, {"rules_basis": "UNVERIFIED"}, format_constraint_ref=ref)  # citing a row is always allowed
    assert pack(tenant, {"x": 1}, status="FAILED")


def test_other_output_types_are_untouched_by_the_exception(two_tenants):
    tenant, _ = two_tenants
    assert _seed.insert_generation(tenant, output_type="HASHTAGS", marketplace=None)


# ---------------------------------------------------------------- the audit table
def actor_for(tenant):
    return Actor(tenant, uuid.uuid4())


def test_saving_an_audit_is_idempotent_per_version_and_each_version_keeps_its_own(two_tenants):
    tenant, _ = two_tenants
    gid = pack(tenant, {"rules_basis": "UNVERIFIED"})
    store, a = ListingAuditStore(), actor_for(tenant)
    first = store.save(a, generation_id=gid, marketplace="AMAZON", content_hash=HASH_A, rules_basis="UNVERIFIED", result=RESULT, keyword_map={"candidates": []})
    again = store.save(a, generation_id=gid, marketplace="AMAZON", content_hash=HASH_A, rules_basis="UNVERIFIED", result={**RESULT, "verdict": audit.BLOCKED}, keyword_map={"candidates": []})
    assert first["reused"] is False and again["reused"] is True and again["auditId"] == first["auditId"] and again["verdict"] == audit.CHECKED_NOT_VERIFIED  # the first answer stands
    other = store.save(a, generation_id=gid, marketplace="AMAZON", content_hash=HASH_B, rules_basis="UNVERIFIED", result={**RESULT, "verdict": audit.BLOCKED}, keyword_map={})
    assert other["reused"] is False and other["auditId"] != first["auditId"]
    assert store.latest(tenant, gid)["contentHash"] == HASH_B
    assert first["checks"][0]["id"] == "A01" and first["measured"]["title"]["codePoints"] == 5


def test_another_tenants_pack_looks_exactly_like_a_missing_one(two_tenants):
    a_t, b_t = two_tenants
    gid_b = pack(b_t, {"rules_basis": "UNVERIFIED"})
    with pytest.raises(NotFound):
        ListingAuditStore().save(actor_for(a_t), generation_id=gid_b, marketplace="AMAZON", content_hash=HASH_A, rules_basis="UNVERIFIED", result=RESULT, keyword_map={})
    with pytest.raises(NotFound):
        ListingAuditStore().save(actor_for(a_t), generation_id=uuid.uuid4(), marketplace="AMAZON", content_hash=HASH_A, rules_basis="UNVERIFIED", result=RESULT, keyword_map={})


def test_tenant_b_cannot_read_tenant_a_audits(two_tenants):
    a_t, b_t = two_tenants
    gid = pack(a_t, {"rules_basis": "UNVERIFIED"})
    ListingAuditStore().save(actor_for(a_t), generation_id=gid, marketplace="AMAZON", content_hash=HASH_A, rules_basis="UNVERIFIED", result=RESULT, keyword_map={})
    assert ListingAuditStore().latest(a_t, gid) is not None
    assert ListingAuditStore().latest(b_t, gid) is None  # RLS hides it; the same id under B's tenant is empty
    with tenant_scope(b_t) as conn:
        assert conn.execute(text("SELECT count(*) FROM cmo_listing_audit")).scalar() == 0


def test_the_application_role_can_only_insert_and_select(two_tenants):
    tenant, _ = two_tenants
    gid = pack(tenant, {"rules_basis": "UNVERIFIED"})
    ListingAuditStore().save(actor_for(tenant), generation_id=gid, marketplace="AMAZON", content_hash=HASH_A, rules_basis="UNVERIFIED", result=RESULT, keyword_map={})
    for stmt in ("UPDATE cmo_listing_audit SET verdict = 'BLOCKED'", "DELETE FROM cmo_listing_audit", "TRUNCATE cmo_listing_audit"):
        with pytest.raises((ProgrammingError, DBAPIError)):
            with tenant_scope(tenant) as conn:
                conn.execute(text(stmt))
    assert ListingAuditStore().latest(tenant, gid)["verdict"] == audit.CHECKED_NOT_VERIFIED


@pytest.mark.parametrize("col,val", [("verdict", "READY"), ("verdict", "COMPLIANT"), ("rules_basis", "unverified"), ("rules_basis", "NONE"), ("content_hash", "short"), ("marketplace", "EBAY"),
                                     ("method_version", "   ")])
def test_check_constraints_reject_invalid_values(two_tenants, col, val):
    tenant, _ = two_tenants
    gid = pack(tenant, {"rules_basis": "UNVERIFIED"})
    row = dict(t=tenant, g=gid, mp="AMAZON", h=HASH_A, rb="UNVERIFIED", v="NEEDS_ATTENTION", m="listing-audit-v1")
    key = {"verdict": "v", "rules_basis": "rb", "content_hash": "h", "marketplace": "mp", "method_version": "m"}[col]
    row[key] = val

    def go():
        with tenant_scope(tenant) as conn:
            conn.execute(text(
                "INSERT INTO cmo_listing_audit (tenant_id, generation_id, marketplace, content_hash, rules_basis, verdict, method_version, checks, findings, keyword_map, measured, created_by) "
                "VALUES (:t, :g, :mp, :h, :rb, :v, :m, '[]', '[]', '{}', '{}', :u)"), {**row, "u": uuid.uuid4()})

    _violates(go)


def test_no_score_volume_demand_rank_or_conversion_column_exists_and_rls_is_forced(migrate_engine):
    with migrate_engine.connect() as conn:
        cols = {r[0] for r in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'cmo_listing_audit'"))}
        flags = conn.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'cmo_listing_audit'")).one()
    assert flags == (True, True)
    assert not any(w in c for c in cols for w in ("score", "volume", "demand", "rank", "conversion", "sales", "compliant", "ready"))
    assert {"tenant_id", "generation_id", "content_hash", "verdict", "checks", "findings", "keyword_map", "measured"} <= cols


# ---------------------------------------------------------------- migration round trip with rows present (scratch database only)
_PKG = Path(__file__).resolve().parents[2]


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=_PKG, env=env, capture_output=True, text=True, timeout=180)


def _heads(migrate_engine) -> str:
    with migrate_engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version_slim_cmo")).scalar_one()


def test_downgrade_refuses_while_unverified_packs_exist_then_round_trips_and_keeps_every_row(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    ref = _constraint(migrate_engine)
    verified = pack(tenant, {"rules_basis": "VERIFIED", "n": 1}, format_constraint_ref=ref)
    unverified = pack(tenant, {"rules_basis": "UNVERIFIED", "n": 2})
    refused = _alembic("downgrade", "20261030_0006")
    assert refused.returncode != 0 and "unverified-basis artefacts exist" in (refused.stderr + refused.stdout)
    assert _heads(migrate_engine) == "20261030_0007"  # nothing was half-applied
    with migrate_engine.begin() as conn:  # the test (not the migration) removes its own unverified row
        conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
        conn.execute(text("DELETE FROM cmo_generation WHERE id = :i"), {"i": str(unverified)})
    down = _alembic("downgrade", "20261030_0006")
    assert down.returncode == 0, down.stderr
    try:
        assert _heads(migrate_engine) == "20261030_0006"
        with migrate_engine.connect() as conn:
            assert conn.execute(text("SELECT to_regclass('cmo_listing_audit')")).scalar() is None
        _violates(lambda: pack(tenant, {"rules_basis": "UNVERIFIED"}))  # the strict check is back: no unverified exception any more
        with tenant_scope(tenant) as conn:
            assert conn.execute(text("SELECT count(*) FROM cmo_generation WHERE id = :i"), {"i": str(verified)}).scalar() == 1  # the existing row survived
    finally:
        up = _alembic("upgrade", "head")
        assert up.returncode == 0, up.stderr
    assert _heads(migrate_engine) == "20261030_0007"
    assert pack(tenant, {"rules_basis": "UNVERIFIED"})  # re-upgraded: the exception works again
    with tenant_scope(tenant) as conn:
        assert conn.execute(text("SELECT count(*) FROM cmo_generation WHERE id = :i"), {"i": str(verified)}).scalar() == 1
