"""Issue 8 (Metrion_24_Fixes): "GST line analysis returned a generic 422 using a test line reference".

`POST /cfo/gst/analyze-lines` takes lines the caller assembles (a reference, a listed amount in paise, a basis, an optional rate); the reference is only echoed back, so a
"test" reference is not what makes it 422. What does: an amount that is not an integer (the page used to send NaN as null), a basis outside INCLUSIVE/EXCLUSIVE, a missing
date or an empty list. A rate written as '18%' used to crash with a 500 and is now a named 422. These tests pin each answer, including with a real persisted line id."""

from __future__ import annotations

import pytest

from tests.integration.test_cfo_imports import _csv, _register_owner, _upload, app_client, fake_clerk  # noqa: F401  (fixtures and helpers)

URL = "/api/v1/cfo/gst/analyze-lines"


def _line(**over):
    return {"line_ref": "LINE-1", "listed_paise": 11800, "basis": "INCLUSIVE", "rate_pct": "18", **over}


def _post(client, headers, lines, as_of="2026-09-30"):
    return client.post(URL, json={"lines": lines, "as_of_date": as_of}, headers=headers)


def test_a_well_formed_line_is_analysed_and_the_reference_is_echoed(app_client, fake_clerk, two_tenants):
    headers = _register_owner(fake_clerk, two_tenants[0])
    resp = _post(app_client, headers, [_line()])
    assert resp.status_code == 200, resp.text
    [row] = resp.json()["lines"]
    assert row["lineRef"] == "LINE-1" and row["disclaimer"]
    if row["isAvailable"]:  # figures only when the GST slab for that date is configured; otherwise the row says why it is unavailable
        assert row["normalizedExclusivePaise"] == 10000
    else:
        assert row["unavailableReason"]


def test_a_real_persisted_canonical_line_id_works_as_the_reference(app_client, fake_clerk, two_tenants):
    headers = _register_owner(fake_clerk, two_tenants[0])
    uploaded = _upload(app_client, headers, _csv(2))
    line_id = uploaded["persistedSalesLineIds"][0]
    resp = _post(app_client, headers, [_line(line_ref=line_id)])
    assert resp.status_code == 200 and resp.json()["lines"][0]["lineRef"] == line_id


@pytest.mark.parametrize(
    "line, field",
    [
        (_line(listed_paise=None), "listed_paise"),
        (_line(listed_paise="abc"), "listed_paise"),
        (_line(listed_paise=118.5), "listed_paise"),
        (_line(basis="GROSS"), "basis"),
        (_line(line_ref=""), "line_ref"),
    ],
)
def test_a_422_names_the_field_that_is_wrong(app_client, fake_clerk, two_tenants, line, field):
    headers = _register_owner(fake_clerk, two_tenants[0])
    resp = _post(app_client, headers, [line])
    assert resp.status_code == 422
    assert any(field in item["loc"] for item in resp.json()["detail"]), resp.text


def test_missing_date_and_empty_list_are_422_with_their_field_named(app_client, fake_clerk, two_tenants):
    headers = _register_owner(fake_clerk, two_tenants[0])
    no_date = app_client.post(URL, json={"lines": [_line()]}, headers=headers)
    assert no_date.status_code == 422 and any("as_of_date" in i["loc"] for i in no_date.json()["detail"])
    empty = _post(app_client, headers, [])
    assert empty.status_code == 422 and any("lines" in i["loc"] for i in empty.json()["detail"])


@pytest.mark.parametrize("bad_rate", ["18%", "eighteen", "1/2", "-5", "1e2", ""])
def test_a_rate_that_is_not_a_plain_decimal_is_a_named_422_not_a_server_error(app_client, fake_clerk, two_tenants, bad_rate):
    headers = _register_owner(fake_clerk, two_tenants[0])
    resp = _post(app_client, headers, [_line(), _line(line_ref="LINE-2", rate_pct=bad_rate)])
    assert resp.status_code == 422, resp.text
    [item] = resp.json()["detail"]
    assert item["loc"] == ["body", "lines", 1, "rate_pct"] and "plain decimal" in item["msg"]


def test_no_rate_is_allowed_and_gives_an_unavailable_line_that_says_why(app_client, fake_clerk, two_tenants):
    headers = _register_owner(fake_clerk, two_tenants[0])
    resp = _post(app_client, headers, [_line(rate_pct=None)])
    assert resp.status_code == 200
    [row] = resp.json()["lines"]
    assert row["isAvailable"] is False and row["unavailableReason"]  # a missing rate is not guessed (E12)
