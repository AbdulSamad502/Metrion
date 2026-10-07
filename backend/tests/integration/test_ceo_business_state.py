"""Business State against a real Postgres (spec §6.13, C16, C17, CP1-D3, CP1-D7, AC24, AC26; resolved Q23).

Rows are seeded through the real repositories as `metrion_app`. The two properties most worth proving are (1) a missing input is a
named gap and never a zero, and (2) a state read computes and writes NOTHING.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import text

from backend.auth.permissions import AGENT_CEO, AGENT_CFO, FILES_VIEW
from backend.ceo import business_state as bs
from backend.ceo.contract import EntryStatus, Figure, Gap, Ref, RefKind, Register
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import ALL_AGENTS, T0, ctx_for, insert_leak, later, partner_ctx, row_counts, save_metric, seed_platform_cap

SEP = "2026-09-01/2026-09-30"
AUG = "2026-08-01/2026-08-31"
CFO_ENTRIES = ("BS_PNL_LATEST", "BS_LEAK_OPEN", "BS_DATA_GAPS", "BS_HEALTH_BANDS")
ALL_ENTRIES = tuple(bs.ENTRIES)


def read(ctx, key, *, attached=ALL_AGENTS, **kw):
    return bs.read_entry(ctx, key, attached=frozenset(attached), now=kw.pop("now", later(10)), **kw)


# ------------------------------------------------------------------------------------------- BS_PNL_LATEST
def test_pnl_with_no_data_is_unavailable_never_zero(two_tenants, app_user):
    a, _ = two_tenants
    entry = read(ctx_for(a, user_id=app_user), "BS_PNL_LATEST")
    assert entry.status is EntryStatus.UNAVAILABLE and entry.figures == () and entry.as_of is None
    assert entry.gaps[0].code == "NO_PNL"  # named, not a silent ₹0.00


def test_pnl_picks_the_latest_period_and_newest_computation_and_cites_engine_results(two_tenants, app_user):
    a, _ = two_tenants
    save_metric(a, "CONTRIBUTION_PROFIT", period=AUG, value_paise=111100, computed_at=later(1))
    stale = save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, value_paise=500000, computed_at=later(2))
    newest = save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, value_paise=14230000, computed_at=later(3))  # a recompute of the same period
    rev = save_metric(a, "NET_REALIZED_REVENUE", period=SEP, value_paise=99999900, computed_at=later(3))
    fees = save_metric(a, "MARKETPLACE_FEES", period=SEP, value_paise=1500050, computed_at=later(3))

    entry = read(ctx_for(a, user_id=app_user), "BS_PNL_LATEST")

    assert entry.status is EntryStatus.AVAILABLE and entry.period == SEP and entry.gaps == ()
    by_label = {f.label: f for f in entry.figures}
    assert by_label["Contribution profit"].formatted_value == "₹142,300.00" and by_label["Contribution profit"].ref.id == newest
    assert by_label["Net realized revenue"].formatted_value == "₹999,999.00" and by_label["Net realized revenue"].ref.id == rev
    assert by_label["Marketplace fees"].formatted_value == "₹15,000.50" and by_label["Marketplace fees"].ref.id == fees
    assert stale not in {f.ref.id for f in entry.figures}  # the superseded computation is not shown
    assert all(f.ref.kind is RefKind.ENGINE_RESULT and f.register is Register.DERIVED and f.as_of is not None for f in entry.figures)
    assert entry.as_of == later(3)  # as_of is always carried (freshness is shown, never inferred)


def test_a_metric_not_computed_for_the_period_is_a_named_gap(two_tenants, app_user):
    a, _ = two_tenants
    save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, value_paise=100)
    entry = read(ctx_for(a, user_id=app_user), "BS_PNL_LATEST")
    assert entry.status is EntryStatus.PARTIAL
    assert {g.code for g in entry.gaps} == {"NO_NET_REALIZED_REVENUE", "NO_MARKETPLACE_FEES"}
    assert [f.label for f in entry.figures] == ["Contribution profit"]


def test_an_unavailable_engine_result_is_shown_as_unavailable_with_its_reason(two_tenants, app_user):
    a, _ = two_tenants
    save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, available=False, unavailable_reason="COGS missing for 3 SKUs")
    save_metric(a, "NET_REALIZED_REVENUE", period=SEP, value_paise=100)
    save_metric(a, "MARKETPLACE_FEES", period=SEP, value_paise=100)
    entry = read(ctx_for(a, user_id=app_user), "BS_PNL_LATEST")
    profit = next(f for f in entry.figures if f.label == "Contribution profit")
    assert profit.formatted_value == "UNAVAILABLE" and profit.register is Register.UNAVAILABLE and "COGS missing" in (profit.note or "")
    assert entry.status is EntryStatus.PARTIAL and any(g.code == "UNAVAILABLE_CONTRIBUTION_PROFIT" for g in entry.gaps)


def test_sku_grain_rows_with_no_period_are_never_mistaken_for_the_period_pnl(two_tenants, app_user):
    a, _ = two_tenants
    save_metric(a, "CONTRIBUTION_PROFIT", period=None, value_paise=777)
    assert read(ctx_for(a, user_id=app_user), "BS_PNL_LATEST").status is EntryStatus.UNAVAILABLE


# ------------------------------------------------------------------------------------------- BS_LEAK_OPEN
def test_no_leak_findings_is_not_a_clean_bill_of_health(two_tenants, app_user):
    a, _ = two_tenants
    entry = read(ctx_for(a, user_id=app_user), "BS_LEAK_OPEN")
    assert entry.status is EntryStatus.UNAVAILABLE and entry.gaps[0].code == "NO_FINDINGS_RECORDED" and "not a clean bill" in entry.gaps[0].message


def test_open_leaks_are_ordered_by_severity_then_stored_amount_and_closed_ones_are_excluded(two_tenants, app_user):
    a, _ = two_tenants
    low_big = insert_leak(a, severity="LOW", amount_paise=900000)
    high_small = insert_leak(a, severity="HIGH", amount_paise=100)
    high_big = insert_leak(a, severity="HIGH", amount_paise=500, status="ACKNOWLEDGED")
    medium = insert_leak(a, severity="MEDIUM", amount_paise=50)
    insert_leak(a, severity="HIGH", amount_paise=10**9, status="DISMISSED")
    insert_leak(a, severity="HIGH", amount_paise=10**9, status="ACTIONED")

    entry = read(ctx_for(a, user_id=app_user), "BS_LEAK_OPEN")

    assert [f.ref.id for f in entry.figures] == [high_big, high_small, medium, low_big]
    assert entry.figures[0].formatted_value == "₹5.00" and entry.status is EntryStatus.AVAILABLE
    assert all(f.ref.kind is RefKind.AGENT_REPORT_FIELD and f.ref.source == "leak_finding" for f in entry.figures)


def test_all_recorded_leaks_closed_says_so_without_inventing_figures(two_tenants, app_user):
    a, _ = two_tenants
    insert_leak(a, severity="HIGH", amount_paise=100, status="DISMISSED")
    entry = read(ctx_for(a, user_id=app_user), "BS_LEAK_OPEN")
    assert entry.status is EntryStatus.AVAILABLE and entry.figures == () and "actioned or dismissed" in entry.facts[0].text


def test_a_long_leak_list_is_truncated_and_says_so(two_tenants, app_user):
    a, _ = two_tenants
    for i in range(bs.MAX_ITEMS_PER_ENTRY + 3):
        insert_leak(a, severity="LOW", amount_paise=100 + i)
    entry = read(ctx_for(a, user_id=app_user), "BS_LEAK_OPEN")
    assert len(entry.figures) == bs.MAX_ITEMS_PER_ENTRY and entry.status is EntryStatus.PARTIAL and entry.gaps[0].code == "TRUNCATED"


# ------------------------------------------------------------------------------------------- BS_DATA_GAPS
def test_open_data_requests_are_gaps_and_answered_ones_are_not(two_tenants, app_user):
    from cfo.repositories import agent_data_request_repo

    a, _ = two_tenants
    agent_data_request_repo.insert(a, requested_field="cogs.SKU-1", reason="COGS needed to compute margin", blocking_metric="CONTRIBUTION_PROFIT")
    agent_data_request_repo.insert(a, requested_field="rto_rate", reason="old", status="ANSWERED")
    entry = read(ctx_for(a, user_id=app_user), "BS_DATA_GAPS")
    assert len(entry.gaps) == 1 and entry.gaps[0].code == "DATA_REQUEST" and "cogs.SKU-1" in entry.gaps[0].message and "CONTRIBUTION_PROFIT" in entry.gaps[0].message
    assert entry.gaps[0].ref_id is not None and entry.figures == ()


def test_no_open_data_requests_is_a_real_statement(two_tenants, app_user):
    a, _ = two_tenants
    entry = read(ctx_for(a, user_id=app_user), "BS_DATA_GAPS")
    assert entry.status is EntryStatus.AVAILABLE and entry.gaps == () and "No inputs" in entry.facts[0].text


# ------------------------------------------------------------------------------------------- BS_SELLER_CONTEXT (K2)
def test_seller_goal_is_a_manual_figure_with_a_seller_provided_ref(two_tenants, app_user):
    from backend.services.cfo_actions import set_seller_goal

    a, _ = two_tenants
    adjustment = set_seller_goal(a, target_margin_pct="12.5", priority_category="Kitchen", note="Hit 12.5 before Diwali", created_by=app_user, now=T0)
    entry = read(ctx_for(a, user_id=app_user), "BS_SELLER_CONTEXT")
    [goal] = entry.figures
    assert (goal.formatted_value, goal.register, goal.ref.kind, goal.ref.id) == ("12.5%", Register.MANUAL, RefKind.SELLER_PROVIDED, adjustment)
    assert {f.label: (f.text, f.basis) for f in entry.facts} == {"Priority category": ("Kitchen", "SELLER_PROVIDED"), "Seller note": ("Hit 12.5 before Diwali", "SELLER_PROVIDED")}


def test_seller_goal_needs_the_cfo_permission_and_says_why_it_is_hidden(two_tenants, app_user):
    from backend.services.cfo_actions import set_seller_goal

    a, _ = two_tenants
    set_seller_goal(a, target_margin_pct="12.5", priority_category=None, note=None, created_by=app_user, now=T0)
    entry = read(partner_ctx(a, AGENT_CEO), "BS_SELLER_CONTEXT")
    assert entry.status is EntryStatus.PARTIAL and entry.figures == () and entry.gaps[0].code == "GOAL_NOT_PERMITTED"


def test_no_goal_recorded(two_tenants, app_user):
    a, _ = two_tenants
    entry = read(ctx_for(a, user_id=app_user), "BS_SELLER_CONTEXT")
    assert entry.status is EntryStatus.UNAVAILABLE and entry.gaps[0].code == "NO_GOAL"


# ------------------------------------------------------------------------------------------- BS_INGEST_STATUS
def test_ingest_status_with_no_uploads(two_tenants, app_user):
    a, _ = two_tenants
    entry = read(ctx_for(a, user_id=app_user), "BS_INGEST_STATUS")
    assert entry.status is EntryStatus.UNAVAILABLE and entry.gaps[0].code == "NO_REPORTS"


# ------------------------------------------------------------------------------------------- BS_HEALTH_BANDS
def test_health_bands_without_a_pnl_is_unavailable(two_tenants, app_user):
    a, _ = two_tenants
    entry = read(ctx_for(a, user_id=app_user), "BS_HEALTH_BANDS")
    assert entry.status is EntryStatus.UNAVAILABLE and entry.gaps[0].code == "NO_PNL"


def test_health_bands_with_a_pnl_but_no_band_metrics_is_unavailable_with_the_engines_reason(two_tenants, app_user):
    a, _ = two_tenants
    save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, value_paise=100)
    entry = read(ctx_for(a, user_id=app_user), "BS_HEALTH_BANDS")
    assert entry.status is EntryStatus.UNAVAILABLE and entry.period == SEP and entry.gaps[0].code == "NO_BANDS"  # never a fabricated GOOD


def test_health_bands_classify_persisted_metrics_with_per_metric_refs(two_tenants, app_user, migrate_engine):
    """A real banding: percent-number scale (25/2 == 12.5%), thresholds from financial_health_config. No composite score exists."""
    a, _ = two_tenants
    margin = save_metric(a, "CONTRIBUTION_MARGIN_PCT", period=SEP, fraction=(25, 2), computed_at=later(1))   # 12.5%
    fees = save_metric(a, "FEE_RATIO_PCT", period=SEP, fraction=(30, 1), computed_at=later(1))              # 30%
    returns = save_metric(a, "RETURN_RATE_PCT", period=SEP, fraction=(4, 1), computed_at=later(1))          # 4%
    save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, value_paise=100, computed_at=later(1))
    config_ids = []
    with migrate_engine.begin() as conn:
        for metric, direction, at_risk, watch in (
            ("CONTRIBUTION_MARGIN_PCT", "LOWER_IS_WORSE", "5.00", "10.00"),
            ("FEE_RATIO_PCT", "HIGHER_IS_WORSE", "35.00", "25.00"),
            ("RETURN_RATE_PCT", "HIGHER_IS_WORSE", "10.00", "6.00"),
        ):
            cid = uuid.uuid4()
            config_ids.append(cid)
            conn.execute(
                text("INSERT INTO financial_health_config (id, tenant_id, metric, direction, at_risk_threshold_pct, watch_threshold_pct, effective_from, version) "
                     "VALUES (:id, NULL, :m, :d, :ar, :w, '2000-01-01', 9999)"),
                {"id": str(cid), "m": metric, "d": direction, "ar": at_risk, "w": watch},
            )
    try:
        entry = read(ctx_for(a, user_id=app_user), "BS_HEALTH_BANDS")
    finally:
        with migrate_engine.begin() as conn:  # remove ONLY the rows this test created
            conn.execute(text("DELETE FROM financial_health_config WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": [str(c) for c in config_ids]})
    bands = {f.label: (f.formatted_value, f.ref.id) for f in entry.figures}
    assert bands == {"Contribution margin band": ("GOOD", margin), "Fee ratio band": ("WATCH", fees), "Return rate band": ("GOOD", returns)}
    assert entry.status is EntryStatus.AVAILABLE and "WATCH" in entry.facts[0].text
    assert all(f.register is Register.DERIVED for f in entry.figures)
    assert not any(f.label.lower().startswith(("score", "health score")) for f in entry.figures)  # CP1-U1: no composite score


# ------------------------------------------------------------------------------------------- gating (C17, CP1-D3, §6.22)
def test_cfo_class_entry_without_the_cfo_permission_is_not_permitted_and_leaks_nothing(two_tenants, app_user):
    a, _ = two_tenants
    save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, value_paise=14230000)
    entry = read(partner_ctx(a, AGENT_CEO), "BS_PNL_LATEST")
    assert entry.status is EntryStatus.NOT_PERMITTED and entry.figures == () and entry.preview_hint is None  # no permission: no preview either
    assert "142" not in repr(entry)


def test_a_detached_agents_entry_is_not_attached(two_tenants, app_user):
    a, _ = two_tenants
    save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, value_paise=14230000)
    entry = read(ctx_for(a, user_id=app_user), "BS_PNL_LATEST", attached={"CI", "PI", "CMO"})
    assert entry.status is EntryStatus.NOT_ATTACHED and entry.figures == () and "add it" in entry.gaps[0].message
    assert "142" not in repr(entry)


def test_permission_without_entitlement_is_not_entitled_with_the_preview_offered(two_tenants, app_user, migrate_engine):
    a, _ = two_tenants
    save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, value_paise=14230000)
    seed_platform_cap(migrate_engine, agent_code="CFO", meter_code="cfo.business_state_read", cap_value=0)
    entry = read(ctx_for(a, user_id=app_user), "BS_PNL_LATEST")
    assert entry.status is EntryStatus.NOT_ENTITLED and entry.preview_hint == "cfo.preview" and entry.figures == ()


def test_ceo_owned_entries_ignore_attachment_but_still_need_their_permission(two_tenants, app_user):
    a, _ = two_tenants
    assert read(ctx_for(a, user_id=app_user), "BS_INGEST_STATUS", attached=set()).status is EntryStatus.UNAVAILABLE  # reachable: no agent owns it
    assert read(partner_ctx(a, AGENT_CEO), "BS_INGEST_STATUS", attached=set()).status is EntryStatus.NOT_PERMITTED  # needs files.view
    assert read(partner_ctx(a, AGENT_CEO, FILES_VIEW), "BS_INGEST_STATUS", attached=set()).status is EntryStatus.UNAVAILABLE


def test_a_member_without_agent_ceo_reads_nothing(two_tenants, app_user):
    a, _ = two_tenants
    assert read(partner_ctx(a, AGENT_CFO), "BS_PNL_LATEST").status is EntryStatus.NOT_PERMITTED


def test_an_unknown_entry_key_is_never_read(two_tenants, app_user):
    a, _ = two_tenants
    with pytest.raises(KeyError):
        read(ctx_for(a, user_id=app_user), "BS_EVERYTHING")


def test_deferred_entries_are_not_in_the_catalog_and_say_why():
    assert not (set(bs.DEFERRED_ENTRIES) & set(bs.ENTRIES))
    assert all(reason.strip() for reason in bs.DEFERRED_ENTRIES.values())


# ------------------------------------------------------------------------------------------- tenant isolation
def test_one_tenant_never_sees_anothers_state(two_tenants, app_user):
    a, b = two_tenants
    save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, value_paise=14230000)
    insert_leak(a, severity="HIGH", amount_paise=5000)
    for key in ("BS_PNL_LATEST", "BS_LEAK_OPEN"):
        entry = read(ctx_for(b, user_id=app_user), key)
        assert entry.status is EntryStatus.UNAVAILABLE and entry.figures == (), key


# ------------------------------------------------------------------------------------------- the provenance gate, integrated
def _entry_with(figures, *, key="BS_TEST"):
    spec = bs.StateEntrySpec(key, None, "test", "test", lambda ctx, now: bs.StateRead(EntryStatus.AVAILABLE, as_of=T0, figures=tuple(figures)))
    return {key: spec}


def _fig(ref: Ref, label="Net revenue", register=Register.VERIFIED):
    return Figure(label=label, formatted_value="₹1.00", register=register, ref=ref)


def test_a_figure_whose_ref_does_not_exist_is_dropped_with_a_named_gap(two_tenants, app_user):
    a, _ = two_tenants
    entries = _entry_with([_fig(Ref(RefKind.ENGINE_RESULT, uuid.uuid4()))])
    entry = bs.read_entry(ctx_for(a, user_id=app_user), "BS_TEST", attached=ALL_AGENTS, entries=entries, now=T0)
    assert entry.figures == () and entry.status is EntryStatus.UNAVAILABLE and entry.gaps[0].code == "UNRESOLVED_REF"


def test_a_figure_citing_another_tenants_result_is_dropped(two_tenants, app_user):
    a, b = two_tenants
    foreign = save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, value_paise=14230000)
    entries = _entry_with([_fig(Ref(RefKind.ENGINE_RESULT, foreign))])
    mine = bs.read_entry(ctx_for(a, user_id=app_user), "BS_TEST", attached=ALL_AGENTS, entries=entries, now=T0)
    theirs = bs.read_entry(ctx_for(b, user_id=app_user), "BS_TEST", attached=ALL_AGENTS, entries=entries, now=T0)
    assert len(mine.figures) == 1 and mine.figures[0].as_of is not None  # resolves for its owner, stamped with the stored computed_at
    assert theirs.figures == () and theirs.gaps[0].code == "UNRESOLVED_REF"  # the same id does not resolve for another tenant


def test_an_engine_result_ref_cannot_masquerade_as_an_estimate(two_tenants, app_user):
    a, _ = two_tenants
    metric = save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, value_paise=100)
    entries = _entry_with([_fig(Ref(RefKind.ESTIMATE, metric))])  # a metric_result id presented as an estimate_ref
    entry = bs.read_entry(ctx_for(a, user_id=app_user), "BS_TEST", attached=ALL_AGENTS, entries=entries, now=T0)
    assert entry.figures == () and entry.gaps[0].code == "UNRESOLVED_REF"


def test_a_value_claimed_for_an_unavailable_result_is_dropped(two_tenants, app_user):
    a, _ = two_tenants
    metric = save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, available=False, unavailable_reason="no data")
    claim = bs.read_entry(ctx_for(a, user_id=app_user), "BS_TEST", attached=ALL_AGENTS, entries=_entry_with([_fig(Ref(RefKind.ENGINE_RESULT, metric))]), now=T0)
    honest = bs.read_entry(ctx_for(a, user_id=app_user), "BS_TEST", attached=ALL_AGENTS, entries=_entry_with([_fig(Ref(RefKind.ENGINE_RESULT, metric), register=Register.UNAVAILABLE)]), now=T0)
    assert claim.figures == () and claim.gaps[0].code == "UNAVAILABLE_AS_REAL" and len(honest.figures) == 1


# ------------------------------------------------------------------------------------------- reads compute and write NOTHING (AC26)
def test_reading_every_entry_computes_and_writes_nothing(two_tenants, app_user, monkeypatch):
    from calc_engine.repositories import manual_adjustment_repo, metric_result_repo
    from cfo.repositories import agent_data_request_repo, leak_finding_repo

    from backend.repositories import agent_run_repo
    from backend.services import cfo_actions

    a, _ = two_tenants
    for code in ("CONTRIBUTION_PROFIT", "NET_REALIZED_REVENUE", "MARKETPLACE_FEES"):
        save_metric(a, code, period=SEP, value_paise=1000)
    insert_leak(a, severity="HIGH", amount_paise=100)
    ctx = ctx_for(a, user_id=app_user)
    watched = ("metric_result", "leak_finding", "agent_run", "manual_adjustment", "agent_data_request", "metered_event")
    before = row_counts(a, *watched)

    def forbidden(name):
        def boom(*args, **kwargs):
            raise AssertionError(f"a Business State read must not call {name}")
        return boom

    for module, names in (
        (metric_result_repo, ("save", "save_many")), (leak_finding_repo, ("insert", "insert_many")),
        (manual_adjustment_repo, ("insert_adjustment",)), (agent_data_request_repo, ("insert", "mark_answered")),
        (agent_run_repo, ("insert_run", "finish_run")),
        (cfo_actions, ("compute_period_pnl", "compute_period_pnl_for_tenant", "run_leak_shield_reconciliation", "compute_pricing_curve",
                       "assemble_strategic_briefing", "run_anomaly_check", "assemble_cash_reconciliation", "narrate_period_comparison")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden(f"{module.__name__}.{name}"))

    entries = bs.read_entries(ctx, ALL_ENTRIES, attached=ALL_AGENTS, now=later(10))

    assert [e.key for e in entries] == list(ALL_ENTRIES) and all(e.status is not EntryStatus.NOT_PERMITTED for e in entries)
    assert row_counts(a, *watched) == before  # and not a single row was written


def test_read_entries_returns_one_result_per_key_in_order(two_tenants, app_user):
    a, _ = two_tenants
    entries = bs.read_entries(ctx_for(a, user_id=app_user), ("BS_DATA_GAPS", "BS_PNL_LATEST"), attached=ALL_AGENTS, now=T0)
    assert [e.key for e in entries] == ["BS_DATA_GAPS", "BS_PNL_LATEST"]
