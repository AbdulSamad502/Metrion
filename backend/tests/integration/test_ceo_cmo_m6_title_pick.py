"""CMO 3.0 M6: the title question lists numbered choices. Typing a bare number picks that choice's REAL text (the plan and the generated listing then carry it), never the title "1";
a number with no such choice is refused and re-asked; a choice that is no longer current (the approved title changed after the card was shown) is refused."""

from __future__ import annotations

import os

import pytest

from backend.ceo import input_session
from tests.integration.test_ceo_cmo_delegation import approve, chat, messages, new_investigation, say  # noqa: F401
from tests.integration.test_ceo_cmo_m6_chat import ASK, seed
from tests.integration.test_cmo_api import _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import NAME

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


def to_title_question(c, inv):
    r = say(c, inv, ASK)
    for _ in range(6):
        if str(r.get("clarifyFor", "")) == "seller_title":
            return r
        assert r["status"] == "CLARIFIED", r
        slot = str(r.get("clarifyFor", ""))
        r = say(c, inv, NAME if slot in ("product_name", "product") else "Amazon" if "marketplace" in slot else "skip")
    raise AssertionError(r)


def finish(c, inv, r):
    for _ in range(10):
        if r["status"] != "CLARIFIED":
            return r
        r = say(c, inv, "skip")
    raise AssertionError(r)


def test_typing_1_picks_the_first_listed_choice_not_the_title_1_and_the_plan_and_listing_carry_it(chat):
    seed(chat)
    inv = new_investigation(chat)
    ask = to_title_question(chat, inv)
    choices = [o for o in ask["choices"]["options"] if o["kind"] in ("RECOMMENDED", "ALTERNATIVE")]
    assert choices, ask["choices"]["options"]
    real = choices[0]["value"]
    r = finish(chat, inv, say(chat, inv, "1"))
    assert r["status"] == "PLANNED", r
    leg = r["plan"]["plan"]["legs"][0]
    assert leg["slots"]["seller_title"] == real and leg["slots"]["seller_title"] != "1"
    plan_json = str(r["plan"])
    assert f"Your title: {real}" in plan_json and "Your title: 1'" not in plan_json
    assert approve(chat, inv, r["plan"]).status_code == 200
    card = [m for m in messages(chat, inv) if m["role"] == "CEO" and m["kind"] == "ANSWER"][-1]["choices"]
    assert card["kind"] == "LISTING" and card["sections"]["title"] == real  # the listing is built from that same title


@pytest.mark.parametrize("typed", ["0", "9", "42"])
def test_a_number_with_no_such_choice_is_refused_and_the_question_is_asked_again(chat, typed):
    seed(chat)
    inv = new_investigation(chat)
    to_title_question(chat, inv)
    r = say(chat, inv, typed)
    assert r["status"] == "CLARIFIED" and r["clarifyFor"] == "seller_title" and f"There is no option {typed}" in r["answer"], r
    assert chat.env.n("cmo_generation") == 0


def test_a_real_typed_title_is_still_taken_as_typed(chat):
    seed(chat)
    inv = new_investigation(chat)
    to_title_question(chat, inv)
    r = finish(chat, inv, say(chat, inv, "AquaNest Steel Bottle 1 L Silver"))
    assert r["plan"]["plan"]["legs"][0]["slots"]["seller_title"] == "AquaNest Steel Bottle 1 L Silver"


# ---------------------------------------------------------------- unit-level: ambiguous and stale (the engine seam, no database)
class _O:
    def __init__(self, text):
        self.label, self.text, self.reason, self.unknown = text, text, "", False


def _field(offered):
    return input_session.Field("seller_title", lambda c, g: "Title?", input_session._text(500), lambda c, g: [_O(t) for t in offered()])


def _card(values):
    return {"options": [{"key": f"opt-{i}", "kind": "RECOMMENDED" if i == 0 else "ALTERNATIVE", "value": v} for i, v in enumerate(values)]
            + [{"key": "other", "kind": "OTHER", "value": None}, {"key": "cancel", "kind": "CANCEL", "value": None}]}


def test_ambiguous_numbers_map_to_the_nth_listed_choice_only():
    f = _field(lambda: ["First title", "Second title"])
    card = _card(["First title", "Second title"])
    nt = input_session._numbered_title
    assert nt(f, card, "1", None, None, {}) == "First title"
    assert nt(f, card, "2", None, None, {}) == "Second title"
    assert isinstance(nt(f, card, "3", None, None, {}), input_session.Reject)
    assert isinstance(nt(f, card, "0", None, None, {}), input_session.Reject)
    assert nt(f, card, "2 litre bottle", None, None, {}) is None  # text that merely starts with a digit is a title


def test_a_stale_choice_is_refused_whether_picked_by_number_or_by_button():
    now = ["New approved title", "Product name"]
    f = _field(lambda: now)
    old = _card(["Old approved title", "Product name"])  # the card was shown before the approved title changed
    nt = input_session._numbered_title
    assert isinstance(nt(f, old, "1", None, None, {}), input_session.Reject)
    assert isinstance(nt(f, old, "Old approved title", "opt-0", None, {}), input_session.Reject)
    assert nt(f, old, "2", None, None, {}) == "Product name"  # a choice that is still offered is fine
    assert nt(f, old, "Product name", "opt-1", None, {}) is None


def test_with_no_approved_title_the_question_says_so_and_how_to_get_options_first(chat):
    seed(chat)
    inv = new_investigation(chat)
    ask = to_title_question(chat, inv)
    assert "have not approved a title" in ask["answer"] and "ask me for titles" in ask["answer"]
    assert chat.env.n("cmo_generation") == 0 and chat.env.n("cmo_title_approval") == 0  # asking changes and charges nothing
