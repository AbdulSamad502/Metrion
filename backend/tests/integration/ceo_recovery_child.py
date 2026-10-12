"""Child process for the recovery process-death test (not a test module): starts a REAL CEO turn and hard-kills itself in the middle of one leg (`os._exit`: no cleanup,
no `finally`, no rollback), while two sibling legs have already completed. The parent then checks what the database says about the dead process's turn."""

from __future__ import annotations

import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "tools"))

from backend.ceo import orchestrator  # noqa: E402
from tests.integration.ceo_support import ctx_for  # noqa: E402
from tests.integration.test_ceo_turn import MSG_PROFIT, PROFIT, Scripted, fake_registry, runtime  # noqa: E402

tenant, user, inv = (uuid.UUID(x) for x in sys.argv[1:4])
request_key = sys.argv[4] if len(sys.argv) > 4 else None  # a submission key, when the parent wants to retry the same submission after the death


def die():
    time.sleep(1.5)  # the two sibling legs have finished and been recorded by now
    os._exit(137)


reg = fake_registry({"cfo.financial_health": die, "cfo.anomaly_check": lambda: {"methods": []}, "cfo.strategic_briefing": lambda: {"signals": []}})
orchestrator.run_turn(ctx_for(tenant, user_id=user), runtime(Scripted({MSG_PROFIT: PROFIT}), registry=reg, leg_timeout=60), inv, MSG_PROFIT, request_key=request_key)
sys.stdout.write("CHILD: returned normally (unexpected)\n")
