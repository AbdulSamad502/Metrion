"""discovery/shortlist_scoring.py — Stage 4's second composite score, §0f. The core
"not a copy of Stage 1" requirement is checked explicitly below."""

from __future__ import annotations

from product_intelligence.discovery.shortlist_scoring import score_shortlist


def _entry(*, proxy_score, proxy_state="COMPUTED", review_insights=None, supplier_leads=None, budget_paise=None):
    return {
        "candidate_id": "c1",
        "proxy_score": proxy_score,
        "proxy_state": proxy_state,
        "review_insights": review_insights or [],
        "supplier_leads": supplier_leads or [],
        "budget_paise": budget_paise,
    }


def test_final_score_state_unavailable_when_nothing_is_available() -> None:
    [scored] = score_shortlist([_entry(proxy_score=None, proxy_state="UNAVAILABLE")])
    assert scored.final_score_state == "UNAVAILABLE"
    assert scored.final_score is None


def test_final_score_uses_proxy_review_and_supplier_signals_together() -> None:
    entry = _entry(
        proxy_score="50.00",
        review_insights=[
            {"insight_state": "COMPLETE", "positive_themes": {"battery life": 5}, "complaint_themes": {}}
        ],
        supplier_leads=[{"contact": {"moq": None}}],
    )
    [scored] = score_shortlist([entry])
    assert scored.final_score_state == "COMPUTED"
    signals = {s["signal"]: s for s in scored.final_score_explanation["signals"]}
    assert signals["proxy_score"]["status"] == "AVAILABLE"
    assert signals["review_sentiment_quality"]["status"] == "AVAILABLE"
    assert signals["supplier_availability"]["status"] == "AVAILABLE"


def test_final_score_diverges_from_stage1_proxy_score_when_review_sentiment_moves_it() -> None:
    """Stage 4 independence — two candidates with the IDENTICAL Stage 1 proxy_score but
    different review-sentiment signal must NOT produce the same final_score; a bare
    re-export/copy of proxy_score would make these equal, which this test forbids."""
    positive_entry = _entry(
        proxy_score="50.00",
        review_insights=[
            {"insight_state": "COMPLETE", "positive_themes": {"quality": 10}, "complaint_themes": {}}
        ],
    )
    negative_entry = _entry(
        proxy_score="50.00",
        review_insights=[
            {"insight_state": "COMPLETE", "positive_themes": {}, "complaint_themes": {"battery life": 10}}
        ],
    )

    [positive_scored] = score_shortlist([positive_entry])
    [negative_scored] = score_shortlist([negative_entry])

    assert positive_scored.final_score != negative_scored.final_score
    assert float(positive_scored.final_score) > float(negative_scored.final_score)


def test_final_score_diverges_from_stage1_proxy_score_when_supplier_availability_moves_it() -> None:
    """Same Stage 1 proxy_score, only supplier-availability signal differs — final_score must
    move, proving Stage 4 combines a genuinely new signal rather than re-deriving Stage 1's."""
    no_supplier_entry = _entry(proxy_score="60.00", supplier_leads=[])
    with_supplier_entry = _entry(
        proxy_score="60.00",
        supplier_leads=[{"contact": {"moq": {"unit_price_paise": 1_000, "quantity": 10}}}],
        budget_paise=50_000,
    )

    [no_supplier_scored] = score_shortlist([no_supplier_entry])
    [with_supplier_scored] = score_shortlist([with_supplier_entry])

    assert no_supplier_scored.final_score != with_supplier_scored.final_score
    assert float(with_supplier_scored.final_score) > float(no_supplier_scored.final_score)


def test_supplier_moq_fitting_budget_earns_more_than_moq_not_fitting() -> None:
    fits = _entry(
        proxy_score="10.00",
        supplier_leads=[{"contact": {"moq": {"unit_price_paise": 1_000, "quantity": 10}}}],
        budget_paise=50_000,
    )
    does_not_fit = _entry(
        proxy_score="10.00",
        supplier_leads=[{"contact": {"moq": {"unit_price_paise": 1_000, "quantity": 1_000}}}],
        budget_paise=50_000,
    )

    [fits_scored] = score_shortlist([fits])
    [does_not_fit_scored] = score_shortlist([does_not_fit])

    assert float(fits_scored.final_score) > float(does_not_fit_scored.final_score)


def test_no_banned_words_in_output() -> None:
    entry = _entry(proxy_score="80.00", review_insights=[{"insight_state": "COMPLETE", "positive_themes": {"a": 1}, "complaint_themes": {}}])
    [scored] = score_shortlist([entry])
    rendered = repr(scored.final_score_explanation).lower()
    for banned in ("trending", "bestseller", "best-seller", "best seller", "popular"):
        assert banned not in rendered
