"""CMO 3.0 M6 N-15d (pure rule): a saved listing is "built from a previous title" only after the seller APPROVES a different title; nothing else flags it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from slim_cmo.listing import title_currency as tc

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
OLD = tc.ApprovalRef("a1", "AquaNest 1 Litre Steel Bottle", T0)
NEW = tc.ApprovalRef("a2", "AquaNest Insulated Steel Bottle 1 Litre", T0 + timedelta(days=1))


def run(built_from, built, current, mp="AMAZON", product="AquaNest bottle"):
    return tc.assess(built_from=built_from, built_approval=built, current=current, marketplace=mp, product=product)


def test_a_pack_built_from_the_currently_approved_title_is_not_flagged():
    r = run(OLD.text, OLD, OLD)
    assert r["state"] == tc.CURRENT and r["reason"] == "SAME_TITLE" and r["currentApproved"] is None and r["nextStep"] is None


def test_a_later_approval_of_a_different_title_flags_the_pack_and_names_product_marketplace_and_both_titles():
    r = run(OLD.text, OLD, NEW)
    assert r["state"] == tc.OUTDATED and r["reason"] == "NEWER_APPROVAL" and r["builtFrom"] == OLD.text and r["currentApproved"] == NEW.text
    assert "AquaNest bottle on Amazon" in r["explanation"] and "previous title" in r["explanation"] and "not been edited" in r["explanation"]
    assert "plan it for your approval" in r["nextStep"] and "Nothing was changed or regenerated" in r["nextStep"]


def test_approving_the_same_words_again_is_not_a_change_even_with_a_new_approval_row():
    again = tc.ApprovalRef("a3", "  aquanest 1 LITRE steel bottle ", T0 + timedelta(days=2))
    assert run(OLD.text, OLD, again)["state"] == tc.CURRENT


def test_a_pack_written_from_a_typed_title_is_unknown_not_outdated_and_not_unapproved():
    r = run("My own typed title", None, NEW)
    assert r["state"] == tc.UNKNOWN and r["reason"] == "TYPED_TITLE" and r["currentApproved"] is None
    assert run(NEW.text, None, NEW)["state"] == tc.CURRENT  # a typed title that equals the approved one is simply current


def test_missing_or_unconfirmed_title_information_is_unknown_never_outdated():
    assert run(None, OLD, NEW)["reason"] == "NO_PACK_TITLE" and run("   ", OLD, NEW)["state"] == tc.UNKNOWN
    no_approval = run(OLD.text, OLD, None)
    assert no_approval["state"] == tc.UNKNOWN and no_approval["reason"] == "NO_APPROVED_TITLE"
    assert run(OLD.text, OLD, tc.ApprovalRef("a9", "  ", T0 + timedelta(days=3)))["state"] == tc.UNKNOWN


def test_an_approval_that_is_not_newer_never_makes_a_pack_outdated():
    earlier = tc.ApprovalRef("a0", "An earlier different title", T0 - timedelta(days=1))
    assert run(OLD.text, OLD, earlier)["state"] == tc.UNKNOWN


def test_the_marketplace_and_product_are_reported_as_given():
    r = run(OLD.text, OLD, NEW, mp="FLIPKART", product=None)
    assert r["marketplace"] == "FLIPKART" and "this product on Flipkart" in r["explanation"]
