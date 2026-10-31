"""Issue 1 (Metrion_24_Fixes): "UI reported 100/100 rows accepted and persisted, while the inspected application DB contained 0 report_file, ingestion_run and
sales_line rows."

A 100-row file goes through the real `POST /cfo/ingest`. The rows are then counted on a connection that has nothing to do with the request (a fresh engine on the same
database), which proves the transaction was committed rather than merely visible to the request's own session. Counting WITHOUT a tenant context returns 0 for every
tenant-owned table, because FORCE ROW LEVEL SECURITY fail-closes: that, not a lost commit, is what a direct `SELECT count(*)` from psql/a DB client shows."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, make_url, text

from tests.integration.test_cfo_imports import _csv, _register_owner, _upload, app_client, fake_clerk  # noqa: F401  (fixtures and helpers)

TABLES = ("report_file", "ingestion_run", "sales_line")


def _counts(url_variable: str, tenant_id: uuid.UUID | None) -> dict[str, int]:
    """Row counts on a brand-new engine (own connection, own transaction). With a tenant, the context is set the way the application sets it."""
    engine = create_engine(os.environ[url_variable])
    try:
        with engine.connect() as conn, conn.begin():
            if tenant_id is not None:
                conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant_id)})
            return {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in TABLES}
    finally:
        engine.dispose()


def test_a_100_row_import_is_committed_and_visible_to_an_independent_connection(app_client, fake_clerk, two_tenants):
    a, b = two_tenants
    headers = _register_owner(fake_clerk, a)
    body = _upload(app_client, headers, _csv(100))
    assert (body["rowCountRead"], body["rowCountAccepted"], body["rowCountRejected"], body["rowCountDuplicate"]) == (100, 100, 0, 0)
    assert len(body["persistedSalesLineIds"]) == 100  # what the UI calls "persisted" is the number of ids the writer returned

    # Committed: a separate connection sees exactly the rows that were reported.
    assert _counts("DATABASE_URL_APP", a) == {"report_file": 1, "ingestion_run": 1, "sales_line": 100}
    # Tenant isolation: the other tenant sees none of it.
    assert _counts("DATABASE_URL_APP", b) == {"report_file": 0, "ingestion_run": 0, "sales_line": 0}


def test_the_same_tables_look_empty_without_a_tenant_context(app_client, fake_clerk, two_tenants):
    """Why an inspection of 'the application DB' can show 0 rows although the import is stored: with no `app.current_tenant_id`, FORCE RLS returns nothing, for the
    application role and for the table owner alike."""
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    _upload(app_client, headers, _csv(100))
    empty = {"report_file": 0, "ingestion_run": 0, "sales_line": 0}
    assert _counts("DATABASE_URL_APP", None) == empty
    assert _counts("DATABASE_URL", None) == empty  # the migrate/owner role too (FORCE applies to the owner)
    assert _counts("DATABASE_URL_APP", a)["sales_line"] == 100


def test_the_server_is_not_pointed_at_a_different_database_than_the_one_tests_use():
    """The application and the importer use one engine factory per package, both from DATABASE_URL_APP; there is no second connection string to drift from."""
    from backend import tenant_context as backend_tc
    from data_foundation.repositories import tenant_context as df_tc

    assert backend_tc.get_engine().url == df_tc.get_engine().url  # same host, port, database, role
    configured = make_url(os.environ["DATABASE_URL_APP"]).port
    assert backend_tc.get_engine().url.port == configured and configured not in (None, 5432)  # and, in this suite, the configured scratch instance (never the development database)
