"""Evidence-packet cache stores (cfo-query-planner.md D3, §6.4).

Values are serialised evidence packets only — never rows. A key is `cache_key(...)` (tenant-prefixed and bound to the plan, the tenant's
`data_version`, the catalog and formula versions), so a stale result is unreachable by construction and no purge is needed. On top of the
key, every read re-checks that the stored packet belongs to the requested plan hash, catalog version and data version, and that the key
carries the requesting tenant's prefix: a corrupt or mis-keyed entry is a miss, never a wrong answer.

`RedisEvidenceCache` talks to any client exposing `get(key)` and `set(key, value, ex=seconds)` (redis-py's interface); the TTL is
configuration with no default (OQ3 recommends 24 h, but correctness does not depend on it).
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Protocol
from uuid import UUID

from cfo.planner.cache import tenant_prefix
from cfo.planner.evidence import EvidencePacket


class EvidenceCache(Protocol):
    def get(self, tenant_id: UUID, key: str, *, plan_hash: str, catalog_version: str, data_version: int) -> EvidencePacket | None: ...

    def put(self, tenant_id: UUID, key: str, packet: EvidencePacket) -> None: ...


def _validated(raw: str | bytes | None, tenant_id: UUID, key: str, plan_hash: str, catalog_version: str, data_version: int) -> EvidencePacket | None:
    if raw is None or not key.startswith(tenant_prefix(tenant_id)):
        return None
    try:
        packet = EvidencePacket.from_json(raw.decode() if isinstance(raw, bytes) else raw)
    except (ValueError, KeyError, TypeError):
        return None
    if (packet.plan_hash, packet.catalog_version, packet.data_version) != (plan_hash, catalog_version, data_version):
        return None
    return packet


class InMemoryEvidenceCache:
    def __init__(self) -> None:
        self._data: MutableMapping[str, str] = {}

    def get(self, tenant_id: UUID, key: str, *, plan_hash: str, catalog_version: str, data_version: int) -> EvidencePacket | None:
        return _validated(self._data.get(key), tenant_id, key, plan_hash, catalog_version, data_version)

    def put(self, tenant_id: UUID, key: str, packet: EvidencePacket) -> None:
        if not key.startswith(tenant_prefix(tenant_id)):
            raise ValueError("cache key does not carry the requesting tenant's prefix")
        self._data[key] = packet.to_json()

    def keys(self) -> list[str]:
        return sorted(self._data)


class _RedisLike(Protocol):
    def get(self, name: str) -> str | bytes | None: ...
    def set(self, name: str, value: str, ex: int | None = None) -> object: ...


class RedisEvidenceCache:
    def __init__(self, client: _RedisLike, ttl_seconds: int) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive (configuration, never defaulted)")
        self._client = client
        self._ttl = ttl_seconds

    def get(self, tenant_id: UUID, key: str, *, plan_hash: str, catalog_version: str, data_version: int) -> EvidencePacket | None:
        if not key.startswith(tenant_prefix(tenant_id)):
            return None
        try:
            raw = self._client.get(key)
        except Exception:  # a cache outage is a miss, not an outage of the answer
            return None
        return _validated(raw, tenant_id, key, plan_hash, catalog_version, data_version)

    def put(self, tenant_id: UUID, key: str, packet: EvidencePacket) -> None:
        if not key.startswith(tenant_prefix(tenant_id)):
            raise ValueError("cache key does not carry the requesting tenant's prefix")
        try:
            self._client.set(key, packet.to_json(), ex=self._ttl)
        except Exception:
            return  # best effort: the packet was already computed correctly
