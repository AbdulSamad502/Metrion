"""Model rewrite of ONE section of a saved listing (CMO 3.0 M6; docs/specs/slim-cmo-agent.md section 6.18.7, owner decision Q26: a model rewrite is 1 unit per section; the seller's own text is free).

The model may rewrite only the named bullet or the description, and only to mention a topic the seller's confirmed facts carry (the caller checks that before any plan card). The candidate must pass
EXACTLY the gates a seller's own edit passes (`revise.check_edit`: unsupported claims, topics the seller left unconfirmed, unsupported numbers, contradictions, forbidden content, competitor
originality) and must really mention the topic and really change the text. Every other section is carried over unchanged; the title is never touched. The result is a NEW immutable pack row
(`revision_of` set); the earlier version is never edited. A rewrite that cannot pass is a FAILED row and uses nothing. One unit only when a rewrite is delivered.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from slim_cmo import billing
from slim_cmo.config import ConfigMissing, INTERNAL_RETRY_BOUND, load_retry_bound
from slim_cmo.generation.engine import Evaluation, classify_failure, run_attempts
from slim_cmo.generation.facts import build_fact_context
from slim_cmo.generation.outcomes import Failure, FailureCode
from slim_cmo.generation.prompts import prompt_rewrite
from slim_cmo.generation.provider import LlmProvider
from slim_cmo.listing import audit as audit_rules
from slim_cmo.listing import limits, revise
from slim_cmo.listing.edit import EDIT, EditRequest
from slim_cmo.listing.text import words
from slim_cmo.service.generate import ArtefactReport, RunReport
from slim_cmo.service.models import Actor, DuplicateArtefact, GenerationRecord, GenerationStore
from slim_cmo.types import GenerationStatus, GroundingBasis, Marketplace, OutputType


@dataclass(frozen=True, slots=True)
class RewriteRequest:
    request_key: str
    marketplace: Marketplace
    sku: str
    source_generation_id: UUID
    target: str  # "bullet" | "description"
    bullet_number: int | None
    topic: str
    sections: revise.Sections  # the saved version being rewritten
    base: audit_rules.AuditInputs  # everything the audit needs (facts, M2 candidates, questions, competitor evidence, rules basis)
    structured: Mapping[str, Any]  # the saved pack's output_structured
    approval_id: UUID | None
    grounding_basis: str | None
    constraint_ref: UUID | None
    input_mode: str
    ci_snapshot: dict[str, Any] | None
    do_not_claim: Sequence[str] = ()
    keywords_allowed: Sequence[str] = ()


def _label(req: RewriteRequest) -> str:
    return f"bullet {req.bullet_number}" if req.target == "bullet" else "description"


class ListingRewriteService:
    def __init__(self, store: GenerationStore, provider: LlmProvider, *, model: str, clock: Callable[[], datetime]) -> None:
        self._store, self._provider, self._model, self._clock = store, provider, model, clock

    def rewrite(self, actor: Actor, req: RewriteRequest) -> RunReport:
        tenant = actor.tenant_id
        key = billing.normalise_request_key(req.request_key)
        item = billing.RequestedArtefact(OutputType.LISTING_COPY, req.marketplace)
        existing = [e for e in self._store.find_artefacts(tenant, key) if e.output_type is OutputType.LISTING_COPY and e.status is GenerationStatus.COMPLETE]
        if existing:  # a repeated request (retry, double click) is served from the first result: free, no model call
            return RunReport((ArtefactReport(OutputType.LISTING_COPY, req.marketplace, GenerationStatus.COMPLETE, existing[0].id, reused=True),), 0, billing.RunStatus.COMPLETE, ())
        retry = load_retry_bound(self._store.load_config(tenant, (INTERNAL_RETRY_BOUND,), self._clock().date()))
        if isinstance(retry, ConfigMissing):
            return self._finish(actor, req, key, item, None, Failure(FailureCode.CONFIG_MISSING, f"required configuration is not set ({retry.describe()})", detail={"missing": list(retry.missing)}))
        ctx = build_fact_context(list(self._store.load_facts(tenant, req.sku)))
        current = req.sections.bullets[(req.bullet_number or 1) - 1] if req.target == "bullet" else req.sections.description
        won: dict[str, Any] = {}

        def make_prompt(feedback: tuple[str, ...]) -> str:
            return prompt_rewrite(marketplace=req.marketplace, ctx=ctx, approved_title=req.sections.title, label=_label(req), current=current, topic=req.topic,
                                  keywords_allowed=req.keywords_allowed, do_not_claim=req.do_not_claim, feedback=feedback)

        def evaluate(parsed: Any) -> Evaluation:
            cand = " ".join(str(parsed.payload["text"]).split())
            cap = limits.EDIT_BULLET_MAX if req.target == "bullet" else limits.EDIT_DESCRIPTION_MAX
            if not cand or len(cand) > cap:
                return Evaluation(done=False, feedback=(f"{_label(req)}: TOO_LONG_OR_EMPTY",), violation_ids=("TOO_LONG_OR_EMPTY",))
            if cand == current:
                return Evaluation(done=False, feedback=(f"{_label(req)}: UNCHANGED",), violation_ids=("UNCHANGED",))
            if not set(words(req.topic)) <= set(words(cand)):
                return Evaluation(done=False, feedback=(f"{_label(req)}: TOPIC_MISSING",), violation_ids=("TOPIC_MISSING",))
            applied = revise.apply_edit(req.sections, EditRequest(EDIT, target=req.target, bullet_number=req.bullet_number, text=cand))
            if isinstance(applied, revise.Refused):
                return Evaluation(done=False, feedback=(f"{_label(req)}: {applied.code}",), violation_ids=(applied.code,))
            result, refused = revise.check_edit(applied, req.base)
            if refused is not None:
                return Evaluation(done=False, feedback=(f"{_label(req)}: {refused.code}",), violation_ids=(refused.code,))
            won.update(applied=applied, audit=result, text=cand)
            return Evaluation(done=True)

        log = run_attempts(provider=self._provider, model=self._model, retry_bound=retry, make_prompt=make_prompt, content_types={"text": str}, evaluate=evaluate,
                           already_done=lambda: bool(won))
        if not won:
            return self._finish(actor, req, key, item, None, classify_failure(log, what=f"the rewrite of {_label(req)}"))
        applied: revise.Applied = won["applied"]
        structured = revise.revision_structured(req.structured, req.sections, applied, source_id=str(req.source_generation_id), by="MODEL_REWRITE",
                                                extra={"topic": req.topic, "attempts": log.attempts})
        return self._finish(actor, req, key, item, structured, None)

    def _finish(self, actor: Actor, req: RewriteRequest, key: str, item: billing.RequestedArtefact, structured: dict[str, Any] | None, failure: Failure | None) -> RunReport:
        ok = structured is not None
        rec = GenerationRecord(
            output_type=OutputType.LISTING_COPY, marketplace=req.marketplace, sku=req.sku, status=GenerationStatus.COMPLETE if ok else GenerationStatus.FAILED, request_key=key,
            generated_by=actor.user_id, agent_run_id=None, output_text=None,
            output_structured=structured if ok else {**(failure.structured() if failure else {}), "provenance": {"rewrite_of": str(req.source_generation_id)}},
            failure_reason=None if ok else (failure.reason if failure else "the rewrite did not complete"), format_constraint_ref=req.constraint_ref, image_analysis_id=None,
            grounding_basis=GroundingBasis(req.grounding_basis) if req.grounding_basis else None, grounding_approval_id=req.approval_id, input_mode=req.input_mode, ci_inputs_snapshot=req.ci_snapshot,
        )
        try:
            gid = self._store.save_generation(actor.tenant_id, rec)
        except DuplicateArtefact:  # a simultaneous identical request won the race: serve its row; no second unit
            won = [e for e in self._store.find_artefacts(actor.tenant_id, key) if e.output_type is OutputType.LISTING_COPY and e.status is GenerationStatus.COMPLETE]
            if not won:
                raise
            return RunReport((ArtefactReport(OutputType.LISTING_COPY, req.marketplace, GenerationStatus.COMPLETE, won[0].id, reused=True),), 0, billing.RunStatus.COMPLETE, ())
        settlement = billing.settle([billing.ArtefactResult(item, rec.status)])
        report = ArtefactReport(OutputType.LISTING_COPY, req.marketplace, rec.status, gid, reused=False, failure=failure)
        return RunReport((report,), settlement.units_billed, settlement.run_status, (gid,) if ok else ())
