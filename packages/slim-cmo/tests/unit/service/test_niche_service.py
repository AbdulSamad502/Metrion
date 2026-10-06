"""P7d: the catalog-seeded niche flow (spec §6.8.3, C15, AC30, AC34, E19, E20, E26, T34) against an in-memory store."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from slim_cmo import config as cfg
from slim_cmo.service.errors import NotFound
from slim_cmo.service.models import Actor
from slim_cmo.service.niche import (
    NO_TITLES_REASON, Decision, DecisionKind, InvalidNicheRequest, InvalidNicheTerms, NicheConfigMissing, NicheService,
    Plan, StoredTerm, TooManyConfirmedTerms,
)
from slim_cmo.types import NicheTermOrigin as O
from slim_cmo.types import NicheTermStatus as S

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
GOOD = {"max_confirmed_niche_terms": 5, "max_term_chars": 40, "catalog_titles_read_cap": 100}
TITLES = [
    "Steel Water Bottle 1 Litre Leak Proof", "Steel Water Bottle Gym Shaker", "Copper Water Bottle 750ml",
    "Steel Lunch Box 3 Compartment", "Steel Lunch Box Insulated", "Yoga Mat Anti Skid",
]


class FakeStore:
    def __init__(self, config=None, titles=None, fact_terms=None) -> None:
        self.config = dict(GOOD if config is None else config)
        self.titles = list(TITLES if titles is None else titles)
        self.fact_terms = list(fact_terms or [])
        self.rows: dict[UUID, StoredTerm] = {}
        self.read_caps: list[int] = []
        self.config_calls = 0

    def load_config(self, tenant_id, keys, as_of):
        self.config_calls += 1
        return {k: v for k, v in self.config.items() if k in keys}

    def read_catalog_titles(self, tenant_id, cap):
        self.read_caps.append(cap)
        return self.titles[:cap]

    def read_seller_fact_terms(self, tenant_id, cap):
        return self.fact_terms[:cap]

    def list_terms(self, tenant_id):
        return list(self.rows.values())

    def apply_plan(self, tenant_id, user_id, plan_fn):
        snapshot = dict(self.rows)
        try:
            plan = plan_fn(list(self.rows.values()))
            assert isinstance(plan, Plan)
            for c in plan.changes:
                old = self.rows[c.term_id]
                self.rows[c.term_id] = StoredTerm(old.id, old.term, old.origin, old.origin_note, c.status)
            for i in plan.inserts:
                tid = uuid4()
                self.rows[tid] = StoredTerm(tid, i.term, i.origin, i.origin_note, i.status)
        except BaseException:
            self.rows = snapshot  # the real store rolls the transaction back
            raise
        return list(self.rows.values())


@pytest.fixture
def actor():
    return Actor(uuid4(), uuid4())


def svc(store):
    return NicheService(store, clock=lambda: NOW)


def by_term(rows):
    return {r.term: r for r in rows}


# ------------------------------------------------------------------------------ config
def test_missing_config_blocks_both_actions_and_reads_nothing(actor):
    store = FakeStore(config={"max_term_chars": 40})
    for call in (lambda: svc(store).suggest(actor), lambda: svc(store).confirm(actor, [], ["steel bottle"])):
        with pytest.raises(NicheConfigMissing) as err:
            call()
        assert set(err.value.problem.missing) == {"max_confirmed_niche_terms", "catalog_titles_read_cap"}
    assert store.read_caps == [] and store.rows == {}


@pytest.mark.parametrize("bad", [{"max_confirmed_niche_terms": 0}, {"max_term_chars": 4.5}, {"catalog_titles_read_cap": True}])
def test_invalid_config_values_fail_closed(actor, bad):
    with pytest.raises(NicheConfigMissing):
        svc(FakeStore(config={**GOOD, **bad})).suggest(actor)


def test_niche_config_needs_only_its_three_keys_not_the_whole_trend_set():
    assert isinstance(cfg.load_niche_config(GOOD), cfg.NicheConfig)
    assert isinstance(cfg.load_trend_config(GOOD), cfg.ConfigMissing)  # the full trend set is still required for reports


def test_stopword_overrides_apply_to_suggestions(actor):
    store = FakeStore(config={**GOOD, "niche_stopwords_extra": ["steel"]})
    terms = {s.term for s in svc(store).suggest(actor).suggestions}
    assert not any("steel" in t.split() for t in terms)


# ------------------------------------------------------------------------------ suggest
def test_suggestions_come_from_titles_only_are_stored_suggested_and_none_are_confirmed(actor):
    store = FakeStore()
    out = svc(store).suggest(actor)
    assert out.status == "OK" and out.confirmed == () and out.titles_read == len(TITLES)
    terms = {s.term for s in out.suggestions}
    assert "water bottle" in terms and "steel lunch box" in terms
    assert all(r.status is S.SUGGESTED and r.origin is O.CATALOG_DERIVED for r in store.rows.values())
    assert len(out.suggestions) <= GOOD["max_confirmed_niche_terms"]


def test_read_is_bounded_by_the_configured_cap(actor):
    store = FakeStore(config={**GOOD, "catalog_titles_read_cap": 2})
    out = svc(store).suggest(actor)
    assert store.read_caps == [2] and out.titles_read == 2


def test_origin_note_carries_counts_never_raw_titles(actor):
    store = FakeStore()
    svc(store).suggest(actor)
    for row in store.rows.values():
        assert row.origin_note and "distinct item titles" in row.origin_note
        assert not any(t.lower() in row.origin_note.lower() for t in TITLES)


def test_a_title_with_a_phone_number_never_yields_an_unsafe_term_T34_E20(actor):
    titles = TITLES + ["Contact 9876543210 for Steel Bottle", "Order od12345678901 steel bottle", "buy at www.shop.com steel bottle"]
    store = FakeStore(titles=titles)
    out = svc(store).suggest(actor)
    for s in out.suggestions:
        assert "9876543210" not in s.term and "od1234" not in s.term and "www" not in s.term and ".com" not in s.term
    assert all("9876543210" not in r.term for r in store.rows.values())


def test_no_titles_is_unavailable_with_the_reason_E19(actor):
    out = svc(FakeStore(titles=[])).suggest(actor)
    assert out.status == "UNAVAILABLE" and out.reason == NO_TITLES_REASON and out.suggestions == ()


def test_resuggest_is_idempotent_and_never_duplicates(actor):
    store = FakeStore()
    first = svc(store).suggest(actor)
    again = svc(store).suggest(actor)
    assert [s.term for s in first.suggestions] == [s.term for s in again.suggestions]
    assert len(store.rows) == len(first.suggestions)


def test_rejected_terms_are_not_reoffered_and_confirmed_terms_are_kept(actor):
    store = FakeStore()
    out = svc(store).suggest(actor)
    ids = {s.term: s.id for s in out.suggestions}
    svc(store).confirm(actor, [Decision(DecisionKind.REJECT, ids["water bottle"]), Decision(DecisionKind.CONFIRM, ids["steel lunch box"])])
    again = svc(store).suggest(actor)
    assert "water bottle" not in {s.term for s in again.suggestions}
    assert [c.term for c in again.confirmed] == ["steel lunch box"]


def test_seller_fact_terms_are_offered_with_their_origin_and_are_screened(actor):
    store = FakeStore(titles=[], fact_terms=["Stainless Steel Bottles", "call 9876543210"])
    out = svc(store).suggest(actor)
    assert out.status == "OK"
    assert [(s.term, s.origin) for s in out.suggestions] == [("stainless steel bottles", O.SELLER_FACT)]


# ------------------------------------------------------------------------------ confirm
def seeded(actor):
    store = FakeStore()
    out = svc(store).suggest(actor)
    return store, {s.term: s.id for s in out.suggestions}


def test_confirm_moves_only_the_chosen_terms_and_nothing_else_is_sent_AC30(actor):
    store, ids = seeded(actor)
    out = svc(store).confirm(actor, [Decision(DecisionKind.CONFIRM, ids["water bottle"]), Decision(DecisionKind.CONFIRM, ids["steel lunch box"])])
    assert {c.term for c in out.confirmed} == {"water bottle", "steel lunch box"}
    assert set(svc(store).confirmed_terms(actor)) == {"water bottle", "steel lunch box"}
    assert all(t.status is S.SUGGESTED for t in out.suggestions)  # untouched suggestions are NOT egress-eligible
    assert "yoga mat" not in svc(store).confirmed_terms(actor)


def test_confirmed_terms_never_includes_suggested_or_rejected(actor):
    store, ids = seeded(actor)
    svc(store).confirm(actor, [Decision(DecisionKind.CONFIRM, ids["water bottle"]), Decision(DecisionKind.REJECT, ids["steel lunch box"])])
    assert svc(store).confirmed_terms(actor) == ("water bottle",)


def test_edit_rejects_the_original_and_confirms_a_new_seller_stated_term(actor):
    store, ids = seeded(actor)
    out = svc(store).confirm(actor, [Decision(DecisionKind.EDIT, ids["water bottle"], "Insulated Steel Flask")])
    rows = by_term(store.rows.values())
    assert rows["water bottle"].status is S.REJECTED
    assert rows["insulated steel flask"].status is S.CONFIRMED and rows["insulated steel flask"].origin is O.SELLER_STATED
    assert [c.term for c in out.confirmed] == ["insulated steel flask"]


def test_an_edit_that_changes_nothing_is_a_confirmation(actor):
    store, ids = seeded(actor)
    svc(store).confirm(actor, [Decision(DecisionKind.EDIT, ids["water bottle"], "  WATER   bottle ")])
    assert by_term(store.rows.values())["water bottle"].status is S.CONFIRMED
    assert len(store.rows) == len(ids)


def test_an_edit_onto_an_existing_term_confirms_that_term_instead_of_duplicating(actor):
    store, ids = seeded(actor)
    svc(store).confirm(actor, [Decision(DecisionKind.EDIT, ids["water bottle"], "steel lunch box")])
    rows = by_term(store.rows.values())
    assert rows["water bottle"].status is S.REJECTED and rows["steel lunch box"].status is S.CONFIRMED
    assert len(store.rows) == len(ids)


def test_seller_typed_terms_are_confirmed_seller_stated_and_deduplicated_against_stored_terms(actor):
    store, ids = seeded(actor)
    svc(store).confirm(actor, [], ["Eco Friendly Bottle", "water  bottle"])
    rows = by_term(store.rows.values())
    assert rows["eco friendly bottle"].origin is O.SELLER_STATED and rows["eco friendly bottle"].status is S.CONFIRMED
    assert rows["water bottle"].status is S.CONFIRMED and rows["water bottle"].origin is O.CATALOG_DERIVED  # no duplicate row


def test_a_rejected_term_can_be_reconfirmed(actor):
    store, ids = seeded(actor)
    svc(store).confirm(actor, [Decision(DecisionKind.REJECT, ids["water bottle"])])
    svc(store).confirm(actor, [Decision(DecisionKind.CONFIRM, ids["water bottle"])])
    assert svc(store).confirmed_terms(actor) == ("water bottle",)


@pytest.mark.parametrize("bad", ["me@example.com", "https://x.test/a", "9876543210", "27AAPFU0939F1ZV", "ABCDE1234F", "12345", "x" * 41, "", "   "])
def test_screen_failures_on_typed_or_edited_terms_are_refused_and_change_nothing_E20(actor, bad):
    store, ids = seeded(actor)
    before = dict(store.rows)
    with pytest.raises(InvalidNicheTerms):
        svc(store).confirm(actor, [Decision(DecisionKind.CONFIRM, ids["water bottle"])], [bad])
    with pytest.raises(InvalidNicheTerms):
        svc(store).confirm(actor, [Decision(DecisionKind.EDIT, ids["steel lunch box"], bad)])
    assert store.rows == before


def test_one_bad_term_in_a_batch_applies_nothing(actor):
    store, ids = seeded(actor)
    before = dict(store.rows)
    with pytest.raises(InvalidNicheTerms) as err:
        svc(store).confirm(actor, [Decision(DecisionKind.CONFIRM, ids["water bottle"])], ["fine term", "call 9876543210"])
    assert len(err.value.rejected) == 1 and store.rows == before


def test_the_confirmed_cap_is_enforced_atomically(actor):
    store = FakeStore(config={**GOOD, "max_confirmed_niche_terms": 2})
    ids = {s.term: s.id for s in svc(store).suggest(actor).suggestions}
    svc(store).confirm(actor, [], ["one term", "two term"])
    before = dict(store.rows)
    with pytest.raises(TooManyConfirmedTerms) as err:
        svc(store).confirm(actor, [Decision(DecisionKind.CONFIRM, next(iter(ids.values())))])
    assert err.value.maximum == 2 and err.value.requested == 3 and store.rows == before


def test_a_swap_at_the_cap_is_allowed(actor):
    store = FakeStore(config={**GOOD, "max_confirmed_niche_terms": 2})
    svc(store).confirm(actor, [], ["one term", "two term"])
    one = next(r for r in store.rows.values() if r.term == "one term")
    svc(store).confirm(actor, [Decision(DecisionKind.EDIT, one.id, "uno term")])
    assert set(svc(store).confirmed_terms(actor)) == {"two term", "uno term"}


def test_unknown_term_id_is_not_found_and_changes_nothing(actor):
    store, ids = seeded(actor)
    before = dict(store.rows)
    with pytest.raises(NotFound):
        svc(store).confirm(actor, [Decision(DecisionKind.CONFIRM, ids["water bottle"]), Decision(DecisionKind.REJECT, uuid4())])
    assert store.rows == before


def test_request_shape_errors(actor):
    store, ids = seeded(actor)
    t = ids["water bottle"]
    for decisions, new in (
        ([], []), ([Decision(DecisionKind.CONFIRM, t), Decision(DecisionKind.REJECT, t)], []),
        ([Decision(DecisionKind.EDIT, t, None)], []), ([Decision(DecisionKind.CONFIRM, t, "x")], []), ([], ["same", "SAME"]),
    ):
        with pytest.raises(InvalidNicheRequest):
            svc(store).confirm(actor, decisions, new)


def test_confirmation_only_ever_touches_the_callers_tenant_store(actor):
    """Tenant comes from the Actor; the store is asked with that tenant id only."""
    seen: list[UUID] = []

    class Spy(FakeStore):
        def apply_plan(self, tenant_id, user_id, plan_fn):
            seen.append(tenant_id)
            return super().apply_plan(tenant_id, user_id, plan_fn)

    store = Spy()
    svc(store).suggest(actor)
    svc(store).confirm(actor, [], ["a term"])
    assert set(seen) == {actor.tenant_id}
