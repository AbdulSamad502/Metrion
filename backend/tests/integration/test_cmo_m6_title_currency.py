"""CMO 3.0 M6 N-15d against a real Postgres, through the real API: a saved complete listing is flagged "built from a previous title" only AFTER the seller approves a different title for the same
product and marketplace. An unapproved title change flags nothing; history is never edited, relabelled, regenerated or invalidated; a typed or missing title is UNKNOWN; tenants are isolated."""

from __future__ import annotations

import json
import os

import pytest
from tests.integration.test_cmo_api import AMAZON, FLIPKART, _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import NAME, SKU, ListingProvider, body, facts, gens

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

T1 = "AquaNest 1 Litre Stainless Steel Water Bottle"
T2 = "AquaNest Stainless Steel Water Bottle 1 Litre Silver"
T3 = "AquaNest Steel Bottle 1 Litre"


class TitleProvider(ListingProvider):
    """Writes three distinct title options for a title prompt, and the usual pack / terms otherwise."""

    def complete(self, *, model: str, prompt: str) -> str:
        shape = prompt.split("Reply shape:")[1].split("\n")[0]
        if '"titles"' in shape:
            with self._lock:
                self.calls += 1
            return json.dumps({"titles": [T1, T2, T3]})
        return super().complete(model=model, prompt=prompt)


def title_set(env, key, mp=AMAZON):
    r = env.post("title-sets", {"request_key": key, "sku": SKU, "brand": "AquaNest", "marketplaces": [mp]})
    assert r.status_code == 200 and r.json()["artefacts"][0]["status"] == "COMPLETE", r.text
    return r.json()["artefacts"][0]["id"]


def approve(env, set_id, text_):
    r = env.post("title-approvals", {"generation_id": set_id, "edited_text": text_})
    assert r.status_code == 200, r.text
    return r.json()


def listing_from(env, approval_id, key="k1", mp=AMAZON):
    out = env.post("full-listing", {**body(key), "marketplace": mp, "seller_title": None, "approval_id": approval_id}).json()
    assert out["status"] in ("COMPLETE", "PARTIAL"), out
    return out["card"]


def card(env, gid, headers=None):
    return env.client().get(f"/api/v1/cmo/listing/{gid}", headers=headers or env.headers)


def setup(env):
    """A title set the seller approves (verified fixture rules, as in the standard CMO tests); the listing is then written from that approval."""
    env.provider = TitleProvider("ok")
    from tests.integration.test_cmo_api import _install

    _install(env.monkeypatch, env.provider)
    facts(env)
    first = title_set(env, "ts1")
    a1 = approve(env, first, T1)
    return a1


def test_a_pack_built_from_the_currently_approved_title_is_not_flagged(env):
    a1 = setup(env)
    c = listing_from(env, a1["approvalId"])
    st = c["titleStatus"]
    assert st["state"] == "CURRENT" and st["currentApproved"] is None and st["marketplace"] == "AMAZON" and st["builtFrom"] == T1


def test_an_unapproved_title_change_flags_nothing(env):
    a1 = setup(env)
    c = listing_from(env, a1["approvalId"])
    assert card(env, c["generationId"]).json()["titleStatus"]["state"] == "CURRENT"  # no new set, no flag
    typed = env.post("full-listing", body("typed", seller_title="A completely different title I typed")).json()
    assert typed["card"]["titleStatus"]["state"] == "UNKNOWN" and typed["card"]["titleStatus"]["reason"] == "TYPED_TITLE"
    assert card(env, c["generationId"]).json()["titleStatus"]["state"] == "CURRENT"  # typing a title elsewhere does not touch this pack


def test_approving_a_different_title_flags_the_pack_and_preserves_history_and_billing(env):
    a1 = setup(env)
    c = listing_from(env, a1["approvalId"])
    gid = c["generationId"]
    rows, events, audits, calls = len(gens(env)), len(env.events()), env.n("cmo_listing_audit"), env.provider.calls
    before = env.q("SELECT output_structured FROM cmo_generation WHERE id = :g", g=gid)[0][0]
    # a new title set (rules are off for the listing basis, so write it under a fixture row) and the seller approves a different title
    second = title_set(env, "ts2")
    assert card(env, gid).json()["titleStatus"]["state"] == "CURRENT"  # a new set of options is not an approval
    a2 = approve(env, second, T2)
    notice = a2["listingsBuiltFromEarlierTitle"]
    assert len(notice) == 1 and notice[0]["generationId"] == gid and notice[0]["marketplace"] == "AMAZON" and "previous title" in notice[0]["explanation"] and "plan it for your approval" in notice[0]["nextStep"]
    st = card(env, gid).json()["titleStatus"]
    assert st["state"] == "OUTDATED" and st["builtFrom"] == T1 and st["currentApproved"] == T2 and st["product"] == NAME and st["marketplace"] == "AMAZON"
    after = env.q("SELECT output_structured FROM cmo_generation WHERE id = :g", g=gid)[0][0]
    assert after == before  # not edited, not relabelled
    new_rows = len(gens(env)) - rows
    assert new_rows == 1 and len(env.events()) == events + 1 and env.n("cmo_listing_audit") == audits  # only the new title set (its own unit); no regenerated listing, no new audit
    assert env.provider.calls == calls + 1


def test_every_version_of_an_outdated_listing_is_flagged_and_all_of_them_are_kept(env):
    a1 = setup(env)
    v1 = listing_from(env, a1["approvalId"])["generationId"]
    v2 = env.client().post(f"/api/v1/cmo/listing/{v1}/edit", json={"message": "Change bullet 2 to: Holds 1 litre"}, headers=env.headers).json()["generationId"]
    approve(env, title_set(env, "ts2"), T2)
    for gid in (v1, v2):
        assert card(env, gid).json()["titleStatus"]["state"] == "OUTDATED"
    assert env.n("cmo_generation", "output_type = 'LISTING_COPY' AND status = 'COMPLETE'") == 2


def test_approving_the_same_words_again_does_not_flag(env):
    a1 = setup(env)
    gid = listing_from(env, a1["approvalId"])["generationId"]
    again = approve(env, title_set(env, "ts2"), T1)
    assert again["listingsBuiltFromEarlierTitle"] == [] and card(env, gid).json()["titleStatus"]["state"] == "CURRENT"


def test_a_title_approved_for_another_marketplace_does_not_flag_this_one(env):
    a1 = setup(env)
    gid = listing_from(env, a1["approvalId"])["generationId"]
    flip = approve(env, title_set(env, "tsf", FLIPKART), T3)
    assert flip["listingsBuiltFromEarlierTitle"] == [] and card(env, gid).json()["titleStatus"]["state"] == "CURRENT"


def test_missing_title_information_is_unknown_never_outdated(env):
    setup(env)
    typed = env.post("full-listing", body("typed2", seller_title="A different title I typed myself")).json()["card"]["titleStatus"]
    assert typed["state"] == "UNKNOWN" and typed["reason"] == "TYPED_TITLE" and typed["currentApproved"] is None  # an approved title exists, but this pack never came from one: not "outdated"
    same = env.post("full-listing", body("typed3", seller_title=T1)).json()["card"]["titleStatus"]
    assert same["state"] == "CURRENT"  # a typed title that equals the approved one is simply current
    # no approval at all for the product and marketplace (and no title on the pack) is covered at rule level: test_title_currency.py::test_missing_or_unconfirmed_title_information_is_unknown_never_outdated


def test_another_tenant_cannot_read_the_status_and_its_approvals_never_flag_my_listing(env):
    a1 = setup(env)
    gid = listing_from(env, a1["approvalId"])["generationId"]
    other, headers = env.other_tenant()
    assert card(env, gid, headers).status_code == 404
    from backend.services import cmo_listing

    assert cmo_listing.earlier_title_notice(other, __import__("uuid").UUID(gid)) == []
    assert card(env, gid).json()["titleStatus"]["state"] == "CURRENT"
