"""Child process for the R5 package-run tests (not a test module): starts a RUNNING `reconciliation_run` or `ci_capture_run` exactly as the specialist packages do, with the
backend's ownership plugged in, announces it and waits to be killed."""

from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.repositories import run_liveness  # noqa: E402

run_liveness.install_package_ownership()
kind, tenant, user = sys.argv[1], uuid.UUID(sys.argv[2]), uuid.UUID(sys.argv[3])
now = datetime.now(timezone.utc)
if kind == "reconciliation_run":
    from calc_engine.repositories import reconciliation_repo

    run = reconciliation_repo.insert_reconciliation_run(
        tenant, marketplace="AMAZON", period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), as_of_date=date(2026, 10, 1),
        tolerance_config_version=0, formula_version="test", status="RUNNING", join_key_validated=True, started_at=now,
    )
else:
    from competitor_intelligence.repositories import ci_capture_run_repo
    from competitor_intelligence.types import Trigger

    run = ci_capture_run_repo.create_run(tenant, trigger=list(Trigger)[0], requested_by=user, url_ids=[], started_at=now)
sys.stdout.write(f"RUN {run}\n")
sys.stdout.flush()
time.sleep(600)
