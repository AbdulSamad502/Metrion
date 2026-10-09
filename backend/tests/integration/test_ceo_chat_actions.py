"""B4: chat actions for CI (price positioning against ONE named competitor) and PI (the latest finished report), with deterministic slot resolution.

The model may fill slot TEXT; only code turns it into a competitor id or an amount in paise, from the caller's own tenant data. Nothing is guessed:
an unreadable amount, an unknown or ambiguous competitor, or no finished research run is a clarification that dispatches nothing."""

from __future__ import annotations

import os

import pytest

from backend.ceo import orchestrator, plans, slot_resolvers
from backend.repositories import agent_run_repo, investigation_repo as repo
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_state_specialists import NOW, seed  # noqa: F401  (fixture + constant)
from tests.integration.test_ceo_turn import Grounded, Scripted, decision, runtime, start

# --------------------------------------------------------------------------------------------- pure: amounts (no database)


@pytest.mark.parametrize("raw,paise", [
    ("499", 49900), ("₹499", 49900), ("Rs. 1,299.50", 129950), ("Rs 499", 49900), ("INR 2,499", 249900), ("1,29,900", 12990000),
    ("499 rupees", 49900), ("499/-", 49900), (" ₹ 499.5 ", 49950), ("0.50", 50), ("12345678901234", 1234567890123400),
])
def test_amounts_are_parsed_exactly_to_integer_paise(raw, paise):
    assert slot_resolvers.parse_amount_paise(raw) == paise and isinstance(slot_resolvers.parse_amount_paise(raw), int)


@pytest.mark.parametrize("raw", [
    None, "", "  ", "five hundred", "5k", "a lakh", "1.5 lakh", "499-599", "10%", "-499", "0", "0.00", "499.999", "1e3", "NaN", "₹", "499 or so",
    "9" * 40,
])
def test_anything_that_is_not_a_plain_rupee_amount_is_refused_never_guessed(raw):
    assert slot_resolvers.parse_amount_paise(raw) is None


def test_amount_parsing_uses_no_float_arithmetic():
    import inspect

    src = inspect.getsource(slot_resolvers.parse_amount_paise)
    assert "float(" not in src and "round(" not in src


# --------------------------------------------------------------------------------------------- competitor resolution (real database)
pytestmark_db = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


@pytestmark_db
@pytest.mark.usefixtures("two_tenants")
class TestResolution:
    def test_exact_label_substring_and_case(self, two_tenants, seed):  # noqa: F811
        a, _ = two_tenants
        u1, u2 = seed.url(a, "Acme Steel Bottle"), seed.url(a, "Zenith Flask")
        assert slot_resolvers.resolve_competitor(a, "acme steel bottle") == slot_resolvers.CompetitorMatch(u1, "Acme Steel Bottle")
        assert slot_resolvers.resolve_competitor(a, "zenith").url_id == u2
        assert slot_resolvers.resolve_competitor(a, "Acme").url_id == u1

    def test_ambiguity_is_a_question_not_a_pick(self, two_tenants, seed):  # noqa: F811
        a, _ = two_tenants
        seed.url(a, "Acme Steel Bottle"), seed.url(a, "Acme Copper Bottle")
        out = slot_resolvers.resolve_competitor(a, "acme")
        assert isinstance(out, slot_resolvers.CompetitorUnresolved) and out.reason == "AMBIGUOUS" and set(out.choices) == {"Acme Steel Bottle", "Acme Copper Bottle"}

    def test_unknown_and_none_tracked(self, two_tenants, seed):  # noqa: F811
        a, _ = two_tenants
        assert slot_resolvers.resolve_competitor(a, "anything").reason == "NONE_TRACKED"
        seed.url(a, "Acme")
        out = slot_resolvers.resolve_competitor(a, "Globex")
        assert out.reason == "NOT_FOUND" and out.choices == ("Acme",)
        assert slot_resolvers.resolve_competitor(a, None).reason == "NOT_FOUND"

    def test_another_tenants_competitor_is_never_matched(self, two_tenants, seed):  # noqa: F811
        a, b = two_tenants
        seed.url(a, "Acme")
        assert slot_resolvers.resolve_competitor(b, "Acme").reason == "NONE_TRACKED"  # B has none, and sees none of A's


# --------------------------------------------------------------------------------------------- the whole turn
def _classifier(msg, slots):
    return Scripted({msg: decision(route="ACTION", route_key="ci.request_price_scenario", slots=slots)})


@pytestmark_db
@pytest.mark.usefixtures("two_tenants")
class TestTurn:
    def test_a_named_competitor_and_price_run_the_ci_leg_and_echo_what_was_understood(self, two_tenants, app_user, seed):  # noqa: F811
        a, _ = two_tenants
        url = seed.url(a, "Rival One")
        seed.snapshot(a, url, 49900)
        msg = "Where does my 499 rupee price stand against Rival One?"
        rt = runtime(_classifier(msg, {"competitor": "Rival One", "amount": "₹599"}), Grounded())
        ctx = ctx_for(a, user_id=app_user)
        inv = start(ctx, rt)
        res = orchestrator.run_turn(ctx, rt, inv, msg)
        assert res.route == "ACTION" and res.route_key == "ci.request_price_scenario"
        assert "Competitor: Rival One." in res.notes and "Your current price taken as ₹599.00." in res.notes  # the reading is shown, not hidden
        finding = [f for f in repo.list_findings(a, inv) if f["action_key"] == "ci.request_price_scenario"]
        assert len(finding) == 1 and finding[0]["source"] == "CI"

    @pytest.mark.parametrize("slots,slot_name", [
        ({"competitor": "Rival One", "amount": "five hundred"}, "amount"),
        ({"competitor": "Rival One", "amount": "5k"}, "amount"),
        ({"competitor": "Globex", "amount": "499"}, "competitor"),
    ])
    def test_an_unreadable_amount_or_unknown_competitor_asks_and_dispatches_nothing(self, two_tenants, app_user, seed, slots, slot_name):  # noqa: F811
        a, _ = two_tenants
        seed.url(a, "Rival One")
        msg = "compare my price"
        rt = runtime(_classifier(msg, slots), Grounded())
        ctx = ctx_for(a, user_id=app_user)
        inv = start(ctx, rt)
        res = orchestrator.run_turn(ctx, rt, inv, msg)
        assert res.status == "CLARIFIED" and res.clarify_for == slot_name
        assert repo.list_findings(a, inv) == []
        assert agent_run_repo.list_children(a, repo.get_turn(a, res.turn_id)["agent_run_id"]) == []  # only the CEO turn row: no CI leg was started

    def test_an_ambiguous_competitor_lists_the_choices(self, two_tenants, app_user, seed):  # noqa: F811
        a, _ = two_tenants
        seed.url(a, "Acme Steel"), seed.url(a, "Acme Copper")
        msg = "price vs acme"
        rt = runtime(_classifier(msg, {"competitor": "acme", "amount": "499"}), Grounded())
        ctx = ctx_for(a, user_id=app_user)
        inv = start(ctx, rt)
        res = orchestrator.run_turn(ctx, rt, inv, msg)
        assert res.status == "CLARIFIED" and "Acme Steel" in res.answer and "Acme Copper" in res.answer

    def test_the_model_cannot_name_another_tenants_competitor(self, two_tenants, app_user, seed):  # noqa: F811
        a, b = two_tenants
        seed.url(a, "Rival One")
        msg = "price vs rival one"
        rt = runtime(_classifier(msg, {"competitor": "Rival One", "amount": "499"}), Grounded())
        ctx_b = ctx_for(b, user_id=app_user)
        inv = start(ctx_b, rt)
        res = orchestrator.run_turn(ctx_b, rt, inv, msg)
        assert res.status == "CLARIFIED" and res.clarify_for == "competitor"  # tenant B has no competitors; A's name resolves to nothing

    def test_a_pi_report_with_no_finished_run_is_a_plain_clarification(self, two_tenants, app_user, seed):  # noqa: F811
        a, _ = two_tenants
        seed.run(a, "RUNNING")  # an unfinished run has no report
        msg = "show my product research report"
        rt = runtime(Scripted({msg: decision(route="ACTION", route_key="pi.report")}), Grounded())
        ctx = ctx_for(a, user_id=app_user)
        inv = start(ctx, rt)
        res = orchestrator.run_turn(ctx, rt, inv, msg)
        assert res.status == "CLARIFIED" and res.clarify_for == "pi_run" and "No finished product research run" in res.answer

    def test_a_pi_report_resolves_to_the_newest_finished_run_not_a_newer_unfinished_one(self, two_tenants, seed):  # noqa: F811
        a, _ = two_tenants
        done = seed.run(a, "COMPLETE", started_at=NOW)
        seed.run(a, "RUNNING", started_at=NOW.replace(day=NOW.day))  # newer in queue order, unfinished
        r = plans.resolve_slots({}, (), tenant_id=a, today=NOW.date(), resolves=("pi_run",))
        assert r.pi_run_id == done
        assert plans.ACTIONS["pi.report"].build_slots(r) == {"run_id": str(done)}


def test_the_new_actions_are_in_the_closed_catalog_with_their_slots():
    assert plans.ACTIONS["ci.request_price_scenario"].required_slots == ("competitor", "amount")
    assert plans.ACTIONS["pi.report"].required_slots == () and plans.ACTIONS["pi.report"].resolves == ("pi_run",)
