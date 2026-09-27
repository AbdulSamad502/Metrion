"""CP1 smoke test — the package and its repositories import cleanly. No business logic to
test yet (that lands in CP2/CP3); this only proves the scaffolding is wired."""

from __future__ import annotations


def test_cfo_package_imports() -> None:
    import cfo  # noqa: F401


def test_repositories_import() -> None:
    from cfo.repositories import agent_data_request_repo, leak_finding_repo, tenant_context  # noqa: F401
