"""The integration suite refuses the development database (port 5432, or a URL with no port) unless explicitly overridden."""

from __future__ import annotations

import pytest

from tests.integration.db_guard import OVERRIDE, development_database_urls, refusal

SCRATCH_APP = "postgresql+psycopg://metrion_app:x@localhost:5544/metrion"
SCRATCH_MIGRATE = "postgresql+psycopg://metrion_migrate:x@localhost:5544/metrion"


def test_the_scratch_database_is_accepted() -> None:
    assert refusal({"DATABASE_URL_APP": SCRATCH_APP, "DATABASE_URL": SCRATCH_MIGRATE}) is None


def test_nothing_configured_is_not_a_refusal_because_the_suite_skips_itself() -> None:
    assert refusal({}) is None


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://metrion_app:x@localhost:5432/metrion",
    "postgresql+psycopg://metrion_app:x@127.0.0.1:5432/metrion",
    "postgresql+psycopg://metrion_app:x@localhost/metrion",  # no port: the default is 5432
    "not a url at all",
])
def test_the_development_database_or_anything_unparsable_is_refused_for_either_variable(url: str) -> None:
    assert development_database_urls({"DATABASE_URL_APP": url, "DATABASE_URL": SCRATCH_MIGRATE}) == ["DATABASE_URL_APP"]
    assert development_database_urls({"DATABASE_URL_APP": SCRATCH_APP, "DATABASE_URL": url}) == ["DATABASE_URL"]
    message = refusal({"DATABASE_URL_APP": SCRATCH_APP, "DATABASE_URL": url})
    assert message and "5544" in message and "DATABASE_URL" in message


def test_an_explicit_override_is_honoured_and_only_the_exact_value_counts() -> None:
    dev = {"DATABASE_URL_APP": "postgresql+psycopg://a:x@localhost:5432/m", "DATABASE_URL": SCRATCH_MIGRATE}
    assert refusal({**dev, OVERRIDE: "1"}) is None
    assert refusal({**dev, OVERRIDE: "true"}) is not None
    assert refusal({**dev, OVERRIDE: ""}) is not None
