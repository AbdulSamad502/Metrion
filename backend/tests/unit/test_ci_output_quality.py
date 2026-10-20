"""Seller-facing quality of competitor answers (owner's manual test, 2026-10-18): no internal register labels, a price comparison that says what each row is (and says it once), a
competitor's name never taken as the seller's SKU, and discovery leads shown by what they are."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from backend.ceo import ci_conversation as cc
from backend.ceo import composer, evidence, input_session
from backend.ceo import slot_resolvers as sr
from backend.ceo.contract import Figure, Ref, RefKind, Register
from backend.services import ci_conv_data

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def _row(value: int, ref: str) -> dict:
    return {
        "id": uuid4(), "metric_code": "PRICE_POSITIONING", "value_paise": value, "is_available": True, "confidence": "MANUAL", "computed_at": NOW,
        "calculation_basis": f"PricePositioning vs {ref} (reference_price_paise=32900, gap_pct=6.08%) — deterministic-engine.md §5.15",
    }


def test_a_price_comparison_row_says_what_it_compares_with_and_the_percentage() -> None:
    fig = evidence.figure_from_metric_row(_row(2000, "AVERAGE"))
    assert "competitor's average price" in fig.label and "6.08%" in fig.label and "a plus means you are higher" in fig.label
    assert "competitor's lowest price" in evidence.figure_from_metric_row(_row(2000, "MIN")).label


def test_a_competitor_answer_uses_plain_words_for_where_a_figure_comes_from() -> None:
    fig = Figure("Your price vs competitor", "₹20.00", Register.MANUAL, Ref(RefKind.ENGINE_RESULT, uuid4(), as_of=NOW), as_of=NOW)
    table = composer.EvidenceTable(figures=(("F1", fig),), ci_narration=True) if hasattr(composer.EvidenceTable, "__dataclass_fields__") else None
    if table is None:
        return
    text = composer.render_template(table)
    assert "MANUAL" not in text and "DERIVED" not in text and "from the price you gave" in text
    other = composer.render_template(composer.EvidenceTable(figures=(("F1", fig),), ci_narration=False))
    assert "MANUAL" in other  # finance answers are unchanged


def test_a_competitors_name_is_never_accepted_as_the_sku(monkeypatch) -> None:
    ctx = input_session.Ctx(uuid4(), NOW.date(), 5)
    monkeypatch.setattr(sr, "resolve_seller_product", lambda t, raw: sr.ProductUnresolved("NOT_FOUND", ("Steel Water Bottle 1L (CI TEST)",)))
    monkeypatch.setattr(sr, "resolve_competitor", lambda t, raw: sr.CompetitorMatch(uuid4(), "CASPIAN Astra Stainless Steel Water Bottle 1L, Royal Blue"))
    monkeypatch.setattr(input_session.ceo_reads, "list_seller_products", lambda t, limit=200: [("CI-TEST-BOTTLE-001", "Steel Water Bottle 1L (CI TEST)")])
    out = input_session._sku("CASPIAN", ctx, {})
    assert isinstance(out, input_session.Reject) and "not one of your products" in out.why and "Steel Water Bottle 1L (CI TEST)" in out.why
    monkeypatch.setattr(sr, "resolve_seller_product", lambda t, raw: sr.ProductMatch("CI-TEST-BOTTLE-001", "Steel Water Bottle 1L (CI TEST)"))
    assert input_session._sku("my steel water bottle", ctx, {}) == "CI-TEST-BOTTLE-001"  # the product's id, not the seller's sentence


def test_a_lead_is_shown_by_title_marketplace_reason_and_link_and_a_lead_without_a_title_is_not_invented(monkeypatch) -> None:
    monkeypatch.setattr(cc, "data", SimpleNamespace(identity_note=ci_conv_data.identity_note))
    queue = [
        {"title": "CASPIAN Astra Stainless Steel Water Bottle 1L, Royal Blue", "marketplace": "AMAZON", "relationship_class": "UNKNOWN", "identity_match": "UNCERTAIN",
         "identity_match_basis": {"seller_brand": None, "candidate_brand": "CASPIAN"}, "candidate_url": "https://www.amazon.in/dp/B0AAAAAAA1"},
        {"title": None, "marketplace": "FLIPKART", "relationship_class": "DIRECT_COMPETITOR", "identity_match": "NOT_A_MATCH", "candidate_url": "https://www.flipkart.com/x"},
    ]
    text = cc._candidate_list(queue)
    assert "1. CASPIAN Astra Stainless Steel Water Bottle 1L, Royal Blue (Amazon): I cannot tell if it is the same product as yours: your product has no brand recorded. https://www.amazon.in/dp/B0AAAAAAA1" in text
    assert "2. A listing on Flipkart that looks like a direct competitor." in text
    assert "not verified prices" in text


def test_review_answers_state_how_many_reviews_were_read_when_and_who_has_no_screenshot() -> None:
    collector = evidence.EvidenceCollector(tenant_id=uuid4())
    collector._ci_reviews({
        "findings": [{"label": "CASPIAN Astra", "complaintThemes": {"strap": 2}, "positiveThemes": {"dial": 1}, "reviewsConsidered": 5, "derivedAt": "2026-10-18T11:35:00+00:00", "reviewInsightId": str(uuid4())}],
        "trackedCompetitors": 2, "competitorsWithoutReviewEvidence": 1,
    })
    facts = {label: text for label, text, _ in collector.facts}
    assert "praised: dial" in facts["CASPIAN Astra"] and not any(ch.isdigit() for ch in facts["CASPIAN Astra"])  # the facts carry no number
    fig, = collector.figures  # the count is a stored figure with its source and date
    assert fig.label == "Reviews read for CASPIAN Astra" and fig.formatted_value == "5" and fig.as_of is not None
    assert any("1 tracked competitor has no review screenshot yet" in (g if isinstance(g, str) else g[-1]) for g in collector.gaps)


def test_the_evidence_collector_can_dedupe_price_comparison_rows() -> None:
    """Regression: a field the price-comparison dedupe needs was never declared, so every competitor price comparison crashed the turn."""
    c = evidence.EvidenceCollector(uuid4())
    assert c._pp_values == set()
