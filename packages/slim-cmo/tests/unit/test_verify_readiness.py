"""The CMO readiness check (CMO 3.0 M0): the pure part that judges one marketplace's rule row. A missing, unsourced-by-date, stale or counting-rule-less row is a blocker; nothing is defaulted."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from datetime import datetime, timedelta, timezone

_SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "verify_cmo_readiness.py"
_spec = importlib.util.spec_from_file_location("slim_cmo_verify_readiness", _SCRIPT)
assert _spec and _spec.loader
ready = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ready  # a dataclass looks its module up here
_spec.loader.exec_module(ready)

NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)


def row(**over):
    base = {"count_rule": "UTF16_CODE_UNITS", "title_max_chars": 200, "title_option_count": 5, "bullet_count": 5, "verified_at": NOW - timedelta(days=10)}
    return {**base, **over}


def test_a_complete_recent_row_is_ready():
    assert ready.assess_marketplace("AMAZON", row(), now=NOW, max_age_days=90).ok


def test_no_row_is_a_blocker_that_says_how_to_clear_it():
    st = ready.assess_marketplace("MEESHO", None, now=NOW, max_age_days=90)
    assert not st.ok and "seed_format_constraints.py" in st.reasons[0]


def test_each_missing_piece_blocks_and_is_named():
    assert "COUNTING_RULE_UNVERIFIED" in ready.assess_marketplace("AMAZON", row(count_rule=None), now=NOW, max_age_days=90).reasons[0]
    assert any("title_max_chars" in r for r in ready.assess_marketplace("AMAZON", row(title_max_chars=None), now=NOW, max_age_days=90).reasons)
    assert any("stale" in r for r in ready.assess_marketplace("AMAZON", row(verified_at=NOW - timedelta(days=91)), now=NOW, max_age_days=90).reasons)


def test_staleness_is_not_guessed_when_the_window_is_not_configured():
    st = ready.assess_marketplace("AMAZON", row(), now=NOW, max_age_days=None)
    assert not st.ok and "not configured" in st.reasons[0]


def test_missing_keys_are_listed_in_order():
    assert ready.missing_keys({"internal_retry_bound"}, ready.GENERATION_KEYS) == ["format_constraint_max_age_days"]
