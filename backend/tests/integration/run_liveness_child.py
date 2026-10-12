"""Child process for the R5 tests (not a test module): opens a RUNNING `agent_run` exactly as a direct route does, announces it, and then waits to be killed.
A kill leaves no `finally`, no rollback and no terminal write behind."""

from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.repositories import agent_run_repo  # noqa: E402

tenant, user = (uuid.UUID(x) for x in sys.argv[1:3])
run = agent_run_repo.insert_run(
    tenant, agent_id="PI", trigger_type="DIRECT", trigger_ref="pi.discover", requested_by=user, permission_check="PASS", entitlement_check="PASS",
    status="RUNNING", started_at=datetime.now(timezone.utc),
)
sys.stdout.write(f"RUN {run}\n")
sys.stdout.flush()
time.sleep(600)
