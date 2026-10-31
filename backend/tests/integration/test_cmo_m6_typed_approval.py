"""CMO 3.0 M6 N-05t (migration 20261031_0008): the seller's explicit approval of a title they TYPED is its own record (`title_source = SELLER_TYPED`, no title-set generation, no option, no model, no unit),
distinguishable from a generated-title approval, tenant-scoped, append-only, and checked against the same current rules as an edited title. Executed on a scratch database in the final closure pass (5 passed)."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from backend.ceo import cmo_chat
from backend.repositories import cmo_chat_repo
from slim_cmo.service.approve import ApprovalRefused, TypedApproved
from slim_cmo.service.models import Actor
from slim_cmo.types import Marketplace
from tests.integration.test_cmo_api import _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import NAME, SKU, ListingProvider, ru_env

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

TYPED = "AquaNest Steel Bottle 1 L Silver"


def approve(env, title=TYPED, mp=Marketplace.AMAZON, sku=SKU):
    return env.runtime.approvals.approve_typed_title(Actor(env.tenant, env.user_id), sku=sku, marketplace=mp, text=title)


def test_a_typed_title_approval_is_its_own_record_with_no_generation_and_is_distinguishable(env):
    ru_env(env, ListingProvider())
    res = approve(env)
    assert isinstance(res, TypedApproved) and res.approved_text == TYPED
    row = env.q("SELECT title_source, generation_id IS NULL, option_id IS NULL, edited_by_seller, sku, marketplace, approved_text, approved_by = :u FROM cmo_title_approval", u=env.user_id)
    assert [tuple(r) for r in row] == [("SELLER_TYPED", True, True, True, SKU, "AMAZON", TYPED, True)]
    assert env.n("cmo_generation") == 0 and env.n("metered_event", "agent_code = 'CMO'") == 0  # no title set was invented, nothing was charged
    ref = cmo_chat_repo.approval_ref(env.tenant, res.approval_id)
    assert ref["titleSource"] == "SELLER_TYPED" and cmo_chat_repo.current_approval(env.tenant, SKU, "AMAZON")["id"] == str(res.approval_id)
    assert cmo_chat_repo.approved_titles(env.tenant, sku=SKU, marketplace="AMAZON")[0]["generationId"] is None  # listed with the seller's other approvals, with no generation


def test_re_approving_is_append_only_and_an_identical_title_is_reused_by_the_chat_helper(env):
    ru_env(env, ListingProvider())
    sku = cmo_chat.product_sku(NAME)  # the chat derives the product identity from the product name the same way
    first = approve(env, sku=sku)
    second = approve(env, sku=sku)
    assert first.approval_id != second.approval_id and env.n("cmo_title_approval") == 2  # the service appends; earlier rows stay
    again, refusal = cmo_chat.record_typed_title_approval(env.tenant, env.user_id, {"seller_title": TYPED, "sku": sku, "product_name": NAME, "marketplace": "AMAZON"})
    assert refusal is None and again in {str(first.approval_id), str(second.approval_id)} and env.n("cmo_title_approval") == 2  # the chat helper reuses an identical approved title


def test_a_typed_approval_is_tenant_scoped(env):
    ru_env(env, ListingProvider())
    res = approve(env)
    other_tenant, _ = env.other_tenant()
    assert cmo_chat_repo.approval_ref(other_tenant, res.approval_id) is None  # a foreign tenant sees nothing (FORCE RLS + tenant-scoped query)
    assert cmo_chat_repo.current_approval(other_tenant, SKU, "AMAZON") is None
    assert env.n("cmo_title_approval", tenant=other_tenant) == 0


def test_the_current_rules_apply_a_verified_limit_refuses_an_over_long_typed_title_and_writes_nothing(env):
    ru_env(env, ListingProvider())
    with env.engine.begin() as conn:
        conn.execute(text("INSERT INTO format_constraint (marketplace, title_max_chars, title_option_count, bullet_count, bullet_max_chars, description_type, description_max_chars, keywords_max_count, "
                          "keywords_max_chars, backend_terms_max_bytes, count_rule, source_url, verified_at, version, row_kind) VALUES ('AMAZON', 10, 3, 3, 200, 'plain', 900, 10, 40, 249, "
                          "'UTF16_CODE_UNITS', 'https://example.invalid/test-fixture', now(), 1, 'TEST_FIXTURE')"))
    res = approve(env)
    assert isinstance(res, ApprovalRefused) and res.code == "TITLE_INVALID" and env.n("cmo_title_approval") == 0


def test_without_the_operator_flag_the_unverified_basis_is_not_available_and_nothing_is_written(env):
    ru_env(env, ListingProvider(), config={"format_constraint_max_age_days": 30, "internal_retry_bound": 0, "hashtag_set_size": 3, "listing_unverified_rules_enabled": False, "rules_unavailable_bullet_target": 3})
    res = approve(env)
    assert isinstance(res, ApprovalRefused) and res.code == "CONSTRAINT_BLOCKED" and env.n("cmo_title_approval") == 0
