"""End-to-end detect -> parse -> validate -> confidence, in-memory (data-foundation.md §2,
§4, §7.1)."""

from __future__ import annotations

import pytest
from calc_engine.types import Confidence

from data_foundation.adapters.meesho_orders_v1 import adapter as meesho_orders_adapter
from data_foundation.ingestion.pipeline import AdapterMismatchError, RunQuarantineThresholdExceeded, run_ingestion
from data_foundation.types import FileSample, RawFile


def _sample_and_file(rows):
    columns = ("Meesho Order Number", "Sub Order No", "Reason for Credit Entry", "Return Status")
    return FileSample(columns=columns), RawFile(columns=columns, rows=rows)


def test_adapter_mismatch_raises_with_missing_column_diff():
    sample = FileSample(columns=("Meesho Order Number",))
    raw = RawFile(columns=("Meesho Order Number",), rows=[])
    with pytest.raises(AdapterMismatchError) as exc_info:
        run_ingestion(meesho_orders_adapter, sample, raw)
    assert "Sub Order No" in exc_info.value.missing_columns


def test_every_accepted_row_is_provisional_confidence():
    # §7.1: "In v1, every row is PROVISIONAL at best" — a direct, stated consequence of every
    # v1 binding having is_verified=False (§2.3), not something the pipeline computes.
    sample, raw = _sample_and_file(
        [{"Meesho Order Number": "ORD1", "Sub Order No": "SUB1", "Reason for Credit Entry": "", "Return Status": "Delivered"}]
    )
    result = run_ingestion(meesho_orders_adapter, sample, raw)
    assert len(result.row_results) == 1
    assert result.row_results[0].confidence == Confidence.PROVISIONAL


def test_unmapped_enum_value_produces_warning_not_error():
    sample, raw = _sample_and_file(
        [{"Meesho Order Number": "ORD1", "Sub Order No": "SUB1", "Reason for Credit Entry": "", "Return Status": "Delivered"}]
    )
    result = run_ingestion(meesho_orders_adapter, sample, raw)
    row_result = result.row_results[0]
    assert not row_result.quarantined  # V-ENUM-001 is WARNING, never blocks
    assert any(f.rule_id == "V-ENUM-001" for f in row_result.findings)


def test_row_count_accepted_and_rejected_add_up():
    sample, raw = _sample_and_file(
        [
            {"Meesho Order Number": "ORD1", "Sub Order No": "SUB1", "Reason for Credit Entry": "", "Return Status": "Delivered"},
            {"Meesho Order Number": "ORD2", "Sub Order No": "SUB2", "Reason for Credit Entry": "", "Return Status": "Delivered"},
        ]
    )
    result = run_ingestion(meesho_orders_adapter, sample, raw)
    assert result.row_count_read == 2
    assert result.row_count_accepted + result.row_count_rejected == 2


def test_quarantine_threshold_exceeded_fails_whole_run():
    # §7.4: ">20% of rows quarantined -> fail the whole run"
    rows = [
        {"Meesho Order Number": f"ORD{i}", "Sub Order No": f"SUB{i}", "Reason for Credit Entry": "", "Return Status": "Delivered"}
        for i in range(10)
    ]
    sample, raw = _sample_and_file(rows)
    # Force every row to have a real ERROR by requiring an identifier that's always blank.
    with pytest.raises(RunQuarantineThresholdExceeded):
        run_ingestion(meesho_orders_adapter, sample, raw, required_fields=("order_ref", "nonexistent_field"))
