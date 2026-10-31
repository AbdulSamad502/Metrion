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
    "registry.py": ("backend.api", "backend.services.ceo_expense_ops", "backend.services.ceo_import_ops", "backend.services.ceo_cash_ops", "backend.services.ceo_perf_ops"),  # + the Expense Tracker handlers (owner decision 2026-10-23): thin wrappers over the tracker's own route functions
    # persisted-derived reads: the single CFO service function (derived_reads) and read-only repositories
    "derived_reads.py": ("backend.services.cfo_actions",),
    # the CI / PI / CMO persisted reads come through ONE declared seam (`backend/services/ceo_reads.py`), never a direct specialist import
    "business_state.py": ("calc_engine.repositories", "cfo.repositories", "backend.services.cfo_imports", "backend.services.ceo_reads"),
    "cmo_chat.py": ("backend.services.cmo_hints", "backend.services.cmo_listing", "backend.services.cmo_preview", "backend.services.cmo_readiness"),  # CMO 3.0 M0: recording a photo detail the seller confirmed is the same zero-unit CMO action as the HTTP route, in one tenant-scoped service
    "cmo_history_chat.py": ("backend.services.cmo_history", "backend.services.cmo_runtime", "slim_cmo.history.ask"),  # CMO 3.0 M7: listing history is a read-only, free CMO service (the same kind of seam as cmo_chat.py) plus the pure parser of the closed set of chat requests
    "clarification.py": ("backend.services.ceo_reads",),  # ranking candidates by their latest capture is a tenant-scoped read through that seam
    "approval.py": ("backend.services.ceo_reads",),  # re-reading the saved niche brief an approval plan is bound to: a tenant-scoped read through that seam
    "plans.py": ("backend.services.ceo_reads",),  # resolving "the latest finished research run" is a tenant-scoped read through that seam
    "input_session.py": ("backend.services.ceo_reads", "backend.services.expense_ledger_rules"),  # real competitors and fee-rate combinations to offer, read through that seam (tenant-scoped, read-only)
    # the ONE declared write (spec 6.35, owner-approved): the research brief a seller confirmed in chat, saved through a single tenant-scoped service
    # and (spec 6.36, owner-approved) the supplier quote / batch budget a seller confirmed on a confirm card, saved through the CFO's own write path in one service
    "orchestrator.py": ("backend.services.ceo_attachment_analysis", "backend.services.ceo_briefs", "backend.services.ceo_import_ops", "backend.services.ceo_inputs", "backend.services.ceo_progress", "backend.services.cmo_ci_inputs", "backend.services.ceo_reads"),  # the attached-spreadsheet analysis: pure code over the seller's own file, no specialist, no ledger, no model
    "pi_research.py": ("backend.services.ceo_pi_research",),  # ceo-pi-research-flow.md: choosing the five products, finalising the case and reading it back, through one tenant-scoped service
    "approval_run.py": ("backend.services.ceo_pi_research",),  # the same read, to write the five-product summary of an approved research plan
    "data_requests.py": ("backend.services.ceo_reads",),  # spec 6.37: reading an open data request and what is already stored, through that tenant-scoped seam
    # the CEO's own deterministic CI conversations (CI spec 6.21): tenant-scoped, read-only reads through two declared seams; every write goes through a registered action
    "ci_conversation.py": ("backend.services.ceo_reads", "backend.services.ci_conv_data"),
    "composition_gate.py": ("backend.services.ci_conv_data",),  # the CI narration rule uses the one list of claims CI does not have (CI spec C40)
    "slot_resolvers.py": ("backend.services.ceo_reads",),  # resolving a named competitor is a tenant-scoped read through that seam
    # the GST lookup invocation: the single declared use of the CFO service function for GST (same precedent as derived_reads.py)
    "gst_lookup.py": ("backend.services.cfo_actions",),
    "profile_context.py": ("backend.services.business_profile",),  # business-profile.md: the ONE read-only seam for the seller's self-declared profile (a short line built by code)
    "provenance.py": ("calc_engine.repositories", "competitor_intelligence.repositories"),
    # the Expense Tracker conversation (ceo-expense-tracker-chat.md): the seller's own entries through ONE read seam, plus the pure category rules
    "import_chat.py": ("backend.services.ceo_import_ops",),  # adding attached reports to the records: the preview and the card text are read through ONE declared seam (cfo-3-growth-advisor.md Phase 0)
    "expense_chat.py": ("backend.services.ceo_expense_reads", "backend.services.expense_ledger_rules"),
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


# ---------------------------------------------------------------------------------------------------------------- B3: the model seams
MODEL_SEAMS = ("classifier.py", "composer.py")
NEVER_IN_MODEL_SEAMS = ("backend.ceo.dispatch", "backend.ceo.registry", "backend.ceo.business_state", "backend.repositories", "backend.entitlement", "backend.tenant_context")


@pytest.mark.parametrize("name", MODEL_SEAMS)
def test_the_two_model_seams_cannot_execute_anything(name: str):
    """The classifier and composer take text in and return text out (spec §6.3, §6.5): neither may import the choke point, the registry,
    Business State, a repository or the entitlement/tenant machinery, so a model's output can only ever be VALIDATED by other code."""
    bad = [f"{name}:{ln} imports {m}" for m, ln in _imports(_tree(CEO / name)) if any(_matches(m, f) for f in NEVER_IN_MODEL_SEAMS)]
    assert not bad, "\n".join(bad)


def test_only_the_orchestrator_calls_dispatch_and_the_legs_come_from_the_fixed_plans():
    callers = []
    for path in FILES:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "dispatch" and path.name not in ("dispatch.py",):
                callers.append(path.name)
    assert set(callers) == {"orchestrator.py"}
    src = (CEO / "orchestrator.py").read_text(encoding="utf-8")
    assert "ACTIONS[key].build_slots" in src and "PLAYBOOKS[key]" in src  # slots and legs come from plans.py, never from model output


def test_nothing_in_the_ceo_package_imports_the_evaluation_harness_or_a_provider_sdk():
    for path in FILES:
        for module, line in _imports(_tree(path)):
            assert not _matches(module, "backend.ceo_eval"), f"{path.name}:{line}"
            assert not any(_matches(module, sdk) for sdk in ("ollama", "openai", "anthropic", "langchain", "langgraph", "httpx")), f"{path.name}:{line} imports {module}"


def test_the_llm_layer_is_the_only_place_that_talks_to_a_model_server():
    llm = SRC / "llm" / "model.py"
    assert "httpx" in llm.read_text(encoding="utf-8")
    for path in FILES:
        assert "11434" not in path.read_text(encoding="utf-8") and "api/generate" not in path.read_text(encoding="utf-8")
