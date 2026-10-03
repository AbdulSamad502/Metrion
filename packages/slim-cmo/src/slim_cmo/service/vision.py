"""Image upload and analysis orchestration (P6; spec §6.2, §6.2.1).

    upload -> validate -> normalise / strip EXIF -> hash -> store -> asset row        (`upload`)
    asset -> analyse (provider) -> parse -> trust-gate -> immutable analysis row      (`analyze`)

Zero units, no entitlement or metering here - exactly like `cmo.confirm_image_hint`; the HTTP layer (P5 patterns)
adds auth, the per-tenant rate limit and the `agent_run`.

* The provider sees ONLY the normalised image the store holds - never the original upload, a seller fact, a
  product name or a price - and its raw reply is parsed and DISCARDED: it is never persisted, returned or turned
  into a fact. Only the validated, stamped observations are stored.
* A provider failure, timeout or unusable reply is a persisted FAILED analysis (0 units, nothing trusted); a
  partially usable reply is DEGRADED; policy-filtered values are just discarded (see `vision.parse`).
* Trust: `vision.trust` stamps `EVAL_PASSED` only under a passing latest evaluation for the exact provider, model
  and schema version; otherwise every observation is an `UNVERIFIED_HINT`. The stored row is immutable.
* Idempotency: a COMPLETE analysis for (asset, provider, model, schema_version) is reused; a concurrent duplicate
  loses the unique-index race and is served the winner's row (a duplicate provider call is accepted in V1).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from slim_cmo.imaging.normalize import ImageLimits, normalize_image
from slim_cmo.service.errors import NotFound
from slim_cmo.service.models import (
    Actor,
    AnalysisRecord,
    DuplicateAnalysis,
    ExistingAnalysis,
    StoredAnalysis,
    StoredAsset,
)
from slim_cmo.types import ImageAnalysisState
from slim_cmo.vision.parse import AnalysisOutcome, parse_analysis
from slim_cmo.vision.provider import ImageInput, VisionProvider
from slim_cmo.vision.schema import SCHEMA_VERSION
from slim_cmo.vision.trust import EvalRunRef, decide_gate, stamp_attributes


class ImageStorePort(Protocol):
    def save_asset(
        self, tenant_id: UUID, *, uploaded_by: UUID, storage_uri: str, sha256: str, content_type: str, byte_size: int
    ) -> tuple[UUID, bool]: ...
    def load_asset(self, tenant_id: UUID, asset_id: UUID) -> StoredAsset | None: ...
    def find_complete_analysis(
        self, tenant_id: UUID, asset_id: UUID, provider: str, model: str, schema_version: str
    ) -> ExistingAnalysis | None: ...
    def save_analysis(self, tenant_id: UUID, record: AnalysisRecord) -> UUID: ...
    def latest_eval_run(self, tenant_id: UUID, provider: str, model: str, schema_version: str) -> EvalRunRef | None: ...
    def load_effective_analysis(self, tenant_id: UUID, analysis_id: UUID) -> StoredAnalysis | None: ...
    def count_recent_analyses(self, tenant_id: UUID, since: datetime) -> int: ...


class FilePort(Protocol):
    def put(self, tenant_id: UUID, sha256: str, data: bytes) -> str: ...
    def get(self, storage_uri: str) -> bytes: ...


class VisionNotConfigured(RuntimeError):
    """`analyze` was called on a service built for upload only (no provider / model supplied)."""


class StoredImageUnreadable(Exception):
    """The asset row exists but its stored file is missing, foreign or failed its integrity check: an operational
    fault, not a seller error and not a provider fault. Nothing is analysed or persisted."""


@dataclass(frozen=True, slots=True)
class UploadResult:
    asset_id: UUID
    created: bool
    sha256: str
    width: int
    height: int
    content_type: str


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    analysis_id: UUID
    state: ImageAnalysisState
    reason: str | None
    attributes: tuple[dict[str, Any], ...]  # name, value, basis, trust_state - the EFFECTIVE (read-time) trust
    reused: bool
    trust_gate_open: bool


_FAILED_UNAVAILABLE = "the vision model was unavailable, so the photo could not be analysed"
_FAILED_UNREADABLE = "the vision model's reply could not be used"


class ImageService:
    def __init__(
        self,
        store: ImageStorePort,
        files: FilePort,
        *,
        limits: ImageLimits,
        provider: VisionProvider | None,
        provider_name: str | None,
        model: str | None,
        clock: Callable[[], datetime],
    ) -> None:
        """`provider_name`, `model` and `limits` come from the composition root (required configuration).
        `provider=None` builds an UPLOAD-ONLY service: `upload` works, `analyze` raises `VisionNotConfigured`."""
        if provider is not None and (not (provider_name or "").strip() or not (model or "").strip()):
            raise ValueError("provider_name and model are required (no defaults)")
        self._store, self._files, self._limits = store, files, limits
        self._provider, self._provider_name, self._model, self._clock = provider, provider_name or "", model or "", clock

    @property
    def max_upload_bytes(self) -> int:
        return self._limits.max_bytes

    # ---- POST /cmo/images ---------------------------------------------------------------------

    def upload(self, actor: Actor, data: bytes, declared_type: str) -> UploadResult:
        image = normalize_image(data, declared_type, self._limits)  # raises ImageRejected; nothing is written
        uri = self._files.put(actor.tenant_id, image.sha256, image.data)
        asset_id, created = self._store.save_asset(
            actor.tenant_id, uploaded_by=actor.user_id, storage_uri=uri, sha256=image.sha256,
            content_type=image.content_type, byte_size=len(image.data),
        )
        return UploadResult(asset_id, created, image.sha256, image.width, image.height, image.content_type)

    # ---- POST /cmo/image-analyses -------------------------------------------------------------

    def has_reusable_analysis(self, actor: Actor, asset_id: UUID) -> bool:
        """True if a COMPLETE analysis already exists for this asset and the configured provider/model/schema, i.e.
        `analyze` would make NO model call. Lets the HTTP layer apply its rate limit only to real model calls."""
        if self._provider is None:
            raise VisionNotConfigured()
        asset = self._store.load_asset(actor.tenant_id, asset_id)
        if asset is None or asset.status != "ACTIVE":
            raise NotFound("image not found")
        return self._store.find_complete_analysis(actor.tenant_id, asset.id, self._provider_name, self._model, SCHEMA_VERSION) is not None

    def analyze(self, actor: Actor, asset_id: UUID) -> AnalysisResult:
        provider = self._provider
        if provider is None:
            raise VisionNotConfigured()
        tenant = actor.tenant_id
        asset = self._store.load_asset(tenant, asset_id)
        if asset is None or asset.status != "ACTIVE":
            raise NotFound("image not found")  # unknown, purged and cross-tenant look identical (AC19)
        existing = self._store.find_complete_analysis(tenant, asset.id, self._provider_name, self._model, SCHEMA_VERSION)
        if existing is not None:
            return self._result(tenant, existing.id, reused=True)

        if not asset.storage_uri.startswith(f"local://{tenant}/"):
            raise StoredImageUnreadable()  # a row pointing at another tenant's file is never read
        try:
            data = self._files.get(asset.storage_uri)
        except Exception:  # noqa: BLE001
            raise StoredImageUnreadable() from None

        try:
            raw = provider.describe(model=self._model, schema_version=SCHEMA_VERSION, image=ImageInput(asset.content_type, data))
        except Exception:  # noqa: BLE001 - any provider failure is a FAILED analysis, never a crash and never invented output
            return self._persist_failed(tenant, asset.id, _FAILED_UNAVAILABLE)

        parsed = parse_analysis(raw, SCHEMA_VERSION)  # `raw` is untrusted text and goes no further than this line
        if parsed.outcome is AnalysisOutcome.FAILED:
            return self._persist_failed(tenant, asset.id, _FAILED_UNREADABLE)

        decision = decide_gate(self._store.latest_eval_run(tenant, self._provider_name, self._model, SCHEMA_VERSION))
        record = AnalysisRecord(
            image_asset_id=asset.id, provider=self._provider_name, model=self._model, schema_version=SCHEMA_VERSION,
            eval_gate_ref=decision.gate_ref, attributes=stamp_attributes(parsed, decision),
            analysis_state=ImageAnalysisState(parsed.outcome.value), degraded_reason=parsed.reason,
        )
        try:
            analysis_id = self._store.save_analysis(tenant, record)
        except DuplicateAnalysis:
            winner = self._store.find_complete_analysis(tenant, asset.id, self._provider_name, self._model, SCHEMA_VERSION)
            if winner is None:
                raise
            return self._result(tenant, winner.id, reused=True)
        return self._result(tenant, analysis_id, reused=False)

    # ---- helpers ------------------------------------------------------------------------------

    def recent_analysis_count(self, actor: Actor, since: datetime) -> int:
        return self._store.count_recent_analyses(actor.tenant_id, since)

    def _persist_failed(self, tenant: UUID, asset_id: UUID, reason: str) -> AnalysisResult:
        record = AnalysisRecord(
            image_asset_id=asset_id, provider=self._provider_name, model=self._model, schema_version=SCHEMA_VERSION,
            eval_gate_ref=None, attributes=[], analysis_state=ImageAnalysisState.FAILED, degraded_reason=reason,
        )
        return self._result(tenant, self._store.save_analysis(tenant, record), reused=False)

    def _result(self, tenant: UUID, analysis_id: UUID, *, reused: bool) -> AnalysisResult:
        stored = self._store.load_effective_analysis(tenant, analysis_id)
        if stored is None:
            raise RuntimeError("persisted analysis missing")
        attrs = tuple({"name": a.get("name"), "value": a.get("value"), "basis": a.get("basis"), "trust_state": a.get("trust_state")} for a in stored.attributes)
        reason = None
        if stored.state is ImageAnalysisState.FAILED:
            reason = "the photo could not be analysed"
        elif stored.state is ImageAnalysisState.DEGRADED:
            reason = "the photo analysis was incomplete"
        trusted = any(a["trust_state"] == "EVAL_PASSED" for a in attrs)
        return AnalysisResult(analysis_id, stored.state, reason, attrs, reused, trusted)
