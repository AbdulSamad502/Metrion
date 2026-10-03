"""Catalog Q&A orchestration (P4) and `cmo.confirm_image_hint` (spec §6.5, §6.2.1, §8.1.1, AC12, AC39).

`answer` - one `CATALOG_ANSWER` artefact per marketplace answered (one product-level artefact if no
marketplace is given), 1 unit each, idempotent on `(request_key, CATALOG_ANSWER, marketplace)`. It makes
NO model call: answers come from the seller's stored/inline facts and a passed-gate image analysis; an
optional `Estimator` may propose labelled ranges/plain-words paths that pass `validate_estimate`. An
answer that is mostly UNKNOWN is still a delivered answer (it tells the seller what to supply); there
is no failure path after the request is accepted.

`confirm_image_hint` - records the seller's OWN statement as a NEW `SELLER_PROVIDED` `seller_fact`
(via `claims.seller_confirmation`), linked to the analysis. Zero units, no model. It never modifies the
analysis row and never makes the hint, the vision provider or any other image attribute trusted: the
stored hint stays `UNVERIFIED_HINT`.

Billing boundary as in P3: this layer never meters; it returns the delivered ids for P5.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from slim_cmo import billing
from slim_cmo.catalog.attributes import CatalogAttribute, normalise_name
from slim_cmo.catalog.estimates import Estimator, RejectedEstimate, ValidEstimate, validate_estimate
from slim_cmo.catalog.resolve import AnswerSet, known_facts, resolve_answers, unresolved_estimable
from slim_cmo.claims import Attribute, seller_confirmation
from slim_cmo.generation.facts import FactInput, build_fact_context, image_attributes
from slim_cmo.service.errors import InvalidConfirmation, NotFound
from slim_cmo.service.generate import ArtefactReport, Intake, RunReport, already_current, intake_facts
from slim_cmo.service.models import Actor, DuplicateArtefact, GenerationRecord, GenerationStore, NewFact, StoredAnalysis
from slim_cmo.textnorm import collapse_whitespace
from slim_cmo.types import (
    AttributeBasis,
    GenerationStatus,
    ImageAnalysisState,
    Marketplace,
    OutputType,
    SellerFactType,
)

ANSWER_DISCLAIMER = (
    "Only SELLER_PROVIDED and gate-passed IMAGE_OBSERVED answers may be stated as fact in a listing. "
    "ESTIMATED and UNKNOWN answers are not specifications."
)


@dataclass(frozen=True, slots=True)
class CatalogRequest:
    intake: Intake  # sku, inline facts, image_analysis_id, request_key (tenant comes from the Actor only)
    questions: tuple[CatalogAttribute, ...]
    marketplaces: tuple[Marketplace, ...] = ()  # empty -> ONE marketplace-independent answer


@dataclass(frozen=True, slots=True)
class ConfirmResult:
    fact_id: str | None  # None when an identical confirmation already stands (nothing was inserted)
    created: bool


class CatalogService:
    def __init__(self, store: GenerationStore, *, estimator: Estimator | None = None) -> None:
        """No estimator is wired in P4: unresolved estimable questions answer UNKNOWN."""
        self._store = store
        self._estimator = estimator

    # ---- cmo.catalog_answer -----------------------------------------------------------------

    def answer(self, actor: Actor, req: CatalogRequest) -> RunReport:
        store, tenant = self._store, actor.tenant_id
        questions = tuple(dict.fromkeys(req.questions))
        if not questions or not all(isinstance(q, CatalogAttribute) for q in questions):
            raise billing.InvalidRequest(billing.RequestError.EMPTY_REQUEST, "ask at least one catalog question")

        key = billing.normalise_request_key(req.intake.request_key)
        marketplaces: list[Marketplace | None] = list(req.marketplaces) or [None]
        items = [billing.RequestedArtefact(OutputType.CATALOG_ANSWER, mp) for mp in marketplaces]
        plan = billing.plan_request(items, request_key=key, existing=store.find_artefacts(tenant, key))
        reused = {r.item.identity: r.existing_id for r in plan.reused}
        sku = (req.intake.sku or "").strip() or None
        new_facts = intake_facts(req.intake)  # validates target_price_paise

        analysis: StoredAnalysis | None = None
        if plan.to_generate and req.intake.image_analysis_id is not None:
            analysis = store.load_image_analysis(tenant, req.intake.image_analysis_id)
            if analysis is None:
                raise NotFound("image analysis not found")  # cross-tenant ids look identical (AC19)

        reports: dict[tuple[OutputType, Marketplace | None], ArtefactReport] = {
            hit.item.identity: ArtefactReport(OutputType.CATALOG_ANSWER, hit.item.marketplace, GenerationStatus.COMPLETE, hit.existing_id, reused=True)
            for hit in plan.reused
        }
        fresh: list[ArtefactReport] = []
        if plan.to_generate:
            facts = self._collect_facts(actor, sku, new_facts)
            image_state = analysis.state.value if analysis is not None else None
            usable = analysis is not None and analysis.state is ImageAnalysisState.COMPLETE
            image_attrs: tuple[Attribute, ...] = image_attributes(analysis.attributes) if usable and analysis is not None else ()
            for item in plan.to_generate:
                fresh.append(self._deliver(actor, req, key, sku, item.marketplace, questions, facts, image_attrs, image_state))
            for item, report in zip(plan.to_generate, fresh, strict=True):
                reports[item.identity] = report

        ordered = tuple(reports[i.identity] for i in items)
        billed = [(i, r) for i, r in zip(plan.to_generate, fresh, strict=True) if not r.reused]
        units = len(billed)  # every accepted catalog answer is COMPLETE: one unit each
        status = billing.settle([billing.ArtefactResult(i, r.status) for i, r in billed]).run_status if billed else billing.RunStatus.COMPLETE
        return RunReport(ordered, units, status, tuple(r.generation_id for _i, r in billed))

    def _collect_facts(self, actor: Actor, sku: str | None, new_facts: Sequence[NewFact]) -> list[FactInput]:
        """Same rules as generation (decision 2): stored facts only by exact non-null sku; inline facts always."""
        stored = list(self._store.load_facts(actor.tenant_id, sku)) if sku else []
        to_save: list[NewFact] = []
        for f in new_facts:
            if already_current(f, stored):
                continue
            if f.fact_type is SellerFactType.FREE_TEXT and any(
                g.fact_type is SellerFactType.FREE_TEXT and " ".join((g.fact_value or "").split()) == " ".join((f.fact_value or "").split())
                for g in to_save
            ):
                continue
            to_save.append(f)
        saved = list(self._store.save_facts(actor.tenant_id, actor.user_id, to_save)) if to_save else []
        return [*stored, *saved]

    def _estimates(
        self, marketplace: Marketplace | None, questions: Sequence[CatalogAttribute], facts: Sequence[FactInput], attrs: Sequence[Attribute]
    ) -> tuple[dict[CatalogAttribute, ValidEstimate], dict[str, object]]:
        if self._estimator is None:
            return {}, {"estimator": "NOT_CONFIGURED"}
        wanted = unresolved_estimable(questions, facts, attrs)
        if not wanted:
            return {}, {"estimator": "NOT_NEEDED"}
        try:
            proposed = self._estimator.estimate(
                marketplace=marketplace, attributes=wanted, known_facts=known_facts(build_fact_context(facts, attrs)),
            )
        except Exception:  # noqa: BLE001 - an estimator outage never fails a catalog answer
            return {}, {"estimator": "UNAVAILABLE"}
        valid: dict[CatalogAttribute, ValidEstimate] = {}
        rejected: dict[str, str] = {}
        for attribute, est in proposed.items():
            if attribute not in wanted:
                rejected[getattr(attribute, "value", str(attribute))] = "NOT_REQUESTED_OR_RESOLVED"
                continue
            result = validate_estimate(attribute, est)
            if isinstance(result, RejectedEstimate):
                rejected[attribute.value] = result.reason
            else:
                valid[attribute] = result
        return valid, {"estimator": "USED", "rejected_estimates": rejected}

    def _deliver(
        self, actor: Actor, req: CatalogRequest, key: str, sku: str | None, marketplace: Marketplace | None,
        questions: Sequence[CatalogAttribute], facts: Sequence[FactInput], attrs: Sequence[Attribute], image_state: str | None,
    ) -> ArtefactReport:
        estimates, estimator_info = self._estimates(marketplace, questions, facts, attrs)
        result: AnswerSet = resolve_answers(questions, facts, attrs, estimates)
        structured = {
            "marketplace": marketplace.value if marketplace else None,
            "attributes": [a.to_json() for a in result.answers],
            "basis_counts": result.basis_counts(),
            "disclaimer": ANSWER_DISCLAIMER,
            "provenance": {
                "fact_ids": list(result.context.fact_ids),
                "excluded_facts": list(result.context.excluded),
                "image_analysis_state": image_state,
                **estimator_info,
            },
        }
        record = GenerationRecord(
            output_type=OutputType.CATALOG_ANSWER, marketplace=marketplace, sku=sku, status=GenerationStatus.COMPLETE,
            request_key=key, generated_by=actor.user_id, agent_run_id=req.intake.agent_run_id, output_text=None,
            output_structured=structured, failure_reason=None, format_constraint_ref=None,
            image_analysis_id=req.intake.image_analysis_id, grounding_basis=None, grounding_approval_id=None,
        )
        try:
            generation_id = self._store.save_generation(actor.tenant_id, record)
        except DuplicateArtefact:
            existing = [
                e for e in self._store.find_artefacts(actor.tenant_id, key)
                if e.output_type is OutputType.CATALOG_ANSWER and e.marketplace == marketplace and e.status is GenerationStatus.COMPLETE
            ]
            if not existing:
                raise
            return ArtefactReport(OutputType.CATALOG_ANSWER, marketplace, GenerationStatus.COMPLETE, existing[0].id, reused=True)
        return ArtefactReport(OutputType.CATALOG_ANSWER, marketplace, GenerationStatus.COMPLETE, generation_id, reused=False)

    # ---- cmo.confirm_image_hint -------------------------------------------------------------

    def confirm_image_hint(
        self, actor: Actor, *, analysis_id: UUID, attribute_name: str, sku: str, confirmed_value: str | None = None
    ) -> ConfirmResult:
        """Record the seller's confirmation (or correction) of a hint. 0 units, no model, and the analysis
        row is never modified: the original hint remains `UNVERIFIED_HINT` and ineligible."""
        sku = (sku or "").strip()
        if not sku:
            raise InvalidConfirmation("a sku is required so the confirmed fact attaches to the right product")
        analysis = self._store.load_image_analysis(actor.tenant_id, analysis_id)
        if analysis is None:
            raise NotFound("image analysis not found")
        wanted = normalise_name(collapse_whitespace(attribute_name or ""))
        raw = next((a for a in analysis.attributes if normalise_name(str(a.get("name", ""))) == wanted), None) if wanted else None
        if raw is None:
            raise NotFound("hint not found on this analysis")
        hint = image_attributes([raw])[0]
        try:
            fact = seller_confirmation(hint, confirmed_value)
        except ValueError as exc:
            raise InvalidConfirmation(str(exc)) from exc
        assert fact.basis == AttributeBasis.SELLER_PROVIDED
        new = NewFact(SellerFactType.ATTRIBUTE, sku, fact.name, fact.value, image_analysis_id=analysis_id)
        stored = list(self._store.load_facts(actor.tenant_id, sku))
        if already_current(new, stored):
            return ConfirmResult(None, False)
        saved = self._store.save_facts(actor.tenant_id, actor.user_id, [new])
        return ConfirmResult(saved[0].fact_id, True)
