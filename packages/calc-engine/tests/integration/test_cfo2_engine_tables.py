"""cfo_read_model_version + expense_class_map — real Postgres (cfo-query-planner.md D2; cfo-unified-financials.md §5)."""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

from calc_engine.repositories import read_model_version_repo as rmv  # noqa: E402
from calc_engine.repositories.tenant_context import tenant_scope  # noqa: E402


def test_version_starts_at_zero_and_only_ever_increases() -> None:
    t = uuid.uuid4()
    assert rmv.get(t) == 0
    assert [rmv.bump(t), rmv.bump(t), rmv.bump(t)] == [1, 2, 3]
    assert rmv.get(t) == 3


def test_bump_inside_the_writers_transaction_rolls_back_with_it() -> None:
    t = uuid.uuid4()
    rmv.bump(t)
    with pytest.raises(RuntimeError):
        with tenant_scope(t) as conn:
            rmv.bump_on(conn, t)
            raise RuntimeError("the write failed after the bump")
    assert rmv.get(t) == 1  # new data and the new version commit together or not at all


def test_versions_are_per_tenant_and_isolated() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    rmv.bump(a), rmv.bump(a)
    assert rmv.get(a) == 2 and rmv.get(b) == 0
    with tenant_scope(b) as conn:  # B cannot see or write A's counter
        assert conn.execute(text("SELECT count(*) FROM cfo_read_model_version WHERE tenant_id = :t"), {"t": str(a)}).scalar_one() == 0
        with pytest.raises(Exception):
            conn.execute(text("INSERT INTO cfo_read_model_version (tenant_id, data_version) VALUES (:t, 99)"), {"t": str(a)})


def _owner_insert(tenant, category: str, cls: str, basis: str | None = None) -> None:
    """expense_class_map is configuration: written only by the owner role (migrations / operators), never by the application role."""
    from sqlalchemy import create_engine

    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
            conn.execute(text("INSERT INTO expense_class_map (tenant_id, category, class, allocation_basis, effective_from, version) "
                              "VALUES (:t, :c, :k, :b, :d, 1)"), {"t": str(tenant), "c": category, "k": cls, "b": basis, "d": date(2026, 10, 1)})
    finally:
        engine.dispose()


def test_expense_class_map_validates_values_and_has_no_seeded_defaults() -> None:
    t = uuid.uuid4()
    with tenant_scope(t) as conn:
        assert conn.execute(text("SELECT count(*) FROM expense_class_map")).scalar_one() == 0  # nothing is assumed for the seller
    _owner_insert(t, "software", "OVERHEAD")
    for bad_class, bad_basis in (("SALARY_MAGIC", None), ("OVERHEAD", "BY_VIBES")):
        with pytest.raises(IntegrityError):
            _owner_insert(t, "x", bad_class, bad_basis)


def test_expense_class_map_is_tenant_isolated() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    _owner_insert(a, "rent", "OVERHEAD")
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM expense_class_map WHERE category = 'rent'")).scalar_one() == 1
    with tenant_scope(b) as conn:
        assert conn.execute(text("SELECT count(*) FROM expense_class_map WHERE category = 'rent'")).scalar_one() == 0


def test_the_application_role_can_read_but_never_write_expense_class_map() -> None:
    """Least privilege: were it writable, the nullable-tenant policy would let the app role plant platform-default rows every tenant sees."""
    from sqlalchemy.exc import ProgrammingError

    t = uuid.uuid4()
    with tenant_scope(t) as conn:
        conn.execute(text("SELECT count(*) FROM expense_class_map"))  # reading is fine
    for sql in ("INSERT INTO expense_class_map (tenant_id, category, class, effective_from, version) VALUES (NULL, 'x', 'OVERHEAD', CURRENT_DATE, 1)",
                "UPDATE expense_class_map SET class = 'OVERHEAD'", "DELETE FROM expense_class_map"):
        with pytest.raises(ProgrammingError):
            with tenant_scope(t) as conn:
                conn.execute(text(sql))
