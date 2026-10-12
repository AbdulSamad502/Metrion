"""Child process for the R2 kill test (not a test module): runs a real CEO turn and hard-kills itself AFTER the turn was finalised and its billing
decision stored, but BEFORE the usage event is written."""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "tools"))

from datetime import timedelta  # noqa: E402

from backend.ceo import orchestrator  # noqa: E402
from backend.repositories import accounting_cutover_repo  # noqa: E402
from tests.integration.ceo_support import T0, ctx_for  # noqa: E402
from tests.integration.test_ceo_turn import MSG_PROFIT, PROFIT, Scripted, fake_registry, runtime  # noqa: E402

tenant, user, inv = (uuid.UUID(x) for x in sys.argv[1:4])
accounting_cutover_repo.effective_at = lambda code: T0 - timedelta(days=1)  # the rule is in effect for this child's (fake-clock) turn


def die(*args, **kwargs):
    os._exit(137)


orchestrator.meter_ceo_turn = die
ok = {"overallBand": "GOOD", "perMetricBands": {}, "engineResultRefs": [], "unavailableReason": None}
reg = fake_registry({"cfo.financial_health": lambda: ok, "cfo.anomaly_check": lambda: {}, "cfo.strategic_briefing": lambda: {}})
orchestrator.run_turn(ctx_for(tenant, user_id=user), runtime(Scripted({MSG_PROFIT: PROFIT}), registry=reg), inv, MSG_PROFIT)
sys.stdout.write("CHILD: returned normally (unexpected)\n")
