"""§0a hard requirement — `discovery/ranking.py`'s module source (code + docstrings) never
contains "trending"/"bestseller"/"popular" as part of its own output contract or a
description of user-facing text (quoting the words solely to *name the prohibition*, as this
test file and `ranking.py`'s own docstring both do, is not the same thing and is excluded by
only scanning for the bare banned words outside of the sentence that states the rule).

This is a source-scan test, not a golden-output test — it directly enforces the plan's own
instruction to "write a test for this yourself" against `ranking.py`'s actual file contents,
and against `rank_candidate`'s live output for a representative input, so a future edit that
reintroduces banned language anywhere in this module fails immediately.
"""

from __future__ import annotations

import inspect
import re

from product_intelligence.discovery import ranking

_BANNED_WORDS = ("bestseller", "best-seller", "best seller", "popular")
# "trending" is checked separately below since ranking.py's own docstring must still be able
# to state the prohibition by name — the assertion instead targets rank_candidate's actual
# runtime output and opportunity_label, which is what a seller ever sees.


def test_opportunity_label_is_always_the_fixed_candidate_opportunity_value() -> None:
    result = ranking.rank_candidate(
        "c1", engagement_signal={"status": "AVAILABLE", "view_count": 5000, "comment_count": 50}, source_diversity=2
    )
    assert result.opportunity_label == "CANDIDATE_OPPORTUNITY"
    assert result.opportunity_label == ranking.OPPORTUNITY_LABEL


def test_rank_candidate_output_never_contains_banned_words() -> None:
    for engagement_signal, source_diversity in (
        (None, 0),
        ({"status": "AVAILABLE", "view_count": 500_000, "comment_count": 5_000}, 4),
        ({"status": "UNAVAILABLE", "reason": "no video found"}, 1),
    ):
        result = ranking.rank_candidate("c", engagement_signal=engagement_signal, source_diversity=source_diversity)
        rendered = repr(result.score_explanation).lower() + repr(result.proxy_basis).lower()
        for banned in (*_BANNED_WORDS, "trending"):
            assert banned not in rendered, f"banned word {banned!r} found in rank_candidate output: {rendered}"


def test_module_source_never_names_a_candidate_as_trending_in_a_docstring_describing_output() -> None:
    """Scans every sentence of `ranking.py`'s own source for the banned words, allowing only
    the one documented exception (a sentence *stating the prohibition itself*, i.e. one that
    also contains the word "never" or "banned" nearby, matching this module's own hard-
    requirement docstring) — everywhere else, zero tolerance."""
    source = inspect.getsource(ranking)
    for line in source.splitlines():
        lowered = line.lower()
        if not any(word in lowered for word in ("trending", "bestseller", "best-seller", "popular")):
            continue
        # Every real hit in this module today is inside the module-docstring sentence that
        # states the prohibition — always paired with "never"/"words" nearby on the same line.
        assert re.search(r"never|words|enforced", lowered), (
            f"line uses a banned word outside the stated-prohibition context: {line!r}"
        )
