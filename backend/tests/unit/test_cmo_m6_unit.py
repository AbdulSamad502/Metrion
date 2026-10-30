"""CMO 3.0 M6 wiring (pure code): the complete listing is one closed CEO action with the right permission, meters and plan; "complete listing" requests reach it while the copy pack, titles and
questions keep their routes; the unverified-basis marker can only be set by the server; the handler's result carries what the existing result presentation needs."""

from __future__ import annotations

import pytest

from backend.api.v1 import cmo as cmo_api
from backend.ceo import classifier, cmo_delegation, input_session, intent_router, orchestrator, question_types
from backend.ceo.effects import ACTION_EFFECTS
from backend.ceo.plans import ACTIONS, PLAYBOOKS
from backend.services import cmo_listing

KEY = "cmo.generate_full_listing"


def decide(text):
    return intent_router.route(text, classifier.build_catalog(list(ACTIONS), list(PLAYBOOKS), question_types.descriptions()))


# ------------------------------------------------------------------ the closed action
def test_the_complete_listing_is_one_registered_delegated_grounded_action():
    assert KEY in ACTIONS and ACTIONS[KEY].session is True
    assert KEY in input_session.CMO_SESSIONS and KEY in cmo_delegation.DELEGATED_ACTIONS and KEY in orchestrator.GROUNDED_CMO_KEYS
    assert KEY in cmo_delegation.CI_INFORMED and KEY in cmo_delegation.IMAGE_FOLLOWUPS  # competitor themes may inform it (CEO-brokered); a photo may start it
    assert input_session.SESSIONS[KEY] is input_session.CMO_FULL_LISTING
    fx = ACTION_EFFECTS[KEY]
    assert fx.meters == ("cmo.generate_listing_copy", "cmo.generate_backend_terms") and fx.requires_approval  # a plan card the seller approves; the artefact meters the cap check reads
    assert "cmo.generate_hashtags" not in fx.meters  # hashtags are off unless asked


def test_the_registry_wires_the_handler_with_the_cmo_permission_and_metered_effect():
    from backend.auth.permissions import AGENT_CMO
    from backend.ceo.registry import build_default_registry

    spec = build_default_registry().get(KEY)
    assert spec.source == "CMO" and spec.effect.name == "GENERATE_METERED" and spec.writes_own_run is True and spec.required_permissions == ()  # agent.cmo is checked by the handler's own route guard
    assert AGENT_CMO
    assert "marketplace" in spec.slot_model.model_fields and "workflow" not in spec.slot_model.model_fields and "rules_basis" not in spec.slot_model.model_fields


def test_the_request_body_has_no_field_that_could_switch_the_unverified_basis_on():
    fields = set(cmo_api.FullListingBody.model_fields)
    assert {"marketplace", "approval_id", "seller_title", "include_hashtags", "request_key", "sku"} <= fields
    assert not {"workflow", "listing", "rules_basis", "unverified", "listing_unverified_rules_enabled", "constraint"} & fields
    assert cmo_api.FullListingBody.model_config.get("extra") == "forbid"
    assert cmo_api.FullListingBody.model_fields["include_hashtags"].default is False


# ------------------------------------------------------------------ routing
@pytest.mark.parametrize("text", ["create my complete Amazon listing", "write my full listing", "Generate a complete listing for my steel bottle", "prepare the entire listing for Flipkart",
                                  "make a full Amazon listing using option 2", "Create my complete Amazon listing using approved title option 2"])
def test_complete_listing_requests_reach_the_new_action(text):
    d = decide(text)
    assert d is not None and d.key == KEY, (text, d)


@pytest.mark.parametrize("text,key", [("write a listing copy pack for my bottle", "cmo.generate_listing_copy"), ("write the full listing copy for Amazon", "cmo.generate_listing_copy"),
                                      ("write 5 titles for my bottle on amazon", "cmo.generate_title_sets"), ("compare these titles", "cmo.analyze_titles")])
def test_other_requests_keep_their_routes(text, key):
    d = decide(text)
    assert d is not None and d.key == key, (text, d)


@pytest.mark.parametrize("text", ["what is a complete listing?", "how do I write a full listing", "show me my complete listing", "is my listing complete", "explain a full listing"])
def test_questions_and_reads_never_start_a_paid_plan(text):
    d = decide(text)
    assert d is None or d.key != KEY, (text, d)


# ------------------------------------------------------------------ the server-side marker
def test_the_workflow_marker_is_off_by_default_set_only_inside_the_server_context_and_always_reset():
    assert cmo_listing.workflow_context() is None
    with cmo_listing.full_listing_workflow():
        ctx = cmo_listing.workflow_context()
        assert ctx is not None and ctx.workflow == "FULL_LISTING" and ctx.keyword_vocab == ()
    assert cmo_listing.workflow_context() is None
    with pytest.raises(RuntimeError):
        with cmo_listing.full_listing_workflow():
            raise RuntimeError("boom")
    assert cmo_listing.workflow_context() is None  # an error inside never leaves the marker behind


def test_an_ordinary_intake_carries_no_listing_context():
    body = cmo_api.GroundedBody(request_key="k", marketplace="AMAZON", seller_title="t")
    assert cmo_api._intake(body, None).listing is None
    with cmo_listing.full_listing_workflow():
        assert cmo_api._intake(body, None).listing is not None


# ------------------------------------------------------------------ the handler's result shape for the CEO's existing presentation
def test_the_result_carries_one_flat_artefact_list_status_and_run_id():
    out = {"status": "PARTIAL", "copy": {"artefacts": [{"id": "1", "outputType": "LISTING_COPY", "status": "COMPLETE"}], "agentRunId": "run-1"},
           "backendTerms": {"artefacts": [{"id": "2", "outputType": "BACKEND_TERMS", "status": "FAILED"}]}, "hashtags": None, "card": None}
    flat = cmo_listing._flatten(dict(out))
    assert [a["id"] for a in flat["artefacts"]] == ["1", "2"] and flat["runStatus"] == "PARTIAL" and flat["agentRunId"] == "run-1"


def test_refusals_are_plain_and_carry_a_machine_code():
    e = cmo_listing.ListingRefused("NEEDS_FACTS", "Tell me: Brand.", missing=["Brand"])
    assert (e.code, e.status, e.missing, str(e)) == ("NEEDS_FACTS", 422, ("Brand",), "Tell me: Brand.")
    assert cmo_listing.ListingRefused("AUDIT_BLOCKED", "x", status=409).status == 409
