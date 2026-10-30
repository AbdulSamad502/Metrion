"""The bounded CEO -> CMO missing-input loop (ceo-cmo-delegation.md CD13, 6.3-3; AC-D5, AC-D6). Pure code over the guided-input field tables: no model, no database
write, no clock but the one the test passes in. Every boundary named by the owner is pinned on BOTH sides:

* question limit: the 8th question is asked, a 9th never is (re-asks count toward the 8);
* re-ask limit: a field is asked at most 1 + 2 = 3 times, the 3rd unusable answer reaches the limit;
* idle expiry: 86399 s live, 86400 s expired, the answers kept and a fresh confirmation required;
* a setting that is present but not a positive whole number fails CLOSED (CONFIG_INVALID); unset means the stated default."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend import config
from backend.ceo import cmo_delegation as cd
from backend.ceo import input_session as ins

T0 = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)
CTX = ins.Ctx(uuid.uuid4(), T0.date(), None)
KEY = "cmo.generate_description"  # product -> marketplace -> the seller's title: three fields, each can be re-asked
VARS = ("CMO_DELEGATION_MAX_QUESTIONS", "CMO_DELEGATION_MAX_REASKS", "CMO_DELEGATION_IDLE_EXPIRY_SECONDS")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for v in VARS:
        monkeypatch.delenv(v, raising=False)


def start_task(now=T0):
    first = ins.start(KEY, CTX)
    assert isinstance(first, ins.Ask)
    return cd.begin(first, action_key=KEY, now=now)


def reply(ask, text, now=T0, option=None):
    return cd.advance(ask.card, option_key=option, text=text, ctx=CTX, now=now)


def at(seconds):
    return T0 + timedelta(seconds=seconds)


# ------------------------------------------------------------------------------------------------ configuration
def test_defaults_when_unset():
    assert cd.load_limits() == cd.Limits(8, 2, 86400)


@pytest.mark.parametrize("name,getter", [("CMO_DELEGATION_MAX_QUESTIONS", config.cmo_delegation_max_questions), ("CMO_DELEGATION_MAX_REASKS", config.cmo_delegation_max_reasks),
                                         ("CMO_DELEGATION_IDLE_EXPIRY_SECONDS", config.cmo_delegation_idle_expiry_seconds)])
@pytest.mark.parametrize("bad", ["0", "-1", "abc", "1.5", "2 3", "0x10", "+4"])
def test_a_present_but_unusable_value_fails_closed(monkeypatch, name, getter, bad):
    monkeypatch.setenv(name, bad)
    with pytest.raises(config.ConfigInvalid):
        getter()
    with pytest.raises(config.ConfigInvalid):
        cd.load_limits()


def test_blank_means_the_default_and_a_valid_value_is_honoured(monkeypatch):
    monkeypatch.setenv("CMO_DELEGATION_MAX_QUESTIONS", "  ")
    assert config.cmo_delegation_max_questions() == 8
    monkeypatch.setenv("CMO_DELEGATION_MAX_QUESTIONS", "3")
    monkeypatch.setenv("CMO_DELEGATION_MAX_REASKS", "1")
    monkeypatch.setenv("CMO_DELEGATION_IDLE_EXPIRY_SECONDS", "60")
    assert cd.load_limits() == cd.Limits(3, 1, 60)


def test_an_invalid_setting_stops_an_open_task_without_asking_anything(monkeypatch):
    ask = start_task()
    monkeypatch.setenv("CMO_DELEGATION_MAX_REASKS", "nope")
    out = reply(ask, "steel water bottle")
    assert isinstance(out, cd.ConfigBlocked) and "CONFIG_INVALID" in out.text


# ------------------------------------------------------------------------------------------------ the question limit (8 asked, 9th never)
def test_the_eighth_question_is_asked_and_the_ninth_is_never_asked():
    ask = start_task()
    assert ask.card["delegation"]["questionCount"] == 1
    asked = [ask]
    # product: 2 re-asks (questions 2, 3), then a good answer -> marketplace is question 4
    for bad in ("it", "this product"):
        ask = reply(ask, bad)
        asked.append(ask)
    ask = reply(ask, "steel water bottle")
    asked.append(ask)
    assert ask.card["slot"] == "marketplace" and ask.card["delegation"]["questionCount"] == 4
    for bad in ("the big one", "whichever"):  # marketplace re-asks: questions 5, 6
        ask = reply(ask, bad)
        asked.append(ask)
    ask = reply(ask, "Amazon")  # the seller's title is question 7
    asked.append(ask)
    assert ask.card["slot"] == "seller_title" and ask.card["delegation"]["questionCount"] == 7
    ask = reply(ask, "x" * 501)  # too long: re-ask 1 of the title is question 8 - ALLOWED
    asked.append(ask)
    assert isinstance(ask, ins.Ask) and ask.card["slot"] == "seller_title" and ask.card["delegation"]["questionCount"] == 8 and len(asked) == 8
    assert all(isinstance(a, ins.Ask) and a.card["kind"] == "INPUT" for a in asked)
    ninth = reply(ask, "y" * 501)  # re-ask 2 would be question 9: refused, even though the re-ask limit (2) is not exceeded
    assert isinstance(ninth, ins.Ask) and ninth.card["slot"] == "restart" and ninth.card["delegation"]["status"] == "LIMIT"
    assert "8 questions" in ninth.text and "Nothing was run, sent or used up" in ninth.text and "your title" in ninth.text
    assert [o["key"] for o in ninth.card["options"]] == ["restart", "cancel"]
    assert ninth.card["pending"]["collected"] == {"product_name": "steel water bottle", "marketplace": "AMAZON"}  # what was gathered is kept and shown


def test_a_lower_question_limit_is_honoured(monkeypatch):
    monkeypatch.setenv("CMO_DELEGATION_MAX_QUESTIONS", "2")
    ask = start_task()
    second = reply(ask, "it")  # question 2: allowed
    assert second.card["slot"] == "product_name" and second.card["delegation"]["questionCount"] == 2
    third = reply(second, "this one")  # question 3: refused
    assert third.card["slot"] == "restart" and "2 questions" in third.text


def test_answering_the_last_question_needs_no_further_question_even_at_the_limit(monkeypatch):
    monkeypatch.setenv("CMO_DELEGATION_MAX_QUESTIONS", "3")
    ask = start_task()
    ask = reply(ask, "steel water bottle")
    ask = reply(ask, "Amazon")
    assert ask.card["delegation"]["questionCount"] == 3
    done = reply(ask, "Steel Water Bottle 1L Insulated")
    assert isinstance(done, ins.Done) and done.inputs == {"product_name": "steel water bottle", "marketplace": "AMAZON", "seller_title": "Steel Water Bottle 1L Insulated", "sku": "steel-water-bottle"}


# ------------------------------------------------------------------------------------------------ the re-ask limit (a field asked at most 3 times)
def test_a_field_is_asked_at_most_three_times_then_the_task_stops(monkeypatch):
    monkeypatch.setenv("CMO_DELEGATION_MAX_QUESTIONS", "50")  # isolate the re-ask limit
    ask = start_task()                      # ask 1
    ask = reply(ask, "it")                  # re-ask 1 (ask 2): allowed
    assert ask.card["slot"] == "product_name" and ask.card["delegation"]["reaskCounts"] == {"product_name": 1} and "Please name the product" in ask.text
    ask = reply(ask, "this product")        # re-ask 2 (ask 3): allowed
    assert ask.card["slot"] == "product_name" and ask.card["delegation"]["reaskCounts"] == {"product_name": 2}
    blocked = reply(ask, "that")            # re-ask 3: never asked
    assert blocked.card["slot"] == "restart" and blocked.card["delegation"]["status"] == "LIMIT"
    assert "3 tries" in blocked.text and "the product" in blocked.text and "instead of guessing" in blocked.text


def test_a_lower_reask_limit_is_honoured(monkeypatch):
    monkeypatch.setenv("CMO_DELEGATION_MAX_REASKS", "1")
    ask = reply(start_task(), "it")
    assert ask.card["slot"] == "product_name"
    assert reply(ask, "it").card["slot"] == "restart"


def test_a_good_answer_does_not_carry_the_reask_count_to_the_next_field():
    ask = reply(start_task(), "it")
    ask = reply(ask, "steel water bottle")
    assert ask.card["slot"] == "marketplace" and ask.card["delegation"]["reaskCounts"] == {"product_name": 1}
    assert reply(ask, "no idea what that is").card["delegation"]["reaskCounts"] == {"product_name": 1, "marketplace": 1}


def test_restart_resets_the_counters_and_offers_the_earlier_answer_for_confirmation_not_silently_reusing_it(monkeypatch):
    monkeypatch.setenv("CMO_DELEGATION_MAX_REASKS", "1")
    ask = reply(start_task(), "steel water bottle")
    ask = reply(ask, "the big one")
    blocked = reply(ask, "whichever")
    assert blocked.card["slot"] == "restart"
    again = cd.advance(blocked.card, option_key="restart", text="", ctx=CTX, now=at(5))
    assert again.card["slot"] == "product_name" and again.card["delegation"]["questionCount"] == 1 and again.card["delegation"]["reaskCounts"] == {}
    assert again.card["pending"]["collected"] == {}  # nothing is silently reused
    offered = again.card["options"][0]
    assert offered["key"] == "prev" and offered["value"] == "steel water bottle" and offered["kind"] == "RECOMMENDED"
    nxt = cd.advance(again.card, option_key="prev", text="", ctx=CTX, now=at(6))  # choosing it IS the confirmation
    assert nxt.card["pending"]["collected"] == {"product_name": "steel water bottle"} and nxt.card["slot"] == "marketplace"


def test_a_typed_reply_in_the_limit_state_repeats_the_choice_and_changes_nothing():
    ask = start_task()
    for _ in range(3):
        ask = reply(ask, "it")
    again = reply(ask, "steel water bottle")  # not an answer to this question
    assert again.card["slot"] == "restart" and again.card["delegation"]["status"] == "LIMIT" and again.card["pending"]["collected"] == {}


# ------------------------------------------------------------------------------------------------ idle expiry (86399 live, 86400 expired)
def test_86399_seconds_idle_is_live_and_86400_is_expired():
    ask = start_task()
    live = reply(ask, "steel water bottle", now=at(86399))
    assert live.card["slot"] == "marketplace" and live.card["delegation"]["status"] == "LIVE" and live.card["pending"]["collected"] == {"product_name": "steel water bottle"}
    expired = reply(ask, "steel water bottle", now=at(86400))
    assert expired.card["slot"] == "continue" and expired.card["delegation"]["status"] == "EXPIRED"
    assert expired.card["pending"]["collected"] == {}  # the late answer was NOT applied: the seller must confirm first
    assert "Nothing has run" in expired.text and [o["key"] for o in expired.card["options"]] == ["continue", "restart", "cancel"]


def test_expiry_is_measured_from_the_last_activity_not_from_the_start():
    ask = start_task()
    ask = reply(ask, "steel water bottle", now=at(80000))  # activity resets the clock
    assert reply(ask, "Amazon", now=at(80000 + 86399)).card["slot"] == "seller_title"
    assert reply(ask, "Amazon", now=at(80000 + 86400)).card["slot"] == "continue"


def test_an_expiry_setting_is_honoured(monkeypatch):
    monkeypatch.setenv("CMO_DELEGATION_IDLE_EXPIRY_SECONDS", "60")
    ask = start_task()
    assert reply(ask, "steel water bottle", now=at(59)).card["slot"] == "marketplace"
    assert reply(ask, "steel water bottle", now=at(60)).card["slot"] == "continue"


def test_after_expiry_the_answers_are_kept_but_nothing_runs_until_the_seller_confirms():
    ask = reply(start_task(), "steel water bottle")
    ask = reply(ask, "Amazon")  # seller_title is the last question
    expired = reply(ask, "Steel Water Bottle 1L", now=at(86400))
    assert expired.card["pending"]["collected"] == {"product_name": "steel water bottle", "marketplace": "AMAZON"}  # preserved
    typed = cd.advance(expired.card, option_key=None, text="Steel Water Bottle 1L", ctx=CTX, now=at(86401))  # an answer is not a confirmation
    assert isinstance(typed, ins.Ask) and typed.card["slot"] == "continue"
    cont = cd.advance(expired.card, option_key="continue", text="", ctx=CTX, now=at(86402))
    assert cont.card["slot"] == "seller_title" and cont.card["delegation"]["status"] == "LIVE"
    assert cont.card["pending"]["collected"] == {"product_name": "steel water bottle", "marketplace": "AMAZON"}
    nxt = cd.advance(cont.card, option_key=None, text="Steel Water Bottle 1L", ctx=CTX, now=at(86403))
    for _ in range(3):  # the skippable extra details (brand, size, key features) are asked next; each can be skipped
        assert isinstance(nxt, ins.Ask) and nxt.card["slot"].startswith("fact_")
        nxt = cd.advance(nxt.card, option_key=None, text="skip", ctx=CTX, now=at(86404))
    assert isinstance(nxt, ins.Done) and "attributes" not in nxt.inputs and "brand" not in nxt.inputs


def test_the_expiry_confirmation_can_be_typed_and_restart_works_from_it():
    ask = reply(start_task(), "steel water bottle")
    expired = reply(ask, "Amazon", now=at(86400))
    cont = cd.advance(expired.card, option_key=None, text="continue", ctx=CTX, now=at(86401))
    assert cont.card["slot"] == "marketplace" and cont.card["pending"]["collected"] == {"product_name": "steel water bottle"}
    restarted = cd.advance(expired.card, option_key=None, text="start again", ctx=CTX, now=at(86401))
    assert restarted.card["slot"] == "product_name" and restarted.card["pending"]["collected"] == {} and restarted.card["delegation"]["previous"] == {"product_name": "steel water bottle"}


def test_cancel_works_in_every_state():
    live = start_task()
    assert isinstance(reply(live, "", option="cancel"), ins.Cancelled) and isinstance(reply(live, "cancel"), ins.Cancelled)
    limit = live
    for _ in range(3):
        limit = reply(limit, "it")
    assert isinstance(cd.advance(limit.card, option_key="cancel", text="", ctx=CTX, now=T0), ins.Cancelled)
    expired = reply(live, "x", now=at(86400))
    assert isinstance(cd.advance(expired.card, option_key=None, text="never mind", ctx=CTX, now=T0), ins.Cancelled)


# ------------------------------------------------------------------------------------------------ confirmed facts are preserved (AC-D6)
def test_the_collected_answers_travel_on_every_question_card():
    ask = reply(start_task(), "steel water bottle")
    ask = reply(ask, "Flipkart")
    assert ask.card["pending"]["collected"] == {"product_name": "steel water bottle", "marketplace": "FLIPKART"}
    back = reply(ask, "", option="back")  # stepping back removes only the last answer
    assert back.card["slot"] == "marketplace" and back.card["pending"]["collected"] == {"product_name": "steel water bottle"}


def _msg(collected):
    return {"choices": {"pending": {"collected": collected}}}


def test_a_pronoun_carries_the_product_given_earlier_and_a_named_product_wins():
    msgs = [_msg({"product_name": "steel water bottle"}), {"choices": None}]
    assert cd.prefill_for("cmo.generate_hashtags", {"product": "it"}, msgs)["product"] == "steel water bottle"
    assert cd.prefill_for("cmo.generate_hashtags", {}, msgs)["product"] == "steel water bottle"
    assert cd.prefill_for("cmo.generate_hashtags", {"product": "this product"}, msgs)["product"] == "steel water bottle"
    assert cd.prefill_for("cmo.generate_hashtags", {"product": "copper mug"}, msgs)["product"] == "copper mug"
    assert "product" not in cd.prefill_for("cmo.generate_hashtags", {"product": "it"}, [])  # nothing to refer to: the product is asked for, never guessed
    assert cd.prefill_for("cmo.market_trends", {"product": "it"}, msgs) == {"product": "it"}  # trends are not about a product


def test_the_product_is_also_found_in_a_stored_plan_when_no_question_was_ever_asked():
    plans = [{"plan": {"legs": [{"slots": {"product_name": "steel water bottle", "marketplace": "AMAZON"}}]}}]
    assert cd.prefill_for("cmo.generate_title_sets", {"product": "it"}, [], plans)["product"] == "steel water bottle"


def test_a_pronoun_is_never_accepted_as_a_product_name():
    ask = start_task()
    for word in ("it", "this", "the same product", "my product"):
        out = reply(ask, word)
        assert out.card["slot"] == "product_name" and "Please name the product" in out.text, word
