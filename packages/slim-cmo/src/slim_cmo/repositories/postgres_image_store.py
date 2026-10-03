"""`ImageStorePort` over Postgres: one `tenant_scope` transaction per call. No call is held open while a vision
model runs (the service calls the provider between store calls, never inside one)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from slim_cmo.repositories import image_repo
from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.service.models import AnalysisRecord, ExistingAnalysis, StoredAnalysis, StoredAsset
from slim_cmo.vision.trust import EvalRunRef


class PostgresImageStore:
    def save_asset(
        self, tenant_id: UUID, *, uploaded_by: UUID, storage_uri: str, sha256: str, content_type: str, byte_size: int
    ) -> tuple[UUID, bool]:
        with tenant_scope(tenant_id) as conn:
            return image_repo.insert_asset_if_absent(
                conn, tenant_id, uploaded_by=uploaded_by, storage_uri=storage_uri, sha256=sha256, content_type=content_type, byte_size=byte_size
            )

    def load_asset(self, tenant_id: UUID, asset_id: UUID) -> StoredAsset | None:
        with tenant_scope(tenant_id) as conn:
            return image_repo.load_asset(conn, tenant_id, asset_id)

    def find_complete_analysis(
        self, tenant_id: UUID, asset_id: UUID, provider: str, model: str, schema_version: str
    ) -> ExistingAnalysis | None:
        with tenant_scope(tenant_id) as conn:
            return image_repo.find_complete_analysis(conn, tenant_id, asset_id, provider, model, schema_version)

    def save_analysis(self, tenant_id: UUID, record: AnalysisRecord) -> UUID:
        # A duplicate raises DuplicateAnalysis out of the `with`, rolling the transaction back.
        with tenant_scope(tenant_id) as conn:
            return image_repo.insert_analysis(conn, tenant_id, record)

    def latest_eval_run(self, tenant_id: UUID, provider: str, model: str, schema_version: str) -> EvalRunRef | None:
        with tenant_scope(tenant_id) as conn:
            return image_repo.latest_eval_run(conn, provider, model, schema_version)

    def load_effective_analysis(self, tenant_id: UUID, analysis_id: UUID) -> StoredAnalysis | None:
        from slim_cmo.repositories import analysis_repo

        with tenant_scope(tenant_id) as conn:
            return analysis_repo.load_analysis(conn, tenant_id, analysis_id)

    def count_recent_analyses(self, tenant_id: UUID, since: datetime) -> int:
        with tenant_scope(tenant_id) as conn:
            return image_repo.count_recent_analyses(conn, tenant_id, since)
