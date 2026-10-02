"""reconcile() — Leak Shield's real reconciliation function.

deterministic-engine.md §5.13.1: `reconcile(period, marketplace, tolerance_ref) ->
reconciliation_exception[] + a metric_result for each aggregate`. This module is the
composition layer that implements data-foundation.md §5.8's two-path algorithm verbatim
against the real repositories, tables and pure formulas that already exist in this codebase
(`calc_engine.formulas.leak`, `calc_engine.repositories.canonical_repo`/`settlement_repo`/
`config_repo`, `calc_engine.repositories.reconciliation_repo` for the three
`reconciliation_run`/`reconciliation_match`/`reconciliation_exception` tables, schema and
outcome-to-table mapping: data-foundation.md §5.9, authoritative field mapping:
`packages/calc-engine/migrations/versions/20260925_0004_reconciliation_tables.py`'s module
docstring). `calc_engine.formulas.leak` itself never touches a repository or a database — this
module is the only place that fetches real rows and calls those pure functions against them.

**Per-marketplace join key (data-foundation.md §5.1.5, extended this session).** `line_ref`
(`sub_order_num` on the real Meesho exports) remains Meesho's join key — data-foundation.md §5.1
confirms it as Meesho's validated key. Amazon and Flipkart now also run through this function,
matched on `order_ref` only (order-grain, not line-item-grain — neither adapter's settlement
side binds a real line-item candidate to `settlement_line.line_ref` today, §5.1.5 point 1) — a
small `_JOIN_KEY_FIELD` lookup below, not a marketplace-generic abstraction invented for keys
that were never validated. Every Amazon/Flipkart match/exception this function produces is
capped at `PROVISIONAL` confidence and flagged `reconciliation_run.join_key_validated = false`
(deterministic-engine.md §5.12.2) — real output against an honestly-disclosed unvalidated join,
never upgraded to Meesho's validated-key status by running it.

**Decision A (this session, confirmed).** No adapter in this codebase currently produces
INVOICE-side (`source_side='INVOICE'`) `line_component` rows at all — verified,
`meesho_tcs_sales_v1.py`/`meesho_orders_v1.py` map zero `component_code`s. `classify_variance()`
is therefore invoked ONLY for a `component_code` present as a `line_component` row on BOTH the
settlement side AND the invoice side for a matched pair (a true set intersection of the two
sides' `component_code`s, by presence — not by nonzero amount). A `component_code` present only
on the settlement side is never defaulted to a zero invoice amount and never classified as any
kind of exception — it is silently skipped for that pair, a genuine `Unavailable` case, not a
leak. Against today's real data this means `reconcile()` produces zero
`VARIANCE_EXCEEDS_TOLERANCE` rows and zero `reconciliation_match` rows from the variance path —
confirmed-expected, not a bug (see `tests/integration/test_reconcile_real_meesho_data.py`).

**Decision B (this session, confirmed).** Real `sales_line` rows from `meesho_tcs_sales_v1.py`
carry `invoice_date`/`dispatch_date`/`order_date` all `None` (that adapter maps no date
column), and `dates.resolve_document_date()` raises `ValueError` when all three are `None`.
Path B checks date presence BEFORE calling `resolve_document_date()`; a sales_line with all
three dates `None` is skipped for lag classification entirely (no row emitted, no crash) and
counted in `ReconcileResult.dates_missing_count` — quarantine-and-disclose, never a guessed
date and never a crashed run.

A fully dateless `sales_line` also can never be *fetched* by `canonical_repo.sales_lines_in_period()`
in the first place — that function's own `coalesce(invoice_date, dispatch_date, order_date)
BETWEEN :period_start AND :period_end` filter evaluates to NULL/false for such a row, correctly
excluding it for that function's OTHER real callers (`compute_period_pnl`, GST period summary),
where a dateless line must never silently enter a period revenue/P&L figure. This module
therefore also calls `canonical_repo.sales_lines_without_document_date()` (a second,
`reconcile()`-specific, non-period-bounded fetch, coordinator-approved this session) and merges
its rows with `sales_lines_in_period()`'s, deduped by `sales_line_id` — the two sets are disjoint
by construction (one requires all three dates NULL, the other requires `coalesce(...)` non-NULL
and in-range) but this module dedupes explicitly rather than assuming that invariant silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from calc_engine.api.compute_metric import MetricResult
from calc_engine.dates import resolve_document_date
from calc_engine.formulas.leak import (
    Collision,
    NoCandidate,
    ReconciliationOutcome,
    SingleMatch,
    classify_settlement_lag,
    classify_variance,
    is_duplicate_settlement,
    leak_aggregate,
    leak_amount,
    resolve_match_candidates,
    resolve_tolerance_or_unavailable,
    should_report_unsettled_as_leak,
)
from calc_engine.repositories import canonical_repo, config_repo, reconciliation_repo, settlement_repo
from calc_engine.types import Confidence, Paise, RecognitionState, Unavailable, combine_confidence

_FORMULA_VERSION = "reconcile.v1"

# --- Amazon/Flipkart extension (data-foundation.md §5.1.5, deterministic-engine.md §5.12.2) --
# A small, explicit (marketplace -> join_key_field) lookup — the only change reconcile() itself
# needs for §5.1.5 point 1. None of calc_engine.formulas.leak's pure functions
# (resolve_match_candidates, classify_variance, classify_settlement_lag,
# should_report_unsettled_as_leak) reference a marketplace-specific field name — verified by
# reading each one directly this session, confirming the spec's own claim. is_duplicate_settlement
# is the one exception (§5.1.5 point 4) — its own join-key tuple (order_ref, line_ref) is
# unchanged by this lookup; only its None-amount guard was hardened (leak.py).
_JOIN_KEY_FIELD: dict[str, str] = {
    "MEESHO": "line_ref",
    "AMAZON": "order_ref",
    "FLIPKART": "order_ref",
}

# Join-key confidence, distinct from any row's field-mapping confidence (deterministic-engine.md
# §5.12.2, mechanism point 1 — the confidence cap). Folded into every confidence this function
# produces for that marketplace's run via combine_confidence, alongside the row(s)' own
# confidence — combine_confidence is monotonic, so a non-Meesho match/exception can never present
# as better than PROVISIONAL, regardless of the underlying rows' own confidence.
_JOIN_KEY_CONFIDENCE: dict[str, Confidence] = {
    "MEESHO": Confidence.VERIFIED,
    "AMAZON": Confidence.PROVISIONAL,
    "FLIPKART": Confidence.PROVISIONAL,
}

# `MetricResult.canonical_data_version` normally derives from `ingestion_run_ids` /
# `adapter_versions` / `active_adjustment_ids` (see `derive_canonical_data_version` in
# `api/compute_metric.py`) — but `reconcile()`'s own signature (deterministic-engine.md
# §5.13.1: `reconcile(period, marketplace, tolerance_ref)`) accepts none of those, so there is
# nothing to derive a real version from here. This reuses the same literal
# `compute_price_positioning`/`compute_repricing_scenario`/`compute_margin_curve` already use
# for the identical reason (no derivation inputs available) — flagged here, not hidden, exactly
# as their own docstrings flag it.
_NON_CANONICAL = "non-canonical"


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    reconciliation_run_id: UUID
    match_count: int
    exception_count: int
    dates_missing_count: int
    # data-foundation.md §5.1.5 point 2: Amazon's amount-gap counter, mirroring
    # dates_missing_count's own quarantine-and-disclose treatment exactly — incremented, never
    # defaulted to zero, whenever a settlement-row-driven exception (ORPHAN_SETTLEMENT/
    # AMBIGUOUS_MATCH/DUPLICATE_SETTLEMENT) could not be honestly persisted because
    # gross_settlement_amount was None.
    amount_unavailable_count: int
    exception_metric_results: tuple[MetricResult, ...]
    aggregate_metric_result: MetricResult


def _group_settlement_components(rows: list[dict[str, Any]]) -> dict[Any, dict[str, Paise]]:
    """Groups `line_component` rows by `settlement_line_id`, filtered to `source_side ==
    'SETTLEMENT'`, summing `amount` per `component_code` within each line — data-foundation.md
    §5.4's leak signal is per-`component_code`, and a code can legitimately appear on more than
    one row for the same line."""
    grouped: dict[Any, dict[str, Paise]] = {}
    for row in rows:
        if row["source_side"] != "SETTLEMENT":
            continue
        line_id = row["settlement_line_id"]
        code = row["component_code"]
        amount = Paise(row["amount"])
        per_line = grouped.setdefault(line_id, {})
        per_line[code] = per_line.get(code, Paise(0)) + amount
    return grouped


def _group_invoice_components(rows: list[dict[str, Any]]) -> dict[Any, dict[str, Paise]]:
    """`canonical_repo.components_for_lines` does not filter `source_side` at all (its SQL has
    no such WHERE clause) — this function does that filtering in memory, keeping only
    `source_side == 'INVOICE'` rows, per Decision A above."""
    grouped: dict[Any, dict[str, Paise]] = {}
    for row in rows:
        if row["source_side"] != "INVOICE":
            continue
        line_id = row["sales_line_id"]
        code = row["component_code"]
        amount = Paise(row["amount"])
        per_line = grouped.setdefault(line_id, {})
        per_line[code] = per_line.get(code, Paise(0)) + amount
    return grouped


def _mint_exception_metric_result(
    *,
    exception_type: str,
    amount_paise: int,
    confidence: str,
    computed_at: datetime,
    as_of_date: date,
    input_refs: tuple[Any, ...],
) -> MetricResult:
    return MetricResult(
        id=uuid4(),
        metric_code="LEAK_EXCEPTION_AMOUNT",
        value_paise=amount_paise,
        recognition_state=RecognitionState.RECOGNISED,
        confidence=confidence,
        calculation_basis=(
            f"LeakExceptionAmount({exception_type}) — deterministic-engine.md §5.13.1, "
            "data-foundation.md §5.8/§5.9"
        ),
        formula_version=_FORMULA_VERSION,
        canonical_data_version=_NON_CANONICAL,
        as_of_date=as_of_date,
        input_refs=input_refs,
        exclusions=(),
        computed_at=computed_at,
        is_available=True,
    )


def reconcile(
    tenant_id: UUID,
    *,
    marketplace: str,
    period_start: date,
    period_end: date,
    as_of_date: date,
    computed_at: datetime,
) -> ReconcileResult:
    # --- join key + join-key confidence for this marketplace (§5.1.5, §5.12.2) --------------
    if marketplace not in _JOIN_KEY_FIELD:
        raise ValueError(
            f"reconcile() has no join-key mapping for marketplace={marketplace!r} — "
            "data-foundation.md §5.1.5 only specifies MEESHO/AMAZON/FLIPKART; refusing to guess "
            "a join key for an unspecified marketplace rather than silently defaulting one."
        )
    join_key_field = _JOIN_KEY_FIELD[marketplace]
    join_key_confidence = _JOIN_KEY_CONFIDENCE[marketplace]
    # §5.9 / §5.12.2 mechanism point 2: the explicit flag, not confidence alone — true only for
    # Meesho's VERIFIED line_ref key, false for Amazon/Flipkart's unvalidated order_ref-only key.
    join_key_validated = marketplace == "MEESHO"

    # Tolerance config is resolved for a fixed (tenant, marketplace, as_of_date) throughout one
    # run, so the answer per component_code (including "no row" = None) cannot change between
    # rows — look each distinct code up once per run instead of once per matched component and
    # once per unmatched sales line (measured: 37% of the matching loop's time at 300 pairs,
    # for 4 distinct keys). Local to this call: nothing is cached across runs, so a config
    # change is always picked up by the next run.
    _tolerance_by_code: dict[str, dict[str, Any] | None] = {}

    def _resolve_tolerance_row(component_code: str) -> dict[str, Any] | None:
        if component_code not in _tolerance_by_code:
            _tolerance_by_code[component_code] = config_repo.resolve_reconciliation_tolerance(
                tenant_id, marketplace=marketplace, component_code=component_code, as_of_date=as_of_date
            )
        return _tolerance_by_code[component_code]

    # Matches/exceptions are queued and bulk-written (one transaction + executemany per chunk)
    # instead of one transaction per row — nothing below reads them back before the run is
    # marked COMPLETE, and ids are client-generated, so the in-memory results are identical.
    # Chunked so a very large run holds a bounded number of pending rows. Matches always flush
    # before the exceptions that may reference them.
    _FLUSH_AT = 2000
    _pending_matches: list[tuple[UUID, dict[str, Any]]] = []
    _pending_exceptions: list[tuple[UUID, dict[str, Any]]] = []

    def _flush_pending() -> None:
        if _pending_matches or _pending_exceptions:
            reconciliation_repo.insert_reconciliation_rows(
                tenant_id, matches=list(_pending_matches), exceptions=list(_pending_exceptions)
            )
            _pending_matches.clear()
            _pending_exceptions.clear()

    def _queue_match(**fields: Any) -> UUID:
        new_id = uuid4()
        _pending_matches.append((new_id, fields))
        if len(_pending_matches) + len(_pending_exceptions) >= _FLUSH_AT:
            _flush_pending()
        return new_id

    def _queue_exception(**fields: Any) -> UUID:
        new_id = uuid4()
        _pending_exceptions.append((new_id, fields))
        if len(_pending_matches) + len(_pending_exceptions) >= _FLUSH_AT:
            _flush_pending()
        return new_id

    # --- tolerance_config_version for the run row -------------------------------------------
    # The run's own `tolerance_config_version` column is a single scalar, but tolerance config
    # is resolved per-component throughout the run (potentially several different `version`
    # values). This uses the marketplace-wide default row's (`component_code='*'`) version as
    # the run-level figure — the same default row Path B below independently needs for
    # settlement_lag_days/grace_period_days, so this is not an extra invented lookup, just an
    # early use of one already required. If no marketplace-wide default row exists at all,
    # `0` is a documented sentinel (never a guessed real version), only there to satisfy the
    # migration's `NOT NULL` constraint on this column.
    default_tolerance_row = _resolve_tolerance_row("*")
    tolerance_config_version = int(default_tolerance_row["version"]) if default_tolerance_row else 0

    run_id = reconciliation_repo.insert_reconciliation_run(
        tenant_id,
        marketplace=marketplace,
        period_start=period_start,
        period_end=period_end,
        as_of_date=as_of_date,
        tolerance_config_version=tolerance_config_version,
        formula_version=_FORMULA_VERSION,
        status="RUNNING",
        join_key_validated=join_key_validated,
        started_at=computed_at,
    )

    # --- fetch + in-memory marketplace filter (neither repo function filters by marketplace) -
    # The marketplace filter is pushed into SQL (other marketplaces' rows are never fetched); the
    # Python re-filter stays as a cheap guard so this stays correct against any caller/stub that
    # returns mixed rows.
    all_settlement_lines = settlement_repo.settlement_lines_in_period(
        tenant_id, period_start=period_start, period_end=period_end, marketplace=marketplace
    )
    settlement_lines = [row for row in all_settlement_lines if row["marketplace"] == marketplace]

    all_sales_lines = canonical_repo.sales_lines_in_period(
        tenant_id, period_start=period_start, period_end=period_end, marketplace=marketplace
    )
    dated_sales_lines = [row for row in all_sales_lines if row["marketplace"] == marketplace]

    # Decision B: sales_lines_in_period()'s own coalesce(...)-BETWEEN filter correctly (for its
    # OTHER callers, e.g. compute_period_pnl) excludes a sales_line with all three dates NULL —
    # a dateless line's coalesce() is NULL, and NULL BETWEEN never matches. Path B below still
    # needs to see those real dateless rows (to count them in dates_missing_count, never to
    # silently drop them), so they are fetched separately, never by widening that function's own
    # period filter (money-correctness for its other callers, out of scope to touch here).
    dateless_sales_lines = canonical_repo.sales_lines_without_document_date(tenant_id, marketplace=marketplace)

    # By construction these two sets are disjoint (one requires coalesce(...) to be non-NULL and
    # in-range, the other requires all three dates NULL) — deduped by sales_line_id anyway rather
    # than assuming that invariant silently holds.
    sales_lines_by_id: dict[Any, dict[str, Any]] = {}
    for row in dated_sales_lines + dateless_sales_lines:
        sales_lines_by_id[row["sales_line_id"]] = row
    sales_lines = list(sales_lines_by_id.values())

    settlement_line_count = len(settlement_lines)
    sales_line_count = len(sales_lines)

    # --- join index: sales_line by this marketplace's join_key_field (§5.1.5) ---------------
    sales_index: dict[str, list[dict[str, Any]]] = {}
    for sales_line in sales_lines:
        join_key_value = sales_line.get(join_key_field)
        if join_key_value is not None:
            sales_index.setdefault(join_key_value, []).append(sales_line)

    # --- batch-fetch components up front, never per-row ---------------------------------------
    settlement_component_rows = settlement_repo.components_for_settlement_lines(
        tenant_id, settlement_line_ids=[row["settlement_line_id"] for row in settlement_lines]
    )
    settlement_components_by_line = _group_settlement_components(settlement_component_rows)

    sales_component_rows = canonical_repo.components_for_lines(
        tenant_id, sales_line_ids=[row["sales_line_id"] for row in sales_lines]
    )
    invoice_components_by_line = _group_invoice_components(sales_component_rows)

    match_count = 0
    exception_count = 0
    amount_unavailable_count = 0
    exception_metric_results: list[MetricResult] = []
    all_exception_amounts: list[Paise] = []

    matched_or_collided_sales_line_ids: set[Any] = set()
    already_processed_settlement_lines: list[dict[str, Any]] = []

    # Deterministic processing order: neither repository guarantees Postgres row order, so
    # settlement_lines are sorted by settlement_line_id (arbitrary but fully reproducible
    # across runs against the same committed data).
    ordered_settlement_lines = sorted(settlement_lines, key=lambda row: str(row["settlement_line_id"]))

    # --- Path A --------------------------------------------------------------------------------
    for settlement_line in ordered_settlement_lines:
        candidates = sales_index.get(settlement_line.get(join_key_field), [])
        resolution = resolve_match_candidates(candidates)

        if isinstance(resolution, Collision):
            for candidate in resolution.candidates:
                matched_or_collided_sales_line_ids.add(candidate["sales_line_id"])
            # §5.1.5 point 2: never mint an AMBIGUOUS_MATCH exception against an amount that
            # doesn't exist (Amazon's structural gap) — skip, count, never fabricate.
            if settlement_line["gross_settlement_amount"] is None:
                amount_unavailable_count += 1
                continue
            exception_confidence = combine_confidence(
                Confidence(settlement_line["confidence"]), join_key_confidence
            )
            exception_id = _queue_exception(
                reconciliation_run_id=run_id,
                exception_type="AMBIGUOUS_MATCH",
                settlement_line_id=settlement_line["settlement_line_id"],
                candidate_sales_line_ids=[c["sales_line_id"] for c in resolution.candidates],
                marketplace=marketplace,
                amount_paise=settlement_line["gross_settlement_amount"],
                confidence=exception_confidence.value,
                formula_version=_FORMULA_VERSION,
                computed_at=computed_at,
            )
            exception_count += 1
            amount = Paise(settlement_line["gross_settlement_amount"])
            all_exception_amounts.append(amount)
            exception_metric_results.append(
                _mint_exception_metric_result(
                    exception_type="AMBIGUOUS_MATCH",
                    amount_paise=amount.value,
                    confidence=exception_confidence.value,
                    computed_at=computed_at,
                    as_of_date=as_of_date,
                    input_refs=(exception_id,),
                )
            )
            continue

        if isinstance(resolution, NoCandidate):
            # §5.1.5 point 2: same amount-gap guard for ORPHAN_SETTLEMENT.
            if settlement_line["gross_settlement_amount"] is None:
                amount_unavailable_count += 1
                continue
            exception_confidence = combine_confidence(
                Confidence(settlement_line["confidence"]), join_key_confidence
            )
            exception_id = _queue_exception(
                reconciliation_run_id=run_id,
                exception_type="ORPHAN_SETTLEMENT",
                settlement_line_id=settlement_line["settlement_line_id"],
                marketplace=marketplace,
                amount_paise=settlement_line["gross_settlement_amount"],
                confidence=exception_confidence.value,
                formula_version=_FORMULA_VERSION,
                computed_at=computed_at,
            )
            exception_count += 1
            amount = Paise(settlement_line["gross_settlement_amount"])
            all_exception_amounts.append(amount)
            exception_metric_results.append(
                _mint_exception_metric_result(
                    exception_type="ORPHAN_SETTLEMENT",
                    amount_paise=amount.value,
                    confidence=exception_confidence.value,
                    computed_at=computed_at,
                    as_of_date=as_of_date,
                    input_refs=(exception_id,),
                )
            )
            continue

        # SingleMatch
        assert isinstance(resolution, SingleMatch)
        matched_or_collided_sales_line_ids.add(resolution.candidate["sales_line_id"])

        if is_duplicate_settlement(
            candidate=settlement_line, already_processed=already_processed_settlement_lines
        ):
            already_processed_settlement_lines.append(settlement_line)
            # §5.1.5 point 2: same amount-gap guard for DUPLICATE_SETTLEMENT — structurally
            # unreachable for Amazon today anyway (is_duplicate_settlement's own None-amount
            # guard, leak.py), kept here too for defensive symmetry with the other two
            # settlement-row-driven exception types.
            if settlement_line["gross_settlement_amount"] is None:
                amount_unavailable_count += 1
                continue
            exception_confidence = combine_confidence(
                Confidence(settlement_line["confidence"]), join_key_confidence
            )
            exception_id = _queue_exception(
                reconciliation_run_id=run_id,
                exception_type="DUPLICATE_SETTLEMENT",
                settlement_line_id=settlement_line["settlement_line_id"],
                marketplace=marketplace,
                amount_paise=settlement_line["gross_settlement_amount"],
                confidence=exception_confidence.value,
                formula_version=_FORMULA_VERSION,
                computed_at=computed_at,
            )
            exception_count += 1
            amount = Paise(settlement_line["gross_settlement_amount"])
            all_exception_amounts.append(amount)
            exception_metric_results.append(
                _mint_exception_metric_result(
                    exception_type="DUPLICATE_SETTLEMENT",
                    amount_paise=amount.value,
                    confidence=exception_confidence.value,
                    computed_at=computed_at,
                    as_of_date=as_of_date,
                    input_refs=(exception_id,),
                )
            )
            continue

        already_processed_settlement_lines.append(settlement_line)

        # Genuine single resolved, non-duplicate pair — Decision A's per-component_code
        # intersection.
        sales_line = resolution.candidate
        settlement_codes = settlement_components_by_line.get(settlement_line["settlement_line_id"], {})
        invoice_codes = invoice_components_by_line.get(sales_line["sales_line_id"], {})
        shared_codes = set(settlement_codes.keys()) & set(invoice_codes.keys())

        for component_code in sorted(shared_codes):
            tolerance_row = _resolve_tolerance_row(component_code)
            tolerance = resolve_tolerance_or_unavailable(tolerance_row)
            if isinstance(tolerance, Unavailable):
                # No tolerance config for this (marketplace, component_code) — skip, never
                # invent a default tolerance (§5.12.1).
                continue
            tolerance_paise, tolerance_bps = tolerance

            invoice_amount = invoice_codes[component_code]
            settlement_amount = settlement_codes[component_code]
            outcome = classify_variance(
                invoice_amount,
                settlement_amount,
                tolerance_paise=tolerance_paise,
                tolerance_bps=tolerance_bps,
            )
            variance = leak_amount(invoice_amount, settlement_amount)

            # A match combines both sides' data — never presented as more certain than either
            # side's own weakest confidence (data-foundation.md §7.1). The marketplace's
            # join-key confidence is folded in as one more input (deterministic-engine.md
            # §5.12.2): an Amazon/Flipkart match can never present better than PROVISIONAL
            # regardless of how strong sales_line/settlement_line's own confidence is.
            match_confidence = combine_confidence(
                Confidence(sales_line["confidence"]),
                Confidence(settlement_line["confidence"]),
                join_key_confidence,
            )

            match_id = _queue_match(
                reconciliation_run_id=run_id,
                sales_line_id=sales_line["sales_line_id"],
                settlement_line_id=settlement_line["settlement_line_id"],
                component_code=component_code,
                outcome=outcome.value,
                variance_paise=variance.value,
                confidence=match_confidence.value,
                formula_version=_FORMULA_VERSION,
                computed_at=computed_at,
            )
            match_count += 1

            if outcome == ReconciliationOutcome.VARIANCE_EXCEEDS_TOLERANCE:
                exception_id = _queue_exception(
                    reconciliation_run_id=run_id,
                    reconciliation_match_id=match_id,
                    exception_type="VARIANCE_EXCEEDS_TOLERANCE",
                    sales_line_id=sales_line["sales_line_id"],
                    settlement_line_id=settlement_line["settlement_line_id"],
                    component_code=component_code,
                    marketplace=marketplace,
                    amount_paise=variance.value,
                    confidence=match_confidence.value,
                    formula_version=_FORMULA_VERSION,
                    computed_at=computed_at,
                )
                exception_count += 1
                all_exception_amounts.append(variance)
                exception_metric_results.append(
                    _mint_exception_metric_result(
                        exception_type="VARIANCE_EXCEEDS_TOLERANCE",
                        amount_paise=variance.value,
                        confidence=match_confidence.value,
                        computed_at=computed_at,
                        as_of_date=as_of_date,
                        input_refs=(exception_id, match_id),
                    )
                )

    # --- Path B --------------------------------------------------------------------------------
    dates_missing_count = 0
    for sales_line in sales_lines:
        if sales_line["sales_line_id"] in matched_or_collided_sales_line_ids:
            continue

        invoice_date = sales_line.get("invoice_date")
        dispatch_date = sales_line.get("dispatch_date")
        order_date = sales_line.get("order_date")
        if invoice_date is None and dispatch_date is None and order_date is None:
            # Decision B: never crash on a genuinely dateless line — count and skip.
            dates_missing_count += 1
            continue

        document_date = resolve_document_date(invoice_date, dispatch_date, order_date)

        lag_row = _resolve_tolerance_row("*")
        if lag_row is None:
            # No marketplace-wide default config at all — never invent a lag threshold.
            continue

        settlement_lag_days = int(lag_row["settlement_lag_days"])
        outcome = classify_settlement_lag(
            document_date=document_date, as_of_date=as_of_date, settlement_lag_days=settlement_lag_days
        )
        if outcome != ReconciliationOutcome.UNSETTLED_BEYOND_LAG:
            # UNSETTLED_WITHIN_LAG — never persisted anywhere (§5.9).
            continue

        grace_period_days = int(lag_row["grace_period_days"])
        if not should_report_unsettled_as_leak(
            document_date=document_date,
            as_of_date=as_of_date,
            settlement_lag_days=settlement_lag_days,
            grace_period_days=grace_period_days,
        ):
            continue

        taxable_amount = sales_line.get("taxable_amount")
        if taxable_amount is None:
            # The one invoice-side scalar this exception_type is defined against is itself
            # missing — never default to zero, skip rather than fabricate an amount.
            continue

        # §5.12.2: the cap applies to Path B too — an unvalidated join key can produce a false
        # negative (a real settlement exists but the candidate key failed to find it) just as it
        # can produce a false positive collision, so this UNSETTLED_BEYOND_LAG exception's
        # confidence is capped by the same join-key confidence as every Path A outcome.
        path_b_confidence = combine_confidence(Confidence(sales_line["confidence"]), join_key_confidence)
        exception_id = _queue_exception(
            reconciliation_run_id=run_id,
            exception_type="UNSETTLED_BEYOND_LAG",
            sales_line_id=sales_line["sales_line_id"],
            marketplace=marketplace,
            amount_paise=taxable_amount,
            confidence=path_b_confidence.value,
            formula_version=_FORMULA_VERSION,
            computed_at=computed_at,
        )
        exception_count += 1
        amount = Paise(taxable_amount)
        all_exception_amounts.append(amount)
        exception_metric_results.append(
            _mint_exception_metric_result(
                exception_type="UNSETTLED_BEYOND_LAG",
                amount_paise=amount.value,
                confidence=path_b_confidence.value,
                computed_at=computed_at,
                as_of_date=as_of_date,
                input_refs=(exception_id,),
            )
        )

    # --- aggregate -------------------------------------------------------------------------
    total = leak_aggregate(all_exception_amounts)
    if all_exception_amounts:
        aggregate_confidence = combine_confidence(
            *[Confidence(mr.confidence) for mr in exception_metric_results]
        ).value
    else:
        # Nothing to combine — zero exceptions this run is a real, available result (a
        # genuine LEAK_TOTAL of 0 paise), not UNAVAILABLE; DERIVED documents that it is
        # computed rather than sourced from any single input.
        aggregate_confidence = Confidence.DERIVED.value

    aggregate_metric_result = MetricResult(
        id=uuid4(),
        metric_code="LEAK_TOTAL",
        value_paise=total.value,
        recognition_state=RecognitionState.RECOGNISED,
        confidence=aggregate_confidence,
        calculation_basis=(
            f"LeakAggregate = Σ reconciliation_exception.amount_paise across {exception_count} "
            "exceptions this run (deterministic-engine.md §5.13.1)"
        ),
        formula_version=_FORMULA_VERSION,
        canonical_data_version=_NON_CANONICAL,
        as_of_date=as_of_date,
        input_refs=tuple(mr.id for mr in exception_metric_results),
        exclusions=(),
        computed_at=computed_at,
        is_available=True,
    )

    _flush_pending()
    reconciliation_repo.mark_reconciliation_run_finished(
        tenant_id,
        run_id,
        status="COMPLETE",
        finished_at=computed_at,
        settlement_line_count=settlement_line_count,
        sales_line_count=sales_line_count,
        match_count=match_count,
        exception_count=exception_count,
    )

    return ReconcileResult(
        reconciliation_run_id=run_id,
        match_count=match_count,
        exception_count=exception_count,
        dates_missing_count=dates_missing_count,
        amount_unavailable_count=amount_unavailable_count,
        exception_metric_results=tuple(exception_metric_results),
        aggregate_metric_result=aggregate_metric_result,
    )
