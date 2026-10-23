"""The provenance gate — spec §6.15 R3.

Before a `Figure` can reach the composer or the seller, its ref is resolved against the OWNING table for
THIS tenant. An unresolvable (missing, or another tenant's) ref means the figure is **dropped and the gap
named** — never shown, never guessed. `engine_result_ref` and `estimate_ref` are different contracts and are
never interchangeable (CLAUDE.md): an ENGINE_RESULT ref resolves only in `metric_result`, an ESTIMATE ref only in
`product_feasibility_estimate` (`competitor_estimate` is deferred — CI §1a item 2 — so a ref to it cannot resolve).

This module reads; it computes nothing. A figure that claims to be available but whose `metric_result` row says it
is not is dropped too (a missing input is never presented as a value).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from calc_engine.repositories import metric_result_repo, product_feasibility_estimate_repo
from calc_engine.repositories import expense_tracker_repo, gst_lookup_repo
from competitor_intelligence.repositories import competitor_snapshot_repo

from backend.ceo.contract import Figure, Gap, Ref, RefKind, Register
from backend.repositories import provenance_repo

Resolver = Callable[[UUID, UUID], Mapping[str, Any] | None]

# (kind, source) -> resolver. Anything not listed is unresolvable by design (fail closed).
_RESOLVERS: dict[tuple[RefKind, str | None], Resolver] = {
    (RefKind.ENGINE_RESULT, None): metric_result_repo.get,
    (RefKind.ESTIMATE, None): product_feasibility_estimate_repo.get,
    (RefKind.SELLER_PROVIDED, None): provenance_repo.get_manual_adjustment,
    (RefKind.AGENT_REPORT_FIELD, "leak_finding"): provenance_repo.get_leak_finding,
    (RefKind.AGENT_REPORT_FIELD, "competitor_snapshot"): competitor_snapshot_repo.get_by_id,
    (RefKind.AGENT_REPORT_FIELD, "gst_lookup_result"): gst_lookup_repo.get_by_id,
    (RefKind.AGENT_REPORT_FIELD, "expense_event"): expense_tracker_repo.get_record,  # an Expense Tracker record the seller entered: resolves only inside their own tenant
}

_AS_OF_KEYS = ("computed_at", "created_at", "captured_at", "first_observed_at", "retrieved_at")


@dataclass(frozen=True, slots=True)
class Resolution:
    ref: Ref
    found: bool
    as_of: datetime | None = None
    is_available: bool | None = None  # only meaningful for ENGINE_RESULT rows


def resolve_ref(tenant_id: UUID, ref: Ref, *, resolvers: Mapping[tuple[RefKind, str | None], Resolver] | None = None) -> Resolution:
    table = resolvers if resolvers is not None else _RESOLVERS
    key = (ref.kind, ref.source if ref.kind is RefKind.AGENT_REPORT_FIELD else None)
    resolver = table.get(key)
    if resolver is None:
        return Resolution(ref=ref, found=False)
    row = resolver(tenant_id, ref.id)
    if row is None:
        return Resolution(ref=ref, found=False)
    as_of = next((row[k] for k in _AS_OF_KEYS if isinstance(row.get(k), datetime)), None)
    is_available = bool(row["is_available"]) if ref.kind is RefKind.ENGINE_RESULT and "is_available" in row else None
    return Resolution(ref=ref, found=True, as_of=as_of, is_available=is_available)


def load_ref_row(tenant_id: UUID, ref: Ref, *, resolvers: Mapping[tuple[RefKind, str | None], Resolver] | None = None) -> Mapping[str, Any] | None:
    """The OWNING row a ref points at, for THIS tenant, or None (missing and cross-tenant are indistinguishable by design). Same resolver
    table as `resolve_ref`, so a ref that does not resolve there can never produce a figure here either."""
    table = resolvers if resolvers is not None else _RESOLVERS
    resolver = table.get((ref.kind, ref.source if ref.kind is RefKind.AGENT_REPORT_FIELD else None))
    return resolver(tenant_id, ref.id) if resolver is not None else None


@dataclass(frozen=True, slots=True)
class GateResult:
    kept: tuple[Figure, ...]
    gaps: tuple[Gap, ...]


def gate_figures(
    tenant_id: UUID,
    figures: Iterable[Figure],
    *,
    resolvers: Mapping[tuple[RefKind, str | None], Resolver] | None = None,
) -> GateResult:
    """Keeps only figures whose ref resolves for `tenant_id`; each dropped figure yields a named `Gap`. Kept figures
    carry the resolved row's `as_of` when the figure had none."""
    kept: list[Figure] = []
    gaps: list[Gap] = []
    for figure in figures:
        resolution = resolve_ref(tenant_id, figure.ref, resolvers=resolvers)
        if not resolution.found:
            gaps.append(Gap("UNRESOLVED_REF", f"'{figure.label}' was left out: its source record could not be verified.", figure.ref.id))
            continue
        if resolution.is_available is False and figure.register is not Register.UNAVAILABLE:
            gaps.append(Gap("UNAVAILABLE_AS_REAL", f"'{figure.label}' was left out: its source result is unavailable.", figure.ref.id))
            continue
        kept.append(figure if figure.as_of is not None or resolution.as_of is None else dataclasses.replace(figure, as_of=resolution.as_of))
    return GateResult(kept=tuple(kept), gaps=tuple(gaps))


def _as_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def default_extract_refs(payload: Mapping[str, Any]) -> list[Ref]:
    """Collects the refs a specialist's own structured payload REPORTS: any key whose name contains
    `engineResultRef` becomes an ENGINE_RESULT ref; `estimateRef` an ESTIMATE ref. Values may be a UUID string or a
    list/tuple of them; non-UUID values are ignored. Nested dicts/lists are walked. This never invents a ref — a
    specialist that reports none yields none (and the leg then has no citable figure)."""
    found: list[Ref] = []
    seen: set[tuple[RefKind, UUID]] = set()

    def add(kind: RefKind, raw: Any) -> None:
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        for value in values:
            ident = _as_uuid(value) if value is not None else None
            if ident is not None and (kind, ident) not in seen:
                seen.add((kind, ident))
                found.append(Ref(kind=kind, id=ident))

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                lowered = str(key).lower()
                if "engineresultref" in lowered:
                    add(RefKind.ENGINE_RESULT, value)
                elif "estimateref" in lowered:
                    add(RefKind.ESTIMATE, value)
                else:
                    walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(payload)
    return found


def report_pointers(payload: Mapping[str, Any]) -> dict[str, str]:
    """Top-level keys named `...Id` whose value is a UUID — pointers to the specialist's own persisted records (generation,
    run, snapshot, request ids), stored on the finding as `report_ref` so a later turn can re-open them. Never copies a value;
    `...Ref` keys are provenance refs, handled by `default_extract_refs`, not pointers."""
    return {
        str(k): str(v)
        for k, v in payload.items()
        if isinstance(k, str) and (k == "id" or k.endswith("Id")) and _as_uuid(v) is not None
    }
