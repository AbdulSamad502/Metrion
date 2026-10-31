"""`GenerationStore` over Postgres. One `tenant_scope` transaction per call (BEGIN / SET LOCAL
tenant / COMMIT); a `None` tenant fails closed before any query runs. Nothing here is held open
while a model is awaited: the service calls the provider between store calls, never inside one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any
from uuid import UUID

from slim_cmo.billing import ExistingArtefact
from slim_cmo.constraints import FormatConstraint
from slim_cmo.generation.facts import FactInput
from slim_cmo.repositories import analysis_repo, approval_repo, config_repo, constraint_repo, fact_repo, generation_repo
from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.service.models import (
    GenerationRecord,
    NewFact,
    StoredAnalysis,
    StoredApproval,
    StoredGeneration,
    StoredTitleSet,
)
from slim_cmo.types import ConstraintRowKind, Marketplace


class PostgresGenerationStore:
    def load_config(self, tenant_id: UUID, keys: Sequence[str], as_of: date) -> Mapping[str, Any]:
        with tenant_scope(tenant_id) as conn:
            return config_repo.load_config_values(conn, tenant_id, keys, as_of)

    def load_constraints(
        self, tenant_id: UUID, marketplace: Marketplace, kinds: frozenset[ConstraintRowKind]
    ) -> Sequence[FormatConstraint]:
        with tenant_scope(tenant_id) as conn:
            return constraint_repo.list_constraints(conn, marketplace, kinds)

    def find_artefacts(self, tenant_id: UUID, request_key: str) -> Sequence[ExistingArtefact]:
        with tenant_scope(tenant_id) as conn:
            return generation_repo.find_artefacts(conn, tenant_id, request_key)

    def load_facts(self, tenant_id: UUID, sku: str | None) -> Sequence[FactInput]:
        if not sku:
            return []  # a sku-less lookup would mix products: never done (decision 2)
        with tenant_scope(tenant_id) as conn:
            return fact_repo.load_facts(conn, tenant_id, sku)

    def save_facts(self, tenant_id: UUID, user_id: UUID, facts: Sequence[NewFact]) -> Sequence[FactInput]:
        with tenant_scope(tenant_id) as conn:
            return fact_repo.insert_facts(conn, tenant_id, user_id, facts)

    def load_approval(self, tenant_id: UUID, approval_id: UUID) -> StoredApproval | None:
        with tenant_scope(tenant_id) as conn:
            return approval_repo.load_approval(conn, tenant_id, approval_id)

    def load_title_set(self, tenant_id: UUID, generation_id: UUID) -> StoredTitleSet | None:
        with tenant_scope(tenant_id) as conn:
            return generation_repo.load_title_set(conn, tenant_id, generation_id)

    def load_image_analysis(self, tenant_id: UUID, analysis_id: UUID) -> StoredAnalysis | None:
        with tenant_scope(tenant_id) as conn:
            return analysis_repo.load_analysis(conn, tenant_id, analysis_id)

    def load_generation(self, tenant_id: UUID, generation_id: UUID) -> StoredGeneration | None:
        """Read-only (P5): a persisted artefact by id, for replay, the settlement guard and the API response."""
        with tenant_scope(tenant_id) as conn:
            return generation_repo.load_generation(conn, tenant_id, generation_id)

    def load_sibling_packs(
        self, tenant_id: UUID, request_key: str, exclude: Marketplace
    ) -> Mapping[Marketplace, Mapping[str, Any]]:
        with tenant_scope(tenant_id) as conn:
            return generation_repo.load_sibling_packs(conn, tenant_id, request_key, exclude)

    def save_generation(self, tenant_id: UUID, record: GenerationRecord) -> UUID:
        # The generation row and its options commit together; a duplicate raises DuplicateArtefact
        # out of the `with`, which rolls the whole transaction back.
        with tenant_scope(tenant_id) as conn:
            return generation_repo.insert_generation(conn, tenant_id, record)

    def save_typed_approval(self, tenant_id: UUID, *, sku: str, marketplace: str, approved_text: str, approved_by: UUID) -> UUID:
        with tenant_scope(tenant_id) as conn:
            return approval_repo.insert_typed_approval(conn, tenant_id, sku=sku, marketplace=marketplace, approved_text=approved_text, approved_by=approved_by)

    def save_approval(
        self,
        tenant_id: UUID,
        *,
        generation_id: UUID,
        option_id: UUID | None,
        approved_text: str,
        edited_by_seller: bool,
        approved_by: UUID,
    ) -> UUID:
        with tenant_scope(tenant_id) as conn:
            return approval_repo.insert_approval(
                conn, tenant_id, generation_id=generation_id, option_id=option_id, approved_text=approved_text,
                edited_by_seller=edited_by_seller, approved_by=approved_by,
            )
