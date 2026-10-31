"""slim-cmo migration 20261101_0012 (performance record corrections): downgrade safety. Runs alembic downgrade/upgrade, so it is opt-in (METRION_ALLOW_DOWNGRADE_TESTS=1) and only for a scratch database.

* The downgrade is REFUSED while any correction exists, and a refused downgrade leaves everything as it was (table, forced row security, corrections, imported rows, effective numbers).
* The imported rows are never changed by a correction, by the refused downgrade, or by a safe downgrade and re-upgrade.
* When no correction exists the downgrade works, and the re-upgrade brings back the table, view, unique chain indexes, forced row security and grants, and corrections work again (stale and duplicate refused).
Synthetic rows only."""

from __future__ import annotations

import hashlib
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from tests.integration.test_accounting_cutover import ROOT, _alembic
from tests.integration.test_cmo_api import _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import ListingProvider, ru_env  # noqa: F401
from tests.integration.test_cmo_perf_correction import correct, first_line, lines

pytestmark = [
    pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres"),
    pytest.mark.skipif(os.environ.get("METRION_ALLOW_DOWNGRADE_TESTS") != "1", reason="runs alembic downgrade/upgrade against DATABASE_URL: opt in only on a scratch/CI database, never the dev DB"),
]
SLIM = os.path.join(ROOT, "..", "packages", "slim-cmo")
PREVIOUS = "20261101_0011"


def originals(env):
    rows = env.q("SELECT id::text, impressions, clicks, orders, units, sales_paise, report_date::text, report_sku FROM cmo_perf_line ORDER BY id")
    return hashlib.sha256(repr(rows).encode()).hexdigest(), len(rows)


def effective(env):
    return env.q("SELECT id::text, impressions, clicks, orders, units, sales_paise, corrected, voided FROM cmo_perf_line_effective ORDER BY id")


def table_state(env):
    return env.engine.connect().execute(text("SELECT to_regclass('cmo_perf_correction') IS NOT NULL, to_regclass('cmo_perf_line_effective') IS NOT NULL")).one()


def test_downgrade_is_refused_with_corrections_then_works_when_safe_and_reupgrades(env):
    line, got = first_line(env)
    other_line = got["lines"][1]
    assert correct(env, line, changes={"clicks": "20", "sales": "750.50"}).status_code == 200
    again = {l["lineId"]: l for l in lines(env).json()["lines"]}[line["lineId"]]
    assert correct(env, again, changes={"clicks": "25"}).status_code == 200  # a two-step chain on one record
    assert correct(env, other_line, void=True, changes={}).status_code == 200
    base_hash, base_n = originals(env)
    eff_before = effective(env)
    by_id = {r[0]: r for r in eff_before}
    assert by_id[line["lineId"]][2] == 25 and by_id[line["lineId"]][5] == 75050 and by_id[line["lineId"]][6] is True  # effective numbers use the corrected values
    assert by_id[other_line["lineId"]][2:6] == (None, None, None, None) and by_id[other_line["lineId"]][7] is True  # a void is blank, never zero
    assert env.q("SELECT clicks, sales_paise FROM cmo_perf_line WHERE id = :i", i=uuid.UUID(line["lineId"]))[0] == (10, 50000)  # the imported row is untouched
    assert env.n("cmo_perf_correction") == 3

    # 1. refused while corrections exist, and the refusal changes nothing
    refused = _alembic(SLIM, "downgrade", PREVIOUS)
    assert refused.returncode != 0 and "performance record corrections exist" in (refused.stderr + refused.stdout)
    assert table_state(env) == (True, True)
    assert env.engine.connect().execute(text("SELECT relforcerowsecurity, relrowsecurity FROM pg_class WHERE relname = 'cmo_perf_correction'")).one() == (True, True)  # forced RLS survived the failed attempt
    assert env.n("cmo_perf_correction") == 3 and originals(env) == (base_hash, base_n) and effective(env) == eff_before
    cur = _alembic(SLIM, "current")
    assert "20261101_0012" in (cur.stdout + cur.stderr)  # still at the corrections revision

    # 2. the application role still sees only its own tenant's corrections (row security enforced after the refused downgrade)
    other, _ = env.other_tenant()
    app = create_engine(os.environ["DATABASE_URL_APP"], poolclass=NullPool)
    try:
        with app.begin() as conn:
            assert conn.execute(text("SELECT count(*) FROM cmo_perf_correction")).scalar_one() == 0  # no tenant context: fails closed
        for tenant, expected in ((env.tenant, 3), (other, 0)):
            with app.begin() as conn:
                conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
                assert conn.execute(text("SELECT count(*) FROM cmo_perf_correction")).scalar_one() == expected
                assert conn.execute(text("SELECT count(*) FROM cmo_perf_line_effective")).scalar_one() == (base_n if tenant == env.tenant else 0)
        ids = env.q("SELECT import_id, report_sku, report_date FROM cmo_perf_line WHERE id = :i", i=uuid.UUID(line["lineId"]))[0]
        with pytest.raises(DBAPIError), app.begin() as conn:  # acting as another seller, the application role cannot write a correction onto this seller's record: the policy refuses it
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(other)})
            conn.execute(text("INSERT INTO cmo_perf_correction (tenant_id, line_id, import_id, marketplace, report_sku, report_date, new_clicks, changed, reason, created_by) "
                              "VALUES (:t, :l, :im, 'AMAZON', :sk, :d, 1, ARRAY['clicks'], 'cross tenant', :u)"),
                         {"t": str(env.tenant), "l": line["lineId"], "im": str(ids[0]), "sk": ids[1], "d": ids[2], "u": str(env.user_id)})
    finally:
        app.dispose()

    # 3. remove the corrections (test set-up on the scratch database only: the application role cannot, and the migration will not) so the downgrade is safe
    with env.cengine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(env.tenant)})
        conn.execute(text("DELETE FROM cmo_perf_correction WHERE tenant_id = :t"), {"t": str(env.tenant)})
    assert env.n("cmo_perf_correction") == 0
    try:
        down = _alembic(SLIM, "downgrade", PREVIOUS)
        assert down.returncode == 0, down.stderr + down.stdout
        assert table_state(env) == (False, False)
        assert env.engine.connect().execute(text("SELECT count(*) FROM pg_constraint WHERE conname = 'cmo_perf_line_tenant_id_id_key'")).scalar_one() == 0
        assert originals(env) == (base_hash, base_n)  # the imported rows came through the downgrade unchanged
    finally:
        up = _alembic(SLIM, "upgrade", "head")
        assert up.returncode == 0, up.stderr + up.stdout

    # 4. re-upgraded: everything is back, the imported rows are unchanged, the effective numbers equal the imported ones (no correction exists), and corrections work again with their guards
    assert table_state(env) == (True, True)
    assert env.engine.connect().execute(text("SELECT relforcerowsecurity FROM pg_class WHERE relname = 'cmo_perf_correction'")).scalar_one() is True
    assert env.q("SELECT has_table_privilege('metrion_app', 'cmo_perf_correction', 'UPDATE'), has_table_privilege('metrion_app', 'cmo_perf_correction', 'DELETE'), has_table_privilege('metrion_app', 'cmo_perf_correction', 'INSERT')")[0] == (False, False, True)
    idx = {r[0] for r in env.engine.connect().execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'cmo_perf_correction'"))}
    assert {"cmo_perf_correction_first_idx", "cmo_perf_correction_chain_idx"} <= idx
    assert originals(env) == (base_hash, base_n)
    assert all(r[6] is False and r[7] is False for r in effective(env)) and len(effective(env)) == base_n
    assert env.q("SELECT clicks FROM cmo_perf_line_effective WHERE id = :i", i=uuid.UUID(line["lineId"]))[0][0] == 10
    fresh = {l["lineId"]: l for l in lines(env).json()["lines"]}[line["lineId"]]
    assert fresh["corrected"] is False and fresh["correctionId"] is None
    assert correct(env, fresh, changes={"clicks": "30"}).status_code == 200
    stale = correct(env, fresh, changes={"clicks": "31"})  # still points at "no correction yet"
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "STALE"
    with pytest.raises(Exception):  # and the database itself refuses a second first-correction of the same record
        env.q("INSERT INTO cmo_perf_correction (tenant_id, line_id, import_id, marketplace, report_sku, report_date, new_clicks, changed, reason, created_by) "
              "SELECT tenant_id, line_id, import_id, marketplace, report_sku, report_date, 1, ARRAY['clicks'], 'dup first', created_by FROM cmo_perf_correction WHERE supersedes_id IS NULL")
    assert env.n("cmo_perf_correction") == 1
    assert originals(env) == (base_hash, base_n)
