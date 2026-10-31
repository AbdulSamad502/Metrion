"""Corrections to wrongly imported performance records (migration slim-cmo 20261101_0012): the imported row is never changed, the correction is append-only with reason, actor and both values, the numbers use
the corrected value, a stale or competing correction is refused, blanks stay blank, and another seller can neither see nor correct the record. Synthetic rows in a scratch database; no model, no credit.
(Written with the feature; see the docs for whether it has been run.)"""

from __future__ import annotations

import os
import uuid

import pytest

from backend.auth.permissions import PARTNER_ROLE
from tests.integration.test_cmo_api import _erase_cmo_rows, _login, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m8_performance import get, importing, report, span
from tests.integration.test_cmo_m6_integration import ListingProvider, ru_env  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


def lines(env, headers=None, **params):
    return env.client().get("/api/v1/cmo/performance/lines", params={"marketplace": "AMAZON", **params}, headers=env.headers if headers is None else headers)


def history(env, headers=None, **params):
    return env.client().get("/api/v1/cmo/performance/correction-history", params=params, headers=env.headers if headers is None else headers)


def correct(env, line, headers=None, **body):
    return env.client().post("/api/v1/cmo/performance/corrections", json={"line_id": line["lineId"], "reason": "I typed the wrong number", "expected_correction_id": line["correctionId"], **body},
                             headers=env.headers if headers is None else headers)


def first_line(env):
    importing(env, report(span(3, 0)))
    got = lines(env).json()
    assert got["total"] == 4
    return got["lines"][0], got


def test_the_original_stays_and_the_correction_records_both_values_the_reason_and_the_actor(env):
    line, _ = first_line(env)
    r = correct(env, line, changes={"clicks": "20", "sales": "750.50"})
    body = r.json()
    assert r.status_code == 200 and body["changed"] == ["clicks", "sales"] and body["previous"]["clicks"] == 10 and body["now"]["clicks"] == 20 and body["now"]["sales"] == 75050 and body["aiCredits"] == 0
    assert env.q("SELECT clicks, sales_paise FROM cmo_perf_line WHERE id = :i", i=uuid.UUID(line["lineId"]))[0] == (10, 50000)  # the imported row is untouched
    row = env.q("SELECT prev_clicks, new_clicks, prev_sales_paise, new_sales_paise, reason, created_by, voided, changed, supersedes_id FROM cmo_perf_correction")[0]
    assert (row[0], row[1], row[2], row[3], row[4], str(row[5]), row[6], list(row[7]), row[8]) == (10, 20, 50000, 75050, "I typed the wrong number", str(env.user_id), False, ["clicks", "sales"], None)
    again = {l["lineId"]: l for l in lines(env).json()["lines"]}[line["lineId"]]
    assert again["corrected"] is True and again["original"]["clicks"] == 10 and again["effective"]["clicks"] == 20 and again["correctionId"] == body["correctionId"]


def test_the_numbers_use_the_corrected_value(env):
    line, _ = first_line(env)
    before = get(env, "dashboard", marketplace="AMAZON").json()
    correct(env, line, changes={"clicks": "30"})
    after = get(env, "dashboard", marketplace="AMAZON").json()
    assert after["correctedRecords"] == 1 and before["correctedRecords"] == 0
    b, a = before["current"]["metrics"]["clicks"], after["current"]["metrics"]["clicks"]
    if b["state"] == "AVAILABLE" and a["state"] == "AVAILABLE":
        assert a["value"] == b["value"] + 20
    assert any("corrected" in l for l in after["limits"]) or after["current"]["metrics"]["clicks"]["state"] != "AVAILABLE"


def test_a_blank_stays_not_reported_and_a_void_blanks_everything_never_zero(env):
    line, _ = first_line(env)
    r = correct(env, line, changes={"units": ""}).json()
    assert r["now"]["units"] is None and r["now"]["clicks"] == 10
    nxt = {l["lineId"]: l for l in lines(env).json()["lines"]}[line["lineId"]]
    v = correct(env, nxt, void=True, changes={}).json()
    assert v["voided"] is True and all(x is None for x in v["now"].values())
    assert env.q("SELECT clicks, units FROM cmo_perf_line_effective WHERE id = :i", i=uuid.UUID(line["lineId"]))[0] == (None, None)


def test_a_reason_a_real_change_and_possible_values_are_required(env):
    line, _ = first_line(env)
    assert correct(env, line, changes={"clicks": "20"}, reason="").status_code == 422
    assert correct(env, line, changes={"clicks": "10"}).status_code == 409  # same as the effective value
    assert correct(env, line, changes={}).status_code == 422
    assert correct(env, line, changes={"clicks": "abc"}).status_code == 422
    assert correct(env, line, changes={"clicks": "-1"}).status_code == 422
    assert correct(env, line, changes={"clicks": "500"}).status_code == 422  # more clicks than impressions
    assert correct(env, line, changes={"colour": "5"}).status_code == 422
    assert correct(env, line, void=True, changes={"clicks": "5"}).status_code == 422
    assert env.n("cmo_perf_correction") == 0
    assert env.client().post("/api/v1/cmo/performance/corrections", json={"line_id": str(uuid.uuid4()), "reason": "because", "changes": {"clicks": "1"}}, headers=env.headers).status_code == 404


def test_a_stale_or_competing_correction_is_refused_so_two_cannot_both_win(env):
    line, _ = first_line(env)
    assert correct(env, line, changes={"clicks": "20"}).status_code == 200
    stale = correct(env, line, changes={"clicks": "25"})  # still points at "no correction yet"
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "STALE"
    current = {l["lineId"]: l for l in lines(env).json()["lines"]}[line["lineId"]]
    assert correct(env, current, changes={"clicks": "25"}).status_code == 200
    assert env.n("cmo_perf_correction") == 2
    chain = env.q("SELECT count(*) FROM cmo_perf_correction WHERE supersedes_id IS NULL")[0][0]
    assert chain == 1


def test_history_lists_every_correction_with_before_after_reason_and_who(env):
    line, _ = first_line(env)
    correct(env, line, changes={"orders": "1"}, reason="Order count was a typo")
    h = history(env, marketplace="AMAZON").json()
    c = h["corrections"][0]
    assert h["aiCredits"] == 0 and c["reason"] == "Order count was a typo" and c["previous"]["orders"] == 2 and c["corrected"]["orders"] == 1 and c["changed"] == ["orders"] and c["by"] == str(env.user_id)


def test_another_seller_cannot_see_or_correct_the_record_and_permissions_are_enforced(env):
    line, _ = first_line(env)
    other, other_headers = env.other_tenant()
    assert lines(env, headers=other_headers).json()["total"] == 0
    assert correct(env, line, headers=other_headers, changes={"clicks": "20"}).status_code == 404
    assert env.n("cmo_perf_correction", tenant=other) == 0 and env.n("cmo_perf_correction") == 0
    assert correct(env, line, headers={}, changes={"clicks": "20"}).status_code == 401
    only_read, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={"agent.cmo": True})
    denied = correct(env, line, headers=only_read, changes={"clicks": "20"})
    assert denied.status_code == 403 and "files.upload" in str(denied.json()) and lines(env, headers=only_read).status_code == 200


def test_the_application_role_can_only_read_and_add_corrections_and_security_is_forced(env):
    for t in ("cmo_perf_correction",):
        assert env.q(f"SELECT has_table_privilege('metrion_app', '{t}', 'UPDATE'), has_table_privilege('metrion_app', '{t}', 'DELETE'), has_table_privilege('metrion_app', '{t}', 'INSERT')")[0] == (False, False, True)
        assert env.q(f"SELECT relforcerowsecurity FROM pg_class WHERE relname = '{t}'")[0][0] is True
    assert env.q("SELECT has_table_privilege('metrion_app', 'cmo_perf_line', 'UPDATE'), has_table_privilege('metrion_app', 'cmo_perf_line', 'DELETE')")[0] == (False, False)
