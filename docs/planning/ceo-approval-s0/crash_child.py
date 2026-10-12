"""S0 scratch child process: runs a real CEO turn whose first leg hard-kills the process (os._exit) mid-leg."""
import os
import sys
import uuid

sys.path.insert(0, r"C:\dev\Metrion\backend")
sys.path.insert(0, r"C:\dev\Metrion\tools")

from backend.ceo import orchestrator  # noqa: E402
from tests.integration.ceo_support import ctx_for  # noqa: E402
from tests.integration.test_ceo_turn import MSG_PROFIT, PROFIT, Scripted, fake_registry, runtime  # noqa: E402

tenant, user, inv = (uuid.UUID(x) for x in sys.argv[1:4])


def die():
    sys.stdout.write("CHILD: leg started, killing process now\n")
    sys.stdout.flush()
    os._exit(137)


reg = fake_registry({"cfo.financial_health": die, "cfo.anomaly_check": lambda: {}, "cfo.strategic_briefing": lambda: {}})
rt = runtime(Scripted({MSG_PROFIT: PROFIT}), registry=reg)
orchestrator.run_turn(ctx_for(tenant, user_id=user), rt, inv, MSG_PROFIT)
sys.stdout.write("CHILD: returned normally (unexpected)\n")
