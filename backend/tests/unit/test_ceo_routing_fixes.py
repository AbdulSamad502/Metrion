"""Table-driven regression test for CEO routing fixes:
- General contribution-margin and profit explanations
- Marketing-plan requests
- CI competitor discovery and comparison
- Product-evaluation questions
"""

from __future__ import annotations

import pytest

from backend.ceo import intent_router
from backend.ceo.classifier import build_catalog
from backend.ceo.plans import ACTIONS, PLAYBOOKS

CAT = build_catalog(list(ACTIONS.keys()), list(PLAYBOOKS.keys()), {})


@pytest.mark.parametrize(
    ("query", "expected_route", "expected_key", "expected_slots"),
    [
        ("Explain contribution margin", "ADVISORY", None, {}),
        ("What is contribution margin?", "ADVISORY", None, {}),
        ("How does contribution margin work?", "ADVISORY", None, {}),
        ("What does contribution margin mean?", "ADVISORY", None, {}),
        ("Can you explain contribution margin?", "ADVISORY", None, {}),
        ("Help me create a marketing plan", "ADVISORY", None, {}),
        ("Marketing plan for my store", "ADVISORY", None, {}),
        ("Marketing strategy for online sales", "ADVISORY", None, {}),
        ("Find competitors for my 1L steel bottle", "ACTION", "ci.discover_competitors", {"product": "1L steel bottle"}),
        ("Discover competitors for yoga mat", "ACTION", "ci.discover_competitors", {"product": "yoga mat"}),
        ("Compare my price with competitors", "CLARIFY", None, {}),
        ("Compare prices with competitors", "CLARIFY", None, {}),
        ("Is this product worth selling?", "PLAYBOOK", "NEW_PRODUCT_DECISION", {}),
        ("Evaluate this product", "PLAYBOOK", "NEW_PRODUCT_DECISION", {}),
        ("Product evaluation for wireless earbuds", "PLAYBOOK", "NEW_PRODUCT_DECISION", {"product": "wireless earbuds"}),
        ("Product feasibility for wireless earbuds", "PLAYBOOK", "NEW_PRODUCT_DECISION", {"product": "wireless earbuds"}),
    ],
)
def test_confirmed_routing_failures_resolved(query: str, expected_route: str, expected_key: str | None, expected_slots: dict[str, str]) -> None:
    decision = intent_router.route(query, CAT)
    assert decision is not None, f"Query '{query}' unexpectedly fell through to model"
    assert decision.route == expected_route
    if expected_key is not None:
        assert decision.key == expected_key
    for slot_k, slot_v in expected_slots.items():
        assert decision.slots.get(slot_k) == slot_v
