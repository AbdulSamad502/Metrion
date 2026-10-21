"""detect -> parse -> validate -> assign confidence — pure, in-memory, no DB I/O. Mirrors
calc-engine's formula-layer purity: this function's output is fully determined by its inputs,
same file+same adapter version always produces the same findings (data-foundation.md §3.1
rule 3's idempotence, at the parse level).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from calc_engine.types import Confidence
from data_foundation.types import FileSample, MarketplaceAdapter, ParsedRow, RawFile
from data_foundation.validation.rules import (
    v_col_001_unknown_columns,
    v_cur_001_currency_is_inr,
    v_enum_001_unmapped_enum_values,
    v_fee_001_rate_amount_reconciliation,
    v_fee_002_duplicate_fee_candidates,
    v_id_001_required_identifiers,
    v_map_001_unparseable_cells,
    v_qty_001_positive_quantity,
    v_sum_001_components_sum_to_total,
    v_tax_001_interstate_tax_head,
    v_tax_002_cgst_sgst_parity,
    v_tax_003_gst_rate_plausibility,
)
from data_foundation.validation.severity import Finding, Severity

# §7.4: ">20% of rows quarantined -> fail the whole run; the file is presumed mismatched."
# Fraction, not float — this package stays float-free throughout, same rule as calc-engine.
QUARANTINE_THRESHOLD = Fraction(1, 5)


class AdapterMismatchError(Exception):
    """§7.4: "Adapter cannot detect format -> Reject at upload with the expected-column diff.
    No partial ingest." Carries the missing-column diff, never a partial result."""

    def __init__(self, missing_columns: tuple[str, ...]) -> None:
        self.missing_columns = missing_columns
        super().__init__(f"adapter did not match: missing columns {missing_columns}")


class RunQuarantineThresholdExceeded(Exception):
    """§7.4: too many rows quarantined — the file is presumed mismatched, not just imperfect."""

    def __init__(self, rejected: int, total: int) -> None:
        self.rejected = rejected
        self.total = total
        super().__init__(f"{rejected}/{total} rows quarantined, exceeding the {QUARANTINE_THRESHOLD} threshold")


@dataclass(frozen=True, slots=True)
class RowResult:
    row: ParsedRow
    findings: tuple[Finding, ...]
    confidence: Confidence
    quarantined: bool  # True if any finding is ERROR-severity


@dataclass(frozen=True, slots=True)
class IngestionResult:
    row_results: tuple[RowResult, ...]
    row_count_read: int
    row_count_accepted: int
    row_count_rejected: int


def _validate_row(row: ParsedRow, *, required_fields: tuple[str, ...], plausible_gst_rates: frozenset[Decimal]) -> list[Finding]:
    findings: list[Finding] = []
    findings += v_col_001_unknown_columns(row)
    findings += v_enum_001_unmapped_enum_values(row)
    findings += v_cur_001_currency_is_inr(row)
    findings += v_qty_001_positive_quantity(row)
    findings += v_tax_001_interstate_tax_head(row)
    findings += v_tax_002_cgst_sgst_parity(row)
    findings += v_tax_003_gst_rate_plausibility(row, plausible_rates_pct=plausible_gst_rates)
    findings += v_fee_001_rate_amount_reconciliation(row)
    findings += v_fee_002_duplicate_fee_candidates(row)
    findings += v_sum_001_components_sum_to_total(row)
    findings += v_id_001_required_identifiers(row, required_fields=required_fields)
    findings += v_map_001_unparseable_cells(row)
    # V-DATE-001/002, V-SETL-001, V-PER-001 operate on already-normalised dates / run-level /
    # settlement-side data respectively — composed by the caller around this function, not
    # inside it (see this module's docstring: pure per-row validation only).
    return findings


def run_ingestion(
    adapter: MarketplaceAdapter,
    sample: FileSample,
    raw_file: RawFile,
    *,
    required_fields: tuple[str, ...] = (),
    plausible_gst_rates: frozenset[Decimal] = frozenset(),
    enforce_quarantine_threshold: bool = True,
) -> IngestionResult:
    detection = adapter.detect(sample)
    if not detection.matched:
        raise AdapterMismatchError(detection.missing_columns)

    row_results: list[RowResult] = []
    for row in adapter.parse(raw_file):
        findings = _validate_row(row, required_fields=required_fields, plausible_gst_rates=plausible_gst_rates)
        quarantined = any(f.severity == Severity.ERROR for f in findings)
        # §7.1: every binding in every v1 adapter is is_verified=False (§2.3) — confidence is
        # therefore PROVISIONAL uniformly, not computed, a direct stated consequence of that
        # fact, asserted by tests/unit/test_pipeline.py rather than re-derived per row here.
        row_results.append(RowResult(row=row, findings=tuple(findings), confidence=Confidence.PROVISIONAL, quarantined=quarantined))

    total = len(row_results)
    rejected = sum(1 for r in row_results if r.quarantined)
    accepted = total - rejected

    if enforce_quarantine_threshold and total > 0 and Fraction(rejected, total) > QUARANTINE_THRESHOLD:
        raise RunQuarantineThresholdExceeded(rejected, total)

    return IngestionResult(
        row_results=tuple(row_results),
        row_count_read=total,
        row_count_accepted=accepted,
        row_count_rejected=rejected,
    )
