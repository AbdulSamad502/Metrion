"""7e: the two new trend keys fail closed like every other (no code default), and flow into the config snapshot."""

import pytest

from slim_cmo import config as cfg

from .factories import trend_config, trend_values

NEW = ("provider_cache_ttl_hours", "provider_daily_search_ceiling")


@pytest.mark.parametrize("key", NEW)
def test_a_missing_key_is_config_missing_and_names_the_key(key):
    values = trend_values()
    del values[key]
    result = cfg.load_trend_config(values)
    assert isinstance(result, cfg.ConfigMissing) and result.missing == (key,)


@pytest.mark.parametrize("key", NEW)
@pytest.mark.parametrize("bad", [None, 0, -1, True, 24.0, "24", [24]])
def test_an_invalid_value_is_refused_never_defaulted(key, bad):
    result = cfg.load_trend_config(trend_values(**{key: bad}))
    assert isinstance(result, cfg.ConfigMissing) and key in {*result.missing, *(k for k, _ in result.invalid)}


def test_the_values_are_carried_into_the_typed_config_and_the_report_snapshot():
    c = trend_config(provider_cache_ttl_hours=24, provider_daily_search_ceiling=20)
    assert (c.provider_cache_ttl_hours, c.provider_daily_search_ceiling) == (24, 20)
    snap = c.snapshot()
    assert snap["provider_cache_ttl_hours"] == 24 and snap["provider_daily_search_ceiling"] == 20


def test_the_new_keys_are_required_for_a_trend_report():
    assert set(NEW) <= set(cfg.TREND_REQUIRED_KEYS)


def test_the_reviewable_cap_seed_targets_the_cmo_trend_meter_only_and_leaves_the_shared_meter_unseeded():
    import pathlib

    from slim_cmo.billing import Action

    sql = (pathlib.Path(__file__).resolve().parents[2] / "scripts" / "seed_trend_report_cap.sql").read_text(encoding="utf-8")
    assert f"'{Action.MARKET_TRENDS.value}'" in sql and "'MONTH'" in sql and ", 5, CURRENT_DATE" in sql
    code = [line for line in sql.splitlines() if not line.lstrip().startswith("--")]
    inserts = [line for line in code if line.lstrip().startswith("INSERT")]
    assert len(inserts) == 1 and "research.market_trends" not in " ".join(code)
