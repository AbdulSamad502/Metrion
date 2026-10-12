# Approval workflow: S1–S3 boundary, R5 evidence plan, verification gate and decision register

Status: **proposal for owner review (2026-10-10); no decision in it has been accepted.** Nothing here is implemented, accepted or approved. It changes no schema, endpoint, billing rule, permission or status-transition semantics. Authority for the workflow itself stays `docs/specs/ceo-approval-workflow.md`; this file only (a) turns its single "S1–S3" row into a concrete proposal, (b) says what evidence R5 needs, (c) pins the verification gate, and (d) lists the decisions that are still the owner's.

**Legend.** *Fact* = verified in the current code or in a recorded test result. *Proposal* = my suggestion, **not accepted**. *Open* = a decision only the owner can make.

---

## 1. Facts about the current tree (inspected 2026-10-10)

| # | Fact | Where |
|---|---|---|
| F-1 | Branch `feat/ceo-foundation` at `2b954c9` plus an uncommitted working tree (71 paths); `stash@{0}` ("backup before pulling 2b954c9") and `stash@{1}` are kept. No commit has been made. | `git status`, `git stash list` |
| F-2 | **No approval code exists.** There is no `investigation_plan` / `investigation_plan_event` table or migration, no plan, hash, approve or decline code, no endpoint, no `route_source='APPROVAL'`, no message kind `PLAN`. The only approval-shaped identifier is CMO's unrelated `INVALID_APPROVAL` (title approval). | repo-wide search |
| F-3 | **R1 is done and is the registry half of the approval gate:** `ceo/effects.py` classifies all 36 registered actions (`meters`, `external` ∈ NONE/MODEL/PUBLIC_FETCH/SELLER_DATA_OUT, derived `requires_approval`), `registry._with_effects` refuses an unclassified or orphaned action, and `tests/unit/test_ceo_effects.py` enumerates all 36, pins the CI discovery provider to the mock, and shows the derived set as a visible diff. Nothing *consumes* `requires_approval` yet. | `ceo/effects.py`, `ceo/registry.py`, `tests/unit/test_ceo_effects.py` |
| F-4 | **R4 is done:** `PLANNED` is in `TURN_STATUSES`/`TERMINAL_TURN_STATUSES` and the DB CHECK (`20261011_0016`); nothing produces it; `billing.unit_decision` returns NOT_DUE for any non-`DELIVERED` status, so a `PLANNED` turn is already unmetered (no test pins it yet). | `ceo/contract.py:37-40`, migration `0016` |
| F-5 | Migration head is `20261011_0017`; the approval migration would be `20261011_0018_ceo_approval_workflow` (not written). | `alembic heads` on the backend chain |
| F-6 | **Drift from the specification's §5.5 "Chat today" column (closed at runtime by D-8, 2026-10-10).** The pulled branch (orchestration spec 6.35, 6.40) made `pi.discover`, `cmo.generate_title_sets/hashtags/description/keywords` and `cmo.market_trends` chat actions (`ActionPlan(..., session=True)` in `ceo/plans.py`). They ran after an in-conversation step with no stored plan, hash, expiry or requester check: **a confirmation card only for `pi.discover` ("Yes, run it") and `cmo.market_trends` (preview, then "Yes, run the research"); the four `cmo.generate_*` actions had no confirmation at all** (they ran on the last answered question). By the registry these are exactly the actions that *require approval*. Under C3 an in-conversation answer is not approval. **Now: all six are refused from chat (orchestrator on the decision, `dispatch()` backstop); S2/S3 are still not implemented.** | `ceo/plans.py`, `ceo/input_session.py`, `ceo/orchestrator.py`, `ceo/dispatch.py`, `tests/integration/test_ceo_approval_blocked_chat.py` |
| F-7 | **Late legs outlive the leg deadline.** Parallel legs run in a thread pool; the turn waits `wait(futures, timeout=leg_timeout_seconds)` and then `pool.shutdown(wait=False)` ("a late leg finishes on its own and writes its own finding"). The turn's advisory lock is released when the turn ends. So a leg's `agent_run` can legitimately be `RUNNING` **after** the turn is `DELIVERED` and **after** the lock is free. | `ceo/orchestrator.py:1022-1024`, `ceo/turn_lock.py` |
| F-8 | `CEO_LEG_TIMEOUT_SECONDS`, `CEO_PLAYBOOK_MAX_LEGS`, `CEO_TURN_LOCK_WAIT_SECONDS` have **no default** (unset → `None`; legs refuse with `CONFIG_MISSING`). | `config.py:209-230` |
| F-9 | No reconciler, sweeper or recovery exists. A hard kill leaves the turn, the CEO anchor run and the leg run non-terminal (experiment X2, `docs/planning/ceo-approval-s0/`). | S0 findings §13.2 |
| F-10 | Durations are recorded in the database: `agent_run.started_at/finished_at` + `trigger_ref` (the action) + `status`; `investigation_turn.created_at/completed_at/stage_timings`; `pi_research_run.started_at/finished_at`. So timing evidence can be collected **read-only, without code changes**. | migrations `20260917_0002`, `20261007_0006`, PI `20260929_0001` |
| F-11 | CI (`.github/workflows/ci.yml`) has no frontend job; the backend job runs `alembic upgrade/downgrade base/upgrade` and `pytest tests/ -v` with `METRION_ALLOW_DOWNGRADE_TESTS=1`. | `ci.yml` |

---

## 2. S1 / S2 / S3 matrix (proposal; the specification has one row, "S1–S3")

The specification's §13.11 lists **one** row, "S1–S3 Registry gate, approval schema, planning", with exit criteria AC-A1–A3, A5, A7, A10–A12, A16, and no line between the three steps. The split below follows the order in which that row names them. **It is a proposal; the boundary is an open decision (D-5).** Several S1–S3 exit criteria (AC-A5, AC-A7, AC-A11) describe behaviour that lives in S4's endpoints; in S1–S3 they are verified at the pure-function, repository and RLS level (contradiction C-5). Order matters: each stage must leave every existing suite green and the product's behaviour unchanged unless stated.

### Already implemented (must not be duplicated)
`ActionEffects` / `ACTION_EFFECTS` (36 actions), derived `requires_approval`, the registry classification gate, the CI-provider pin test, `PLANNED` vocabulary (constants, migration `0016`, frontend rendering), the accounting cut-over table and `billing.unit_decision` (CEO_UNIT_RULE_2), the effects-metadata tests. AC-A2 (registry classification) is therefore **already satisfied**; S1–S3 only *consume* it.

### S1: the registry gate (pure code, no schema, no endpoint, no behaviour change)
| | |
|---|---|
| **Scope** | A pure function that applies the leg rule (D1/C11) to the legs a turn or playbook would run: "which legs need approval; does this turn need a plan". Playbook gating is derived from the legs (no blanket exemption). Observe-only: it **reports**, it does not change what runs. |
| **Files** | New `backend/src/backend/ceo/approval_gate.py`; new `backend/tests/unit/test_ceo_approval_gate.py`. No migration. No change to `orchestrator.py`, `input_session.py` or any API. |
| **Dependencies** | R1 (done). Nothing else. |
| **Acceptance tests** | (a) a turn with no flagged leg → no plan required (AC-A1's pure half); (b) a playbook is gated iff one of its legs is, evaluated over the **real** `PLAYBOOKS` table and every `ACTIONS` entry (C11, AC-A3's gate half); (c) the gate agrees with `effects.derived requires_approval` for all 36 actions; (d) the gate never returns "not required" for an action with meters or `SELLER_DATA_OUT`; (e) an unknown/unregistered key fails closed (required); (f) the current chat-reachable set is pinned, with the F-6 actions listed as "flagged, reachable from chat" so the drift is a visible, reviewed fact. |
| **Exit** | Unit suite green; existing suites unchanged; no DB touched; the F-6 list recorded in the spec. |
| **Note** | Wiring the gate to refuse or plan is **not** in S1 (see D-5 and D-8). |

### S2: the approval schema (migration + repository; no producer, no endpoint)
| | |
|---|---|
| **Scope** | Migration `20261011_0018_ceo_approval_workflow` per spec §5.1, §5.2, §5.4, §13.6: `investigation_plan` (`UNIQUE (tenant_id, id)`, partial unique `(tenant_id, investigation_id) WHERE status='AWAITING_APPROVAL'`, CHECKs, `expires_at > created_at`), `investigation_plan_event` (append-only, composite FK `(tenant_id, plan_id)`), `investigation_turn.plan_id` + `route_source` CHECK `+APPROVAL`, `investigation_message.kind` CHECK `+PLAN`, `FORCE` RLS + `tenant_isolation`, `REVOKE ALL` then narrow grants (`SELECT, INSERT`; column-level `UPDATE (status, execution_turn_id, decided_by, decided_at, decision_reason)` on the plan; events `SELECT, INSERT`), downgrade that **refuses when rows exist**. One repository module with a **single transactional transition function** that writes the status change and its event together. |
| **Files** | New migration; new `repositories/investigation_plan_repo.py`; tests: new `test_investigation_plan_rls.py`, `test_investigation_plan_constraints.py`, `test_investigation_plan_migration.py` (round trip + refusal, opt-in downgrade env var), extend `test_privilege_boundary.py` (`has_column_privilege`, direct-SQL attempts as `metrion_app`, `KNOWN_APP_DELETABLE` stays accurate), confirm `tools/testkit/tenant_cleanup.py` purges the new tables children-first. |
| **Dependencies** | R4 (`0016`) and R0 (`0017`), done. **Decisions Q-A9 (TTL source) and Q-A10 (how transitions are enforced) are required before this stage** (D-3, D-4); O1 (composite FK) is recommended in the spec. Nothing may be applied to the development database in this stage. |
| **Acceptance tests** | AC-A10 (database half: event table has no `UPDATE`/`DELETE`; one event per transition via the repository function), AC-A11 (RLS: foreign tenant cannot read or write; foreign id = unknown id; missing tenant context fails closed), AC-A12 (app role cannot update `plan`, `plan_hash`, `requested_by`, `expires_at`, cannot `DELETE`/`TRUNCATE`); migration round trip on a scratch database; downgrade refuses with rows present. |
| **Exit** | Scratch-database suites green; privilege boundary extended and passing; no producer or endpoint exists; the dev database untouched. |

### S3: planning (the producer; behaviour changes for flagged actions)
| | |
|---|---|
| **Scope** | Canonical JSON and `plan_hash` (spec §6.2; binds `plan_id, tenant_id, investigation_id, requested_by, expires_at, plan`; integers only); the plan builder (code only, from the registry and already-validated slots: spec §5.3); the gate wired at `PLAN_VALIDATED` and at `input_session.Done` (D2); production of `PLANNED` atomically with one plan, one `CREATED` event and one `PLAN` message (AC-A3); `expires_at = created_at + 1800 s` stored per plan from the server clock (C6, D4, AC-A5); supersession of an older open plan (partial unique index); exclude `PLAN` messages from classifier context and summary (N7); a code-rendered plan card template (no model call); composer evals (AC-A16); a unit test pinning that a `PLANNED` turn is unmetered (D-9; `unit_decision` already returns NOT_DUE); the fail-closed enablement config (N8, D9). |
| **Files** | New `ceo/plan_hash.py`, `ceo/plan_builder.py`; edit `ceo/orchestrator.py`, `ceo/input_session.py`, `ceo/contract.py`, `ceo/summary.py`, `ceo/classifier.py`/context, `ceo/composer.py` (template), `config.py` + `.env.example`; read endpoints `GET …/plans` and `GET …/plans/{id}` (spec §6.5; **stage not stated, D-5**); frontend types only if the owner places the UI in S3 (spec puts it in S6). |
| **Dependencies** | S1, S2 accepted; D-1 (R2/R3 billing accepted), D-3, D-7, D-8, D-9 decided. R5 is **not** required to create plans but **is** required to *enable* approval (VP-2, D-6). |
| **Acceptance tests** | AC-A1 (non-flagged turn unchanged: the existing CEO suites), AC-A3 (zero legs dispatched; atomic plan + event + message; playbook gated iff a leg is), AC-A5 (exactly +1800 s; expired plan cannot be used), AC-A7 (hash changes on any material field; client value never a source), AC-A10 (events), AC-A16 (evals: no figure not in the plan, no dropped disclaimer, no narration of a non-result), and a test that **no approve path exists** (AC-A4 holds by absence). |
| **Exit** | All of the above green on scratch; **approval is still disabled** (no approve/decline endpoint, no execution); the F-6 chat paths either planned or explicitly left on the interim confirm card per D-8. |

**Not in S1–S3** (spec §13.11): S4 approve/decline + execution (AC-A4, A6, A8, A9, A13), S6 frontend (AC-A17), S7 hardening. AC-A14 (crash recovery) and AC-A15 (metering) depend on R5 and VP-1/VP-2 and are not satisfied by S1–S3.

---

## 3. R5 (crash reconciliation): evidence plan. R5 stays **BLOCKED**

### 3.1 What the code shows about the lifecycle (facts)
1. `run_turn` takes the investigation advisory lock (session-level; released if the process dies), creates the turn + CEO anchor `agent_run`, runs legs, finalises (`finalise_turn`, billing decision stored once, first writer wins), releases the lock.
2. Parallel legs run in threads; the turn waits at most `CEO_LEG_TIMEOUT_SECONDS` and then **stops waiting but does not stop the leg** (F-7). A single leg is run inline with no deadline at all.
3. Each leg is bounded only by the timeouts *inside the action* (HTTP client timeouts, model timeouts), not by the turn.
4. A hard kill bypasses both the in-process exception handler and the leg's own `finish_run`, leaving non-terminal rows forever (X2). Direct-path PI runs have no investigation, hence no lock.
5. External side effects happen inside legs (Tavily/YouTube/Places, model calls, metered provider calls); a kill can occur after a request left Metrion and before the result was stored.

### 3.2 Two consequences that must be settled before any threshold exists
- **The liveness proof is not enough on its own.** R5.2 treats "I can take the investigation lock" as "no live turn in this investigation". Because late legs keep running after the turn (and its lock) end (F-7), a *free lock does not prove a RUNNING leg is dead*. Only age above that action's real maximum duration can. The staleness rule must therefore be **per action**, not `leg_timeout + margin` as spec D9 words it (the design's R5.6, which uses the maximum action worst case, is the correct reading; D9's wording should be amended when R5 is accepted).
- **A structural bound is not evidence.** The ≈1,640 s PI figure is derived from constants and holds only for `candidate_cap` 1–100 under listed assumptions; it is a lower bound for a safe threshold, never the threshold.

### 3.3 Evidence required before a threshold may be chosen (acceptance criteria for lifting the block)
| # | Evidence | Acceptance |
|---|---|---|
| E1 | Target-host duration distribution **per action** (`trigger_ref`) for every action the reconciler can see, at least `pi.discover` (SHALLOW and COMPLETE, default and maximum `candidate_cap`), `pi.supplier_lookup`, `cmo.*` (each), `cfo.gst_lookup`, `cfo.*` compute legs, `ci.*`, and the CEO turn as a whole | ≥ 30 completed runs per action (or ≥ 10 for a very expensive one with the sample size stated), recorded with the host description; separate runs for cold and warm model |
| E2 | Slow-path evidence: runs under provider timeouts (provider stubbed to the configured timeout) and a saturated model host | the observed **maximum** per action under forced timeouts, which must not exceed the structural bound |
| E3 | The target model host and the deployment environment are decided (F1/F4 of the design) | named in the decision register; measurements are only valid for that host class |
| E4 | Recovery behaviour proven by the 14 failure-injection tests in the design (§R5) on a scratch database, including: kill mid-leg, concurrent and repeated reconcile, live turn skipped, **late leg finishing after the turn** (new: pin F-7), threshold ±1 s with an injected clock, reconciler killed mid-run, never-retries guard, tenant isolation, dry-run, config below the computed floor refused | all pass; no provider call count changes during recovery |
| E5 | Owner acceptance of the margin and of the per-action values | recorded in the decision register |

### 3.4 Measurement procedure (reproducible, read-only, no code change)
1. **Environment.** Run on the target host class with the real model endpoint and real provider keys *or* with providers configured to their production timeouts; note CPU/GPU, model name, region, concurrency. A laptop or CI number is not valid for E1.
2. **Workload.** Drive each action through its normal entry point (direct route or CEO turn) from a scripted client, sequentially (one at a time) and then at the expected concurrency (N parallel tenants), 30+ runs each, mixing minimum, default and maximum inputs (`candidate_cap` 1, 30, 100).
3. **Collect** with read-only SQL on that database (the application's own tables; nothing is added): 
   `SELECT trigger_ref, status, EXTRACT(EPOCH FROM finished_at - started_at) AS secs FROM agent_run WHERE finished_at IS NOT NULL AND started_at >= :window` for legs and anchors; `SELECT EXTRACT(EPOCH FROM completed_at - created_at), stage_timings FROM investigation_turn …` for turns; `SELECT EXTRACT(EPOCH FROM finished_at - started_at), status FROM pi_research_run …` for PI runs. Record failed/partial runs separately (they set the high tail).
4. **Summarise** per action: n, min, median, p95, p99, **maximum observed**, and the maximum under forced timeouts (E2). Keep the raw rows with the report.
5. **Margin methodology (proposal, owner to accept).** `stale_after(action) = max(max_observed(E1,E2), structural_bound(action)) × safety_factor`, and the reconciler's global value is the maximum over the actions it can see, never below the computed floor already specified (R5.6). `safety_factor` is chosen by the owner and recorded; a larger value only delays recovery of a crashed run, a smaller one risks marking a live slow run dead. 2× is the provisional factor in the design; it is a placeholder until D-6 is decided.
6. **Re-measure** whenever the model, host class, provider timeouts or `candidate_cap` ceiling changes; the floor is computed in code from the same constants so it cannot drift silently.

### 3.5 Constraints that stay (no change here)
No background loop in the web app; no automatic retry or re-dispatch of any approved or uncertain effect; a recovered row is only ever marked `FAILED`/`OUTCOME_UNKNOWN`; if a live process later finishes the same leg its true result wins (design R5.7); reconciliation is a standalone one-shot CLI plus a bounded lazy trigger (design R5.1), deployment of any scheduler undecided (F4).

---

## 4. Verification gate

### 4.1 What has been verified (exact; targeted, not a complete-suite pass)
| Check | Result | Scope |
|---|---|---|
| Backend unit suite (`tests/unit`) | 3,992 passed, 6 xfailed, 0 failed, 0 skipped | **complete unit suite**, merged tree, scratch DB |
| Merge-affected backend integration subset (15 files, 139 tests) | 135 passed, 1 failed, 2 skipped, 1 xfailed; the failure was a stale `(1 of 3)` expectation, now `(1 of 8)`, file passes 10/10; the 2 skips (opt-in downgrade tests) pass when enabled; the xfail is the documented Q13 gap | **subset only** |
| `candidate_cap` + quota + usage + discover API tests | 26 passed, 0 xfailed (incl. the 8-way last-unit test) | targeted |
| Migration round trips (scratch DBs 5544/5545) | PI `downgrade 20261001_0001`→`upgrade head`; backend `downgrade base`→`upgrade head` → `20261011_0017 (head)`; downgrade refusal cases and `test_privilege_boundary.py`: 35 passed | scratch only |
| Frontend | eslint clean; `tsc --noEmit` clean; `next build` succeeds; vitest 198/198 (18 files) **with `--maxWorkers=4`**; with 12 workers under heavy machine load 2–6 different tests timed out at 5 s and passed alone | working tree |
| **Complete backend suite on the merged tree** | **NOT RUN** (≈ 4,700 tests; integration is slow here: the 139-test subset took 22 minutes; `test_ceo_safety_gate` alone runs 700 turns). The last complete run (4,675 passed, 1 failed, 7 xfailed) predates the merge. | **open gate** |

### 4.2 The remaining CI gate (exact)
Run on a disposable Postgres 16 + pgvector with `docker/postgres-init/01-enable-pgvector.sql` and `02-roles.sql` applied, every package migrated in CI order (`backend/scripts/scratch_db.sh up` does this on port 5544), then from `backend/`:
```
python -m alembic upgrade head && python -m alembic downgrade base && python -m alembic upgrade head
METRION_ALLOW_DOWNGRADE_TESTS=1 python -m pytest tests/ -v
```
(with the CI placeholder `CLERK_*`/`FRONTEND_ORIGIN` variables from `ci.yml`). Required result: **0 failed**, xfails only the documented ones, skips only the opt-in tests (none skipped when the variable is set). The package suites (`packages/*`, `python -m pytest tests/`) run in the same job as today. Expected wall time: several hours on a laptop-class Docker host; run it in CI, not interactively. **The gate is not passed until that run is green on the merged tree.**
Frontend: `npm --prefix frontend run lint`, `npx tsc --noEmit`, `npx vitest run --maxWorkers=4`, `npx next build`. **CI has no frontend job (F-11); adding one is a proposal (D-11), not done.** Do not run the frontend suite at default concurrency while a backend suite is running.

### 4.3 Scratch-only rule and the dev-database guard
Migration round trips, downgrade-refusal tests and privilege checks run **only** against scratch databases. Guards today: the S0 experiments refuse any URL that is not port 5544; the downgrade tests are opt-in (`METRION_ALLOW_DOWNGRADE_TESTS=1`) but have **no URL guard**, so the operator must point `DATABASE_URL` at a scratch database before setting the variable (adding a URL guard to those tests is a proposal, not done). **Before any future upgrade of the development database**, do a **read-only** inspection, and stop on any mismatch:
```
SELECT version_num FROM alembic_version_backend;      -- and the PI package's version table
```
Compare each recorded revision with the revision IDs in the repository. **Known hazard:** this work first used `20261010_0011` for `attachment_append_only`, and an earlier session applied it to the dev database. The pulled branch now uses `20261010_0011` for `agent_memory`. If the dev database records `20261010_0011`, **stop and report the exact conflict**: Alembic would believe `agent_memory` is applied while `agent_memory` and (depending on history) the append-only narrowing may be missing. The repair is a deliberate, reviewed step (verify the actual table and grant state first), never an automatic `stamp`. Take the before/after fingerprint described in the dev-DB safety notes.

---

## 5. Decision register D-1 … D-12 (for the owner's review)

**How to read it.** *Approved* = recorded in the approval specification as an owner decision (C1–C11, Q-A2/A3/A5/Q12/Q-A1/Q-A6, Q-S0-1…4, Q-R1…R10) or in the orchestration spec as owner-approved (6.35, 6.40). *Recommended* = my proposal; **nothing under "Recommended" is accepted, and no decision below has been accepted on the owner's behalf.** Each decision lists what it blocks: "S1", "S2", "S3" (§2 matrix), "ENABLE" (turning approval on at all), "RELEASE".

| ID | Decision | Approved so far | Blocks |
|---|---|---|---|
| D-1 | R2/R3 billing: accept the implemented semantics | the core rules (Q-R1…R4, R6) | S3, ENABLE, RELEASE (R2/R3 acceptance) |
| D-2 | `candidate_cap` contract 1–100 | nothing (my proposal) | RELEASE; R5 floor |
| D-3 | Q-A9: how the 1,800 s expiry is held | the **value** 1,800 s (C6, Q-A2) | S2, S3 |
| D-4 | Q-A10: database enforcement of status transitions | nothing (the spec says a repository function is necessary) | S2 |
| D-5 | The S1 / S2 / S3 boundary and the stage of the plan read endpoints | the order "Registry gate, approval schema, planning" | S1, S2, S3 |
| D-6 | R5: evidence, margin and acceptance | no threshold; lazy recovery + standalone CLI, no scheduler/thread (Q-S0-4/Q-R7); no invented threshold (Q-R5) | ENABLE |
| D-7 | Enablement configuration and the refusal outcome when approval is off | "disabled when unset; refuse with an explanation" (D9, wording only) | S3 |
| D-8 | Interim status of chat actions that run behind a confirm card | C1/C3/Q12 (approval required) **and** 6.35/6.40 (confirm card, owner-approved): both approved, they conflict | S3, RELEASE |
| D-9 | Billing of a `PLANNED` (planning) turn | stated in D6/§13.4 item 3 ("never metered") as design, not as an owner decision | S3 |
| D-10 | Optional hardening and minor questions (O1, O2, O4–O7, Q-A4, Q-A8, F10) | Q-A4 recommended only | per item |
| D-11 | Frontend verification in CI | nothing | S6 exit, RELEASE |
| D-12 | Development-database revision conflict (`20261010_0011`) | nothing | any dev-DB upgrade |

### D-1 R2/R3 billing semantics
- **Question.** Accept the implemented R2 (`CEO_UNIT_RULE_2`) and R3 (`PI_USAGE_1`) rules for release, and settle the five small open facts.
- **Already approved (do not re-ask):** any failed required leg ⇒ no CEO unit even if an optional leg succeeded (Q-S0-3/Q-R1); PI `PARTIAL` billable only with a usable result, one event per meter per run (Q-R2); only successful `research.niche_run` executions count (Q-R3); no refunds, retroactive charges or backfills, legacy rows never reinterpreted, durable cut-over records (Q-R4); `OUT_OF_SCOPE` billing preserved and made explicit (Q-R6); no overshoot once PI caps are enabled, reservation first (Q-R8).
- **Still open (small):** F2 documentation of the `OUT_OF_SCOPE` unit (now written as orchestration spec 6.42; owner to confirm); F6 a required leg that is `PARTIAL` with a data request (counted *not failed* until decided); F7 a delivered "not available yet" Business State answer is charged today; F8 the PI "usable result" predicates (≥ 1 computed candidate; lookup ≥ 1 lead; proposed by me); F9 the durable `accounting_cutover` table (extra migration, applied on scratch, not on dev).
- **Recommended default.** Accept as implemented. F6: keep "not failed, no unit while input is pending" (already the code: outcome `PENDING_INPUT`). F7: keep charging. F8, F9: accept.
- **Consequence.** *Billing:* behaviour is already implemented and tested (targeted); accepting changes no code, rejecting any item means a billing change plus tests. *Idempotency:* unit event key `ceo:turn:<turn_id>`, PI keys per run; only the finalising call writes. *Legacy:* turns and runs before the cut-over are never re-evaluated, repaired, charged or refunded. *Migration:* `20261011_0017` and PI `0002` ship only after acceptance and the dev-DB check (D-12).
- **Blocks.** S3 (the planning turn's accounting builds on it), ENABLE, RELEASE of R2/R3.

### D-2 `candidate_cap` API contract
- **Question.** Is `1 ≤ candidate_cap ≤ 100` (422 outside; default 30) the public contract for `POST /pi/discover`?
- **Approved.** Nothing. This **narrows** a previously unbounded public contract; 100 is not a measured provider limit.
- **Recommended.** Accept 1–100. If another ceiling is chosen, change `MAX_CANDIDATE_CAP`, the timing floor and the three tests together.
- **Consequence.** *Security/cost:* closes the unbounded-work path (a cap below 1 defeated the cap). *API:* callers sending `0`, negatives or more than 100 now get 422. The 1,850 s figure applies to the default cap only and is not a maximum. R5's floor is derived from this ceiling.
- **Blocks.** RELEASE; the R5 floor (D-6).

### D-3 Q-A9 plan expiry setting
- **Question.** Is the 1,800 s expiry a code constant, or a config setting `CEO_PLAN_TTL_SECONDS` seeded to 1800?
- **Approved.** The value: 30 minutes from creation (C6, Q-A2; D4: stored per plan, immutable, server clock, blocks *starting* only).
- **Recommended.** A named constant `PLAN_TTL_SECONDS = 1800` in code, stored in each plan's `expires_at`. Reason: the owner fixed the value, and the repository's convention is that deployment knobs have **no default** (`config.py`), so a knob "seeded to 1800" would be a default in disguise, or would force every environment to set a value the owner already chose. A knob is added only if the owner wants it tunable, and then it must never extend an existing plan (D4).
- **Consequence.** *Security:* a constant cannot be mis-set to a long window. *Migration:* none either way (the value lives in `expires_at`; the CHECK is only `expires_at > created_at`). *Tests:* AC-A5 is `created_at + 1800 s` exactly either way.
- **Blocks.** S3 (builder); S2 only if a knob adds config validation.

### D-4 Q-A10 status-transition enforcement in the database
- **Question.** Beyond one transactional repository function, does the database itself enforce legal transitions and "no status change without an event"?
- **Approved.** Nothing on the mechanism. Approved intent: auditable, append-only transitions (C10); narrow grants (spec §5.4).
- **Recommended.** Option 1 (one repository function that updates the status and inserts the event in one transaction; the app role holds column-level `UPDATE (status, …)` only) **plus** a constraint trigger on `investigation_plan` that (a) rejects any status change outside the legal transition table and (b) rejects a change with no matching event row in the same transaction. Option 2 (a `SECURITY DEFINER` function, then revoking the column `UPDATE`) is the stronger alternative; choose it if "the application role cannot change a status at all" is wanted.
- **Consequence.** *Security:* with option 1 alone, AC-A10 ("no code path changes status without an event") is only a code-discipline claim, because the app role can `UPDATE status` directly; the trigger or definer function makes it a database guarantee. *Migration:* the trigger or function is part of `20261011_0018`; the downgrade must drop it; the privilege test must assert it. *Implementation:* about one function and its tests; nothing for S1.
- **Blocks.** S2 (changes the migration and the privilege model).

### D-5 The S1 / S2 / S3 boundary and the read-endpoint stage
- **Question.** Adopt the §2 split? Which stage holds `GET …/plans` and `GET …/plans/{id}`?
- **Approved.** The row name and order only ("Registry gate, approval schema, planning").
- **Recommended.** §2 as written: S1 pure gate; S2 schema + repository; S3 planning. Put the two GET endpoints in **S3** (they only read what S3 writes and are needed to show a plan); approve and decline stay S4.
- **Consequence.** The S1–S3 exit list contains criteria whose behaviour lives in S4 (AC-A5 "expired plan returns 409", AC-A7 hash at approval, AC-A11 "approve, decline or list"). Under this split they are verified at **repository / pure-function / RLS level** in S1–S3 and re-verified at the endpoint in S4; the spec should say so (contradiction C-5).
- **Blocks.** S1, S2, S3.

### D-6 R5 evidence and acceptance
- **Question.** Approve the evidence list E1–E5, the measurement procedure (§3.4) and the margin method (`max(observed, structural) × factor`, per action) as the acceptance criteria for lifting R5's block; choose the factor and the target host.
- **Approved.** Lazy recovery + a standalone CLI, no thread or scheduler in the web app (Q-S0-4, Q-R7); never retry; `OUTCOME_UNKNOWN` for external-capable work; no invented threshold (Q-R5).
- **Recommended.** As §3. Amend spec D9 and §6.8 item 6 to the per-action rule (contradiction C-6). The safety factor stays unset until E1/E2 data exist; the 2× in the design is a placeholder.
- **Consequence.** *Safety:* a threshold too low mislabels a live slow leg (late legs outlive the turn and its lock); too high only delays recovery. *Implementation:* R5 (reconcile module, CLI, guarded transitions) is not started; no schema. *Dependency:* the target model host and deployment (design F1, F4).
- **Blocks.** ENABLE (VP-2); not S1–S3.

### D-7 Enablement configuration and the refusal outcome
- **Question.** What is the exact setting that turns approval on, what must be true for it to be on, and which turn status/outcome does a flagged action get when approval is off?
- **Approved.** Disabled when unset; flagged actions "refused with an explanation, never run unapproved" (D9; wording only: name and status are not specified).
- **Recommended.** One required setting with no default (`CEO_APPROVAL_ENABLED`); "on" additionally requires `CEO_LEG_TIMEOUT_SECONDS`, `CEO_PLAYBOOK_MAX_LEGS` and (after R5) `CEO_RECONCILE_STALE_AFTER_SECONDS` to be set and valid (fail closed); the refusal is a `DENIED` turn with a plain explanation (existing status, no new vocabulary), no leg dispatched, no unit.
- **Consequence.** *Security:* fail closed at configuration. *Behaviour:* while off, flagged chat actions are refused, which conflicts with the live confirm-card paths (D-8). *Implementation:* config + `.env.example`; S3.
- **Blocks.** S3.

### D-8 Interim status of the chat actions behind confirm cards
- **Status 2026-10-10.** The question below was settled for runtime by the instruction to close these paths: all six are **refused** until a stored plan exists (no interim confirmation-card execution). Re-enabling any of them from chat is a later decision tied to S3. The text below is kept as the record of the question; the four `cmo.generate_*` actions had **no** confirmation card (see F-6).
- **Question.** Until S3 plans exist, do `pi.discover`, `cmo.generate_title_sets/hashtags/description/keywords` and `cmo.market_trends` stay available from chat behind the in-session confirm card, or are they disabled?
- **Approved (both, in conflict).** C1/C3/Q-A5/Q12 (2026-10-10): metered or externally transmitting execution requires approval of a stored plan, and a clarification or confirm answer is not approval. Orchestration 6.35/6.40 (2026-10-10): these actions run from chat after a confirm card.
- **Recommended.** Keep the confirm card as a **documented, time-boxed interim** (the owner approved it, it names exactly what will run, and disabling would remove shipped features), recorded as an explicit dated exception to C1 that S3 removes; **do not claim approval-workflow compliance for these actions** until then. Correct the spec's §5.5 "Chat today" column and test scenario 2 (contradiction C-2).
- **Consequence.** *Security/billing:* until S3 they run with no hash binding, no 30-minute expiry, no requester-only check and no event trail; they are metered (CMO) or send seller data out (PI, CMO trends) on one confirmation. *Implementation:* none now; S3 replaces the confirm step with plan creation at `input_session.Done`. If instead disabled: a registry/`ActionPlan` change and a visible product regression.
- **Blocks.** S3, RELEASE.

### D-9 Accounting for a `PLANNED` turn
- **Question.** Confirm that a planning turn consumes no CEO unit and a declined or expired plan costs nothing; the approved execution turn is metered once if `DUE`.
- **Approved.** Not an explicit owner decision; stated as design in D6, §13.4 item 3 and AC-A15, and consistent with Q-R1.
- **Recommended.** Confirm. **Fact:** the current `unit_decision` already returns NOT_DUE for any non-`DELIVERED` status (including `PLANNED`, outcome `PLANNED`), so no billing code change is needed; what is missing is a **test that pins it**.
- **Consequence.** *Billing:* nothing to change; add one unit test with S3. *Legacy:* `PLANNED` turns exist only after the cut-over, so legacy handling does not apply. *Frontend:* the stored outcome for a non-delivered turn equals its status (the panel already ignores the outcome unless the turn is `DELIVERED`).
- **Blocks.** S3 (pin test only).

### D-10 Optional hardening and minor questions
- **Items.** O1 composite `(tenant_id, plan_id)` FK (the spec recommends it); O2 `SECURITY DEFINER` (see D-4); O4 usage recording for CFO/CI/GST; O5 `has_active_run`; O6 unify out-of-catalog statuses; O7 idempotency key on `POST …/turns`; F10 PI's double `agent_run`; Q-A4 reuse existing permission keys; Q-A8 how long declined/expired plans stay in the UI history.
- **Approved.** None. Q-A4 "reuse existing keys" is the spec's recommended design (no permission change).
- **Recommended.** Accept O1 and Q-A4 with S2; leave O4–O7 and F10 out of S1–S3; settle Q-A8 (UX) before S6.
- **Consequence.** O1 changes the S2 migration (a composite FK and `UNIQUE (tenant_id, id)`); Q-A4 means no `permissions.py` or `auth.md` change.
- **Blocks.** O1 and Q-A4: S2. The rest: nothing in S1–S3.

### D-11 Frontend verification in CI
- **Question.** Add a frontend job to `ci.yml` (lint, `tsc`, `vitest run --maxWorkers=4`, `next build`)?
- **Approved.** Nothing. The spec's S6 exit already requires "vitest/lint/tsc/build".
- **Recommended.** Add it before S6; until then the gate is local runs (198/198 with four workers).
- **Consequence.** CI only; no application change. Without it S6's exit criterion cannot be verified in CI. The design's AC-X counts (frontend 165, backend 4,5xx) are stale (now 198 and about 4,700) and should be reworded as "all existing suites green".
- **Blocks.** S6 exit; RELEASE.

### D-12 Development-database revision conflict
- **Question.** How is the dev database's recorded revision reconciled with the reassigned `20261010_0011` before any upgrade?
- **Approved.** The standing rule: scratch databases only for verification; the dev DB only after review, with a before/after fingerprint.
- **Fact.** An earlier session applied my `attachment_append_only` migration to the dev database under revision ID `20261010_0011`; the pulled branch now uses `20261010_0011` for `agent_memory`, and the build-status document says migrations through `…0010` were applied. The dev DB's real state has **not been inspected** (not in this task either).
- **Recommended.** Read-only inspection first (`SELECT version_num FROM alembic_version_backend;` and the PI table; `to_regclass('agent_memory')`; the app role's privileges on `investigation_attachment`). If it records `20261010_0011`, stop and report; the repair is a reviewed manual step (never an automatic `stamp`) that ensures `agent_memory` and `20261010_0012…0014` are applied and the attachment narrowing (now `20261011_0015`) is applied exactly once.
- **Consequence.** A blind `alembic upgrade head` would skip `agent_memory` (believed applied) and fail or leave tables missing at `0012`. No code change.
- **Blocks.** Any dev-DB upgrade (and therefore any dev-DB use of R0–R4).

---

## 6. Contradictions between the documents (and how each is resolved or flagged)

| # | Documents | Contradiction | Status / proposed resolution |
|---|---|---|---|
| C-1 | spec C6/D4/AC-A5 vs Q-A9 and the config convention | The value is fixed (1,800 s), but Q-A9 asks for a knob "seeded to 1800" while the repo's knobs have no default | Not contradictory in value; resolved by **D-3** (constant). No document gives a different number |
| C-2 | approval spec C1/C3/Q12/§5.5/test scenario 2 vs orchestration 6.35/6.40 | Approval spec: metered or seller-data-out actions require a stored plan, and says these actions are not chat-reachable ("Chat today = no"; scenario 2 expects `cmo.market_trends` → `PLANNED`). Orchestration spec: the same actions run from chat after a confirm card, owner-approved, same date | **Real conflict; D-8.** Amend §5.5 and scenario 2 to say "interim confirm card until S3" once the owner decides |
| C-3 | spec D6/§13.4 vs my earlier readiness text | The spec says `PLANNED` is never metered; my earlier draft said `unit_decision` "has no PLANNED rule" | **Corrected:** the code already returns NOT_DUE for any non-`DELIVERED` status; only a pinning test is missing (**D-9**) |
| C-4 | spec D6 vs orchestration D5/§6.42 | D5 ("one unit per user turn") vs the new rule | Already reconciled: D5 carries a "superseded in detail by §6.42" pointer |
| C-5 | spec §13.11 S1–S3 exit criteria vs S4 | AC-A5 (409 on expired approve), AC-A7 (hash at approval) and AC-A11 ("approve, decline or list") are in the S1–S3 exit list, but approve/decline are S4 and the GET endpoints have no stage | **D-5:** S1–S3 verify the repository / pure / RLS halves; endpoint halves in S4; GET endpoints assigned to S3. Spec to be amended |
| C-6 | spec D9 and §6.8 item 6 vs design R5.1/R5.6 and Q-S0-4/Q-R7 | Spec: staleness = `ceo_leg_timeout_seconds + margin`, "optional periodic task". Design and owner: per-action maximum, standalone one-shot CLI, **no** scheduler or thread in FastAPI. Code: late legs outlive the turn and its lock (`pool.shutdown(wait=False)`), so `leg_timeout + margin` can mislabel a live leg | **D-6:** the design and the owner decisions win; amend D9 and §6.8 |
| C-7 | spec §13.9 vs design §4 | §13.9 puts the reconciler inside new `ceo/approval.py`; the design (and the §13.11 inventory) makes it a separate `ceo/reconcile.py` with a CLI | The design wins (separate module); amend §13.9 |
| C-8 | spec AC-A10 and §5.2 ("no code path updates status without the event") vs §5.4 (app role keeps column `UPDATE (status, …)`) | With only a repository function the guarantee is code discipline, not enforced by the database | **D-4** |
| C-9 | spec §13.10 ("approval build after the prerequisites are accepted") vs §13.11 (the S1–S3 row has no such gate) vs the gate sentence ("P1 done … VP-1 and VP-2 PASS" to *enable*) | Whether S1–S3 may be built before R5 and VP-2 pass is not stated | Reading proposed here: S1–S3 may be built and reviewed once the owner accepts the prerequisite checkpoint (D-1, D-2, D-12, the full-suite gate); **enabling** needs VP-2. Owner to confirm (**D-5**) |
| C-10 | remediation design AC-X vs current counts | "frontend 165 tests, backend 4,5xx" are stale | Reword to "all existing suites green"; counts live in readiness §4 (**D-11**) |
| C-11 | build-status ("migrations through `20261010_0010` applied to dev", `…0011 agent_memory`) vs a prior session that applied a *different* `20261010_0011` to dev | Two meanings for the same revision ID | **D-12**; inspect before any upgrade |
| C-12 | approval spec §3 A5/VP-1 "FAIL" vs readiness R2/R3 "PASS (targeted)" | VP-1 stays FAIL by the design's own rule until R5 repairs and the full gate pass | Consistent; keep VP-1 and VP-2 FAIL and R2/R3 "PASS (targeted)" |
| C-13 | spec §3 A1 / §5.5 "36 actions" vs the registry | none: `test_ceo_effects` pins 36 and passes | No contradiction |

---

## 7. Recommended smallest next implementation task (after the review; not started)

**S1 only: the observe-only registry gate.** Preconditions: D-5 accepted (S1 as defined in §2); D-2 and D-12 reviewed so the prerequisite checkpoint is accepted; and the complete backend suite green in CI (or the owner explicitly accepting the targeted evidence for a pure-code, no-schema step).

- **Scope.** New `backend/src/backend/ceo/approval_gate.py` (pure functions `legs_requiring_approval(keys)` and `plan_required(keys)`; unknown key ⇒ required; playbooks expanded from the existing `PLAYBOOKS`/`ACTIONS` tables) and `backend/tests/unit/test_ceo_approval_gate.py`. Nothing imports the gate into the orchestrator, `input_session`, an API or the frontend.
- **Out of scope.** Any schema or migration; any endpoint; any refusal or planning behaviour; billing; permissions; config; the F-6 chat paths (they are only *listed* by a test).
- **Acceptance criteria.** (1) For every one of the 36 registered actions the gate agrees with its R1 `requires_approval`. (2) For every playbook and every guided-input route in `plans.py`: gated if and only if at least one leg is flagged (C11); with today's registry neither decision playbook is gated. (3) An action with meters, or `SELLER_DATA_OUT`, is never reported "not required". (4) An unregistered or empty key fails closed. (5) A test pins the exact set of **flagged actions reachable from chat today** (`pi.discover`, `cmo.generate_*`, `cmo.market_trends`), so any change is a reviewed diff (contradiction C-2 / D-8). (6) The unit suite (3,992 + the new tests) and lint pass; no integration, migration, config or frontend file changes; `git diff` shows only the two new files.
- **Why this one.** It is the only piece with no schema, no behaviour change and no dependency on D-1, D-3, D-4, D-7, D-8 or D-9; it gives S2 and S3 a tested rule to build on; and it turns the F-6 drift into a pinned, reviewable fact. S2 is next but needs D-3 and D-4; S3 needs D-1, D-3, D-7, D-8 and D-9.

## 8. Blockers (exact)
1. **S1** needs only D-5 (and acceptance of the prerequisite checkpoint, C-9). **S2** needs D-3, D-4 (and D-10's O1/Q-A4). **S3** needs D-1, D-3, D-7, D-8, D-9 (and S2 accepted).
2. **Approval cannot be enabled** until VP-2 passes, which needs R5 and its evidence (D-6); R5 stays BLOCKED.
3. **The complete backend suite has not passed on the merged tree** (§4.2).
4. **The dev-database revision conflict** (D-12) is uninspected.
