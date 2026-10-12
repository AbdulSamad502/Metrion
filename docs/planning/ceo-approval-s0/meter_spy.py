"""S0 scratch plugin (NOT part of the repo): records every call that would write a metered_event row, per test.
Read-only observation: it calls straight through to the real function."""
import json
import os

import pytest

LOG = os.environ.get("S0_SPY_LOG", "spy.log")
_current = {"id": None}


@pytest.fixture(autouse=True)
def _s0_spy(request, monkeypatch):
    _current["id"] = request.node.nodeid
    try:
        from backend.repositories import entitlement_repo
    except Exception:  # package without backend installed
        yield
        return
    real = entitlement_repo.insert_metered_event

    def spy(*a, **k):
        row = {"test": _current["id"], "agent_code": k.get("agent_code"), "event_kind": k.get("event_kind"), "key": k.get("idempotency_key")}
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        return real(*a, **k)

    monkeypatch.setattr(entitlement_repo, "insert_metered_event", spy)
    yield
