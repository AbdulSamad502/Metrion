"""Generation orchestration (P3). One accepted request -> per-artefact outcomes -> persisted rows.

Sequence (spec §6.4, §8.3; P3 decisions 4, 6):

1. REQUEST-LEVEL checks, before anything is persisted: request key, request shape
   (`billing.validate_request`), exactly one explicit anchor for grounded artefacts, that the
   approval / image-analysis ids exist for this tenant. Failure raises; no row is written.
2. Idempotency (`billing.plan_request`): a COMPLETE artefact under the same key is returned as is -
   no model call, no new row, no new unit.
3. The request is now ACCEPTED. Inline facts are stored (`seller_fact`), then each artefact is
   produced independently: config -> constraint resolution (C13) -> grounding -> generator (NO
   database transaction is open while the model is awaited) -> ONE write transaction.
   Every per-artefact failure persists a FAILED row (0 units) with a plain reason.
4. A race on the idempotency index is treated as reuse: one row, one unit, never two.

Billing boundary: this layer never meters. It returns `units_to_bill` (`billing.settle`) and the
generation ids; the route layer (P5) meters each delivered id with `cmo_metering_key`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from slim_cmo import billing
from slim_cmo.claims import ApprovalRef, Grounding, GroundingResult, check_grounding, shared_text_findings
from slim_cmo.config import (
    FORMAT_CONSTRAINT_MAX_AGE_DAYS,
    HASHTAG_SET_SIZE,
    INTERNAL_RETRY_BOUND,
    ConfigMissing,
    GenerationConfig,
    HashtagConfig,
    load_generation_config,
    load_hashtag_config,
)
from slim_cmo.constraints import ConstraintUnavailable, ResolvedConstraint, resolve_constraint
from slim_cmo.generation import copy as copy_gen
from slim_cmo.generation import standalone as standalone_gen
from slim_cmo.generation.facts import FactContext, FactInput, build_fact_context, image_attributes
from slim_cmo.generation.outcomes import Delivered, Failed, Failure, FailureCode, Outcome
from slim_cmo.generation.provider import LlmProvider
from slim_cmo.generation.titles import generate_title_set
from slim_cmo.service.errors import GroundingRequired, NotFound
from slim_cmo.service.models import (
    Actor,
    DuplicateArtefact,
    GenerationRecord,
    GenerationStore,
    NewFact,
    StoredAnalysis,
    StoredApproval,
)
from slim_cmo.types import (
    CONSTRAINT_BOUND_OUTPUT_TYPES,
    GROUNDED_OUTPUT_TYPES,
    ConstraintRowKind,
    GenerationStatus,
    GroundingBasis,
    ImageAnalysisState,
    Marketplace,
    OutputType,
    SellerFactType,
)

PRODUCT_NAME_ATTRIBUTE = "product_name"
_CONFIG_KEYS = (FORMAT_CONSTRAINT_MAX_AGE_DAYS, INTERNAL_RETRY_BOUND, HASHTAG_SET_SIZE)


@dataclass(frozen=True, slots=True)
class Intake:
    """The declared fields CEO hands CMO for generation (spec §6.1). `tenant_id` is deliberately
    absent: it comes from the authenticated `Actor`, never from the request (AC19)."""

    request_key: str
    sku: str | None = None
    product_name: str | None = None
    brand: str | None = None
    category_hint: str | None = None
    attributes: tuple[tuple[str, str], ...] = ()
    notes: tuple[str, ...] = ()
    target_price_paise: int | None = None  # stored for context only; never prompted, never written into copy (C7)
    image_analysis_id: UUID | None = None
    text_only_confirmed: bool = False  # E7: explicit seller confirmation to proceed without a usable analysis
    agent_run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class GroundingRequest:
    """Exactly one of the two. Never inferred (C8)."""

    approval_id: UUID | None = None
    seller_title: str | None = None


@dataclass(frozen=True, slots=True)
class ArtefactReport:
    output_type: OutputType
    marketplace: Marketplace | None
    status: GenerationStatus
    generation_id: UUID
    reused: bool
    failure: Failure | None = None
    outcome: Delivered | None = None


@dataclass(frozen=True, slots=True)
class RunReport:
    artefacts: tuple[ArtefactReport, ...]
    units_to_bill: int  # newly delivered artefacts only (reused ones were billed when first delivered)
    run_status: billing.RunStatus
    delivered_ids: tuple[UUID, ...] = field(default=())  # the ids P5 meters, one unit each


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def intake_facts(intake: Intake) -> list[NewFact]:
    """Every declared text field becomes a `seller_fact` (§6.1)."""
    sku = _clean(intake.sku)
    out: list[NewFact] = []
    if _clean(intake.product_name):
        out.append(NewFact(SellerFactType.ATTRIBUTE, sku, PRODUCT_NAME_ATTRIBUTE, _clean(intake.product_name)))
    if _clean(intake.brand):
        out.append(NewFact(SellerFactType.BRAND, sku, None, _clean(intake.brand)))
    if _clean(intake.category_hint):
        out.append(NewFact(SellerFactType.CATEGORY, sku, None, _clean(intake.category_hint)))
    for name, value in intake.attributes:
        if _clean(name) and _clean(value):
            out.append(NewFact(SellerFactType.ATTRIBUTE, sku, _clean(name), _clean(value)))
    for note in intake.notes:
        if _clean(note):
            out.append(NewFact(SellerFactType.FREE_TEXT, sku, None, _clean(note)))
    if intake.target_price_paise is not None:
        paise = intake.target_price_paise
        if type(paise) is not int or paise < 0:
            raise ValueError("target_price_paise must be a non-negative integer (paise)")
        out.append(NewFact(SellerFactType.TARGET_PRICE, sku, None, None, paise))
    return out


def _fact_key(f: FactInput) -> tuple[str, str]:
    return (f.fact_type.value, (f.attribute_name or f.fact_type.value.lower()).strip().casefold())


def _already_current(new: NewFact, stored: Sequence[FactInput]) -> bool:
    """Skip a re-insert when the latest stored row for the same key already says the same thing."""
    if new.fact_type is SellerFactType.TARGET_PRICE:
        return False  # a price is never deduplicated by value
    if new.fact_type is SellerFactType.FREE_TEXT and not (new.attribute_name or "").strip():
        # An identical note already stored for this sku is not re-inserted (notes are never superseded).
        text = " ".join((new.fact_value or "").split())
        return any(
            f.fact_type is SellerFactType.FREE_TEXT and not (f.attribute_name or "").strip()
            and " ".join((f.value or "").split()) == text
            for f in stored
        )
    key = (new.fact_type.value, (new.attribute_name or new.fact_type.value.lower()).strip().casefold())
    latest: FactInput | None = None
    for f in stored:
        if _fact_key(f) == key:
            latest = f  # `stored` is ordered oldest -> newest
    return latest is not None and (latest.value or "").strip() == (new.fact_value or "").strip()


already_current = _already_current  # shared with the catalog service


class GenerationService:
    def __init__(
        self,
        store: GenerationStore,
        provider: LlmProvider,
        *,
        model: str,
        clock: Callable[[], datetime],
        accepted_row_kinds: frozenset[ConstraintRowKind] = frozenset({ConstraintRowKind.VERIFIED}),
    ) -> None:
        """`model` comes from the composition root (decision 11). `accepted_row_kinds` defaults to
        VERIFIED only (C13); only test code passes anything else."""
        if not model.strip():
            raise ValueError("model is required (supplied by the composition root)")
        self._store = store
        self._provider = provider
        self._model = model
        self._clock = clock
        self._kinds = accepted_row_kinds

    # ---- public actions ---------------------------------------------------------------------

    def generate_title_sets(self, actor: Actor, intake: Intake, marketplaces: Sequence[Marketplace]) -> RunReport:
        return self._run(actor, intake, OutputType.TITLE_SET, list(marketplaces), None)

    def generate_listing_copy(
        self, actor: Actor, intake: Intake, marketplace: Marketplace, grounding: GroundingRequest
    ) -> RunReport:
        return self._run(actor, intake, OutputType.LISTING_COPY, [marketplace], grounding)

    def generate_standalone(
        self, actor: Actor, intake: Intake, output_type: OutputType, marketplace: Marketplace, grounding: GroundingRequest
    ) -> RunReport:
        if output_type not in {OutputType.DESCRIPTION, OutputType.BULLETS, OutputType.KEYWORDS, OutputType.BACKEND_TERMS}:
            raise ValueError(f"{output_type.value} is not a standalone listing artefact")
        return self._run(actor, intake, output_type, [marketplace], grounding)

    def generate_hashtags(self, actor: Actor, intake: Intake, marketplace: Marketplace | None = None) -> RunReport:
        return self._run(actor, intake, OutputType.HASHTAGS, [marketplace], None)

    # ---- the pipeline -----------------------------------------------------------------------

    def _run(
        self,
        actor: Actor,
        intake: Intake,
        output_type: OutputType,
        marketplaces: Sequence[Marketplace | None],
        grounding_req: GroundingRequest | None,
    ) -> RunReport:
        store, tenant = self._store, actor.tenant_id

        # 1. request-level validation: nothing is persisted if any of this raises.
        key = billing.normalise_request_key(intake.request_key)
        items = [billing.RequestedArtefact(output_type, mp) for mp in marketplaces]
        plan = billing.plan_request(items, request_key=key, existing=store.find_artefacts(tenant, key))
        reused = {r.item.identity: r.existing_id for r in plan.reused}
        sku = _clean(intake.sku)
        fact_rows = intake_facts(intake)  # validates target_price_paise

        approval: StoredApproval | None = None
        seller_title: str | None = None
        if plan.to_generate:
            if output_type in GROUNDED_OUTPUT_TYPES:
                approval, seller_title = self._resolve_grounding_request(tenant, grounding_req)
            analysis: StoredAnalysis | None = None
            if intake.image_analysis_id is not None:
                analysis = store.load_image_analysis(tenant, intake.image_analysis_id)
                if analysis is None:
                    raise NotFound("image analysis not found")
        else:
            analysis = None

        reports: dict[tuple[OutputType, Marketplace | None], ArtefactReport] = {}
        for hit in plan.reused:
            reports[hit.item.identity] = ArtefactReport(
                hit.item.output_type, hit.item.marketplace, GenerationStatus.COMPLETE, hit.existing_id, reused=True
            )

        generated: list[ArtefactReport] = []
        if plan.to_generate:
            # 2. ACCEPTED. Config, facts and the shared claim context.
            values = store.load_config(tenant, _CONFIG_KEYS, self._clock().date())
            gen_cfg = load_generation_config(values)
            hash_cfg = load_hashtag_config(values) if output_type is OutputType.HASHTAGS else None
            blocked_config: ConfigMissing | None = None
            if isinstance(gen_cfg, ConfigMissing):
                blocked_config = gen_cfg
            elif isinstance(hash_cfg, ConfigMissing):
                blocked_config = hash_cfg

            fact_inputs = self._store_and_collect_facts(actor, sku, fact_rows)
            image_attrs: tuple[Any, ...] = ()
            text_only = False
            image_blocked = False
            if analysis is not None:
                if analysis.state is ImageAnalysisState.COMPLETE:
                    image_attrs = image_attributes(analysis.attributes)
                elif intake.text_only_confirmed:
                    text_only = True  # proceed on seller facts only; image-derived detail stays absent (E7)
                else:
                    image_blocked = True
            ctx = build_fact_context(fact_inputs, image_attrs)
            provenance: dict[str, Any] = {"fact_ids": list(ctx.fact_ids), "text_only_confirmed": text_only}
            if seller_title is not None:
                provenance["grounding_title"] = seller_title

            for item in plan.to_generate:
                if blocked_config is not None:
                    failure: Failure | None = Failure(
                        FailureCode.CONFIG_MISSING, f"required configuration is not set ({blocked_config.describe()})",
                        detail={"missing": list(blocked_config.missing), "invalid": [list(p) for p in blocked_config.invalid]},
                    )
                elif image_blocked:
                    failure = Failure(
                        FailureCode.IMAGE_ANALYSIS_NEEDS_CONFIRMATION,
                        "the photo could not be analysed; confirm you want text-only generation to proceed",
                    )
                else:
                    failure = None
                generated.append(
                    self._produce(
                        actor=actor, intake=intake, key=key, sku=sku, output_type=output_type, marketplace=item.marketplace,
                        ctx=ctx, provenance=provenance, gen_cfg=gen_cfg if isinstance(gen_cfg, GenerationConfig) else None,
                        hash_cfg=hash_cfg if isinstance(hash_cfg, HashtagConfig) else None,
                        approval=approval, seller_title=seller_title, preblocked=failure,
                    )
                )
            for item, report in zip(plan.to_generate, generated, strict=True):
                reports[item.identity] = report

        ordered = tuple(reports[i.identity] for i in items)
        # An artefact served from a concurrent identical request (a reused row) was billed when it was
        # first delivered: it never counts toward this run's units.
        fresh = [(i, r) for i, r in zip(plan.to_generate, generated, strict=True) if not r.reused]
        if fresh:
            settlement = billing.settle([billing.ArtefactResult(i, r.status) for i, r in fresh])
            units, status = settlement.units_billed, settlement.run_status
        else:
            units, status = 0, billing.RunStatus.COMPLETE
        delivered = tuple(r.generation_id for r in generated if r.status is GenerationStatus.COMPLETE and not r.reused)
        return RunReport(ordered, units, status, delivered)

    # ---- helpers ----------------------------------------------------------------------------

    def _resolve_grounding_request(
        self, tenant: UUID, req: GroundingRequest | None
    ) -> tuple[StoredApproval | None, str | None]:
        if req is None or (req.approval_id is None) == (req.seller_title is None):
            raise GroundingRequired("provide exactly one of approval_id or seller_title")
        if req.approval_id is not None:
            approval = self._store.load_approval(tenant, req.approval_id)
            if approval is None:
                raise NotFound("approval not found")  # cross-tenant ids look identical (E8, AC19)
            return approval, None
        title = _clean(req.seller_title)
        if title is None:
            raise GroundingRequired("seller_title is empty")
        return None, title

    def _store_and_collect_facts(self, actor: Actor, sku: str | None, new_facts: Sequence[NewFact]) -> list[FactInput]:
        stored = list(self._store.load_facts(actor.tenant_id, sku)) if sku else []
        to_save: list[NewFact] = []
        for f in new_facts:
            if _already_current(f, stored):
                continue
            if f.fact_type is SellerFactType.FREE_TEXT and any(
                g.fact_type is SellerFactType.FREE_TEXT
                and " ".join((g.fact_value or "").split()) == " ".join((f.fact_value or "").split())
                for g in to_save
            ):
                continue  # the same note twice in ONE request
            to_save.append(f)
        saved = list(self._store.save_facts(actor.tenant_id, actor.user_id, to_save)) if to_save else []
        # With a sku the stored rows (oldest -> newest) plus the just-saved ones; without one only the
        # inline rows may be used (decision 2) - stored sku-less facts are never loaded.
        return [*stored, *saved]

    def _produce(
        self,
        *,
        actor: Actor,
        intake: Intake,
        key: str,
        sku: str | None,
        output_type: OutputType,
        marketplace: Marketplace | None,
        ctx: FactContext,
        provenance: dict[str, Any],
        gen_cfg: GenerationConfig | None,
        hash_cfg: HashtagConfig | None,
        approval: StoredApproval | None,
        seller_title: str | None,
        preblocked: Failure | None,
    ) -> ArtefactReport:
        constraint_ref: UUID | None = None
        grounding_basis: GroundingBasis | None = None
        grounding_approval: UUID | None = None
        outcome: Outcome | None = None
        failure: Failure | None = preblocked
        resolved: ResolvedConstraint | None = None
        anchor: str | None = None

        if failure is None and output_type in CONSTRAINT_BOUND_OUTPUT_TYPES:
            assert gen_cfg is not None and marketplace is not None
            rows = self._store.load_constraints(actor.tenant_id, marketplace, self._kinds)
            res = resolve_constraint(
                rows, marketplace=marketplace, category=intake.category_hint, output_type=output_type,
                now=self._clock(), max_age_days=gen_cfg.format_constraint_max_age_days, accepted_row_kinds=self._kinds,
            )
            if isinstance(res, ConstraintUnavailable):
                failure = Failure(
                    FailureCode.CONSTRAINT_BLOCKED, res.detail,
                    detail={"unavailable_reason": res.reason.value, "missing": list(res.missing)},
                )
            else:
                resolved = res
                constraint_ref = res.row.id

        if failure is None and output_type in GROUNDED_OUTPUT_TYPES:
            assert resolved is not None and marketplace is not None
            if approval is not None and approval.sku is not None and sku is not None and approval.sku != sku:
                grounded = None  # the approval belongs to a different product
                failure = Failure(
                    FailureCode.GROUNDING_INVALID, "the approved title belongs to a different product (SKU)",
                    detail={"errors": ["SKU_MISMATCH"]},
                )
            else:
                grounded = self._ground(actor, output_type, marketplace, resolved, approval, seller_title)
            if grounded is None:
                pass
            elif not grounded.ok:
                failure = Failure(
                    FailureCode.GROUNDING_INVALID, "the title this copy must be anchored to is missing or no longer valid",
                    detail={"errors": [e.value if hasattr(e, "value") else str(e) for e in grounded.errors]},
                )
            else:
                anchor = grounded.anchor_text
                basis, approval_id = grounded.persisted_columns()
                grounding_basis = GroundingBasis(basis) if basis else None
                grounding_approval = approval_id

        if failure is None:
            assert gen_cfg is not None
            outcome = self._generate(output_type, marketplace, resolved, ctx, anchor, gen_cfg, hash_cfg)
            if isinstance(outcome, Failed):
                failure, outcome = outcome.failure, None
            elif output_type is OutputType.TITLE_SET and resolved is not None:
                # Persist the category context the set was resolved under, so approval re-validation
                # uses the SAME context (never a caller-supplied hint). `resolved_category` is audit.
                outcome.structured["category_context"] = {
                    "category_hint": _clean(intake.category_hint), "resolved_category": resolved.row.category,
                }

        record = self._record(
            actor=actor, intake=intake, key=key, sku=sku, output_type=output_type, marketplace=marketplace,
            outcome=outcome if isinstance(outcome, Delivered) else None, failure=failure, provenance=provenance,
            constraint_ref=constraint_ref, grounding_basis=grounding_basis, grounding_approval=grounding_approval,
            ctx=ctx,
        )
        try:
            generation_id = self._store.save_generation(actor.tenant_id, record)
        except DuplicateArtefact:
            # A simultaneous identical request won the race: serve its row; ours is discarded. No second unit.
            existing = [
                e for e in self._store.find_artefacts(actor.tenant_id, key)
                if e.output_type is output_type and e.marketplace == marketplace and e.status is GenerationStatus.COMPLETE
            ]
            if not existing:
                raise
            return ArtefactReport(output_type, marketplace, GenerationStatus.COMPLETE, existing[0].id, reused=True)
        return ArtefactReport(
            output_type, marketplace, record.status, generation_id, reused=False,
            failure=failure, outcome=outcome if isinstance(outcome, Delivered) else None,
        )

    def _shared_text(self, actor: Actor, key: str, marketplace: Marketplace, mine: Delivered) -> list[dict[str, str]]:
        """DIAGNOSTIC only (decision 10): identical description/bullet text against packs already
        delivered under the same request key for other marketplaces. Never fails or regenerates a pack."""
        siblings = self._store.load_sibling_packs(actor.tenant_id, key, marketplace)
        if not siblings:
            return []
        view = {marketplace: (str(mine.structured["description"]), list(mine.structured["bullets"]))}
        for mp, s in siblings.items():
            view[mp] = (str(s.get("description", "")), list(s.get("bullets", [])))
        return [{"a": f.a.value, "b": f.b.value, "kind": f.kind} for f in shared_text_findings(view)]

    def _ground(
        self, actor: Actor, output_type: OutputType, marketplace: Marketplace,
        resolved: ResolvedConstraint, approval: StoredApproval | None, seller_title: str | None,
    ) -> GroundingResult:
        if approval is not None:
            grounding = Grounding(
                GroundingBasis.APPROVED_TITLE,
                approval=ApprovalRef(approval.id, approval.tenant_id, approval.marketplace, approval.approved_text),
            )
        else:
            grounding = Grounding(GroundingBasis.SELLER_SUPPLIED_TITLE, seller_title=seller_title)
        return check_grounding(output_type, tenant_id=actor.tenant_id, marketplace=marketplace, grounding=grounding, constraint=resolved.row)

    def _generate(
        self, output_type: OutputType, marketplace: Marketplace | None, resolved: ResolvedConstraint | None,
        ctx: FactContext, anchor: str | None, gen_cfg: GenerationConfig, hash_cfg: HashtagConfig | None,
    ) -> Outcome:
        common: dict[str, Any] = {"provider": self._provider, "model": self._model, "facts": ctx, "retry_bound": gen_cfg.internal_retry_bound}
        if output_type is OutputType.HASHTAGS:
            assert hash_cfg is not None
            return standalone_gen.generate_hashtags(hashtag_set_size=hash_cfg.hashtag_set_size, **common)
        assert marketplace is not None and resolved is not None
        if output_type is OutputType.TITLE_SET:
            return generate_title_set(marketplace=marketplace, resolved=resolved, **common)
        assert anchor is not None
        fn = {
            OutputType.LISTING_COPY: copy_gen.generate_listing_copy,
            OutputType.DESCRIPTION: standalone_gen.generate_description,
            OutputType.BULLETS: standalone_gen.generate_bullets,
            OutputType.KEYWORDS: standalone_gen.generate_keywords,
            OutputType.BACKEND_TERMS: standalone_gen.generate_backend_terms,
        }[output_type]
        return fn(marketplace=marketplace, resolved=resolved, anchor_title=anchor, **common)

    def _record(
        self, *, actor: Actor, intake: Intake, key: str, sku: str | None, output_type: OutputType,
        marketplace: Marketplace | None, outcome: Delivered | None, failure: Failure | None,
        provenance: dict[str, Any], constraint_ref: UUID | None, grounding_basis: GroundingBasis | None,
        grounding_approval: UUID | None, ctx: FactContext,
    ) -> GenerationRecord:
        base: dict[str, Any] = dict(
            output_type=output_type, marketplace=marketplace, sku=sku, request_key=key, generated_by=actor.user_id,
            agent_run_id=intake.agent_run_id, format_constraint_ref=constraint_ref,
            image_analysis_id=intake.image_analysis_id, grounding_basis=grounding_basis,
            grounding_approval_id=grounding_approval,
        )
        if outcome is not None:
            structured = {**outcome.structured, "provenance": provenance}
            if output_type is OutputType.LISTING_COPY and marketplace is not None:
                structured["diagnostics"] = {"shared_text": self._shared_text(actor, key, marketplace, outcome)}
            return GenerationRecord(
                status=GenerationStatus.COMPLETE, output_text=outcome.output_text, output_structured=structured,
                failure_reason=None, options=outcome.options, **base,
            )
        assert failure is not None
        return GenerationRecord(
            status=GenerationStatus.FAILED, output_text=None,
            output_structured={**failure.structured(), "provenance": provenance},
            failure_reason=failure.reason, **base,
        )

