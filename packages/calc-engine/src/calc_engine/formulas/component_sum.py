"""sum_components() — the generic component-summation primitive underlying §5.3/§5.4/§5.6/§5.9.

Every formula that sums line_component amounts under some filter (component code, source
side, bearer, RTO exclusion) reduces to a call into this one function, so filter semantics
are defined exactly once.
"""

from __future__ import annotations

from typing import Callable, Sequence

from calc_engine.types import ZERO, Bearer, CanonicalLine, Paise

BearerResolver = Callable[[str, str], Bearer]
"""(marketplace, component_code) -> Bearer, resolved as of the line's document_date by the caller-supplied resolver."""


def sum_components(
    lines: Sequence[CanonicalLine],
    *,
    component_codes: frozenset[str] | None,
    component_kind: str | None = None,
    side: str = "INVOICE",
    bearer: Bearer | None = None,
    bearer_resolver: BearerResolver | None = None,
    exclude_rto_lines: bool = False,
    exclude_codes: frozenset[str] | None = None,
) -> Paise:
    """Sum `line_component.amount` across `lines` under the given filters.

    - `component_codes=None` matches any code (the spec's "*" wildcard, e.g. §5.3's
      `Σ[* where bearer=UNKNOWN]`); a non-None set restricts to those codes.
    - `side`: "INVOICE" | "SETTLEMENT" | "SETTLEMENT_ELSE_INVOICE". The last mirrors §5.6's
      `Σ[FEE where side = settlement, else invoice]` — per line, settlement-side matches are
      used if any exist for that line, otherwise invoice-side matches are used.
    - `bearer`: filters to components whose resolved bearer equals this value. Requires
      `bearer_resolver`. Bearer only has meaning for DISCOUNT components; callers filtering by
      bearer are expected to also pass `component_kind="DISCOUNT"` (or specific discount codes)
      per §5.3 — this function does not assume that on the caller's behalf.
    - `exclude_rto_lines`: skips a line entirely when it is an *actual* return/RTO
      (`return_status == "RETURNED"` or `rto_status == "RTO"`) — used to keep
      `ShippingLogistics` free of return/RTO logistics charges, which belong exclusively to
      `ReturnRTOLosses` (§5.6 amendment). A line whose status is merely *resolved-but-nothing-
      happened* (e.g. `return_status == "DELIVERED"`) is never excluded by this flag — only
      the two literal "something happened" values are.
    - `exclude_codes`: components whose code is in this set never match, regardless of
      `component_codes` — used to keep a code that is already summed unconditionally by one
      term (e.g. `SELLER_DISCOUNT`) from also being picked up by a separate bearer=UNKNOWN
      wildcard term for the same metric, which would otherwise double-count it whenever a
      bearer_resolver has no explicit mapping for that code.
    """
    if bearer is not None and bearer_resolver is None:
        raise ValueError("sum_components: bearer filter requires a bearer_resolver")

    total = ZERO
    for line in lines:
        if exclude_rto_lines and (line.return_status == "RETURNED" or line.rto_status == "RTO"):
            continue

        matching = [
            c
            for c in line.components
            if (component_codes is None or c.component_code in component_codes)
            and (component_kind is None or c.component_kind == component_kind)
            and (exclude_codes is None or c.component_code not in exclude_codes)
        ]

        if side in ("INVOICE", "SETTLEMENT"):
            selected = [c for c in matching if c.source_side == side]
        elif side == "SETTLEMENT_ELSE_INVOICE":
            settlement_matches = [c for c in matching if c.source_side == "SETTLEMENT"]
            selected = settlement_matches if settlement_matches else [c for c in matching if c.source_side == "INVOICE"]
        else:
            raise ValueError(f"sum_components: unknown side {side!r}")

        if bearer is not None:
            assert bearer_resolver is not None
            selected = [c for c in selected if bearer_resolver(line.marketplace, c.component_code) == bearer]

        for component in selected:
            total = total + component.amount

    return total


__all__ = ["sum_components", "BearerResolver"]
