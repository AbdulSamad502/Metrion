"""Issues 6 and 7 (Metrion_24_Fixes): Leak Shield / Reconciliation and CFO Preview "returned a generic failure".

Against the real routes and the scratch Postgres, with and without persisted canonical lines: both answer 200 with structured counts (never an exception) when nothing can be
reconciled, they count undated lines instead of dropping them silently, and a tenant only ever sees its own lines. Matching with settlement data is covered by
`test_settlement_lag_days`, `test_cfo_preview` and the calc-engine reconciliation suites; this file pins the states a seller meets first."""

from __future__ import annotations

import pytest

from tests.integration.test_cfo_imports import _csv, _register_owner, _upload, app_client, fake_clerk  # noqa: F401  (fixtures and helpers)

PERIOD = {"marketplace": "MEESHO", "period_start": "2026-09-01", "period_end": "2026-09-30", "as_of_date": "2026-09-30"}
RECONCILE, PREVIEW = "/api/v1/cfo/reconcile", "/api/v1/cfo/preview"


def test_with_nothing_uploaded_both_answer_200_with_zero_counts_not_an_error(app_client, fake_clerk, two_tenants):
    headers = _register_owner(fake_clerk, two_tenants[0])
    r = app_client.post(RECONCILE, json=PERIOD, headers=headers)
    assert r.status_code == 200 and r.json()["findings"] == []
    assert (r.json()["matchCount"], r.json()["exceptionCount"], r.json()["datesMissingCount"]) == (0, 0, 0)
    p = app_client.post(PREVIEW, json=PERIOD, headers=headers)
    assert p.status_code == 200 and p.json()["revealedFinding"] is None and p.json()["lockedFindingsCount"] == 0


def test_persisted_lines_without_dates_are_counted_as_missing_dates_rather_than_ignored(app_client, fake_clerk, two_tenants):
    headers = _register_owner(fake_clerk, two_tenants[0])
    _upload(app_client, headers, _csv(100))  # a MEESHO orders file with no order dates
    r = app_client.post(RECONCILE, json=PERIOD, headers=headers).json()
    assert r["datesMissingCount"] == 100 and r["matchCount"] == 0 and r["findings"] == []
    assert app_client.post(PREVIEW, json=PERIOD, headers=headers).status_code == 200


def test_another_tenants_lines_never_count(app_client, fake_clerk, two_tenants):
    a, b = two_tenants
    _upload(app_client, _register_owner(fake_clerk, a), _csv(100))
    r = app_client.post(RECONCILE, json=PERIOD, headers=_register_owner(fake_clerk, b)).json()
    assert r["datesMissingCount"] == 0


@pytest.mark.parametrize("url", [RECONCILE, PREVIEW])
@pytest.mark.parametrize("bad", [{"marketplace": ""}, {"period_start": "not-a-date"}, {"as_of_date": None}])
def test_bad_input_is_a_422_that_names_the_field(app_client, fake_clerk, two_tenants, url, bad):
    headers = _register_owner(fake_clerk, two_tenants[0])
    r = app_client.post(url, json={**PERIOD, **bad}, headers=headers)
    assert r.status_code == 422
    assert any(next(iter(bad)) in item["loc"] for item in r.json()["detail"])


@pytest.mark.parametrize("url", [RECONCILE, PREVIEW])
def test_a_period_that_ends_before_it_starts_does_not_crash(app_client, fake_clerk, two_tenants, url):
    headers = _register_owner(fake_clerk, two_tenants[0])
    r = app_client.post(url, json={**PERIOD, "period_start": "2026-09-30", "period_end": "2026-09-01"}, headers=headers)
    assert r.status_code < 500, r.text
