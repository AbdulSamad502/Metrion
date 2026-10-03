"""Database-level guarantees of the slim-cmo schema (spec §5, AC5/AC7/AC8/AC10/AC12/AC15/AC19/
AC20/AC24). Every test exercises a real constraint on a real Postgres as `metrion_app`.

Sections: enum/CHECK drift against `slim_cmo.types` · generation invariants · idempotency ·
grounding & approval · cross-tenant composite FKs · vision trust gate · seller_fact money rule ·
niche terms · trend report · format_constraint · asset · grants (append-only provenance).
"""

from __future__ import annotations

import re
import uuid
from enum import Enum

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.types import (
    CONSTRAINT_BOUND_OUTPUT_TYPES,
    GROUNDED_OUTPUT_TYPES,
    MARKETPLACE_SCOPED_OUTPUT_TYPES,
    AttributeBasis,
    ConstraintRowKind,
    CountRule,
    GenerationStatus,
    GroundingBasis,
    ImageAnalysisState,
    ImageAssetStatus,
    InputMode,
    Marketplace,
    NicheTermOrigin,
    NicheTermStatus,
    OutputType,
    SellerFactType,
    TrendSection,
    TrustState,
)

from . import _seed

_version = [100]


def _v() -> int:
    _version[0] += 1
    return _version[0]


def _constraint(migrate_engine, marketplace="AMAZON") -> uuid.UUID:
    return _seed.insert_format_constraint(migrate_engine, marketplace=marketplace, version=_v())


# ---------------------------------------------------------------------------------------------
# Enum <-> CHECK drift: types.py and the migration must agree value-for-value.
# ---------------------------------------------------------------------------------------------

_DOMAIN_CHECKS: list[tuple[str, str, type[Enum]]] = [
    ("cmo_generation", "marketplace", Marketplace),
    ("cmo_generation", "output_type", OutputType),
    ("cmo_generation", "input_mode", InputMode),
    ("cmo_generation", "status", GenerationStatus),
    ("cmo_generation", "grounding_basis", GroundingBasis),
    ("format_constraint", "marketplace", Marketplace),
    ("format_constraint", "row_kind", ConstraintRowKind),
    ("format_constraint", "count_rule", CountRule),
    ("seller_image_asset", "status", ImageAssetStatus),
    ("product_image_analysis", "analysis_state", ImageAnalysisState),
    ("seller_fact", "fact_type", SellerFactType),
    ("cmo_niche_term", "origin", NicheTermOrigin),
    ("cmo_niche_term", "status", NicheTermStatus),
    ("cmo_trend_report", "sections_requested", TrendSection),
]


def _domain_literals(defn: str, column: str) -> set[str] | None:
    """The value list of a `<column> = ANY (ARRAY[...])` / `<column> <@ ARRAY[...]` domain check,
    or None if this constraint is not a domain check for that column."""
    match = re.search(rf"(?<![A-Za-z_]){column}(?![A-Za-z_])\)?(?:::text)?\s*(?:=\s*ANY\s*\(\s*ARRAY|<@\s*ARRAY)\[(.*?)\]", defn)
    return set(re.findall(r"'([A-Z][A-Z0-9_]+)'", match.group(1))) if match else None


@pytest.mark.parametrize("table,column,enum", _DOMAIN_CHECKS, ids=lambda v: getattr(v, "__name__", str(v)))
def test_enum_values_match_check_constraint(migrate_engine, table, column, enum):
    with migrate_engine.connect() as conn:
        defs = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname = :t AND c.contype = 'c'"
                ),
                {"t": table},
            )
        ]
    domains = [lit for d in defs if (lit := _domain_literals(d, column)) is not None]
    assert len(domains) == 1, f"expected exactly one domain CHECK for {table}.{column}, found {len(domains)}"
    assert domains[0] == {e.value for e in enum}, f"{table}.{column}: DB {sorted(domains[0])} != enum"


def test_vision_attribute_checks_agree_with_enums(migrate_engine):
    with migrate_engine.connect() as conn:
        defs = " ".join(
            r[0]
            for r in conn.execute(
                text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname = 'product_image_analysis' AND c.contype = 'c'"
                )
            )
        )
    literals = set(re.findall(r'"([A-Z][A-Z0-9_]+)"', defs.replace("\\\"", '"')))
    # vision may emit only these two bases ...
    assert {AttributeBasis.IMAGE_OBSERVED.value, AttributeBasis.UNKNOWN.value} <= literals
    assert literals - {t.value for t in TrustState} - {b.value for b in AttributeBasis} == set()
    # ... and both trust states are named
    assert {t.value for t in TrustState} <= literals


# ---------------------------------------------------------------------------------------------
# cmo_generation invariants
# ---------------------------------------------------------------------------------------------


def _violates(fn) -> None:
    with pytest.raises((IntegrityError, DBAPIError)):
        fn()


def test_marketplace_required_exactly_for_marketplace_scoped_types(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    constraint = _constraint(migrate_engine)
    for output_type in OutputType:
        if output_type is OutputType.BACKEND_TERMS:
            continue  # separately covered (Amazon-only)
        common = dict(output_type=output_type.value, marketplace=None, format_constraint_ref=constraint)
        if output_type in GROUNDED_OUTPUT_TYPES:
            common.update(grounding_basis="SELLER_SUPPLIED_TITLE")
        if output_type in MARKETPLACE_SCOPED_OUTPUT_TYPES:
            _violates(lambda c=common: _seed.insert_generation(tenant, **c))
        else:
            _seed.insert_generation(tenant, **common)  # accepted without a marketplace


def test_backend_terms_are_amazon_only(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    constraint = _constraint(migrate_engine)
    kw = dict(output_type="BACKEND_TERMS", format_constraint_ref=constraint, grounding_basis="SELLER_SUPPLIED_TITLE")
    _violates(lambda: _seed.insert_generation(tenant, marketplace="FLIPKART", **kw))
    _violates(lambda: _seed.insert_generation(tenant, marketplace="MEESHO", **kw))
    _seed.insert_generation(tenant, marketplace="AMAZON", **kw)


def test_constraint_ref_required_exactly_for_constraint_bound_types_when_complete(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    for output_type in OutputType:
        marketplace = "AMAZON" if output_type in MARKETPLACE_SCOPED_OUTPUT_TYPES else None
        kw = dict(output_type=output_type.value, marketplace=marketplace)
        if output_type in GROUNDED_OUTPUT_TYPES:
            kw.update(grounding_basis="SELLER_SUPPLIED_TITLE")
        if output_type in CONSTRAINT_BOUND_OUTPUT_TYPES:
            _violates(lambda k=kw: _seed.insert_generation(tenant, **k))
            # a FAILED attempt never reached the point of citing a rule, so it may omit it (E5)
            _seed.insert_generation(tenant, status="FAILED", **kw)
        else:
            _seed.insert_generation(tenant, **kw)


def test_grounded_types_must_cite_their_anchor_when_complete(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    constraint = _constraint(migrate_engine)
    for output_type in GROUNDED_OUTPUT_TYPES:
        kw = dict(output_type=output_type.value, marketplace="AMAZON", format_constraint_ref=constraint)
        _violates(lambda k=kw: _seed.insert_generation(tenant, **k))  # no grounding_basis
        _seed.insert_generation(tenant, grounding_basis="SELLER_SUPPLIED_TITLE", **kw)
        _seed.insert_generation(tenant, status="FAILED", **kw)  # a failed attempt may lack one


def test_billable_units_is_always_one(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    constraint = _constraint(migrate_engine)
    for bad in (0, 2, 3):
        _violates(lambda b=bad: _seed.insert_generation(tenant, format_constraint_ref=constraint, billable_units=b))


def test_ci_snapshot_and_input_mode_travel_together(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    constraint = _constraint(migrate_engine)
    base = dict(format_constraint_ref=constraint)
    _violates(lambda: _seed.insert_generation(tenant, input_mode="CEO_BROKERED_CI", **base))
    _violates(lambda: _seed.insert_generation(tenant, input_mode="INDEPENDENT", ci_inputs_snapshot={"x": 1}, **base))
    _seed.insert_generation(tenant, input_mode="CEO_BROKERED_CI", ci_inputs_snapshot={"insight_ids": []}, **base)
    _seed.insert_generation(tenant, input_mode="INDEPENDENT", **base)


def test_failed_rows_need_a_real_reason_and_complete_rows_need_output(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    constraint = _constraint(migrate_engine)
    _violates(lambda: _seed.insert_generation(tenant, status="FAILED", failure_reason=""))
    _violates(lambda: _seed.insert_generation(tenant, status="FAILED", failure_reason="   "))
    _violates(lambda: _seed.insert_generation(tenant, format_constraint_ref=constraint, allow_empty_output=True))
    _seed.insert_generation(tenant, status="FAILED", failure_reason="constraint stale")


def test_invalid_enum_values_are_rejected(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    constraint = _constraint(migrate_engine)
    _violates(lambda: _seed.insert_generation(tenant, output_type="GST_ANSWER", marketplace=None))
    _violates(lambda: _seed.insert_generation(tenant, marketplace="MYNTRA", format_constraint_ref=constraint))
    _violates(lambda: _seed.insert_generation(tenant, status="PARTIAL", format_constraint_ref=constraint))


# ---------------------------------------------------------------------------------------------
# Idempotency (AC15)
# ---------------------------------------------------------------------------------------------


def test_complete_artefact_is_unique_per_request_key_type_and_marketplace(two_tenants, migrate_engine):
    tenant, other = two_tenants
    constraint = _constraint(migrate_engine)
    kw = dict(request_key="req-1", format_constraint_ref=constraint)
    _seed.insert_generation(tenant, marketplace="AMAZON", **kw)
    _violates(lambda: _seed.insert_generation(tenant, marketplace="AMAZON", **kw))  # duplicate
    _seed.insert_generation(tenant, marketplace="FLIPKART", **kw)  # other marketplace, same request: fine
    _seed.insert_generation(other, marketplace="AMAZON", **kw)  # other tenant, same key: fine


def test_failed_attempts_do_not_block_a_retry_under_the_same_key(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    constraint = _constraint(migrate_engine)
    kw = dict(request_key="req-retry", marketplace="AMAZON", format_constraint_ref=constraint)
    _seed.insert_generation(tenant, status="FAILED", **kw)
    _seed.insert_generation(tenant, status="FAILED", **kw)  # a second failed attempt
    _seed.insert_generation(tenant, status="COMPLETE", **kw)  # the retry succeeds
    _violates(lambda: _seed.insert_generation(tenant, status="COMPLETE", **kw))


def test_null_marketplace_artefacts_are_still_idempotent(two_tenants):
    tenant, _ = two_tenants
    kw = dict(output_type="HASHTAGS", marketplace=None, request_key="req-tags")
    _seed.insert_generation(tenant, **kw)
    _violates(lambda: _seed.insert_generation(tenant, **kw))  # NULLS NOT DISTINCT


# ---------------------------------------------------------------------------------------------
# Grounding & approval (AC10, AC11)
# ---------------------------------------------------------------------------------------------


def _title_set_with_option(tenant, migrate_engine):
    constraint = _constraint(migrate_engine)
    generation = _seed.insert_generation(tenant, output_type="TITLE_SET", format_constraint_ref=constraint)
    option = _seed.insert_option(tenant, generation)
    return constraint, generation, option


def test_approved_title_grounding_requires_an_approval_and_vice_versa(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    constraint, generation, option = _title_set_with_option(tenant, migrate_engine)
    approval = _seed.insert_approval(tenant, generation, option_id=option)
    base = dict(output_type="LISTING_COPY", marketplace="AMAZON", format_constraint_ref=constraint)

    _seed.insert_generation(tenant, grounding_basis="APPROVED_TITLE", grounding_approval_id=approval, **base)
    _violates(lambda: _seed.insert_generation(tenant, grounding_basis="APPROVED_TITLE", **base))
    _violates(lambda: _seed.insert_generation(tenant, grounding_approval_id=approval, **base))
    _violates(
        lambda: _seed.insert_generation(
            tenant, grounding_basis="SELLER_SUPPLIED_TITLE", grounding_approval_id=approval, **base
        )
    )


def test_approval_edit_flag_agrees_with_option_id(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    _, generation, option = _title_set_with_option(tenant, migrate_engine)
    _violates(lambda: _seed.insert_approval(tenant, generation, option_id=option, edited_by_seller=True))
    _violates(lambda: _seed.insert_approval(tenant, generation, option_id=None, edited_by_seller=False))
    _seed.insert_approval(tenant, generation, option_id=None, edited_by_seller=True, approved_text="seller's own")
    _seed.insert_approval(tenant, generation, option_id=option, edited_by_seller=False)


def test_approval_option_must_belong_to_the_approved_generation(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    _, gen_a, _ = _title_set_with_option(tenant, migrate_engine)
    _, gen_b, option_b = _title_set_with_option(tenant, migrate_engine)
    _violates(lambda: _seed.insert_approval(tenant, gen_a, option_id=option_b))  # option from a different set


def test_title_option_rank_is_positive_and_unique_per_set(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    _, generation, _ = _title_set_with_option(tenant, migrate_engine)
    _violates(lambda: _seed.insert_option(tenant, generation, rank=1))  # rank 1 already used
    _violates(lambda: _seed.insert_option(tenant, generation, rank=0))
    _seed.insert_option(tenant, generation, rank=2)


# ---------------------------------------------------------------------------------------------
# Cross-tenant composite foreign keys: a row cannot reference another tenant's row.
# (RI checks bypass RLS, so a plain id FK would NOT stop this — the composite FK does.)
# ---------------------------------------------------------------------------------------------


def test_generation_cannot_reference_another_tenants_analysis(two_tenants, migrate_engine):
    tenant_a, tenant_b = two_tenants
    analysis_a = _seed.insert_analysis(tenant_a, _seed.insert_asset(tenant_a))
    constraint = _constraint(migrate_engine)
    _violates(lambda: _seed.insert_generation(tenant_b, format_constraint_ref=constraint, image_analysis_id=analysis_a))


def test_analysis_cannot_reference_another_tenants_asset(two_tenants):
    tenant_a, tenant_b = two_tenants
    asset_a = _seed.insert_asset(tenant_a)
    _violates(lambda: _seed.insert_analysis(tenant_b, asset_a))


def test_approval_cannot_reference_another_tenants_generation_or_option(two_tenants, migrate_engine):
    tenant_a, tenant_b = two_tenants
    _, generation_a, option_a = _title_set_with_option(tenant_a, migrate_engine)
    _violates(lambda: _seed.insert_approval(tenant_b, generation_a, option_id=None))
    _violates(lambda: _seed.insert_approval(tenant_b, generation_a, option_id=option_a))


def test_fact_and_report_cannot_reference_another_tenants_generation(two_tenants, migrate_engine):
    tenant_a, tenant_b = two_tenants
    generation_a = _seed.insert_generation(tenant_a, output_type="TREND_REPORT", marketplace=None)
    _violates(lambda: _seed.insert_fact(tenant_b, cmo_generation_id=generation_a))
    _violates(lambda: _seed.insert_trend_report(tenant_b, generation_a))


def test_grounding_approval_cannot_belong_to_another_tenant(two_tenants, migrate_engine):
    tenant_a, tenant_b = two_tenants
    constraint, generation_a, option_a = _title_set_with_option(tenant_a, migrate_engine)
    approval_a = _seed.insert_approval(tenant_a, generation_a, option_id=option_a)
    _violates(
        lambda: _seed.insert_generation(
            tenant_b,
            output_type="LISTING_COPY",
            marketplace="AMAZON",
            format_constraint_ref=constraint,
            grounding_basis="APPROVED_TITLE",
            grounding_approval_id=approval_a,
        )
    )


# ---------------------------------------------------------------------------------------------
# Vision trust gate (AC20, spec §6.2.1) — enforced by the database, not just by application code
# ---------------------------------------------------------------------------------------------


def _hint(basis="IMAGE_OBSERVED", trust="UNVERIFIED_HINT", **extra):
    return {"name": "color", "value": "blue", "basis": basis, "trust_state": trust, **extra}


def test_gate_closed_analysis_accepts_only_unverified_hints(two_tenants):
    tenant, _ = two_tenants
    asset = _seed.insert_asset(tenant)
    _seed.insert_analysis(tenant, asset, attributes=[_hint(), _hint(basis="UNKNOWN")])
    _violates(lambda: _seed.insert_analysis(tenant, asset, attributes=[_hint(trust="EVAL_PASSED")]))


@pytest.mark.parametrize("basis", ["SELLER_PROVIDED", "SOURCE_DERIVED", "ESTIMATED", "image_observed", ""])
def test_vision_may_only_emit_image_observed_or_unknown(two_tenants, basis):
    tenant, _ = two_tenants
    asset = _seed.insert_asset(tenant)
    _violates(lambda: _seed.insert_analysis(tenant, asset, attributes=[_hint(basis=basis)]))


def test_attribute_elements_must_name_basis_and_trust_state(two_tenants):
    tenant, _ = two_tenants
    asset = _seed.insert_asset(tenant)
    _violates(lambda: _seed.insert_analysis(tenant, asset, attributes=[{"name": "x", "value": "y", "trust_state": "UNVERIFIED_HINT"}]))
    _violates(lambda: _seed.insert_analysis(tenant, asset, attributes=[{"name": "x", "value": "y", "basis": "UNKNOWN"}]))
    _violates(lambda: _seed.insert_analysis(tenant, asset, attributes=[_hint(trust="TRUSTED")]))


def _attr(**kw):
    base = {"name": "w", "value": "1", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}
    base.update(kw)
    return base


# Regression for a defect found by independent P1 verification: the first (negative-form)
# trust-gate constraint accepted type-confused values - a list for `basis`, a bool for
# `trust_state` - because comparing them with a string is UNKNOWN in jsonpath, not true. The
# constraint is now a strict-mode positive allow-list; every payload below must be rejected.
_MALFORMED_ATTRIBUTE_PAYLOADS = {
    "string element": ["x"],
    "null element": [None],
    "number element": [1],
    "empty object": [{}],
    "nested array hiding a forbidden basis": [[_attr(basis="SELLER_PROVIDED")]],
    "nested array hiding EVAL_PASSED": [[_attr(trust_state="EVAL_PASSED")]],
    "nested array of otherwise-valid objects": [[_attr()]],
    "basis case variant": [_attr(basis="image_observed")],
    "basis trailing whitespace": [_attr(basis="IMAGE_OBSERVED ")],
    "trust_state trailing whitespace": [_attr(trust_state="EVAL_PASSED ")],
    "basis as a list (valid value inside)": [_attr(basis=["IMAGE_OBSERVED"])],
    "basis as a list (forbidden value inside)": [_attr(basis=["SELLER_PROVIDED"])],
    "basis as an object": [_attr(basis={"v": "IMAGE_OBSERVED"})],
    "basis null": [_attr(basis=None)],
    "basis number": [_attr(basis=1)],
    "trust_state as bool true": [_attr(trust_state=True)],
    "trust_state as bool false": [_attr(trust_state=False)],
    "trust_state as list": [_attr(trust_state=["UNVERIFIED_HINT"])],
    "trust_state null": [_attr(trust_state=None)],
    "trust_state missing": [{k: v for k, v in _attr().items() if k != "trust_state"}],
    "basis missing": [{k: v for k, v in _attr().items() if k != "basis"}],
    "name missing": [{k: v for k, v in _attr().items() if k != "name"}],
    "name not a string": [_attr(name=5)],
    "one good element plus one bad": [_attr(), _attr(basis="ESTIMATED")],
    "one good element plus one type-confused": [_attr(), _attr(trust_state=True)],
    "gate closed, EVAL_PASSED": [_attr(trust_state="EVAL_PASSED")],
}


@pytest.mark.parametrize("name", sorted(_MALFORMED_ATTRIBUTE_PAYLOADS))
def test_trust_gate_rejects_malformed_and_type_confused_payloads(two_tenants, name):
    tenant, _ = two_tenants
    asset = _seed.insert_asset(tenant)
    _violates(lambda: _seed.insert_analysis(tenant, asset, attributes=_MALFORMED_ATTRIBUTE_PAYLOADS[name]))


def test_trust_gate_still_accepts_well_formed_payloads(two_tenants):
    tenant, _ = two_tenants
    # One COMPLETE analysis per (asset, provider, model, schema_version) since P6's partial unique index, so each
    # well-formed payload goes on its own asset.
    _seed.insert_analysis(tenant, _seed.insert_asset(tenant), attributes=[])
    _seed.insert_analysis(tenant, _seed.insert_asset(tenant), attributes=[_attr(), _attr(basis="UNKNOWN", value=None)])
    _seed.insert_analysis(tenant, _seed.insert_asset(tenant), attributes=[_attr(value=12), _attr(value={"nested": True}, confidence="low")])  # extra keys are fine


def test_attributes_must_be_a_json_array(two_tenants):
    tenant, _ = two_tenants
    asset = _seed.insert_asset(tenant)
    _violates(lambda: _seed.insert_analysis(tenant, asset, attributes={"color": "blue"}))  # type: ignore[arg-type]


def test_eval_passed_requires_a_passing_matching_evaluation(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    asset = _seed.insert_asset(tenant)
    passing = _seed.insert_vision_eval_run(migrate_engine, provider="p", model="m", schema_version="v1", passed=True)
    failing = _seed.insert_vision_eval_run(migrate_engine, provider="p", model="m", schema_version="v1", passed=False)
    attrs = [_hint(trust="EVAL_PASSED")]
    kw = dict(provider="p", model="m", schema_version="v1")

    _seed.insert_analysis(tenant, asset, attributes=attrs, eval_gate_ref=passing, **kw)  # cleared
    _violates(lambda: _seed.insert_analysis(tenant, asset, attributes=attrs, eval_gate_ref=failing, **kw))  # run failed
    _violates(lambda: _seed.insert_analysis(tenant, asset, attributes=attrs, eval_gate_ref=passing, provider="p", model="OTHER", schema_version="v1"))
    _violates(lambda: _seed.insert_analysis(tenant, asset, attributes=attrs, eval_gate_ref=passing, provider="p", model="m", schema_version="v2"))
    _violates(lambda: _seed.insert_analysis(tenant, asset, attributes=attrs, eval_gate_ref=uuid.uuid4(), **kw))  # no such run


def test_degraded_or_failed_analysis_states_need_a_reason(two_tenants):
    tenant, _ = two_tenants
    asset = _seed.insert_asset(tenant)
    for state in ("DEGRADED", "FAILED"):
        _violates(lambda s=state: _seed.insert_analysis(tenant, asset, analysis_state=s, attributes=[]))
        _violates(lambda s=state: _seed.insert_analysis(tenant, asset, analysis_state=s, attributes=[], degraded_reason=" "))
        _seed.insert_analysis(tenant, asset, analysis_state=state, attributes=[], degraded_reason="model timed out")


# ---------------------------------------------------------------------------------------------
# seller_fact — the only money value CMO holds is TARGET_PRICE, in integer paise (C7)
# ---------------------------------------------------------------------------------------------


def test_target_price_is_paise_only_and_never_text(two_tenants):
    tenant, _ = two_tenants
    _seed.insert_fact(tenant, fact_type="TARGET_PRICE", fact_value=None, value_paise=49900)
    _violates(lambda: _seed.insert_fact(tenant, fact_type="TARGET_PRICE", fact_value="499", value_paise=49900))  # text copy of money
    _violates(lambda: _seed.insert_fact(tenant, fact_type="TARGET_PRICE", fact_value=None, value_paise=None))
    _violates(lambda: _seed.insert_fact(tenant, fact_type="TARGET_PRICE", fact_value=None, value_paise=-1))


@pytest.mark.parametrize("fact_type", ["CATEGORY", "BRAND", "ATTRIBUTE", "NICHE", "FREE_TEXT"])
def test_non_price_facts_carry_text_and_never_paise(two_tenants, fact_type):
    tenant, _ = two_tenants
    _seed.insert_fact(tenant, fact_type=fact_type, fact_value="something")
    _violates(lambda: _seed.insert_fact(tenant, fact_type=fact_type, fact_value="something", value_paise=100))
    _violates(lambda: _seed.insert_fact(tenant, fact_type=fact_type, fact_value=None))
    _violates(lambda: _seed.insert_fact(tenant, fact_type=fact_type, fact_value="   "))


def test_confirming_a_hint_writes_one_seller_fact_and_cannot_change_the_analysis(two_tenants):
    """cmo.confirm_image_hint: the seller's confirmation is a NEW SELLER_PROVIDED fact. The stored
    analysis keeps its UNVERIFIED_HINT attributes, and the application role cannot rewrite it - so
    no code path can 'upgrade' an image-derived attribute by confirming it."""
    tenant, _ = two_tenants
    analysis = _seed.insert_analysis(tenant, _seed.insert_asset(tenant))
    fact = _seed.insert_fact(tenant, image_analysis_id=analysis, fact_type="ATTRIBUTE", fact_value="matte blue")

    with tenant_scope(tenant) as conn:
        attrs = conn.execute(text("SELECT attributes FROM product_image_analysis WHERE id = :i"), {"i": str(analysis)}).scalar_one()
        facts = conn.execute(text("SELECT count(*) FROM seller_fact WHERE image_analysis_id = :i"), {"i": str(analysis)}).scalar_one()
    assert facts == 1 and fact
    assert [a["trust_state"] for a in attrs] == ["UNVERIFIED_HINT"]  # untouched by the confirmation

    for statement in (
        "UPDATE product_image_analysis SET attributes = '[]'::jsonb WHERE id = :i",
        "UPDATE product_image_analysis SET eval_gate_ref = NULL WHERE id = :i",
        "DELETE FROM product_image_analysis WHERE id = :i",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            with tenant_scope(tenant) as conn:
                conn.execute(text(statement), {"i": str(analysis)})


def test_fact_can_confirm_an_image_hint_without_a_generation(two_tenants):
    tenant, _ = two_tenants
    analysis = _seed.insert_analysis(tenant, _seed.insert_asset(tenant))
    _seed.insert_fact(tenant, image_analysis_id=analysis, fact_value="matte blue")


# ---------------------------------------------------------------------------------------------
# cmo_niche_term (C15)
# ---------------------------------------------------------------------------------------------


def test_only_confirmed_terms_carry_a_confirmer(two_tenants):
    tenant, _ = two_tenants
    _seed.insert_niche_term(tenant, status="CONFIRMED")
    _seed.insert_niche_term(tenant, status="SUGGESTED")
    _seed.insert_niche_term(tenant, status="REJECTED")
    _violates(lambda: _seed.insert_niche_term(tenant, status="CONFIRMED", confirmed=False))
    _violates(lambda: _seed.insert_niche_term(tenant, status="SUGGESTED", confirmed=True))
    _violates(lambda: _seed.insert_niche_term(tenant, status="REJECTED", confirmed=True))


def test_niche_terms_are_trimmed_unique_per_tenant(two_tenants):
    tenant, other = two_tenants
    _seed.insert_niche_term(tenant, term="steel bottle")
    _violates(lambda: _seed.insert_niche_term(tenant, term="steel bottle"))
    _seed.insert_niche_term(other, term="steel bottle")  # another tenant may hold the same term
    _violates(lambda: _seed.insert_niche_term(tenant, term=" padded "))
    _violates(lambda: _seed.insert_niche_term(tenant, term=""))
    _violates(lambda: _seed.insert_niche_term(tenant, term="x", origin="WEB_SEARCH"))


# ---------------------------------------------------------------------------------------------
# cmo_trend_report (§6.8)
# ---------------------------------------------------------------------------------------------


def test_trend_report_evidence_is_never_empty(two_tenants):
    tenant, _ = two_tenants
    generation = _seed.insert_generation(tenant, output_type="TREND_REPORT", marketplace=None)
    _violates(lambda: _seed.insert_trend_report(tenant, generation, evidence={}))
    _seed.insert_trend_report(tenant, generation, evidence={"gaps": ["no sales data"]})


def test_trend_report_sections_must_be_the_five_researched_sections(two_tenants):
    tenant, _ = two_tenants
    for i, bad in enumerate((["INTERPRETATION"], ["NICHE", "GOSSIP"], [])):
        generation = _seed.insert_generation(tenant, output_type="TREND_REPORT", marketplace=None, request_key=f"bad-{i}")
        _violates(lambda g=generation, b=bad: _seed.insert_trend_report(tenant, g, sections_requested=b))
    generation = _seed.insert_generation(tenant, output_type="TREND_REPORT", marketplace=None, request_key="ok")
    _seed.insert_trend_report(tenant, generation, sections_requested=[s.value for s in TrendSection])


def test_one_report_per_generation_and_outbound_queries_are_an_array(two_tenants):
    tenant, _ = two_tenants
    generation = _seed.insert_generation(tenant, output_type="TREND_REPORT", marketplace=None)
    _seed.insert_trend_report(tenant, generation, outbound_queries=[{"query": "steel bottle india", "section": "NICHE"}])
    _violates(lambda: _seed.insert_trend_report(tenant, generation))
    other_gen = _seed.insert_generation(tenant, output_type="TREND_REPORT", marketplace=None, request_key="r2")
    _violates(lambda: _seed.insert_trend_report(tenant, other_gen, outbound_queries={"query": "x"}))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# format_constraint (§6.3, C13) and platform tables
# ---------------------------------------------------------------------------------------------


def test_format_constraint_check_rules(migrate_engine):
    ok = dict(source_url="https://example.invalid/rule")
    _seed.insert_format_constraint(migrate_engine, marketplace="AMAZON", version=_v(), backend_terms_max_bytes=250)
    with pytest.raises(IntegrityError):  # backend terms exist only on Amazon
        _seed.insert_format_constraint(migrate_engine, marketplace="FLIPKART", version=_v(), backend_terms_max_bytes=250)
    for field in ("title_max_chars", "title_option_count", "bullet_count", "bullet_max_chars",
                  "description_max_chars", "keywords_max_count", "keywords_max_chars", "backend_terms_max_bytes"):
        with pytest.raises(IntegrityError):
            _seed.insert_format_constraint(migrate_engine, marketplace="AMAZON", version=_v(), **{field: 0})
    with pytest.raises(IntegrityError):
        _seed.insert_format_constraint(migrate_engine, version=_v(), source_url="not-a-url")
    with pytest.raises(IntegrityError):
        _seed.insert_format_constraint(migrate_engine, version=0)
    with pytest.raises(IntegrityError):
        _seed.insert_format_constraint(migrate_engine, version=_v(), row_kind="DRAFT")
    with pytest.raises(IntegrityError):  # only the supported counting rules may be recorded
        _seed.insert_format_constraint(migrate_engine, version=_v(), count_rule="GRAPHEMES")
    _seed.insert_format_constraint(migrate_engine, version=_v(), count_rule=None)  # NULL = unverified is storable (and blocks production)
    _seed.insert_format_constraint(migrate_engine, version=_v(), count_rule="CODE_POINTS")
    del ok


def test_format_constraint_version_unique_per_kind_even_for_null_category(migrate_engine):
    v = _v()
    _seed.insert_format_constraint(migrate_engine, marketplace="MEESHO", category=None, version=v)
    with pytest.raises(IntegrityError):
        _seed.insert_format_constraint(migrate_engine, marketplace="MEESHO", category=None, version=v)
    _seed.insert_format_constraint(migrate_engine, marketplace="MEESHO", category="drinkware", version=v)
    # the same (marketplace, category, version) may exist once as VERIFIED and once as TEST_FIXTURE.
    # A VERIFIED row must never outlive a test, so prove it inside a rolled-back transaction.
    with migrate_engine.connect() as conn:
        tx = conn.begin()
        conn.execute(
            text(
                "INSERT INTO format_constraint (marketplace, category, version, row_kind, source_url, verified_at) "
                "VALUES ('MEESHO', NULL, :v, 'VERIFIED', 'https://example.invalid/x', now())"
            ),
            {"v": v},
        )
        tx.rollback()


def test_application_role_cannot_write_platform_tables(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    run = _seed.insert_vision_eval_run(migrate_engine)
    constraint = _constraint(migrate_engine)
    with tenant_scope(tenant) as conn:
        assert conn.execute(text("SELECT count(*) FROM format_constraint WHERE id = :i"), {"i": str(constraint)}).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM vision_eval_run WHERE id = :i"), {"i": str(run)}).scalar_one() == 1
    for stmt in (
        "UPDATE format_constraint SET title_max_chars = 1",
        "DELETE FROM format_constraint",
        "UPDATE vision_eval_run SET passed = true",
        "DELETE FROM vision_eval_run",
        "INSERT INTO vision_eval_run (provider, model, schema_version, dataset_ref, metrics, bar_ref, passed, run_by) "
        "VALUES ('p','m','v','d','{}'::jsonb,'b',true,'app')",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            with tenant_scope(tenant) as conn:
                conn.execute(text(stmt))


# ---------------------------------------------------------------------------------------------
# seller_image_asset
# ---------------------------------------------------------------------------------------------


def test_asset_content_address_rules(two_tenants):
    tenant, other = two_tenants
    sha = uuid.uuid4().hex + uuid.uuid4().hex
    first = _seed.insert_asset(tenant, sha256=sha)
    assert first
    _violates(lambda: _seed.insert_asset(tenant, sha256=sha))  # same bytes, same tenant: one asset
    _seed.insert_asset(other, sha256=sha)  # another tenant may hold the identical image
    _violates(lambda: _seed.insert_asset(tenant, sha256="not-a-sha"))
    _violates(lambda: _seed.insert_asset(tenant, sha256="A" * 64))  # lowercase hex only


def test_asset_size_must_be_positive_and_status_valid(two_tenants):
    tenant, _ = two_tenants
    for stmt in (
        "INSERT INTO seller_image_asset (tenant_id, storage_uri, sha256, content_type, byte_size, uploaded_by, status) "
        "VALUES (:t, 'file:///x', :sha, 'image/jpeg', 0, :u, 'ACTIVE')",
        "INSERT INTO seller_image_asset (tenant_id, storage_uri, sha256, content_type, byte_size, uploaded_by, status) "
        "VALUES (:t, 'file:///x', :sha, 'image/jpeg', 10, :u, 'DELETED')",
    ):
        with pytest.raises((IntegrityError, DBAPIError)):
            with tenant_scope(tenant) as conn:
                conn.execute(text(stmt), {"t": str(tenant), "sha": "b" * 64, "u": str(uuid.uuid4())})


# ---------------------------------------------------------------------------------------------
# Grants: provenance is append-only for the application role
# ---------------------------------------------------------------------------------------------

_APPEND_ONLY = [
    "cmo_generation",
    "cmo_title_option",
    "cmo_title_approval",
    "product_image_analysis",
    "seller_fact",
    "cmo_trend_report",
]


@pytest.mark.parametrize("table", _APPEND_ONLY)
def test_application_role_cannot_rewrite_or_delete_provenance(two_tenants, table):
    tenant, _ = two_tenants
    for stmt in (f"DELETE FROM {table}", f"UPDATE {table} SET tenant_id = tenant_id"):
        with pytest.raises(DBAPIError, match="permission denied"):
            with tenant_scope(tenant) as conn:
                conn.execute(text(stmt))


def test_mutable_tables_allow_update_but_not_delete(two_tenants):
    tenant, _ = two_tenants
    term = _seed.insert_niche_term(tenant, status="SUGGESTED")
    asset = _seed.insert_asset(tenant)
    with tenant_scope(tenant) as conn:
        conn.execute(text("UPDATE cmo_niche_term SET status = 'REJECTED' WHERE id = :i"), {"i": str(term)})
        conn.execute(text("UPDATE seller_image_asset SET status = 'PURGED' WHERE id = :i"), {"i": str(asset)})
    for table in ("cmo_niche_term", "seller_image_asset"):
        with pytest.raises(DBAPIError, match="permission denied"):
            with tenant_scope(tenant) as conn:
                conn.execute(text(f"DELETE FROM {table}"))


def test_migration_head_is_recorded(migrate_engine):
    with migrate_engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version_slim_cmo")).scalar_one()
    assert version == "20261005_0002"  # P6 added the vision indexes on top of the P1 schema (20261003_0001)
