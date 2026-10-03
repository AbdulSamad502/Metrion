"""`product_image_analysis` READ (spec §6.2). P3 consumes an existing analysis; creating one is P6.

Attributes are returned as stored, EXCEPT that `EVAL_PASSED` is downgraded to `UNVERIFIED_HINT` unless the latest
evaluation for the analysis's exact provider/model/schema_version passed (read-time trust revocation, P6). The
stored row is never modified; `claims.assess` decides what is claim-eligible. A hint is never promoted here.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, text

from slim_cmo.service.models import StoredAnalysis
from slim_cmo.types import ImageAnalysisState
from slim_cmo.vision.trust import effective_attributes

_LOAD = text(
    "SELECT id, analysis_state, attributes, provider, model, schema_version FROM product_image_analysis "
    "WHERE tenant_id = :tenant_id AND id = :id"
)
# The LATEST evaluation for exactly this provider/model/schema decides whether stored EVAL_PASSED still counts.
_LATEST_PASSED = text(
    "SELECT passed FROM vision_eval_run WHERE provider = :provider AND model = :model AND schema_version = :schema_version "
    "ORDER BY run_at DESC, id DESC LIMIT 1"
)


def load_analysis(conn: Connection, tenant_id: UUID, analysis_id: UUID) -> StoredAnalysis | None:
    r = conn.execute(_LOAD, {"tenant_id": tenant_id, "id": analysis_id}).first()
    if r is None:
        return None
    stored = [a for a in (r.attributes or []) if isinstance(a, dict)]
    latest = conn.execute(_LATEST_PASSED, {"provider": r.provider, "model": r.model, "schema_version": r.schema_version}).first()
    # Read-time revocation (P6 decision 3): the stored row is immutable and never changes; a consumer is only
    # shown EVAL_PASSED while the latest evaluation for the exact provider/model/schema passed. Nothing is promoted.
    attrs = tuple(effective_attributes(stored, latest is not None and bool(latest[0])))
    return StoredAnalysis(r.id, ImageAnalysisState(r.analysis_state), attrs)
