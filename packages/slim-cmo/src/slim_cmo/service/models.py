"""Plain data and the persistence port of the P3 service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID

from slim_cmo.billing import ExistingArtefact
from slim_cmo.constraints import FormatConstraint
from slim_cmo.generation.facts import FactInput
from slim_cmo.types import (
    ConstraintRowKind,
    GenerationStatus,
    GroundingBasis,
    ImageAnalysisState,
    Marketplace,
    OutputType,
    SellerFactType,
)
from slim_cmo.validators import AcceptedOption


class DuplicateArtefact(Exception):
    """The idempotency index rejected a second COMPLETE row for (request_key, type, marketplace)."""


@dataclass(frozen=True, slots=True)
class Actor:
    tenant_id: UUID  # always from the authenticated session - never from a client (AC19)
    user_id: UUID


@dataclass(frozen=True, slots=True)
class NewFact:
    fact_type: SellerFactType
    sku: str | None
    attribute_name: str | None = None
    fact_value: str | None = None
    value_paise: int | None = None  # TARGET_PRICE only: integer paise, stored, never computed on
    image_analysis_id: UUID | None = None  # set only when this fact CONFIRMS an image hint (spec §6.2.1)


@dataclass(frozen=True, slots=True)
class StoredOption:
    id: UUID
    rank: int
    title_text: str


@dataclass(frozen=True, slots=True)
class StoredTitleSet:
    generation_id: UUID
    marketplace: Marketplace
    sku: str | None
    options: tuple[StoredOption, ...]
    category_hint: str | None = None  # the hint the set was RESOLVED under (persisted in output_structured)


@dataclass(frozen=True, slots=True)
class StoredOptionDetail:
    id: UUID
    rank: int
    title_text: str
    char_count: int


@dataclass(frozen=True, slots=True)
class StoredGeneration:
    """A persisted artefact as read back (replay, settlement guard, API response). Read-only: the
    persisted `status` - never `billable_units` - is what billing is derived from."""

    id: UUID
    output_type: OutputType
    marketplace: Marketplace | None
    status: GenerationStatus
    failure_reason: str | None
    output_text: str | None
    output_structured: Mapping[str, Any] | None
    agent_run_id: UUID | None
    created_at: datetime
    options: tuple[StoredOptionDetail, ...] = ()


@dataclass(frozen=True, slots=True)
class StoredApproval:
    id: UUID
    tenant_id: UUID
    generation_id: UUID
    marketplace: Marketplace
    sku: str | None
    approved_text: str
    edited_by_seller: bool


@dataclass(frozen=True, slots=True)
class StoredAnalysis:
    id: UUID
    state: ImageAnalysisState
    attributes: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class GenerationRecord:
    """One `cmo_generation` row (+ title options). Always INDEPENDENT mode in P3 (P11 for CI)."""

    output_type: OutputType
    marketplace: Marketplace | None
    sku: str | None
    status: GenerationStatus
    request_key: str
    generated_by: UUID
    agent_run_id: UUID | None
    output_text: str | None
    output_structured: dict[str, Any] | None
    failure_reason: str | None
    format_constraint_ref: UUID | None
    image_analysis_id: UUID | None
    grounding_basis: GroundingBasis | None
    grounding_approval_id: UUID | None
    options: tuple[AcceptedOption, ...] = ()


class GenerationStore(Protocol):
    """Every method is tenant-scoped. The Postgres implementation opens one `tenant_scope`
    transaction per call; no call is made while a model is being awaited."""

    def load_config(self, tenant_id: UUID, keys: Sequence[str], as_of: date) -> Mapping[str, Any]: ...
    def load_constraints(
        self, tenant_id: UUID, marketplace: Marketplace, kinds: frozenset[ConstraintRowKind]
    ) -> Sequence[FormatConstraint]: ...
    def find_artefacts(self, tenant_id: UUID, request_key: str) -> Sequence[ExistingArtefact]: ...
    def load_facts(self, tenant_id: UUID, sku: str | None) -> Sequence[FactInput]: ...
    def save_facts(self, tenant_id: UUID, user_id: UUID, facts: Sequence[NewFact]) -> Sequence[FactInput]: ...
    def load_approval(self, tenant_id: UUID, approval_id: UUID) -> StoredApproval | None: ...
    def load_title_set(self, tenant_id: UUID, generation_id: UUID) -> StoredTitleSet | None: ...
    def load_image_analysis(self, tenant_id: UUID, analysis_id: UUID) -> StoredAnalysis | None: ...
    def load_sibling_packs(
        self, tenant_id: UUID, request_key: str, exclude: Marketplace
    ) -> Mapping[Marketplace, Mapping[str, Any]]:
        """`output_structured` of COMPLETE LISTING_COPY rows under this key for OTHER marketplaces
        (diagnostic only)."""
        ...
    def save_generation(self, tenant_id: UUID, record: GenerationRecord) -> UUID:
        """Atomic: the generation row and its title options commit together. Raises
        `DuplicateArtefact` if the idempotency index rejects a second COMPLETE row."""
        ...
    def save_approval(
        self, tenant_id: UUID, *, generation_id: UUID, option_id: UUID | None, approved_text: str,
        edited_by_seller: bool, approved_by: UUID,
    ) -> UUID: ...


class DuplicateAnalysis(Exception):
    """The partial unique index rejected a second COMPLETE analysis for (asset, provider, model, schema_version)."""


@dataclass(frozen=True, slots=True)
class StoredAsset:
    id: UUID
    storage_uri: str
    sha256: str
    content_type: str
    byte_size: int
    status: str  # ACTIVE | PURGED


@dataclass(frozen=True, slots=True)
class AnalysisRecord:
    """One `product_image_analysis` row to append. `attributes` is already stamped by `vision.trust`."""

    image_asset_id: UUID
    provider: str
    model: str
    schema_version: str
    eval_gate_ref: UUID | None
    attributes: list[dict[str, Any]]
    analysis_state: ImageAnalysisState
    degraded_reason: str | None


@dataclass(frozen=True, slots=True)
class ExistingAnalysis:
    id: UUID
    state: ImageAnalysisState
    degraded_reason: str | None

