"""CMO 3.0 M6, N-15g through the CEO chat: an edit sentence that names neither product nor marketplace is AMBIGUOUS when more than one listing is saved (the CEO asks which and changes nothing);
a loose "make bullet 2 shorter" / "Change bullet 2" is not an edit sentence, so it is never guessed: the seller is told the exact words that work (free, no model, no unit)."""

from __future__ import annotations

import os

import pytest

from tests.integration.test_ceo_cmo_delegation import chat, new_investigation, say  # noqa: F401
from tests.integration.test_ceo_cmo_m6_chat import SKU, counts, last_answer, listed
from tests.integration.test_cmo_api import FLIPKART, _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import body

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


def test_an_edit_naming_neither_product_nor_marketplace_asks_which_when_two_listings_exist_and_changes_nothing(chat):
    inv = listed(chat)
    assert chat.env.post("full-listing", {**body("fk"), "sku": SKU, "marketplace": FLIPKART}).json()["status"] == "COMPLETE"  # the same product now also has a Flipkart listing
    before = counts(chat)
    r = say(chat, inv, "Change bullet 2 to: Holds 1 litre of water")
    msg = last_answer(chat, inv)
    assert msg["choices"] is None and "more than one listing" in msg["content"] and "Amazon" in msg["content"] and "Flipkart" in msg["content"] and "which one" in msg["content"], (r, msg)
    assert counts(chat) == before  # nothing was changed, charged or generated
    r = say(chat, inv, "For my AquaNest 1 Litre Stainless Steel Water Bottle, change bullet 2 on Flipkart to: Holds 1 litre of water")
    done = last_answer(chat, inv)
    assert done["choices"], done["content"]
    assert done["choices"]["kind"] == "LISTING" and done["choices"]["marketplace"] == "FLIPKART" and done["choices"]["sections"]["bullets"][1] == "Holds 1 litre of water", r
    gid = chat.env.q(f"SELECT id::text FROM cmo_generation WHERE sku = '{SKU}' AND marketplace = 'AMAZON' AND output_type = 'LISTING_COPY' ORDER BY created_at LIMIT 1")[0][0]
    amazon = chat.env.client().get(f"/api/v1/cmo/listing/{gid}", headers=chat.env.headers).json()
    assert amazon["sections"]["bullets"][1] != "Holds 1 litre of water"  # only the named marketplace's listing changed


@pytest.mark.parametrize("loose", ["make bullet 2 shorter", "Change bullet 2", "please shorten the description", "improve bullet 3."])
def test_a_loose_edit_request_is_never_guessed_and_the_seller_is_told_what_works(chat, loose):
    inv = listed(chat)
    before = counts(chat)
    say(chat, inv, loose)
    msg = last_answer(chat, inv)
    assert msg["choices"] is None and "exact words" in msg["content"] and "to: your text" in msg["content"] and "costs 1 CMO unit" in msg["content"] and "plan" in msg["content"], msg
    assert counts(chat) == before


def test_a_loose_request_without_any_saved_listing_is_routed_as_before(chat):
    from tests.integration.test_ceo_cmo_m6_chat import seed  # noqa: PLC0415

    seed(chat)
    inv = new_investigation(chat)
    r = say(chat, inv, "make bullet 2 shorter")
    assert "exact words" not in (r.get("answer") or "")


def test_n16c_in_chat_a_title_over_the_verified_limit_is_refused_before_any_plan_card(chat):
    from sqlalchemy import text  # noqa: PLC0415

    from tests.integration.test_ceo_cmo_m6_chat import converse, plan_messages, seed  # noqa: PLC0415
    from tests.integration.test_cmo_m6_integration import TITLE  # noqa: PLC0415

    seed(chat)
    with chat.env.engine.begin() as conn:
        conn.execute(text("INSERT INTO format_constraint (marketplace, title_max_chars, title_option_count, bullet_count, bullet_max_chars, description_type, description_max_chars, keywords_max_count, "
                          "keywords_max_chars, backend_terms_max_bytes, count_rule, source_url, verified_at, version, row_kind) VALUES ('AMAZON', 20, 3, 3, 200, 'plain', 900, 10, 40, 249, "
                          "'UTF16_CODE_UNITS', 'https://example.invalid/test-fixture', now(), 1, 'TEST_FIXTURE')"))
    inv = new_investigation(chat)
    r = converse(chat, inv)
    assert r["status"] != "PLANNED" and r.get("plan") is None and plan_messages(chat, inv) == [], r
    assert "at most 20 characters" in r["answer"] and f"is {len(TITLE)} characters" in r["answer"] and "shorter title" in r["answer"], r["answer"]
    assert chat.env.n("cmo_generation") == 0 and chat.env.n("metered_event", "agent_code = 'CMO'") == 0
    assert chat.env.n("cmo_title_approval") == 0 and chat.env.n("cmo_title_approval", "title_source = 'SELLER_TYPED'") == 0  # no typed-title approval row was saved for the refused title
    assert chat.env.n("cmo_listing_audit") == 0 and chat.env.n("cmo_quota_reservation") == 0  # no listing was generated or audited and no unit was reserved
    assert "I have not approved, saved or cut your title, and nothing was charged" in r["answer"] and "could not use that title" not in r["answer"]  # the specific verified-limit wording, not the generic refusal
