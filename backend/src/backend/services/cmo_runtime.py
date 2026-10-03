"""Slim CMO composition root (P5): wires the P3/P4 services to a model provider and the Postgres store.

Everything model-related is REQUIRED configuration with no default (`config.cmo_llm_model`,
`cmo_ollama_host`, `cmo_llm_timeout_seconds`): if any is missing or invalid `build_runtime` raises
`CmoNotConfigured` and the route answers `503 CMO_NOT_CONFIGURED` before doing any work. Tests
replace `build_runtime` (monkeypatch) with one holding a fake provider.

The P3/P4 services stay free of HTTP, entitlement and metering: this module only constructs them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from slim_cmo.imaging.normalize import ImageLimits
from slim_cmo.providers.ollama import OllamaLlmProvider
from slim_cmo.providers.ollama_vision import OllamaVisionProvider
from slim_cmo.repositories.postgres_image_store import PostgresImageStore
from slim_cmo.repositories.postgres_store import PostgresGenerationStore
from slim_cmo.service.approve import ApprovalService
from slim_cmo.service.catalog import CatalogService
from slim_cmo.service.generate import GenerationService
from slim_cmo.service.vision import ImageService
from slim_cmo.storage.local_disk import LocalDiskImageStore
from slim_cmo.types import ConstraintRowKind

from backend import config

logger = logging.getLogger(__name__)


class CmoNotConfigured(Exception):
    """Required CMO runtime configuration is missing or invalid. Carries no detail for the client."""


@dataclass(frozen=True, slots=True)
class CmoRuntime:
    store: PostgresGenerationStore
    generation: GenerationService
    approvals: ApprovalService
    catalog: CatalogService
    clock: Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_runtime(
    *,
    accepted_row_kinds: frozenset[ConstraintRowKind] = frozenset({ConstraintRowKind.VERIFIED}),
    clock: Callable[[], datetime] = utc_now,
) -> CmoRuntime:
    """`accepted_row_kinds` defaults to VERIFIED only (spec C13); only test code passes anything else."""
    try:
        model = config.cmo_llm_model()
        provider = OllamaLlmProvider(host=config.cmo_ollama_host(), timeout_seconds=config.cmo_llm_timeout_seconds())
    except (config.MissingConfig, ValueError) as exc:
        logger.error("Slim CMO runtime is not configured: %s", exc)  # server-side only: names the variable
        raise CmoNotConfigured() from None
    store = PostgresGenerationStore()
    return CmoRuntime(
        store=store,
        generation=GenerationService(store, provider, model=model, clock=clock, accepted_row_kinds=accepted_row_kinds),
        approvals=ApprovalService(store, clock=clock, accepted_row_kinds=accepted_row_kinds),
        catalog=CatalogService(store),
        clock=clock,
    )


# ---- P6: image intake and analysis ----------------------------------------------------------------------

# The trust identity of the local vision provider (with the model and schema version): an evaluation is recorded against
# these exact strings (`scripts/vision_eval.py --provider ollama`). Not a setting - there is exactly one V1 provider.
VISION_PROVIDER_NAME = "ollama"


@dataclass(frozen=True, slots=True)
class CmoImageRuntime:
    images: ImageService
    clock: Callable[[], datetime]
    rate_max: int | None  # None only for an upload-only runtime
    rate_window_seconds: int | None


def build_image_runtime(*, need_vision: bool, clock: Callable[[], datetime] = utc_now) -> CmoImageRuntime:
    """Every limit, the storage directory and (for analysis) the vision model, host, timeout and rate limit are REQUIRED
    configuration. Anything missing or invalid raises `CmoNotConfigured` -> `503`, before the upload is read or any model
    is called. `need_vision=False` builds an upload-only runtime that does not require the vision settings."""
    try:
        max_bytes, max_pixels, types = config.cmo_image_max_bytes(), config.cmo_image_max_pixels(), config.cmo_image_allowed_types()
        if max_bytes is None or max_pixels is None or not types:
            raise config.MissingConfig("CMO_IMAGE_MAX_BYTES / CMO_IMAGE_MAX_PIXELS / CMO_IMAGE_ALLOWED_TYPES")
        limits = ImageLimits(max_bytes=max_bytes, max_pixels=max_pixels, allowed_types=types)
        files = LocalDiskImageStore(config.cmo_image_storage_dir())
        provider: OllamaVisionProvider | None = None
        model: str | None = None
        rate_max = window = None
        if need_vision:
            model = config.cmo_vision_model()
            provider = OllamaVisionProvider(
                host=config.cmo_vision_ollama_host(), timeout_seconds=config.cmo_vision_timeout_seconds(), keep_alive=config.ollama_keep_alive(),
            )
            rate_max, window = config.cmo_vision_rate_max(), config.cmo_vision_rate_window_seconds()
    except (config.MissingConfig, ValueError) as exc:
        logger.error("Slim CMO image runtime is not configured: %s", exc)  # server-side only: names the variable
        raise CmoNotConfigured() from None
    service = ImageService(
        PostgresImageStore(), files, limits=limits, provider=provider, provider_name=VISION_PROVIDER_NAME if provider else None, model=model, clock=clock,
    )
    return CmoImageRuntime(images=service, clock=clock, rate_max=rate_max, rate_window_seconds=window)

