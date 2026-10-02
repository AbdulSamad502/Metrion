"""Shared pytest fixtures.

CP1 scaffolding only (`twinkly-mapping-canyon.md`): no CFO-specific fakes exist yet — those
land with CP2's composition logic (Brain-3 `LlmProvider` fakes, engine-call fakes) and CP3's
tests. This file exists so `pytest packages/cfo/tests` has somewhere to wire fixtures into
without every future test file needing to invent its own conftest from scratch.
"""

from __future__ import annotations


# --- Tenant-scoped cleanup for tests that touch the database from the UNIT directory -----------
# A few unit-level tests write real rows (e.g. via a repository) without the integration
# conftest's fixtures. Purge exactly the tenants such a test touched — see
# tools/testkit/tenant_cleanup.py. Does nothing when a test never touched the database.
import os as _os  # noqa: E402
import pathlib as _pathlib  # noqa: E402
import sys as _sys  # noqa: E402

import pytest  # noqa: E402

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[3] / "tools"))
from sqlalchemy import create_engine as _create_engine  # noqa: E402
from testkit.tenant_cleanup import TRACKER as _TRACKER  # noqa: E402

_TRACKER.install()


@pytest.fixture(autouse=True)
def _purge_tenants_touched_by_unit_test():
    _TRACKER.reset()
    yield
    url = _os.environ.get("DATABASE_URL")
    if url and _TRACKER.tenants:
        engine = _create_engine(url)
        try:
            _TRACKER.purge(engine)
        finally:
            engine.dispose()
