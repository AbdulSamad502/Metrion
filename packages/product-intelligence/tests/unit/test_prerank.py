"""discovery/prerank.py — the deterministic top-5 pick made before supplier lookup (docs/specs/ceo-pi-research-flow.md C4)."""

from __future__ import annotations

from uuid import UUID

from product_intelligence.discovery.prerank import TOP_N, prerank


def _entry(n: int, proxy: str | None, state: str = "COMPUTED", positive: dict | None = None, negative: dict | None = None) -> dict:
    insights = []
    if positive is not None or negative is not None:
        insights = [{"insight_state": "COMPLETE", "positive_themes": positive or {}, "complaint_themes": negative or {}}]
    return {"candidate_id": UUID(int=n), "proxy_score": proxy, "proxy_state": state, "review_insights": insights}


def test_orders_by_score_and_returns_at_most_five() -> None:
    entries = [_entry(i, f"{i * 10}.00") for i in range(1, 9)]  # proxy 10..80
    ranked = prerank(entries)
    assert len(ranked) == TOP_N
    assert [r.candidate_id for r in ranked] == [UUID(int=8), UUID(int=7), UUID(int=6), UUID(int=5), UUID(int=4)]


def test_same_inputs_give_the_same_order_and_ties_break_by_candidate_id() -> None:
    entries = [_entry(3, "50.00"), _entry(1, "50.00"), _entry(2, "50.00")]
    first = [r.candidate_id for r in prerank(entries)]
    assert first == [UUID(int=1), UUID(int=2), UUID(int=3)]
    assert first == [r.candidate_id for r in prerank(list(reversed(entries)))]


def test_commentary_sentiment_raises_the_rank() -> None:
    plain = _entry(1, "50.00")
    liked = _entry(2, "50.00", positive={"comfort": 6}, negative={})
    ranked = prerank([plain, liked])
    assert ranked[0].candidate_id == UUID(int=2)


def test_a_candidate_with_nothing_to_rank_on_is_never_padded_in() -> None:
    ranked = prerank([_entry(1, None, state="UNAVAILABLE"), _entry(2, "40.00")])
    assert [r.candidate_id for r in ranked] == [UUID(int=2)]


def test_fewer_than_five_returns_fewer() -> None:
    assert len(prerank([_entry(1, "10.00"), _entry(2, "20.00")])) == 2


def test_explanation_names_the_supplier_signal_as_not_yet_evaluated_and_score_is_a_string() -> None:
    (r,) = prerank([_entry(1, "70.00")])
    supplier = next(s for s in r.explanation["signals"] if s["signal"] == "supplier_availability")
    assert supplier["status"] == "NOT_YET_EVALUATED"
    assert isinstance(r.prerank_score, str) and "." in r.prerank_score
    assert r.prerank_score == "40.00"  # proxy 70/100 * 40 pts = 28 of 70 pts -> 40.00/100


def test_products_with_commentary_come_before_higher_scored_products_without_it() -> None:
    no_commentary = _entry(1, "90.00")
    with_commentary = _entry(2, "40.00", positive={"comfort": 3}, negative={})
    ranked = prerank([no_commentary, with_commentary])
    assert [r.candidate_id for r in ranked] == [UUID(int=2), UUID(int=1)]  # evidence first; the other only fills the five
    assert ranked[0].explanation["has_commentary"] is True and ranked[1].explanation["has_commentary"] is False


def test_a_deal_video_or_roundup_title_is_not_a_product_and_only_fills_the_five_when_needed() -> None:
    from product_intelligence.discovery.prerank import looks_like_a_product_title

    for bad in ("[BBD Sale 2026] Best Earbuds Deals Under 1000 On Flipkart", "Top 10 earbuds", "Sony vs Bose?", "x" * 81, "", None):
        assert not looks_like_a_product_title(bad), bad
    for good in ("Sony WF-1000XM5", "CMF Buds 2", "Technics EAH-AZ100", "Wholesale Pro Buds"):
        assert looks_like_a_product_title(good), good
    deal = {**_entry(1, "90.00", positive={"x": 9}, negative={}), "candidate_title": "Best Earbuds Deals Under 1000"}
    real = {**_entry(2, "30.00"), "candidate_title": "CMF Buds 2"}
    assert [r.candidate_id for r in prerank([deal, real])] == [UUID(int=2), UUID(int=1)]  # the real product first, the deal title only fills a place
