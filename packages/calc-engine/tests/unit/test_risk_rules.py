"""Proactive-scan rules (docs/specs/cfo-phase3-scope.md AC-F1): each has a firing and a non-firing test, boundaries included; config missing is unavailable."""

from __future__ import annotations

from datetime import date
from fractions import Fraction as F

import pytest

from calc_engine.formulas.risk_rules import data_age_days, is_stale, margin_drop
from calc_engine.types import Unavailable

T, H = F(2), F(5)  # 2 and 5 percentage points


def test_a_margin_drop_fires_at_the_threshold_and_not_one_hair_below_it() -> None:
    r = margin_drop(F(30), F(28), T, H)
    assert r is not None and not isinstance(r, Unavailable) and r.drop_points == 2 and r.severity == "LOW"
    assert margin_drop(F(30), F(28) + F(1, 1000), T, H) is None  # 1.999 points: no signal


def test_severity_bands() -> None:
    assert margin_drop(F(30), F(26), T, H).severity == "MEDIUM"  # type: ignore[union-attr]  # 4 points = twice the threshold
    assert margin_drop(F(30), F(25), T, H).severity == "HIGH"  # type: ignore[union-attr]  # 5 points
    assert margin_drop(F(30), F(31), T, H) is None  # a rise is not a drop


def test_missing_margins_or_configuration_are_unavailable_never_no_drop() -> None:
    assert isinstance(margin_drop(None, F(10), T, H), Unavailable)
    assert isinstance(margin_drop(F(10), None, T, H), Unavailable)
    assert isinstance(margin_drop(F(30), F(20), None, H), Unavailable)
    assert isinstance(margin_drop(F(30), F(20), T, None), Unavailable)
    with pytest.raises(ValueError):
        margin_drop(F(30), F(20), F(0), H)
    with pytest.raises(ValueError):
        margin_drop(F(30), F(20), F(5), F(2))


def test_data_age_and_staleness_boundaries() -> None:
    assert data_age_days(date(2026, 10, 1), date(2026, 10, 22)) == 21 and data_age_days(date(2026, 10, 22), date(2026, 10, 22)) == 0
    assert data_age_days(date(2026, 11, 1), date(2026, 10, 22)) == 0  # a document dated in the future is not "negative age"
    assert data_age_days(None, date(2026, 10, 22)) is None
    assert is_stale(14, 14) is False and is_stale(15, 14) is True  # equality is not stale
    assert is_stale(None, 14) is True  # no order data at all
    assert isinstance(is_stale(3, None), Unavailable)
    with pytest.raises(ValueError):
        is_stale(3, 0)
