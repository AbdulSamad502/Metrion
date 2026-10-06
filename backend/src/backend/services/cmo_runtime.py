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
from market_signals.cache import InProcessQueryCache
from market_signals.tavily_client import HttpTavilyClient
from market_signals.youtube_client import HttpYoutubeClient
from slim_cmo.config import TrendConfig
from slim_cmo.generation.provider import LlmProvider
from slim_cmo.providers.ollama import OllamaLlmProvider
from slim_cmo.providers.ollama_vision import OllamaVisionProvider
from slim_cmo.repositories.niche_repo import PostgresNicheStore
from slim_cmo.repositories.postgres_image_store import PostgresImageStore
from slim_cmo.repositories.postgres_store import PostgresGenerationStore
from slim_cmo.repositories.trend_repo import PostgresTrendStore
from slim_cmo.repositories.usage_repo import PostgresSlotStore
from slim_cmo.retrieval.service import RetrievalService
from slim_cmo.service.approve import ApprovalService
from slim_cmo.service.catalog import CatalogService
from slim_cmo.service.generate import GenerationService
from slim_cmo.service.niche import NicheService
from slim_cmo.service.trends import TrendReportService
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


def _ollama_provider() -> LlmProvider:
    return OllamaLlmProvider(host=config.cmo_ollama_host(), timeout_seconds=config.cmo_llm_timeout_seconds(), think=config.cmo_llm_think())


# The CMO only ever sees the `LlmProvider` protocol (text in, text out). Ollama is the DEVELOPMENT backend; a hosted model is added by
# registering one more factory here and setting CMO_LLM_PROVIDER at deployment. No generation, validation or repair code changes.
_LLM_PROVIDERS: dict[str, Callable[[], LlmProvider]] = {"ollama": _ollama_provider}


def build_llm_provider() -> LlmProvider:
    name = config.cmo_llm_provider()
    factory = _LLM_PROVIDERS.get(name)
    if factory is None:
        raise ValueError(f"CMO_LLM_PROVIDER {name!r} is not registered (known: {sorted(_LLM_PROVIDERS)})")
    return factory()


def build_runtime(
    *,
    accepted_row_kinds: frozenset[ConstraintRowKind] | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> CmoRuntime:
    """`accepted_row_kinds` defaults to VERIFIED only (spec C13); only test code, or the explicit DEV flag
    `CMO_ACCEPT_TEST_FIXTURE_CONSTRAINTS=true`, widens it to include TEST_FIXTURE."""
    if accepted_row_kinds is None:
        accepted_row_kinds = frozenset({ConstraintRowKind.VERIFIED, ConstraintRowKind.TEST_FIXTURE}) if config.cmo_accept_test_fixture_constraints() else frozenset({ConstraintRowKind.VERIFIED})
    try:
        model = config.cmo_llm_model()
        provider = build_llm_provider()
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


# ---- P7d: niche flow (no model, no network: needs no CMO model configuration) ----------------------------------


def build_niche_service(*, clock: Callable[[], datetime] = utc_now) -> NicheService:
    """The catalog-seeded niche flow reads the tenant's own item titles and writes `cmo_niche_term` only. It calls no
    model and no provider, so unlike `build_runtime` it has no runtime configuration to be missing; its policy values
    (`max_confirmed_niche_terms`, `max_term_chars`, `catalog_titles_read_cap`) are checked per request and fail closed."""
    return NicheService(PostgresNicheStore(), clock=clock)


# ---- P7f: market trends ---------------------------------------------------------------------------------------

# One process-wide cache for provider results (24h by configuration). CMO-namespaced; deliberately not tenant-keyed:
# keys are built from fixed template text + confirmed niche terms only and the payloads are public search results.
_TREND_CACHE = InProcessQueryCache()


@dataclass(frozen=True, slots=True)
class CmoTrendRuntime:
    service: TrendReportService
    clock: Callable[[], datetime]


def build_trend_runtime(*, clock: Callable[[], datetime] = utc_now) -> CmoTrendRuntime:
    """Needs the CMO model configuration AND both provider keys (no defaults, none invented): missing = `CmoNotConfigured`
    (503) before any work. The provider clients are built per request, after the configured timeout is read, so the
    15 s CMO timeout never changes Product Intelligence's clients. No tactic-risk pattern set exists yet (launch blocker
    H6): every tactic is therefore `UNASSESSED` with no suggested action (the fail-safe)."""
    try:
        model = config.cmo_llm_model()
        llm = build_llm_provider()
        tavily_key, youtube_key = config.tavily_api_key(), config.youtube_api_key()
        if not tavily_key or not youtube_key:
            raise config.MissingConfig("TAVILY_API_KEY / YOUTUBE_API_KEY")
    except (config.MissingConfig, ValueError) as exc:
        logger.error("Slim CMO trend runtime is not configured: %s", exc)  # server-side only: names the variable
        raise CmoNotConfigured() from None

    def retrieval(trend_config: TrendConfig) -> RetrievalService:
        timeout = float(trend_config.provider_call_timeout_seconds)
        return RetrievalService(
            tavily=HttpTavilyClient(api_key=tavily_key, timeout_seconds=timeout),
            youtube=HttpYoutubeClient(api_key=youtube_key, timeout_seconds=timeout),
            cache=_TREND_CACHE, slots=PostgresSlotStore(), clock=clock,
        )

    niche = NicheService(PostgresNicheStore(), clock=clock)
    return CmoTrendRuntime(TrendReportService(PostgresTrendStore(), niche, retrieval, llm, model=model, clock=clock, pattern_set=None), clock)
