"""GROSS_SALES and its cross-marketplace reconciliation (deterministic-engine.md §5.17.1 (1)). Golden values are hand-computed paise.

The marketplace-specific behaviour under test: gross sales is a measured volume and is available for every marketplace, including the ones whose
Net Realized Revenue is `UNAVAILABLE` (Amazon and Flipkart carry no cancellation/RTO status); a consolidated NRR must not silently drop them."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from hypothesis import given, strategies as st

from calc_engine.api.compute_metric import compute_net_realized_revenue
from calc_engine.formulas.completeness import Completeness
from calc_engine.formulas.gross_sales import gross_sales, gross_sales_by_marketplace
from calc_engine.formulas.identities import check_additive
from calc_engine.types import Paise, RecognitionState, Unavailable
from tests.fixtures.canonical_builder import CanonicalDataBuilder

B = CanonicalDataBuilder


def meesho():
    return [B().marketplace("MEESHO").gross(1_000_00).build(),
            B().marketplace("MEESHO").gross(500_00).cancelled().build(),  # cancelled: still gross sales (a volume)
            B().marketplace("MEESHO").gross(250_00).returned(1).build()]  # returned: still gross sales


def amazon():
    return [B().marketplace("AMAZON").gross(2_000_00).unresolved_cancellation().build(),
            B().marketplace("AMAZON").gross(1_500_00).unresolved_cancellation().build()]


def flipkart():
    return [B().marketplace("FLIPKART").gross(800_00).unresolved_return().build()]


def test_gross_sales_includes_cancelled_and_returned_lines() -> None:
    r = gross_sales(meesho())
    assert not isinstance(r, Unavailable)
    assert r.value == Paise(1_750_00) and r.line_count == 3 and r.completeness is Completeness.COMPLETE


def test_gross_sales_is_available_where_net_realized_revenue_is_not(empty_bearer_resolver) -> None:
    nrr = compute_net_realized_revenue(amazon(), bearer_resolver=empty_bearer_resolver, recognition_state=RecognitionState.RECOGNISED,
                                       ingestion_run_ids=[uuid4()], adapter_versions=["amazon.mtr.v1:1"], active_adjustment_ids=[],
                                       computed_at=datetime(2026, 10, 21, tzinfo=timezone.utc), as_of_date=date(2026, 10, 21))
    assert not nrr.is_available  # Amazon carries no cancellation status: revenue cannot be measured...
    g = gross_sales(amazon())
    assert not isinstance(g, Unavailable) and g.value == Paise(3_500_00)  # ...but the volume that was sold can


def test_per_marketplace_gross_sales_add_up_to_the_consolidated_figure_exactly() -> None:
    lines = meesho() + amazon() + flipkart()
    r = gross_sales_by_marketplace(lines)
    assert set(r.by_marketplace) == {"AMAZON", "FLIPKART", "MEESHO"}
    parts = {mp: (v.value.value if not isinstance(v, Unavailable) else None) for mp, v in r.by_marketplace.items()}
    assert parts == {"AMAZON": 3_500_00, "FLIPKART": 800_00, "MEESHO": 1_750_00}
    assert not isinstance(r.consolidated, Unavailable) and r.consolidated.value == Paise(6_050_00)
    assert check_additive(parts, r.consolidated.value.value).ok  # Σ marketplaces = consolidated, to the paisa


def test_net_revenue_excludes_unmeasurable_lines_but_discloses_them_while_gross_sales_counts_them(empty_bearer_resolver) -> None:
    lines = [B().marketplace("MEESHO").gross(1_000_00).build()] + amazon()
    nrr = compute_net_realized_revenue(lines, bearer_resolver=empty_bearer_resolver, recognition_state=RecognitionState.RECOGNISED,
                                       ingestion_run_ids=[uuid4()], adapter_versions=["x"], active_adjustment_ids=[],
                                       computed_at=datetime(2026, 10, 21, tzinfo=timezone.utc), as_of_date=date(2026, 10, 21))
    assert nrr.value_paise == 1_000_00 and len(nrr.exclusions) == 2  # the two Amazon lines are disclosed, not silently dropped
    g = gross_sales(lines)
    assert not isinstance(g, Unavailable) and g.value == Paise(4_500_00) and g.line_count == 3  # gross sales still counts them


def test_blocked_lines_make_the_result_partial_and_are_counted() -> None:
    r = gross_sales(meesho(), blocked_line_count=4)
    assert not isinstance(r, Unavailable) and r.completeness is Completeness.PARTIAL and r.blocked_line_count == 4
    by = gross_sales_by_marketplace(meesho() + amazon(), blocked_by_marketplace={"AMAZON": 2})
    assert by.by_marketplace["MEESHO"].completeness is Completeness.COMPLETE  # type: ignore[union-attr]
    assert by.by_marketplace["AMAZON"].completeness is Completeness.PARTIAL  # type: ignore[union-attr]
    assert by.consolidated.completeness is Completeness.PARTIAL  # type: ignore[union-attr]


def test_no_lines_is_unavailable_never_zero() -> None:
    r = gross_sales([])
    assert isinstance(r, Unavailable) and "no order lines" in r.reason


@given(st.lists(st.tuples(st.sampled_from(["AMAZON", "FLIPKART", "MEESHO"]), st.integers(min_value=0, max_value=10**9)), min_size=1, max_size=40))
def test_property_marketplaces_always_partition_the_consolidated_total(rows) -> None:
    lines = [B().marketplace(mp).gross(g).build() for mp, g in rows]
    r = gross_sales_by_marketplace(lines)
    assert not isinstance(r.consolidated, Unavailable)
    parts = {mp: v.value.value for mp, v in r.by_marketplace.items() if not isinstance(v, Unavailable)}
    assert sum(parts.values()) == r.consolidated.value.value == sum(g for _, g in rows)
