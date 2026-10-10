"""Following up on a numbered list of ideas (spec 6.35): deterministic, only in range, only when the list exists."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.ceo import references
from backend.ceo.composer import WEB_ARTEFACT_TITLE

IDEAS = ["Alpha Shoe", "Beta Shoe", "Gamma Shoe"]


def finding(items=IDEAS, source="PI", at=1, title=WEB_ARTEFACT_TITLE):
    return {"source": source, "created_at": datetime(2026, 10, at, tzinfo=timezone.utc), "presentation": {"artefacts": [{"title": title, "items": items, "note": None}]}}


@pytest.mark.parametrize("text,expected", [
    ("write titles for #2", "write titles for Beta Shoe"),
    ("hashtags for number 3", "hashtags for Gamma Shoe"),
    ("GST rate for the second one", "GST rate for Beta Shoe"),
    ("titles for the 1st idea", "titles for Alpha Shoe"),
    ("hashtags for the last one", "hashtags for Gamma Shoe"),
    ("hashtags for the first product", "hashtags for Alpha Shoe"),
])
def test_references_become_the_names_from_the_list_the_seller_saw(text, expected):
    out, notes = references.expand([finding()], text)
    assert out == expected and len(notes) == 1 and "from the product ideas above" in notes[0]


@pytest.mark.parametrize("text", ["write titles for #4", "titles for #0", "hashtags for the tenth one", "give me #steelbottle hashtags", "nothing to refer to"])
def test_out_of_range_or_unrelated_text_is_left_exactly_as_typed(text):
    assert references.expand([finding()], text) == (text, [])


def test_without_a_list_nothing_is_substituted():
    assert references.expand([], "titles for #2") == ("titles for #2", [])
    assert references.expand([finding(source="CMO")], "titles for #2") == ("titles for #2", [])  # only Product Intelligence lists count
    assert references.expand([finding(title="Hashtags for Amazon")], "titles for #2")[1] == []  # not a list of ideas


def test_the_newest_list_wins():
    out, _ = references.expand([finding(["Old One", "Old Two"], at=1), finding(["New One", "New Two"], at=2)], "titles for #1")
    assert out == "titles for New One"
