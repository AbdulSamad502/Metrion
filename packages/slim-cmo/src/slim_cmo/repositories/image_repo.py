"""`seller_image_asset`, `product_image_analysis` and `vision_eval_run` access for P6.

* Assets: content-addressed (`unique (tenant_id, sha256)`); an upload of an existing hash returns the existing
  asset. The application role may INSERT/UPDATE them; nothing here updates one.
* Analyses: APPEND-ONLY (the application role has SELECT + INSERT only). The partial unique index
  `product_image_analysis_complete_triple_idx` turns a duplicate COMPLETE analysis into `DuplicateAnalysis`.
* Evaluation runs are platform data, read-only here (written only by the operator CLI as the admin role).

Every tenant-owned query filters on `tenant_id` explicitly in addition to RLS.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from slim_cmo.service.models import AnalysisRecord, DuplicateAnalysis, ExistingAnalysis, StoredAsset
from slim_cmo.types import ImageAnalysisState
from slim_cmo.vision.trust import EvalRunRef

TRIPLE_INDEX = "product_image_analysis_complete_triple_idx"

_INSERT_ASSET = text(
    """
    INSERT INTO seller_image_asset (tenant_id, storage_uri, sha256, content_type, byte_size, uploaded_by, status)
    VALUES (:tenant_id, :storage_uri, :sha256, :content_type, :byte_size, :uploaded_by, 'ACTIVE')
    ON CONFLICT (tenant_id, sha256) DO NOTHING
    RETURNING id
    """
)
_FIND_ASSET_BY_SHA = text("SELECT id FROM seller_image_asset WHERE tenant_id = :tenant_id AND sha256 = :sha256")
_LOAD_ASSET = text(
    "SELECT id, storage_uri, sha256, content_type, byte_size, status FROM seller_image_asset WHERE tenant_id = :tenant_id AND id = :id"
)
_FIND_COMPLETE = text(
    """
    SELECT id, analysis_state, degraded_reason FROM product_image_analysis
    WHERE tenant_id = :tenant_id AND image_asset_id = :asset AND provider = :provider AND model = :model
      AND schema_version = :schema_version AND analysis_state = 'COMPLETE'
    """
)
_INSERT_ANALYSIS = text(
    """
    INSERT INTO product_image_analysis
      (tenant_id, image_asset_id, schema_version, provider, model, eval_gate_ref, attributes, analysis_state, degraded_reason)
    VALUES
      (:tenant_id, :asset, :schema_version, :provider, :model, :gate, CAST(:attributes AS jsonb), :state, :reason)
    RETURNING id
    """
)
_LATEST_RUN = text(
    """
    SELECT id, provider, model, schema_version, passed, run_at FROM vision_eval_run
    WHERE provider = :provider AND model = :model AND schema_version = :schema_version
    ORDER BY run_at DESC, id DESC LIMIT 1
    """
)
_COUNT_RECENT = text("SELECT count(*) FROM product_image_analysis WHERE tenant_id = :tenant_id AND created_at >= :since")


def insert_asset_if_absent(
    conn: Connection, tenant_id: UUID, *, uploaded_by: UUID, storage_uri: str, sha256: str, content_type: str, byte_size: int
) -> tuple[UUID, bool]:
    row = conn.execute(
        _INSERT_ASSET,
        {"tenant_id": tenant_id, "storage_uri": storage_uri, "sha256": sha256, "content_type": content_type,
         "byte_size": byte_size, "uploaded_by": uploaded_by},
    ).first()
    if row is not None:
        created: UUID = row.id
        return created, True
    existing = conn.execute(_FIND_ASSET_BY_SHA, {"tenant_id": tenant_id, "sha256": sha256}).one()
    found: UUID = existing.id
    return found, False


def load_asset(conn: Connection, tenant_id: UUID, asset_id: UUID) -> StoredAsset | None:
    r = conn.execute(_LOAD_ASSET, {"tenant_id": tenant_id, "id": asset_id}).first()
    return None if r is None else StoredAsset(r.id, r.storage_uri, r.sha256, r.content_type, r.byte_size, r.status)


def find_complete_analysis(
    conn: Connection, tenant_id: UUID, asset_id: UUID, provider: str, model: str, schema_version: str
) -> ExistingAnalysis | None:
    r = conn.execute(_FIND_COMPLETE, {"tenant_id": tenant_id, "asset": asset_id, "provider": provider, "model": model, "schema_version": schema_version}).first()
    return None if r is None else ExistingAnalysis(r.id, ImageAnalysisState(r.analysis_state), r.degraded_reason)


def insert_analysis(conn: Connection, tenant_id: UUID, rec: AnalysisRecord) -> UUID:
    try:
        row = conn.execute(
            _INSERT_ANALYSIS,
            {"tenant_id": tenant_id, "asset": rec.image_asset_id, "schema_version": rec.schema_version, "provider": rec.provider,
             "model": rec.model, "gate": rec.eval_gate_ref, "attributes": json.dumps(rec.attributes),
             "state": rec.analysis_state.value, "reason": rec.degraded_reason},
        ).one()
    except IntegrityError as exc:
        diag = getattr(exc.orig, "diag", None)
        if getattr(diag, "constraint_name", None) == TRIPLE_INDEX or TRIPLE_INDEX in str(exc.orig):
            raise DuplicateAnalysis() from exc
        raise
    analysis_id: UUID = row.id
    return analysis_id


def latest_eval_run(conn: Connection, provider: str, model: str, schema_version: str) -> EvalRunRef | None:
    r = conn.execute(_LATEST_RUN, {"provider": provider, "model": model, "schema_version": schema_version}).first()
    return None if r is None else EvalRunRef(r.id, r.provider, r.model, r.schema_version, bool(r.passed), r.run_at)


def count_recent_analyses(conn: Connection, tenant_id: UUID, since: datetime) -> int:
    return int(conn.execute(_COUNT_RECENT, {"tenant_id": tenant_id, "since": since}).scalar_one())
