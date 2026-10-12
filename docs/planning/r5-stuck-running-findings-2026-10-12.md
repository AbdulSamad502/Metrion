# R5: why jobs stayed RUNNING, the fix, and the evidence (2026-10-12; extended to every execution path the same day)

Scope: `agent_run` rows (every CEO leg, every direct specialist route, CMO), `pi_research_run`, `reconciliation_run` and `ci_capture_run`. Scratch PostgreSQL (port 5544) only. No timeout, age or deadline was invented; `CEO_LEG_ABANDON_SECONDS` stays unset.

## Root causes (confirmed in code, then reproduced)
1. **No owner evidence.** A row written `RUNNING` meant only "no terminal write yet". After a process death nothing could tell a dead run from a slow one. The only recovery that existed covered seller-turn CEO anchors (turn lock). Direct routes (`POST /pi/discover`, `/pi/supplier-lookup`, CFO/CI direct dispatch, CEO Hub dispatchers) and late legs were never recovered. A hard-killed child process reproduced it: the row stayed `RUNNING` indefinitely.
2. **Exceptions in the CEO Hub direct-dispatch functions** (`agents/ceo_hub.py`, `ceo_hub_cmo.py`, 18 functions) wrote a `RUNNING` row and then called a specialist with no handling. An error left the row `RUNNING` in a process that was still alive, so nothing could ever recover it.
3. **Orphaned `pi_research_run` rows** (`QUEUED`/`RUNNING`) block editing and re-running the seller's brief for as long as they stay active (`pi_research_run_repo._ACTIVE_STATUSES`).

## Fix
- `repositories/run_liveness.py`: while a process works on a `RUNNING` run it holds a Postgres session-level advisory lock keyed by the run id (one dedicated connection per process, not one per run). Taken **before** the row is inserted, released **after** the terminal write. A process that dies releases it by ending the session. A slow or hung run inside a live process keeps it and is never touched. A lost liveness connection is re-opened on the next claim/release and re-takes the locks still held (gap documented in the module).
- `agent_run_repo.insert_run` claims on `RUNNING`; `finish_run` / `finish_run_if_unfinished` release after the write. `settles_open_runs` (decorator on all hub dispatchers) fails any run the call opened if it raises, storing the exception class only.
- `ceo/recovery.sweep_orphan_runs` (called by `sweep_all`, i.e. at start-up): for every `RUNNING` non-seller-turn row whose lock is free, guarded write to `FAILED` / `INTERRUPTED`. It also fails a tenant's orphaned `pi_research_run` rows, but only when the tenant has no live PI run, and never rows created at/after the instant it started looking. It imports no dispatcher and retries nothing: an interrupted external call's effect is neither assumed nor repeated; the seller is told it was interrupted.
- Prevents wrongly recovering live workers (lock held = alive); competing recovery workers (guarded write, exactly one wins); stale workers corrupting results (a late finisher cannot overwrite `INTERRUPTED`, both the unguarded and the guarded finisher).

## Regression evidence (`backend/tests/integration/test_run_liveness_r5.py`, 14 tests, scratch DB)
Real child process killed (`Popen.kill`) with the lock observed held before and free after; repeated sweep = 0; late finisher cannot overwrite; 4 competing sweepers over 3 orphans settle exactly 3; tenant scoping; settle-on-exception stores class only; DB-session loss of a live process survived (liveness connection terminated with `pg_terminate_backend`); one failing tenant does not stop the pass; sweep never dispatches; PI orphan rules (settled only without a live PI owner; live owner left alone; row created after the look never swept).
Also unchanged and green: `test_ceo_hardening_recovery`, `test_agent_run_guarded_transitions`, `test_ceo_leg_deadline`, `test_ceo_turn` (80 passed).

## Coverage after the second pass (every run table that starts RUNNING)
| Execution path / table | Owner evidence | Settle on exception in a live process | Recovery of a dead process | Proven by |
|---|---|---|---|---|
| Seller-turn CEO anchor (`agent_run`, CONVERSATIONAL) | turn lock + run lock | yes (guarded terminal write) | start-up/periodic turn recovery (answers the seller once, never charges) | `test_ceo_hardening_recovery` (real kill) |
| CEO legs, direct routes, CEO Hub dispatchers (`agent_run`) | run lock, taken before the row | `settles_open_runs` on the 18 dispatchers; PI routes already did | `sweep_orphan_runs` | `test_run_liveness_r5` (real kill, 14 tests) |
| **CMO billable actions (`agent_run`)** | run lock, from the first model call | yes (`BaseException` closes the row FAILED) | `sweep_orphan_runs` | `test_cmo_api` x3 incl. a real `os._exit` in the model call |
| `pi_research_run` | tenant has no live PI run | n/a (the route's `agent_run` is settled) | sweep fails QUEUED/RUNNING rows only when the tenant has no live PI owner; never a row created after the look | `test_run_liveness_r5` |
| **`reconciliation_run`** (calc-engine) | per-run lock via the package `ownership` hook | `settles_open_runs` on `reconcile()` | `sweep_orphan_runs` | `test_run_liveness_packages` (real kill) |
| **`ci_capture_run`** (competitor-intelligence) | same hook | `settles_open_runs` on `submit_research_session` and `submit_review_research` | `sweep_orphan_runs` | `test_run_liveness_packages` (real kill) |
Guarded terminal writes now exist on every table above (`AND status = 'RUNNING'`), so a late finisher cannot overwrite a recovery mark and two sweepers settle a row once.

**CMO decision.** The CMO row is opened at the first model call, not at acceptance: requests rejected before any model call (grounding missing, unknown id, ...) must persist nothing (`test_malformed_requests_are_422_and_persist_nothing` pins it). A request that dies before its first model call has produced nothing and billed nothing, so there is nothing to recover. The only residue of a killed CMO request is its quota reservation, which expires at its TTL (counts against the cap until then, the conservative direction).

## Recovery triggers
Start-up sweep (every worker), plus a **periodic pass** (`RECOVERY_SWEEP_INTERVAL_SECONDS`, default 300, `0` = off). It is a polling interval, not a deadline: it decides how soon a dead worker's rows are noticed, never whether a live run is touched (ownership decides that). Cost measured on scratch: an empty pass 6 ms, a pass over 200 live-owned rows 215 ms. Visible through `GET /api/v1/ops/runs` (token-protected, counts only): RUNNING now, live owner vs ownerless, oldest age, this process's last sweep.

**R5 status: resolved for `agent_run`, `pi_research_run`, `reconciliation_run` and `ci_capture_run`, including CMO.** Evidence: real-process-kill tests for each table, repeated and concurrent recovery, late finishers, tenant scoping, lost liveness connection.

## Limitations (not resolved)
- **Deploy precondition.** Rows that were `RUNNING` before this change have no lock and are treated as ownerless on the next sweep. Deploy with no older worker running (a single dev instance restart satisfies this).
- A finisher that raises (database down at the terminal write) leaves its lock held by a live process, so the row looks owned until that process exits.
- The PI rule is tenant-level (no live PI run in the tenant), so an orphaned `pi_research_run` stays until the tenant's other live PI run finishes; conservative by design.
- A killed CMO request's quota reservation lives to its TTL.
- A hung leg in a live process is still governed only by the opt-in `CEO_LEG_ABANDON_SECONDS`; no value is recommended without measured durations.
- `slim_cmo` image/vision actions (`record_free_run`) write a single terminal row and are not long-running; not changed.
