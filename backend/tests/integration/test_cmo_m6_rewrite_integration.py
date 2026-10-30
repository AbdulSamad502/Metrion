"""CMO 3.0 M6 model rewrite of ONE section (spec 6.18.7, owner decision Q26; acceptance N-15b, N-15c) against a real Postgres, through the real API: exactly one unit per delivered section on the
proven billing path, a NEW immutable version that passed the seller-edit gates and was audited, every other section and the title untouched, an earlier approval never carried over, and failures that
leave nothing billed and nothing half-saved. A fake provider answers from a script; nothing leaves the machine."""

from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import text

from slim_cmo.service.models import NewFact
from slim_cmo.types import SellerFactType as F
from tests.integration.test_cmo_api import AMAZON, FLIPKART, _erase_cmo_rows, _login, ctx_engine, env, fake_clerk, seed_cap  # noqa: F401
from tests.integration.test_cmo_m6_integration import FLAG_ON, SKU, TITLE, ListingProvider, body, gens, ru_env

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

GOOD = "Wide opening makes filling easy."
METER = "cmo.generate_listing_copy"


class RewriteProvider(ListingProvider):
    """The listing provider plus a scripted answer for the rewrite prompt (identified by its own instruction); a script that runs out answers with something that is not JSON."""

    def __init__(self, rewrites=(), boom: bool = False, **kw) -> None:
        super().__init__(**kw)
        self.rewrites, self.boom, self.rewrite_calls = list(rewrites), boom, 0

    def complete(self, *, model: str, prompt: str) -> str:
        if "rewrite ONLY the" not in prompt:
            return super().complete(model=model, prompt=prompt)
        with self._lock:
            self.calls += 1
            self.rewrite_calls += 1
            self.prompts.append(prompt)
        if self.boom:
            raise RuntimeError("boom-secret-token http://internal-ollama:11434")
        return json.dumps({"text": self.rewrites.pop(0)}) if self.rewrites else "not json"


def rw_body(gid, key="rw1", **extra):
    return {"request_key": key, "generation_id": gid, "target": "bullet", "bullet_number": 3, "topic": "wide opening", "sku": SKU, **extra}


def listing(env, rewrites=(), **kw):
    """A saved complete listing on the unverified basis and the seller's confirmed 'Opening: wide' fact. Returns its LISTING card."""
    ru_env(env, RewriteProvider(rewrites, **kw))
    env.runtime.store.save_facts(env.tenant, env.user_id, [NewFact(F.ATTRIBUTE, SKU, "Opening", "wide")])
    out = env.post("full-listing", body()).json()
    assert out["status"] == "COMPLETE", out
    return out["card"]


def card_of(env, gid, headers=None):
    return env.client().get(f"/api/v1/cmo/listing/{gid}", headers=headers or env.headers)


def rewrite(env, gid, key="rw1", headers=None, **extra):
    return env.post("listing-rewrite", rw_body(gid, key, **extra), headers=headers)


# ---------------------------------------------------------------- a valid rewrite
def test_a_valid_rewrite_costs_one_unit_makes_a_new_version_and_changes_only_that_section(env):
    old = listing(env, [GOOD])
    gid, events, rows, audits = old["generationId"], len(env.events()), len(gens(env)), env.n("cmo_listing_audit")
    r = rewrite(env, gid)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "COMPLETE" and out["unitsBilled"] == 1 and out["sourceGenerationId"] == gid
    new = out["card"]
    assert new["generationId"] != gid and new["revisionOf"] == gid and new["kind"] == "LISTING" and new["rulesBasis"] == "UNVERIFIED"
    assert new["sections"]["bullets"][2] == GOOD and new["sections"]["bullets"][:2] == old["sections"]["bullets"][:2]
    assert new["sections"]["description"] == old["sections"]["description"] and new["sections"]["title"] == TITLE and new["sections"]["keywords"] == old["sections"]["keywords"]
    assert new["sections"]["backend_terms"] == old["sections"]["backend_terms"]
    assert [e[1] for e in env.events()][-1] == METER and len(env.events()) == events + 1  # exactly one metered unit
    assert len(gens(env)) == rows + 1 and env.n("cmo_listing_audit") == audits + 1  # one new immutable version, audited as itself
    saved = env.q("SELECT output_structured FROM cmo_generation WHERE id = :g", g=new["generationId"])[0][0]
    assert saved["revision"]["by"] == "MODEL_REWRITE" and saved["revision"]["section"] == "BULLET 3" and saved["previous"]["bullets"][2] == "Easy to carry"
    assert card_of(env, gid).json()["sections"]["bullets"][2] == "Easy to carry"  # the earlier version is untouched
    assert new["audit"]["verdict"] != "BLOCKED" and {c["id"]: c["status"] for c in new["audit"]["checks"]}["A13"] == "NOT_ASSESSED"


def test_the_description_can_be_rewritten_and_the_bullets_are_untouched(env):
    old = listing(env, ["The AquaNest water bottle has a wide opening and holds 1 litre."])
    out = rewrite(env, old["generationId"], target="description", bullet_number=None).json()
    assert out["status"] == "COMPLETE" and out["unitsBilled"] == 1
    assert out["card"]["sections"]["description"].startswith("The AquaNest water bottle has a wide opening") and out["card"]["sections"]["bullets"] == old["sections"]["bullets"]


def test_the_prompt_carries_only_the_one_section_the_topic_the_title_and_confirmed_facts(env):
    old = listing(env, [GOOD])
    rewrite(env, old["generationId"])
    prompt = env.provider.prompts[-1]
    assert '"part_to_rewrite": "bullet 3"' in prompt and '"must_mention": "wide opening"' in prompt and f'"approved_title": "{TITLE}"' in prompt
    assert "Easy to carry" in prompt and "Stainless steel body" not in prompt  # only the section being rewritten is shown


# ---------------------------------------------------------------- refused before any charge
@pytest.mark.parametrize("extra,status,code", [
    ({"topic": "keeps drinks cold"}, 422, "TOPIC_NOT_CONFIRMED"),  # nothing the seller confirmed says so
    ({"topic": "wide steel"}, 422, "TOPIC_NOT_CONFIRMED"),  # words from two different details are not one confirmed fact
    ({"bullet_number": 9}, 422, "BULLET_OUT_OF_RANGE"),
    ({"sku": "someone-elses-bottle"}, 409, "WRONG_PRODUCT"),
    ({"marketplace": FLIPKART}, 409, "WRONG_MARKETPLACE"),
])
def test_a_rewrite_that_cannot_be_done_is_refused_in_plain_words_before_any_charge(env, extra, status, code):
    old = listing(env, [GOOD])
    calls, events, rows = env.provider.calls, len(env.events()), len(gens(env))
    r = rewrite(env, old["generationId"], **extra)
    assert r.status_code == status and r.json()["detail"]["code"] == code and r.json()["detail"]["detail"], r.text
    assert (env.provider.calls, len(env.events()), len(gens(env))) == (calls, events, rows) and env.reservations().count("RESERVED") == 0


@pytest.mark.parametrize("bad", [
    {"target": "title", "bullet_number": None}, {"target": "keywords", "bullet_number": None}, {"target": "bullet", "bullet_number": None},
    {"target": "description", "bullet_number": 2}, {"topic": "x"}, {"topic": "y" * 81}, {"tenant_id": str(uuid.uuid4())}, {"workflow": "FULL_LISTING"}, {"rules_basis": "UNVERIFIED"},
    {"units": 0}, {"meter_code": "none"},
])
def test_the_request_shape_is_closed_no_other_section_no_client_tenant_workflow_or_meter(env, bad):
    old = listing(env, [GOOD])
    calls = env.provider.calls
    r = rewrite(env, old["generationId"], **bad)
    assert r.status_code == 422 and env.provider.calls == calls and len(env.events()) == 2


def test_a_missing_or_unknown_listing_is_a_404_and_nothing_runs(env):
    listing(env, [GOOD])
    calls, events = env.provider.calls, len(env.events())
    r = rewrite(env, str(uuid.uuid4()))
    assert r.status_code == 404 and (env.provider.calls, len(env.events())) == (calls, events)


def test_a_title_set_row_is_not_a_listing_and_cannot_be_rewritten(env):
    listing(env, [GOOD])
    t = env.post("title-sets", {"request_key": "t9", "sku": SKU, "brand": "AquaNest", "marketplaces": [AMAZON]})
    ids = [a["id"] for a in t.json().get("artefacts", [])]
    for i in ids:
        assert rewrite(env, i, key="ts").status_code in (404, 409, 422)


# ---------------------------------------------------------------- the gates
def test_a_rewrite_that_makes_an_unsupported_claim_is_saved_as_a_failed_row_and_uses_nothing(env):
    old = listing(env, ["Keeps drinks cold with a wide opening."])
    events, audits = len(env.events()), env.n("cmo_listing_audit")
    out = rewrite(env, old["generationId"]).json()
    assert out["status"] == "FAILED" and out["unitsBilled"] == 0 and out["card"] is None and out["artefacts"][0]["status"] == "FAILED"
    assert len(env.events()) == events and env.n("cmo_listing_audit") == audits
    failed = env.q("SELECT status, output_text, output_structured FROM cmo_generation WHERE request_key = 'rw1'")
    assert len(failed) == 1 and failed[0][0] == "FAILED" and failed[0][1] is None and "bullets" not in (failed[0][2] or {})  # nothing partial is kept
    assert "Keeps drinks cold" not in json.dumps(out)  # the rejected text is never echoed back
    assert card_of(env, old["generationId"]).json()["sections"]["bullets"][2] == "Easy to carry"
    assert env.reservations().count("RESERVED") == 0


@pytest.mark.parametrize("bad", ["A wide opening, 12 years of use.", "Wide opening in plastic.", "Easy to carry.", ""])
def test_unsupported_numbers_contradictions_missing_topic_and_empty_text_never_become_a_version(env, bad):
    old = listing(env, [bad])
    rows = len(gens(env, "status = 'COMPLETE'"))
    out = rewrite(env, old["generationId"], key="rwbad").json()
    assert out["status"] == "FAILED" and out["unitsBilled"] == 0 and len(gens(env, "status = 'COMPLETE'")) == rows and len(env.events()) == 2


def test_a_model_failure_leaves_a_failed_row_no_unit_and_leaks_nothing(env):
    old = listing(env, [], boom=False)
    env.provider.boom = True
    events = len(env.events())
    r = rewrite(env, old["generationId"])
    assert r.status_code == 200 and r.json()["status"] == "FAILED" and r.json()["unitsBilled"] == 0 and len(env.events()) == events
    assert "boom-secret" not in r.text and "internal-ollama" not in r.text
    assert env.reservations().count("RESERVED") == 0


def test_a_failed_request_key_can_be_retried_and_then_costs_exactly_one_unit(env):
    old = listing(env, ["Keeps drinks cold with a wide opening.", GOOD])
    assert rewrite(env, old["generationId"]).json()["status"] == "FAILED"
    events = len(env.events())
    retry = rewrite(env, old["generationId"]).json()
    assert retry["status"] == "COMPLETE" and retry["unitsBilled"] == 1 and len(env.events()) == events + 1


# ---------------------------------------------------------------- billing and idempotency
def test_a_repeated_request_is_served_free_with_no_second_call_version_or_unit(env):
    old = listing(env, [GOOD, "Some other wide opening text."])
    first = rewrite(env, old["generationId"]).json()
    calls, events, rows = env.provider.calls, len(env.events()), len(gens(env))
    again = rewrite(env, old["generationId"])
    assert again.status_code == 200 and again.json()["unitsBilled"] == 0 and env.provider.calls == calls and len(env.events()) == events and len(gens(env)) == rows
    assert again.json()["card"]["generationId"] == first["card"]["generationId"]


def test_a_different_key_is_a_new_request_and_a_new_version(env):
    old = listing(env, [GOOD, "A wide opening helps with ice."])
    a = rewrite(env, old["generationId"], key="rwA").json()
    b = rewrite(env, old["generationId"], key="rwB").json()
    assert a["unitsBilled"] == 1 and b["unitsBilled"] == 1 and a["card"]["generationId"] != b["card"]["generationId"]
    assert len(env.events()) == 4 and env.n("cmo_generation", "output_structured ->> 'revision_of' = :g", g=old["generationId"]) == 2


def test_an_exhausted_cap_denies_the_rewrite_with_nothing_run_and_nothing_written(env):
    old = listing(env, [GOOD])
    seed_cap(env.engine, METER, 1)  # the complete listing already used the one listing-copy unit
    calls, rows = env.provider.calls, len(gens(env))
    r = rewrite(env, old["generationId"])
    assert r.status_code == 402 and r.json()["detail"]["reason"] == "OVER_CAP" and r.json()["detail"]["remaining"] == 0
    assert env.provider.calls == calls and len(gens(env)) == rows and len(env.events()) == 2


def test_a_failure_after_the_version_is_saved_never_bills_twice_and_the_retry_returns_the_same_version(env):
    from backend.services import cmo_listing

    old = listing(env, [GOOD, "must never be asked for"])
    real = cmo_listing.build_card

    def boom(*a, **k):
        raise RuntimeError("audit store down")

    env.monkeypatch.setattr(cmo_listing, "build_card", boom)
    r = rewrite(env, old["generationId"])
    assert r.status_code == 500 and r.json()["detail"]["code"] == "INTERNAL_ERROR" and "audit store down" not in r.text
    assert len(env.events()) == 3 and len(gens(env, "output_structured ->> 'revision_of' IS NOT NULL")) == 1  # delivered and billed once
    env.monkeypatch.setattr(cmo_listing, "build_card", real)
    calls = env.provider.calls
    retry = rewrite(env, old["generationId"])
    assert retry.status_code == 200 and retry.json()["unitsBilled"] == 0 and env.provider.calls == calls and len(env.events()) == 3
    assert retry.json()["card"]["sections"]["bullets"][2] == GOOD


# ---------------------------------------------------------------- versions and approvals
def test_an_approval_of_the_earlier_version_does_not_carry_to_the_rewrite(env):
    old = listing(env, [GOOD])
    gid = old["generationId"]
    assert env.client().post(f"/api/v1/cmo/listing/{gid}/approve", headers=env.headers).status_code == 200
    new = rewrite(env, gid).json()["card"]
    assert new["states"]["approvedForUse"]["done"] is False
    assert card_of(env, gid).json()["states"]["approvedForUse"]["done"] is True  # the earlier approval stays exactly as it was
    assert env.n("cmo_result_usage_event", "event_kind = 'APPROVED'") == 1
    assert env.client().post(f"/api/v1/cmo/listing/{new['generationId']}/approve", headers=env.headers).status_code == 200
    assert env.n("cmo_result_usage_event", "event_kind = 'APPROVED'") == 2 and len(env.events()) == 3  # approving costs nothing


def test_a_rewrite_of_a_rewrite_keeps_the_lineage_and_every_earlier_version(env):
    old = listing(env, [GOOD, "Wide opening, easy to clean by hand."])
    v2 = rewrite(env, old["generationId"], key="v2").json()["card"]
    v3 = rewrite(env, v2["generationId"], key="v3", bullet_number=2).json()["card"]
    assert v3["revisionOf"] == v2["generationId"] and v3["sections"]["bullets"][2] == GOOD and v3["sections"]["bullets"][1] != old["sections"]["bullets"][1]
    assert card_of(env, old["generationId"]).json()["sections"]["bullets"] == old["sections"]["bullets"]
    assert card_of(env, v2["generationId"]).json()["sections"]["bullets"][1] == old["sections"]["bullets"][1]


# ---------------------------------------------------------------- security
def test_another_tenant_cannot_rewrite_read_or_bill_against_my_listing(env):
    old = listing(env, [GOOD])
    other, headers = env.other_tenant()
    calls = env.provider.calls
    r = rewrite(env, old["generationId"], headers=headers)
    assert r.status_code == 404 and env.provider.calls == calls
    assert env.n("cmo_generation", tenant=other) == 0 and env.n("metered_event", tenant=other) == 0 and env.n("cmo_listing_audit", tenant=other) == 0
    assert env.n("cmo_generation", "output_structured ->> 'revision_of' IS NOT NULL") == 0  # mine are untouched


def test_the_same_request_key_under_two_tenants_never_mixes_results(env):
    old = listing(env, [GOOD])
    mine = rewrite(env, old["generationId"], key="shared").json()
    other, headers = env.other_tenant()
    r = rewrite(env, mine["card"]["generationId"], key="shared", headers=headers)  # the other tenant has no listing, so it has nothing to rewrite under any key
    assert r.status_code == 404 and env.n("cmo_generation", tenant=other) == 0


def test_without_the_cmo_permission_or_without_a_login_nothing_runs(env):
    from backend.auth.permissions import PARTNER_ROLE

    old = listing(env, [GOOD])
    denied, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={})
    calls, events = env.provider.calls, len(env.events())
    r = rewrite(env, old["generationId"], headers=denied)
    assert r.status_code == 403 and "agent.cmo" in json.dumps(r.json())
    assert env.client().post("/api/v1/cmo/listing-rewrite", json=rw_body(old["generationId"])).status_code in (401, 403)
    assert (env.provider.calls, len(env.events())) == (calls, events)


def test_a_client_cannot_use_the_rewrite_route_to_reach_the_unverified_basis_or_the_flag(env):
    ru_env(env, RewriteProvider([GOOD]), config={**FLAG_ON, "listing_unverified_rules_enabled": False})
    env.runtime.store.save_facts(env.tenant, env.user_id, [NewFact(F.ATTRIBUTE, SKU, "Opening", "wide")])
    r = rewrite(env, str(uuid.uuid4()), listing={"workflow": "FULL_LISTING"})
    assert r.status_code == 422
    assert env.provider.calls == 0 and gens(env) == []
