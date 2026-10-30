"""CMO 3.0 M6 title approval on the rules-unavailable basis (spec 6.18.11, Q32; acceptance N-16a-c): a seller-edited title is checked without a marketplace length only for a title set the
SERVER generated inside a full-listing request, with the flag on and no usable verified row. A verified row, a standalone set, a configuration fault and any client input keep C13."""

from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

from slim_cmo.listing.basis import FULL_LISTING
from slim_cmo.listing.context import ListingContext
from slim_cmo.service.approve import ApprovalRefused, ApprovalService, Approved
from slim_cmo.service.generate import GenerationService, Intake
from slim_cmo.generation.provider import ScriptedLlmProvider
from slim_cmo.types import Marketplace as M

from ..factories import NOW, constraint
from ..generation.helpers import MODEL, j
from .fakes import ACTOR, GOOD_CONFIG, InMemoryStore, clock

LISTING = ListingContext(workflow=FULL_LISTING)
INTAKE = Intake(request_key="t1", sku="SKU1", brand="AquaKeep", attributes=(("material", "stainless steel"), ("capacity", "750 ml")))
TS5 = j(titles=["AquaKeep Steel Bottle 750 ml", "AquaKeep Stainless Water Bottle", "AquaKeep Steel Water Bottle 750 ml", "AquaKeep 750 ml Steel Flask", "AquaKeep Everyday Steel Bottle"])
LONG = "AquaKeep Stainless Steel Water Bottle 750 ml for everyday use at home and in the office"
ON = {**GOOD_CONFIG, "listing_unverified_rules_enabled": True, "rules_unavailable_bullet_target": 5}


def title_set(*, listing=LISTING, constraints=None, config=None):
    store = InMemoryStore(constraints=[] if constraints is None else constraints, config=dict(config or ON))
    svc = GenerationService(store, ScriptedLlmProvider([TS5]), model=MODEL, clock=clock(NOW))
    run = svc.generate_title_sets(ACTOR, replace(INTAKE, listing=listing), [M.AMAZON])
    assert run.artefacts[0].status.value == "COMPLETE", run.artefacts[0].failure
    return store, run.artefacts[0].generation_id


def approve(store, gid, text=LONG):
    return ApprovalService(store, clock=clock(NOW)).approve_title(ACTOR, gid, edited_text=text)


def test_an_edited_title_in_a_full_listing_set_is_approved_without_a_marketplace_length():
    store, gid = title_set()
    res = approve(store, gid)
    assert isinstance(res, Approved) and res.edited_by_seller and res.approved_text == LONG
    assert store.approval_rows[0]["edited"] is True


def test_the_content_gates_still_apply_on_the_unverified_basis():
    store, gid = title_set()
    res = approve(store, gid, "AquaKeep Steel Bottle at Rs 499 only")
    assert isinstance(res, ApprovalRefused) and res.code == "TITLE_INVALID" and store.approval_rows == []


def test_choosing_a_generated_option_needs_no_rule_at_all_and_still_works():
    store, gid = title_set()
    opt = store.option_ids[gid][0]
    assert isinstance(ApprovalService(store, clock=clock(NOW)).approve_title(ACTOR, gid, option_id=opt), Approved)


def test_with_the_flag_off_the_edit_is_refused_with_the_reason():
    store, gid = title_set()
    store.config["listing_unverified_rules_enabled"] = False
    res = approve(store, gid)
    assert isinstance(res, ApprovalRefused) and res.code == "CONSTRAINT_BLOCKED" and "unverified drafts are not enabled" in res.detail


def test_a_set_generated_outside_the_workflow_never_gets_the_exception():
    store, gid = title_set(listing=None, constraints=[constraint(M.AMAZON)])  # a normal verified set
    store.constraints.clear()  # the verified data later disappears
    res = approve(store, gid)
    assert isinstance(res, ApprovalRefused) and res.code == "CONSTRAINT_BLOCKED" and "unverified" not in res.detail


def test_a_verified_row_that_appears_later_takes_priority_and_its_limit_applies():
    store, gid = title_set()
    store.constraints.append(constraint(M.AMAZON, title_max_chars=40))
    res = approve(store, gid)
    assert isinstance(res, ApprovalRefused) and res.code == "TITLE_INVALID" and any("TOO_LONG" in v for v in res.violations)
    ok = approve(store, gid, "AquaKeep Steel Bottle 750 ml")
    assert isinstance(ok, Approved)


@pytest.mark.parametrize("bad", [{"format_constraint_max_age_days": 0}])
def test_a_configuration_fault_still_blocks_the_approval(bad):
    store, gid = title_set()
    store.config.update(bad)
    res = approve(store, gid)
    assert isinstance(res, ApprovalRefused) and res.code == "CONSTRAINT_BLOCKED"


def test_a_client_cannot_supply_the_workflow_marker_to_the_approval():
    params = set(inspect.signature(ApprovalService.approve_title).parameters)
    assert params == {"self", "actor", "generation_id", "option_id", "edited_text"}  # nothing that could carry a workflow or a basis


def test_another_tenants_set_is_not_found():
    from slim_cmo.service.errors import NotFound
    from slim_cmo.service.models import Actor
    import uuid

    store, gid = title_set()
    with pytest.raises(NotFound):
        ApprovalService(store, clock=clock(NOW)).approve_title(Actor(uuid.uuid4(), ACTOR.user_id), gid, edited_text=LONG)
