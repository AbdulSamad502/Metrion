"""calc_engine.api.reconcile.reconcile — composition-level unit tests against in-memory
fixtures shaped like what `settlement_repo`/`canonical_repo`/`config_repo` return, and against
monkeypatched `reconciliation_repo` insert functions (no live Postgres in this session,
mirroring `packages/cfo/tests/unit/test_cfo_actions_landed_cost.py`'s
`monkeypatch.setattr(module.some_repo, "fn", ...)` convention).

Exercises every path in data-foundation.md §5.8 plus both session decisions:
  - Decision A: a component_code present on the settlement side only is skipped, never
    defaulted to a zero invoice amount and never classified.
  - Decision B: a sales_line with all three dates None is counted in `dates_missing_count`,
    never crashes `resolve_document_date()`.

The one exception is `test_matched_pair_with_synthetic_components_both_sides` — invoice-side
`line_component` rows do not exist anywhere in real ingested data today (Decision A), so that
one test's invoice-side components are explicitly synthetic, constructed only to prove the
variance-classification path itself works when both sides of a component_code genuinely exist.
Every other test in this file uses shapes that match real ingested data (settlement-side
components only, no invoice-side components) to keep the other paths honest about what data
actually looks like today.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

import calc_engine.api.reconcile as reconcile_module
from calc_engine.api.reconcile import _JOIN_KEY_CONFIDENCE, _JOIN_KEY_FIELD, reconcile
from calc_engine.types import Confidence

_TENANT = uuid4()
_MARKETPLACE = "MEESHO"
_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 1, 31)
_AS_OF = date(2026, 9, 25)
_COMPUTED_AT = datetime(2026, 9, 25, tzinfo=timezone.utc)

_DEFAULT_TOLERANCE_ROW = {
    "tolerance_paise": 50,
    "tolerance_bps": 10,
    "settlement_lag_days": 14,
    "grace_period_days": 5,
    "effective_from": date(2026, 1, 1),
    "version": 1,
}


def _sales_line(
    *,
    sales_line_id=None,
    order_ref="SUB1",
    line_ref="SUB1_1",
    invoice_date=None,
    dispatch_date=None,
    order_date=date(2026, 1, 5),
    taxable_amount=10_000,
    confidence="VERIFIED",
):
    return {
        "sales_line_id": sales_line_id or uuid4(),
        "marketplace": _MARKETPLACE,
        "document_type": "TAX_INVOICE",
        "quantity": 1,
        "invoice_date": invoice_date,
        "dispatch_date": dispatch_date,
        "order_date": order_date,
        "gross_item_amount": None,
        "return_status": None,
        "confidence": confidence,
        "order_ref": order_ref,
        "line_ref": line_ref,
        "taxable_amount": taxable_amount,
    }


def _settlement_line(
    *,
    settlement_line_id=None,
    order_ref="SUB1",
    line_ref="SUB1_1",
    gross_settlement_amount=10_000,
    settlement_date_=date(2026, 1, 20),
    confidence="VERIFIED",
):
    return {
        "settlement_line_id": settlement_line_id or uuid4(),
        "tenant_id": _TENANT,
        "ingestion_run_id": uuid4(),
        "marketplace": _MARKETPLACE,
        "order_ref": order_ref,
        "line_ref": line_ref,
        "settlement_id": None,
        "gross_settlement_amount": gross_settlement_amount,
        "currency": "INR",
        "settlement_date": settlement_date_,
        "document_type": "Order Payments",
        "source_row_number": 1,
        "source_row_json": {},
        "confidence": confidence,
    }


def _component(*, owner_key, owner_id, component_code, source_side, amount):
    return {
        "id": uuid4(),
        owner_key: owner_id,
        "component_kind": "FEE",
        "component_code": component_code,
        "source_side": source_side,
        "amount": amount,
        "tax_amount": None,
        "rate_pct": None,
    }


class _RepoStub:
    """Records every insert_reconciliation_match/insert_reconciliation_exception call and
    hands back deterministic uuids, mirroring how test_cfo_actions_*.py stubs persistence."""

    def __init__(self) -> None:
        self.runs: list[dict] = []
        self.finished: list[dict] = []
        self.matches: list[dict] = []
        self.exceptions: list[dict] = []

    def insert_reconciliation_run(self, tenant_id, **kwargs):
        run_id = uuid4()
        self.runs.append({"tenant_id": tenant_id, "id": run_id, **kwargs})
        return run_id

    def mark_reconciliation_run_finished(self, tenant_id, run_id, **kwargs):
        self.finished.append({"tenant_id": tenant_id, "run_id": run_id, **kwargs})

    def insert_reconciliation_match(self, tenant_id, **kwargs):
        match_id = uuid4()
        self.matches.append({"tenant_id": tenant_id, "id": match_id, **kwargs})
        return match_id

    def insert_reconciliation_exception(self, tenant_id, **kwargs):
        exception_id = uuid4()
        self.exceptions.append({"tenant_id": tenant_id, "id": exception_id, **kwargs})
        return exception_id

    def insert_reconciliation_rows(self, tenant_id, *, matches, exceptions):
        """reconcile() now queues matches/exceptions and bulk-writes them — record each entry in
        the exact same shape the single-row stubs above use, so every assertion below is unchanged."""
        for match_id, kwargs in matches:
            self.matches.append({"tenant_id": tenant_id, "id": match_id, **kwargs})
        for exception_id, kwargs in exceptions:
            self.exceptions.append({"tenant_id": tenant_id, "id": exception_id, **kwargs})


@pytest.fixture
def repo_stub(monkeypatch: pytest.MonkeyPatch) -> _RepoStub:
    stub = _RepoStub()
    monkeypatch.setattr(reconcile_module.reconciliation_repo, "insert_reconciliation_run", stub.insert_reconciliation_run)
    monkeypatch.setattr(
        reconcile_module.reconciliation_repo, "mark_reconciliation_run_finished", stub.mark_reconciliation_run_finished
    )
    monkeypatch.setattr(reconcile_module.reconciliation_repo, "insert_reconciliation_match", stub.insert_reconciliation_match)
    monkeypatch.setattr(
        reconcile_module.reconciliation_repo, "insert_reconciliation_exception", stub.insert_reconciliation_exception
    )
    monkeypatch.setattr(reconcile_module.reconciliation_repo, "insert_reconciliation_rows", stub.insert_reconciliation_rows)
    return stub


def _wire_data(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sales_lines: list[dict],
    settlement_lines: list[dict],
    invoice_components: list[dict] | None = None,
    settlement_components: list[dict] | None = None,
    tolerance_row: dict | None = _DEFAULT_TOLERANCE_ROW,
) -> None:
    # Mirrors the real split reconcile() now does: a fully dateless row is only ever returned by
    # sales_lines_without_document_date(), never by sales_lines_in_period() (its own coalesce(...)
    # BETWEEN filter excludes it) — partition the fixture the same way rather than trusting the
    # caller to pre-split it.
    dated = [
        row for row in sales_lines
        if not (row.get("invoice_date") is None and row.get("dispatch_date") is None and row.get("order_date") is None)
    ]
    dateless = [
        row for row in sales_lines
        if row.get("invoice_date") is None and row.get("dispatch_date") is None and row.get("order_date") is None
    ]
    monkeypatch.setattr(reconcile_module.canonical_repo, "sales_lines_in_period", lambda *a, **k: dated)
    monkeypatch.setattr(
        reconcile_module.canonical_repo, "sales_lines_without_document_date", lambda *a, **k: dateless
    )
    monkeypatch.setattr(reconcile_module.settlement_repo, "settlement_lines_in_period", lambda *a, **k: settlement_lines)
    monkeypatch.setattr(
        reconcile_module.canonical_repo, "components_for_lines", lambda *a, **k: invoice_components or []
    )
    monkeypatch.setattr(
        reconcile_module.settlement_repo,
        "components_for_settlement_lines",
        lambda *a, **k: settlement_components or [],
    )
    monkeypatch.setattr(
        reconcile_module.config_repo,
        "resolve_reconciliation_tolerance",
        lambda *a, **k: tolerance_row,
    )


def _run():
    return reconcile(
        _TENANT,
        marketplace=_MARKETPLACE,
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        computed_at=_COMPUTED_AT,
    )


def test_matched_pair_with_synthetic_components_both_sides(monkeypatch: pytest.MonkeyPatch, repo_stub: _RepoStub):
    """SYNTHETIC ONLY: real Meesho data never produces invoice-side line_component rows today
    (Decision A) — these components are constructed purely to prove classify_variance's own
    path works end-to-end when a component_code genuinely exists on both sides."""
    sales = _sales_line()
    settlement = _settlement_line()
    invoice_components = [
        _component(
            owner_key="sales_line_id", owner_id=sales["sales_line_id"],
            component_code="COMMISSION", source_side="INVOICE", amount=5_000,
        ),
        _component(
            owner_key="sales_line_id", owner_id=sales["sales_line_id"],
            component_code="TAX", source_side="INVOICE", amount=1_000,
        ),
    ]
    settlement_components = [
        _component(
            owner_key="settlement_line_id", owner_id=settlement["settlement_line_id"],
            component_code="COMMISSION", source_side="SETTLEMENT", amount=5_000,  # exact match
        ),
        _component(
            owner_key="settlement_line_id", owner_id=settlement["settlement_line_id"],
            component_code="TAX", source_side="SETTLEMENT", amount=1_010,  # within tolerance (50 paise/10bps)
        ),
    ]
    _wire_data(
        monkeypatch,
        sales_lines=[sales],
        settlement_lines=[settlement],
        invoice_components=invoice_components,
        settlement_components=settlement_components,
    )

    result = _run()

    assert result.match_count == 2
    assert result.exception_count == 0
    assert result.dates_missing_count == 0
    outcomes = {m["component_code"]: m["outcome"] for m in repo_stub.matches}
    assert outcomes["COMMISSION"] == "MATCHED_EXACT"
    assert outcomes["TAX"] == "MATCHED_WITHIN_TOLERANCE"
    assert repo_stub.exceptions == []
    assert result.aggregate_metric_result.metric_code == "LEAK_TOTAL"
    assert result.aggregate_metric_result.value_paise == 0


def test_variance_exceeds_tolerance(monkeypatch: pytest.MonkeyPatch, repo_stub: _RepoStub):
    sales = _sales_line()
    settlement = _settlement_line()
    invoice_components = [
        _component(owner_key="sales_line_id", owner_id=sales["sales_line_id"], component_code="COMMISSION", source_side="INVOICE", amount=5_000)
    ]
    settlement_components = [
        _component(owner_key="settlement_line_id", owner_id=settlement["settlement_line_id"], component_code="COMMISSION", source_side="SETTLEMENT", amount=6_500)
    ]
    _wire_data(
        monkeypatch,
        sales_lines=[sales],
        settlement_lines=[settlement],
        invoice_components=invoice_components,
        settlement_components=settlement_components,
    )

    result = _run()

    assert result.match_count == 1
    assert result.exception_count == 1
    assert repo_stub.matches[0]["outcome"] == "VARIANCE_EXCEEDS_TOLERANCE"
    assert repo_stub.exceptions[0]["exception_type"] == "VARIANCE_EXCEEDS_TOLERANCE"
    assert repo_stub.exceptions[0]["amount_paise"] == 1_500
    assert repo_stub.exceptions[0]["reconciliation_match_id"] == repo_stub.matches[0]["id"]
    assert repo_stub.exceptions[0]["sales_line_id"] == sales["sales_line_id"]
    assert repo_stub.exceptions[0]["settlement_line_id"] == settlement["settlement_line_id"]
    assert result.aggregate_metric_result.value_paise == 1_500


def test_orphan_settlement(monkeypatch: pytest.MonkeyPatch, repo_stub: _RepoStub):
    settlement = _settlement_line(line_ref="NO_MATCH")
    _wire_data(monkeypatch, sales_lines=[], settlement_lines=[settlement])

    result = _run()

    assert result.match_count == 0
    assert result.exception_count == 1
    assert repo_stub.exceptions[0]["exception_type"] == "ORPHAN_SETTLEMENT"
    assert repo_stub.exceptions[0]["settlement_line_id"] == settlement["settlement_line_id"]
    assert repo_stub.exceptions[0].get("sales_line_id") is None
    assert repo_stub.exceptions[0]["amount_paise"] == settlement["gross_settlement_amount"]


def test_duplicate_settlement(monkeypatch: pytest.MonkeyPatch, repo_stub: _RepoStub):
    sales = _sales_line()
    first = _settlement_line(settlement_line_id=uuid4(), gross_settlement_amount=6_500, settlement_date_=date(2026, 1, 15))
    # A second settlement row with the SAME order_ref/line_ref/amount/date — the literal
    # duplicate definition (§5.2 C4).
    duplicate = _settlement_line(
        settlement_line_id=uuid4(),
        gross_settlement_amount=6_500,
        settlement_date_=date(2026, 1, 15),
    )
    # Ensure deterministic sort places `first` before `duplicate` regardless of random uuid4 order.
    ordered = sorted([first, duplicate], key=lambda r: str(r["settlement_line_id"]))
    first, duplicate = ordered[0], ordered[1]

    _wire_data(monkeypatch, sales_lines=[sales], settlement_lines=[first, duplicate])

    result = _run()

    assert result.exception_count == 1
    assert repo_stub.exceptions[0]["exception_type"] == "DUPLICATE_SETTLEMENT"
    assert repo_stub.exceptions[0]["settlement_line_id"] == duplicate["settlement_line_id"]


def test_ambiguous_match(monkeypatch: pytest.MonkeyPatch, repo_stub: _RepoStub):
    sales_a = _sales_line(sales_line_id=uuid4())
    sales_b = _sales_line(sales_line_id=uuid4())
    settlement = _settlement_line()
    _wire_data(monkeypatch, sales_lines=[sales_a, sales_b], settlement_lines=[settlement])

    result = _run()

    assert result.match_count == 0
    assert result.exception_count == 1
    exc = repo_stub.exceptions[0]
    assert exc["exception_type"] == "AMBIGUOUS_MATCH"
    assert exc["settlement_line_id"] == settlement["settlement_line_id"]
    assert exc.get("sales_line_id") is None
    assert set(exc["candidate_sales_line_ids"]) == {sales_a["sales_line_id"], sales_b["sales_line_id"]}
    assert exc["amount_paise"] == settlement["gross_settlement_amount"]


def test_unsettled_beyond_lag(monkeypatch: pytest.MonkeyPatch, repo_stub: _RepoStub):
    # document_date 2026-01-05, as_of 2026-09-25 => far beyond 14-day lag + 5-day grace.
    sales = _sales_line(line_ref="ORPHAN_SALE", invoice_date=date(2026, 1, 5), taxable_amount=7_777)
    _wire_data(monkeypatch, sales_lines=[sales], settlement_lines=[])

    result = _run()

    assert result.exception_count == 1
    exc = repo_stub.exceptions[0]
    assert exc["exception_type"] == "UNSETTLED_BEYOND_LAG"
    assert exc["sales_line_id"] == sales["sales_line_id"]
    assert exc.get("settlement_line_id") is None
    assert exc["amount_paise"] == 7_777
    assert result.dates_missing_count == 0


def test_unsettled_within_lag_never_persisted(monkeypatch: pytest.MonkeyPatch, repo_stub: _RepoStub):
    # as_of_date only 3 days after document_date — well within the 14-day lag.
    sales = _sales_line(line_ref="ORPHAN_SALE_2", invoice_date=date(2026, 9, 22))
    _wire_data(monkeypatch, sales_lines=[sales], settlement_lines=[])

    result = _run()

    assert result.exception_count == 0
    assert repo_stub.exceptions == []
    assert result.dates_missing_count == 0


def test_component_code_settlement_side_only_skipped_no_crash(monkeypatch: pytest.MonkeyPatch, repo_stub: _RepoStub):
    """Decision A: a component_code present on the settlement side with zero matching
    invoice-side rows must never be defaulted to zero or classified — this mirrors 100% of
    real Meesho data today (no adapter produces INVOICE-side line_component rows at all)."""
    sales = _sales_line()
    settlement = _settlement_line()
    settlement_components = [
        _component(owner_key="settlement_line_id", owner_id=settlement["settlement_line_id"], component_code="FIXED_FEE", source_side="SETTLEMENT", amount=6_500)
    ]
    _wire_data(
        monkeypatch,
        sales_lines=[sales],
        settlement_lines=[settlement],
        invoice_components=[],  # no invoice-side components at all — the real-data shape
        settlement_components=settlement_components,
    )

    result = _run()

    assert result.match_count == 0
    assert result.exception_count == 0
    assert repo_stub.matches == []
    assert repo_stub.exceptions == []


def test_dates_missing_counted_not_crashed(monkeypatch: pytest.MonkeyPatch, repo_stub: _RepoStub):
    sales = _sales_line(
        line_ref="ORPHAN_SALE_3", invoice_date=None, dispatch_date=None, order_date=None
    )
    _wire_data(monkeypatch, sales_lines=[sales], settlement_lines=[])

    result = _run()

    assert result.dates_missing_count == 1
    assert result.exception_count == 0
    assert repo_stub.exceptions == []


def test_run_marked_finished_with_all_counts(monkeypatch: pytest.MonkeyPatch, repo_stub: _RepoStub):
    sales = _sales_line()
    settlement = _settlement_line()
    _wire_data(monkeypatch, sales_lines=[sales], settlement_lines=[settlement])

    result = _run()

    assert len(repo_stub.finished) == 1
    finished = repo_stub.finished[0]
    assert finished["status"] == "COMPLETE"
    assert finished["settlement_line_count"] == 1
    assert finished["sales_line_count"] == 1
    assert finished["match_count"] == result.match_count
    assert finished["exception_count"] == result.exception_count
    assert repo_stub.runs[0]["status"] == "RUNNING"


# --- data-foundation.md §5.1.5 point 1: per-marketplace join-key lookup ---------------------
# (pure logic, no DB — the lookup dicts themselves)


def test_join_key_field_lookup_per_marketplace():
    assert _JOIN_KEY_FIELD["MEESHO"] == "line_ref"
    assert _JOIN_KEY_FIELD["AMAZON"] == "order_ref"
    assert _JOIN_KEY_FIELD["FLIPKART"] == "order_ref"


def test_join_key_confidence_lookup_per_marketplace():
    assert _JOIN_KEY_CONFIDENCE["MEESHO"] == Confidence.VERIFIED
    assert _JOIN_KEY_CONFIDENCE["AMAZON"] == Confidence.PROVISIONAL
    assert _JOIN_KEY_CONFIDENCE["FLIPKART"] == Confidence.PROVISIONAL


def test_reconcile_rejects_unmapped_marketplace(monkeypatch: pytest.MonkeyPatch, repo_stub: _RepoStub):
    """Fail closed rather than silently defaulting a join key for a marketplace this design
    never specified (data-foundation.md §5.1.5 only covers MEESHO/AMAZON/FLIPKART)."""
    _wire_data(monkeypatch, sales_lines=[], settlement_lines=[])
    with pytest.raises(ValueError, match="no join-key mapping"):
        reconcile(
            _TENANT,
            marketplace="SNAPDEAL",
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            as_of_date=_AS_OF,
            computed_at=_COMPUTED_AT,
        )


def test_run_row_join_key_validated_true_for_meesho(monkeypatch: pytest.MonkeyPatch, repo_stub: _RepoStub):
    _wire_data(monkeypatch, sales_lines=[], settlement_lines=[])
    _run()
    assert repo_stub.runs[0]["join_key_validated"] is True


# --- data-foundation.md §5.1.5 point 2 / Amazon amount-gap handling, at the composition level -


def test_amazon_orphan_settlement_with_none_amount_skipped_and_counted(
    monkeypatch: pytest.MonkeyPatch, repo_stub: _RepoStub
):
    """A settlement row with gross_settlement_amount=None (real Amazon shape — amazon.settlement.v2
    never populates it) must never mint an ORPHAN_SETTLEMENT exception — skipped, counted in
    amount_unavailable_count, never defaulted to zero."""
    settlement = _settlement_line(order_ref="AMZ-ORDER-1", line_ref=None, gross_settlement_amount=None)
    settlement["marketplace"] = "AMAZON"

    _wire_data(monkeypatch, sales_lines=[], settlement_lines=[settlement])

    result = reconcile(
        _TENANT,
        marketplace="AMAZON",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        computed_at=_COMPUTED_AT,
    )

    assert result.exception_count == 0
    assert repo_stub.exceptions == []
    assert result.amount_unavailable_count == 1


def test_amazon_ambiguous_match_confidence_capped_at_provisional_even_when_verified(
    monkeypatch: pytest.MonkeyPatch, repo_stub: _RepoStub
):
    """deterministic-engine.md §5.12.2: even a VERIFIED underlying settlement_line row's own
    field-mapping confidence must never let an Amazon exception present better than
    PROVISIONAL — the join-key confidence cap folds in regardless."""
    sales_a = _sales_line(sales_line_id=uuid4(), order_ref="AMZ-ORDER-1", line_ref=None, confidence="VERIFIED")
    sales_a["marketplace"] = "AMAZON"
    sales_b = _sales_line(sales_line_id=uuid4(), order_ref="AMZ-ORDER-1", line_ref=None, confidence="VERIFIED")
    sales_b["marketplace"] = "AMAZON"
    # Order-grain collision: two real Amazon sales_line rows sharing one order_ref (§5.1.5,
    # "consequence of order-grain matching").
    settlement = _settlement_line(
        order_ref="AMZ-ORDER-1", line_ref=None, gross_settlement_amount=9_999, confidence="VERIFIED"
    )
    settlement["marketplace"] = "AMAZON"

    _wire_data(monkeypatch, sales_lines=[sales_a, sales_b], settlement_lines=[settlement])

    result = reconcile(
        _TENANT,
        marketplace="AMAZON",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        computed_at=_COMPUTED_AT,
    )

    assert repo_stub.runs[0]["join_key_validated"] is False
    assert result.exception_count == 1
    exc = repo_stub.exceptions[0]
    assert exc["exception_type"] == "AMBIGUOUS_MATCH"
    # Both underlying rows are VERIFIED, but the AMAZON join-key confidence (PROVISIONAL) caps
    # the result — combine_confidence is monotonic, weakest input wins.
    assert exc["confidence"] == "PROVISIONAL"
    assert result.exception_metric_results[0].confidence == "PROVISIONAL"
