"""Architecture tests for `backend/ceo` (spec AC22, AC23, §6.10 enforcement list; CLAUDE.md's hard rule).

These are AST checks over the CEO package's own source. They are honest about their reach: they catch the *kinds* of mistake that
would make the CEO a compute path or a bypass (SQL, eval/exec, Brain 1 compute imports, direct specialist imports, a synthetic
`AuthContext`, floats, operators on money-named operands). They do not prove semantic correctness — the behaviour tests do that.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "backend"
CEO = SRC / "ceo"
FILES = sorted(p for p in CEO.glob("*.py"))

# Which modules may import what. Anything not allowed is a failure.
SPECIALIST_PREFIXES = ("backend.api", "backend.services", "backend.agents", "cfo", "competitor_intelligence", "product_intelligence",
                       "slim_cmo", "calc_engine", "data_foundation", "market_signals")
ALLOWED_SPECIALIST_IMPORTS: dict[str, tuple[str, ...]] = {
    # the registry is the ONLY module that imports specialist handlers
    "registry.py": ("backend.api",),
    # persisted-derived reads: the single CFO service function (derived_reads) and read-only repositories
    "derived_reads.py": ("backend.services.cfo_actions",),
    "business_state.py": ("calc_engine.repositories", "cfo.repositories", "backend.services.cfo_imports"),
    "provenance.py": ("calc_engine.repositories", "competitor_intelligence.repositories"),
}
# Brain 1 compute surfaces: NEVER importable from the CEO package.
FORBIDDEN_PREFIXES = ("calc_engine.formulas", "calc_engine.api", "calc_engine.anomaly", "calc_engine.gst", "backend.agents")
_ARITH = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.Module) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            # `from a.b import c` may be importing the module a.b.c, so match against the fully-qualified name.
            out += [(f"{node.module}.{a.name}", node.lineno) for a in node.names]
    return out


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def test_the_package_exists_and_is_scanned():
    assert {"contract.py", "dispatch.py", "registry.py", "business_state.py", "provenance.py", "figure_format.py"} <= {p.name for p in FILES}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_sql_eval_exec_or_dynamic_code(path: Path):
    tree = _tree(path)
    bad = [f"{path.name}:{ln} imports {m}" for m, ln in _imports(tree) if _matches(m, "sqlalchemy") or _matches(m, "psycopg") or m in ("subprocess", "pickle", "marshal")]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec", "compile", "__import__"):
            bad.append(f"{path.name}:{node.lineno} calls {node.func.id}()")
    assert not bad, "\n".join(bad)  # CEO code never writes SQL or runs generated code (OP10)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_specialists_and_brain1_are_reached_only_where_allowed(path: Path):
    allowed = ALLOWED_SPECIALIST_IMPORTS.get(path.name, ())
    bad: list[str] = []
    for module, line in _imports(_tree(path)):
        if any(_matches(module, f) for f in FORBIDDEN_PREFIXES):
            bad.append(f"{path.name}:{line} imports forbidden {module}")
        elif any(_matches(module, s) for s in SPECIALIST_PREFIXES) and not any(_matches(module, a) for a in allowed):
            bad.append(f"{path.name}:{line} imports {module} (only {allowed or 'nothing'} is allowed here)")
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_ceo_never_constructs_an_auth_context(path: Path):
    """R1: the choke point takes the REAL authenticated context; the old synthetic `AuthContext(clerk_user_id="ceo-hub")` is retired."""
    bad = [
        f"{path.name}:{n.lineno}"
        for n in ast.walk(_tree(path))
        if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) == "AuthContext"
    ]
    assert not bad, f"AuthContext constructed in: {bad}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_floats_and_no_rounding(path: Path):
    bad: list[str] = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            bad.append(f"{path.name}:{node.lineno} float literal")
        elif isinstance(node, ast.Name) and node.id in ("float", "round"):
            bad.append(f"{path.name}:{node.lineno} uses {node.id}")
    assert not bad, "\n".join(bad)  # no floats in any calculation path (CLAUDE.md)


def _is_money_named(node: ast.expr) -> bool:
    name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""
    lowered = name.lower()
    return "paise" in lowered or "amount" in lowered or "rupee" in lowered


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_arithmetic_on_money_named_operands(path: Path):
    """Same convention as `packages/cfo/tests/unit/test_no_arithmetic_lint.py`: no `+ - * / // % **` with a paise/amount/rupee-named operand.
    Display conversion uses `divmod`/`abs` calls in `figure_format.py` only, which read as unit conversion, not derivation."""
    bad: list[str] = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ARITH) and (_is_money_named(node.left) or _is_money_named(node.right)):
            bad.append(f"{path.name}:{node.lineno} arithmetic on a money-named operand")
        if isinstance(node, ast.AugAssign) and isinstance(node.op, _ARITH) and _is_money_named(node.target):
            bad.append(f"{path.name}:{node.lineno} augmented arithmetic on a money-named target")
    assert not bad, "\n".join(bad)


def test_money_formatting_lives_in_exactly_one_module():
    """`divmod` (the unit-conversion call) appears only in figure_format.py."""
    users = [p.name for p in FILES if any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == "divmod" for n in ast.walk(_tree(p)))]
    assert users == ["figure_format.py"]


def test_the_composition_root_is_not_imported_by_other_modules():
    """Only the registry imports specialist HTTP handlers, and nothing in the package imports the dummy-hub modules."""
    for path in FILES:
        for module, line in _imports(_tree(path)):
            assert not _matches(module, "backend.agents"), f"{path.name}:{line} imports the dummy hub"
            if _matches(module, "backend.api") and path.name != "registry.py":
                pytest.fail(f"{path.name}:{line} imports an HTTP module")
