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
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from slim_cmo import billing
from slim_cmo.catalog.attributes import CatalogAttribute
from slim_cmo.service.approve import ApprovalRefused
from slim_cmo.service.catalog import CatalogRequest
from slim_cmo.service.errors import GroundingRequired, InvalidApproval, InvalidConfirmation, NotFound
from slim_cmo.imaging.normalize import ImageRejected
from slim_cmo.service.generate import GroundingRequest, Intake
from slim_cmo.service.models import Actor
from slim_cmo.service.vision import VisionNotConfigured
from slim_cmo.types import Marketplace, OutputType

from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_CMO, FILES_UPLOAD, has_permission
from backend.services import cmo_actions, cmo_images, cmo_runtime
from backend.services.cmo_actions import Principal, QuotaDenied, RequestInProgress
from backend.services.cmo_runtime import CmoNotConfigured
from backend.uploads import read_upload_capped

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/cmo")

# Request-size sanity bounds: implementation limits that stop absurd payloads, NOT marketplace or business rules.
_TEXT = 500
_NAME = 200

NonNegInt = Annotated[int, Field(strict=True, ge=0)]


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


class TitleSetsBody(ProductBody):
    marketplaces: list[Marketplace] = Field(min_length=1, max_length=3)


class GroundedBody(ProductBody):
    marketplace: Marketplace
    approval_id: UUID | None = None
    seller_title: str | None = Field(default=None, max_length=_TEXT)


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
        text_only_confirmed=body.text_only_confirmed, agent_run_id=agent_run_id,
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
    except InvalidConfirmation as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CONFIRMATION", "detail": str(exc)}) from None
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

