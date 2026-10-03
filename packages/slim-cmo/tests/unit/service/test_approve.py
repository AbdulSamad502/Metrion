"""cmo.approve_title (decision 5, C8, AC11, E8, E10, T9c)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import timedelta

import pytest

from slim_cmo.generation.provider import ScriptedLlmProvider
from slim_cmo.service.approve import ApprovalRefused, Approved, ApprovalService
from slim_cmo.service.errors import InvalidApproval, NotFound
from slim_cmo.service.generate import GenerationService, Intake
from slim_cmo.service.models import Actor
from slim_cmo.types import Marketplace as M

from ..factories import NOW, constraint
from ..generation.helpers import GOOD_TITLES, MODEL, j
from .fakes import ACTOR, TENANT_B, USER, InMemoryStore, clock

INTAKE = Intake(request_key="ts", sku="SKU1", brand="AquaKeep", attributes=(("capacity", "750 ml"), ("material", "stainless steel")))


def title_set(store, mp=M.AMAZON, key="ts"):
    svc = GenerationService(store, ScriptedLlmProvider([j(titles=GOOD_TITLES)]), model=MODEL, clock=clock())
    run = svc.generate_title_sets(ACTOR, replace(INTAKE, request_key=key), [mp])
    gid = run.artefacts[0].generation_id
    return gid, store.option_ids[gid]


def approver(store, now=NOW):
    return ApprovalService(store, clock=clock(now))


class TestOptionApproval:
    def test_persists_an_approval_for_the_chosen_option_and_costs_nothing(self):
        store = InMemoryStore()
        gid, opts = title_set(store)
        res = approver(store).approve_title(ACTOR, gid, option_id=opts[2])
        assert isinstance(res, Approved) and res.approved_text == GOOD_TITLES[2] and not res.edited_by_seller
        assert store.approval_rows == [{"id": res.approval_id, "option_id": opts[2], "edited": False, "by": USER}]

    def test_reapproving_creates_a_new_row_and_leaves_the_old_one(self):
        store = InMemoryStore()
        gid, opts = title_set(store)
        a = approver(store).approve_title(ACTOR, gid, option_id=opts[0])
        b = approver(store).approve_title(ACTOR, gid, option_id=opts[1])
        assert a.approval_id != b.approval_id and len(store.approval_rows) == 2 and a.approval_id in store.approvals

    def test_e8_unknown_foreign_or_wrong_set_ids_are_not_found(self):
        store = InMemoryStore()
        gid, opts = title_set(store)
        gid2, opts2 = title_set(store, M.FLIPKART, key="ts2")
        a = approver(store)
        with pytest.raises(NotFound):
            a.approve_title(ACTOR, gid, option_id=uuid.uuid4())
        with pytest.raises(NotFound):
            a.approve_title(ACTOR, gid, option_id=opts2[0])  # an option of a DIFFERENT set
        with pytest.raises(NotFound):
            a.approve_title(ACTOR, uuid.uuid4(), option_id=opts[0])
        with pytest.raises(NotFound):
            a.approve_title(Actor(TENANT_B, USER), gid, option_id=opts[0])  # another tenant's set
        assert store.approval_rows == []

    def test_a_failed_title_set_or_a_non_title_set_cannot_be_approved(self):
        store = InMemoryStore()
        svc = GenerationService(store, ScriptedLlmProvider([j(titles=["z" * 90])] * 2), model=MODEL, clock=clock())
        failed = svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON]).artefacts[0]
        with pytest.raises(NotFound):
            approver(store).approve_title(ACTOR, failed.generation_id, edited_text="AquaKeep Bottle")

    def test_exactly_one_of_option_or_edited_text(self):
        store = InMemoryStore()
        gid, opts = title_set(store)
        for kw in ({}, {"option_id": opts[0], "edited_text": "AquaKeep Bottle"}, {"edited_text": "   "}):
            with pytest.raises(InvalidApproval):
                approver(store).approve_title(ACTOR, gid, **kw)
        assert store.approval_rows == []


class TestEditedTitle:
    def test_a_valid_edit_is_stored_as_seller_edited_with_no_option(self):
        store = InMemoryStore()
        gid, _ = title_set(store)
        res = approver(store).approve_title(ACTOR, gid, edited_text="  AquaKeep Steel Flask 750 ml  ")
        assert isinstance(res, Approved) and res.edited_by_seller and res.option_id is None
        assert res.approved_text == "AquaKeep Steel Flask 750 ml" and store.approval_rows[0]["edited"] is True

    def test_t9c_an_edit_past_the_limit_is_refused_deterministically_with_no_row(self):
        store = InMemoryStore()
        gid, _ = title_set(store)
        res = approver(store).approve_title(ACTOR, gid, edited_text="AquaKeep " * 20)
        assert isinstance(res, ApprovalRefused) and res.code == "TITLE_INVALID"
        assert any("TOO_LONG" in v for v in res.violations) and store.approval_rows == []

    def test_a_forbidden_edit_is_refused(self):
        store = InMemoryStore()
        gid, _ = title_set(store)
        res = approver(store).approve_title(ACTOR, gid, edited_text="AquaKeep Bottle Rs. 499")
        assert isinstance(res, ApprovalRefused) and any("PRICE" in v for v in res.violations)

    def test_decision_5_the_edit_is_checked_against_the_CURRENT_constraint_not_the_historical_one(self):
        store = InMemoryStore()
        gid, _ = title_set(store)  # created under title_max_chars=40
        edit = "AquaKeep Steel Flask 750 ml Pro"  # 31 chars: fine then
        assert isinstance(approver(store).approve_title(ACTOR, gid, edited_text=edit), Approved)
        store.constraints = [constraint(M.AMAZON, title_max_chars=20, version=2), *store.constraints]  # rule tightened since
        res = approver(store).approve_title(ACTOR, gid, edited_text=edit)
        assert isinstance(res, ApprovalRefused) and res.code == "TITLE_INVALID" and len(store.approval_rows) == 1

    def test_decision_5_if_the_current_constraint_cannot_be_resolved_the_approval_is_refused(self):
        store = InMemoryStore()
        gid, _ = title_set(store)
        late = NOW + timedelta(days=90)  # the verified row is now stale
        res = approver(store, now=late).approve_title(ACTOR, gid, edited_text="AquaKeep Steel Flask 750 ml")
        assert isinstance(res, ApprovalRefused) and res.code == "CONSTRAINT_BLOCKED" and store.approval_rows == []
        store.constraints = []
        res = approver(store).approve_title(ACTOR, gid, edited_text="AquaKeep Steel Flask 750 ml")
        assert isinstance(res, ApprovalRefused) and res.code == "CONSTRAINT_BLOCKED"

    def test_a_missing_staleness_config_refuses_the_edit_but_never_an_unedited_option(self):
        store = InMemoryStore()
        gid, opts = title_set(store)
        store.config = {}
        assert isinstance(approver(store).approve_title(ACTOR, gid, edited_text="AquaKeep Steel Flask"), ApprovalRefused)
        assert isinstance(approver(store).approve_title(ACTOR, gid, option_id=opts[0]), Approved)  # option text was validated at creation

    def test_the_category_context_is_the_one_the_set_was_resolved_under_not_a_caller_choice(self):
        import inspect

        assert "category_hint" not in inspect.signature(ApprovalService.approve_title).parameters
        store = InMemoryStore()
        store.constraints.append(constraint(M.AMAZON, category="Kitchen", title_max_chars=15))
        edit = "AquaKeep Steel Flask 750 ml"  # 27 chars
        # a set created WITHOUT a hint was resolved against the marketplace-wide rule: the Kitchen rule never applies
        gid, _ = title_set(store, key="plain")
        assert isinstance(approver(store).approve_title(ACTOR, gid, edited_text=edit), Approved)
        # a set created under hint "kitchen" keeps that context at approval time
        svc = GenerationService(store, ScriptedLlmProvider([j(titles=["AquaKeep Flask", "AquaKeep Bottle", "AquaKeep Steel"])]), model=MODEL, clock=clock())
        run = svc.generate_title_sets(ACTOR, replace(INTAKE, request_key="kit", category_hint=" Kitchen "), [M.AMAZON])
        kitchen = run.artefacts[0].generation_id
        saved = store.rows()[-1].output_structured["category_context"]
        assert saved == {"category_hint": "Kitchen", "resolved_category": "Kitchen"}
        res = approver(store).approve_title(ACTOR, kitchen, edited_text=edit)
        assert isinstance(res, ApprovalRefused) and res.code == "TITLE_INVALID"
        assert isinstance(approver(store).approve_title(ACTOR, kitchen, edited_text="AquaKeep Mug"), Approved)

    def test_an_unmatched_hint_is_remembered_and_still_falls_back_to_the_marketplace_wide_rule(self):
        store = InMemoryStore()
        svc = GenerationService(store, ScriptedLlmProvider([j(titles=GOOD_TITLES)]), model=MODEL, clock=clock())
        gid = svc.generate_title_sets(ACTOR, replace(INTAKE, category_hint="Toys"), [M.AMAZON]).artefacts[0].generation_id
        assert store.rows()[0].output_structured["category_context"] == {"category_hint": "Toys", "resolved_category": None}
        assert isinstance(approver(store).approve_title(ACTOR, gid, edited_text="AquaKeep Steel Flask 750 ml"), Approved)


def test_the_approver_cannot_be_ceo_or_inferred_it_is_the_actor_user():
    store = InMemoryStore()
    gid, opts = title_set(store)
    approver(store).approve_title(Actor(ACTOR.tenant_id, uuid.UUID(int=7)), gid, option_id=opts[0])
    assert store.approval_rows[0]["by"] == uuid.UUID(int=7)
