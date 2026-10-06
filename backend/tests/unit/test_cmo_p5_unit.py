"""P5 unit tests (no database): route surface, request validation, response allow-list, error mapping,
required configuration, and the structural billing boundaries."""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from slim_cmo import billing
from slim_cmo.service.errors import GroundingRequired, InvalidApproval, InvalidConfirmation, NotFound
from slim_cmo.service.models import StoredGeneration, StoredOptionDetail
from slim_cmo.types import GenerationStatus as S
from slim_cmo.types import Marketplace as M
from slim_cmo.types import OutputType as O

from backend import config
from backend.api.v1 import cmo
from backend.services import cmo_actions, cmo_response, cmo_runtime
from backend.services.cmo_actions import QuotaDenied, RequestInProgress
from backend.services.cmo_runtime import CmoNotConfigured

NOW = datetime(2026, 10, 4, tzinfo=UTC)

EXPECTED_ROUTES = {
    "/api/v1/cmo/title-sets", "/api/v1/cmo/listing-copy", "/api/v1/cmo/description", "/api/v1/cmo/bullets",
    "/api/v1/cmo/keywords", "/api/v1/cmo/backend-terms", "/api/v1/cmo/hashtags", "/api/v1/cmo/catalog-answers",
    "/api/v1/cmo/title-approvals", "/api/v1/cmo/image-hints/confirm",
    "/api/v1/cmo/images", "/api/v1/cmo/image-analyses",  # P6: explicit zero-unit image actions
    "/api/v1/cmo/niche-terms/suggest", "/api/v1/cmo/niche-terms/confirm", "/api/v1/cmo/niche-terms",  # P7d: zero-unit niche flow
    "/api/v1/cmo/market-trends/preview", "/api/v1/cmo/market-trends", "/api/v1/cmo/market-trends/{generation_id}",  # P7f
}
READ_ONLY_ROUTES = {"/api/v1/cmo/niche-terms", "/api/v1/cmo/market-trends/{generation_id}"}  # GET-only; /market-trends is POST + GET


class TestRouteSurface:
    def test_exactly_the_registered_actions_exist_all_post_and_nothing_else(self):
        routes: dict[str, set[str]] = {}
        for r in cmo.router.routes:  # type: ignore[attr-defined]
            routes.setdefault(r.path, set()).update(r.methods)
        assert set(routes) == EXPECTED_ROUTES
        assert all(m == ({"GET"} if path in READ_ONLY_ROUTES else {"GET", "POST"} if path == "/api/v1/cmo/market-trends" else {"POST"}) for path, m in routes.items())

    def test_no_marketplace_write_back_route_exists_anywhere_in_the_app(self, monkeypatch):
        for k in ("CLERK_SECRET_KEY", "CLERK_WEBHOOK_SECRET", "CLERK_JWT_KEY", "FRONTEND_ORIGIN"):
            monkeypatch.setenv(k, "placeholder" if k != "FRONTEND_ORIGIN" else "http://localhost:3000")
        for fn in (config.clerk_secret_key, config.clerk_webhook_secret, config.clerk_jwt_key, config.frontend_origin):
            fn.cache_clear()
        from backend.main import create_app

        spec = create_app().openapi()["paths"]
        paths = [(p, sorted(m.upper() for m in methods)) for p, methods in spec.items()]
        cmo_paths = [p for p, _ in paths if p.startswith("/api/v1/cmo")]
        assert set(cmo_paths) == EXPECTED_ROUTES
        banned = ("publish", "update", "sync", "push", "listing-write", "marketplace", "write-back", "submit")
        assert not [p for p in cmo_paths if any(b in p for b in banned)]
        assert not [p for p, methods in paths if p.startswith("/api/v1/cmo") and set(methods) & {"PUT", "PATCH", "DELETE"}]

    def test_every_route_requires_the_agent_cmo_permission(self):
        for route in cmo.router.routes:  # type: ignore[attr-defined]
            deps = [d.call for d in route.dependant.dependencies]
            assert deps, route.path


def code_identifiers(obj) -> set[str]:
    """Every identifier, attribute name and imported module in the CODE of a function/module - docstrings and
    comments excluded, so a test cannot be tripped (or satisfied) by prose."""
    src = inspect.getsource(obj) if not isinstance(obj, str) else obj
    tree = ast.parse(textwrap.dedent(src))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.update(node.module.lower().split("."))
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.update(a.name.lower().split("."))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 60 and "\n" not in node.value:
            names.add(node.value)  # short string literals (e.g. a default "localhost")
    return names


BASE = {"request_key": "k1"}


class TestRequestValidation:
    @pytest.mark.parametrize("field", ["tenant_id", "member_id", "user_id", "meter_code", "cap_value", "agent_code", "units", "billable_units"])
    def test_client_supplied_identity_meter_or_cap_fields_are_rejected(self, field):
        with pytest.raises(ValidationError):
            cmo.TitleSetsBody(**BASE, marketplaces=["AMAZON"], **{field: "x"})
        with pytest.raises(ValidationError):
            cmo.ApprovalBody(generation_id=uuid.uuid4(), option_id=uuid.uuid4(), **{field: "x"})
        with pytest.raises(ValidationError):
            cmo.ConfirmHintBody(analysis_id=uuid.uuid4(), attribute_name="color", sku="S", **{field: "x"})

    @pytest.mark.parametrize("marketplaces", [[], ["AMAZON"] * 0, ["AMAZON", "FLIPKART", "MEESHO", "AMAZON"], ["EBAY"], "AMAZON", None])
    def test_marketplaces_are_one_to_three_known_values(self, marketplaces):
        with pytest.raises(ValidationError):
            cmo.TitleSetsBody(**BASE, marketplaces=marketplaces)

    @pytest.mark.parametrize("price", [499.5, -1, True, "100", 1.0])
    def test_target_price_must_be_a_non_negative_integer_of_paise(self, price):
        with pytest.raises(ValidationError):
            cmo.TitleSetsBody(**BASE, marketplaces=["AMAZON"], target_price_paise=price)
        assert cmo.TitleSetsBody(**BASE, marketplaces=["AMAZON"], target_price_paise=0).target_price_paise == 0

    def test_required_and_bounded_fields(self):
        for bad in ({}, {"request_key": ""}, {"request_key": "x" * 129}):
            with pytest.raises(ValidationError):
                cmo.TitleSetsBody(**bad, marketplaces=["AMAZON"])
        with pytest.raises(ValidationError):
            cmo.GroundedBody(**BASE)  # marketplace is required
        with pytest.raises(ValidationError):
            cmo.CatalogBody(**BASE, questions=[])
        with pytest.raises(ValidationError):
            cmo.CatalogBody(**BASE, questions=["PRICE"])  # a closed vocabulary
        with pytest.raises(ValidationError):
            cmo.TitleSetsBody(**BASE, marketplaces=["AMAZON"], attributes=[{"name": "", "value": "x"}])


def _row(output_type, *, status=S.COMPLETE, structured=None, options=(), marketplace=M.AMAZON, reason=None, text=None):
    return StoredGeneration(uuid.uuid4(), output_type, marketplace, status, reason, text, structured, uuid.uuid4(), NOW, tuple(options))


LEAKY = {
    "provenance": {"fact_ids": ["f1"]}, "excluded_facts": ["TARGET_PRICE:price"], "prompt": "SECRET PROMPT", "raw_model_output": "RAW",
    "api_key": "sk-123", "format_constraint_ref": "00000000-0000-0000-0000-000000000001",
    "constraint": {"source_url": "https://rules.example/x", "verified_at": "2026-10-01T00:00:00+00:00", "version": 2,
                   "format_constraint_ref": "internal-id"},
}


class TestResponseAllowList:
    def test_title_set_returns_options_and_the_cited_rule_and_nothing_internal(self):
        opt = StoredOptionDetail(uuid.uuid4(), 1, "AquaKeep Bottle", 15)
        row = _row(O.TITLE_SET, structured={**LEAKY, "expected_option_count": 3, "delivered_option_count": 1, "short": True, "short_label": "short", "unverified_limits": ["title_max_chars"], "count_rule": "UTF16_CODE_UNITS"}, options=[opt])
        out = cmo_response.artefact_json(row, reused=False)
        assert out["options"] == [{"id": str(opt.id), "rank": 1, "text": "AquaKeep Bottle", "charCount": 15}]
        assert out["constraint"] == {"sourceUrl": "https://rules.example/x", "verifiedAt": "2026-10-01T00:00:00+00:00", "version": 2}
        assert out["short"] is True and out["unverifiedLimits"] == ["title_max_chars"]
        blob = json.dumps(out)
        for forbidden in ("SECRET PROMPT", "RAW", "sk-123", "fact_ids", "TARGET_PRICE", "internal-id", "provenance", "00000000-0000-0000-0000-000000000001"):
            assert forbidden not in blob

    def test_failed_artefacts_expose_only_a_code_a_plain_reason_and_screened_fact_names(self):
        row = _row(O.LISTING_COPY, status=S.FAILED, reason="needs more confirmed product facts: material",
                   structured={"failure_code": "NEEDS_FACTS", "missing_facts": ["material"], "detail": {"violations": {"TOO_LONG": 2}}, **LEAKY})
        out = cmo_response.artefact_json(row, reused=False)
        assert out["failure"] == {"code": "NEEDS_FACTS", "reason": "needs more confirmed product facts: material", "missingFacts": ["material"]}
        assert "detail" not in json.dumps(out) and "violations" not in json.dumps(out) and "SECRET" not in json.dumps(out)

    @pytest.mark.parametrize("otype,struct,keys", [
        (O.LISTING_COPY, {"description": "d", "bullets": ["b"], "keywords": ["k"], "description_type": "plain"}, {"description", "bullets", "keywords"}),
        (O.DESCRIPTION, {"description": "d"}, {"description"}), (O.BULLETS, {"bullets": ["b"]}, {"bullets"}),
        (O.KEYWORDS, {"keywords": ["k"]}, {"keywords"}), (O.BACKEND_TERMS, {"backend_terms": ["t"], "joined": "t", "byte_count": 1, "max_bytes": 50}, {"terms", "byteCount"}),
        (O.HASHTAGS, {"hashtags": ["#a"], "label": "marketing suggestions", "max_set_size": 3}, {"hashtags", "label", "listingField"}),
    ])
    def test_each_artefact_type_has_its_own_explicit_shape(self, otype, struct, keys):
        out = cmo_response.artefact_json(_row(otype, structured={**LEAKY, **struct}), reused=True)
        assert keys <= set(out) and out["reused"] is True and "provenance" not in json.dumps(out)

    def test_hashtags_are_never_a_listing_field(self):
        out = cmo_response.artefact_json(_row(O.HASHTAGS, marketplace=None, structured={"hashtags": ["#a"], "label": "x"}), reused=False)
        assert out["listingField"] is False

    def test_catalog_answers_drop_source_fact_ids(self):
        attr = {"attribute": "COLOR", "value": "red", "basis": "SELLER_PROVIDED", "claim_eligible": True, "requires_seller_input": False,
                "note": "n", "source_fact_id": "fact-123", "suggestion": None, "estimate": None, "superseded_values": [], "conflicting_observation": None}
        out = cmo_response.artefact_json(_row(O.CATALOG_ANSWER, marketplace=None, structured={"attributes": [attr], "basis_counts": {"SELLER_PROVIDED": 1}, "disclaimer": "d", **LEAKY}), reused=False)
        assert out["attributes"][0]["basis"] == "SELLER_PROVIDED" and "fact-123" not in json.dumps(out)

    def test_a_row_with_no_structured_data_does_not_crash(self):
        assert cmo_response.artefact_json(_row(O.TITLE_SET, structured=None), reused=False)["status"] == "COMPLETE"
        assert cmo_response.artefact_json(_row(O.BULLETS, status=S.FAILED, structured=None), reused=False)["failure"]["code"] == "UNKNOWN"


class TestErrorMapping:
    @pytest.mark.parametrize("exc,status", [
        (billing.InvalidRequest(billing.RequestError.BAD_REQUEST_KEY, "x"), 422), (GroundingRequired("x"), 422), (InvalidApproval("x"), 422),
        (InvalidConfirmation("x"), 422), (NotFound("secret table name"), 404), (QuotaDenied({"reason": "OVER_CAP"}), 402),
        (RequestInProgress(), 409), (CmoNotConfigured(), 503),
    ])
    def test_status_mapping(self, exc, status):
        def boom():
            raise exc
        with pytest.raises(HTTPException) as caught:
            cmo._guarded(boom)
        assert caught.value.status_code == status

    def test_not_found_never_echoes_what_was_missing(self):
        with pytest.raises(HTTPException) as caught:
            cmo._guarded(lambda: (_ for _ in ()).throw(NotFound("approval 123 for tenant B")))
        assert caught.value.detail == "Not found"

    def test_an_unexpected_exception_is_a_generic_500_with_no_leakage(self):
        def boom():
            raise RuntimeError("psycopg.errors.UndefinedTable: relation secret_tbl; password=hunter2; prompt=SECRET")
        with pytest.raises(HTTPException) as caught:
            cmo._guarded(boom)
        assert caught.value.status_code == 500 and caught.value.detail == {"code": "INTERNAL_ERROR"}

    def test_quota_denial_body_carries_the_existing_402_fields(self):
        payload = {"reason": "OVER_CAP", "meterCode": "cmo.generate_title_sets", "evaluationBasis": "OVER_CAP", "cap": 1}
        with pytest.raises(HTTPException) as caught:
            cmo._guarded(lambda: (_ for _ in ()).throw(QuotaDenied(payload)))
        assert caught.value.detail == payload


class TestRequiredConfiguration:
    NAMES = ("CMO_LLM_MODEL", "CMO_OLLAMA_HOST", "CMO_LLM_TIMEOUT_SECONDS", "CMO_QUOTA_RESERVATION_TTL_SECONDS")
    FNS = (config.cmo_llm_model, config.cmo_ollama_host, config.cmo_llm_timeout_seconds, config.cmo_quota_reservation_ttl_seconds)

    @pytest.fixture(autouse=True)
    def clean(self, monkeypatch):
        for n in self.NAMES:
            monkeypatch.delenv(n, raising=False)
        for f in self.FNS:
            f.cache_clear()
        yield
        for f in self.FNS:
            f.cache_clear()

    @pytest.mark.parametrize("fn", FNS)
    def test_nothing_has_a_default(self, fn):
        with pytest.raises(config.MissingConfig):
            fn()

    def test_no_hidden_model_or_host_literals_remain_in_cmo_config(self):
        ids = code_identifiers(config.cmo_llm_model) | code_identifiers(config.cmo_ollama_host)
        assert not [i for i in ids if "qwen" in i or "localhost" in i or "11434" in i]
        assert "get" not in ids  # `os.environ.get(NAME, default)` would be a hidden default; only `_required(NAME)` is used

    @pytest.mark.parametrize("bad", ["abc", "0", "-1", "2.5", " ", "1e3"])
    def test_integers_are_strict_and_positive(self, monkeypatch, bad):
        monkeypatch.setenv("CMO_LLM_TIMEOUT_SECONDS", bad)
        monkeypatch.setenv("CMO_QUOTA_RESERVATION_TTL_SECONDS", bad)
        with pytest.raises((ValueError, config.MissingConfig)):
            config.cmo_llm_timeout_seconds()
        with pytest.raises((ValueError, config.MissingConfig)):
            config.cmo_quota_reservation_ttl_seconds()

    def test_valid_values_are_read_as_ints(self, monkeypatch):
        monkeypatch.setenv("CMO_LLM_TIMEOUT_SECONDS", "120")
        monkeypatch.setenv("CMO_QUOTA_RESERVATION_TTL_SECONDS", "300")
        assert (config.cmo_llm_timeout_seconds(), config.cmo_quota_reservation_ttl_seconds()) == (120, 300)

    def test_build_runtime_without_configuration_is_cmo_not_configured(self):
        with pytest.raises(CmoNotConfigured):
            cmo_runtime.build_runtime()

    def test_build_runtime_with_configuration_wires_the_services(self, monkeypatch):
        monkeypatch.setenv("CMO_LLM_MODEL", "some-model")
        monkeypatch.setenv("CMO_OLLAMA_HOST", "http://ollama.test:11434")
        monkeypatch.setenv("CMO_LLM_TIMEOUT_SECONDS", "30")
        for f in self.FNS:
            f.cache_clear()
        rt = cmo_runtime.build_runtime()
        assert rt.generation is not None and rt.approvals is not None and rt.catalog is not None


class TestStructuralBillingBoundaries:
    def test_billing_never_reads_billable_units_only_persisted_status(self):
        ids = code_identifiers(cmo_actions)
        assert "billable_units" not in ids
        assert "status" in code_identifiers(cmo_actions._settle) and "COMPLETE" in code_identifiers(cmo_actions._settle)

    def test_zero_unit_routes_never_touch_admission_reservation_or_metering(self):
        for fn in (cmo.post_title_approval, cmo.post_confirm_image_hint, cmo.post_image, cmo.post_image_analysis):
            src = inspect.getsource(fn)
            ids = code_identifiers(fn)
            for banned in ("run_billable", "record_metered_event", "cmo_quota_repo", "_admit", "_settle", "resolve_cmo_entitlement"):
                assert banned not in ids, (fn.__name__, banned)

    def test_settlement_is_only_reachable_from_the_billable_path(self):
        assert "_settle" not in code_identifiers(cmo_actions.record_free_run)
        assert "_settle" in code_identifiers(cmo_actions.run_billable)
        assert "_settle" not in code_identifiers(cmo)

    def test_the_p3_p4_services_know_nothing_about_http_entitlement_or_metering(self):
        import pathlib

        import slim_cmo

        root = pathlib.Path(slim_cmo.__file__).parent
        for path in list((root / "service").glob("*.py")) + list((root / "generation").glob("*.py")) + list((root / "catalog").glob("*.py")):
            ids = {i.lower() for i in code_identifiers(path.read_text(encoding="utf-8"))}
            for banned in ("fastapi", "httpexception", "record_metered_event", "metered_event", "cmo_quota_repo", "entitlement"):
                assert banned not in ids, (path.name, banned)

    def test_tenant_and_user_come_only_from_the_authenticated_context(self):
        assert "tenant_id" not in {f for f in cmo.ProductBody.model_fields}
        for fn in (cmo.post_title_sets, cmo.post_catalog_answers, cmo.post_title_approval, cmo.post_confirm_image_hint):
            assert "ctx" in inspect.signature(fn).parameters
