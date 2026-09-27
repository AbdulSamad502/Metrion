"""`backend.services.cfo_actions.rank_suppliers` — end-to-end at the unit level, real engine
functions (`parse_supplier_quote_adjustment`, `compute_landed_cost`, `landed_cost_per_unit`).
The two DB-touching calls this composition makes (`manual_adjustment_repo.
active_adjustments_for_target`, `metric_result_repo.save`) and the data-request insert are
monkeypatched — no live Postgres in this session, mirroring `test_cfo_actions_landed_cost.py`'s
own `_stub_persistence`/`insert_data_request` monkeypatch conventions exactly.

Activates twinkly-mapping-canyon.md CP B1 / cfo-agent.md §6.11's supplier RANKING — sorting
every ACTIVE `supplier.quote` row for a SKU by landed cost. Deliberately calls
`manual_adjustment_repo.active_adjustments_for_target` DIRECTLY (not through
`compute_landed_cost_for_quote`), matching CP B1's own convention that multiple suppliers
quoting the same SKU land as multiple ACTIVE rows under one `(target_type="SKU",
target_ref=sku, field="supplier.quote")` triple.

Covers:
  - three ACTIVE rows with different unit costs -> ordered ascending by landed cost, all three
    `MetricResult`s persisted with correct provenance.
  - zero ACTIVE rows -> exactly one `agent_data_request` raised, `ranked == []`.
  - exactly one ACTIVE (valid) row -> `is_single_quote is True`, structurally distinguishable
    from a real ranking.
  - one malformed row among three valid ones -> quarantined and disclosed (not silently
    dropped, not crashing the ranking of the other two) — exercised via the REAL
    `parse_supplier_quote_adjustment` raising a real `ValueError`.
  - AC13 guardrail: ranking uses only seller-supplied `supplier.quote` rows — no
    external/discovered supplier data anywhere in this function's inputs.
  - the no-arithmetic lint (`test_no_arithmetic_lint.py`) already scans `cfo_actions.py`
    broadly, including the new `sorted()` call — confirmed by inspection/a direct assertion
    below, not duplicated here.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import (
    QuarantinedSupplierQuote,
    RankedSupplierQuote,
    SupplierRankingOutcome,
    SupplierRankingRequest,
    rank_suppliers,
)

_AS_OF = date(2026, 9, 23)
_COMPUTED_AT = datetime(2026, 9, 23, tzinfo=timezone.utc)


def _quote_value(supplier_name: str, unit_cost_paise: int, **extra: object) -> dict[str, object]:
    return {
        "supplier_name": supplier_name,
        "sku": "SKU-1",
        "unit_cost_paise": unit_cost_paise,
        **extra,
    }


def _adjustment_row(value: dict[str, object], *, row_id=None) -> dict[str, object]:
    return {
        "id": row_id or uuid4(),
        "target_type": "SKU",
        "target_ref": "SKU-1",
        "field": "supplier.quote",
        "value": value,
        "reason": None,
        "created_by": uuid4(),
        "created_at": _COMPUTED_AT,
        "supersedes_id": None,
        "status": "ACTIVE",
    }


def _base_request(*, quantity: int = 100) -> SupplierRankingRequest:
    return SupplierRankingRequest(
        sku="SKU-1",
        quantity=quantity,
        active_adjustment_ids=[],
        requested_by=uuid4(),
        as_of_date=_AS_OF,
        computed_at=_COMPUTED_AT,
    )


@pytest.fixture(autouse=True)
def _stub_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    """`metric_result_repo.save` opens a real DB connection — no live Postgres in this
    session, so persistence is stubbed to a no-op, exactly as `test_cfo_actions_landed_cost.py`'s
    own `_stub_persistence` fixture does. Records every call so persistence-count/provenance
    assertions can inspect it."""
    calls: list[dict[str, object]] = []

    def _fake_save(tenant_id, result, **kwargs):
        calls.append({"tenant_id": tenant_id, "result": result, **kwargs})

    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "save", _fake_save)
    monkeypatch.setattr(cfo_actions_module, "_save_calls", calls, raising=False)


def _save_calls() -> list[dict[str, object]]:
    return cfo_actions_module._save_calls  # type: ignore[attr-defined]


def test_three_valid_quotes_ranked_ascending_by_landed_cost_and_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _adjustment_row(_quote_value("Mid Supplier", 200_00)),
        _adjustment_row(_quote_value("Cheapest Supplier", 100_00)),
        _adjustment_row(_quote_value("Priciest Supplier", 300_00)),
    ]
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda *a, **k: rows,
    )

    outcome = rank_suppliers(uuid4(), _base_request())

    assert isinstance(outcome, SupplierRankingOutcome)
    assert outcome.data_request_id is None
    assert outcome.quarantined == []
    assert outcome.is_single_quote is False
    assert len(outcome.ranked) == 3

    # Ascending by landed cost (no shipping supplied -> landed cost == unit_cost_paise).
    supplier_names_in_order = [r.supplier_name for r in outcome.ranked]
    assert supplier_names_in_order == ["Cheapest Supplier", "Mid Supplier", "Priciest Supplier"]
    values_in_order = [r.result.value_paise for r in outcome.ranked]
    assert values_in_order == sorted(values_in_order)
    assert values_in_order == [100_00, 200_00, 300_00]

    for r in outcome.ranked:
        assert isinstance(r, RankedSupplierQuote)
        assert r.result.metric_code == "LANDED_COST_PER_UNIT"
        assert r.result.id is not None  # engine_result_ref
        assert r.result.is_available is True

    # All three persisted with correct grain/target_ref provenance.
    calls = _save_calls()
    assert len(calls) == 3
    for call in calls:
        assert call["grain"] == "SKU"
        assert call["target_ref"] == "SKU-1"
        assert call["config_version"] == cfo_actions_module._SUPPLIER_RANKING_CONFIG_VERSION


def test_zero_active_quotes_yields_data_request_never_scores_missing_supplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda *a, **k: [],
    )
    captured_requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        cfo_actions_module,
        "insert_data_request",
        lambda tenant_id, **kwargs: captured_requests.append(kwargs) or uuid4(),
    )

    outcome = rank_suppliers(uuid4(), _base_request())

    assert outcome.ranked == []
    assert outcome.quarantined == []
    assert outcome.is_single_quote is False
    assert outcome.data_request_id is not None
    assert len(captured_requests) == 1
    assert captured_requests[0]["requested_field"] == "supplier.quote"
    assert captured_requests[0]["blocking_metric"] == "LANDED_COST_PER_UNIT"
    assert "no quote" in captured_requests[0]["reason"] or "CFO never scores" in captured_requests[0]["reason"]


def test_exactly_one_valid_quote_is_structurally_a_single_quote_not_a_ranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_adjustment_row(_quote_value("Solo Supplier", 150_00))]
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda *a, **k: rows,
    )

    outcome = rank_suppliers(uuid4(), _base_request())

    assert outcome.data_request_id is None
    assert len(outcome.ranked) == 1
    # E15's structural distinction: a dedicated boolean flag, not just "len(ranked) == 1".
    assert outcome.is_single_quote is True
    assert outcome.ranked[0].supplier_name == "Solo Supplier"


def test_one_malformed_quote_among_three_is_quarantined_not_dropped_not_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed_row_id = uuid4()
    rows = [
        _adjustment_row(_quote_value("Good Supplier A", 120_00)),
        # Missing unit_cost_paise -> parse_supplier_quote_adjustment raises a REAL ValueError.
        _adjustment_row({"supplier_name": "Malformed Supplier"}, row_id=malformed_row_id),
        _adjustment_row(_quote_value("Good Supplier B", 90_00)),
    ]
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda *a, **k: rows,
    )

    outcome = rank_suppliers(uuid4(), _base_request())

    # The ranking of the two valid rows proceeds — the malformed row did not abort it.
    assert outcome.data_request_id is None
    assert len(outcome.ranked) == 2
    assert [r.supplier_name for r in outcome.ranked] == ["Good Supplier B", "Good Supplier A"]

    # The malformed row is disclosed, not silently dropped.
    assert len(outcome.quarantined) == 1
    quarantined = outcome.quarantined[0]
    assert isinstance(quarantined, QuarantinedSupplierQuote)
    assert quarantined.adjustment_id == malformed_row_id
    assert quarantined.supplier_name == "Malformed Supplier"
    assert "unit_cost_paise" in quarantined.reason

    # Only the two valid rows were persisted.
    assert len(_save_calls()) == 2


def test_all_rows_malformed_yields_data_request_naming_the_quarantine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _adjustment_row({"supplier_name": "Broken A"}),
        _adjustment_row({"unit_cost_paise": 100_00}),  # missing supplier_name
    ]
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda *a, **k: rows,
    )
    captured_requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        cfo_actions_module,
        "insert_data_request",
        lambda tenant_id, **kwargs: captured_requests.append(kwargs) or uuid4(),
    )

    outcome = rank_suppliers(uuid4(), _base_request())

    assert outcome.ranked == []
    assert len(outcome.quarantined) == 2
    assert outcome.data_request_id is not None
    assert len(captured_requests) == 1
    assert captured_requests[0]["blocking_metric"] == "LANDED_COST_PER_UNIT"


def test_quantity_le_zero_caller_bug_propagates_uncaught_affecting_all_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_adjustment_row(_quote_value("Any Supplier", 100_00))]
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda *a, **k: rows,
    )

    with pytest.raises(ValueError, match="quantity"):
        rank_suppliers(uuid4(), _base_request(quantity=0))


def test_ac13_ranking_uses_only_seller_supplied_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC13 structural guardrail: `rank_suppliers` derives every ranked entry's data (supplier
    name, landed cost, MOQ, lead time, payment terms, reliability note) exclusively from the
    ACTIVE `supplier.quote` manual_adjustment rows `active_adjustments_for_target` returns —
    no external/discovered supplier lookup is ever called."""
    rows = [
        _adjustment_row(
            _quote_value(
                "Only Seller-Supplied Co",
                175_00,
                moq=50,
                lead_time_days=10,
                payment_terms="Net 30",
                reliability_note="Reliable",
            )
        )
    ]

    fetch_calls: list[tuple] = []

    def _fake_fetch(*args, **kwargs):
        fetch_calls.append((args, kwargs))
        return rows

    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo, "active_adjustments_for_target", _fake_fetch
    )

    outcome = rank_suppliers(uuid4(), _base_request())

    # Exactly one fetch, scoped to this tenant's own supplier.quote field — no other data
    # source consulted.
    assert len(fetch_calls) == 1
    _, kwargs = fetch_calls[0]
    assert kwargs["field"] == "supplier.quote"
    assert kwargs["target_type"] == "SKU"

    entry = outcome.ranked[0]
    assert entry.supplier_name == "Only Seller-Supplied Co"
    assert entry.moq == 50
    assert entry.lead_time_days == 10
    assert entry.payment_terms == "Net 30"
    assert entry.reliability_note == "Reliable"


def test_sorted_call_on_value_paise_is_not_flagged_by_no_arithmetic_lint() -> None:
    """Explicit empirical confirmation (not just an assumption): the AST lint only flags
    `ast.BinOp`/`ast.AugAssign` with `+ - * /` (and friends) where an operand is paise-named —
    a `sorted(..., key=lambda entry: entry.result.value_paise)` call contains no such BinOp/
    AugAssign node at all (it's a `Call` with a `Lambda` whose body is an `Attribute` chain,
    no arithmetic operator anywhere), so the lint correctly does not (and structurally cannot)
    flag it."""
    import ast
    from pathlib import Path

    cfo_actions_path = Path(cfo_actions_module.__file__)
    tree = ast.parse(cfo_actions_path.read_text(encoding="utf-8"))

    sort_call_nodes = [
        node
        for node in ast.walk(tree)
        for call in [node]
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "sort"
    ]
    assert len(sort_call_nodes) >= 1, "expected at least one list.sort() call in cfo_actions.py"

    for call_node in sort_call_nodes:
        for sub_node in ast.walk(call_node):
            assert not isinstance(sub_node, (ast.BinOp, ast.AugAssign)), (
                "sorted()/list.sort() call unexpectedly contains arithmetic — "
                "would legitimately need the lint's attention"
            )

    from tests.unit.test_no_arithmetic_lint import _check_file

    violations = _check_file(cfo_actions_path)
    assert violations == []
