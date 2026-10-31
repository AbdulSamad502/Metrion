"""The marketplace rules register keeps its own policy (B1/B6): no value without an official source and a date; nothing promotable until every needed field is verified."""

from __future__ import annotations

import copy

from slim_cmo.service import marketplace_rules as mr


def test_the_shipped_register_is_consistent_with_its_own_policy():
    assert mr.problems(mr.load()) == []


def test_today_no_marketplace_has_enough_verified_rules_to_become_a_constraint_row():
    data = mr.load()
    for m in ("AMAZON", "FLIPKART", "MEESHO"):
        assert mr.promotable_row(data, m) is None  # the unverified-draft restriction stays


def test_a_third_party_figure_can_only_be_a_hint_never_a_value():
    data = mr.load()
    data["rules"].append({"marketplace": "AMAZON", "scope": "x", "field": "bullet.max_chars", "value": 500, "status": "THIRD_PARTY_ONLY", "source": None, "checked_on": "2026-10-31"})
    assert any("must carry value null" in p for p in mr.problems(data))


def test_an_official_rule_needs_https_an_official_host_a_value_and_a_date():
    data = mr.load()
    bad = copy.deepcopy(data)
    bad["rules"].append({"marketplace": "AMAZON", "scope": "x", "field": "title.max_chars", "value": 200, "status": "OFFICIAL_VERIFIED", "source": {"url": "http://example.com/blog"}, "checked_on": "soon"})
    found = " ".join(mr.problems(bad))
    assert "https URL on an official host" in found and "ISO date" in found


def test_promotion_requires_every_needed_field_verified():
    data = mr.load()
    for f, v in zip(data["required_for_constraint_row"], (200, 5, 500, 2000, 249)):
        data["rules"].append({"marketplace": "AMAZON", "scope": "amazon.in", "field": f, "value": v, "status": "OFFICIAL_VERIFIED",
                              "source": {"url": "https://sellercentral.amazon.in/help/example"}, "checked_on": "2026-10-31"})
    assert mr.problems(data) == [] and mr.promotable_row(data, "AMAZON") is not None
    data["rules"] = [r for r in data["rules"] if r["field"] != "backend_terms.max_bytes" or r["status"] != mr.OFFICIAL_VERIFIED]
    assert mr.promotable_row(data, "AMAZON") is None  # one missing field and nothing is promoted


def test_the_register_lists_the_evidence_a_seller_account_must_supply_and_its_failed_access_attempts():
    data = mr.load()
    for m in ("AMAZON", "FLIPKART", "MEESHO"):
        assert data["evidence_needed_from_a_seller_account"][m]
    assert data["access_attempts"] and all(a["url"].startswith("https://") for a in data["access_attempts"])


def test_display_rules_come_from_the_register_only_when_official_verified_for_all_categories():
    data = mr.load()
    assert mr.display_rules_config(data) == {}  # nothing is verified today
    data["rules"].append({"marketplace": "AMAZON", "scope": "amazon.in ALL_CATEGORIES", "field": "title.display_chars.mobile", "value": 70, "status": "OFFICIAL_VERIFIED",
                          "source": {"url": "https://sellercentral.amazon.in/help/example"}, "checked_on": "2026-10-31"})
    data["rules"].append({"marketplace": "AMAZON", "scope": "amazon.in Kitchen", "field": "title.display_chars.desktop", "value": 120, "status": "OFFICIAL_VERIFIED",
                          "source": {"url": "https://sellercentral.amazon.in/help/example"}, "checked_on": "2026-10-31"})
    assert mr.display_rules_config(data) == {"AMAZON": {"mobile": {"visible_chars": 70, "source_url": "https://sellercentral.amazon.in/help/example", "verified_at": "2026-10-31"}}}


def _obs(i: int, **kw):
    base = {"marketplace": "AMAZON", "category": "Kitchen", "device": "mobile", "surface": "search_results", "listing_ref": f"https://www.amazon.in/dp/TEST{i}",
            "observed_on": "2026-10-30", "method": "screenshot at 390px, signed out", "title_chars": 150, "visible_chars": 60 + i, "truncated": True, "authorized_by": "owner"}
    base.update(kw)
    return base


def test_no_display_measurement_exists_yet_and_the_register_stays_valid():
    data = mr.load()
    assert data["display_measurements"] == [] and mr.measurement_problems(data) == [] and mr.measured_display_summary(data) == []


def test_a_measurement_without_its_evidence_fields_is_not_evidence():
    data = mr.load()
    data["display_measurements"] = [_obs(1, method="", authorized_by=None, device="tablet", observed_on="2999-01-01", visible_chars=200, listing_ref="http://x.example/p")]
    found = " ".join(mr.measurement_problems(data, today=__import__("datetime").date(2026, 10, 31)))
    for part in ("method is required", "authorized_by is required", "device must be", "in the future", "visible_chars must be", "must be https"):
        assert part in found


def test_truncated_must_agree_with_the_characters_shown():
    data = mr.load()
    data["display_measurements"] = [_obs(1, truncated=False)]
    assert any("truncated must be true exactly" in p for p in mr.measurement_problems(data))


def test_a_summary_needs_several_observations_of_different_listings_and_is_only_a_candidate():
    data = mr.load()
    data["display_measurements"] = [_obs(i) for i in range(4)]
    assert mr.measured_display_summary(data)[0]["status"] == "INSUFFICIENT"
    data["display_measurements"] = [_obs(i, listing_ref="https://www.amazon.in/dp/SAME") for i in range(5)]
    assert mr.measured_display_summary(data)[0]["status"] == "INSUFFICIENT"  # one listing five times is one observation
    data["display_measurements"] = [_obs(i) for i in range(5)]
    s = mr.measured_display_summary(data)[0]
    assert (s["status"], s["visible_chars_min"], s["visible_chars_max"]) == ("CANDIDATE_FOR_REVIEW", 60, 64)
    assert mr.display_rules_config(data) == {}  # a measurement never reaches the preview by itself
