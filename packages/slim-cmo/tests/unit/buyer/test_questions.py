"""CMO 3.0 M5 buyer questions (N-10, N-11): answers only from the seller's confirmed facts; NOT CONFIRMED otherwise; seller-unknown is a settled do-not-claim; no demand claim."""

from __future__ import annotations

from datetime import datetime, timezone

from slim_cmo.buyer.questions import CONFIRMED, NOT_CONFIRMED, SELLER_UNKNOWN, TOPICS, analyse, is_unknown_value, topic_for_label

D = datetime(2026, 10, 28, tzinfo=timezone.utc)
NAME = "AquaNest 1 Litre Stainless Steel Water Bottle"


def attr(label, value, source="you told me"):
    return {"label": label, "value": value, "source": source, "at": D, "history": []}


def profile(*attrs):
    return {"name": NAME, "attributes": list(attrs), "notes": [], "notConfirmed": []}


def by_id(r):
    return {q["id"]: q for q in r["questions"]}


def test_a_drinkware_product_gets_the_drinkware_questions_and_a_generic_one_does_not():
    bottle = by_id(analyse(profile(), NAME))
    assert {"insulated", "leakproof", "dishwasher", "bpa", "lid"} <= set(bottle) and {"material", "size", "color", "brand"} <= set(bottle)
    lamp = by_id(analyse(profile(), "Desk Lamp LED"))
    assert "insulated" not in lamp and "leakproof" not in lamp and "material" in lamp


def test_confirmed_facts_answer_the_question_with_the_sellers_own_words_and_source():
    q = by_id(analyse(profile(attr("Material", "stainless steel"), attr("Size", "1 litre"), attr("Brand", "AquaNest"), attr("Color", "silver", "confirmed by you from a photo reading")), NAME))
    assert q["material"]["status"] == CONFIRMED and q["material"]["answer"] == "stainless steel" and q["material"]["source"] == {"label": "Material", "origin": "you told me", "at": "2026-10-28"}
    assert q["color"]["source"]["origin"] == "confirmed by you from a photo reading" and q["size"]["answer"] == "1 litre"
    assert "exactly as you stated it" in q["material"]["listingUse"]


def test_an_unanswered_question_is_not_confirmed_asks_for_the_detail_and_is_never_answered_from_knowledge():
    q = by_id(analyse(profile(attr("Material", "stainless steel")), NAME))
    for qid in ("insulated", "leakproof", "dishwasher", "bpa", "warranty"):
        assert q[qid]["status"] == NOT_CONFIRMED and q[qid]["answer"] is None and "Tell me about its" in q[qid]["ask"] and q[qid]["source"] is None
    assert "Must NOT be claimed" in q["insulated"]["listingUse"] and "Not stated in your listing" in q["weight"]["listingUse"]


def test_when_the_seller_says_they_do_not_know_it_is_a_settled_do_not_claim_not_an_answer():
    q = by_id(analyse(profile(attr("Insulated", "not tested"), attr("Dishwasher safe", "Unknown"), attr("Leakproof", "I haven't tested it")), NAME))
    for qid in ("insulated", "dishwasher", "leakproof"):
        assert q[qid]["status"] == SELLER_UNKNOWN and q[qid]["answer"] is None and "I will not claim it" in q[qid]["ask"]


def test_a_claim_in_a_feature_list_counts_but_only_when_it_is_not_a_negative():
    q = by_id(analyse(profile(attr("Key Features", "reusable, dishwasher safe, tested by me")), NAME))
    assert q["dishwasher"]["status"] == CONFIRMED and "dishwasher safe" in q["dishwasher"]["answer"]
    q2 = by_id(analyse(profile(attr("Key Features", "dishwasher safe: not tested")), NAME))
    assert q2["dishwasher"]["status"] != CONFIRMED or "not tested" not in (q2["dishwasher"]["answer"] or "")


def test_competitor_themes_flag_a_question_as_competitor_relevant_and_sort_it_first_without_any_demand_claim():
    r = analyse(profile(), NAME, ci_stems=["insulated", "durable"], ci_listing_count=3)
    q = by_id(r)
    assert q["insulated"]["importance"] == "COMPETITOR_RELEVANT" and r["questions"][0]["id"] == "insulated"
    assert any(e["kind"] == "COMPETITOR_THEME" and "3 listings" in e["detail"] for e in q["insulated"]["evidence"])
    assert by_id(analyse(profile(), NAME))["insulated"]["importance"] == "LIKELY"  # without competitor evidence it is only "commonly asked"
    text = " ".join(r["limits"]).lower()
    assert "not drawn from search, review or marketplace q&a data" in text and "how often" in text


def test_no_question_states_how_often_it_is_asked():
    import json

    blob = json.dumps(analyse(profile(), NAME)).lower()
    for banned in ("most asked", "top question", "% of buyers", "searches", "popular"):
        assert banned not in blob


def test_counts_and_ordering_are_stable():
    r = analyse(profile(attr("Material", "steel")), NAME)
    assert r["counts"][CONFIRMED] == 1 and r["counts"][NOT_CONFIRMED] == len(r["questions"]) - 1
    assert analyse(profile(attr("Material", "steel")), NAME) == r


def test_unknown_value_detection_and_topic_labels():
    assert all(is_unknown_value(v) for v in ("no", "Not tested", "unknown", "N/A", "I don't know", "not sure", "haven't tested"))
    assert not any(is_unknown_value(v) for v in ("yes", "dishwasher safe", "tested and safe", "notable steel"))
    assert topic_for_label("  Dishwasher   SAFE ") is not None and topic_for_label("colour of the moon") is None
    assert len({t.id for t in TOPICS}) == len(TOPICS) and len({t.label.casefold() for t in TOPICS}) == len(TOPICS)
