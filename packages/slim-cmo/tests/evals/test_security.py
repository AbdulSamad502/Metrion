"""Static security and architecture checks for Slim CMO (plan P10, matrix: recommend-only, no money outside the engine, tenant from
context only, no event-loop blocking). These read the source, so they fail the moment a forbidden pattern is introduced."""

from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[4]
PKG = ROOT / "packages" / "slim-cmo" / "src" / "slim_cmo"
MS = ROOT / "packages" / "market-signals" / "src" / "market_signals"
BE = ROOT / "backend" / "src" / "backend"
CMO_BACKEND = [BE / "api/v1/cmo.py", BE / "services/cmo_actions.py", BE / "services/cmo_trends.py", BE / "services/cmo_runtime.py", BE / "services/cmo_images.py",
               BE / "services/cmo_response.py", BE / "agents/ceo_hub_cmo.py"]
ALL_SOURCES = [*PKG.rglob("*.py"), *MS.rglob("*.py"), *CMO_BACKEND]


def code(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_only_external_hosts_in_cmo_code_are_the_two_search_providers_and_youtube_links():
    allowed = {"https://api.tavily.com", "https://www.googleapis.com", "https://www.youtube.com"}
    found = {m for f in ALL_SOURCES for m in re.findall(r"https?://[A-Za-z0-9._-]+", code(f))}
    # example/documentation hosts inside docstrings or tests-only strings are fine; a REAL marketplace host never is
    assert found <= allowed | {u for u in found if "example" in u}, found - allowed
    marketplaces = ("amazon.", "flipkart.", "meesho.", "myntra.", "seller.", "sellercentral", "mp.flipkart")
    for f in ALL_SOURCES:
        assert not [h for h in marketplaces if re.search(r"https?://[^\s'\"]*" + re.escape(h), code(f))], f


def test_no_http_verb_other_than_a_read_or_a_provider_search_exists_in_cmo_code():
    """Recommend-only (AC1): no PUT/PATCH/DELETE route, and the only outbound POST is Tavily's search endpoint."""
    for f in [BE / "api/v1/cmo.py", BE / "agents/ceo_hub_cmo.py"]:
        assert not re.search(r"\.(put|patch|delete)\(|router\.(put|patch|delete)\(", code(f)), f
    outbound_posts = [f.name for f in ALL_SOURCES if re.search(r"httpx\.(post|put|patch|delete)\(", code(f))]
    assert outbound_posts == ["tavily_client.py"]


def test_cmo_code_does_arithmetic_on_money_nowhere():
    """Money is an integer paise value that is stored and echoed, never computed on. Only these modules mention paise at all."""
    mentions = sorted(str(f.relative_to(PKG)).replace("\\", "/") for f in PKG.rglob("*.py") if "paise" in code(f))
    assert mentions == ["forbidden.py", "history/metrics.py", "history/report_import.py", "repositories/fact_repo.py", "service/catalog.py", "service/generate.py", "service/models.py", "trends/numeric.py"]
    for f in PKG.rglob("*.py"):
        tree = ast.parse(code(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)):
                names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
                assert not [n for n in names if "paise" in n or "price" in n or "rupee" in n], (f, ast.dump(node)[:80])


def test_the_long_running_cmo_routes_are_sync_handlers_so_they_run_in_the_threadpool_and_never_block_the_event_loop():
    tree = ast.parse(code(BE / "api/v1/cmo.py"))
    asyncs = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    assert asyncs == {"post_image", "_perf_file", "post_performance_import_preview", "post_performance_import", "post_product_images"}  # the uploads (photo, M8 report, M9 product images) read the body asynchronously and immediately hand the heavy work to run_in_threadpool
    assert "run_in_threadpool" in code(BE / "api/v1/cmo.py")


def test_the_tenant_is_never_read_from_a_request_body_anywhere_in_the_cmo_routes():
    src = code(BE / "api/v1/cmo.py")
    assert 'extra="forbid"' in src
    assert not re.search(r"body\.tenant|body\.member|tenant_id:\s*UUID", src)
    models = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ClassDef) and n.name.endswith("Body")]
    for m in models:
        fields = {t.target.id for t in m.body if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)}
        assert not {"tenant_id", "member_id", "user_id", "meter_code", "cap_value", "units"} & fields, (m.name, fields)


def test_provider_api_keys_never_appear_in_a_log_call_or_a_response_builder():
    for f in [*MS.rglob("*.py"), BE / "services/cmo_runtime.py", BE / "services/cmo_trends.py", BE / "api/v1/cmo.py"]:
        for line in code(f).splitlines():
            if re.search(r"logger\.\w+\(", line):
                assert not re.search(r"api_key|_key\b|tavily_key|youtube_key", line), (f.name, line.strip())


def test_the_cmo_services_do_not_import_the_engine_cfo_pi_or_ci_packages():
    forbidden = ("calc_engine", "cfo", "product_intelligence", "competitor_intelligence")
    for f in PKG.rglob("*.py"):
        for node in ast.walk(ast.parse(code(f))):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not [m for m in mods if m.split(".")[0] in forbidden], (f, mods)
