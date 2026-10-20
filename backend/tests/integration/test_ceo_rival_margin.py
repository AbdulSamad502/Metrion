"""Spec 6.38 (C3): "what is my margin at <competitor>'s price?" fuses CI's observation with a CFO margin, through the CEO.

The rule routes it to the price-impact conversation (no model: the classifier is EMPTY), the competitor named is matched against the seller's tracked competitors,
CI's last captured price is OFFERED (with its date) as the price to test and never filled in, a price the seller states is taken as theirs, and the margin itself comes
from the same CFO leg as the price-impact form."""

from __future__ import annotations

import os

import pytest

from backend.ceo import orchestrator
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_guided_input import option_key, rt_for, say
from tests.integration.test_ceo_state_specialists import NOW, seed  # noqa: F401  (fixture + constant)
from tests.integration.test_ceo_turn import start

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]


def walk_to_candidates(ctx, rt, inv, first):
    res = say(ctx, rt, inv, "SKU-1")
    # (the fee reference is filled in from saved data when only one exists)
    res = say(ctx, rt, inv, "", card=res.message_id, option=option_key(res, "Prices exclude GST"))
    res = say(ctx, rt, inv, "", card=res.message_id, option=option_key(res, "I do not know"))
    return say(ctx, rt, inv, "499")


def test_the_competitor_is_taken_from_the_question_and_their_captured_price_is_offered_not_filled_in(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    comp = seed.url(a, "Acme Steel")
    seed.snapshot(a, comp, 52000)
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    first = orchestrator.run_turn(ctx, rt, inv, "what is my margin at Acme Steel's price?")
    assert first.clarify_for == "sku" and first.choices["pending"]["collected"] == {"competitor": str(comp), "fee": {"marketplace": "meesho", "category": "*", "fee_type": "COMMISSION"}} and "(3 of 8)" in first.answer
    res = walk_to_candidates(ctx, rt, inv, first)
    assert res.clarify_for == "candidate_prices_paise"
    [offer] = [o for o in res.choices["options"] if o["kind"] in ("RECOMMENDED", "ALTERNATIVE")]
    assert offer["label"] == "Match Acme Steel price (₹520.00)" and "Not verified" in offer["reason"]  # CI's figure, dated, labelled
    assert "candidate_prices_paise" not in res.choices["pending"]["collected"] and calls == {}  # offered, never filled in
    nxt = say(ctx, rt, inv, "", card=res.message_id, option=offer["key"])
    assert nxt.clarify_for == "costs_gate" and nxt.choices["pending"]["collected"]["candidate_prices_paise"] == [52000]


def test_a_price_the_seller_states_is_taken_as_theirs_and_not_asked_again(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    comp = seed.url(a, "Acme Steel")
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    first = orchestrator.run_turn(ctx, rt, inv, "Acme Steel is at 449, what is my margin")
    assert first.choices["pending"]["collected"] == {"competitor": str(comp), "candidate_prices_paise": [44900], "fee": {"marketplace": "meesho", "category": "*", "fee_type": "COMMISSION"}}
    nxt = walk_to_candidates(ctx, rt, inv, first)
    assert nxt.clarify_for == "costs_gate"  # the candidate price was already given


def test_an_unknown_competitor_name_is_asked_about_never_guessed(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    seed.url(a, "Acme Steel")
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for({})
    inv = start(ctx, rt)
    first = orchestrator.run_turn(ctx, rt, inv, "what is my margin at Zed Corp's price?")
    assert first.clarify_for == "competitor" and "Acme Steel" in [o["label"] for o in first.choices["options"]] and first.choices["pending"]["collected"] == {"fee": {"marketplace": "meesho", "category": "*", "fee_type": "COMMISSION"}}
