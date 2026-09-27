"""Deferred capabilities — twinkly-mapping-canyon.md CP3 "What to explicitly mark as
blocked" list. `packages/competitor-intelligence`'s own test suite has no precedent for this
pattern simply because it has no deferred capabilities of its own to mark; CP3's plan
explicitly prefers a skipped stub test naming the blocker (over a report-only line) "so it
shows up in test collection and reminds future work" — this file is that preference applied.

Every test below is a documented, intentional `pytest.mark.skip` — never a silently-passing
placeholder, and never a workaround that fabricates the missing engine function it names.
"""

from __future__ import annotations

import os

import pytest


# T1-full/T2/E1/AC5 (Leak Shield seller-facing findings) — RESOLVED (D5). `reconcile()`
# (`calc_engine.api.reconcile`, D4) is real, and `backend.services.cfo_actions.
# run_leak_shield_reconciliation` now wires it end-to-end into real, persisted `leak_finding`
# rows via `POST /cfo/reconcile` / `cfo.reconcile` dispatch (`agents.ceo_hub.
# dispatch_cfo_reconcile`) — guardrail 4 is closed. `AMBIGUOUS_MATCH` exceptions are the one
# deliberate exclusion (Decision B, D5): not a `ReconciliationOutcome` value, never a
# `leak_finding`, counted separately instead. Coverage now lives in
# `test_cfo_actions_leak_shield.py` (unit, mocked `reconcile()`) and
# `packages/cfo/tests/integration/test_leak_shield_reconciliation.py` (integration, real
# Postgres) — removing this stub would otherwise leave a false "still blocked" claim in a file
# whose whole purpose is accuracy about blockers.


# T18/T19/AC12/E14 (margin_curve pricing) — RESOLVED. margin_curve/MARGIN_AT_PRICE is real
# (Engine Phase 2) and wired into CFO end-to-end (twinkly-mapping-canyon.md CP A1,
# `cfo_actions.compute_pricing_curve` / POST /cfo/pricing / cfo.pricing dispatch). Coverage
# now lives in test_cfo_actions_pricing.py, not here — removing this stub would otherwise
# leave a false "still blocked" claim in a file whose whole purpose is accuracy about blockers.

# Landed cost PRIMITIVE (per-quote) — RESOLVED (twinkly-mapping-canyon.md CP A4).
# landed_cost/LANDED_COST_PER_UNIT is real at the engine layer (CP1) AND now wired into CFO
# end-to-end for a single quote (`cfo_actions.compute_landed_cost_for_quote` /
# POST /cfo/landed-cost / cfo.landed_cost dispatch). Coverage now lives in
# test_cfo_actions_landed_cost.py, not here.

# Supplier RANKING — RESOLVED (twinkly-mapping-canyon.md CP B1). T20/T21/AC13 are real:
# `cfo_actions.rank_suppliers` sorts every ACTIVE supplier.quote row for a SKU ascending by
# landed cost (fetched directly via manual_adjustment_repo.active_adjustments_for_target, not
# through the single-quote primitive), wired to POST /cfo/suppliers/rank / cfo.supplier_ranking
# dispatch. Coverage now lives in test_cfo_actions_supplier_ranking.py, not here — removing
# this stub would otherwise leave a false "still blocked" claim in a file whose whole purpose
# is accuracy about blockers.
#
# Batch size — RESOLVED (twinkly-mapping-canyon.md CP B3b). T34/AC17f are real: B3a's engine
# core (`budget_constrained_quantity`/`compute_batch_constrained_quantity`) is now wired end-to-
# end via `backend.services.cfo_actions.assemble_batch_size_estimate` — sales velocity
# (`calc_engine.formulas.sales_velocity.observed_units_sold`, real, new), the `supplier.quote`/
# `batch.budget` lookups (mirroring CP A4's zero/multiple/malformed handling, plus a real expiry
# check on `batch.budget`), and §6.12's precise `agent_data_request` rule (refused only when
# velocity AND lead time AND MOQ are ALL missing, never on velocity alone) — wired to
# `POST /cfo/batch-size` / `cfo.batch_size` dispatch. T34's never-sold-SKU case degrades to the
# honest budget-and-MOQ floor rather than refusing outright, whenever the quote names a lead
# time or MOQ. Coverage now lives in `test_cfo_actions_batch_size.py` and
# `packages/calc-engine/tests/unit/test_sales_velocity.py`, not here — removing this stub would
# otherwise leave a false "still blocked" claim in a file whose whole purpose is accuracy about
# blockers.
#
# Still genuinely open (NOT resolved by CP B3b, per §6.12's own stated limitations): velocity
# from a short history is not seasonality-adjusted (Indian festive distortion can badly mislead
# a two-month window), and lead time/MOQ remain seller-declared, unverified data.


# T22 — RESOLVED (E1/E2/E3). `docs/specs/anomaly-detection.md` is the owning spec (Q10);
# `calc_engine.anomaly` (E2) is real, pure-statistics code implementing all three V1 methods;
# and E3 wires it into CFO for the one series with a real, spec-grounded formula
# (`MARGIN_PCT`, via the new `calc_engine.api.compute_metric.compute_contribution_margin_pct`
# + `backend.services.cfo_actions.run_anomaly_check` / `POST /cfo/anomaly-check` /
# `cfo.anomaly_check` dispatch). `FEE_RATIO_PCT`/`SETTLEMENT_LAG_DAYS`/`RETURN_RATE_PCT` remain
# out of scope (anomaly-detection.md §10 P1/P2). The skip's own reason is now false — replaced
# with a real test below, against real Postgres, seeding a real `CONTRIBUTION_MARGIN_PCT`
# history via `compute_contribution_margin_pct`'s own real output (mirroring
# `test_leak_shield_reconciliation.py`'s own real-Postgres pattern) — not a mock. Fuller
# coverage (config-resolved flag path, per-method configuration-gap independence) lives in
# `packages/cfo/tests/integration/test_anomaly_check.py`; this is the minimal real proof this
# stub always promised to become.
@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL_APP/DATABASE_URL not set — this test needs a live Postgres",
)
def test_brain_2_anomaly_detection() -> None:
    import uuid
    from datetime import date, datetime, timezone

    from calc_engine.anomaly.types import AnomalyConfigurationGap
    from calc_engine.api.compute_metric import MetricResult, compute_contribution_margin_pct
    from calc_engine.repositories import metric_result_repo
    from calc_engine.types import RecognitionState
    from sqlalchemy import create_engine, text

    import backend.services.cfo_actions as cfo_actions_module

    as_of = date(2026, 9, 25)
    computed_at = datetime(2026, 9, 25, tzinfo=timezone.utc)
    tenant_id = uuid.uuid4()
    migrate_engine = create_engine(os.environ["DATABASE_URL"])

    try:
        with migrate_engine.begin() as conn:
            conn.execute(text("DELETE FROM metric_result"))

        # Real per-period ContributionProfit/NetRealizedRevenue -> real
        # compute_contribution_margin_pct -> real metric_result_repo.save, exactly the honest
        # "who populates this history" story E3's own report names: nothing else does yet.
        for i in range(8):
            nrr = MetricResult(
                id=uuid.uuid4(),
                metric_code="NET_REALIZED_REVENUE",
                value_paise=100_00,
                recognition_state=RecognitionState.RECOGNISED,
                confidence="VERIFIED",
                calculation_basis="test fixture",
                formula_version="NET_REALIZED_REVENUE.v1",
                canonical_data_version="cdv-1",
                as_of_date=as_of,
                input_refs=(),
                exclusions=(),
                computed_at=computed_at,
                is_available=True,
            )
            cp = MetricResult(
                id=uuid.uuid4(),
                metric_code="CONTRIBUTION_PROFIT",
                value_paise=(20 + i) * 100,
                recognition_state=RecognitionState.RECOGNISED,
                confidence="VERIFIED",
                calculation_basis="test fixture",
                formula_version="CONTRIBUTION_PROFIT.v1",
                canonical_data_version="cdv-1",
                as_of_date=as_of,
                input_refs=(),
                exclusions=(),
                computed_at=computed_at,
                is_available=True,
            )
            margin_pct = compute_contribution_margin_pct(cp, nrr, computed_at=computed_at, as_of_date=as_of)
            assert margin_pct.is_available is True

            month = i + 1
            metric_result_repo.save(
                tenant_id,
                margin_pct,
                grain="SKU",
                target_ref="SKU-T22",
                period=f"2026-{month:02d}-01/2026-{month:02d}-28",
                config_version="TEST.v1",
            )

        request = cfo_actions_module.AnomalyCheckRequest(
            target_ref="SKU-T22",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            as_of_date=as_of,
            requested_by=uuid.uuid4(),
        )
        outcome = cfo_actions_module.run_anomaly_check(tenant_id, request)

        # A real, structured, non-mocked outcome: 8 real points found, all three methods
        # invoked, none silently skipped. No anomaly_detection_config row is seeded anywhere
        # in this codebase (this checkpoint's own explicit non-goal) so the real, honest
        # outcome for every method is AnomalyConfigurationGap — a genuine non-flag outcome
        # (anomaly-detection.md §5.2), not an error and not a silently-assumed threshold.
        assert outcome.series_length == 8
        assert len(outcome.methods) == 3
        for method_outcome in outcome.methods:
            assert isinstance(method_outcome.configuration_gap, AnomalyConfigurationGap)
    finally:
        with migrate_engine.begin() as conn:
            conn.execute(text("DELETE FROM metric_result"))
        migrate_engine.dispose()


# T28/AC19/E21 (funding readiness) — PARTIALLY RESOLVED (twinkly-mapping-canyon.md CP B2). The
# REDUCED slice §6.13 names as honestly buildable today — Contribution Profit history, period-
# over-period trend (via the real `compute_metric_delta`), and explicit gaps (periods missing,
# COGS/RTO-classification absent) — is real and wired end-to-end
# (`cfo_actions.assemble_funding_readiness_reduced` / `POST /cfo/funding-readiness` /
# `cfo.funding_readiness` dispatch). No score/valuation/lending judgement anywhere (AC19); thin
# data still assembles what exists and names every gap (E21). Coverage now lives in
# `test_cfo_actions_funding_readiness.py`, not here.
#
# Still genuinely open (NOT resolved by CP B2): the FULL §6.13 output also names margin
# stability, revenue concentration by SKU/marketplace, and cash-conversion timing from
# settlement data — none of these are assembled by the reduced slice, because all three depend
# on a real `reconcile()`/`cash_reconciliation()` (Phase D), which does not exist yet. CP B2's
# own `FundingReadinessOutcome.deferred_sections` states this structurally on every response
# rather than silently omitting it.
@pytest.mark.skip(reason="T28/AC19/E21 (full §6.13) — margin stability, revenue concentration and cash-conversion timing still need reconcile()/cash_reconciliation() (Phase D), not yet built; the reduced slice (CP history, trend, named gaps) is real — see test_cfo_actions_funding_readiness.py")
def test_funding_readiness_full_signal() -> None:
    ...


@pytest.mark.skip(reason="T35/AC1c — estimate_ref contract (CI-sourced estimates) is not yet exercised through any CFO surface in this slice")
def test_estimate_ref_distinct_from_engine_result_ref() -> None:
    ...


# T37/T42-delta (period-over-period metric delta) — RESOLVED. metric_delta/compute_metric_delta
# is real at the engine layer (CP3, calc_engine.formulas.metric_delta) AND now wired into CFO
# end-to-end (twinkly-mapping-canyon.md CP A3, `cfo_actions.narrate_period_comparison` /
# POST /cfo/period-comparison / cfo.period_comparison dispatch), activating cfo-agent.md
# §7.4.4's "once built" period-comparison narration rule. Coverage now lives in
# test_cfo_actions_period_comparison.py, not here — removing this stub would otherwise leave
# a false "still blocked" claim in a file whose whole purpose is accuracy about blockers.
# NOTE: T37's other half (Brain-2-sourced NAMED CAUSE attribution for a movement, as opposed
# to stating its magnitude) still depends on Brain 2, which has no specification yet (Q10,
# test_brain_2_anomaly_detection below) — that narrower gap remains genuinely open.


@pytest.mark.skip(reason="T25/T13/T17-full — cash_reconciliation()/cash_view and the reconcile-dependent cash flow view do not exist yet (Q13, C14)")
def test_cash_reconciliation_view() -> None:
    ...


# GST period total — RESOLVED. gst.summary/compute_gst_period_summary is real (Engine CP4)
# and wired into CFO end-to-end (twinkly-mapping-canyon.md CP A2,
# `cfo_actions.render_gst_period_summary` / POST /cfo/gst/period-summary /
# cfo.gst_summary dispatch), kept permanently distinct from the line-level
# `analyze_gst_lines`. Coverage now lives in test_cfo_actions_gst_period_summary.py.

# leak_aggregate engine_result_ref wrapper (§6.4 rule 5) — RESOLVED (D5). `reconcile()`'s own
# `aggregate_metric_result` (a real `LEAK_TOTAL` `MetricResult`, D4) is now persisted by
# `run_leak_shield_reconciliation` via `metric_result_repo.save` (`grain="MARKETPLACE"`,
# `target_ref=marketplace`) — its `.id` IS the headline leak total's real `engine_result_ref`,
# for the first time. Coverage now lives in `test_cfo_actions_leak_shield.py` and
# `test_leak_shield_reconciliation.py` — removing this stub would otherwise leave a false
# "still blocked" claim in a file whose whole purpose is accuracy about blockers.
