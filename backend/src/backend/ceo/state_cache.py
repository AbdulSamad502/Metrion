"""Business State cache (spec §6.26 L7): keyed (tenant, entry, data_version), with authorization checked BEFORE any cache read.

`data_version` here is a READ-ONLY fingerprint of the rows an entry is built from: for each source table, the row count and the sum of each row's
`xmin` (the id of the transaction that last wrote it), taken through the caller's own tenant scope. Any insert, update or delete by ANY writer (an upload,
a worker, a repository, a person with psql) changes it, so a new upload invalidates the cache without any owning package having to remember to bump a
counter, and the fingerprint is itself row-level-security scoped (it can only ever see this tenant's rows). A freeze or vacuum only invalidates; it can never
make stale data look current.

What is cached is the OUTPUT OF AN ENTRY'S LOADER (the persisted read), never an authorization decision and never the verified figures: the provenance gate
still re-resolves every ref on every read. An entry whose result depends on the clock (CI's staleness label) declares no source tables and is never cached;
every other key also carries the UTC date, so a day change recomputes.

Off unless an operator sets `CEO_STATE_CACHE_MAX_ENTRIES` (no default, like every CEO bound). In-process: with several workers each has its own cache, which is
safe (each validates its own entries against the database fingerprint) and merely less effective. Cross-worker sharing is the Redis item (V1.1).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from backend import config
from backend.repositories import ceo_runtime_repo

CacheKey = tuple[UUID, str, str, date]


def data_version(tenant_id: UUID, tables: Sequence[str]) -> str:
    """The fingerprint (see the module docstring), computed by the repository: this package contains no SQL."""
    return ceo_runtime_repo.data_fingerprint(tenant_id, tables)


class StateCache:
    def __init__(self, max_entries: int) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max = max_entries
        self._lock = threading.Lock()
        self._data: OrderedDict[CacheKey, Any] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: CacheKey) -> Any | None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]
            self.misses += 1
            return None

    def put(self, key: CacheKey, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


_cache: StateCache | None = None
_cache_size: int | None = None
_guard = threading.Lock()


def get_cache() -> StateCache | None:
    """The process cache, or None when no size is configured (caching off). Re-reads the setting so an operator or a test change takes effect."""
    global _cache, _cache_size
    size = config.ceo_state_cache_max_entries()
    with _guard:
        if size is None:
            _cache, _cache_size = None, None
        elif _cache is None or _cache_size != size:
            _cache, _cache_size = StateCache(size), size
        return _cache
