"""The fallback for a request the CEO cannot place must not narrow the product to one agent (it used to name only profit, leaks, payments and health)."""

from backend.ceo import orchestrator


def test_the_unclear_request_text_names_every_area_the_seller_can_ask_about():
    text = orchestrator._clarification_text("UNCLEAR_REQUEST").lower()
    for area in ("profit", "payments", "competitors", "product ideas", "marketing"):
        assert area in text
    assert "₹" not in text and not any(ch.isdigit() for ch in text)  # a fixed sentence with no figure in it
