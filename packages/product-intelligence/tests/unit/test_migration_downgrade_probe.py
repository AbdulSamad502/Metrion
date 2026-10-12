"""Practical-acceptance finding: `product-intelligence downgrade base` failed with `relation "tenant" does not exist` in the order CI runs the round trips (every package before the backend, which
owns `tenant`). The downgrade of 20261011_0002 refuses to destroy stored accounting decisions, so it probes each tenant; with no `tenant` table there is nobody to protect. These unit tests
drive that probe with a fake connection (no database): the missing-table case must pass quietly, and the protective refusal must still fire when a stored decision exists."""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

PATH = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "20261011_0002_pi_run_accounting.py"


def load():
    spec = importlib.util.spec_from_file_location("pi_run_accounting_migration", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Result:
    def __init__(self, rows): self.rows = rows
    def scalar(self): return self.rows[0][0] if self.rows else None
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None


class _Probe:
    def __init__(self, answers): self.answers, self.seen = answers, []
    def execute(self, statement, params=None):
        sql = str(statement)
        self.seen.append(sql)
        for needle, rows in self.answers.items():
            if needle in sql:
                return _Result(rows)
        return _Result([])


def run(mod, probe):
    @contextmanager
    def connect():
        yield probe

    bind = mock.Mock()
    bind.engine.connect = connect
    with mock.patch.object(mod.op, "get_bind", return_value=bind):
        mod._refuse_if_rows_exist()


def test_no_tenant_table_yet_means_nothing_to_protect_and_the_probe_does_not_query_it():
    probe = _Probe({"to_regclass": [(None,)]})
    run(load(), probe)
    assert not any("FROM tenant" in s for s in probe.seen)


def test_with_tenants_and_a_stored_accounting_decision_the_downgrade_is_still_refused():
    probe = _Probe({"to_regclass": [("tenant",)], "FROM tenant": [("t-1",)], "FROM pi_research_run": [(1,)]})
    with pytest.raises(RuntimeError, match="stored accounting decisions"):
        run(load(), probe)


def test_with_tenants_and_no_stored_decision_the_downgrade_proceeds():
    probe = _Probe({"to_regclass": [("tenant",)], "FROM tenant": [("t-1",)]})
    run(load(), probe)
