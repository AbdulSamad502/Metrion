"""Slim CMO direct-execution routes (P5; docs/specs/slim-cmo-agent.md §8.1, auth.md §5.2).

Recommend-only (spec §0): there is NO route that publishes to or updates a marketplace - every
response is a proposal the seller copies. Each route is one registered action, declared fields only,
`extra="forbid"` bodies (a client-supplied `tenant_id`, `member_id`, `meter_code` or `cap_value` is a 422;
the tenant and user come ONLY from the authenticated context). `agent.cmo` is the route permission.

Status mapping (decided for P5):
  200  the request was accepted and executed - body has `runStatus` and per-artefact results (a FAILED
       artefact is a result, persisted with its reason, not an HTTP error)
  401/403  the existing auth chain          402  quota exhausted (nothing was executed or written)
  404  unknown or cross-tenant id (identical) 409  an identical request is in flight, or a seller title
       change is blocked by the marketplace rule (E5)
  422  malformed / invalid request           503  `CMO_NOT_CONFIGURED` (required runtime config missing)
  500  unexpected execution failure - generic body, nothing internal leaked

`confirm_image_hint` and `approve_title` are zero-unit: they never reach quota admission or metering.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from slim_cmo import billing
from slim_cmo.catalog.attributes import CatalogAttribute
from slim_cmo.service.approve import ApprovalRefused
from slim_cmo.service.catalog import CatalogRequest
from slim_cmo.service.keywords import KeywordIntelligenceService, KeywordRequest
from slim_cmo.service.title_analysis import TitleAnalysisService
from slim_cmo.service.errors import GroundingRequired, InvalidApproval, InvalidConfirmation, NotFound
from slim_cmo.imaging.normalize import ImageRejected
from slim_cmo.service.generate import GroundingRequest, Intake
from slim_cmo.service.models import Actor
from slim_cmo.service.trends import PlanChanged, RequestKeyReused, TrendConfigMissing
from slim_cmo.service.niche import (
    Decision, DecisionKind, InvalidNicheRequest, InvalidNicheTerms, NicheConfigMissing, TooManyConfirmedTerms,
)
from slim_cmo.service.vision import VisionNotConfigured
from slim_cmo.types import Marketplace, OutputType, TrendSection

from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_CMO, CATALOG_VIEW, FILES_UPLOAD, RESEARCH_MARKET_TRENDS, has_permission
from backend.services import cmo_actions, cmo_ci_inputs, cmo_images, cmo_listing, cmo_runtime, cmo_trends
from backend.services.cmo_actions import Principal, QuotaDenied, RequestInProgress
from backend.services.cmo_runtime import CmoNotConfigured
from backend.uploads import read_upload_capped

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/cmo")

# Request-size sanity bounds: implementation limits that stop absurd payloads, NOT marketplace or business rules.
_TEXT = 500
_NAME = 200

NonNegInt = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]  # le: the database column is BIGINT (a technical bound, not a business rule)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttributePair(_Body):
    name: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=_TEXT)


class ProductBody(_Body):
    """Spec §6.1 declared intake fields. No tenant / member / meter / cap field exists."""

    request_key: str = Field(min_length=1, max_length=128)
    sku: str | None = Field(default=None, max_length=128)
    product_name: str | None = Field(default=None, max_length=_NAME)
    brand: str | None = Field(default=None, max_length=_NAME)
    category_hint: str | None = Field(default=None, max_length=_NAME)
    attributes: list[AttributePair] = Field(default_factory=list, max_length=50)
    notes: list[Annotated[str, Field(max_length=1000)]] = Field(default_factory=list, max_length=20)
    target_price_paise: NonNegInt | None = None
    image_analysis_id: UUID | None = None
    text_only_confirmed: bool = False
    ci_insight_ids: list[UUID] = Field(default_factory=list, max_length=5)  # section 6.7: saved competitor listing insights the CEO brokered; each must be the seller's own (404 otherwise)
    _ci: Any = PrivateAttr(default=None)  # the CiInputs built from them by `_billable` (never part of the request)


class TitleSetsBody(ProductBody):
    marketplaces: list[Marketplace] = Field(min_length=1, max_length=3)


class GroundedBody(ProductBody):
    marketplace: Marketplace
    approval_id: UUID | None = None
    seller_title: str | None = Field(default=None, max_length=_TEXT)


class FullListingBody(GroundedBody):
    """CMO 3.0 M6 (spec 6.18): one approved title -> the pack, Amazon backend terms, optional hashtags (off unless asked), then the audit. Nothing here can switch the unverified-rules basis on."""

    include_hashtags: bool = False


class ListingEditBody(_Body):
    message: str = Field(min_length=1, max_length=2500)


class ListingRewriteBody(_Body):
    """CMO 3.0 M6 (spec 6.18.7, Q26): the model rewrites ONE bullet or the description of a saved version to mention a topic the seller's confirmed facts carry. Declared fields only: no tenant,
    meter, cap, rules-basis or workflow field exists. `sku`, `marketplace` and `product_name` are what the seller named; the saved version must match them."""

    request_key: str = Field(min_length=1, max_length=128)
    generation_id: UUID
    target: Literal["bullet", "description"]
    bullet_number: int | None = Field(default=None, ge=1, le=20)
    topic: str = Field(min_length=2, max_length=80)
    sku: str | None = Field(default=None, max_length=128)
    marketplace: Marketplace | None = None
    product_name: str | None = Field(default=None, max_length=_NAME)

    @model_validator(mode="after")
    def _section_shape(self) -> "ListingRewriteBody":
        if (self.target == "bullet") != (self.bullet_number is not None):
            raise ValueError("bullet_number is required for a bullet and not allowed for the description")
        return self


class HashtagsBody(ProductBody):
    marketplace: Marketplace | None = None


class CatalogBody(ProductBody):
    questions: list[CatalogAttribute] = Field(min_length=1, max_length=len(CatalogAttribute))
    marketplaces: list[Marketplace] = Field(default_factory=list, max_length=3)


class ApprovalBody(_Body):
    generation_id: UUID
    option_id: UUID | None = None
    edited_text: str | None = Field(default=None, max_length=_TEXT)


class ConfirmHintBody(_Body):
    analysis_id: UUID
    attribute_name: str = Field(min_length=1, max_length=100)
    sku: str = Field(min_length=1, max_length=128)
    confirmed_value: str | None = Field(default=None, max_length=_TEXT)


# ---- helpers --------------------------------------------------------------------------------


def _principal(ctx: AuthContext) -> Principal:
    assert ctx.tenant_id is not None  # require_auth(permission=...) guarantees an active tenant context
    return Principal(ctx.tenant_id, ctx.app_user_id)


def _actor(p: Principal) -> Actor:
    return Actor(p.tenant_id, p.user_id)


def _intake(body: ProductBody, agent_run_id: UUID | None) -> Intake:
    return Intake(
        request_key=body.request_key, sku=body.sku, product_name=body.product_name, brand=body.brand,
        category_hint=body.category_hint, attributes=tuple((a.name, a.value) for a in body.attributes),
        notes=tuple(body.notes), target_price_paise=body.target_price_paise, image_analysis_id=body.image_analysis_id,
        text_only_confirmed=body.text_only_confirmed, agent_run_id=agent_run_id, ci_inputs=body._ci,
        listing=cmo_listing.workflow_context(),  # M6: set by the server's own plan only (never a request field); None for every ordinary request
    )


_IMAGE_REJECTION_STATUS = {
    "EMPTY": 422, "TOO_LARGE": 413, "TYPE_NOT_ALLOWED": 415, "NOT_AN_IMAGE": 415, "TYPE_MISMATCH": 415, "CORRUPT": 422,
    "TOO_MANY_PIXELS": 422, "ANIMATED_NOT_SUPPORTED": 415,
}


def _guarded(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """The single place domain / admission errors become HTTP responses. Internals never reach the client."""
    try:
        return fn()
    except HTTPException:
        raise
    except billing.InvalidRequest as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code.value, "detail": exc.detail}) from None
    except GroundingRequired as exc:
        raise HTTPException(status_code=422, detail={"code": "GROUNDING_REQUIRED", "detail": str(exc)}) from None
    except InvalidApproval as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_APPROVAL", "detail": str(exc)}) from None
    except TrendConfigMissing as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "CONFIG_MISSING", "missing": list(exc.problem.missing), "invalid": [{"key": k, "reason": why} for k, why in exc.problem.invalid]},
        ) from None
    except RequestKeyReused:
        raise HTTPException(status_code=409, detail={"code": "REQUEST_KEY_REUSED", "detail": "That request key already produced a report for a different plan; use a new key."}) from None
    except PlanChanged:
        raise HTTPException(status_code=409, detail={"code": "PLAN_CHANGED", "detail": "The confirmed niche terms or the configuration changed since the preview; review the new preview."}) from None
    except NicheConfigMissing as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "CONFIG_MISSING", "missing": list(exc.problem.missing), "invalid": [{"key": k, "reason": why} for k, why in exc.problem.invalid]},
        ) from None
    except InvalidNicheTerms as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "NICHE_TERM_REFUSED", "terms": [{"term": t, "reasons": [r.value for r in why]} for t, why in exc.rejected]},
        ) from None
    except TooManyConfirmedTerms as exc:
        raise HTTPException(status_code=422, detail={"code": "TOO_MANY_CONFIRMED_TERMS", "maximum": exc.maximum}) from None
    except InvalidNicheRequest as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_NICHE_REQUEST", "detail": str(exc)}) from None
    except InvalidConfirmation as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CONFIRMATION", "detail": str(exc)}) from None
    except cmo_listing.ListingRefused as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": exc.detail, "missing": list(exc.missing)}) from None
    except NotFound:
        raise HTTPException(status_code=404, detail="Not found") from None  # unknown and cross-tenant look identical
    except QuotaDenied as exc:
        raise HTTPException(status_code=402, detail=exc.payload) from None
    except RequestInProgress:
        raise HTTPException(status_code=409, detail={"code": "REQUEST_IN_PROGRESS"}) from None
    except CmoNotConfigured:
        raise HTTPException(status_code=503, detail={"code": "CMO_NOT_CONFIGURED"}) from None
    except VisionNotConfigured:
        raise HTTPException(status_code=503, detail={"code": "CMO_NOT_CONFIGURED"}) from None
    except cmo_images.RateLimited as exc:
        raise HTTPException(
            status_code=429, detail={"code": "RATE_LIMITED"}, headers={"Retry-After": str(exc.retry_after_seconds)}
        ) from None
    except ImageRejected as exc:
        raise HTTPException(status_code=_IMAGE_REJECTION_STATUS.get(exc.code, 422), detail={"code": exc.code, "detail": exc.detail}) from None
    except Exception:  # noqa: BLE001 - generic 500; the exception is logged server-side, never returned
        logger.exception("unexpected Slim CMO failure")
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR"}) from None


def _guarded_value(fn: Callable[[], Any]) -> Any:
    """`_guarded` for a callable that returns a non-JSON value (a runtime object): same error mapping."""
    holder: list[Any] = []

    def run() -> dict[str, Any]:
        holder.append(fn())
        return {}

    _guarded(run)
    return holder[0]


def _billable(
    ctx: AuthContext, body: ProductBody, action: billing.Action, items: list[billing.RequestedArtefact],
    execute: Callable[[cmo_runtime.CmoRuntime, Principal, UUID | None], Any],
) -> dict[str, Any]:
    p = _principal(ctx)

    def go() -> dict[str, Any]:
        body._ci = cmo_ci_inputs.load_inputs(ctx, body.ci_insight_ids) if body.ci_insight_ids else None  # 404 for an id that is not the seller's; None = run independently
        rt = cmo_runtime.build_runtime()  # looked up on the module so tests can substitute a fake provider
        return cmo_actions.run_billable(
            p, rt, action=action, items=items, request_key=body.request_key,
            execute=lambda run_id: execute(rt, p, run_id),
        )

    return _guarded(go)


# ---- billable actions -----------------------------------------------------------------------


@router.post("/title-sets")
def post_title_sets(body: TitleSetsBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    items = [billing.RequestedArtefact(OutputType.TITLE_SET, mp) for mp in body.marketplaces]
    return _billable(
        ctx, body, billing.Action.GENERATE_TITLE_SETS, items,
        lambda rt, p, run: rt.generation.generate_title_sets(_actor(p), _intake(body, run), body.marketplaces),
    )


@router.post("/listing-copy")
def post_listing_copy(body: GroundedBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    items = [billing.RequestedArtefact(OutputType.LISTING_COPY, body.marketplace)]
    g = GroundingRequest(body.approval_id, body.seller_title)
    return _billable(
        ctx, body, billing.Action.GENERATE_LISTING_COPY, items,
        lambda rt, p, run: rt.generation.generate_listing_copy(_actor(p), _intake(body, run), body.marketplace, g),
    )


def _standalone(ctx: AuthContext, body: GroundedBody, output_type: OutputType, action: billing.Action) -> dict[str, Any]:
    items = [billing.RequestedArtefact(output_type, body.marketplace)]
    g = GroundingRequest(body.approval_id, body.seller_title)
    return _billable(
        ctx, body, action, items,
        lambda rt, p, run: rt.generation.generate_standalone(_actor(p), _intake(body, run), output_type, body.marketplace, g),
    )


@router.post("/description")
def post_description(body: GroundedBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    return _standalone(ctx, body, OutputType.DESCRIPTION, billing.Action.GENERATE_DESCRIPTION)


@router.post("/bullets")
def post_bullets(body: GroundedBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    return _standalone(ctx, body, OutputType.BULLETS, billing.Action.GENERATE_BULLETS)


@router.post("/keywords")
def post_keywords(body: GroundedBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    return _standalone(ctx, body, OutputType.KEYWORDS, billing.Action.GENERATE_KEYWORDS)


@router.post("/backend-terms")
def post_backend_terms(body: GroundedBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    return _standalone(ctx, body, OutputType.BACKEND_TERMS, billing.Action.GENERATE_BACKEND_TERMS)


@router.post("/full-listing")
def post_full_listing(body: FullListingBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """The complete, audited listing for ONE marketplace (CMO 3.0 M6). Each artefact is billed on the proven per-artefact path; the audit, keyword map and card are free."""
    def go() -> dict[str, Any]:
        body._ci = cmo_ci_inputs.load_inputs(ctx, body.ci_insight_ids) if body.ci_insight_ids else None  # 404 for an id that is not the seller's; None = run independently
        return cmo_listing.run_full_listing(ctx, body, make_intake=_intake)

    return _guarded(go)


@router.get("/listing/{generation_id}")
def get_listing(generation_id: UUID, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """The `LISTING` card for one saved pack (audited once per version; free)."""
    def go() -> dict[str, Any]:
        _principal(ctx)
        return cmo_listing.build_card(ctx.tenant_id, ctx.app_user_id, cmo_runtime.build_runtime(), generation_id)  # type: ignore[arg-type]

    return _guarded(go)


@router.post("/listing/{generation_id}/approve")
def post_listing_approve(generation_id: UUID, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """"Approve for use": a click bound to this exact saved version. Zero units. Not a publication."""
    def go() -> dict[str, Any]:
        _principal(ctx)
        return cmo_listing.approve_for_use(ctx.tenant_id, ctx.app_user_id, cmo_runtime.build_runtime(), generation_id)  # type: ignore[arg-type]

    return _guarded(go)


@router.post("/listing/{generation_id}/edit")
def post_listing_edit(generation_id: UUID, body: ListingEditBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """The seller's own section edit (spec 6.18.7a): free, deterministic, saved as a new version; a refused edit saves nothing."""
    def go() -> dict[str, Any]:
        _principal(ctx)
        return cmo_listing.apply_edit(ctx.tenant_id, ctx.app_user_id, cmo_runtime.build_runtime(), generation_id, body.message)  # type: ignore[arg-type]

    return _guarded(go)


@router.post("/listing-rewrite")
def post_listing_rewrite(body: ListingRewriteBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """The model rewrites one section of a saved version (CMO 3.0 M6, Q26). One unit, only when a rewrite is delivered; the result is a NEW immutable version, audited; nothing else changes."""
    def go() -> dict[str, Any]:
        _principal(ctx)
        return cmo_listing.rewrite_section(ctx, body)

    return _guarded(go)


@router.post("/hashtags")
def post_hashtags(body: HashtagsBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    items = [billing.RequestedArtefact(OutputType.HASHTAGS, body.marketplace)]
    return _billable(
        ctx, body, billing.Action.GENERATE_HASHTAGS, items,
        lambda rt, p, run: rt.generation.generate_hashtags(_actor(p), _intake(body, run), body.marketplace),
    )


@router.post("/catalog-answers")
def post_catalog_answers(body: CatalogBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    mps: list[Marketplace | None] = list(body.marketplaces) or [None]
    items = [billing.RequestedArtefact(OutputType.CATALOG_ANSWER, mp) for mp in mps]
    return _billable(
        ctx, body, billing.Action.CATALOG_ANSWER, items,
        lambda rt, p, run: rt.catalog.answer(
            _actor(p), CatalogRequest(_intake(body, run), tuple(body.questions), tuple(body.marketplaces))
        ),
    )


# ---- zero-unit actions ----------------------------------------------------------------------


class KeywordIntelBody(_Body):
    """`cmo.keyword_intelligence` (CMO 3.0 M2): which keywords fit this product, with the evidence. Declared fields only; no tenant, meter or cap."""

    request_key: str = Field(min_length=1, max_length=128)
    sku: str = Field(min_length=1, max_length=128)
    marketplace: Marketplace | None = None
    ci_insight_ids: list[UUID] = Field(default_factory=list, max_length=5)  # saved competitor listing insights the CEO brokered; each must be the seller's own (404 otherwise)


class TitleAnalysisBody(_Body):
    """`cmo.analyze_titles` (CMO 3.0 M3): compare the options of one saved title set. Declared fields only."""

    request_key: str = Field(min_length=1, max_length=128)
    generation_id: UUID
    ci_insight_ids: list[UUID] = Field(default_factory=list, max_length=5)


@router.post("/title-analysis")
def post_title_analysis(body: TitleAnalysisBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """`cmo.analyze_titles` - rule-based comparison of the saved title options against the seller's confirmed facts and the VERIFIED marketplace rule. 0 units: no model, no network, no
    entitlement check, no reservation, no metered event; one `agent_run` for a new analysis. No numeric score, ranking, conversion or sales claim exists in it."""
    p = _principal(ctx)

    def go() -> dict[str, Any]:
        rt = cmo_runtime.build_runtime()
        started, run_id = rt.clock(), uuid4()
        ci = cmo_ci_inputs.load_inputs(ctx, body.ci_insight_ids) if body.ci_insight_ids else None
        kinds = getattr(rt.generation, "accepted_row_kinds", None)
        svc = TitleAnalysisService(rt.store, clock=rt.clock, **({"accepted_row_kinds": kinds} if kinds else {}))
        res = svc.run(_actor(p), body.generation_id, body.request_key, ci)
        if not res["reused"]:
            cmo_actions.record_free_run(p, rt, "cmo.analyze_titles", run_id, started)
        return {**res, "unitsBilled": 0, "agentRunId": None if res["reused"] else str(run_id)}

    return _guarded(go)


@router.post("/keyword-intelligence")
def post_keyword_intelligence(body: KeywordIntelBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """`cmo.keyword_intelligence` - evidence-backed keyword candidates from the seller's own confirmed facts. 0 units: no model, no network, no entitlement check, no reservation, no
    metered event; one `agent_run` for a new analysis. Search volume, demand and rank are always NOT_ASSESSED."""
    p = _principal(ctx)

    def go() -> dict[str, Any]:
        rt = cmo_runtime.build_runtime()
        started, run_id = rt.clock(), uuid4()
        ci = cmo_ci_inputs.load_inputs(ctx, body.ci_insight_ids) if body.ci_insight_ids else None
        res = KeywordIntelligenceService(rt.store).run(_actor(p), KeywordRequest(body.request_key, body.sku, body.marketplace, ci))
        if not res["reused"]:
            cmo_actions.record_free_run(p, rt, "cmo.keyword_intelligence", run_id, started)
        return {**res, "unitsBilled": 0, "agentRunId": None if res["reused"] else str(run_id)}

    return _guarded(go)



@router.post("/title-approvals")
def post_title_approval(body: ApprovalBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """`cmo.approve_title` - persists the seller's own approval. 0 units: no entitlement check, no reservation,
    no metered event. CEO can never call this on a seller's behalf (the actor is the authenticated user)."""
    p = _principal(ctx)

    def go() -> dict[str, Any]:
        rt = cmo_runtime.build_runtime()
        started, run_id = rt.clock(), uuid4()
        res = rt.approvals.approve_title(_actor(p), body.generation_id, option_id=body.option_id, edited_text=body.edited_text)
        if isinstance(res, ApprovalRefused):
            status = 409 if res.code == "CONSTRAINT_BLOCKED" else 422
            raise HTTPException(status_code=status, detail={"code": res.code, "detail": res.detail, "violations": list(res.violations)})
        cmo_actions.record_free_run(p, rt, billing.Action.APPROVE_TITLE, run_id, started)
        return {
            "approvalId": str(res.approval_id), "generationId": str(res.generation_id),
            "optionId": str(res.option_id) if res.option_id else None, "approvedText": res.approved_text,
            "editedBySeller": res.edited_by_seller, "unitsBilled": 0, "agentRunId": str(run_id),
        }

    return _guarded(go)


@router.post("/image-hints/confirm")
def post_confirm_image_hint(body: ConfirmHintBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """`cmo.confirm_image_hint` - records the seller's own statement as a new SELLER_PROVIDED fact. 0 units:
    it is not an artefact and never enters admission or settlement. The analysis row is never modified."""
    p = _principal(ctx)

    def go() -> dict[str, Any]:
        rt = cmo_runtime.build_runtime()
        started, run_id = rt.clock(), uuid4()
        res = rt.catalog.confirm_image_hint(
            _actor(p), analysis_id=body.analysis_id, attribute_name=body.attribute_name, sku=body.sku,
            confirmed_value=body.confirmed_value,
        )
        if res.created:  # an identical re-confirmation is a replay: no new run
            cmo_actions.record_free_run(p, rt, billing.Action.CONFIRM_IMAGE_HINT, run_id, started)
        return {"factId": res.fact_id, "created": res.created, "unitsBilled": 0, "agentRunId": str(run_id) if res.created else None}

    return _guarded(go)


# ---- image intake and analysis (P6): explicit zero-unit actions ---------------------------------------------


class AnalyzeBody(_Body):
    asset_id: UUID


@router.post("/images")
async def post_image(file: UploadFile, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """`cmo.upload_image` - validate, re-encode (EXIF/GPS and all metadata stripped), hash and store ONE image. 0 units. Needs
    `agent.cmo` AND `files.upload` (spec §8.1). The runtime configuration is checked BEFORE the body is read; the byte limit is
    enforced by the body-size middleware and again exactly here; the original upload is never stored."""
    p = _principal(ctx)
    if ctx.role is None or not has_permission(role=ctx.role, permissions=ctx.permissions, key=FILES_UPLOAD):
        raise HTTPException(status_code=403, detail="Missing permission: files.upload")

    def configure() -> cmo_runtime.CmoImageRuntime:
        return cmo_runtime.build_image_runtime(need_vision=False)

    rt = await run_in_threadpool(_guarded_value, configure)
    max_bytes = rt.images.max_upload_bytes
    data = await read_upload_capped(file, max_bytes=max_bytes, env_var="CMO_IMAGE_MAX_BYTES")
    declared = file.content_type or ""
    return await run_in_threadpool(_guarded, lambda: cmo_images.upload_image(p, rt, data, declared))


class AnalyzeAttachmentBody(_Body):
    """The CEO -> CMO hand-off of a photo BY REFERENCE (ceo-cmo-delegation.md CD5): an attachment id of the CEO conversation and, optionally, the content hash the CEO saw. Nothing
    else - no bytes, no text. There is deliberately NO HTTP route for it: the CEO reaches it in-process (`cmo.analyze_attachment`), and the seller never calls it directly."""

    attachment_id: UUID
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def analyze_attachment_for_ceo(body: AnalyzeAttachmentBody, ctx: AuthContext, investigation_id: UUID) -> dict[str, Any]:
    """`cmo.analyze_attachment` - loads the referenced photo through the CMO's OWN tenant-scoped read and runs the existing normalise -> store -> analyse path. 0 units."""
    from backend.services import cmo_attachment

    p = _principal(ctx)
    return _guarded(lambda: cmo_attachment.analyze_attachment(p, investigation_id, body.attachment_id, body.sha256))


@router.post("/image-analyses")
def post_image_analysis(body: AnalyzeBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """`cmo.analyze_image` - run the local vision model over a stored image and persist a validated, IMMUTABLE analysis. 0 units;
    a per-tenant rate limit guards the model call. Observations are untrusted hints unless the exact provider/model/schema has
    a passing, latest evaluation. The raw model reply is never stored or returned."""
    p = _principal(ctx)

    def go() -> dict[str, Any]:
        rt = cmo_runtime.build_image_runtime(need_vision=True)
        return cmo_images.analyze_image(p, rt, body.asset_id)

    return _guarded(go)



# ---- catalog-seeded niche (P7d, spec §6.8.3): zero-unit, no model, no provider call -----------------------------------


class NicheDecisionBody(_Body):
    term_id: UUID
    decision: DecisionKind
    new_text: str | None = Field(default=None, max_length=_NAME)


class NicheConfirmBody(_Body):
    decisions: list[NicheDecisionBody] = Field(default_factory=list, max_length=100)
    new_terms: list[Annotated[str, Field(max_length=_NAME)]] = Field(default_factory=list, max_length=50)


def _term_json(t: Any) -> dict[str, Any]:
    return {
        "id": str(t.id), "term": t.term, "origin": t.origin.value, "originNote": t.origin_note, "status": t.status.value,
        **({"documentFrequency": t.document_frequency} if hasattr(t, "document_frequency") else {}),
    }


@router.post("/niche-terms/suggest")
def post_suggest_niche_terms(ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """`cmo.suggest_niche_terms` - deterministic suggestions from the member's own catalog item titles. Needs `agent.cmo`
    AND `catalog.view` (auth.md §5.2: the member must be allowed to have their catalog titles read). 0 units. Suggestions are stored
    `SUGGESTED` and are NOT sent anywhere; only terms the seller later confirms may leave Metrion (C15)."""
    p = _principal(ctx)
    if ctx.role is None or not has_permission(role=ctx.role, permissions=ctx.permissions, key=CATALOG_VIEW):
        raise HTTPException(status_code=403, detail="Missing permission: catalog.view")

    def go() -> dict[str, Any]:
        service = cmo_runtime.build_niche_service()
        started, run_id = service.clock(), uuid4()
        out = service.suggest(_actor(p))
        cmo_actions.record_free_run(p, service, billing.Action.SUGGEST_NICHE_TERMS, run_id, started)
        return {
            "status": out.status, "reason": out.reason, "titlesRead": out.titles_read,
            "suggestions": [_term_json(s) for s in out.suggestions], "confirmed": [_term_json(t) for t in out.confirmed],
            "unitsBilled": 0, "agentRunId": str(run_id),
        }

    return _guarded(go)


@router.get("/niche-terms")
def get_niche_terms(ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """The tenant's niche terms with their status. Read-only; no agent run, no units."""
    p = _principal(ctx)

    may_see_catalog_terms = ctx.role is not None and has_permission(role=ctx.role, permissions=ctx.permissions, key=CATALOG_VIEW)

    def go() -> dict[str, Any]:
        terms = cmo_runtime.build_niche_service().list_terms(_actor(p))
        if not may_see_catalog_terms:  # suggestions come from catalog titles: without catalog.view only the seller's CONFIRMED terms are shown
            terms = tuple(t for t in terms if t.status.value == "CONFIRMED")
        return {"terms": [_term_json(t) for t in terms]}

    return _guarded(go)


@router.post("/niche-terms/confirm")
def post_confirm_niche_terms(body: NicheConfirmBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """`cmo.confirm_niche_terms` - the seller confirms, rejects or edits terms and may type their own. 0 units. All or
    nothing: any refused term, unknown id, or confirmed-term cap breach changes nothing."""
    p = _principal(ctx)

    def go() -> dict[str, Any]:
        service = cmo_runtime.build_niche_service()
        started, run_id = service.clock(), uuid4()
        out = service.confirm(
            _actor(p), [Decision(d.decision, d.term_id, d.new_text) for d in body.decisions], tuple(body.new_terms),
        )
        cmo_actions.record_free_run(p, service, billing.Action.CONFIRM_NICHE_TERMS, run_id, started)
        return {
            "confirmed": [_term_json(t) for t in out.confirmed], "suggestions": [_term_json(t) for t in out.suggestions],
            "rejectedCount": out.rejected_count, "unitsBilled": 0, "agentRunId": str(run_id),
        }

    return _guarded(go)


# ---- market trends (P7f, spec §6.8): preview (zero-unit) -> execute (1 CMO unit + 1 shared unit) -----------------------------


class TrendPreviewBody(_Body):
    sections: list[TrendSection] = Field(default_factory=list, max_length=len(TrendSection))
    marketplaces: list[Marketplace] = Field(default_factory=list, max_length=3)


class TrendRunBody(TrendPreviewBody):
    request_key: str = Field(min_length=1, max_length=128)
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def _trend_principal(ctx: AuthContext) -> Principal:
    """`agent.cmo` is the route key (require_auth); the shared service's own key is checked here, server-side."""
    if ctx.role is None or not has_permission(role=ctx.role, permissions=ctx.permissions, key=RESEARCH_MARKET_TRENDS):
        raise HTTPException(status_code=403, detail="Missing permission: research.market_trends")
    return _principal(ctx)


@router.post("/market-trends/preview")
def post_market_trends_preview(body: TrendPreviewBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """The exact outbound searches (and the digest the run must be bound to) - shown to the seller BEFORE anything is sent.
    Zero units, no provider call, no model call. Needs `agent.cmo` AND `research.market_trends`."""
    p = _trend_principal(ctx)

    def go() -> dict[str, Any]:
        rt = cmo_runtime.build_trend_runtime()
        pv = rt.service.preview(_actor(p), sections=tuple(body.sections) or tuple(TrendSection), marketplaces=tuple(body.marketplaces))
        return {
            "digest": pv.digest, "queries": pv.plan.preview(), "sections": [s.value for s in pv.sections],
            "marketplaces": [m.value for m in pv.marketplaces], "unavailableSections": dict(pv.unavailable_reason),
            "unresearchedTerms": list(pv.plan.unresearched_terms), "skippedByBudget": [[s.section.value, s.reason] for s in pv.plan.skipped],
            "budget": dict(pv.plan.budget_usage), "byProvider": pv.plan.by_provider(), "config": dict(pv.config_snapshot),
            "notice": "Only these fixed searches, containing only your confirmed niche terms and marketplace names, will be sent to the search providers.",
        }

    return _guarded(go)


@router.post("/market-trends")
def post_market_trends(body: TrendRunBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """`cmo.market_trends` - one trend report: 1 CMO unit plus 1 unit on the shared `research.market_trends` meter, only if
    COMPLETE. Bound to a preview by `plan_digest` (409 if it changed). Needs `agent.cmo` AND `research.market_trends`."""
    p = _trend_principal(ctx)

    def go() -> dict[str, Any]:
        rt = cmo_runtime.build_trend_runtime()
        return cmo_trends.run_trend_report(
            p, rt.service, request_key=body.request_key, plan_digest=body.plan_digest,
            sections=tuple(body.sections) or tuple(TrendSection), marketplaces=tuple(body.marketplaces),
        )

    return _guarded(go)


@router.get("/market-trends")
def get_market_trends(ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """The tenant's recent trend reports (summary only). Read-only."""
    p = _trend_principal(ctx)

    def go() -> dict[str, Any]:
        rt = cmo_runtime.build_trend_runtime()
        rows = rt.service.recent(_actor(p), 20)
        return {"reports": [
            {"generationId": str(r.generation_id), "status": r.status.value, "failureReason": r.failure_reason, "createdAt": r.created_at.isoformat(), "summary": r.report}
            for r in rows
        ]}

    return _guarded(go)


@router.get("/market-trends/{generation_id}")
def get_market_trend(generation_id: UUID, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    """One stored report. Unknown and cross-tenant ids are an identical 404."""
    p = _trend_principal(ctx)

    def go() -> dict[str, Any]:
        rt = cmo_runtime.build_trend_runtime()
        return cmo_trends.report_json(rt.service.get(_actor(p), generation_id), reused=False, units=0, run_id=None)

    return _guarded(go)
