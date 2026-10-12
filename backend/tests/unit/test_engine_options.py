"""The seven database engines (backend + six packages) share one set of connection settings. Pure unit tests: no database."""

from __future__ import annotations

import importlib
import inspect

import pytest

MODULES = (
    "backend.tenant_context",
    "calc_engine.repositories.tenant_context",
    "cfo.repositories.tenant_context",
    "competitor_intelligence.repositories.tenant_context",
    "data_foundation.repositories.tenant_context",
    "product_intelligence.repositories.tenant_context",
    "slim_cmo.repositories.tenant_context",
)
ENV = ("DB_CONNECT_TIMEOUT_SECONDS", "DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_TIMEOUT_SECONDS")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("module", MODULES)
def test_defaults_bound_the_connection_and_keep_sqlalchemys_own_pool_sizes(module):
    opts = importlib.import_module(module).engine_options()
    assert opts == {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10, "pool_timeout": 30, "connect_args": {"connect_timeout": 10}}


@pytest.mark.parametrize("module", MODULES)
def test_every_setting_can_be_overridden_per_deployment(module, monkeypatch):
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("DB_POOL_SIZE", "2")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "4")
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "7")
    opts = importlib.import_module(module).engine_options()
    assert (opts["pool_size"], opts["max_overflow"], opts["pool_timeout"], opts["connect_args"]) == (2, 4, 7, {"connect_timeout": 3})


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("name,bad", [(n, v) for n in ENV for v in ("0", "-1", "abc", "1.5")])
def test_an_invalid_value_is_an_error_not_a_silent_default(module, name, bad, monkeypatch):
    monkeypatch.setenv(name, bad)
    with pytest.raises(ValueError):
        importlib.import_module(module).engine_options()


def test_the_seven_copies_are_identical():
    sources = {m: inspect.getsource(importlib.import_module(m).engine_options) for m in MODULES}
    assert len(set(sources.values())) == 1, "engine_options() drifted between packages: " + ", ".join(sorted(sources))
