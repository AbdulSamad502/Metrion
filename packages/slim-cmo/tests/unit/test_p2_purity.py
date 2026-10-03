"""Structural guarantees about the deterministic core, checked on the source itself.

P2 is the safety net that stands behind the (P3) LLM. If it could call a model, reach the
network, read a database or consult the clock it could not be tested, replayed or trusted, so
this test fails the build if any P2 module ever does:

* imports a network, model, database or randomness module;
* calls the wall clock (`datetime.now()/utcnow()/today()`, `time.time()`...) - time is always an
  argument, which is what makes the boundary tests exact;
* uses `float` anywhere (also enforced by scripts/lint_no_float.py, repeated here so a unit run
  alone catches it).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "slim_cmo"

# Everything except the DB plumbing (repositories/) is the deterministic core.
P2_FILES = sorted(p for p in SRC.rglob("*.py") if "repositories" not in p.parts)

FORBIDDEN_MODULES = {
    "httpx", "requests", "urllib3", "aiohttp", "socket", "ssl", "http", "urllib.request", "ftplib", "smtplib", "websockets",
    "ollama", "openai", "anthropic", "langchain", "langchain_core", "transformers", "torch", "google.generativeai", "cohere", "mistralai",
    "sqlalchemy", "psycopg", "psycopg2", "alembic", "asyncpg", "redis",
    "random", "secrets", "uuid_utils",
    "subprocess", "os", "shutil", "pathlib", "tempfile", "pickle", "marshal",
}
CLOCK_ATTRS = {"now", "utcnow", "today", "time", "monotonic", "perf_counter", "time_ns", "sleep"}


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _id(path: pathlib.Path) -> str:
    return str(path.relative_to(SRC)).replace("\\", "/")


def test_the_deterministic_core_is_what_we_think_it_is():
    names = {_id(p) for p in P2_FILES}
    for expected in ("config.py", "constraints.py", "validators.py", "forbidden.py", "claims.py", "billing.py", "narration.py",
                     "textnorm.py", "types.py", "trends/evidence.py", "trends/sources.py", "trends/screening.py", "trends/risk.py"):
        assert expected in names
    assert not any("repositories" in n for n in names)


@pytest.mark.parametrize("path", P2_FILES, ids=_id)
def test_no_network_model_database_or_filesystem_imports(path):
    imported = _imports(ast.parse(path.read_text(encoding="utf-8")))
    bad = {m for m in imported if m in FORBIDDEN_MODULES or m.split(".")[0] in FORBIDDEN_MODULES}
    assert not bad, f"{_id(path)} imports {sorted(bad)}"


@pytest.mark.parametrize("path", P2_FILES, ids=_id)
def test_no_wall_clock_access(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in CLOCK_ATTRS:
            owner = ast.unparse(node.func.value)
            if owner in {"datetime", "datetime.datetime", "time", "date", "datetime.date"}:
                offenders.append(f"{owner}.{node.func.attr}()")
    assert not offenders, f"{_id(path)} reads the clock: {offenders}"


@pytest.mark.parametrize("path", P2_FILES, ids=_id)
def test_no_floats(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            pytest.fail(f"{_id(path)}:{node.lineno} float literal")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
            pytest.fail(f"{_id(path)}:{node.lineno} float() call")


def test_only_the_psl_dependency_is_third_party():
    third_party = set()
    stdlib_and_self = {"slim_cmo", "__future__"}
    import sys

    stdlib = set(sys.stdlib_module_names) | stdlib_and_self
    for path in P2_FILES:
        for module in _imports(ast.parse(path.read_text(encoding="utf-8"))):
            root = module.split(".")[0]
            if root not in stdlib:
                third_party.add(root)
    assert third_party == {"publicsuffixlist"}
