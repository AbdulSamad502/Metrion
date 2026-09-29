"""resolve_line_status — deterministic-engine.md §7.2.1's `cancellation_state_override` /
`return_status_override` / `rto_status_override` fields, added this session to close the CFO
end-to-end evaluation's own headline finding
(`docs/evaluation/cfo-e2e-evaluation-mtr-mock-2026-09-27.md` §1/§3/§4/§11): none of the 3 real
MTR-shaped mock files carried a resolvable cancellation/return/RTO status at all, so
`NET_REALIZED_REVENUE`/`CONTRIBUTION_PROFIT` were `UNAVAILABLE` for 100% of that dataset — a
seller who knows their own order's real outcome had no way to say so.

This module is deliberately tiny: the ENTIRE rule is "an observed status from the marketplace
report always wins; a seller-declared override is consulted only to fill a genuine gap." That
precedence is implemented and tested here, once, so no caller (today's caller-assembled
`CanonicalLine` construction, or a future ingestion-to-canonical composition layer) has to
re-derive it and risk silently letting a seller's override contradict real marketplace data.
"""

from __future__ import annotations


def resolve_line_status(observed: str | None, override: str | None) -> str | None:
    """`observed` is the value read (or resolvable) from the marketplace report itself —
    `CanonicalLine.cancellation_state`/`return_status`/`rto_status` before any override is
    applied. `override` is the seller-declared `cancellation_state_override`/
    `return_status_override`/`rto_status_override` manual_adjustment value for this line, if
    any ACTIVE row exists.

    Returns `observed` unchanged whenever it is not `None` — a resolved marketplace-reported
    status (even a "not cancelled"/"not returned"/"not RTO'd" resolution) is real data and is
    never silently overruled by a seller's override. Returns `override` only when `observed` is
    `None` (the marketplace report carried no resolvable status for this line at all) — the
    exact gap `cancellation_state_override` et al. exist to fill. Returns `None` when both are
    `None` — still genuinely unresolvable, still `UNAVAILABLE` downstream, never guessed."""
    if observed is not None:
        return observed
    return override


def resolve_line_count(observed: int | None, override: int | None) -> int | None:
    """The identical precedence rule as `resolve_line_status`, typed for `returned_qty_override`/
    `rto_qty_override` (deterministic-engine.md §7.2.1, added while building the ingestion-to-
    canonical composition layer, cfo-agent.md §6.16): no real `sales_line` schema column or
    adapter supplies a returned/RTO unit COUNT today (only a status), so `observed` is `None`
    for every real line unless a future returns-report correlation supplies one. Returns `None`
    when both are `None` — the caller (the composition layer) must treat that as a genuinely
    unresolvable count and exclude/block the line rather than defaulting to 0, exactly the same
    "missing input is UNAVAILABLE, never zero" discipline `billable_quantity` already applies
    to a missing `rto_outcome`."""
    if observed is not None:
        return observed
    return override
