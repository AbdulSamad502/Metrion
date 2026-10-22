"""R1: every registered action is classified by what it REALLY does (ceo/effects.py), the approval rule is derived, and the one place a
declared effect would silently become wrong (CI discovery gaining a real search provider) is pinned."""

from __future__ import annotations

import pytest

from backend.ceo.contract import ActionSpec, AgentCode, Effect
from backend.ceo.effects import ACTION_EFFECTS, ActionEffects, External, effects_for
from backend.ceo.registry import ActionRegistry, RegistryError, _with_effects, get_registry


def test_every_registered_action_has_exactly_one_effects_entry_and_vice_versa():
    keys = {s.key for s in get_registry().specs()}
    assert len(keys) == 49  # +1 cfo.query (CFO 2.0 planner)
    assert keys == set(ACTION_EFFECTS)
    assert all(s.effects is ACTION_EFFECTS[s.key] for s in get_registry().specs())


def test_an_unclassified_or_orphaned_action_fails_registry_construction():
    fake = ActionSpec(key="cfo.brand_new_action", source="CFO", agent=AgentCode.CFO, effect=Effect.READ, description="x", invoke=lambda s, c, l: {})
    with pytest.raises(RegistryError, match="unclassified"):
        _with_effects([*get_registry().specs(), fake])
    with pytest.raises(RegistryError, match="orphaned"):
        _with_effects([s for s in get_registry().specs() if s.key != "cfo.pricing"])


def test_the_approval_rule_is_derived_from_meters_and_seller_data_leaving_metrion():
    assert ActionEffects().requires_approval is False
    assert ActionEffects(external=External.MODEL, model_egress=("X",)).requires_approval is False  # an operator-controlled model is internal (Q-S0-2)
    assert ActionEffects(external=External.PUBLIC_FETCH, destinations=("p",)).requires_approval is False  # GST public pages (Q-S0-2)
    assert ActionEffects(meters=("m",)).requires_approval is True  # metered
    assert ActionEffects(external=External.SELLER_DATA_OUT, egress=("e",), destinations=("d",)).requires_approval is True
    assert ActionEffects(force_approval=True).requires_approval is True  # can only ADD approval


def test_inconsistent_metadata_is_refused():
    with pytest.raises(ValueError, match="egress data classes and destinations"):
        ActionEffects(external=External.SELLER_DATA_OUT).validate("x")
    with pytest.raises(ValueError, match="destinations"):
        ActionEffects(external=External.PUBLIC_FETCH).validate("x")
    with pytest.raises(ValueError, match="egress is only meaningful"):
        ActionEffects(egress=("e",)).validate("x")
    with pytest.raises(KeyError, match="classify it"):
        effects_for("nope.nothing")


def test_the_derived_approval_set_is_a_visible_diff_when_it_changes():
    gated = {s.key for s in get_registry().specs() if s.effects.requires_approval}
    assert gated == {
        "cmo.analyze_attachment", "cmo.catalog_answer", "cmo.generate_backend_terms", "cmo.generate_bullets", "cmo.generate_description", "cmo.generate_hashtags",
        "cmo.generate_keywords", "cmo.generate_listing_copy", "cmo.generate_title_sets", "cmo.market_trends", "pi.discover", "pi.supplier_lookup",
        "ci.discover_competitors",
    }


def test_declared_effect_understatements_are_recorded_not_hidden():
    # GST is COMPUTE_PERSIST yet fetches public pages and calls a model; the table says so, and does not gate it (Q-S0-2)
    for key in ("cfo.gst_lookup", "service.gst_lookup"):
        fx = ACTION_EFFECTS[key]
        assert fx.external is External.PUBLIC_FETCH and fx.model_egress == ("PRODUCT_TITLE",) and not fx.requires_approval
    # PI is declared GENERATE_METERED and now names the meters it records (R3), plus the shared niche-run meter for discover
    assert ACTION_EFFECTS["pi.discover"].meters == ("pi.discover", "research.niche_run")
    assert ACTION_EFFECTS["pi.supplier_lookup"].meters == ("pi.supplier_lookup",)
    assert ACTION_EFFECTS["cfo.period_comparison"].external is External.MODEL


def test_every_external_action_names_where_the_data_goes():
    for key, fx in ACTION_EFFECTS.items():
        if fx.external in (External.PUBLIC_FETCH, External.SELLER_DATA_OUT):
            assert fx.destinations, key
        if fx.external is External.SELLER_DATA_OUT:
            assert fx.egress, key
        if fx.external is External.MODEL:
            assert fx.model_egress, key


def test_ci_discovery_is_seller_data_out_because_its_provider_is_tavily():
    """`ci.discover_competitors` sends the seller's product search terms to Tavily (CI spec C34), so it is `SELLER_DATA_OUT` and approval-gated. The composition root
    must pick its provider through `services.ci_search`; if that changes (or the payload does), this row must be reclassified in the same change."""
    import inspect

    from backend.services import ci_actions

    source = inspect.getsource(ci_actions.run_discovery)
    assert "select_search_provider(" in source
    assert "MockSearchProvider" not in source
    fx = ACTION_EFFECTS["ci.discover_competitors"]
    assert fx.external is External.SELLER_DATA_OUT
    assert fx.destinations == ("Tavily",) and fx.egress == ("SELLER_PRODUCT_SEARCH_TERMS",)
    assert fx.requires_approval


def test_the_registry_class_still_accepts_specs_without_effects_for_isolated_tests():
    plain = ActionSpec(key="x.y", source="CFO", agent=AgentCode.CFO, effect=Effect.READ, description="x", invoke=lambda s, c, l: {})
    assert plain.effects is None
    ActionRegistry([plain])  # only the DEFAULT registry demands a classification
