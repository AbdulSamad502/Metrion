"""CMO 3.0 M6 preconditions (spec 6.18.2; acceptance N-05h, N-05i): contradictory confirmed facts are never resolved silently, and missing details are named."""

from __future__ import annotations

from slim_cmo.claims import Attribute
from slim_cmo.listing import preconditions as pre
from slim_cmo.types import AttributeBasis

SP = AttributeBasis.SELLER_PROVIDED


def A(name, value, basis=SP):
    return Attribute(name, value, basis)


def test_agreeing_facts_have_no_contradiction():
    assert pre.contradictions([A("Size", "1 litre"), A("Capacity", "1000 ml"), A("Colour", "Silver"), A("color", "silver"), A("Material", "stainless steel")]) == []


def test_two_different_capacities_under_two_names_contradict():
    got = pre.contradictions([A("Size", "500 ml"), A("Capacity", "1 litre")])
    assert got == [{"detail": "capacity", "values": ["1 litre", "500 ml"]}]


def test_two_different_colours_contradict_but_a_repeated_one_does_not():
    assert pre.contradictions([A("Color", "silver"), A("Colour", "blue")])[0]["detail"] == "colour"
    assert pre.contradictions([A("Color", "Silver"), A("Colour", "silver ")]) == []


def test_unconfirmed_values_never_create_a_contradiction():
    assert pre.contradictions([A("Size", "1 litre"), A("Capacity", "750 ml", AttributeBasis.ESTIMATED), A("Colour", "red", AttributeBasis.IMAGE_OBSERVED)]) == []


def test_missing_facts_are_named_in_plain_words():
    assert pre.missing_facts([A("brand", "AquaNest")]) == ["Size or capacity", "Material"]
    assert pre.missing_facts([A("brand", "AquaNest"), A("Volume", "1 litre"), A("material", "steel")]) == []
    assert pre.missing_facts([A("size", "1 litre", AttributeBasis.ESTIMATED), A("brand", "x"), A("material", "y")]) == ["Size or capacity"]


# ---------------------------------------------------------------- the topic of a model rewrite (N-15c)
def test_a_topic_is_supported_only_when_one_confirmed_detail_carries_all_its_words():
    facts = [A("Opening", "wide"), A("Material", "stainless steel"), A("Brand", "AquaNest")]
    assert pre.topic_supported("wide opening", facts) and pre.topic_supported("stainless steel", facts) and pre.topic_supported("Material", facts)
    assert not pre.topic_supported("keeps drinks cold", facts)  # nothing the seller confirmed says so
    assert not pre.topic_supported("wide steel", facts)  # words from two different details are not one confirmed fact
    assert not pre.topic_supported("", facts) and not pre.topic_supported("   ", facts)


def test_an_unconfirmed_or_empty_detail_never_supports_a_topic():
    assert not pre.topic_supported("wide opening", [A("Opening", "")])
    assert not pre.topic_supported("wide opening", [])
