"""The collection permission grid (rag-knowledge.md §6.1): which agent may query which collection. A code constant, enforced in the repository (not by the caller's good behaviour).

V1 builds retrieval for the CEO and, narrowly, the CMO; the other rows are specified but their retrieval is not built. The repository still refuses anything outside a row.
"""

from __future__ import annotations

from collections.abc import Mapping

AGENTS = ("CEO", "CFO", "PI", "CMO", "CI")
COLLECTIONS = ("SELLER_DOCUMENT", "APPROVED_FINDING", "APPROVED_MEMORY", "GLOBAL_REFERENCE")

# agent -> collections it may query. Finer limits (document tags, finding kinds, memory kinds) are applied by the retrieval layer on top of this coarse gate (R3).
GRID: Mapping[str, frozenset[str]] = {
    "CEO": frozenset({"SELLER_DOCUMENT", "APPROVED_FINDING", "APPROVED_MEMORY"}),
    "CMO": frozenset({"SELLER_DOCUMENT", "APPROVED_MEMORY"}),
    "CFO": frozenset({"SELLER_DOCUMENT", "GLOBAL_REFERENCE"}),
    "PI": frozenset({"SELLER_DOCUMENT", "APPROVED_FINDING"}),
    "CI": frozenset({"APPROVED_FINDING"}),
}


class CollectionNotPermitted(PermissionError):
    pass


def permitted(agent: str, collections: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """The requested collections, if ALL are permitted to `agent`; otherwise `CollectionNotPermitted` (a partial grant is a refusal, never a silent narrowing)."""
    allowed = GRID.get(agent)
    if allowed is None:
        raise CollectionNotPermitted(f"unknown agent {agent!r}")
    if not collections:
        raise CollectionNotPermitted("no collection requested")
    denied = [c for c in collections if c not in allowed]
    if denied:
        raise CollectionNotPermitted(f"{agent} may not query {denied}")
    return tuple(collections)
