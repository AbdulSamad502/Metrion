"""Business State — the CEO's verified view of the seller's business (spec §6.13, C16, CP1-D7).

A fixed catalog of read functions over PERSISTED, verified results. It is not a cache of numbers and not a place computation
happens: no fresh computation, no write, no external call, no model call (AC26). "Latest" is an ORDERING of persisted rows, not a
calculation. A missing input is never zero — it is a named `Gap` and the entry reports `UNAVAILABLE`.

Gating order, every read (spec §6.13/§6.22): member permission -> attachment of the owning agent -> the owner's entitlement
(evaluated, never consumed) -> the loader -> the provenance gate (R3). A CFO-class entry therefore needs `agent.cfo` AND CFO
entitlement; permission-without-entitlement yields `NOT_ENTITLED` with `cfo.preview` offered; no permission yields `NOT_PERMITTED`
and no figure (CP1-D3, C17). An agent-owned entry is readable only while that agent is attached (`NOT_ATTACHED` otherwise);
**previously delivered findings are separate evidence and are never touched by attachment** (resolved Q23).

`STALE` needs a configured maximum age, and none is seeded — so B1 never emits `STALE`; `as_of` is always carried and shown
instead. (Inventing a freshness threshold would be an invented business rule.)

**Persisted-source verification (B1, Q18).** Implemented entries each name a source that was verified to exist and be
tenant-scoped. Entries whose source exists but has no tenant-wide read function in the owning package yet are NOT in the catalog
(`DEFERRED_ENTRIES` below states why) — dropped, not worked around, per the spec.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from calc_engine.repositories import manual_adjustment_repo, metric_result_repo
from cfo.repositories import agent_data_request_repo, leak_finding_repo

from backend.auth.context import AuthContext
from backend.auth.permissions import AGENT_CEO, AGENT_CFO, FILES_VIEW, has_permission
from backend.ceo import conflicts as conflict_rules
from backend.ceo import derived_reads, provenance, state_cache
from backend.ceo.contract import (
    AGENT_PERMISSION_KEY,
    AgentCode,
    BusinessStateEntry,
    Conflict,
    EntryStatus,
    Fact,
    Figure,
    Gap,
    Ref,
    RefKind,
    Register,
)
from backend.ceo.figure_format import format_paise, register_for
from backend.services import ceo_reads, cfo_imports

# A presentation bound on how many rows one entry lists — not a business threshold. Truncation is stated as a gap.
MAX_ITEMS_PER_ENTRY = 20
_INGEST_FACT_LIMIT = 5

_PNL_METRICS: Mapping[str, str] = {
    "NET_REALIZED_REVENUE": "Net realized revenue",
    "CONTRIBUTION_PROFIT": "Contribution profit",
    "MARKETPLACE_FEES": "Marketplace fees",
}
_BAND_METRICS: Mapping[str, str] = {
    "CONTRIBUTION_MARGIN_PCT": "Contribution margin",
    "FEE_RATIO_PCT": "Fee ratio",
    "RETURN_RATE_PCT": "Return rate",
}
_OPEN_LEAK_STATUSES = ("NEW", "ACKNOWLEDGED")
_SEVERITY_WEIGHT = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


@dataclass(frozen=True, slots=True)
class StateRead:
    status: EntryStatus
    as_of: datetime | None = None
    period: str | None = None
    figures: tuple[Figure, ...] = ()
    facts: tuple[Fact, ...] = ()
    gaps: tuple[Gap, ...] = ()
    conflicts: tuple[Conflict, ...] = ()


Loader = Callable[[AuthContext, datetime], StateRead]


@dataclass(frozen=True, slots=True)
class StateEntrySpec:
    key: str
    owner: AgentCode | None  # None => CEO-owned (always readable)
    description: str
    persisted_source: str  # what was verified
    loader: Loader
    extra_permissions: tuple[str, ...] = ()
    # The tables this entry is built from, for the L7 cache's data fingerprint (`state_cache`). None = never cached: the result depends on something
    # other than stored rows (CI's staleness label depends on the clock), so a fingerprint would not be enough to know it is still current.
    source_tables: tuple[str, ...] | None = None


# --------------------------------------------------------------------------------------------- loaders
def _latest_pnl_rows(tenant_id: UUID) -> tuple[str | None, dict[str, Mapping[str, Any]], list[Conflict]]:
    """The newest persisted TENANT_PERIOD label across the P&L metrics, and the newest-computed row per metric for it.
    Ordering only: the period label begins with its ISO start date, so it sorts chronologically (metric_result_repo docs)."""
    rows_by_code = {code: [r for r in metric_result_repo.list_by_metric_code(tenant_id, metric_code=code) if r.get("period")]
                    for code in _PNL_METRICS}
    periods = [str(r["period"]) for rows in rows_by_code.values() for r in rows]
    if not periods:
        return None, {}, []
    latest = max(periods)
    chosen: dict[str, Mapping[str, Any]] = {}
    for code, rows in rows_by_code.items():
        match = [r for r in rows if str(r["period"]) == latest]
        if match:
            chosen[code] = max(match, key=lambda r: r["computed_at"])
    found = conflict_rules.metric_conflicts(
        [r for rows in rows_by_code.values() for r in rows if str(r["period"]) == latest],
        figure_for=lambda r: _figure_from_metric_row(_PNL_METRICS[str(r["metric_code"])], r),
        what_for=lambda r: f"{_PNL_METRICS[str(r['metric_code'])]} ({latest})",
    )
    # Only a disagreement over the result the seller would otherwise be shown is reported: an older, superseded input set that disagreed with itself is history.
    shown = {UUID(str(r["id"])) for r in chosen.values()}
    return latest, chosen, [c for c in found if c.a.ref.id in shown]


def recent_periods(tenant_id: UUID, *, limit: int) -> list[str]:
    """The newest distinct persisted P&L period labels ("start/end" ISO), newest first: for offering the seller a real choice of period. Ordering only
    (a period label begins with its ISO start date, so it sorts chronologically); nothing is computed."""
    labels: set[str] = set()
    for code in _PNL_METRICS:
        for r in metric_result_repo.list_by_metric_code(tenant_id, metric_code=code):
            period = str(r.get("period") or "")
            if period.count("/") == 1 and all(len(p) == 10 for p in period.split("/")):
                labels.add(period)
    return sorted(labels, reverse=True)[:limit]


def _figure_from_metric_row(label: str, row: Mapping[str, Any]) -> Figure:
    available = bool(row["is_available"])
    return Figure(
        label=label,
        formatted_value=format_paise(row.get("value_paise"), is_available=available),
        register=register_for(is_available=available, confidence=row.get("confidence")),
        ref=Ref(RefKind.ENGINE_RESULT, UUID(str(row["id"])), as_of=row["computed_at"]),
        as_of=row["computed_at"],
        note=None if available else (row.get("unavailable_reason") or "unavailable"),
    )


def _load_pnl_latest(ctx: AuthContext, now: datetime) -> StateRead:
    assert ctx.tenant_id is not None
    period, rows, found = _latest_pnl_rows(ctx.tenant_id)
    if period is None:
        return StateRead(
            EntryStatus.UNAVAILABLE,
            gaps=(Gap("NO_PNL", "No profit & loss has been computed yet — upload your reports and run the P&L first."),),
        )
    figures = tuple(_figure_from_metric_row(_PNL_METRICS[c], rows[c]) for c in _PNL_METRICS if c in rows)
    gaps: list[Gap] = [Gap(f"NO_{c}", f"{_PNL_METRICS[c]} has not been computed for {period}.") for c in _PNL_METRICS if c not in rows]
    gaps += [
        Gap(f"UNAVAILABLE_{c}", f"{_PNL_METRICS[c]} is unavailable for {period}: {rows[c].get('unavailable_reason') or 'unavailable'}.")
        for c in _PNL_METRICS if c in rows and not rows[c]["is_available"]
    ]
    return StateRead(
        EntryStatus.PARTIAL if gaps else EntryStatus.AVAILABLE,
        as_of=max(f.as_of for f in figures if f.as_of is not None), period=period, figures=figures, gaps=tuple(gaps), conflicts=tuple(found),
    )


def _load_leak_open(ctx: AuthContext, now: datetime) -> StateRead:
    assert ctx.tenant_id is not None
    rows = leak_finding_repo.list_for_tenant(ctx.tenant_id)
    if not rows:
        return StateRead(
            EntryStatus.UNAVAILABLE,
            gaps=(Gap("NO_FINDINGS_RECORDED", "No leak findings are recorded — reconciliation may not have been run, so this is not a clean bill of health."),),
        )
    open_rows = [r for r in rows if r["status"] in _OPEN_LEAK_STATUSES]
    if not open_rows:
        return StateRead(
            EntryStatus.AVAILABLE, as_of=max(r["first_observed_at"] for r in rows),
            facts=(Fact("Leak findings", "Every recorded leak finding has been actioned or dismissed.", "SOURCE_DERIVED"),),
        )
    # Ordering of stored columns only (severity class, then the stored amount), both descending via reverse=True — no arithmetic.
    open_rows.sort(key=lambda r: (_SEVERITY_WEIGHT.get(str(r["severity"]), 0), r["amount_paise"]), reverse=True)
    shown, truncated = open_rows[:MAX_ITEMS_PER_ENTRY], len(open_rows) > MAX_ITEMS_PER_ENTRY
    figures = tuple(
        Figure(
            label=f"{r['leak_category']} — {r['marketplace']}" + (f" (SKU {r['sku']})" if r.get("sku") else "") + f" [{r['severity']}]",
            formatted_value=format_paise(r["amount_paise"]),
            register=register_for(is_available=True, confidence=r.get("confidence")),
            ref=Ref(RefKind.AGENT_REPORT_FIELD, UUID(str(r["id"])), source="leak_finding", as_of=r["first_observed_at"]),
            as_of=r["first_observed_at"],
        )
        for r in shown
    )
    gaps = (Gap("TRUNCATED", "More open leak findings exist than are listed here."),) if truncated else ()
    return StateRead(
        EntryStatus.PARTIAL if truncated else EntryStatus.AVAILABLE,
        as_of=max(r["first_observed_at"] for r in open_rows), figures=figures, gaps=gaps,
    )


def _load_data_gaps(ctx: AuthContext, now: datetime) -> StateRead:
    assert ctx.tenant_id is not None
    rows = agent_data_request_repo.list_for_tenant(ctx.tenant_id)
    open_rows = [r for r in rows if r["status"] == "OPEN"]
    if not open_rows:
        return StateRead(
            EntryStatus.AVAILABLE, as_of=max((r["created_at"] for r in rows), default=None),
            facts=(Fact("Data requests", "No inputs are currently being requested.", "SOURCE_DERIVED"),),
        )
    gaps = tuple(
        Gap(
            "DATA_REQUEST",
            f"{r['requested_field']}: {r['reason']}" + (f" (blocks {r['blocking_metric']})" if r.get("blocking_metric") else ""),
            UUID(str(r["id"])),
        )
        for r in open_rows[:MAX_ITEMS_PER_ENTRY]
    )
    if len(open_rows) > MAX_ITEMS_PER_ENTRY:
        gaps += (Gap("TRUNCATED", "More open data requests exist than are listed here."),)
    return StateRead(EntryStatus.AVAILABLE, as_of=max(r["created_at"] for r in open_rows), gaps=gaps)


def _load_seller_context(ctx: AuthContext, now: datetime) -> StateRead:
    """K2 facts (spec §6.16). The seller's goal is CFO context: shown only to a member who holds `agent.cfo`, and said so otherwise."""
    assert ctx.tenant_id is not None and ctx.role is not None
    if not has_permission(role=ctx.role, permissions=ctx.permissions, key=AGENT_CFO):
        return StateRead(
            EntryStatus.PARTIAL,
            gaps=(Gap("GOAL_NOT_PERMITTED", "The seller goal is CFO context and needs the CFO permission to be shown."),),
        )
    rows = manual_adjustment_repo.active_adjustments_for_target(
        ctx.tenant_id, target_type="ACCOUNT", target_ref=str(ctx.tenant_id), field="seller.goal"
    )
    if not rows:
        return StateRead(EntryStatus.UNAVAILABLE, gaps=(Gap("NO_GOAL", "No seller goal has been recorded."),))
    row = rows[0]
    value = row["value"] or {}
    goal_conflicts = conflict_rules.manual_input_conflicts(
        rows,
        comparable=lambda r: str((r["value"] or {}).get("target_margin_pct")) if (r["value"] or {}).get("target_margin_pct") is not None else None,
        figure_for=lambda r: Figure(
            label="Target margin (your goal)", formatted_value=f"{r['value']['target_margin_pct']}%", register=Register.MANUAL,
            ref=Ref(RefKind.SELLER_PROVIDED, UUID(str(r["id"])), as_of=r["created_at"]), as_of=r["created_at"],
        ),
        what="Your saved target margin",
    )
    figures: tuple[Figure, ...] = ()
    if value.get("target_margin_pct") is not None and not goal_conflicts:  # two different goals: neither is shown as "the" goal, the conflict block shows both
        figures = (
            Figure(
                label="Target margin (your goal)",
                formatted_value=f"{value['target_margin_pct']}%",
                register=Register.MANUAL,
                ref=Ref(RefKind.SELLER_PROVIDED, UUID(str(row["id"])), as_of=row["created_at"]),
                as_of=row["created_at"],
            ),
        )
    facts = tuple(
        Fact(label, str(value[k]), "SELLER_PROVIDED", row["created_at"])
        for k, label in (("priority_category", "Priority category"), ("note", "Seller note"))
        if value.get(k)
    )
    return StateRead(EntryStatus.AVAILABLE, as_of=row["created_at"], figures=figures, facts=facts, conflicts=tuple(goal_conflicts))


def _load_ingest_status(ctx: AuthContext, now: datetime) -> StateRead:
    assert ctx.tenant_id is not None
    imports = cfo_imports.list_imports(ctx.tenant_id, limit=_INGEST_FACT_LIMIT)
    if not imports:
        return StateRead(EntryStatus.UNAVAILABLE, gaps=(Gap("NO_REPORTS", "No marketplace reports have been uploaded yet."),))
    facts: list[Fact] = []
    newest: datetime | None = None
    for item in imports:
        uploaded = item.get("uploadedAt")
        stamp = datetime.fromisoformat(str(uploaded)) if uploaded else None
        if stamp is not None and (newest is None or stamp > newest):
            newest = stamp
        facts.append(
            Fact(
                f"{item['marketplace']} {item['reportCategory']} report",
                f"'{item['filename']}' — ingestion status: {item['status'] or 'not yet processed'}",
                "SOURCE_DERIVED",
                stamp,
            )
        )
    return StateRead(EntryStatus.AVAILABLE, as_of=newest, facts=tuple(facts))


def _load_health_bands(ctx: AuthContext, now: datetime) -> StateRead:
    """CFO's GOOD/WATCH/AT_RISK bands over the latest persisted P&L period — a persisted-derived read (derived_reads). No composite
    score and no projection exist or are created (CP1-U1)."""
    assert ctx.tenant_id is not None
    period, _rows, _found = _latest_pnl_rows(ctx.tenant_id)
    if period is None or "/" not in period:
        return StateRead(
            EntryStatus.UNAVAILABLE, gaps=(Gap("NO_PNL", "No profit & loss has been computed yet, so there is nothing to classify."),)
        )
    start_text, end_text = period.split("/", 1)
    try:
        start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
    except ValueError:
        return StateRead(EntryStatus.UNAVAILABLE, gaps=(Gap("BAD_PERIOD", "The latest P&L period label could not be read."),))
    outcome = derived_reads.financial_health_for_period(ctx.tenant_id, period_start=start, period_end=end, as_of_date=now.date())
    if outcome.overall_band is None:
        return StateRead(
            EntryStatus.UNAVAILABLE, period=period,
            gaps=(Gap("NO_BANDS", f"Health bands could not be classified: {outcome.unavailable_reason or 'insufficient persisted metrics'}."),),
        )
    figures = tuple(
        Figure(
            label=f"{_BAND_METRICS.get(metric, metric)} band",
            formatted_value=getattr(band, "value", str(band)),
            register=Register.DERIVED,
            ref=Ref(RefKind.ENGINE_RESULT, outcome.per_metric_refs[metric]),
        )
        for metric, band in outcome.per_metric_bands.items()
        if metric in outcome.per_metric_refs
    )
    overall = getattr(outcome.overall_band, "value", str(outcome.overall_band))
    return StateRead(
        EntryStatus.AVAILABLE if len(figures) == len(_BAND_METRICS) else EntryStatus.PARTIAL, period=period, figures=figures,
        facts=(Fact("Overall health band", f"{overall} (classified by the engine from the metrics listed)", "SOURCE_DERIVED"),),
        gaps=tuple(Gap(f"NO_{m}", f"{lbl} could not be classified for {period}.") for m, lbl in _BAND_METRICS.items() if m not in outcome.per_metric_bands),
    )


def _load_competitor_snapshot(ctx: AuthContext, now: datetime) -> StateRead:
    """CI's latest captured price per tracked competitor, through CI's own handoff builder (a DB read: no capture, no fetch). CI never claims
    VERIFIED, so every price is DERIVED (competitor-intelligence-agent.md 5.1); the ref is the snapshot row, re-resolved by the provenance gate."""
    assert ctx.tenant_id is not None
    urls = ceo_reads.list_active_competitors(ctx.tenant_id, limit=MAX_ITEMS_PER_ENTRY + 1)
    if not urls:
        return StateRead(EntryStatus.UNAVAILABLE, gaps=(Gap("NO_COMPETITORS", "No competitors are being tracked yet."),))
    figures: list[Figure] = []
    gaps: list[Gap] = []
    as_of: datetime | None = None
    for u in urls[:MAX_ITEMS_PER_ENTRY]:
        name = str(u.get("label") or f"{u['marketplace']} competitor")
        snap = ceo_reads.competitor_handoff(ctx.tenant_id, UUID(str(u["id"])), now=now)
        if isinstance(snap, ceo_reads.CiUnavailable):
            gaps.append(Gap(f"NO_SNAPSHOT_{str(u['id'])[:8]}", f"{name}: no research has been submitted yet."))
            continue
        if snap.listed_price_paise is None or snap.capture_status not in ("COMPLETE", "PARTIAL"):
            gaps.append(Gap(f"NO_PRICE_{str(u['id'])[:8]}", f"{name}: no usable price has been captured yet."))
            continue
        figures.append(Figure(
            label=f"{name}: listed price ({snap.marketplace})", formatted_value=format_paise(snap.listed_price_paise), register=Register.DERIVED,
            ref=Ref(RefKind.AGENT_REPORT_FIELD, snap.snapshot_id, source="competitor_snapshot", as_of=snap.captured_at), as_of=snap.captured_at,
            note="This capture is out of date." if snap.is_stale else None,
        ))
        as_of = snap.captured_at if as_of is None or snap.captured_at > as_of else as_of
    if len(urls) > MAX_ITEMS_PER_ENTRY:
        gaps.append(Gap("TRUNCATED", "More competitors are tracked than are listed here."))
    if not figures:
        return StateRead(EntryStatus.UNAVAILABLE, gaps=tuple(gaps))
    return StateRead(EntryStatus.PARTIAL if gaps else EntryStatus.AVAILABLE, as_of=as_of, figures=tuple(figures), gaps=tuple(gaps))


def _load_pi_report_latest(ctx: AuthContext, now: datetime) -> StateRead:
    """The state of PI's most recent research run: status and date only, no candidate counts or scores (a count has no engine ref)."""
    assert ctx.tenant_id is not None
    run = ceo_reads.latest_pi_run(ctx.tenant_id)
    if run is None:
        return StateRead(EntryStatus.UNAVAILABLE, gaps=(Gap("NO_RESEARCH_RUN", "No product research has been run yet."),))
    when = run.get("finished_at") or run.get("started_at")
    status = str(run["status"])
    text = {
        "COMPLETE": "finished; its report is ready", "PARTIAL": "finished with some parts missing; its report is ready",
        "FAILED": "did not complete", "RUNNING": "is still running", "QUEUED": "is queued and has not started",
    }.get(status, status.lower())
    return StateRead(
        EntryStatus.AVAILABLE if status in ("COMPLETE", "PARTIAL") else EntryStatus.PARTIAL, as_of=when,
        facts=(Fact("Latest product research", f"The latest research run {text}" + (f" ({when.date().isoformat()})." if when else "."), "SOURCE_DERIVED"),),
        gaps=(Gap("RUN_INCOMPLETE", "The latest research run has no report to show yet."),) if status not in ("COMPLETE", "PARTIAL") else (),
    )


_CMO_OUTPUT_LABEL = {
    "TITLE_SET": "title options", "TITLES": "title options", "LISTING_COPY": "listing copy", "DESCRIPTION": "description", "BULLETS": "bullet points",
    "KEYWORDS": "keywords", "BACKEND_TERMS": "backend terms", "HASHTAGS": "hashtags",
}


def _load_cmo_workflow(ctx: AuthContext, now: datetime) -> StateRead:
    """What Slim CMO last produced and how each ended: output type, SKU, marketplace, status. Never the generated copy (R9)."""
    assert ctx.tenant_id is not None
    rows = ceo_reads.recent_cmo_generations(ctx.tenant_id, limit=5)
    if not rows:
        return StateRead(EntryStatus.UNAVAILABLE, gaps=(Gap("NO_GENERATIONS", "No listing content has been generated yet."),))
    facts = tuple(
        Fact(
            "Listing content",
            f"{_CMO_OUTPUT_LABEL.get(str(r['output_type']), str(r['output_type']).lower().replace('_', ' '))} for SKU {r['sku']} on "
            f"{str(r['marketplace']).title()}: {str(r['status']).lower().replace('_', ' ')} ({r['created_at'].date().isoformat()})",
            "SOURCE_DERIVED",
        )
        for r in rows
    )
    return StateRead(EntryStatus.AVAILABLE, as_of=rows[0]["created_at"], facts=facts)


_CACHE_SOURCES: Mapping[str, tuple[str, ...]] = {
    "BS_PNL_LATEST": ("metric_result",),
    "BS_HEALTH_BANDS": ("metric_result", "financial_health_config"),
    "BS_LEAK_OPEN": ("leak_finding",),
    "BS_DATA_GAPS": ("agent_data_request",),
    "BS_SELLER_CONTEXT": ("manual_adjustment",),
    "BS_INGEST_STATUS": ("report_file", "ingestion_run"),
    "BS_PI_REPORT_LATEST": ("pi_research_run",),
    "BS_CMO_WORKFLOW": ("cmo_generation",),
    # BS_COMPETITOR_SNAPSHOT is deliberately absent: its "out of date" label depends on the clock, not only on stored rows.
}

ENTRIES: Mapping[str, StateEntrySpec] = {
    spec.key: dataclasses.replace(spec, source_tables=_CACHE_SOURCES.get(spec.key))
    for spec in (
        StateEntrySpec("BS_PNL_LATEST", AgentCode.CFO, "Latest persisted P&L period: revenue, contribution profit, marketplace fees",
                       "metric_result (Brain 1) via metric_result_repo.list_by_metric_code", _load_pnl_latest),
        StateEntrySpec("BS_LEAK_OPEN", AgentCode.CFO, "Open Leak Shield findings, most severe first",
                       "leak_finding via leak_finding_repo.list_for_tenant", _load_leak_open),
        StateEntrySpec("BS_DATA_GAPS", AgentCode.CFO, "Inputs CFO is waiting on (OP1)",
                       "agent_data_request via agent_data_request_repo.list_for_tenant", _load_data_gaps),
        StateEntrySpec("BS_HEALTH_BANDS", AgentCode.CFO, "CFO health bands over the latest P&L period (persisted-derived read)",
                       "metric_result + financial_health_config via assemble_financial_health", _load_health_bands),
        StateEntrySpec("BS_COMPETITOR_SNAPSHOT", AgentCode.CI, "Latest captured listed price per tracked competitor, with staleness",
                       "competitor_url + competitor_snapshot via competitor_intelligence.handoff.build_ci_handoff_snapshot", _load_competitor_snapshot),
        StateEntrySpec("BS_PI_REPORT_LATEST", AgentCode.PI, "State of the most recent product research run",
                       "pi_research_run via pi_research_run_repo.latest_run_for_tenant", _load_pi_report_latest),
        StateEntrySpec("BS_CMO_WORKFLOW", AgentCode.CMO, "What Slim CMO last generated and how each ended (never the copy itself)",
                       "cmo_generation via generation_repo.list_recent_for_tenant", _load_cmo_workflow),
        StateEntrySpec("BS_SELLER_CONTEXT", None, "Seller-declared context (goal, priority, note)",
                       "manual_adjustment field seller.goal", _load_seller_context),
        StateEntrySpec("BS_INGEST_STATUS", None, "What data the CEO has to reason on (latest report uploads and ingestion status)",
                       "report_file + ingestion_run via cfo_imports.list_imports", _load_ingest_status, (FILES_VIEW,)),
    )
}

# Sources that exist but have no tenant-wide read function in their owning package, so the entry is NOT in the V1 catalog yet
# (spec §6.13 hard rule 5: dropped, not worked around). Each needs a small read function in the owner, added with its specialist leg.
DEFERRED_ENTRIES: Mapping[str, str] = {
    "BS_GOAL_PROGRESS": "V1-later: needs the ceo_goal registry and Brain 1 goal_progress (deterministic-engine.md §5.16)",
    "BS_SITUATIONS": "V1-later: needs the situation table and detectors (spec §6.21)",
}


# --------------------------------------------------------------------------------------------- the read
def _entitlement_for(owner: AgentCode, tenant_id: UUID, now: datetime) -> Any:
    from backend import entitlement as ent

    if owner is AgentCode.CFO:
        return ent.resolve_cfo_entitlement(tenant_id, direct_action_code="cfo.business_state_read", occurred_at=now)
    if owner is AgentCode.PI:
        return ent.resolve_pi_entitlement(tenant_id, direct_action_code="pi.business_state_read", occurred_at=now)
    if owner is AgentCode.CMO:
        return ent.resolve_cmo_entitlement(tenant_id, direct_action_code="cmo.business_state_read", occurred_at=now)
    return ent.resolve_ci_entitlement(tenant_id)


def _load_through_cache(ctx: AuthContext, spec: StateEntrySpec, at: datetime) -> StateRead:
    """The persisted read, served from the L7 cache when it is configured and still current. Called only AFTER the permission, attachment and
    entitlement checks above, so a cache can never serve what the caller may not see. The key carries the tenant, the entry, the data fingerprint and
    the UTC date; the provenance gate still re-resolves every ref on every read."""
    assert ctx.tenant_id is not None
    cache = state_cache.get_cache()
    if cache is None or spec.source_tables is None:
        return spec.loader(ctx, at)
    key = (ctx.tenant_id, spec.key, state_cache.data_version(ctx.tenant_id, spec.source_tables), at.date())  # fingerprint BEFORE the load
    cached = cache.get(key)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    read = spec.loader(ctx, at)
    cache.put(key, read)
    return read


def read_entry(
    ctx: AuthContext,
    key: str,
    *,
    attached: frozenset[str],
    now: datetime | None = None,
    entries: Mapping[str, StateEntrySpec] | None = None,
    resolvers: Mapping[Any, Any] | None = None,
) -> BusinessStateEntry:
    """Reads ONE Business State entry for this member, applying the full gating order. Never raises for a refusal: it returns the
    status that explains it. An unknown key raises KeyError (a value outside the closed catalog is never read)."""
    catalog = entries if entries is not None else ENTRIES
    spec = catalog[key]
    at = now or datetime.now(timezone.utc)
    assert ctx.tenant_id is not None and ctx.role is not None

    owner_key = (AGENT_PERMISSION_KEY[spec.owner],) if spec.owner is not None else ()
    needed = [AGENT_CEO, *owner_key, *spec.extra_permissions]
    if any(not has_permission(role=ctx.role, permissions=ctx.permissions, key=k) for k in needed):
        return BusinessStateEntry(key, EntryStatus.NOT_PERMITTED, gaps=(Gap("NOT_PERMITTED", "You do not have access to this information."),))
    if spec.owner is not None and spec.owner.value not in attached:
        return BusinessStateEntry(
            key, EntryStatus.NOT_ATTACHED,
            gaps=(Gap("NOT_ATTACHED", f"{spec.owner.value} is not attached to this investigation — add it to use this information."),),
        )
    if spec.owner is not None:
        verdict = _entitlement_for(spec.owner, ctx.tenant_id, at)
        if not verdict.passed:
            return BusinessStateEntry(
                key, EntryStatus.NOT_ENTITLED, gaps=(Gap("NOT_ENTITLED", f"{spec.owner.value} is not available on your current plan."),),
                preview_hint="cfo.preview" if spec.owner is AgentCode.CFO else None,
            )

    read = _load_through_cache(ctx, spec, at)
    gated = provenance.gate_figures(ctx.tenant_id, read.figures, resolvers=resolvers)
    gaps = read.gaps + gated.gaps
    kept_conflicts: list[Conflict] = []
    for c in read.conflicts:  # both sides must verify for THIS tenant, or the disagreement is not shown (and is named as a gap)
        if len(provenance.gate_figures(ctx.tenant_id, (c.a, c.b)).kept) == 2:
            kept_conflicts.append(c)
        else:
            gaps = gaps + (Gap("CONFLICT_UNVERIFIED", f"{c.what} has two stored values that disagree, but one could not be verified, so it is not shown."),)
    status = read.status
    if gated.gaps and status is EntryStatus.AVAILABLE:
        status = EntryStatus.PARTIAL
    if not gated.kept and read.figures and status is EntryStatus.PARTIAL and not read.facts:
        status = EntryStatus.UNAVAILABLE  # every figure failed verification: nothing citable remains
    return BusinessStateEntry(
        key=key, status=status, as_of=read.as_of, period=read.period, figures=gated.kept, facts=read.facts, gaps=gaps, conflicts=tuple(kept_conflicts),
    )


def read_entries(
    ctx: AuthContext, keys: Iterable[str], *, attached: frozenset[str], now: datetime | None = None
) -> list[BusinessStateEntry]:
    """Sequential in B1 (parallel reads and the per-tenant cache are B4/L7)."""
    return [read_entry(ctx, k, attached=attached, now=now) for k in keys]


def catalog_keys() -> Sequence[str]:
    return tuple(ENTRIES)
