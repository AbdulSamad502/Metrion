"""Operator configuration loader (`scripts/config_admin.py`): runs as the OWNER role against the scratch database (asserted), validates against the real columns, is a dry
run unless told otherwise, inserts all rows or none, and refuses anything that is not a whitelisted configuration table."""

from __future__ import annotations

import importlib.util
import json
import os

import pytest
from sqlalchemy import make_url, text

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "config_admin.py")
METRIC = "TEST_LOADER_METRIC"

spec = importlib.util.spec_from_file_location("config_admin", SCRIPT)
config_admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_admin)  # type: ignore[union-attr]


@pytest.fixture(autouse=True)
def _scratch_only_and_clean(migrate_engine):
    assert make_url(os.environ["DATABASE_URL"]).port == 5544
    yield
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM anomaly_detection_config WHERE metric = :m"), {"m": METRIC})


def _count(migrate_engine) -> int:
    with migrate_engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM anomaly_detection_config WHERE metric = :m"), {"m": METRIC}).scalar_one()


def _rows(tmp_path, rows) -> str:
    path = tmp_path / "rows.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return str(path)


GOOD = {"metric": METRIC, "method": "Z_SCORE", "min_series_length": 6, "z_score_threshold": 2.5, "effective_from": "2026-01-01", "version": 1}


def test_a_dry_run_validates_and_inserts_nothing(tmp_path, migrate_engine, capsys):
    assert config_admin.main(["load", "anomaly_detection_config", _rows(tmp_path, [GOOD])]) == 0
    out = capsys.readouterr().out
    assert "port=5544" in out and "dry run" in out  # the destination is the first thing printed
    assert _count(migrate_engine) == 0


def test_apply_inserts_exactly_the_operators_values_including_json_columns(tmp_path, migrate_engine):
    row = {**GOOD, "delta_severity_bands": {"low": 10, "high": 30}}
    assert config_admin.main(["load", "anomaly_detection_config", _rows(tmp_path, [row]), "--apply"]) == 0
    with migrate_engine.connect() as conn:
        got = conn.execute(text("SELECT min_series_length, z_score_threshold, delta_severity_bands FROM anomaly_detection_config WHERE metric = :m"), {"m": METRIC}).one()
    assert (got[0], float(got[1]), got[2]) == (6, 2.5, {"low": 10, "high": 30})  # nothing invented, nothing defaulted


@pytest.mark.parametrize("bad,reason", [
    ({**GOOD, "surprise": 1}, "unknown column 'surprise'"),
    ({k: v for k, v in GOOD.items() if k != "min_series_length"}, "required column 'min_series_length'"),
])
def test_invalid_rows_are_refused_with_the_reason_and_nothing_is_inserted(tmp_path, migrate_engine, capsys, bad, reason):
    assert config_admin.main(["load", "anomaly_detection_config", _rows(tmp_path, [GOOD, bad]), "--apply"]) == 1
    assert reason in capsys.readouterr().err
    assert _count(migrate_engine) == 0  # the good first row was not inserted either: all or none


def test_a_database_error_rolls_back_every_row(tmp_path, migrate_engine):
    broken = {**GOOD, "version": "not-a-number"}  # passes the column check, fails in the database
    with pytest.raises(Exception):
        config_admin.main(["load", "anomaly_detection_config", _rows(tmp_path, [GOOD, broken]), "--apply"])
    assert _count(migrate_engine) == 0


def test_tables_outside_the_whitelist_are_refused(tmp_path, capsys):
    for table in ("agent_run", "tenant", "metered_event", "plan; DROP TABLE plan"):
        assert config_admin.main(["load", table, _rows(tmp_path, [{"x": 1}]), "--apply"]) == 2
    assert "not a loadable configuration table" in capsys.readouterr().err


def test_template_lists_required_columns(capsys):
    assert config_admin.main(["template", "fee_reference"]) == 0
    out = capsys.readouterr().out
    assert "marketplace" in out and "REQUIRED" in out and "id " in out


def test_the_application_role_cannot_do_what_the_tool_does(app_engine):
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    with pytest.raises((ProgrammingError, DBAPIError)):
        with app_engine.begin() as conn:
            conn.execute(text("INSERT INTO anomaly_detection_config (metric, method, min_series_length, effective_from, version) VALUES ('X','Z_SCORE',1,'2026-01-01',1)"))
