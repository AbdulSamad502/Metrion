"""CMO 3.0 M0, end to end through the real CEO chat (HTTP -> orchestrator -> real registry and CMO handlers -> real Postgres; only the CMO's language model is a deterministic fake).

The seller's whole journey: titles -> plan card -> approve -> CHOOSE one in chat -> the choice is saved (free, nothing published) -> the description is grounded on the approved title ->
history shows what was chosen -> "is it dishwasher safe?" is "not confirmed" -> "does copying mean it was published?" is "no"."""

from __future__ import annotations

import os
import uuid

import pytest

from tests.integration.test_ceo_cmo_delegation import approve, ask_for_titles, chat, cmo_counts, messages, say, skip_extras  # noqa: F401
from tests.integration.test_ceo_cmo_image_handoff import confirm_facts, photo, read_the_photo  # noqa: F401
from tests.integration.test_cmo_api import TITLES, _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


def written_titles(c):
    inv, planned = ask_for_titles(c)
    body = approve(c, inv, planned["plan"]).json()
    assert body["status"] == "DELIVERED", body
    return inv, body


def test_titles_are_saved_against_a_stable_product_and_the_answer_says_how_to_choose(chat):
    c = chat
    inv, body = written_titles(c)
    assert "To choose one, say" in body["answer"] and "nothing is published" in body["answer"]
    assert c.env.q("SELECT DISTINCT sku FROM cmo_generation WHERE output_type = 'TITLE_SET'")[0][0] == "steel-bottle"
    assert c.env.n("seller_fact", "sku = 'steel-bottle' AND attribute_name = 'product_name'") == 1


def test_the_seller_chooses_a_title_in_chat_for_free_and_nothing_is_published(chat):
    c, e = chat, chat.env
    inv, _ = written_titles(c)
    before = cmo_counts(c)
    ask = say(c, inv, "use option 2")
    assert ask["status"] == "CLARIFIED" and ask["choices"]["slot"] == "title_pick" and ask["choices"]["playbook"] == "cmo.approve_title"
    assert all(f"{i}. {t}" in ask["answer"] for i, t in enumerate(TITLES, start=1))  # the exact saved options, numbered
    for typed in ("yes", "ok"):  # a bare yes is not a title
        again = say(c, inv, typed)
        assert again["status"] == "CLARIFIED" and again["choices"]["slot"] == "title_pick"
    assert e.n("cmo_title_approval") == 0
    done = say(c, inv, "2")
    assert done["status"] == "DELIVERED", done
    assert "Your title choice is saved." in done["answer"] and TITLES[1] in done["answer"] and "Nothing was published" in done["answer"]
    assert e.n("cmo_title_approval") == 1 and e.q("SELECT approved_text, edited_by_seller FROM cmo_title_approval")[0] == (TITLES[1], False)
    after = cmo_counts(c)
    assert after["cmo_events"] == before["cmo_events"] and after["model_calls"] == before["model_calls"]  # no CMO unit, no model call


def test_the_description_is_grounded_on_the_approved_title_and_the_plan_card_says_so(chat):
    c, e = chat, chat.env
    inv, _ = written_titles(c)
    say(c, inv, "use option 2")
    say(c, inv, "2")
    q = say(c, inv, "write a description for my steel bottle on amazon")
    assert q["status"] == "CLARIFIED" and q["choices"]["slot"] == "seller_title", q
    assert any(o["value"] == TITLES[1] and "approved" in o["label"] for o in q["choices"]["options"])  # the approved title is offered first
    planned = skip_extras(c, inv, say(c, inv, TITLES[1]))
    assert planned["status"] == "PLANNED", planned
    leg = planned["plan"]["plan"]["legs"][0]
    assert leg["action_key"] == "cmo.generate_description" and "approval_id" in leg["slots"] and not leg["slots"].get("seller_title")
    assert f"Written from the title you approved: “{TITLES[1]}”." in planned["plan"]["plan"]["summary_text"]
    body = approve(c, inv, planned["plan"]).json()
    assert body["status"] == "DELIVERED", body
    row = e.q("SELECT grounding_basis, grounding_approval_id FROM cmo_generation WHERE output_type = 'DESCRIPTION'")[0]
    assert row[0] == "APPROVED_TITLE" and row[1] is not None


def test_a_different_typed_title_stays_a_seller_supplied_title(chat):
    c, e = chat, chat.env
    inv, _ = written_titles(c)
    say(c, inv, "use option 2")
    say(c, inv, "2")
    say(c, inv, "write a description for my steel bottle on amazon")
    planned = skip_extras(c, inv, say(c, inv, "AquaKeep Steel Bottle Silver"))
    leg = planned["plan"]["plan"]["legs"][0]
    assert leg["slots"]["seller_title"] == "AquaKeep Steel Bottle Silver" and "approval_id" not in leg["slots"]


def test_history_in_chat_lists_the_chosen_title_and_says_copying_is_not_publishing(chat):
    c = chat
    inv, _ = written_titles(c)
    empty = say(c, inv, "Show my previously selected Amazon title and description")
    assert "Titles you chose" not in empty["answer"]  # nothing chosen yet: nothing claimed
    say(c, inv, "use option 3")
    say(c, inv, "3")
    shown = say(c, inv, "Show my previously selected Amazon title and description")
    assert "Titles you chose" in shown["answer"] and TITLES[2] in shown["answer"] and "approved by you on" in shown["answer"]
    no = say(c, inv, "If I copy a title or mark it used, does that mean it was published on Amazon?")
    assert no["answer"].startswith("No.") and "does not prove" in no["answer"]


def test_a_property_question_is_not_confirmed_unless_the_seller_said_it(chat):
    c = chat
    inv, _ = written_titles(c)
    r = say(c, inv, "Is my steel bottle dishwasher safe?")
    assert r["status"] == "DELIVERED" and "has not been confirmed" in r["answer"] and "steel bottle" in r["answer"]
    assert "will not state it in any title" in r["answer"]
    assert cmo_counts(c)["model_calls"] == 1  # only the title run: the answer came from code, not a model


def test_with_no_title_options_the_choice_says_so_and_nothing_is_saved(chat):
    c = chat
    inv = c.client.post("/api/v1/ceo/investigations", json={"title": "x"}, headers=c.env.headers).json()["investigationId"]
    r = say(c, inv, "use option 2")
    assert "no title options" in r["answer"].lower() and c.env.n("cmo_title_approval") == 0


def test_another_tenants_titles_are_never_offered(chat):
    c = chat
    written_titles(c)
    other, headers = c.env.other_tenant()
    inv = c.client.post("/api/v1/ceo/investigations", json={"title": "x"}, headers=headers).json()["investigationId"]
    r = say(c, inv, "use option 2", headers=headers)
    assert TITLES[0] not in r["answer"] and "no title options" in r["answer"].lower()


def test_the_title_choice_is_audited_as_a_child_of_the_ceo_turn(chat):
    c, e = chat, chat.env
    inv, _ = written_titles(c)
    say(c, inv, "use option 1")
    say(c, inv, "1")
    runs = e.q("SELECT agent_id, trigger_ref, parent_run_id FROM agent_run WHERE trigger_ref = 'cmo.approve_title'")
    assert len(runs) == 1 and runs[0][0] == "CMO" and runs[0][2] is not None
    assert uuid.UUID(str(runs[0][2]))


def test_what_the_seller_confirmed_from_a_photo_is_recorded_as_their_statement_linked_to_the_reading_for_zero_units(photo):
    p, e = photo, photo.c.env
    inv, _att, _planned, _body = read_the_photo(p)
    last, _asked = confirm_facts(p, inv)
    assert last["status"] == "PLANNED"
    rows = {r[0]: (r[1], r[2]) for r in e.q("SELECT attribute_name, fact_value, image_analysis_id FROM seller_fact WHERE image_analysis_id IS NOT NULL")}
    assert rows["color"][0] == "silver" and rows["material"][0] == "steel" and rows["brand"][0] == "AquaKeep"  # the seller's own (corrected) values
    assert len({v[1] for v in rows.values()}) == 1  # all linked to the one reading
    assert e.n("agent_run", "trigger_ref = 'cmo.confirm_image_hint'") == 3 and e.events() == [] and e.reservations() == []


def test_catalog_details_are_asked_in_chat_planned_with_no_model_and_answered_with_how_sure_each_one_is(chat):
    c, e = chat, chat.env
    inv = c.client.post("/api/v1/ceo/investigations", json={"title": "Catalog"}, headers=e.headers).json()["investigationId"]
    q1 = say(c, inv, "what are the colour and material of my steel bottle")
    assert q1["status"] == "CLARIFIED" and q1["choices"]["playbook"] == "cmo.catalog_answer", q1
    r = q1
    for a in ("steel bottle", "colour and material"):
        if r["choices"]["slot"] in ("product_name", "catalog_questions"):
            r = say(c, inv, a)
    planned = skip_extras(c, inv, r)
    assert planned["status"] == "PLANNED", planned
    leg = planned["plan"]["plan"]["legs"][0]
    assert leg["action_key"] == "cmo.catalog_answer" and leg["slots"]["questions"] == ["COLOR", "MATERIAL"] and leg["slots"]["sku"] == "steel-bottle"
    card = planned["plan"]["plan"]["summary_text"]
    assert "No language model is used" in card and "Quota effect: 1 CMO unit" in card
    body = approve(c, inv, planned["plan"]).json()
    assert body["status"] == "DELIVERED", body
    assert "Color: " in body["answer"] and "Material: " in body["answer"] and "not known yet" in body["answer"]  # nothing was said, so nothing is claimed
    assert cmo_counts(c)["model_calls"] == 0 and cmo_counts(c)["cmo_events"] == 1
