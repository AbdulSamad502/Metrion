"""The Competitor Intelligence evidence → research path as the Competitors screen uses it (`POST /ci/evidence`, then `POST /ceo-hub/research-now`).

This is the direct path the seller's own page drives. The CEO's chat action `ci.research_now` is deliberately NOT wired (spec Q8, see the integration matrix), so these
tests pin what a future chat bridge would have to preserve: who may call it, what it refuses, what it stores, and that a failed or missing extraction never becomes a price.

Real Postgres on the scratch database; only Clerk and the vision model are faked. No Ollama call is made: `_vision_extractor` is replaced by a scripted extractor
(a deterministic test double, not a live-model result). Evidence files go to a temporary directory."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from backend.api.v1 import ceo_hub as ceo_hub_api
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionFailed, ExtractionResult
from tests.integration.test_ci_api import _register_deny_all_partner, _register_owner, client, fake_clerk  # noqa: F401  (fixtures and helpers)

pytestmark = pytest.mark.usefixtures("_clean_backend_tables")


class Scripted:
    """A vision extractor that returns what the test says and records which image_refs it was asked to read."""

    def __init__(self, outcome) -> None:
        self.outcome, self.asked = outcome, []

    def extract(self, image_ref: str):
        self.asked.append(image_ref)
        return self.outcome


@pytest.fixture
def evidence_dir(tmp_path, monkeypatch) -> Path:
    from backend import config

    monkeypatch.setenv("CI_EVIDENCE_DIR", str(tmp_path))
    config.ci_evidence_storage_dir.cache_clear()  # the setting is read once per process; without this an earlier test's directory would be used
    yield tmp_path
    config.ci_evidence_storage_dir.cache_clear()


def use_extractor(monkeypatch, extractor: Scripted) -> Scripted:
    monkeypatch.setattr(ceo_hub_api, "_vision_extractor", lambda: extractor)
    return extractor


def track(client, headers, name="research") -> str:
    r = client.post("/api/v1/ci/competitor-urls", json={"url": f"https://amazon.in/dp/{name}-{uuid.uuid4().hex[:8]}"}, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def snapshots(client, headers, url) -> list:
    body = client.get(f"/api/v1/ci/competitor-urls/{url}/snapshots", headers=headers)
    assert body.status_code == 200, body.text
    data = body.json()
    return data if isinstance(data, list) else data.get("snapshots", [])


RESEARCH = "/api/v1/ceo-hub/research-now"
PRICE_ONLY = ExtractionResult(fields=(ExtractedField("listed_price_paise", 99900),))
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


# ------------------------------------------------------------------------------------------------ the upload
def test_an_upload_needs_a_signed_in_member_with_the_ci_key(client, fake_clerk, two_tenants, evidence_dir):
    a, _ = two_tenants
    png = {"file": ("shot.png", PNG, "image/png")}
    assert client.post("/api/v1/ci/evidence", files=png).status_code == 401
    assert client.post("/api/v1/ci/evidence", files=png, headers=_register_deny_all_partner(fake_clerk, a)).status_code == 403
    assert list(evidence_dir.iterdir()) == []  # a refused upload leaves nothing on disk


def test_an_upload_without_a_file_is_refused_and_a_valid_one_returns_an_opaque_reference(client, fake_clerk, two_tenants, evidence_dir):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    assert client.post("/api/v1/ci/evidence", headers=headers).status_code == 422
    ok = client.post("/api/v1/ci/evidence", files={"file": ("listing.png", PNG, "image/png")}, headers=headers)
    assert ok.status_code == 200, ok.text
    ref = ok.json()["imageRef"]
    assert ref.endswith(".png") and "/" not in ref and "\\" not in ref and ref != "listing.png"  # minted by the server, never the client's name
    assert (evidence_dir / ref).read_bytes().startswith(b"\x89PNG")


# ------------------------------------------------------------------------------------------------ the research request
def test_research_needs_a_signed_in_member_with_the_ci_key_and_a_valid_body(client, fake_clerk, two_tenants, monkeypatch):
    a, _ = two_tenants
    extractor = use_extractor(monkeypatch, Scripted(PRICE_ONLY))
    headers = _register_owner(fake_clerk, a)
    url = track(client, headers)
    body = {"competitor_url_id": url, "image_refs": [], "manual_fields": {"listed_price_paise": 1}}
    assert client.post(RESEARCH, json=body).status_code == 401
    assert client.post(RESEARCH, json=body, headers=_register_deny_all_partner(fake_clerk, a)).status_code == 403
    for bad in ({}, {"competitor_url_id": "not-a-uuid"}, {"competitor_url_id": url, "image_refs": "x"}, {"competitor_url_id": url, "manual_fields": []}):
        assert client.post(RESEARCH, json=bad, headers=headers).status_code == 422, bad
    assert extractor.asked == []  # nothing invalid reached the model


def test_a_competitor_that_is_not_the_members_is_treated_as_missing_and_nothing_is_stored(client, fake_clerk, two_tenants, monkeypatch):
    a, b = two_tenants
    extractor = use_extractor(monkeypatch, Scripted(PRICE_ONLY))
    ha, hb = _register_owner(fake_clerk, a), _register_owner(fake_clerk, b)
    b_url = track(client, hb, "owned-by-b")
    for target in (b_url, str(uuid.uuid4())):
        resp = client.post(RESEARCH, json={"competitor_url_id": target, "image_refs": ["x.png"], "manual_fields": {"listed_price_paise": 5}}, headers=ha)
        assert resp.status_code < 500, resp.text
        assert resp.status_code == 404 or resp.json()["ci"]["status"] == "FAILED", resp.json()
    assert snapshots(client, hb, b_url) == []  # B's record was not touched by A
    assert extractor.asked == []  # an unknown competitor is refused before any image is read


# ------------------------------------------------------------------------------------------------ what is stored and what is never made up
def test_extracted_and_manual_values_become_a_snapshot_and_the_manual_value_wins(client, fake_clerk, two_tenants, monkeypatch):
    a, _ = two_tenants
    extractor = use_extractor(monkeypatch, Scripted(ExtractionResult(fields=(ExtractedField("listed_price_paise", 99900), ExtractedField("availability", "IN_STOCK")))))
    headers = _register_owner(fake_clerk, a)
    url = track(client, headers)
    resp = client.post(RESEARCH, json={"competitor_url_id": url, "image_refs": ["shot.png"], "manual_fields": {"listed_price_paise": 94900}}, headers=headers)
    assert resp.status_code == 200, resp.text
    ci = resp.json()["ci"]
    assert ci["status"] != "FAILED" and ci["snapshotId"]
    assert extractor.asked == ["shot.png"]
    rows = snapshots(client, headers, url)
    assert len(rows) == 1
    flat = str(rows[0])
    assert "94900" in flat and "99900" not in flat  # the seller's own entry replaces the model's reading


def test_a_failed_reading_with_no_manual_entry_never_becomes_a_price(client, fake_clerk, two_tenants, monkeypatch):
    a, _ = two_tenants
    use_extractor(monkeypatch, Scripted(ExtractionFailed(reason="image unreadable")))
    headers = _register_owner(fake_clerk, a)
    url = track(client, headers)
    resp = client.post(RESEARCH, json={"competitor_url_id": url, "image_refs": ["blurry.png"], "manual_fields": {}}, headers=headers)
    assert resp.status_code == 200, resp.text
    ci = resp.json()["ci"]
    assert ci["captureStatus"] != "COMPLETE" and ci["priceEventId"] is None
    assert not any(r.get("listedPricePaise") or r.get("listed_price_paise") for r in snapshots(client, headers, url))


def test_research_with_neither_evidence_nor_a_manual_entry_is_not_reported_as_a_success(client, fake_clerk, two_tenants, monkeypatch):
    a, _ = two_tenants
    extractor = use_extractor(monkeypatch, Scripted(PRICE_ONLY))
    headers = _register_owner(fake_clerk, a)
    url = track(client, headers)
    resp = client.post(RESEARCH, json={"competitor_url_id": url, "image_refs": [], "manual_fields": {}}, headers=headers)
    assert resp.status_code == 200, resp.text
    ci = resp.json()["ci"]
    assert ci["captureStatus"] != "COMPLETE" and ci["priceEventId"] is None
    assert extractor.asked == []


def test_submitting_the_same_research_twice_stores_two_audited_runs_and_invents_no_price_change(client, fake_clerk, two_tenants, monkeypatch):
    a, _ = two_tenants
    use_extractor(monkeypatch, Scripted(PRICE_ONLY))
    headers = _register_owner(fake_clerk, a)
    url = track(client, headers)
    body = {"competitor_url_id": url, "image_refs": [], "manual_fields": {"listed_price_paise": 99900, "availability": "IN_STOCK"}}
    first = client.post(RESEARCH, json=body, headers=headers).json()
    second = client.post(RESEARCH, json=body, headers=headers).json()
    assert first["ceoAgentRunId"] != second["ceoAgentRunId"]  # not idempotent: each press is a new, audited run
    assert first["ci"]["researchSessionId"] != second["ci"]["researchSessionId"]
    assert second["ci"]["priceEventId"] is None  # the same price twice is not a price change
