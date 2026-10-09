"""Spec §6.33: the sales history a new-product run reads. It is assembled by code in the engine's FULL line shape, so a returned or RTO unit is never counted as sold
(the reduced GST-summary line shape drops that status). Real engine objects, assembly stubbed at the one DB seam."""

from __future__ import annotations

import uuid
from datetime import date

from calc_engine.formulas.sales_velocity import observed_units_sold
from calc_engine.types import CanonicalLine, ComponentRow, Confidence, Paise

from backend.api.v1.cfo import PeriodPnlLineRequest, _period_pnl_line_to_canonical
from backend.services import cfo_actions, ceo_reads


def line(qty=2, **over):
    base = dict(sales_line_id=uuid.uuid4(), marketplace="AMAZON", document_type="INVOICE", quantity=qty, invoice_date=date(2026, 9, 3), dispatch_date=date(2026, 9, 2),
                order_date=date(2026, 9, 1), gross_item_amount=Paise(100000),
                components=(ComponentRow(id=uuid.uuid4(), component_kind="FEE", component_code="COMMISSION", source_side="MARKETPLACE", amount=Paise(1000)),),
                confidence=Confidence.VERIFIED)
    base.update(over)
    return CanonicalLine(**base)


def outcome(lines, skus, blocked=()):
    sku_by_line = {str(l.sales_line_id): s for l, s in zip(lines, skus)}
    for b, s in blocked:
        sku_by_line[str(b.sales_line_id)] = s
    return cfo_actions.CanonicalAssemblyOutcome(lines=tuple(lines), blocked=tuple(b for b, _ in blocked), sku_by_line=sku_by_line, ingestion_run_ids=(), active_adjustment_ids=())


def test_only_the_named_skus_lines_come_back_blocked_ones_are_counted_with_their_reason(monkeypatch):
    mine, other = line(), line()
    stuck = cfo_actions.CanonicalAssemblyBlockedLine(sales_line_id=uuid.uuid4(), reason="return confirmed but no unit count is known", missing_inputs=("returned_qty_override",))
    elsewhere = cfo_actions.CanonicalAssemblyBlockedLine(sales_line_id=uuid.uuid4(), reason="belongs to another SKU", missing_inputs=())
    monkeypatch.setattr(cfo_actions, "assemble_canonical_lines_for_period", lambda *a, **k: outcome([mine, other], ["SKU-1", "SKU-2"], [(stuck, "SKU-1"), (elsewhere, "SKU-2")]))
    h = ceo_reads.sales_history(uuid.uuid4(), "SKU-1", period_start=date(2026, 9, 1), period_end=date(2026, 9, 30))
    assert [l["sales_line_id"] for l in h.lines] == [str(mine.sales_line_id)]
    assert h.blocked_count == 1 and h.blocked_reasons == ("return confirmed but no unit count is known",)  # named, never silently dropped


def test_a_returned_unit_is_not_counted_as_sold_after_the_round_trip_through_the_route_model(monkeypatch):
    sold = line(qty=5)
    returned = line(qty=3, return_status="RETURNED", returned_qty=2)  # 3 ordered, 2 came back: 1 unit sold
    monkeypatch.setattr(cfo_actions, "assemble_canonical_lines_for_period", lambda *a, **k: outcome([sold, returned], ["SKU-1", "SKU-1"]))
    h = ceo_reads.sales_history(uuid.uuid4(), "SKU-1", period_start=date(2026, 9, 1), period_end=date(2026, 9, 30))
    rebuilt = [_period_pnl_line_to_canonical(PeriodPnlLineRequest.model_validate(d)) for d in h.lines]  # exactly what the batch-size route does with `canonical_lines`
    assert observed_units_sold(rebuilt, date(2026, 9, 30)) == 6  # 5 + (3 - 2)
    assert observed_units_sold([sold, returned], date(2026, 9, 30)) == 6  # identical to the engine's own count on the original lines


def test_no_lines_for_the_sku_is_an_empty_history_not_an_error(monkeypatch):
    monkeypatch.setattr(cfo_actions, "assemble_canonical_lines_for_period", lambda *a, **k: outcome([line()], ["SKU-2"]))
    h = ceo_reads.sales_history(uuid.uuid4(), "SKU-1", period_start=date(2026, 9, 1), period_end=date(2026, 9, 30))
    assert h.lines == () and h.blocked_count == 0
