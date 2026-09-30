"""§0d explainability — PI build plan Checkpoint 3's own named check: every persisted
`product_candidate` has a non-empty `score_explanation` naming every signal considered
(present or UNAVAILABLE), never just a bare `proxy_score`."""

from __future__ import annotations

from product_intelligence.discovery.ranking import rank_candidate

_REQUIRED_SIGNAL_NAMES = {
    "engagement_signal.view_count",
    "engagement_signal.comment_count",
    "source_diversity",
    "demand_signal",
}


def test_score_explanation_names_every_signal_when_fully_available() -> None:
    result = rank_candidate(
        "c1", engagement_signal={"status": "AVAILABLE", "view_count": 50_000, "comment_count": 200}, source_diversity=3
    )
    signal_names = {s["signal"] for s in result.score_explanation["signals"]}
    assert signal_names == _REQUIRED_SIGNAL_NAMES
    assert result.score_explanation["summary"]


def test_score_explanation_names_every_signal_even_when_all_unavailable() -> None:
    result = rank_candidate("c1", engagement_signal=None, source_diversity=0)
    signal_names = {s["signal"] for s in result.score_explanation["signals"]}
    assert "demand_signal" in signal_names
    assert "source_diversity" in signal_names
    assert result.score_explanation["signals"]
    assert result.proxy_state == "UNAVAILABLE"


def test_score_explanation_is_never_just_a_bare_number() -> None:
    result = rank_candidate(
        "c1", engagement_signal={"status": "AVAILABLE", "view_count": 5000, "comment_count": 10}, source_diversity=1
    )
    assert isinstance(result.score_explanation, dict)
    assert "signals" in result.score_explanation
    for signal in result.score_explanation["signals"]:
        assert signal["reason"], f"signal {signal['signal']} has no plain-language reason"
        assert signal["status"] in ("AVAILABLE", "UNAVAILABLE")


def test_demand_signal_is_always_named_unavailable_with_a_reason_this_build() -> None:
    result = rank_candidate(
        "c1", engagement_signal={"status": "AVAILABLE", "view_count": 5000, "comment_count": 10}, source_diversity=1
    )
    demand = next(s for s in result.score_explanation["signals"] if s["signal"] == "demand_signal")
    assert demand["status"] == "UNAVAILABLE"
    assert demand["reason"]
