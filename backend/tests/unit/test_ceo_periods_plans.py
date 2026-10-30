"""B3: deterministic period/slot resolution and the fixed plans (spec §6.3 rule 3, §6.11, §6.12). No model, no database."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import date

import pytest

from backend.ceo.periods import PeriodUnresolvable, resolve_period
from backend.ceo.plans import ACTIONS, PLAYBOOK_LEG_SLOTS, PLAYBOOKS, Clarification, ResolvedSlots, resolve_slots
from backend.ceo.registry import get_registry

TODAY = date(2026, 10, 7)
TENANT = uuid.uuid4()


@pytest.mark.parametrize(
    "text, start, end",
    [
        ("last month", "2026-09-01", "2026-09-30"),
        ("Previous month", "2026-09-01", "2026-09-30"),
        ("September", "2026-09-01", "2026-09-30"),
        ("for September", "2026-09-01", "2026-09-30"),
        ("sep", "2026-09-01", "2026-09-30"),
        ("August 2025", "2025-08-01", "2025-08-31"),
        ("december", "2025-12-01", "2025-12-31"),  # most recent December NOT in the future
        ("this month", "2026-10-01", "2026-10-07"),
        ("october", "2026-10-01", "2026-10-07"),  # the current month is cut at today, never extended into the future
        ("2026-08", "2026-08-01", "2026-08-31"),
        ("2026-09-01 to 2026-09-15", "2026-09-01", "2026-09-15"),
    ],
)
def test_period_resolution(text, start, end):
    p = resolve_period(text, today=TODAY)
    assert (p.start.isoformat(), p.end.isoformat()) == (start, end)
    assert p.as_of == TODAY  # as_of is the day of the request, never a model- or seller-supplied date
    assert start in p.echo and end in p.echo  # the interpretation is always echoed (AC17)


@pytest.mark.parametrize("text", ["", None, "last quarter", "Q2", "recently", "tomorrow", "2026-13", "2026-09-30 to 2026-09-01", "2027-03", "foo 2026"])
def test_an_unresolvable_period_is_refused_never_guessed(text):
    with pytest.raises(PeriodUnresolvable):
        resolve_period(text, today=TODAY)


def test_january_looks_back_across_the_year_boundary():
    p = resolve_period("last month", today=date(2026, 1, 15))
    assert (p.start, p.end) == (date(2025, 12, 1), date(2025, 12, 31))


def test_missing_required_slots_are_clarifications():
    assert resolve_slots({}, ("period",), tenant_id=TENANT, today=TODAY) == Clarification("period", resolve_slots({}, ("period",), tenant_id=TENANT, today=TODAY).question)
    r = resolve_slots({"period": "september"}, ("marketplace", "period"), tenant_id=TENANT, today=TODAY)
    assert isinstance(r, Clarification) and r.slot == "marketplace"
    r = resolve_slots({"period": "soonish", "marketplace": "Amazon"}, ("marketplace", "period"), tenant_id=TENANT, today=TODAY)
    assert isinstance(r, Clarification) and r.slot == "period"


def test_marketplace_text_is_normalised():
    r = resolve_slots({"period": "last month", "marketplace": "my flipkart store"}, ("marketplace", "period"), tenant_id=TENANT, today=TODAY)
    assert isinstance(r, ResolvedSlots) and r.marketplace == "FLIPKART" and any("Flipkart" in e for e in r.echoes())
    assert isinstance(resolve_slots({"marketplace": "Shopify", "period": "september"}, ("marketplace", "period"), tenant_id=TENANT, today=TODAY), Clarification)


# ------------------------------------------------------------------------------------------------ the fixed plans
def test_every_planned_action_is_a_wired_registry_action_with_valid_slots():
    import uuid

    from backend.ceo.plans import GST_KEY, GST_ROUTE_KEYS

    reg = get_registry()
    base = resolve_slots({"period": "september", "marketplace": "amazon"}, ("marketplace", "period"), tenant_id=TENANT, today=TODAY)
    assert isinstance(base, ResolvedSlots)
    # every value code can resolve, so each plan can build its slots (the resolvers themselves are tested where their data lives)
    resolved = ResolvedSlots(
        tenant_id=TENANT, today=TODAY, period=base.period, marketplace=base.marketplace, competitor_url_id=uuid.uuid4(), competitor_label="Rival",
        seller_price_paise=49900, pi_run_id=uuid.uuid4(), product_text="steel water bottle", product_id="SKU-1", question="which SKU made the most profit",
    )
    sample = {  # what each guided input session ends with (spec 6.35)
        "pi.discover": {"niche_brief_id": str(uuid.uuid4()), "depth": "SHALLOW"},
        "cmo.generate_title_sets": {"request_key": "k", "product_name": "bottle", "marketplaces": ["AMAZON"]},
        "cmo.generate_hashtags": {"request_key": "k", "product_name": "bottle"},
        "cmo.generate_description": {"request_key": "k", "product_name": "bottle", "marketplace": "AMAZON", "seller_title": "Steel Bottle"},
        "cmo.generate_keywords": {"request_key": "k", "product_name": "bottle", "marketplace": "AMAZON", "seller_title": "Steel Bottle"},
        "cmo.generate_bullets": {"request_key": "k", "product_name": "bottle", "marketplace": "AMAZON", "seller_title": "Steel Bottle"},
        "cmo.generate_backend_terms": {"request_key": "k", "product_name": "bottle", "marketplace": "AMAZON", "seller_title": "Steel Bottle"},
        "cmo.generate_listing_copy": {"request_key": "k", "product_name": "bottle", "marketplace": "AMAZON", "seller_title": "Steel Bottle"},
        "cmo.catalog_answer": {"request_key": "k", "product_name": "bottle", "questions": ["COLOR"]},
        "cmo.keyword_intelligence": {"request_key": "k", "sku": "bottle"},
        "cmo.approve_title": {"generation_id": "00000000-0000-0000-0000-000000000001", "option_id": "00000000-0000-0000-0000-000000000002"},
        "cmo.market_trends": {"request_key": "k", "marketplaces": ["AMAZON"], "plan_digest": "a" * 64},  # spec 6.40: the run is bound to a confirmed preview
        "cmo.market_trends_preview": {"marketplaces": ["AMAZON"]},
        "cfo.expense_add": {"effective_date": "2026-10-01", "category": "operating_overhead", "amount_paise": 500000, "request_key": "k"},
        "cfo.expense_correct": {"expense_id": str(uuid.uuid4()), "effective_date": "2026-10-01", "category": "software", "amount_paise": 99900, "request_key": "k"},
        "cfo.expense_void": {"expense_id": str(uuid.uuid4()), "reason": "duplicate", "request_key": "k"},
        "cfo.expense_paid": {"expense_id": str(uuid.uuid4()), "status": "paid", "request_key": "k"},
        "cfo.cash_position": {},
        "cfo.performance": {"period_start": "2026-09-01", "period_end": "2026-09-30", "as_of_date": "2026-10-23"},
        "cfo.import_attachments": {"investigation_id": str(uuid.uuid4()), "files": [{"attachment_id": str(uuid.uuid4()), "filename": "r.csv", "marketplace": "AMAZON"}], "request_key": "k"},
    }
    for key, plan in ACTIONS.items():
        built = plan.build_slots(dataclasses.replace(resolved, direct=sample[key]) if key in sample else resolved)
        specs = [reg.get(k) for k in GST_ROUTE_KEYS] if key == GST_KEY else [reg.get(key)]  # GST is one action to the model; code picks the route
        for spec in specs:
            assert spec.wired and not spec.denial_surface
            spec.slot_model.model_validate({**built, **dict(spec.fixed_params)})  # the registry's own model accepts exactly what the plan builds
        if key != GST_KEY:
            assert specs[0].agent is not None


def test_slot_builders_never_take_a_tenant_id_from_the_request():
    resolved = resolve_slots({"period": "september"}, ("period",), tenant_id=TENANT, today=TODAY)
    assert isinstance(resolved, ResolvedSlots)
    built = ACTIONS["cfo.anomaly_check"].build_slots(resolved)
    assert built["target_ref"] == str(TENANT) and built["include_narration"] is False  # derived from the authenticated tenant; narration off


def test_playbook_legs_are_registry_keys_and_independent():
    reg = get_registry()
    for pb in PLAYBOOKS.values():
        assert len({leg.key for leg in pb.legs}) == len(pb.legs)
        for leg in pb.legs:
            assert leg.key in reg  # no leg outside the closed, wired set
            assert leg.key in ACTIONS or (pb.id, leg.key) in PLAYBOOK_LEG_SLOTS  # a form-only playbook leg has its own slot builder, never a chat action
        assert all(read.startswith("BS_") for read in pb.state_reads)


def test_the_two_decision_playbooks_run_only_from_a_form():
    assert {k for k, p in PLAYBOOKS.items() if p.needs_form} == {"COMPETITOR_PRICE_IMPACT", "NEW_PRODUCT_DECISION"}  # run only from a form's inputs (spec 6.33)


def test_business_briefing_has_no_legs_and_reads_only_persisted_state():
    pb = PLAYBOOKS["BUSINESS_BRIEFING"]
    assert pb.legs == () and "BS_PNL_LATEST" in pb.state_reads


# ------------------------------------------------------------------------------------------------ single days and relative ranges (ceo-expense-tracker-chat.md)
@pytest.mark.parametrize("text,start,end", [
    ("today", "2026-10-23", "2026-10-23"), ("Yesterday", "2026-10-22", "2026-10-22"), ("last 7 days", "2026-10-17", "2026-10-23"), ("the last 30 days", "2026-09-24", "2026-10-23"),
    ("2026-10-05", "2026-10-05", "2026-10-05"), ("5 october", "2026-10-05", "2026-10-05"), ("oct 5, 2026", "2026-10-05", "2026-10-05"), ("5th Oct", "2026-10-05", "2026-10-05"),
    ("5/10/2026", "2026-10-05", "2026-10-05"), ("1 oct to 15 oct", "2026-10-01", "2026-10-15"), ("from 1 sept to 30 sept", "2026-09-01", "2026-09-30"),
    ("30 december", "2025-12-30", "2025-12-30"),  # a day without a year is its most recent occurrence not in the future
])
def test_single_days_and_relative_ranges_are_read_exactly(text, start, end):
    from datetime import date as d

    r = resolve_period(text, today=d(2026, 10, 23))
    assert (r.start.isoformat(), r.end.isoformat(), r.as_of) == (start, end, d(2026, 10, 23)) and "I read the period" in r.echo


@pytest.mark.parametrize("text", ["tomorrow", "2026-11-05", "last 0 days", "last 400 days", "32 october", "15 oct to 1 oct", "5/13/2026", "soon"])
def test_what_cannot_be_read_exactly_is_refused_never_guessed(text):
    from datetime import date as d

    with pytest.raises(PeriodUnresolvable):
        resolve_period(text, today=d(2026, 10, 23))
