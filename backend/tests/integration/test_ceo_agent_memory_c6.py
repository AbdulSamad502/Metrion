"""Agent memory C6 (spec agent-memory.md section 11): CMO, CI and CFO each keep a PRIVATE short choice the seller confirmed (last marketplaces, last competitor, last GST
basis) and OFFER it first next time. Offered, never filled in; written only when a session finished; private per agent and per tenant; forgotten through the existing
mechanism; a value that is not in its closed form is not offered."""

from __future__ import annotations

import datetime
import os
from uuid import uuid4

import pytest

from backend.ceo import input_session, memory, orchestrator
from backend.repositories import agent_memory_repo as repo
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_cmo_chat import ASK, HASHTAGS, rt_for as cmo_rt
from tests.integration.test_ceo_decision_playbooks import save_cogs
from tests.integration.test_ceo_guided_input import UI, option_key, rt_for as cfo_rt, say
from tests.integration.test_ceo_state_specialists import NOW, seed  # noqa: F401  (fixture + constant)
from tests.integration.test_ceo_turn import Scripted, decision, start

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

SRC = {"message_id": str(uuid4())}
LAST = "What you chose last time"
TITLES = lambda **slots: decision(route="ACTION", route_key="cmo.generate_title_sets", slots=slots)  # noqa: E731


def ictx(tenant):
    return input_session.Ctx(tenant, datetime.date.today(), 5)


def keep(tenant, user, agent, key, value):
    return memory.note(tenant, agent=agent, key=key, value=value, basis="CONFIRMED_DECISION", source_ref=SRC, created_by=user)


def first_option(card):
    return card["options"][0]


def offered_labels(card):
    return [o["label"] for o in card["options"] if o["kind"] in ("RECOMMENDED", "ALTERNATIVE")]


# ------------------------------------------------------------------------------------------------ CMO
def test_cmo_remembers_the_confirmed_marketplace_and_offers_it_first_without_filling_it(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = cmo_rt(calls, Scripted({ASK: HASHTAGS(product="steel water bottle")}))
    inv = start(ctx, rt)
    q = orchestrator.run_turn(ctx, rt, inv, ASK)
    assert q.status == "CLARIFIED" and memory.offered(a, "CMO", "last_marketplaces") is None  # a session still asking writes nothing
    assert [o["label"] for o in q.choices["options"]][:3] == ["Amazon", "Flipkart", "Meesho"]  # no memory yet: the existing options only
    done = orchestrator.run_turn(ctx, rt, inv, "Flipkart")
    assert done.status == "DELIVERED"
    [row] = repo.list_active(a, scope="PRIVATE", agent="CMO", kind="NOTE", key="last_marketplaces")
    assert row["value"] == "FLIPKART" and row["basis"] == "CONFIRMED_DECISION" and row["source_ref"]["message_id"]
    # the next run: offered first with the reason, the field is still unanswered
    q2 = orchestrator.run_turn(ctx, rt, start(ctx, rt), ASK)
    opts = [o for o in q2.choices["options"] if o["kind"] in ("RECOMMENDED", "ALTERNATIVE")]
    assert opts[0]["label"] == "Flipkart" and opts[0]["reason"] == LAST and len(opts) == 3
    assert [o["label"] for o in opts] == ["Flipkart", "Amazon", "Meesho"]  # the same text is not repeated; the others stay in order
    assert "marketplace" not in q2.choices["pending"]["collected"]


def test_cmo_titles_offer_a_remembered_multiple_but_a_one_marketplace_question_does_not(two_tenants, app_user):
    a, _ = two_tenants
    keep(a, app_user, "CMO", "last_marketplaces", "AMAZON, FLIPKART")
    titles = input_session.start("cmo.generate_title_sets", ictx(a), {"product": "steel bottle"})  # product given; category asked first
    assert titles.card["slot"] == "category_hint"
    nxt = input_session.advance(titles.card, option_key=None, text="kitchen", ctx=ictx(a))
    assert nxt.card["slot"] == "marketplaces" and first_option(nxt.card)["label"] == "Amazon, Flipkart" and first_option(nxt.card)["reason"] == LAST
    assert "marketplaces" not in nxt.card["pending"]["collected"]
    assert len(offered_labels(nxt.card)) == 3
    one = input_session.start("cmo.generate_description", ictx(a), {"product": "steel bottle"})
    assert one.card["slot"] == "marketplace" and all(o["reason"] != LAST for o in one.card["options"])  # a multi value cannot answer a one-marketplace question
    hashtags = input_session.start("cmo.generate_hashtags", ictx(a), {"product": "steel bottle"})
    assert all(o["reason"] != LAST for o in hashtags.card["options"])


def test_cmo_hashtags_and_grounded_offer_a_remembered_single_marketplace(two_tenants, app_user):
    a, _ = two_tenants
    keep(a, app_user, "CMO", "last_marketplaces", "MEESHO")
    for key in ("cmo.generate_hashtags", "cmo.generate_description", "cmo.generate_keywords"):
        s = input_session.start(key, ictx(a), {"product": "steel bottle"})
        assert s.card["slot"] == "marketplace" and first_option(s.card)["label"] == "Meesho" and first_option(s.card)["reason"] == LAST, key
        assert len(offered_labels(s.card)) <= input_session.MAX_OPTIONS


def test_skipping_the_optional_marketplace_remembers_nothing(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = cmo_rt(calls, Scripted({ASK: HASHTAGS(product="steel water bottle")}))
    inv = start(ctx, rt)
    orchestrator.run_turn(ctx, rt, inv, ASK)
    assert orchestrator.run_turn(ctx, rt, inv, "skip").status == "DELIVERED"
    assert memory.offered(a, "CMO", "last_marketplaces") is None


# ------------------------------------------------------------------------------------------------ CI and CFO (the price-impact conversation)
def _finish_price_impact(ctx, rt, inv, competitor_label, basis_label):
    orchestrator.run_turn(ctx, rt, inv, "Price impact", ui_action=UI("PLAYBOOK", "COMPETITOR_PRICE_IMPACT"))
    res = say(ctx, rt, inv, competitor_label)
    res = say(ctx, rt, inv, "SKU-1")
    res = say(ctx, rt, inv, "", card=res.message_id, option=res.choices["options"][0]["key"])
    res = say(ctx, rt, inv, "", card=res.message_id, option=option_key(res, basis_label))
    res = say(ctx, rt, inv, "", card=res.message_id, option=option_key(res, "I do not know"))
    for typed in ("₹499", "449, 479"):
        res = say(ctx, rt, inv, typed)
    for _ in range(4):
        res = say(ctx, rt, inv, "", card=res.message_id, option=option_key(res, "None (0), I confirm"))
    return res


def test_ci_and_cfo_remember_the_confirmed_competitor_and_basis_and_offer_them_first(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    comp = seed.url(a, "Acme Steel")
    seed.snapshot(a, comp, 52000)
    for name in ("Beta One", "Beta Two", "Beta Three"):  # newer: Acme Steel is no longer among the first three shown
        seed.url(a, name)
    save_cogs(a, app_user)
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = cfo_rt(calls)
    inv = start(ctx, rt)
    first = orchestrator.run_turn(ctx, rt, inv, "Price impact", ui_action=UI("PLAYBOOK", "COMPETITOR_PRICE_IMPACT"))
    assert all(o["reason"] != LAST for o in first.choices["options"])  # nothing remembered yet
    final = _finish_price_impact(ctx, rt, inv, "Acme Steel", "Prices exclude GST")
    assert final.status == "DELIVERED" and calls
    assert memory.offered(a, "CI", "last_competitor") == "Acme Steel" and memory.offered(a, "CFO", "last_basis") == "EXCLUSIVE"
    # next conversation: both offered first, neither filled in
    again = orchestrator.run_turn(ctx, rt, start(ctx, rt), "Price impact", ui_action=UI("PLAYBOOK", "COMPETITOR_PRICE_IMPACT"))
    opts = [o for o in again.choices["options"] if o["kind"] in ("RECOMMENDED", "ALTERNATIVE")]
    assert opts[0]["label"] == "Acme Steel" and opts[0]["reason"] == LAST and len(opts) == 3
    assert again.choices["pending"]["collected"] == {}
    card = input_session.advance(again.choices, option_key=opts[0]["key"], text="", ctx=ictx(a))
    card = input_session.advance(card.card, option_key=None, text="SKU-1", ctx=ictx(a))
    assert card.card["slot"] == "fee"
    card = input_session.advance(card.card, option_key="opt-0", text="", ctx=ictx(a))
    assert card.card["slot"] == "basis" and "basis" not in card.card["pending"]["collected"]
    assert (first_option(card.card)["label"], first_option(card.card)["value"], first_option(card.card)["reason"]) == ("Prices exclude GST", "exclusive", LAST)
    assert [o["label"] for o in card.card["options"][:2]] == ["Prices exclude GST", "Prices include GST"]


def test_a_cancelled_conversation_remembers_nothing(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    seed.url(a, "Acme Steel")
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = cfo_rt(calls)
    inv = start(ctx, rt)
    orchestrator.run_turn(ctx, rt, inv, "Price impact", ui_action=UI("PLAYBOOK", "COMPETITOR_PRICE_IMPACT"))
    say(ctx, rt, inv, "Acme Steel")
    assert say(ctx, rt, inv, "cancel") is not None
    assert memory.offered(a, "CI", "last_competitor") is None and memory.offered(a, "CFO", "last_basis") is None


# ------------------------------------------------------------------------------------------------ isolation
def test_each_agents_memory_is_private_and_so_is_each_tenants(two_tenants, app_user, seed):  # noqa: F811
    a, b = two_tenants
    seed.url(a, "Acme Steel")
    seed.url(b, "Acme Steel")
    keep(a, app_user, "CMO", "last_marketplaces", "AMAZON")
    keep(a, app_user, "CI", "last_competitor", "Acme Steel")
    keep(a, app_user, "CFO", "last_basis", "INCLUSIVE")
    # another agent never reads it: the same key under another agent is nothing, and PI's own memory does not contain it
    assert memory.offered(a, "CI", "last_marketplaces") is None and memory.offered(a, "CMO", "last_competitor") is None and memory.offered(a, "PI", "last_marketplaces") is None
    assert memory.pi_defaults(a) == {}
    assert all(r["scope"] == "PRIVATE" for r in repo.list_active(a)) and memory.profile(a) == {}  # nothing leaked into shared memory
    # another tenant never reads it
    assert [memory.offered(b, ag, k) for ag, k in (("CMO", "last_marketplaces"), ("CI", "last_competitor"), ("CFO", "last_basis"))] == [None, None, None]
    s = input_session.start("COMPETITOR_PRICE_IMPACT", ictx(b), {})
    assert all(o["reason"] != LAST for o in s.card["options"])  # B has a competitor of the same name, yet it is not "remembered" for B
    assert repo.list_active(b) == []
    # a pair outside the allowlist is refused, not stored
    for agent, key, value in (("CEO", "last_basis", "INCLUSIVE"), ("CMO", "last_basis", "INCLUSIVE"), ("CFO", "last_marketplaces", "AMAZON"), ("PI", "last_competitor", "x"),
                              ("CFO", "last_basis", "MAYBE"), ("CMO", "last_marketplaces", "AMAZON, BITCOIN"), ("CI", "last_competitor", "<script>")):
        with pytest.raises(ValueError):
            memory.note_choice(a, agent=agent, key=key, value=value, source_ref=SRC, created_by=app_user)


# ------------------------------------------------------------------------------------------------ forget
def test_forgetting_removes_the_offer(two_tenants, app_user, seed):  # noqa: F811
    a, b = two_tenants
    seed.url(a, "Acme Steel")
    keep(a, app_user, "CMO", "last_marketplaces", "MEESHO")
    keep(a, app_user, "CI", "last_competitor", "Acme Steel")
    keep(a, app_user, "CFO", "last_basis", "INCLUSIVE")
    items = {i["label"]: i for i in memory.list_for_seller(a)}
    assert set(items) == {"Marketing: last marketplaces you wrote listing content for", "Competitor Intelligence: last competitor you compared against",
                          "Finance: whether your prices include GST (last choice)"}  # visible to the seller with plain labels
    assert items["Finance: whether your prices include GST (last choice)"]["agent"] == "CFO" and items["Marketing: last marketplaces you wrote listing content for"]["shared"] is False
    mp = items["Marketing: last marketplaces you wrote listing content for"]["id"]
    assert memory.forget(b, __import__("uuid").UUID(mp), app_user) is False  # not another tenant's to forget
    for item in items.values():
        assert memory.forget(a, __import__("uuid").UUID(item["id"]), app_user) is True
    assert [memory.offered(a, ag, k) for ag, k in (("CMO", "last_marketplaces"), ("CI", "last_competitor"), ("CFO", "last_basis"))] == [None, None, None]
    s = input_session.start("cmo.generate_description", ictx(a), {"product": "steel bottle"})
    assert all(o["reason"] != LAST for o in s.card["options"])
    p = input_session.start("COMPETITOR_PRICE_IMPACT", ictx(a), {})
    assert all(o["reason"] != LAST for o in p.card["options"])
    assert memory.list_for_seller(a) == []
    keep(a, app_user, "CMO", "last_marketplaces", "MEESHO")  # remembered again later
    assert memory.offered(a, "CMO", "last_marketplaces") == "MEESHO"


# ------------------------------------------------------------------------------------------------ bad values
def test_a_bad_or_unknown_remembered_value_is_not_offered(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    seed.url(a, "Acme Steel")
    # written around the validation on purpose (as a bug or an old row might): reading still refuses it
    keep(a, app_user, "CMO", "last_marketplaces", "AMAZON, BITCOIN")
    keep(a, app_user, "CFO", "last_basis", "MAYBE")
    keep(a, app_user, "CI", "last_competitor", "A competitor that is no longer tracked")
    assert memory.offered(a, "CMO", "last_marketplaces") is None and memory.offered(a, "CFO", "last_basis") is None
    s = input_session.start("cmo.generate_description", ictx(a), {"product": "steel bottle"})
    assert [o["label"] for o in s.card["options"][:3]] == ["Amazon", "Flipkart", "Meesho"] and all(o["reason"] != LAST for o in s.card["options"])
    p = input_session.start("COMPETITOR_PRICE_IMPACT", ictx(a), {})
    assert p.card["slot"] == "competitor" and [o["label"] for o in p.card["options"] if o["kind"] != "OTHER" and o["kind"] != "CANCEL"] == ["Acme Steel"]
    assert all(o["reason"] != LAST for o in p.card["options"])  # untracked label: not offered
