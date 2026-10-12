# S0 scratch experiments (not product tests)

Evidence scripts for `docs/planning/ceo-approval-s0-findings.md`. They **must only run against the isolated scratch Postgres** (`bash backend/scripts/scratch_db.sh up`, port 5544): `test_s0_experiments.py` refuses to run unless both `DATABASE_URL` and `DATABASE_URL_APP` point at port 5544. Never run them against the development database.

| File | Purpose |
|---|---|
| `test_s0_experiments.py` | X1: a `DELIVERED` turn with a failed required leg still consumes one CEO unit. X2: a hard process kill mid-leg leaves the turn, the anchor run and the leg run non-terminal and nothing reconciles them. X3: which registered actions are reachable from a CEO turn (all but the 8 chat actions are refused `OUT_OF_CATALOG`). |
| `crash_child.py` | The child process for X2 (runs a real turn whose leg calls `os._exit(137)`). Paths inside are absolute to this checkout. |
| `meter_spy.py` | A pytest plugin that records every `metered_event` write attempt per test (calls straight through). |

From `backend/`, with the scratch environment loaded (`eval "$(bash scripts/scratch_db.sh env)"`) and `PYTHONPATH` set to this directory:

```bash
python -m pytest docs/planning/ceo-approval-s0/test_s0_experiments.py -p tests.integration.conftest -p no:cacheprovider -s -q
S0_SPY_LOG=spy.log python -m pytest tests/integration/test_cfo_pnl.py tests/integration/test_pi_discover_api.py -p meter_spy -p no:cacheprovider -q
```
