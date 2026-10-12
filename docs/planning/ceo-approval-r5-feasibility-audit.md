# R5 crash reconciliation: feasibility audit (read-only)

Date: 2026-10-10. Status: **audit and recommendation only; nothing was implemented or changed.** No schema, migration, billing, permission or runtime change; the development database was not touched. Inputs: `docs/planning/ceo-approval-s1-readiness.md` (§3, D-6), `docs/planning/ceo-approval-remediation-design.md` (R5, in `docs/planning/`, not `docs/`), `docs/specs/ceo-approval-workflow.md` (§6.8, D9), the S0 experiments in `docs/planning/ceo-approval-s0/`, and the code cited below.

**Context that changes the urgency.** Since the D-8 closure, no approval-required action can run from chat (orchestrator refusal + `dispatch()` backstop). The legs a chat turn can still run are internal and unmetered (CFO computations, `ci.request_price_scenario`, `pi.report`, `cmo.market_trends_preview`, GST lookup). So today a stuck row is **hygiene** for chat. R5 becomes a **safety prerequisite** only when approved execution of metered or externally-sending legs is enabled (spec §6.8, VP-2). The agents' own pages (for example `POST /pi/discover`) still create `RUNNING` rows without a CEO turn; those were not traced for execution safety here and are out of scope.

## 1. Confirmed lifecycle behaviour (code evidence)

| # | Fact | Where |
|---|---|---|
| L1 | One turn runs entirely inside a per-investigation Postgres **session-level advisory lock** on a dedicated autocommit connection, released when the `with` block exits or the connection closes (process death, connection drop). | `ceo/orchestrator.py:231` (`run_turn`), `ceo/turn_lock.py`, `repositories/ceo_runtime_repo.py:35-63` (`AdvisoryLock`, `pg_try_advisory_lock(hashtextextended(key,0))`) |
| L2 | With **two or more** tasks (legs plus state reads), legs run in a `ThreadPoolExecutor`; the turn waits `wait(futures, timeout=leg_timeout_seconds)` and then `pool.shutdown(wait=False)`. **The deadline stops the wait, not the leg.** The comment states it: "a late leg finishes on its own and writes its own finding". | `ceo/orchestrator.py:1038-1043` |
| L3 | With **one** task the leg runs inline (`results = [fn()]`) and has **no deadline at all**: the turn, and its lock, last as long as the action. | `ceo/orchestrator.py:1035` |
| L4 | `dispatch()` writes the leg's `agent_run` as `RUNNING` **before** invoking, for actions whose specialist writes no row of its own (CFO, CI price scenario), and finishes it in a local `finish()` using `datetime.now()`. A hard kill leaves it `RUNNING` forever (experiment X2). | `ceo/dispatch.py` (insert before invoke, `finish` at lines 313-358) |
| L5 | **PI** writes its own `RUNNING` row in the route handler before the provider work (`post_discover`: reserve → `insert_run RUNNING` → run → `finish_run` → `settle_discover`), and releases the quota reservation only on an in-process exception. | `api/v1/pi.py` (~lines 229-275) |
| L6 | **CMO writes its `agent_run` only once, after the result, with both `started_at` and `finished_at`** ("one `agent_run` per ACCEPTED execution, written once it has a terminal status"). **A CMO leg that dies mid-flight leaves no `agent_run` row at all.** In flight, the only trace is its quota reservation (and any artefact rows, not traced here). | `services/cmo_actions.py:_record_run` (~line 123) |
| L7 | `agent_run_repo.finish_run` and `investigation_repo.update_turn` are **unguarded `UPDATE … WHERE id = :id`**: no status precondition, no compare-and-set. A late finisher overwrites any earlier recovery mark; a recovery write overwrites a late success. (`finalise_turn` is the guarded, first-writer-wins path used for billing.) | `repositories/agent_run_repo.py:62,129`; `repositories/investigation_repo.py:353,383` |
| L8 | A late leg still writes its finding (`_record` → `insert_finding`) and, for metered actions, its own usage events (PI: `pi:run:<run_id>:<meter>` via `settle_discover`; CMO per artefact) **after** the turn was finalised. The CEO unit decision was computed at finalisation, when that leg was absent, and `unit_decision` treats an absent required leg as failed (`ceo/billing.py`: `leg is None or …`). | `ceo/dispatch.py:_record`; `services/pi_usage.py`; `ceo/billing.py` |
| L9 | There is **no heartbeat, lease, owner, worker id or last-seen column** on `agent_run`, `investigation_turn` or `pi_research_run`. No sweeper or reconciler exists (`has_active_run` does not exist). | migrations `20260917_0002`, `20261007_0006`; repo search |
| L10 | Quota reservations expire at a TTL derived from the action's structural worst case (`pi_usage._ttl`, `cmo_quota_repo.reserve`); an unreleased one "simply expires at its TTL". | `services/pi_usage.py`, `services/cmo_actions.py:_finish_reservation` |

## 2. The six questions

**1. Can a timed-out leg run after the parent turn releases its lock? Yes.** For two or more parallel tasks the turn returns after `leg_timeout_seconds` while the thread keeps running (L2); the `with investigation_turn_lock` block then exits (L1) and the next turn can start. The late leg later writes its finding, finishes its `agent_run` and, if metered, records usage (L8). The one-task case is the opposite (no deadline, lock held for the whole call, L3).

**2. Can the system tell a dead worker from a slow or orphaned one? Not today.**
- *Turn level: yes, with caveats.* The turn lock is held for the whole turn by one session; if `pg_try_advisory_lock` succeeds for the investigation, no live turn owns it, so a non-terminal turn there is dead. Caveats: (a) the lock is also free after a connection drop while the process lives (and session-level locks do not survive a transaction-mode pooler such as PgBouncer; the deployment is undecided); (b) it proves nothing about **legs**, because late legs outlive it (L2).
- *Leg level: no.* A `RUNNING` leg row with a free investigation lock is ambiguous: dead, or a live late leg in a surviving worker thread. A released lock must not be read as "dead" (design R5.2 as written is unsafe for legs). Age cannot settle it without a measured, per-action maximum (readiness §3). For CMO there is no row to examine (L6).

**3. Which timestamps and statuses are trustworthy?**

| Source | Written by | Clock | Trust |
|---|---|---|---|
| `investigation_turn.created_at` | database default `now()` | database | trustworthy start |
| `investigation_turn.completed_at`, `stage_timings` | app (`runtime.clock()`) | application | trustworthy only on a **finalised** turn; `NULL` means "not finalised", not "dead" |
| `agent_run.started_at` (choke-point legs, PI) | app (`runtime.clock()` / `now`) | application | start of dispatch; good for CFO/CI/PI |
| `agent_run.started_at` (CMO) | app, set at the end | application | **not** the real start; row absent while running |
| `agent_run.finished_at` | app `datetime.now()` (dispatch `finish`) | application, different source from `started_at` in tests | good for completed rows; compare only within one host |
| `agent_run.status` | unguarded writes (L7) | n/a | `RUNNING` means "no terminal write yet", **not** "alive"; a terminal value can be overwritten |
| `pi_research_run.created_at` (post R0) | database `now()` | database | trustworthy; `started_at`/`finished_at` are set by the PI service |
| `pi_research_run.status` | PI service | n/a | same caveat as `agent_run.status` |
| quota reservation `state`/TTL | reservation repo | database | the only in-flight CMO evidence; TTL is a structural estimate, not a measured one |

Nothing in the schema records "who is running this" or "when it was last known alive" (L9).

**4. Smallest safe mechanism against duplicate dispatch and duplicate billing during recovery.**
No new table or column is needed for the following design:
1. **Recovery never dispatches** (R5.5): the reconciler module imports no `dispatch` or registry invoker; a test installs handlers that fail if called. This alone removes recovery-caused duplicate dispatch.
2. **A per-leg liveness lease on the existing `AdvisoryLock`**, key derived from `(turn anchor run id, action key)`, which both the dispatcher and the reconciler can compute without the leg's own row id. The leg thread takes it on its own dedicated connection **before** writing its first row (so there is no window with a row and no owner), holds it for the whole call and releases it **after** the terminal write. The reconciler, for a `RUNNING` leg row (or a CMO reservation with no run row), tries `pg_try_advisory_lock` on that key: **not acquired ⇒ the owner is alive (skip); acquired ⇒ no live owner**. A hard kill releases it with the session; a dropped connection is treated conservatively (see 6). This replaces "free lock ⇒ dead" and the age threshold for liveness.
3. **Guarded transitions only**: recovery uses `UPDATE … WHERE status IN ('QUEUED','RUNNING')` (design `finish_run_if_unfinished`) and `finalise_turn`-style first-writer-wins for turns, and the leg's own terminal write becomes guarded too so a late finisher cannot silently overwrite a recovery mark, or the reverse, without an event (design R5.7 "the live finisher's real result wins" then has a defined meaning).
4. **Idempotent usage by stored decision only**: usage events keep their existing keys (`ceo:turn:<turn_id>`, `pi:run:<run_id>:<meter>`); recovery repairs a missing event only from a stored decision (R5c), so a late finisher and a repair write the same key once.
5. **Uncertain external outcomes are marked, never repeated**: `OUTCOME_UNKNOWN` for external-capable legs, no automatic retry; the seller's own retry is a new request. A seller retry **while the first leg is still alive** is a different hazard (two live runs): it needs its own rule once flagged legs can run (an in-flight check on the same lease key, to be decided; not needed for today's unmetered chat legs).
6. **CMO needs an in-flight row** to be recoverable at all (L6): either write the `RUNNING` row at acceptance (a change to `cmo_actions`) or define recovery for CMO from reservation + artefact state. This is a behaviour change to CMO's own accounting path and needs an owner decision; until then a CMO leg killed mid-flight cannot be seen by a reconciler.

**5. Failure-injection tests required** (scratch Postgres; child processes for kills; injectable clock; provider fakes with call counters; all must pass before R5 may be called done):
- T1 Hard kill mid-leg for each leg type: choke-point leg, PI discover (fake provider), CMO (no row). Rows end `FAILED`/`OUTCOME_UNKNOWN` as designed; the provider call count is unchanged by recovery.
- T2 **Late leg after the deadline** (the L2 case): two legs, one slower than `leg_timeout_seconds`; assert the turn is finalised and the investigation lock is free **while the leg is still `RUNNING` and alive**; the reconciler (lease held) skips it; the leg then completes: its row is `COMPLETE`, its finding exists once, usage is recorded once, the stored CEO-unit decision is unchanged, recovery never touched it.
- T3 Reconciler and late finisher race, both orderings, repeated: exactly one terminal state, one event, no second usage event, no overwritten success.
- T4 Window ordering: the lease is held before the first row exists; a reconciler running at every instant of dispatch (injected pause points) never marks a live leg.
- T5 Lease lost while the leg is alive (connection killed with `pg_terminate_backend`): the leg is marked `OUTCOME_UNKNOWN` (conservative), **no re-dispatch**, and the late real result, if it arrives, is reconciled by the guarded write.
- T6 Repeated and concurrent reconcile, and the reconciler killed mid-run: identical final state, converges on rerun.
- T7 Never-dispatches guard: a registry whose handlers fail the test if invoked; reconciliation never calls them.
- T8 Seller retry while the first leg is alive (once flagged legs can run): defined outcome, no second external call or second billed event unless the owner decides otherwise.
- T9 Duplicate billing: reconcile twice plus a late completion; exactly one event per idempotency key (CEO unit, PI per meter, CMO per artefact).
- T10 Quota: a reservation that expires while its leg is still alive (TTL shorter than the real duration, injected) must not allow a second request past a cap of 1; documents the L10 gap and its fix (the lease, not the TTL, decides liveness).
- T11 Cut-over, legacy rows, tenant isolation, `--dry-run`, and threshold/config refusal (design tests 9-14).

**6. Target-host timing evidence.**
*Measurable without any application change* (read-only SQL on the target database; procedure in readiness §3.4):
- completed-leg durations per action: `agent_run` where `finished_at IS NOT NULL`, grouped by `trigger_ref` (valid for CFO, CI, PI; **CMO rows give duration but never show in-flight or killed runs**, L6);
- turn durations: `investigation_turn.completed_at - created_at` and `stage_timings` (per-leg timing);
- PI run durations: `pi_research_run.finished_at - started_at`;
- **how often late legs occur and how late**: legs whose `finished_at` is later than their turn's `completed_at` (join `agent_run` leg → anchor → `investigation_turn.agent_run_id`);
- slow-path maxima by running the real actions with providers at their configured timeouts (configuration only);
- model-host latency with the real endpoint at the expected concurrency.
*Needs instrumentation first, but only for recovery, not for measurement*: the per-leg lease (mechanism 2) and CMO's in-flight row (mechanism 6). With the lease, liveness no longer depends on a duration, so **no timeout threshold is required to decide dead vs alive**; durations are then still needed for (a) quota reservation TTLs (L10), (b) any minimum-age safety margin the owner wants on top of the lease, (c) the "never started" rule for an approved execution turn. No number is proposed here; the factor and values remain the owner's decision with the E1-E5 evidence of the readiness document.

## 3. Specific safety gaps (summary)
- **G1** A released investigation lock does not prove a leg is dead (L2). The readiness §3.2 caveat is confirmed in code.
- **G2** No liveness signal for legs exists (L9); age alone would need a measured per-action maximum.
- **G3** Unguarded terminal writes (L7): recovery and late finishers can overwrite each other silently.
- **G4** A late metered leg is billed after the turn showed it as failed and charged no unit (L8); with approved external legs this is a visible inconsistency, and a seller retry could duplicate the external call.
- **G5** CMO has no row while running (L6): a mid-flight CMO kill is invisible.
- **G6** Quota reservation TTL is a structural estimate; expiry while alive can let a second request through (L10).
- **G7** Session-level advisory locks (turn lock, and any lease) assume a direct or session-pooled connection; the deployment is undecided, and a transaction-mode pooler would silently break them.
- **G8** The spec's D9 wording (`leg_timeout + margin`) and "optional periodic task" are superseded by this design and the owner's Q-S0-4/Q-R7 decisions (standalone one-shot CLI, no thread or scheduler in FastAPI).

## 4. Smallest defensible remediation design
Order of work, each separately reviewable, **none started**:
1. **I-1 Instrumentation (application change, no schema):** the per-leg lease (acquire before the first row, release after the terminal write), guarded terminal writes for `agent_run` legs and turns, and a recorded reason when a guard refuses. Tests T2-T5, T7, T9. Owner decision needed on CMO's in-flight row (mechanism 6).
2. **I-2 Measurement** (no code, runs in parallel): the SQL in §2.6 on the target host class; also report how often late legs happen.
3. **R5a/b Reconciler** as designed (standalone one-shot CLI, lazy bounded trigger, `--dry-run`), deciding liveness by the lease and never by a bare timeout; per-action ages only as an extra, owner-chosen margin.
4. **R5c Repairs** (CEO unit, PI usage) only from stored decisions, by the existing idempotency keys.
No scheduler is deployed and no background loop is added to the web application at any step.

## 5. Recommendation
**NO-GO to implement R5 as currently designed** (design §R5.2: "free lock ⇒ dead" plus an age threshold), because it can mislabel a live late leg (G1) and cannot see a killed CMO leg (G5).
**CONDITIONAL GO for the lease-based redesign above**, starting with **I-1** and **I-2**. It does not need a measured timeout to decide liveness, so measurement is not on the critical path for the lease, but it is still required for reservation TTLs and any margin. **Instrumentation (I-1) must precede the reconciler; it does not need to precede measurement** (§2.6: measurement needs no code change).
**Pre-conditions before I-1 starts:** owner decisions on (a) the lease approach and its connection cost, (b) CMO's in-flight row, (c) the deployment/pooler assumption (G7, design F4), (d) the S1/S2/S3 and D-6 decisions already listed in the readiness document. R5 stays **BLOCKED** until I-1, the T1-T11 evidence and the owner's acceptance exist; approval must not be enabled before then (VP-2).

## 6. Not verified here
The agents' own page routes were not traced for execution safety. CMO artefact rows and the exact CMO reservation states were not read in full. `pi_research_run` clock sources beyond the cited functions were not traced. No test was run for this audit and no timing was measured.
