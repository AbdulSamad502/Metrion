# R5 and the approval gate: dependency graph, decision matrix and owner briefs

Date: 2026-10-11. Status: **analysis plus verified evidence; no decision in this file is accepted.** Sources read for this file (not summaries): `docs/specs/ceo-approval-workflow.md` (§13.11, Q-A9, Q-A10), `ceo-approval-s1-readiness.md` (S1–S3 rows, D-1…D-12), `ceo-approval-r5-feasibility-audit.md`, `ceo-approval-r5-lease-design.md` (§14), the owner decisions recorded in `memory/ceo-approval-workflow-decisions.md`, and the code (`agent_run_repo.py`, `ceo/dispatch.py`, `api/v1/pi.py`, `services/cmo_actions.py`, `tenant_context.py`, `config.py`). It changes no schema, endpoint, billing rule or permission.

## 1. Dependency graph (what blocks what)

```
R5 evidence  = Stage A (done) -> D-L1/D-L2/D-L10 accepted -> Stage B (lease table) -> C (choke-point legs) -> D (PI) -> E (CMO) -> F (reconciler + repairs) -> T1..T11 pass
                                         \-> Stage 0b measurement (needs an authorised target host; feeds reservation TTLs and any optional margin, NOT liveness)
P1 (prerequisite checkpoint) = R0..R4,R6,R7 PASS (targeted)  +  R5 PASS            => P1 is NOT done
VP-1 = metering on failed/interrupted legs (spec §13.2): R2 and R3 are implemented and PASS (targeted), but the design keeps VP-1 FAIL until R5 repairs and the full gate pass   => FAIL
VP-2 = crashed-turn recovery (spec §13.2, X2): FAIL until R5 exists and its kill-process tests pass; no reconciler exists   => FAIL
ENABLE approval (spec §13.11 gate) = P1 done AND VP-1 PASS AND VP-2 PASS AND D-7 (enable config) decided   => NOT MET

S1 (pure observe-only gate)  : implemented (`ceo/approval_gate.py`, `tests/unit/test_ceo_approval_gate.py`), plus the D-8 refusal in the orchestrator and the `dispatch()` backstop.  [R5 not needed]
S2 (approval schema + repository, migration 0018)  : needs D-3 (Q-A9), D-4 (Q-A10), D-5 (stage boundary); applies a migration.     [R5 NOT needed]
S3 (planning: hash, builder, PLANNED production, plan read endpoints) : needs S1+S2 accepted and D-1, D-3, D-7, D-8, D-9.            [R5 NOT needed to create plans]
S4 (approve/decline + execution)  : needs S3 and R5 (AC-A14 crash recovery, AC-A15 metering).  S6 frontend, S7 hardening follow.
```

Two facts this graph makes explicit: **(a) S2 and S3 do not wait for R5**; they wait for owner decisions and a migration approval. **(b) Nothing that *runs* an approved action can start before R5 + VP-1/VP-2.** Today no approval-required action can run from chat (D-8 refusal + `dispatch()` backstop); the specialists' own pages (`POST /pi/discover`, CMO routes) are direct, seller-initiated, and outside the CEO approval policy.

## 2. Decision matrix

| ID | Question | Options | Evidence (current repo / owner decisions) | Safety implications | Owner | Unlocks | Can implementation proceed? |
|---|---|---|---|---|---|---|---|
| **D-L1** lease storage | new table `ceo_leg_lease` (+ optional event table) vs columns on `agent_run` | (A) new table; (B) columns on `agent_run` | `agent_run` is written by specialists, has **no status CHECK**, status writes were unguarded (L7); **CMO writes its row only at the end** (`cmo_actions._record_run`), so a CMO leg has no row to put columns on; owner rule "legacy rows never reinterpreted". | (B) cannot represent a CMO leg in flight and mixes fencing with specialist-owned rows; (A) keeps fencing in one backend-owned place, allows RLS/grants/terminal trigger (D-L6) in one migration. | Owner (needs a migration approval) | Stages B–F | **No** (schema). Recommend **A**. |
| **D-L2** liveness | session advisory lock (no duration) vs heartbeat + expiry | (A) session lock primary; (B) heartbeat needs a lease duration | Owner decisions: **no invented threshold (Q-R5)**, recovery is a standalone CLI with no scheduler/thread (Q-S0-4, Q-R7). A heartbeat *requires* a duration and a renewing thread; the existing per-investigation turn lock already requires session semantics (`ceo_runtime_repo.AdvisoryLock`). **Verified on PostgreSQL 16 (this sprint, see §4):** a session lock is held exactly while its connection lives and is released by the server when the backend dies, with no timeout. | (A) a delayed live worker is never declared dead; a crashed one is detected exactly. (A)'s limit: it assumes session-level connections (transaction-mode pooler breaks it, and so would the existing turn lock). (B) invents a number the owner forbade. | Owner supplies **A1: production pooler mode** (a deployment fact) | Stage C onwards | **Constrained toward A by Q-R5/Q-S0-4**; the only open input is A1. Recommend **A**; adopt B only if A1 = transaction pooling. |
| **D-L10** connection budget / migration order | how many connections a live leg may hold; migration numbering | (a) one dedicated autocommit connection per live leg, pool sized beforehand; (b) a shared lease connection per worker; (c) number it when written | `create_engine(url)` has **no pool arguments** (SQLAlchemy default 5 + 10 overflow, 30 s wait); the turn lock already holds one slot per turn; `ceo_playbook_max_legs` has **no default** (`config.py`), so simultaneous leases are unbounded; legs outlive the request (`pool.shutdown(wait=False)`). Alembic is one linear chain. | Without a bound a burst of legs can exhaust the pool and block unrelated requests: a real availability risk. | Owner/ops: expected concurrent turns × legs, pool size, Postgres `max_connections` | Stage C sizing; `ceo_playbook_max_legs` becomes mandatory | **Partly.** Recommend (a) with `CEO_PLAYBOOK_MAX_LEGS` required and a documented formula: `concurrent_turns × (1 turn lock + max_legs)` must stay under the pool; numbers are the owner's. Migration number: take the next free revision when written (needs only acknowledgement). |
| **Q-A9** plan TTL | `CEO_PLAN_TTL_SECONDS` knob "seeded to 1800" vs constant | knob / constant | The **value** (30 min, immutable per plan, server clock, blocks starting only) is an owner decision (C6, Q-A2, D4). Repo convention: deployment knobs have **no default** (`config.py`), so a knob "seeded to 1800" is a default in disguise. | A constant cannot be mis-set to a long window. A knob must never extend an existing plan. | Owner (one line) | S2 (only if a knob adds validation), S3 | The requirements already point to **constant `PLAN_TTL_SECONDS = 1800` stored in each plan's `expires_at`**; it still needs the owner's confirmation because the spec lists it as a question. |
| **Q-A10** transition enforcement | repository function only vs + constraint trigger vs `SECURITY DEFINER` function | (1) one transactional function; (1+T) function + constraint trigger; (2) `SECURITY DEFINER` and revoke column `UPDATE` | Spec says (1) is necessary. Option (1) alone leaves AC-A10 "no status change without an event" a code-discipline claim because the app role has column `UPDATE (status…)`. **Verified (this sprint):** a trigger makes terminal states immutable even against direct `UPDATE` from the application's own connection (`test_a_constraint_trigger_makes_terminal_states_immutable_even_against_direct_sql`). | (1+T) makes the guarantee a database one at the cost of one trigger in the same migration; (2) is stronger but changes the privilege model. | Owner | S2 (and lease D-L6) | **No** (migration). Recommend **(1+T)**; (2) if "the application role cannot change a status at all" is wanted. |
| D-L3 deadline policy | revoke metered legs at the turn deadline? | revoke / keep "stop waiting" | Revocation cannot stop an in-flight call (V2) and manufactures an uncertain state for work that usually completes (§14.2). | Do **not** revoke at the deadline; revoke only for a proven dead owner, a lost lease, or an operator abort. | Owner | Stage C | Recommended: keep current behaviour. |
| D-L2b late completion | bill a completion proven after revocation | bill once from the stored decision / do not charge | A not-charged success is free usable work and contradicts Q-R2/R3; billing is idempotent per key. | Bill once, from the stored decision. | Owner (billing) | Stage D/F | Recommended: bill once. |
| D-L11 duplicate dispatch | key the in-flight uniqueness by intent, not per click | per-request key / per-intent key | Request keys are per click today; a retyped request gets a new key and would run a second external call. | Block a second live run of the same intent with an "in progress" answer. | Owner (it blocks a seller action) | Stage C/D | Recommended: per-intent. |
| D-1, D-5, D-7, D-8, D-9 | S3 gating decisions (R2/R3 billing acceptance, S1/S2/S3 boundary, enable config and refusal text, interim chat status, billing of a PLANNED turn) | see readiness §5 | All "recommended", none approved. D-8 is partly implemented (refusal + backstop). | needed before behaviour changes for flagged actions | Owner | S3 | **No.** |

## 3. R5 recovery semantics: what is and is not decided

Decided by the owner's recorded decisions (so not open): recovery is a **standalone one-shot CLI plus lazy bounded trigger**, never a loop in the web server; **no automatic retry** of an approved or uncertain effect; **`OUTCOME_UNKNOWN`** for external-capable work with no durable completion evidence; **no invented staleness threshold**; legacy rows never reinterpreted; recovery writes only through guarded transitions and the existing idempotency keys; no refund or new charge from recovery. The timeout/free-lock design (R5.2) is **rejected** and is not reintroduced.

Not decided: the three decisions above (storage, liveness input A1, connection budget). Everything below the line depends on them.

| Guarantee required | Today | Status |
|---|---|---|
| A terminal write cannot overwrite an established terminal state (choke-point legs) | `agent_run_repo.finish_run_if_unfinished` + dispatch `finish()` | **Implemented and tested** (Stage A) |
| Same for PI's direct run row (the route the CEO's `pi.discover` also uses) | `api/v1/pi.py::_finish_run` now uses the guarded write | **Implemented and tested this sprint** (`test_a_pi_run_row_settled_by_someone_else_mid_call_keeps_its_status`) |
| CMO run row | written once, at the end: nothing to guard | n/a (but a CMO leg in flight has no row: needs the lease, D-L5) |
| `investigation_turn` terminal writes guarded | unguarded `update_turn` | **Not implemented** (needs a legal-transition table; Stage C+) |
| Ownership acquisition, contention, duplicate-dispatch block | none | **Not implemented** (D-L1/D-L2/D-L11) |
| Liveness without a timeout | primitive **verified** (§4); no producer | **Not implemented** |
| Fencing of a stale owner at every durable write | design V3; primitive **verified** (§4); no producer | **Not implemented** (D-L1) |
| Recovery of a stuck `RUNNING` leg without redispatch | none | **Not implemented** (Stage F) |
| `OUTCOME_UNKNOWN` representation | status exists in the design; no producer | **Not implemented** |
| Reservation extension while a leg is alive | `finish` exists, `extend` does not (V6) | **Not implemented** |
| Quota reservation never leaks on a failed run row | fixed this sprint in `api/v1/pi.py` (insert failure, failing row update) | **Implemented and tested** |
| Pool budget for per-leg connections | unbounded | **Open decision** (D-L10) |

## 4. Verified database facts (the evidence the owner's decision can rest on)

`backend/tests/integration/test_r5_lease_primitives_spike.py` (six tests; throwaway `r5_spike_*` tables on the **scratch** database, refuses to run unless the connection is port 5544; no migration, no application code, no product behaviour):
1. **Session advisory lock = liveness with no timeout.** A competing `pg_try_advisory_lock` fails while the owner's connection is alive (however long it has been held) and succeeds after the owner's backend is terminated.
2. **The hazard:** a check-then-write fence *without* a row lock lets a revoked owner's write land (epoch 1 result under a lease already at epoch 2).
3. **The proposed fence works:** `SELECT … FOR SHARE` with the epoch check inside the writing transaction rejects a stale owner, and a concurrent revoke **waits** for the in-flight fenced write (asserted by timing and ordering), after which the old owner is fenced out.
4. **Completion vs revocation** (compare-and-set on `epoch`/`state`, 25 rounds with a barrier): exactly one winner every time.
5. **Terminal immutability by trigger** holds against direct SQL.
Limits, stated plainly: these are raw-SQL primitives, not the production lease; RLS and grants were not part of the spike; the lost-connection-while-alive case (T5) and pool behaviour (A1/A2) still need the real implementation and a real deployment answer; a hash collision in `hashtextextended` can only make a dead owner look alive (conservative).

## 5. Owner decision briefs (smallest set, each with a recommended default)

1. **Accept the lease design's storage and liveness (D-L1 + D-L2 + A1), one decision.** *Recommended:* new `ceo_leg_lease` table with a terminal-immutability trigger; session advisory lock for liveness; fencing by epoch under `FOR SHARE`. *Alternative:* heartbeat + expiry, only if production uses a transaction-mode pooler (then a lease duration and its measurement become the owner's input). *Needed from you:* "accept" or "reject", and **which pooler mode production uses**. *Unlocks:* Stages B–F. *Cost:* one migration, one extra connection per live leg.
2. **Connection budget (D-L10).** *Recommended:* one dedicated connection per live leg, `CEO_PLAYBOOK_MAX_LEGS` made mandatory, pool sized so `concurrent turns × (1 + max_legs)` fits. *Needed:* expected concurrency and the pool/`max_connections` numbers. *Unlocks:* sizing for Stage C.
3. **Policy confirmations (D-L3, D-L2b, D-L11).** *Recommended:* do not revoke at the turn deadline; bill a proven completion once from the stored decision; block a second live run of the same intent. *Needed:* a yes/no on each; D-L11 blocks a seller action.
4. **Q-A9:** confirm the plan TTL is the constant `PLAN_TTL_SECONDS = 1800`, not a knob.
5. **Q-A10:** choose *repository function + constraint trigger* (recommended) or *`SECURITY DEFINER` function*.
6. **S2/S3 gating (D-1, D-5, D-7, D-8, D-9):** accept the S1/S2/S3 split with the plan read endpoints in S3 (D-5); accept R2/R3 billing semantics (D-1); confirm the enable setting `CEO_APPROVAL_ENABLED` (no default) and the refusal text (D-7); resolve the confirm-card vs approval conflict (D-8); confirm a `PLANNED` turn is never metered (D-9).
7. **Authorisation to run `ceo-approval-r5-measurement.sql`** read-only on the target host (needed for reservation TTLs and any margin; not for liveness).

## 6. Exact criteria to unblock each gate

| Gate | Criteria |
|---|---|
| **S2** | Items 4, 5, 6 (D-5) accepted; permission to add migration `0018` on the scratch database; tests listed in readiness §S2 pass. |
| **S3** | S2 accepted; items 3's D-1, D-7, D-8, D-9; the S3 acceptance tests pass on scratch; approval still disabled. |
| **P1** | R0–R4, R6, R7 already PASS (targeted); **R5** = item 1 accepted, Stages B–F implemented, T1–T11 pass on scratch, owner accepts. |
| **VP-1** | R2/R3 already PASS (targeted); R5c repairs (a missing CEO-unit or PI usage event is repaired only from a stored decision, by the existing idempotency keys) plus the full gate pass (design rule, readiness C-12). |
| **VP-2** | R5 exists and its kill-process failure-injection tests (T1–T11, readiness E1–E5, including item 7's measurement for reservation TTLs) pass, and the owner accepts D-6. AC-A14: no permanent `RUNNING`, `OUTCOME_UNKNOWN` for interrupted external-capable legs, nothing retried automatically. |
| **ENABLE approval** | P1 done, VP-1 PASS, VP-2 PASS, D-7 decided, S4 implemented and verified. |

## 7. Is approval safe to enable? **No.**
Nothing in the repository enables it (no `CEO_APPROVAL_ENABLED` setting exists), approval-required actions are refused in chat and by the `dispatch()` backstop, and the R5 guarantees that would make an approved execution safe (ownership, liveness, fencing, recovery, `OUTCOME_UNKNOWN`) are not implemented. Stage A and the PI guard remove only the "late finisher overwrites a settled row" gap for choke-point legs and PI's direct route.
