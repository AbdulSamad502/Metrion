"""combine_confidence — data-foundation.md §7.1: the weakest input always wins."""

from __future__ import annotations

from calc_engine.types import Confidence, combine_confidence


def test_all_verified_stays_verified():
    assert combine_confidence(Confidence.VERIFIED, Confidence.VERIFIED) == Confidence.VERIFIED


def test_one_provisional_drags_verified_down():
    assert combine_confidence(Confidence.VERIFIED, Confidence.PROVISIONAL) == Confidence.PROVISIONAL


def test_manual_is_always_weakest():
    assert combine_confidence(Confidence.VERIFIED, Confidence.PROVISIONAL, Confidence.DERIVED, Confidence.MANUAL) == Confidence.MANUAL


def test_single_level_returns_itself():
    assert combine_confidence(Confidence.DERIVED) == Confidence.DERIVED
