"""§0g — `web_price_signal` is a rough reference only, never fed into Brain-1 math. PI build
plan Checkpoint 3's own named check: neither `estimate_product_feasibility`/any margin
calculation in calc-engine, nor any PI call site, ever reads/passes `web_price_signal`."""

from __future__ import annotations

import inspect

from calc_engine.api import estimate_product_feasibility as calc_module
from product_intelligence.direct_path import pi_discover, pi_report, pi_supplier_lookup
from product_intelligence.discovery import candidate_synthesis, discovery_run, ranking, shortlist_scoring


def test_calc_engine_estimate_product_feasibility_never_mentions_web_price_signal() -> None:
    source = inspect.getsource(calc_module)
    assert "web_price_signal" not in source


def test_calc_engine_estimate_product_feasibility_has_no_import_of_product_intelligence() -> None:
    """Structural enforcement, not just a naming check — calc-engine's PI-exclusive surface
    has no dependency at all on the package that produces web_price_signal, so it could not
    read the field even if a future edit tried to smuggle it in via a shared type."""
    source = inspect.getsource(calc_module)
    assert "product_intelligence" not in source


def _code_lines_only(source: str) -> str:
    """Strips module/function docstrings (triple-quoted blocks) so this scan checks actual
    code — imports, calls, kwargs — never a docstring's own prose *describing* the isolation
    rule (which necessarily names both terms to state the prohibition, same convention as
    `test_ranking_no_banned_words.py`'s own docstring-vs-code distinction)."""
    import re

    return re.sub(r'"""[\s\S]*?"""', "", source)


def test_no_pi_module_imports_calc_engine_at_all() -> None:
    """None of PI's discovery/direct_path modules import calc_engine — `web_price_signal` is
    produced by `candidate_synthesis.py`, which has no path to reach calc-engine's feasibility
    surface even if a future edit tried to wire the two together carelessly."""
    for module in (pi_discover, pi_report, pi_supplier_lookup, discovery_run, candidate_synthesis, ranking, shortlist_scoring):
        code = _code_lines_only(inspect.getsource(module))
        assert "import calc_engine" not in code and "from calc_engine" not in code, (
            f"{module.__name__} imports calc_engine — web_price_signal isolation depends on "
            "no PI discovery/direct_path module reaching calc-engine's feasibility surface at all"
        )


def test_no_pi_module_passes_web_price_signal_into_a_calc_engine_call() -> None:
    """`discovery_run.py` legitimately writes `web_price_signal=` as a repository-insert
    kwarg (persisting it for display, §0g) — that is not the isolation concern. What must
    never happen is `web_price_signal` reaching a calc-engine call; since no PI module imports
    calc_engine at all (previous test), no such call site can exist. This test re-confirms the
    same guarantee from the call-argument angle: no PI module contains a call whose name
    matches `estimate_product_feasibility` or `ProspectiveObservationSet` at all."""
    for module in (pi_discover, pi_report, pi_supplier_lookup, discovery_run, ranking, shortlist_scoring):
        code = _code_lines_only(inspect.getsource(module))
        assert "estimate_product_feasibility(" not in code
        assert "ProspectiveObservationSet(" not in code
