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

# Everything except the I/O layers is the deterministic core. `generation/` (P3) stays INSIDE the
# set: prompts, parsing and retry loops take an `LlmProvider` Protocol and never import a model,
# network, database or clock themselves. `repositories/` (SQL), `providers/` (HTTP clients) and
# `service/` (orchestration over the DB) are the only places allowed to do I/O.
IO_PACKAGES = {"repositories", "providers", "service", "imaging", "storage", "evaluation", "retrieval"}
P2_FILES = sorted(p for p in SRC.rglob("*.py") if not (IO_PACKAGES & set(p.parts)))

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
                     "textnorm.py", "types.py", "generation/titles.py", "generation/copy.py", "generation/standalone.py",
                     "generation/engine.py", "generation/prompts.py", "generation/parse.py", "generation/safety.py",
                     "generation/facts.py", "generation/provider.py", "catalog/attributes.py", "catalog/estimates.py", "catalog/resolve.py",
                     "vision/schema.py", "vision/provider.py", "vision/prompts.py", "vision/parse.py", "vision/trust.py", "vision/eval.py", "trends/evidence.py", "trends/sources.py", "trends/screening.py", "trends/risk.py", "trends/queries.py"):
        assert expected in names
    assert not any(set(n.split("/")) & IO_PACKAGES for n in names)


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
            if root == "PIL" and "imagequality" in path.parts:
                continue  # M9's pure image measurements use Pillow only; its own boundary test below pins that
            if root not in stdlib:
                third_party.add(root)
    assert third_party == {"publicsuffixlist"}


# ---- P6: the I/O layers that are NOT in the pure set still have a hard import boundary ------------------------

NETWORK_AND_MODEL_MODULES = {
    "httpx", "requests", "urllib3", "aiohttp", "socket", "ssl", "http", "urllib.request", "ollama", "openai", "anthropic",
    "langchain", "langchain_core", "transformers", "torch", "sqlalchemy", "psycopg", "psycopg2", "alembic", "redis",
}


def _layer_imports(layer: str) -> set[str]:
    found: set[str] = set()
    for path in (SRC / layer).rglob("*.py"):
        for module in _imports(ast.parse(path.read_text(encoding="utf-8"))):
            found.add(module.split(".")[0])
    return found


def test_imaging_touches_no_network_database_or_model_and_only_pillow_is_third_party():
    imported = _layer_imports("imaging")
    assert not imported & {m.split(".")[0] for m in NETWORK_AND_MODEL_MODULES}
    import sys

    third_party = {m for m in imported if m not in set(sys.stdlib_module_names) | {"slim_cmo", "__future__"}}
    assert third_party == {"PIL"}


def test_imagequality_stays_pure_pillow_only_with_no_network_database_model_or_clock():
    """CMO 3.0 M9: the image measurements and score are deterministic Pillow code. Still subject to the float and clock rules above (it is not an I/O package)."""
    imported = _layer_imports("imagequality")
    assert not imported & {m.split(".")[0] for m in NETWORK_AND_MODEL_MODULES}
    import sys

    third_party = {m for m in imported if m not in set(sys.stdlib_module_names) | {"slim_cmo", "__future__"}}
    assert third_party == {"PIL"}


def test_storage_is_stdlib_only_and_has_no_network_or_database():
    import sys

    imported = _layer_imports("storage")
    assert not imported & {m.split(".")[0] for m in NETWORK_AND_MODEL_MODULES}
    assert imported <= set(sys.stdlib_module_names) | {"slim_cmo", "__future__"}


def test_the_vision_core_has_no_image_library_file_or_network_access():
    imported = _layer_imports("vision")
    assert not imported & ({m.split(".")[0] for m in NETWORK_AND_MODEL_MODULES} | {"PIL", "os", "pathlib", "tempfile", "io", "base64"})


def test_only_the_vision_provider_and_the_evaluation_db_writer_reach_the_network_or_database():
    for layer in ("imaging", "storage", "service", "evaluation"):
        for path in (SRC / layer).rglob("*.py"):
            imported = {m.split(".")[0] for m in _imports(ast.parse(path.read_text(encoding="utf-8")))}
            assert "httpx" not in imported, (layer, path.name)
    for path in (SRC / "evaluation").rglob("*.py"):
        imported = {m.split(".")[0] for m in _imports(ast.parse(path.read_text(encoding="utf-8")))}
        if path.name != "db.py":
            assert "sqlalchemy" not in imported, path.name


def test_retrieval_calls_providers_only_through_market_signals_and_touches_no_llm_database_or_raw_http():
    """The retrieval layer is deterministic: no model of any kind, no direct DB or HTTP (the slot counter is injected, the
    provider clients come from market_signals), and no catalog / niche / generation code that could feed it seller data."""
    imported = _layer_imports("retrieval")
    assert not imported & {m.split(".")[0] for m in NETWORK_AND_MODEL_MODULES}
    assert imported <= {"__future__", "logging", "collections", "contextlib", "dataclasses", "datetime", "enum", "typing", "market_signals", "slim_cmo"}
    internal = {m for path in (SRC / "retrieval").rglob("*.py") for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith("slim_cmo")}
    assert not {m for m in internal if m.split(".")[1:2] in (["generation"], ["providers"], ["catalog"], ["service"], ["repositories"], ["vision"])}

