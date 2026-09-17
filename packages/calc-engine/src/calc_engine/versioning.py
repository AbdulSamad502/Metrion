"""canonical_data_version derivation — deterministic-engine.md §4.3.

Derived, never stored upstream: a fingerprint of everything that fed a calculation, sorted
before hashing so the result never depends on database row order (required for AC1).
"""

from __future__ import annotations

import hashlib
from typing import Iterable
from uuid import UUID


def derive_canonical_data_version(
    ingestion_run_ids: Iterable[UUID | str],
    adapter_versions: Iterable[str],
    active_adjustment_ids: Iterable[UUID | str],
) -> str:
    """sha256 of sorted(ingestion_run ids) + sorted(adapter_id:adapter_version) + sorted(active manual_adjustment ids).

    `adapter_versions` entries must already be pre-formatted as "adapter_id:adapter_version"
    strings by the caller — this function only sorts and hashes, it does not know the shape
    of an adapter identity.
    """
    sorted_runs = sorted(str(i) for i in ingestion_run_ids)
    sorted_adapters = sorted(adapter_versions)
    sorted_adjustments = sorted(str(i) for i in active_adjustment_ids)

    payload = "\n".join(
        [
            "ingestion_runs:" + ",".join(sorted_runs),
            "adapters:" + ",".join(sorted_adapters),
            "manual_adjustments:" + ",".join(sorted_adjustments),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
