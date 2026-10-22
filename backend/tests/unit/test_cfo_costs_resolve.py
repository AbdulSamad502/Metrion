"""Cost-ownership arbitration, pure (docs/specs/cfo-expense-ledger.md D5 / AC-L8): for a component, a marketplace and a period exactly one source counts."""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from backend.services.cfo_costs import Item, Sources, resolve


def pool(comp: str, amount: int, mp: str | None = None) -> Item:
    return Item(comp, mp, {"amount_paise": amount, "marketplace": mp}, "POOL")


def led(comp: str, amount: int, mp: str | None = None) -> Item:
    return Item(comp, mp, {"amount_paise": amount, "marketplace": mp}, "LEDGER")


def rep(amount: int, mp: str) -> Item:
    return Item("ADVERTISING", mp, {"amount_paise": amount, "marketplace": mp}, "REPORT")


def amounts(r) -> list[int]:  # noqa: ANN001
    return sorted(int(v["amount_paise"]) for v in [*r.advertising, *r.other])  # type: ignore[call-overload]


NONE = lambda component, marketplace: None  # noqa: E731


def chose(owner: str):  # noqa: ANN201
    return lambda component, marketplace: owner


def test_a_single_source_counts_whatever_it_is() -> None:
    assert amounts(resolve(Sources([pool("PACKAGING", 100)]), ["MEESHO"], NONE)) == [100]
    assert amounts(resolve(Sources(ledger=[led("PACKAGING", 100)]), ["MEESHO"], NONE)) == [100]
    assert amounts(resolve(Sources(reports=[rep(100, "MEESHO")]), ["MEESHO"], NONE)) == [100]
    assert amounts(resolve(Sources(), ["MEESHO"], NONE)) == []


def test_pool_and_ledger_for_the_same_cost_never_count_twice_and_the_established_pool_wins_until_the_seller_chooses() -> None:
    r = resolve(Sources([pool("PACKAGING", 100)], [led("PACKAGING", 70)]), ["MEESHO"], NONE)
    assert amounts(r) == [100] and len(r.conflicts) == 1 and r.conflicts[0].component == "PACKAGING" and r.conflicts[0].marketplace == "ALL" and r.conflicts[0].counted == "POOL"
    assert amounts(resolve(Sources([pool("PACKAGING", 100)], [led("PACKAGING", 70)]), ["MEESHO"], chose("LEDGER"))) == [70]
    chosen_pool = resolve(Sources([pool("PACKAGING", 100)], [led("PACKAGING", 70)]), ["MEESHO"], chose("POOL"))
    assert amounts(chosen_pool) == [100] and chosen_pool.conflicts == []


def test_a_choice_for_a_source_that_is_not_present_is_no_choice() -> None:
    r = resolve(Sources([pool("PACKAGING", 100)], [led("PACKAGING", 70)]), ["MEESHO"], chose("REPORT"))
    assert amounts(r) == [100] and len(r.conflicts) == 1  # REPORT does not exist for packaging


def test_components_are_independent_a_packaging_conflict_leaves_advertising_alone() -> None:
    r = resolve(Sources([pool("PACKAGING", 100), pool("ADVERTISING", 40)], [led("PACKAGING", 70)]), ["MEESHO"], NONE)
    assert amounts(r) == [40, 100] and [c.component for c in r.conflicts] == ["PACKAGING"]
    assert r.advertising == [{"amount_paise": 40, "marketplace": None}] and r.other == [{"amount_paise": 100, "marketplace": None}]


def test_each_marketplace_is_arbitrated_on_its_own() -> None:
    src = Sources([pool("ADVERTISING", 30, "MEESHO")], [led("ADVERTISING", 20, "MEESHO"), led("ADVERTISING", 55, "FLIPKART")], [rep(90, "AMAZON")])
    r = resolve(src, ["MEESHO", "FLIPKART", "AMAZON"], NONE)
    assert amounts(r) == [30, 55, 90] and [(c.component, c.marketplace) for c in r.conflicts] == [("ADVERTISING", "MEESHO")]
    only_meesho = resolve(src, ["MEESHO"], chose("LEDGER"))
    assert amounts(only_meesho) == [20]  # the other marketplaces are out of scope


def test_a_report_and_a_marketplace_pool_conflict_and_the_pool_keeps_counting_until_the_seller_chooses() -> None:
    src = Sources([pool("ADVERTISING", 30, "MEESHO")], reports=[rep(90, "MEESHO")])
    assert amounts(resolve(src, ["MEESHO"], NONE)) == [30]
    assert amounts(resolve(src, ["MEESHO"], chose("REPORT"))) == [90]
    assert amounts(resolve(src, ["MEESHO"], chose("POOL"))) == [30]


def test_an_account_wide_cost_entered_by_hand_conflicts_with_reports_so_both_are_never_counted() -> None:
    src = Sources([pool("ADVERTISING", 500)], reports=[rep(90, "MEESHO"), rep(10, "FLIPKART")])
    unresolved = resolve(src, ["MEESHO", "FLIPKART"], NONE)
    assert amounts(unresolved) == [500] and unresolved.conflicts[0].marketplace == "ALL"  # the hand-entered figure keeps counting; the reports are dropped
    assert amounts(resolve(src, ["MEESHO", "FLIPKART"], chose("REPORT"))) == [10, 90]  # the account-wide entry is excluded
    assert amounts(resolve(src, ["MEESHO", "FLIPKART"], chose("POOL"))) == [500]
    ledger_wins = resolve(Sources([pool("ADVERTISING", 500)], [led("ADVERTISING", 480)], [rep(90, "MEESHO")]), ["MEESHO"], chose("LEDGER"))
    assert amounts(ledger_wins) == [480]


def test_an_account_wide_cost_does_not_conflict_with_reports_outside_the_scope() -> None:
    r = resolve(Sources([pool("ADVERTISING", 500)], reports=[rep(90, "AMAZON")]), ["MEESHO"], NONE)
    assert amounts(r) == [500] and r.conflicts == []


@settings(deadline=None, max_examples=500)
@given(st.lists(st.tuples(st.sampled_from(["ADVERTISING", "PACKAGING", "OTHER"]), st.sampled_from([None, "MEESHO", "FLIPKART"]), st.integers(1, 10**6),
                          st.sampled_from(["POOL", "LEDGER", "REPORT"])), max_size=14),
       st.sampled_from([None, "POOL", "LEDGER", "REPORT"]))
def test_property_two_sources_never_both_count_for_one_component_and_marketplace(rows, owner) -> None:  # noqa: ANN001
    pools = [pool(c, a, mp) for c, mp, a, s in rows if s == "POOL"]
    ledger = [led(c, a, mp) for c, mp, a, s in rows if s == "LEDGER"]
    reports = [rep(a, mp) for c, mp, a, s in rows if s == "REPORT" and mp is not None]
    r = resolve(Sources(pools, ledger, reports), ["MEESHO", "FLIPKART"], (lambda c, m: owner) if owner else NONE)
    seen: dict[tuple[str, str | None], set[str]] = {}
    for it in r.counted:
        seen.setdefault((it.component, it.marketplace), set()).add(it.source)
    assert all(len(sources) == 1 for sources in seen.values())
    assert len(r.advertising) + len(r.other) == len(r.counted)
