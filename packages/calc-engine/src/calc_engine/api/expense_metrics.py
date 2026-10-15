"""Minting `MetricResult`s for the expense aggregates and profit lines — deterministic-engine.md §9.2/§9.3 (Round 6).

Pure and in-memory like `compute_metric.py`: it builds the same stamped `MetricResult` and persists nothing (a caller saves them with
`metric_result_repo.save_many`, supplying the real `target_ref` for the tenant-level rows and the `period` / `config_version`). The inactive
formula versions are stamped as given in `INACTIVE_FORMULA_VERSIONS`; the ledger watermark rides in `input_refs` (no schema change).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID, uuid4

from calc_engine.api.compute_metric import MetricResult
from calc_engine.definitions.expense_definitions import INACTIVE_FORMULA_VERSIONS
from calc_engine.formulas.expense_profit import ProfitStatement
from calc_engine.formulas.ledger_feed import LedgerFeedResult
from calc_engine.types import Paise, RecognitionState, Unavailable
from calc_engine.versioning import derive_canonical_data_version

TENANT_TARGET = "tenant"  # placeholder target_ref for tenant-level rows; the caller substitutes str(tenant_id) when saving


@dataclass(frozen=True, slots=True)
class MintedMetric:
    result: MetricResult
    grain: str
    target_ref: str


def mint_expense_metrics(
    feed: LedgerFeedResult,
    statement: ProfitStatement,
    *,
    ingestion_run_ids: Sequence[UUID | str],
    adapter_versions: Sequence[str],
    active_adjustment_ids: Sequence[UUID | str],
    computed_at: datetime,
    as_of_date: date | None,
) -> list[MintedMetric]:
    cdv = derive_canonical_data_version(ingestion_run_ids, adapter_versions, active_adjustment_ids)
    adjustments = tuple(str(a) for a in active_adjustment_ids)
    out: list[MintedMetric] = []

    def add(code: str, value: Paise | Unavailable, *, basis: str, target: str = TENANT_TARGET, exclusions: tuple[dict, ...] = ()) -> None:
        ok = not isinstance(value, Unavailable)
        out.append(
            MintedMetric(
                result=MetricResult(
                    id=uuid4(), metric_code=code, value_paise=value.value if ok else None,
                    recognition_state=RecognitionState.RECOGNISED if ok else RecognitionState.UNAVAILABLE,
                    confidence="DERIVED", calculation_basis=basis, formula_version=INACTIVE_FORMULA_VERSIONS[code],
                    canonical_data_version=cdv, as_of_date=as_of_date, input_refs=(feed.watermark,), exclusions=exclusions,
                    computed_at=computed_at, is_available=ok, manual_adjustment_set=adjustments,
                    unavailable_reason=None if ok else value.reason,
                ),
                grain="TENANT_PERIOD", target_ref=target,
            )
        )

    def reason(line: str, why: str | None, detail: str | None = None) -> tuple[dict, ...]:
        return ({"line": line, "reason": why, "detail": detail},) if why else ()

    add("EXPENSE_TOTAL", feed.expense_total, basis="Σ counted ledger rows (confirmed, incremental), signed (engine spec §5.17)")
    for category, amount in feed.by_category.items():
        add("EXPENSE_BY_CATEGORY", amount, basis="Σ counted ledger rows per category (§5.17)", target=category)
    for cls, amount in feed.by_cost_class.items():
        add("EXPENSE_BY_COST_CLASS", amount, basis="Σ counted ledger rows per cost class (§5.17)", target=cls)
    add("EXPENSE_RECURRING_TOTAL", feed.recurring_total, basis="Σ counted recurring ledger rows (§5.17)")
    add("EXPENSE_REVIEW_QUEUE_AMOUNT", feed.review_queue_amount, basis="amounts awaiting review, not counted in any pool (§5.17)")
    add("EXPENSE_INCLUDING_UNRESOLVED", feed.including_unresolved, basis="counted rows plus the review queue (§5.17)")

    add("UNALLOCATED_ADVERTISING", statement.unallocated_advertising, basis="advertising pool not allocated (§5.8.1)",
        exclusions=reason("UNALLOCATED_ADVERTISING", statement.advertising_reason))
    add("UNALLOCATED_STORAGE", statement.unallocated_storage, basis="storage pool not allocated (§5.8.1)",
        exclusions=reason("UNALLOCATED_STORAGE", statement.storage_reason))
    add("UNALLOCATED_OVERHEAD", statement.unallocated_overhead, basis="overhead pool not allocated (§5.8.1)",
        exclusions=reason("UNALLOCATED_OVERHEAD", statement.overhead_reason, statement.overhead_detail))
    add("ALLOCATED_OVERHEAD", statement.allocated_overhead, basis="overhead allocated on the seller-selected basis (§5.8.1)")

    add("CONTRIBUTION_PROFIT", statement.contribution_profit, basis="ContributionProfit.v2: no overhead term; includes StorageCosts (§5.8, §5.8.1)")
    add("FULLY_ALLOCATED_PROFIT", statement.fully_allocated_profit, basis="ContributionProfit − AllocatedOverhead (§5.8.1)")
    add("TOTAL_PROFIT", statement.total_profit, basis="Total profit, Option A: includes all pools, allocated and unallocated (§5.8.1)")
    return out
