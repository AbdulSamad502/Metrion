"""`backend/scripts/dev_env.py`: the dev backend says which database it uses and warns, without printing a password, when a stale shell variable overrides `backend/.env`."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev_env.py"
spec = importlib.util.spec_from_file_location("dev_env", SCRIPT)
dev_env = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(dev_env)  # type: ignore[union-attr]

MANUAL = "postgresql+psycopg://metrion_app:s3cret@localhost:5544/metrion_manual"
DEV = "postgresql+psycopg://metrion_app:other-secret@localhost:5432/metrion"


def test_the_target_names_role_host_port_and_database_and_never_the_password() -> None:
    assert dev_env.target(MANUAL) == "metrion_app@localhost:5544/metrion_manual"
    assert "s3cret" not in dev_env.target(MANUAL)
    assert dev_env.target(None) == "not set" and dev_env.target("") == "not set"
    assert dev_env.target("postgresql://u:p@host:notaport/db") == "unreadable"


def test_a_clean_shell_reports_the_file_database_with_no_warning() -> None:
    env = {"DATABASE_URL": MANUAL, "DATABASE_URL_APP": MANUAL}
    lines = dev_env.database_report(env, {"DATABASE_URL": None, "DATABASE_URL_APP": None}, env)
    assert lines == ["[run_dev] DATABASE_URL -> metrion_app@localhost:5544/metrion_manual", "[run_dev] DATABASE_URL_APP -> metrion_app@localhost:5544/metrion_manual"]


def test_a_stale_shell_variable_is_called_out_with_the_fix_and_without_secrets() -> None:
    effective = {"DATABASE_URL": DEV, "DATABASE_URL_APP": MANUAL}
    lines = dev_env.database_report(effective, {"DATABASE_URL": DEV, "DATABASE_URL_APP": None}, {"DATABASE_URL": MANUAL, "DATABASE_URL_APP": MANUAL})
    warning = [line for line in lines if "WARNING" in line]
    assert len(warning) == 1 and "DATABASE_URL is set in this shell (metrion_app@localhost:5432/metrion)" in warning[0]
    assert "overrides backend/.env (metrion_app@localhost:5544/metrion_manual)" in warning[0] and "Remove-Item Env:DATABASE_URL,Env:DATABASE_URL_APP" in warning[0]
    assert not any("secret" in line for line in lines)


def test_a_shell_value_equal_to_the_file_is_not_a_warning() -> None:
    env = {"DATABASE_URL": MANUAL, "DATABASE_URL_APP": MANUAL}
    assert not any("WARNING" in line for line in dev_env.database_report(env, env, env))


def test_an_unset_shell_or_missing_file_value_never_warns() -> None:
    assert not any("WARNING" in line for line in dev_env.database_report({"DATABASE_URL": MANUAL}, {"DATABASE_URL": MANUAL}, {}))
