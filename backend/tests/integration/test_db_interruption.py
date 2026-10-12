"""Database interruption (Stage 4): a restart or failover of PostgreSQL kills every pooled connection. The next request must not fail because of a connection that died while idle
in the pool (`pool_pre_ping`), and a database that is down must produce a prompt, clean failure, not a hang and not a half-written run."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from backend.tenant_context import get_engine, tenant_scope

pytestmark = pytest.mark.usefixtures("two_tenants")


def _kill_every_pooled_app_connection():
    """Ends all idle sessions of the application role other than the killer's own: what a database restart does to a pool."""
    killer = create_engine(os.environ["DATABASE_URL_APP"])
    try:
        with killer.begin() as conn:
            return int(conn.execute(text(
                "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE usename = current_user AND pid <> pg_backend_pid() AND datname = current_database()"
            )).scalar_one())
    finally:
        killer.dispose()


def test_a_pool_whose_connections_were_killed_serves_the_next_request(two_tenants):
    a, _ = two_tenants
    for _ in range(3):  # warm several pooled connections
        with tenant_scope(a) as conn:
            conn.execute(text("SELECT 1"))
    assert _kill_every_pooled_app_connection() >= 1
    for _ in range(3):  # every one of them is dead; none may surface as an error
        with tenant_scope(a) as conn:
            assert conn.execute(text("SELECT 1")).scalar_one() == 1


def test_the_engine_checks_a_connection_before_using_it():
    assert get_engine().pool._pre_ping is True
