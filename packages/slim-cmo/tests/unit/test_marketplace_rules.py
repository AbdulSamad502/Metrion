"""The marketplace rules register keeps its own policy (B1/B6): no value without an official source and a date; nothing promotable until every needed field is verified."""

from __future__ import annotations

import copy

from slim_cmo.service import marketplace_rules as mr


def test_the_shipped_register_is_consistent_with_its_own_policy():
    assert mr.problems(mr.load()) == []


def test_today_no_marketplace_has_enough_verified_rules_to_become_a_constraint_row():
    data = mr.load()
    for m in ("AMAZON", "FLIPKART", "MESHO"):
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
