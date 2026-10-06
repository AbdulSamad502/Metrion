"""`cmo.market_trends` orchestration (spec §6.8, 7f): plan -> preview digest -> retrieval -> findings -> interpretation ->
evidence -> persistence. Zero billing logic here (the backend admits, meters and records the run), no HTTP.

Order of authority: configuration fails closed first (no provider call); the executed plan must equal the plan the seller was
shown (digest); retrieval is bounded and egress-guarded; the model only proposes wording and groupings that deterministic code
then validates and measures; a section with nothing supportable is `UNAVAILABLE` and is never back-filled from model knowledge.
A report is `COMPLETE` (1 CMO unit + 1 shared unit, even with degraded sections) iff at least one section has a finding with a
citable source and the evidence block names every degraded section; otherwise it is persisted `FAILED` and bills nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from slim_cmo import config as cfg
from slim_cmo.billing import ExistingArtefact
from slim_cmo.generation.engine import Evaluation, run_attempts
from slim_cmo.generation.parse import Parsed
from slim_cmo.generation.provider import LlmProvider
from slim_cmo.retrieval.service import RetrievalResult, RetrievalService, SectionResult, SectionStatus
from slim_cmo.service.errors import NotFound
from slim_cmo.service.models import Actor, DuplicateArtefact
from slim_cmo.service.niche import NicheService
from slim_cmo.trends import findings as F
from slim_cmo.trends.evidence import Thresholds
from slim_cmo.trends.interpretation import INTERPRETATION_LABEL, FindingRef, InterpretationItem, check_interpretation
from slim_cmo.trends.queries import QueryPlan, build_plan
from slim_cmo.trends.report import SectionOutcome, SectionState, Verdict, assess_report, undeclared_degraded_sections
from slim_cmo.trends.report_build import cap_items, evidence_section, plan_digest
from slim_cmo.trends.risk import RiskPatternSet
from slim_cmo.types import GenerationStatus, Marketplace, OutputType, TrendSection

logger = logging.getLogger(__name__)

NOT_REQUESTED = "Not requested."
NO_SUPPORTED_FINDING = "The retrieved sources did not support a finding that can be cited."
SUMMARY_UNAVAILABLE = "No summary for this section passed the automatic safety checks."
INTERPRETATION_UNAVAILABLE = "The interpretation step produced nothing that passed the checks."


class TrendConfigMissing(Exception):
    def __init__(self, problem: cfg.ConfigMissing) -> None:
        super().__init__(problem.describe())
        self.problem = problem


class RequestKeyReused(Exception):
    """A COMPLETE report already exists under this request key for a DIFFERENT plan (other terms, sections or marketplaces)."""


class PlanChanged(Exception):
    """The seller's confirmed terms or the configuration changed since the preview they approved."""


@dataclass(frozen=True, slots=True)
class TrendRequest:
    request_key: str
    plan_digest: str
    sections: tuple[TrendSection, ...] = tuple(TrendSection)
    marketplaces: tuple[Marketplace, ...] = ()
    agent_run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class TrendPreview:
    plan: QueryPlan
    digest: str
    sections: tuple[TrendSection, ...]
    marketplaces: tuple[Marketplace, ...]
    unavailable_reason: Mapping[str, str]
    config_snapshot: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TrendRecord:
    """The `cmo_trend_report` row (+ the `cmo_generation` row it hangs off)."""

    niche_term_ids: tuple[UUID, ...]
    sections_requested: tuple[str, ...]
    sections: dict[str, Any]
    interpretation: dict[str, Any]
    evidence: dict[str, Any]
    outbound_queries: list[dict[str, Any]]
    config_snapshot: dict[str, Any]
    market_signal_run_ref: UUID


@dataclass(frozen=True, slots=True)
class TrendRunReport:
    generation_id: UUID
    status: GenerationStatus
    reused: bool
    failure_reason: str | None
    units_to_bill: int  # 1 CMO unit AND 1 shared unit when COMPLETE and newly delivered; else 0


@dataclass(frozen=True, slots=True)
class StoredTrendReport:
    generation_id: UUID
    status: GenerationStatus
    failure_reason: str | None
    created_at: datetime
    agent_run_id: UUID | None
    report: Mapping[str, Any] | None  # sections / interpretation / evidence / outbound_queries / config_snapshot


class TrendStore(Protocol):
    def load_config(self, tenant_id: UUID, keys: Sequence[str], as_of: date) -> Mapping[str, Any]: ...
    def find_artefacts(self, tenant_id: UUID, request_key: str) -> Sequence[ExistingArtefact]: ...

    def save_report(
        self, tenant_id: UUID, user_id: UUID, *, request_key: str, status: GenerationStatus, failure_reason: str | None,
        agent_run_id: UUID | None, summary: dict[str, Any] | None, trend: TrendRecord | None,
    ) -> UUID: ...

    def load_report(self, tenant_id: UUID, generation_id: UUID) -> StoredTrendReport | None: ...
    def list_reports(self, tenant_id: UUID, limit: int) -> Sequence[StoredTrendReport]: ...


class TrendReportService:
    def __init__(
        self,
        store: TrendStore,
        niche: NicheService,
        retrieval: Callable[[cfg.TrendConfig], RetrievalService],
        llm: LlmProvider,
        *,
        model: str,
        clock: Callable[[], datetime],
        pattern_set: RiskPatternSet | None = None,
    ) -> None:
        self._store, self._niche, self._retrieval_factory, self._llm = store, niche, retrieval, llm  # the factory builds provider clients with the configured timeout
        self._model, self.clock, self._pattern_set = model, clock, pattern_set

    # ------------------------------------------------------------------ config / plan
    def _config(self, tenant_id: UUID) -> tuple[cfg.TrendConfig, int]:
        keys = (*cfg.TREND_REQUIRED_KEYS, *cfg.TREND_OPTIONAL_KEYS, cfg.INTERNAL_RETRY_BOUND)
        values = self._store.load_config(tenant_id, keys, self.clock().date())
        trend = cfg.load_trend_config(values)
        retry = cfg.load_retry_bound(values)
        missing: list[str] = []
        invalid: list[tuple[str, str]] = []
        for part in (trend, retry):
            if isinstance(part, cfg.ConfigMissing):
                missing += list(part.missing)
                invalid += list(part.invalid)
        if missing or invalid:
            raise TrendConfigMissing(cfg.ConfigMissing(tuple(missing), tuple(invalid)))
        assert isinstance(trend, cfg.TrendConfig) and isinstance(retry, int)
        return trend, retry

    def ensure_configured(self, actor: Actor) -> None:
        """Raise `TrendConfigMissing` if any required key is missing or invalid (called BEFORE admission, so nothing is reserved)."""
        self._config(actor.tenant_id)

    def preview(self, actor: Actor, *, sections: Sequence[TrendSection] = tuple(TrendSection), marketplaces: Sequence[Marketplace] = ()) -> TrendPreview:
        config, _ = self._config(actor.tenant_id)
        requested = tuple(dict.fromkeys(sections)) or tuple(TrendSection)
        terms = self._niche.confirmed_terms(actor)
        plan = build_plan(config=config, sections=requested, confirmed_terms=terms, marketplaces=marketplaces)
        unavailable = {s.value: r for s, r in plan.unavailable.items()}
        for s in TrendSection:
            if s not in requested:
                unavailable[s.value] = NOT_REQUESTED
        return TrendPreview(plan, plan_digest(plan, sections=requested), requested, tuple(marketplaces), unavailable, config.snapshot())

    def find_existing(self, actor: Actor, request_key: str) -> UUID | None:
        """The COMPLETE trend report already delivered under this key, if any (idempotent replay: no admission, no units)."""
        for a in self._store.find_artefacts(actor.tenant_id, request_key):
            if a.status is GenerationStatus.COMPLETE and a.output_type is OutputType.TREND_REPORT:  # a title set under the same key is not a report
                return a.id
        return None

    def check_replay(self, actor: Actor, generation_id: UUID, plan_digest: str) -> None:
        """An idempotent replay returns the stored report only for the SAME plan; the same key with a different plan is refused."""
        stored = self.get(actor, generation_id)
        digest = ((stored.report or {}).get("evidence") or {}).get("plan_digest")
        if digest is not None and digest != plan_digest:
            raise RequestKeyReused()

    # ------------------------------------------------------------------ generate
    def generate(self, actor: Actor, request: TrendRequest) -> TrendRunReport:
        existing = self.find_existing(actor, request.request_key)
        if existing is not None:
            self.check_replay(actor, existing, request.plan_digest)
            return TrendRunReport(existing, GenerationStatus.COMPLETE, True, None, 0)
        config, retry = self._config(actor.tenant_id)
        requested = tuple(dict.fromkeys(request.sections)) or tuple(TrendSection)
        terms = self._niche.confirmed_terms(actor)
        plan = build_plan(config=config, sections=requested, confirmed_terms=terms, marketplaces=request.marketplaces)
        if plan_digest(plan, sections=requested) != request.plan_digest:
            raise PlanChanged()

        run_ref = uuid4()
        retrieval = self._retrieval_factory(config).run(plan, config=config, confirmed_terms=terms, cache_scope=str(actor.tenant_id))  # egress-guarded; fails closed on a bad plan
        built = self._build(config, retry, requested, plan, retrieval)
        built.evidence["plan_digest"] = request.plan_digest  # binds a later replay to the plan that produced this report

        if built.verdict is Verdict.FAILED:
            gid = self._store.save_report(
                actor.tenant_id, actor.user_id, request_key=request.request_key, status=GenerationStatus.FAILED,
                failure_reason=built.failure_reason or "no section produced a citable finding", agent_run_id=request.agent_run_id,
                summary=None, trend=None,
            )
            return TrendRunReport(gid, GenerationStatus.FAILED, False, built.failure_reason, 0)

        used = {q.term for q in plan.queries if q.term}
        ids = tuple(t.id for t in self._niche.list_terms(actor) if t.term in used)
        trend = TrendRecord(
            niche_term_ids=ids, sections_requested=tuple(s.value for s in requested), sections=built.sections,
            interpretation=built.interpretation, evidence=built.evidence, outbound_queries=plan.preview(),
            config_snapshot=config.snapshot(), market_signal_run_ref=run_ref,
        )
        summary = {"findings": built.finding_counts, "degraded_sections": [d["section"] for d in built.evidence["degraded_sections"]]}
        try:
            gid = self._store.save_report(
                actor.tenant_id, actor.user_id, request_key=request.request_key, status=GenerationStatus.COMPLETE, failure_reason=None,
                agent_run_id=request.agent_run_id, summary=summary, trend=trend,
            )
        except DuplicateArtefact:  # an identical request finished first: serve ITS report; this one is a replay (no second unit)
            winner = self.find_existing(actor, request.request_key)
            if winner is None:
                raise
            return TrendRunReport(winner, GenerationStatus.COMPLETE, True, None, 0)
        return TrendRunReport(gid, GenerationStatus.COMPLETE, False, None, 1)

    def get(self, actor: Actor, generation_id: UUID) -> StoredTrendReport:
        row = self._store.load_report(actor.tenant_id, generation_id)
        if row is None:
            raise NotFound(str(generation_id))
        return row

    def recent(self, actor: Actor, limit: int) -> tuple[StoredTrendReport, ...]:
        return tuple(self._store.list_reports(actor.tenant_id, limit))

    # ------------------------------------------------------------------ the build (no I/O besides the model)
    def _build(self, config: cfg.TrendConfig, retry: int, requested: Sequence[TrendSection], plan: QueryPlan, retrieval: RetrievalResult) -> "_Built":
        thresholds = Thresholds.from_config(config)
        # 1. numbered inputs per section, capped across the report
        raw_inputs: dict[TrendSection, list[F.FindingInput]] = {}
        for sec in retrieval.sections:
            unique = list({i.url: i for i in sec.items}.values())  # one entry per URL per section
            raw_inputs[sec.section] = [F.FindingInput(0, sec.section, i.to_source_item(), i.snippet, i.view_count) for i in unique]
        kept, dropped = cap_items(raw_inputs, config.section_priority, config.max_sources_per_report)

        sections_json: dict[str, Any] = {}
        outcomes: list[SectionOutcome] = []
        all_findings: list[F.Finding] = []
        rejected_by_section: dict[str, dict[str, int]] = {}
        withheld_total = 0
        by_section_result = {s.section: s for s in retrieval.sections}

        for section in TrendSection:
            if section not in requested:
                sections_json[section.value] = _section_json(SectionState.UNAVAILABLE, NOT_REQUESTED, ())
                outcomes.append(SectionOutcome(section, SectionState.UNAVAILABLE, 0, NOT_REQUESTED))
                continue
            res = by_section_result.get(section)
            if res is None:  # planned-away (no confirmed niche / budget): carries the plan's reason
                why = plan.unavailable.get(section) or "No research was planned for this section."
                sections_json[section.value] = _section_json(SectionState.UNAVAILABLE, why, ())
                outcomes.append(SectionOutcome(section, SectionState.UNAVAILABLE, 0, why))
                continue
            items = kept.get(section, [])
            numbered = [F.FindingInput(n, section, it.source, it.snippet, it.view_count) for n, it in enumerate(items, start=1)]
            promptable, withheld = F.split_promptable(numbered)
            withheld_total += withheld
            findings: tuple[F.Finding, ...] = ()
            rejects: dict[str, int] = {}
            summary_failed = False
            if promptable:
                findings, rejects, summary_failed = self._section_findings(section, promptable, config, thresholds, retry)
            if rejects:
                rejected_by_section[section.value] = rejects
            state, reason = self._section_state(res, findings, bool(promptable), summary_failed, bool(items))
            sections_json[section.value] = _section_json(state, reason, findings)
            outcomes.append(SectionOutcome(section, state, len(findings), reason))
            all_findings += findings

        assessment = assess_report(outcomes)
        interpretation, interp_counts = self._interpret(all_findings, retry) if assessment.verdict is Verdict.COMPLETE else (_interp_json(()), {"proposed": 0, "accepted": 0, "rejected": 0})
        evidence = evidence_section(
            findings=all_findings, assessment=assessment, plan=plan, accounting=retrieval.accounting, config_snapshot=config.snapshot(),
            withheld_instruction_like=withheld_total, dropped_by_source_cap=dropped, rejected_findings=rejected_by_section,
            interpretation_counts=interp_counts, unresearched_terms=retrieval.unresearched_terms,
        )
        undeclared = undeclared_degraded_sections(assessment, [TrendSection(d["section"]) for d in evidence["degraded_sections"]])
        if undeclared:  # cannot happen by construction; refuse to deliver a report that hides a degraded section
            raise RuntimeError("evidence block omitted a degraded section")
        return _Built(assessment.verdict, assessment.failure_reason, sections_json, interpretation, evidence, {s: len([f for f in all_findings if f.section.value == s]) for s in (x.value for x in TrendSection)})

    @staticmethod
    def _section_state(res: SectionResult, findings: Sequence[F.Finding], had_promptable: bool, summary_failed: bool, had_items: bool) -> tuple[SectionState, str | None]:
        if not findings:
            if res.status is SectionStatus.UNAVAILABLE and res.reason:
                return SectionState.UNAVAILABLE, res.reason
            if summary_failed:
                return SectionState.UNAVAILABLE, SUMMARY_UNAVAILABLE
            return SectionState.UNAVAILABLE, NO_SUPPORTED_FINDING if had_items else (res.reason or "No sources were returned.")
        if res.status is not SectionStatus.COMPLETE:
            return SectionState.PARTIAL, res.reason or "Some sources were unavailable."
        return SectionState.COMPLETE, None

    def _section_findings(
        self, section: TrendSection, inputs: Sequence[F.FindingInput], config: cfg.TrendConfig, thresholds: Thresholds, retry: int
    ) -> tuple[tuple[F.Finding, ...], dict[str, int], bool]:
        by_n = {i.n: i for i in inputs}
        state: dict[str, Any] = {"accepted": (), "rejections": ()}

        def evaluate(parsed: Parsed) -> Evaluation:
            assert parsed.payload is not None
            accepted, rejections = F.validate_proposals(section, parsed.payload["findings"], by_n)
            state["accepted"], state["rejections"] = accepted, rejections
            if accepted or not rejections:  # a real answer, or a legitimate "nothing supportable"
                return Evaluation(done=True)
            return Evaluation(done=False, feedback=F.feedback_for(rejections), violation_ids=tuple(p.value for r in rejections for p in r.problems))

        log = run_attempts(
            provider=self._llm, model=self._model, retry_bound=retry, make_prompt=lambda fb: F.findings_prompt(section, inputs, fb),
            content_types={"findings": list}, evaluate=evaluate,
        )
        accepted = state["accepted"]
        rejects = dict(log.violations)
        if not accepted and (state["rejections"] or log.attempts == log.provider_errors + log.parse_failures):
            return (), rejects, True
        findings = F.assemble_findings(
            section, accepted, by_n, thresholds, official_domains=config.official_marketplace_domains, pattern_set=self._pattern_set,
            max_findings=config.max_findings_per_section,
        )
        return findings, rejects, False

    def _interpret(self, findings: Sequence[F.Finding], retry: int) -> tuple[dict[str, Any], dict[str, int]]:
        refs = {f.finding_id: FindingRef(f.finding_id, f.section, f.text, f.policy_risk) for f in findings}
        state: dict[str, Any] = {"check": None, "proposed": 0}

        def evaluate(parsed: Parsed) -> Evaluation:
            assert parsed.payload is not None
            items: list[InterpretationItem] = []
            for e in parsed.payload["items"]:
                if not isinstance(e, dict):
                    continue
                ids = e.get("derived_from_finding_ids")
                items.append(InterpretationItem(
                    e["statement"] if isinstance(e.get("statement"), str) else "",
                    tuple(i for i in ids if isinstance(i, str)) if isinstance(ids, list) else (),
                    e["action_type"] if isinstance(e.get("action_type"), str) else "",
                ))
            check = check_interpretation(items, refs)
            state["check"], state["proposed"] = check, len(items)
            if check.accepted or not check.rejected:
                return Evaluation(done=True)
            return Evaluation(done=False, feedback=tuple(f"{len(check.rejected)} interpretation item(s) failed the checks" for _ in (0,)),
                              violation_ids=tuple(p.value for r in check.rejected for p in r.problems))

        run_attempts(
            provider=self._llm, model=self._model, retry_bound=retry,
            make_prompt=lambda fb: F.interpretation_prompt([(f.finding_id, f.text) for f in findings], fb),
            content_types={"items": list}, evaluate=evaluate,
        )
        check = state["check"]
        if check is None:
            return _interp_json(()), {"proposed": 0, "accepted": 0, "rejected": 0, "note": 1}
        return _interp_json(check.accepted), {"proposed": state["proposed"], "accepted": len(check.accepted), "rejected": len(check.rejected)}


@dataclass(frozen=True, slots=True)
class _Built:
    verdict: Verdict
    failure_reason: str | None
    sections: dict[str, Any]
    interpretation: dict[str, Any]
    evidence: dict[str, Any]
    finding_counts: dict[str, int] = field(default_factory=dict)


def _section_json(state: SectionState, reason: str | None, findings: Sequence[F.Finding]) -> dict[str, Any]:
    return {"state": state.value, "reason": reason, "findings": [f.to_json() for f in findings]}


def _interp_json(items: Sequence[InterpretationItem]) -> dict[str, Any]:
    return {
        "label": INTERPRETATION_LABEL,
        "items": [{"statement": i.statement, "derived_from_finding_ids": list(i.derived_from_finding_ids), "action_type": i.action_type} for i in items],
        "note": None if items else INTERPRETATION_UNAVAILABLE,
    }
