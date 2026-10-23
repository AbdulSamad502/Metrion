"""The V1 action registry (spec §6.11, C15, C21, AC22, AC23)."""

from __future__ import annotations

import uuid

import pytest

from backend.auth.permissions import AGENT_CEO, AGENT_CFO, AGENT_CMO, CATALOG_VIEW, INVESTIGATION_VIEW, RESEARCH_MARKET_TRENDS
from backend.ceo.contract import ActionSpec, AgentCode, Effect
from backend.ceo.registry import FORBIDDEN_ACTION_KEYS, ActionRegistry, RegistryError, build_default_registry
from tests.unit.ceo_fakes import owner, partner, spec


@pytest.fixture(scope="module")
def registry() -> ActionRegistry:
    return build_default_registry()


def test_there_is_no_write_effect():
    assert {e.name for e in Effect} == {"READ", "COMPUTE_PERSIST", "GENERATE_METERED", "RECORD_CHOICE", "RECORD_ENTRY", "IMPORT_DATA"}  # the only chat-prepared write is an Expense Tracker entry the seller approved on a plan card (owner decision 2026-10-23, ceo-expense-tracker-chat.md CE2); no other write is expressible (C21)


def test_no_forbidden_write_class_key_is_registered(registry):
    assert not (set(registry.keys()) & FORBIDDEN_ACTION_KEYS)


@pytest.mark.parametrize("key", sorted(FORBIDDEN_ACTION_KEYS))
def test_registering_a_forbidden_action_fails_loudly(key):
    with pytest.raises(RegistryError):
        ActionRegistry([spec(key)])


def test_the_named_exclusions_from_the_spec_are_all_forbidden():
    for key in ("cfo.enter_expense", "cfo.expense_budget_set", "cfo.line_status_override", "cfo.line_count_override",
                "cfo.gst_lookup_accept", "cfo.analyze_gst_lines", "cfo.pnl", "cfo.ingest"):
        assert key in FORBIDDEN_ACTION_KEYS


def test_duplicate_keys_are_rejected():
    with pytest.raises(RegistryError):
        ActionRegistry([spec("a.b"), spec("a.b")])


def test_an_unwired_action_must_say_why():
    with pytest.raises(RegistryError):
        ActionRegistry([ActionSpec(key="x.y", source="CFO", agent=AgentCode.CFO, effect=Effect.READ, description="d")])


def test_fixed_params_must_name_real_slot_fields():
    with pytest.raises(RegistryError):
        ActionRegistry([spec("x.y", fixed_params={"not_a_field": 1})])


def test_every_wired_handler_resolves_and_every_slot_model_forbids_nothing_it_should_not(registry):
    for s in registry.specs():
        if s.wired:
            assert callable(s.invoke), s.key
        else:
            assert s.not_wired_reason, s.key


def test_the_expected_v1_catalog(registry):
    keys = set(registry.keys())
    assert {"cfo.pnl_for_tenant", "cfo.pricing", "cfo.gst_summary", "cfo.period_comparison", "cfo.landed_cost", "cfo.supplier_ranking",
            "cfo.funding_readiness", "cfo.batch_size", "cfo.reconcile", "cfo.anomaly_check", "cfo.financial_health",
            "cfo.cash_reconciliation", "cfo.strategic_briefing", "cfo.preview"} <= keys
    assert {"pi.discover", "pi.supplier_lookup", "pi.report", "ci.request_price_scenario", "ci.discover_competitors"} <= keys
    assert len([k for k in keys if k.startswith("cmo.")]) == 15  # the 13 of §6.9, the pre-send trend preview, and the photo hand-off by reference (cmo.analyze_attachment)


def test_unwired_actions_are_exactly_the_ones_that_need_later_checkpoints(registry):
    assert {s.key for s in registry.specs() if not s.wired} == {"ci.research_now"}  # the GST routes were wired in B4


def test_cmo_actions_match_the_dummy_hub_permission_table(registry):
    """Parity with the table the registry replaces (`ceo_hub_cmo.CMO_DISPATCH_ACTIONS`). Delete this test with that module."""
    from backend.agents.ceo_hub_cmo import CMO_DISPATCH_ACTIONS

    for key, (_handler, extra) in CMO_DISPATCH_ACTIONS.items():
        assert registry.get(key).required_permissions == extra, key
    assert registry.get("cmo.market_trends_preview").required_permissions == (RESEARCH_MARKET_TRENDS,)
    assert registry.get("cmo.suggest_niche_terms").required_permissions == (CATALOG_VIEW,)


def test_cfo_entitlement_codes_match_the_codes_the_routes_enforce(monkeypatch):
    """The preflight must meter the same action the route does, or the two checks would disagree."""
    import backend.entitlement as ent

    seen: dict[str, str] = {}

    def fake(tenant_id, *, direct_action_code, **kw):
        seen[direct_action_code] = direct_action_code
        return _P()

    monkeypatch.setattr(ent, "resolve_cfo_entitlement", fake)  # patched BEFORE the registry binds it
    registry = build_default_registry()
    from backend.api.v1 import cfo as cfo_api

    expected = {
        "cfo.pnl_for_tenant": cfo_api.CFO_PNL, "cfo.pricing": cfo_api.CFO_PRICING, "cfo.gst_summary": cfo_api.CFO_GST_SUMMARY,
        "cfo.period_comparison": cfo_api.CFO_PERIOD_COMPARISON, "cfo.landed_cost": cfo_api.CFO_LANDED_COST,
        "cfo.supplier_ranking": cfo_api.CFO_SUPPLIER_RANKING, "cfo.funding_readiness": cfo_api.CFO_FUNDING_READINESS,
        "cfo.batch_size": cfo_api.CFO_BATCH_SIZE, "cfo.reconcile": cfo_api.CFO_RECONCILE, "cfo.anomaly_check": cfo_api.CFO_ANOMALY_CHECK,
        "cfo.financial_health": cfo_api.CFO_FINANCIAL_HEALTH, "cfo.cash_reconciliation": cfo_api.CFO_CASH_RECONCILIATION,
        "cfo.strategic_briefing": cfo_api.CFO_STRATEGIC_BRIEFING,
    }
    for key, code in expected.items():
        seen.clear()
        registry.get(key).entitlement(uuid.uuid4(), None)  # type: ignore[misc]
        assert list(seen) == [code], key


class _P:
    passed = True


def test_strategic_briefing_never_lets_cfo_narrate_twice(registry):
    assert registry.get("cfo.strategic_briefing").fixed_params == {"include_narration": False}


def test_cfo_preview_is_the_denial_surface_without_an_entitlement_gate(registry):
    s = registry.get("cfo.preview")
    assert s.denial_surface and s.entitlement is None and s.agent is AgentCode.CFO


def test_specialists_that_write_their_own_run_are_marked(registry):
    own = {s.key for s in registry.specs() if s.writes_own_run}
    assert {"pi.discover", "pi.supplier_lookup"} <= own and all(k.startswith(("pi.", "cmo.", "ci.")) for k in own)
    assert not registry.get("cfo.reconcile").writes_own_run  # CFO writes none: the choke point does


def test_required_permissions_are_ceo_plus_agent_plus_extras(registry):
    assert registry.required_permissions(registry.get("cfo.pricing")) == (AGENT_CEO, AGENT_CFO)
    assert registry.required_permissions(registry.get("cmo.market_trends")) == (AGENT_CEO, AGENT_CMO, RESEARCH_MARKET_TRENDS)
    assert registry.required_permissions(registry.get("pi.discover"))[-1] == "research.niche_run"


# ---- catalog_for: the classifier's closed, per-member, per-investigation set (advisory; the choke point re-checks) ----
def test_catalog_is_wired_and_permitted_and_attached(registry):
    ctx = partner(AGENT_CEO, INVESTIGATION_VIEW, AGENT_CFO)
    cat = set(registry.catalog_for(ctx, attached=frozenset({"CFO", "CI"})))
    assert "cfo.pricing" in cat
    assert not any(k.startswith(("pi.", "cmo.", "ci.")) for k in cat)  # CI attached but the member lacks agent.ci
    assert "cfo.gst_lookup" not in cat  # unwired actions are in no catalog


def test_detaching_removes_the_agents_actions_from_the_catalog(registry):
    ctx = owner()
    with_cfo = set(registry.catalog_for(ctx, attached=frozenset({"CFO", "CI", "PI", "CMO"})))
    without_cfo = set(registry.catalog_for(ctx, attached=frozenset({"CI", "PI", "CMO"})))
    assert any(k.startswith("cfo.") for k in with_cfo) and not any(k.startswith("cfo.") for k in without_cfo)
    assert {k for k in without_cfo} == {k for k in with_cfo if not k.startswith("cfo.")}


def test_catalog_for_a_member_with_no_agent_keys_is_empty(registry):
    assert registry.catalog_for(partner(AGENT_CEO), attached=frozenset({"CFO", "CI", "PI", "CMO"})) == ()
