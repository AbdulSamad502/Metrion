"""C35 / AC41 / T81 — a Tavily lead is never an observation.

Static, not behavioural: the modules that build observations (snapshots, deltas, comparison,
price-band inputs, review/listing insight, alerts, digest, handoff) must not so much as import
anything that carries search-lead data. If one ever does, this fails the build — the rule is
enforced by structure, not by convention (§6.28.3).
"""

from __future__ import annotations

import ast
from pathlib import Path

import competitor_intelligence

_PKG = Path(competitor_intelligence.__file__).parent

OBSERVATION_PATHS = (
    "evidence",
    "delta",
    "landscape",
    "alerts",
    "insight",
    "review_insight",
    "listing_insight",
    "digest",
    "direct_path",
    "handoff.py",
)

FORBIDDEN_MODULE_FRAGMENTS = (
    "discovery.tavily_search_provider",
    "discovery.search_provider",
    "discovery.mock_search_provider",
    "discovery.listing_url",
    "repositories.ci_search_result_repo",
    "repositories.ci_search_query_repo",
)


def _python_files(rel: str) -> list[Path]:
    target = _PKG / rel
    return [target] if target.is_file() else sorted(target.rglob("*.py"))


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
            found += [f"{node.module}.{alias.name}" for alias in node.names]
    return found


def test_observation_modules_never_import_search_lead_data() -> None:
    offenders: list[str] = []
    for rel in OBSERVATION_PATHS:
        for path in _python_files(rel):
            for module in _imported_modules(path):
                if any(fragment in module for fragment in FORBIDDEN_MODULE_FRAGMENTS):
                    offenders.append(f"{path.relative_to(_PKG)} imports {module}")
    assert offenders == [], "search-lead data reached an observation module: " + "; ".join(offenders)


def test_the_boundary_check_actually_sees_the_observation_modules() -> None:
    """Guard against the test passing vacuously because a path was renamed."""
    for rel in OBSERVATION_PATHS:
        assert _python_files(rel), f"observation path {rel!r} no longer exists — update OBSERVATION_PATHS"
