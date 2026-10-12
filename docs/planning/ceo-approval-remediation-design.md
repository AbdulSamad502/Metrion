# CEO approval prerequisites — remediation design (R0–R7), revision 2

**Status:** Design for review. **Nothing here is implemented**; no schema, billing, endpoint or database change has been made. Experiments (if any are needed to validate the design) stay on the isolated scratch Postgres (`:5544`); the development database is not touched.
**Date:** 2026-10-10 · **Inputs:** `docs/planning/ceo-approval-s0-findings.md`, `docs/specs/ceo-approval-workflow.md` (§12–§13), owner decisions of 2026-10-10 (Q-S0-1…4, Q-R1…10).
**Out of scope for the implementation checkpoint that follows this design:** plan creation, approval endpoints, approval execution, the workflow editor.
**Revision 2** applies Q-R1…Q-R10, adds R0 (accounting cut-over), R6 (PI quota reservation) and R7 (LLM endpoint guard), and lists the facts that are still unresolved (§5).

## 0. Decisions applied
| Decision | Applied as |
|---|---|
| **Q-S0-1** one idempotent usage event per **successful** PI run; failed runs consume nothing | R3 |
| **Q-S0-2** GST public fetch / internal LLM do not independently need approval; classify actual data flows | R1 (data-flow table) + R7 (what "internal" means) |
| **Q-S0-3** exact CEO-unit outcomes; idempotent; no double charge in recovery | R2 / §1.1 |
| **Q-S0-4** lazy + periodic recovery; separately testable runner; never retry unknown outcomes | R5 |
| **Q-R1** any failed required leg ⇒ no CEO unit, even if an optional leg succeeded; optional results may still be returned with the failure/partial status shown | §1.1 rule, R2 (stored `outcome`, shown in the UI) |
| **Q-R2** a PI `PARTIAL` run is billable only if it yields a valid, usable partial result under a documented criterion; empty/failed/interrupted are not billable; ≤ 1 idempotent event per run | §1.2 criterion, R3 |
| **Q-R3** only successful `research.niche_run` executions count toward usage/entitlement; keep started/failed/interrupted/successful counts separate; check consumers before changing a field | §1.3, R3 (consumer audit; `niche_run_count` is **not** repurposed) |
| **Q-R4** no refunds, retroactive charges or backfills; explicit cut-over timestamps; the reconciler never reinterprets legacy records | R0 + §1.4 |
| **Q-R5** no invented staleness threshold; derive from timeouts and measured durations with a margin; validated config, no silent default; report a blocker if evidence is insufficient | R5.6 and §5 (**blocker reported**) |
| **Q-R6** preserve `OUT_OF_SCOPE` billing if documented and successfully delivered; keep distinct from failed execution | §1.1 (explicit rule + outcome `DECLINED`); documentation gap reported in §5 |
| **Q-R7** reconciler = standalone one-shot CLI, no scheduler in FastAPI; scheduler deployment documented only after the environment is confirmed | R5.1; §5 (**environment unconfirmed**) |
| **Q-R8** no quota overshoot once PI caps are enabled; atomic reservation before any cap is seeded; concurrent-last-unit test; until then, explicitly "caps not enforced" | R6 |
| **Q-R9** guard that the LLM endpoint is operator-controlled; if unverifiable, classify as external and apply the disclosure policy | R7; the disclosure **policy itself is undefined** (§5) |
| **Q-R10** `pi.supplier_lookup` payload = public candidate titles + the fixed suffix; approval because metered; reclassify if the payload changes | R1 payload pin test |

---

## 1. Exact billing outcomes (each row becomes a test)

### 1.1 CEO conversation unit (`ceo.chat_turn`, qty 1, key `ceo:turn:<turn_id>`)
**Invariant:** a CEO turn with **any** failed required leg consumes **no** CEO unit, regardless of optional-leg success. A delivered answer alone does not establish successful execution.
The decision is computed **once, when the turn is finalised**, by one pure function, and stored **once** on the turn (`investigation_turn.safety_result.billing`, an existing jsonb column; first writer wins). Every later actor (repair, reconciler) trusts the stored decision.

`unit_decision(turn_created_at, cutover, status, route, planned_leg_keys, required_keys, legs)`:
1. `turn_created_at < cutover` → **LEGACY**: no decision is made or stored; never repaired, charged or refunded.
2. `status != DELIVERED` → **NOT_DUE** (`TURN_NOT_DELIVERED`), outcome `FAILED` (or `CLARIFIED`/`DENIED` as the turn status says).
3. `route == OUT_OF_SCOPE` → **DUE** (`OUT_OF_SCOPE_DELIVERED`), outcome **`DECLINED`** — a successfully delivered explanation; distinct from failed execution (Q-R6; see §5 for the documentation gap).
4. No legs planned (Business State read, advisory, synthesise, legless playbook) → **DUE** (`NO_LEGS`), outcome `SUCCEEDED` (but see open fact Q-R12 for an UNAVAILABLE-only state read).
5. Let `R = required_keys` (if empty, every planned leg). A leg **failed** iff its status ∈ {`FAILED`, `UNAVAILABLE`, `DENIED`, `NOT_ENTITLED`} or it did not finish by the leg deadline. If **every** leg in `R` is `COMPLETE`/`PARTIAL` → **DUE** (`ALL_REQUIRED_LEGS_SUCCEEDED`); otherwise **NOT_DUE** (`REQUIRED_LEG_FAILED`) even if optional legs succeeded.
**Outcome** (stored with the decision, returned additively as `outcome`, shown in the UI as a status): `FAILED` = a required leg failed; `PARTIAL` = every required leg ok but ≥ 1 optional leg failed/missing, or a leg ended `PARTIAL`; `SUCCEEDED` = all legs `COMPLETE`; `DECLINED` = out-of-scope reply. Optional results are still returned and shown with that outcome.
(`PARTIAL` leg = a payload that carries a data request or `partialReason`. Whether such a leg is a *usable* result is open fact Q-R11; until decided it counts as not failed.)

| Outcome | Turn status | Required legs | CEO unit | Stored decision / reason |
|---|---|---|---|---|
| **Full success** | `DELIVERED` | all `COMPLETE` | **1** | DUE · `ALL_REQUIRED_LEGS_SUCCEEDED` · SUCCEEDED |
| **Partial success** — every required leg ok, an optional leg failed or a leg `PARTIAL` | `DELIVERED` | all ok | **1** | DUE · `ALL_REQUIRED_LEGS_SUCCEEDED` · PARTIAL |
| **Failure — answered** (≥ 1 required leg raised/unavailable/denied; the CEO still answers and names the gap), incl. one required leg ok + another required failed, and required failed + optional ok | `DELIVERED` (unchanged) | any failed | **0** | NOT_DUE · `REQUIRED_LEG_FAILED` · FAILED |
| **Failure — refused / deadline** | `FAILED`/`DENIED` (unchanged) | — | **0** | NOT_DUE · `TURN_NOT_DELIVERED` |
| **Clarified / denied / out-of-catalog** | `CLARIFIED`/`DENIED` | — | **0** | NOT_DUE · `TURN_NOT_DELIVERED` |
| **Out of scope, delivered** | `DELIVERED` | — | **1** (today's behaviour, now explicit) | DUE · `OUT_OF_SCOPE_DELIVERED` · DECLINED |
| **Interrupted before delivery** | reconciled to `FAILED` | — | **0** | NOT_DUE · `INTERRUPTED` (written by the reconciler under the investigation lock) |
| **Interrupted after the decision was stored, before the event was written** | `DELIVERED` | per stored decision | **1 if DUE**, written by repair | as stored |
| **Late optional leg** finishing after delivery | unchanged | unchanged | no change | decision is final |
| **Seller retries** | new turn | — | charged on its own merits, once | — |
| **Legacy turn** | any | — | **never** re-evaluated, repaired, refunded | none |
**Exactly-once mechanics:** (a) finalisation is a guarded `UPDATE … WHERE id=:id AND completed_at IS NULL` that returns whether *this call* finalised the turn; **only that call** stores the decision and writes the event; (b) the event uses key `ceo:turn:<id>` (`ON CONFLICT DO NOTHING`, existing and tested); (c) repair uses the same key; (d) the reconciler only acts when it holds the investigation lock, so a live finaliser and a reconciler can never both act on one turn.

### 1.2 PI usage — events and the "usable result" criterion
Events: `pi.discover` (agent `PI`) **and** `research.niche_run` (agent `SHARED`, the shared-service meter, like CMO's shared trends meter), both qty 1, **only** for a successful discover; `pi.supplier_lookup` (agent `PI`) for a successful lookup. Event kind goes through the existing `metered_event_meter_map` so the pre-flight check and the recorded usage share a bucket. **At most one event per meter per run** (key `pi:run:<pi_research_run.id>:<meter>`; lookup: `pi:supplier:<route agent_run id>`).
**Usable-result criteria (documented, testable; owner may adjust before implementation):**
- `pi.discover` is **billable** iff the run ended `COMPLETE` or `PARTIAL` **and** it persisted ≥ 1 `product_candidate` for the run with `proxy_state = 'COMPUTED'` and a non-null `proxy_score` (the same predicate the run itself uses to build its shortlist). Evidence for needing this: today a run with **no candidates** is `PARTIAL` (`discovery_run.py` marks `partial_reason` when `not rows`), and a `COMPLETE` run could in principle be empty.
- `pi.supplier_lookup` is **billable** iff the call returned and ≥ 1 per-candidate result has a non-empty `lead_ids`; all-empty or all-degraded-without-leads is not billable.
| Outcome | Stored decision | Events |
|---|---|---|
| `COMPLETE`, usable | DUE · `USABLE` | 1 per meter |
| `PARTIAL`, usable (some sources down but ≥ 1 computed candidate) | DUE · `USABLE_PARTIAL` | 1 per meter |
| `PARTIAL`/`COMPLETE` with **no usable candidate** (empty) | NOT_DUE · `EMPTY_RESULT` | 0 |
| `FAILED` (refusal, brief not READY, exception) | NOT_DUE · `FAILED` | 0 |
| Interrupted (reconciled) | NOT_DUE · `INTERRUPTED` / `OUTCOME_UNKNOWN` | 0 |
| Duplicate settle, concurrent settle, repair after a write failure | — | still ≤ 1 per meter |
| HTTP/seller retry | a new run, its own decision | its own event if usable (PI has no client idempotency key; unchanged) |

### 1.3 `research.niche_run` — usage vs operational counts (Q-R3)
Consumer audit (searched `backend/`, `packages/`, `frontend/`, `docs/`): `NicheRunEntitlementResult.niche_run_count` is read only by `api/v1/pi.py` (the 402 body key `nicheRunCount`), constructed in `entitlement.py` and in unit tests; `pi_research_run_repo.count_runs_for_tenant` is read only by `entitlement.py`; **no frontend or document consumes either.**
Decision: **do not repurpose** `niche_run_count` or `count_runs_for_tenant` (both keep meaning "rows ever started"). Add separate, named counts — `started`, `failed`, `interrupted`, `successful` (new `pi_research_run_repo.operational_counts(tenant)`) — and a new result field `niche_runs_successful`. **Usage and entitlement enforcement use only the successful count** (recorded `research.niche_run` events), never the operational counts. The 402 body gains `nicheRunsSuccessful` (additive) and keeps `nicheRunCount` (documented as "started").

### 1.4 Cut-over and legacy records (Q-R4)
No refunds, no retroactive charges, no backfill. Explicit cut-over timestamps live in a durable platform table (R0), not an environment variable that could drift. The reconciler and every repair require **both** a stored decision/`created_at ≥ cut-over` **and** a matching cut-over code; a record without them is "legacy" and is neither billed nor interpreted. Legacy rows stuck in a non-terminal state stay as they are (reported by the CLI as `legacy_skipped`, never altered).

### 1.5 Unchanged
CMO artefacts/reports (per COMPLETE, replay-free, reservation-protected).

---

## R0. Accounting cut-over records (new, small migration)
**Problem:** Q-R4 needs explicit, durable cut-over timestamps; `pi_research_run` has **no `created_at`** (only `started_at`, null while `QUEUED`), so PI runs cannot be dated at all today.
**Design:** (1) core migration `20261011_0017_accounting_cutover`: platform table `accounting_cutover(code text primary key, effective_at timestamptz not null, recorded_at timestamptz not null default now(), note text not null)`; no `tenant_id`, no RLS (like `plan`); **`REVOKE ALL … FROM metrion_app; GRANT SELECT`** (default privileges would otherwise let the app delete it); migration inserts `CEO_UNIT_RULE_2` , `PI_USAGE_1`, `NICHE_RUN_USAGE_1` with `effective_at = now()` of the migration run; downgrade removes them. (2) PI-package migration `packages/product-intelligence/migrations/versions/20261011_0002_pi_run_accounting.py`: nullable `pi_research_run.created_at timestamptz`, `outcome_code text`, `usage_due boolean` (legacy rows keep NULL ⇒ legacy). `create_run` sets `created_at = now()`; the finaliser writes `outcome_code`/`usage_due` once.
**Rollout order:** migrate, then deploy. Old workers still running during the overlap may create post-cut-over rows without a stored decision; those are **legacy by construction** (no decision ⇒ never repaired or reinterpreted).
**Success criteria:** the app role cannot `UPDATE`/`DELETE`/`INSERT` `accounting_cutover` (direct SQL as `metrion_app`); legacy `pi_research_run` rows read `created_at IS NULL`; downgrades round-trip on an empty DB (CI) and refuse nothing silently. **Failure-injection tests:** a turn/run created before the cut-over is untouched by every repair; a post-cut-over row with no stored decision is untouched; moving a cut-over later in a test makes previously eligible rows legacy again, never the reverse.

## R1. External-effect registry metadata (code only; no behaviour change)
**Design:** new `backend/src/backend/ceo/effects.py` with one explicit, reviewed table `ACTION_EFFECTS`; `ActionSpec` gains a **required** `effects: ActionEffects`; registry construction fails on a missing/unknown key.
```
ActionEffects: meters (codes actually recorded), external: NONE|MODEL|PUBLIC_FETCH|SELLER_DATA_OUT, egress (seller data classes that leave Metrion),
               destinations (plan-card labels), model_egress (what the LLM endpoint receives), worst_case_seconds (structural upper bound, R5.6),
               requires_approval (DERIVED: bool(meters) or external == SELLER_DATA_OUT; may be forced True, never False for those cases)
```
**Data flows (evidence; approval = metered, or seller-specific confidential data leaves Metrion):**
| Action(s) | Leaves Metrion (to whom) | `external` | Meters (after R3) | Approval |
|---|---|---|---|---|
| `cfo.*` computations, `cfo.preview`, `pi.report`, `cmo.suggest_niche_terms`, `cmo.market_trends_preview`, `RECORD_CHOICE` | nothing | NONE | — | no |
| `cfo.period_comparison` | figures/labels → LLM endpoint | MODEL | — | no (while R7 says INTERNAL) |
| `cfo.gst_lookup`, `service.gst_lookup` | fixed public URLs (no seller data in the request); product title → LLM endpoint | PUBLIC_FETCH + MODEL | — | **no** |
| `ci.request_price_scenario` | nothing | NONE | — | no |
| `ci.discover_competitors` | nothing today (`MockSearchProvider`); **pinned by a guard test** | NONE | — | no today |
| `pi.discover` | seller-entered **niche category text**, in 3 query variants, → Tavily, YouTube | SELLER_DATA_OUT | `pi.discover`, `research.niche_run` | **yes** |
| `pi.supplier_lookup` | `<public candidate title> manufacturer supplier wholesale india` → Google Places, Tavily (Q-R10) | PUBLIC-derived payload (not seller-entered) | `pi.supplier_lookup` | **yes** (metered) |
| `cmo.generate_*`, `cmo.catalog_answer` | catalog text → LLM endpoint | MODEL | per-output meters | **yes** (metered) |
| `cmo.market_trends` | seller-**confirmed** niche terms only → Tavily, YouTube | SELLER_DATA_OUT | two meters | **yes** |
**Payload pin tests (Q-R10, and the same pattern for `pi.discover`/`cmo.market_trends`):** with fake provider clients that record every outgoing query: `pi.supplier_lookup` queries must equal `f"{title} manufacturer supplier wholesale india"` where `title` is a persisted `product_candidate.candidate_title` of that run; `pi.discover` queries must be exactly the three variants of `category_text`; a change to either payload shape (e.g. adding a SKU, brand or price) fails the test and forces a reclassification review in the same change.
**Files:** new `ceo/effects.py`; edit `ceo/contract.py`, `ceo/registry.py`. **Migration:** none.
**Success criteria / tests:** all 36 keys covered both ways; derivation matches the table; non-NONE/MODEL externals list a destination; the `MockSearchProvider` pin fails if the provider type changes without editing `ACTION_EFFECTS["ci.discover_competitors"]`; a snapshot of the derived approval set.

## R2. CEO unit semantics (billing change — review required)
**Design:** `ceo/billing.py` (pure `unit_decision`, §1.1); `repositories/investigation_repo.py` gains `finalise_turn(...) -> bool` (guarded, first-writer-wins decision); `orchestrator._finish` calls it and **meters only when it returned `True` and the decision is DUE**; the `outcome` is added to the turn projection and the turn response (additive), and `frontend/lib/ceoModel.ts`'s `messageView` shows `FAILED`/`PARTIAL` for a `DELIVERED` turn (today the badge only exists for turn status `FAILED`). Repair (R5c) uses the stored decision.
**Files:** new `ceo/billing.py`; edit `ceo/orchestrator.py`, `repositories/investigation_repo.py`, `api/v1/ceo.py` (projection), `frontend/lib/ceo.ts`, `frontend/lib/ceoModel.ts`. **Migration:** none (R0's cut-over row only).
**Failure-injection tests:** (1) one required leg raises → `DELIVERED`, no unit, outcome FAILED; (2) required A ok + required B fails → no unit; (3) required fails + optional ok → no unit, optional finding still returned; (4) all required ok + optional fails → 1 unit, outcome PARTIAL; (5) required `PARTIAL` → 1 unit; (6) `DENIED`/`NOT_ENTITLED` required → no unit; (7) no-leg routes → 1 unit; (8) out-of-scope delivered → 1 unit with outcome `DECLINED`, and a refused/failed turn → none; (9) `record_metered_event` returns `None`/raises → answer delivered, decision DUE stored, repair writes exactly one event; (10) repair ×2 and from two concurrent threads → one event; (11) child process killed **after** finalisation, **before** the meter write → repair writes one; (12) killed **before** finalisation → reconciled `FAILED`, never charged; (13) finalise called twice (second returns `False`, stores nothing, meters nothing); (14) a turn created before the cut-over, or without a stored decision, is never repaired; (15) all existing CEO tests unchanged.

## R3. PI usage recording (billing change — review required)
**Design:** after the route's own `finish_run` in `api/v1/pi.py` (`post_discover`, `post_supplier_lookup`; both the direct and the CEO path call these), `services/pi_usage.py` evaluates the §1.2 criterion **once**, stores it (`pi_research_run.usage_due`/`outcome_code`; supplier lookup stores it on the route's `agent_run.output_refs`), and writes the events only when DUE and the run is at/after the cut-over. Writes are best-effort like CMO's (a failure never blocks the response and is repaired). Failed/interrupted/empty runs write nothing. `research.niche_run` is recorded alongside `pi.discover`.
**Consumers:** `resolve_niche_run_entitlement` gains `niche_runs_successful` (from recorded events) and enforcement uses it (§1.3); `niche_run_count` keeps its meaning.
**Files:** `backend/src/backend/api/v1/pi.py`, new `services/pi_usage.py`, `entitlement.py` (new field + successful-events count), `repositories/entitlement_repo.py` (count helper), PI package `repositories/pi_research_run_repo.py` (`create_run` sets `created_at`; `operational_counts`; `record_outcome`), PI migration from R0. 
**Failure-injection tests** (fakes for Tavily/YouTube/Places as in `test_pi_discover_api.py`): (1) usable `COMPLETE` → events for both meters, ≤ 1 each; (2) usable `PARTIAL` (YouTube down, ≥ 1 computed candidate) → billed; (3) `PARTIAL` with **zero** candidates → not billed, `EMPTY_RESULT`; (4) `COMPLETE` with zero usable candidates → not billed; (5) `FAILED` (brief not READY) → none; (6) exception after external calls succeeded → run `FAILED`, none; (7) supplier lookup with ≥ 1 lead → 1 event; all-empty → none; (8) write failure → HTTP 200, no event, repair later writes exactly one; (9) settle twice and from two threads → one row per meter; (10) child process killed mid-run → reconciled `FAILED`/`OUTCOME_UNKNOWN`, none, stable under repeated reconciliation; (11) live run finishes **after** the reconciler marked it → exactly the right events once, final status true; (12) a run before the cut-over (or with `created_at IS NULL`) is never repaired; (13) operational counts (`started/failed/interrupted/successful`) are mutually consistent and independent of the usage count; (14) `niche_run_count` and `nicheRunCount` still return "started"; (15) CMO and CEO metering tests unchanged.

## R4. `PLANNED` status vocabulary (tiny migration; no producer)
Unchanged from revision 1: constants `TURN_STATUSES`/`TERMINAL_TURN_STATUSES` in `ceo/contract.py` replace the `orchestrator.py:271` whitelist; migration `20261011_0016_turn_status_planned` replaces `investigation_turn_status_check` adding `PLANNED` (downgrade refuses if any `PLANNED` row exists); `frontend/lib/ceo.ts` `TurnStatus` + `ExecutionPanel` map it neutrally; **nothing produces `PLANNED`** in this checkpoint. **Tests:** round-trip through `update_turn`/`finalise_turn`; never stored as `FAILED`; never metered; Python constant == DB constraint (drift test via `pg_get_constraintdef`); upgrade/downgrade on scratch incl. refusal with a `PLANNED` row; frontend renders it neutrally.

## R5. Crash reconciliation — standalone CLI + lazy trigger
**R5.1 Shape (Q-R7).** `backend/src/backend/ceo/reconcile.py` (pure transition logic over repository functions) with `reconcile_investigation(tenant, investigation_id, now)` (lazy: called, bounded and exception-safe, from the investigation-detail read and the start of `run_turn`), `reconcile_tenant(...)` and `run_once(...)`. **The periodic runner is a standalone one-shot CLI**: `python -m backend.ceo.reconcile --once [--tenant UUID] [--dry-run] [--limit N]`, JSON report on stdout, exit 0 on success / non-zero on configuration refusal or partial failure; it is idempotent and safe to overlap. **Nothing is scheduled inside FastAPI and there is no background thread.** Scheduler deployment is **not documented yet**: the deployment target has never been chosen (readiness review item 2.19 `[P]`; the repo has no Dockerfile/IaC and `backend/README.md` states there is no deployment layer). Until that is confirmed, the docs contain only the CLI contract and how to run it by hand.
**R5.2 Liveness proof.** For rows with an `investigation_id`: `pg_try_advisory_lock` on the investigation (existing `AdvisoryLock`); if not acquired → a live turn → skip; if acquired → no live turn in that investigation, so a non-terminal turn/leg there is dead — and still must be older than its stale threshold (R5.6). Rows with no investigation (direct-path PI runs) have no lock: age only, and only ever marked `FAILED`/`OUTCOME_UNKNOWN`, never "recovered".
**R5.3 Transitions (guarded, idempotent, one transaction per row; a guarded `agent_run_repo.finish_run_if_unfinished` replaces today's unconditional `finish_run` for reconciliation):**
| Row | From | To |
|---|---|---|
| leg `agent_run` | `QUEUED`/`RUNNING` | `FAILED`, `error_reason = OUTCOME_UNKNOWN` if the action's `external != NONE`, else `INTERRUPTED` |
| CEO anchor `agent_run` | `RUNNING` | `FAILED`/`INTERRUPTED` |
| `investigation_turn` | `completed_at IS NULL` | `FAILED`; stores `billing` = NOT_DUE/`INTERRUPTED`/FAILED and `recovery:{reason,outcomeUncertain,legs,at}` — **only if no decision is already stored** |
| unanswered `USER` message | — | one `SYSTEM_NOTE`, only when the turn transition changed a row |
| `pi_research_run` (post-cut-over, `created_at` set) | `QUEUED`/`RUNNING` | `FAILED`, `outcome_code = INTERRUPTED` or `OUTCOME_UNKNOWN` (external) , `usage_due = false` |
`DELIVERED` turns are never modified by R5a/b. Legacy rows (§1.4) are counted as `legacy_skipped` and never touched.
**R5.4 Repairs (R5c; key-based, never a retry):** CEO unit for `DELIVERED` turns whose stored decision is DUE; PI events for runs whose stored `usage_due` is true; both at/after the cut-over, both via the same idempotent keys as the live paths.
**R5.5 Never retries.** The module imports no dispatch/registry `invoke`; a test installs a registry whose handlers fail the test if called.
**R5.6 Staleness threshold (Q-R5) — derivation, no invented number.** Config `CEO_RECONCILE_STALE_AFTER_SECONDS` is **required, validated, no default**. Validation rejects a value below a **computed floor**: `safety_factor × max(worst_case_seconds)` over the actions the reconciler can see, where each action's `worst_case_seconds` is derived **in code from the same constants and configured timeouts the action uses** (so it cannot silently drift). Evidence gathered (structural, from the code — **not measurements**):
- Client timeouts: Tavily 10 s, YouTube 10 s, Google Places 10 s, embeddings 30 s, PI product-extraction LLM 90 s, PI review-insight LLM 90 s, GST fetch 10 s, CMO LLM `CMO_LLM_TIMEOUT_SECONDS=120` (dev `.env`), CEO LLM `CEO_LLM_TIMEOUT_SECONDS` (required, no default, and not set in the dev `.env`; an in-repo note says a CPU host measured 15–200 s per call), `CEO_LEG_TIMEOUT_SECONDS` (optional, unset).
- `pi.discover` structure: 3 Tavily + 3 YouTube queries in one parallel wave (≤ 10 s each); product extraction one LLM call per unique result text with 5 workers (author's note: "~6–20 calls"; hard cap by constants ≤ 60 texts ⇒ ≤ 12 waves × 90 s); review insight for ≤ 15 shortlisted candidates (5 workers, ≤ 3 waves × (90 s + YouTube comment fetches)); embeddings batched ≤ 30 s or ≤ 6 waves × 30 s. **Structural upper bound ≈ 1,640 s (≈ 27 min); the author-expected case is ≈ 10 min or less.** `pi.supplier_lookup` ≈ 70 s per candidate, one wave of ≤ 5 ⇒ ≈ 70–140 s.
- No measured end-to-end durations from the target host exist in the repo (only an embedding timing note), and the LLM hardware/deployment are undecided.
**Conclusion: the evidence is sufficient to compute a *floor* (and to make the floor self-updating) but **insufficient to choose the final value**; that is reported as a blocker in §5.** Provisional method: `stale_after ≥ 2 × structural bound` (≈ 3,300 s for PI discover on today's constants), recalibrated by a measured run on the target host. A larger value only delays recovery of crashed runs; a too-small value risks mislabelling a live slow run, which the lock proof and the "live finisher wins" rule (R5.5 below) already contain for CEO turns.
**R5.7 Uncertain outcomes.** Never retried, never charged; the report lists them. If a live process later finishes the same leg/run, its true terminal status and usage (idempotent keys) win.
**Files:** new `ceo/reconcile.py`; edit `repositories/agent_run_repo.py`, `repositories/investigation_repo.py`, `api/v1/ceo.py` (lazy trigger), `ceo/orchestrator.py` (lazy trigger), `config.py` + `.env.example`, `backend/README.md` (CLI contract only), PI package `pi_research_run_repo.py`. **Migration:** none beyond R0.
**Failure-injection tests (scratch DB; child processes where noted):** (1) kill mid-leg → turn/anchor `FAILED`, leg `INTERRUPTED`, one note, no usage; (2) reconcile ×3 and concurrently → identical state, one note; (3) kill mid-leg of an external-capable leg with a fake provider counter → `OUTCOME_UNKNOWN`, provider call count unchanged by recovery; (4) live turn (lock held elsewhere) → skipped, untouched; (5) threshold boundary with an injected clock (±1 s); (6) kill the reconciler itself mid-run → rerun converges; (7) late live finisher after a reconciler mark → true status and one event; (8) CEO-unit repair and PI repair: exactly-once, concurrent-safe, legacy/undecided rows untouched; (9) cut-over: rows before it never touched; (10) never-retries test; (11) tenant isolation; (12) `--dry-run` changes nothing; (13) threshold config unset or below the computed floor → refuses with a clear error, changes nothing; (14) CLI as a subprocess with no web server (`--once`, `--tenant`, exit codes).

## R6. PI quota reservation (no overshoot before any cap is enabled)
**Evidence:** CMO already has the machinery — `cmo_quota_reservation` (migration 0005; generic columns `agent_code`, `meter_code`, `period_key`, `units`, `request_key`, state `RESERVED/SETTLED/RELEASED`, TTL) and `cmo_quota_repo.reserve()` (one transaction: `pg_advisory_xact_lock` on tenant+agent+meter+period, expire stale reservations, `usage = metered + unexpired reserved`, then insert) — introduced because **a plain check-then-record let 7 of 8 concurrent requests pass a cap of 1** (migration 0005's own note). Today PI has no reservation.
**Strategy (recommended; owner confirmation in §5):** reuse the existing table and `reserve`/`finish` for `agent_code = 'PI'` (`pi.discover`, `pi.supplier_lookup`) and `agent_code = 'SHARED'` (`research.niche_run`), through a neutral wrapper module `repositories/quota_reservation_repo.py` (no migration, no table rename now; the `cmo_` prefix is a documented naming wart). Flow for `pi.discover`: pre-flight (permission) → reserve `research.niche_run` then `pi.discover` (separate short transactions; if the second is denied, release the first, as CMO trends does) → run → on usable success write both events then mark both `SETTLED`; on failure/empty → `RELEASED`; crash → the reservation counts until its TTL, so an interrupted run cannot be used to exceed the cap. Reservation key `pi:discover:<route agent_run id>` (one active reservation per request). `PI_QUOTA_RESERVATION_TTL_SECONDS` is **required when any cap is configured, validated ≥ the same computed floor as R5.6** (an expired reservation of a still-running run is the one way to overshoot), no default; missing ⇒ `503 PI_NOT_CONFIGURED`. When no cap is configured (`NO_CAP_CONFIGURED`) nothing is reserved (as CMO).
**Gate (Q-R8):** until R6 is merged **and** its concurrency tests pass, **PI caps are not enforced and no cap may be seeded**; documents say so explicitly. A guard test fails if a PI/SHARED cap row is seeded while the reservation path is disabled.
**Files:** new `repositories/quota_reservation_repo.py`, `services/pi_usage.py`, `api/v1/pi.py`, `entitlement.py` (cap resolution for `research.niche_run` like `resolve_market_trends_entitlement`), `config.py`. **Migration:** none.
**Concurrency / failure-injection tests:** (1) **N = 8 threads (and a second run with processes) competing for the final unit** at cap 1 → exactly one reservation, exactly one run executes, exactly one event per meter, seven refused `402 OVER_CAP`; (2) the same through the HTTP route with fakes that hold a barrier inside the provider call so runs genuinely overlap; (3) winner fails → reservation `RELEASED` → the next request proceeds; (4) winner killed → reservation holds the unit until `expires_at`, others refused, then one proceeds; (5) metering write fails → reservation stays `RESERVED`, delivery not blocked, repair settles it; (6) `research.niche_run` denied after `pi.discover` reserved → first released; (7) double-submit of the same request key → "in progress", not a second unit; (8) successful runs only count toward the cap (failed/empty/interrupted do not); (9) CMO reservation tests unchanged.

## R7. LLM endpoint guard (Q-R9)
**Evidence:** only the CEO model layer refuses a non-local host (`backend/llm/model.py`: regex `localhost|127.0.0.1|[::1]`). Every other call site builds its client from an **unchecked** URL: `config.ollama_host()` (default `http://localhost:11434`; used by CFO narration, GST extraction, PI extraction/embeddings), `cmo_ollama_host()` (required, no default), CI `ollama_client`; `CMO_LLM_PROVIDER`/`CEO_LLM_PROVIDER` allow other registered providers. The stated policy (`config.ollama_host` docstring, C15) is "always a local address, never a hosted provider" but it is **only enforced for the CEO**.
**Design:** one function `llm_endpoint_trust(url) -> INTERNAL | EXTERNAL` in `config.py`: `INTERNAL` iff the host is a loopback literal **or** an exact `host[:port]` that the operator listed in `LLM_OPERATOR_CONTROLLED_HOSTS` (an explicit attestation; private-range addresses are *not* assumed operator-controlled); anything else — including a non-Ollama provider or an unparsable URL — is `EXTERNAL`. All factories (`ollama_host`, `cmo_ollama_host`, CEO, CI, PI) call it at construction. **Consequence of EXTERNAL (fail closed):** (a) CEO turns and any seller-data-bearing model call refuse with a clear configuration error (retaining today's CEO behaviour and extending it to the other call sites); (b) `ActionEffects.external` is evaluated at registration time with the trust result, so MODEL-tier actions become `SELLER_DATA_OUT` ⇒ approval-required **and** blocked unless a data-disclosure policy is configured. **The applicable data-disclosure policy does not exist in the repo** (searched specs and the readiness review; `auth.md` V5 lists identity-data residency only), so the policy configuration (`LLM_EXTERNAL_DISCLOSURE_POLICY_ID`) is a placeholder and the unresolved fact is reported in §5.
**Files:** `backend/src/backend/config.py`, `llm/model.py`, `services/ceo_runtime.py`, `services/cfo_actions.py`, `services/pi_actions.py`, `services/cmo_runtime.py`, CI `ollama_client` composition root, `ceo/effects.py`. **Migration:** none.
**Tests:** loopback/attested/`localhost.evil.com`/private-IP/`http://[::1]` cases; unparsable URL ⇒ EXTERNAL; a non-Ollama provider ⇒ EXTERNAL; EXTERNAL + no policy ⇒ every call site refuses and no request leaves the process (a fake transport proves zero connections); the derived approval set changes when trust flips (snapshot test).

---

## 2. Isolation and dependency matrix
| Fix | Independent? | Depends on | Billing change? | Migration |
|---|---|---|---|---|
| **R4** `PLANNED` vocabulary | yes | — | no | `20261011_0016_turn_status_planned` |
| **R0** cut-over records | yes | — | no (enables the others) | `20261011_0017_accounting_cutover` + PI `20261011_0002_pi_run_accounting` |
| **R1** effects metadata | yes | — | no | none |
| **R7** LLM endpoint guard | yes (R1 consumes its result) | — | no | none |
| **R2** CEO unit | yes | R0 | **yes** | none |
| **R3** PI usage | needs R0; reservation parts need R6 | R0 (R1 for meters) | **yes** | PI migration (R0) |
| **R6** PI quota reservation | yes | R0, R3's events | no (enforcement) | none |
| **R5a/b** reconciliation | mostly | R0, R1 | no | none |
| **R5c** repairs | no | R2, R3, R0 | writes usage idempotently | none |
**Proposed order:** R4 → R0 → R1 ∥ R7 → R2 ∥ R3 (+R6 before any cap is seeded) → R5a/b → R5c. Billing changes (R2, R3) each land behind their own tests and are reviewed before any dev-database exposure; the dev database is migrated only after review with a before/after fingerprint.

## 3. Proposed acceptance criteria (for the implementation checkpoint)
- **AC-R0** `accounting_cutover` exists with the three codes; the app role has `SELECT` only; legacy rows are identifiable (`created_at IS NULL` / no stored decision).
- **AC-R1** Every one of the 36 registered actions has an effects entry; derivation, destinations, payload pins and the `MockSearchProvider` pin pass; the derived approval set is snapshot-tested.
- **AC-R2** The §1.1 table holds exactly: any failed required leg ⇒ no CEO unit regardless of optional success; `OUT_OF_SCOPE` delivered ⇒ one unit with outcome `DECLINED`; the decision is stored once (first writer wins) and the event is written only by the finalising call; `outcome` is visible to the UI for `DELIVERED` turns.
- **AC-R3** PI usage events follow §1.2 exactly (≤ 1 per meter per run; usable-result criterion; empty/failed/interrupted ⇒ none); operational counts are separate; `niche_run_count` unchanged; enforcement uses successful counts only.
- **AC-R4** `PLANNED` round-trips, is never coerced to `FAILED`, never metered, and the constant equals the DB constraint.
- **AC-R5** After a mid-leg kill one reconcile pass leaves nothing non-terminal; a second pass changes nothing; external-capable legs read `OUTCOME_UNKNOWN`; nothing is retried or charged; legacy rows untouched; the CLI runs standalone; the threshold setting is validated against the computed floor and refuses when unset.
- **AC-R6** With a cap of 1 and ≥ 8 concurrent attempts, exactly one run proceeds and exactly one event per meter exists; failed/killed winners behave per R6 tests; until this passes, caps stay unseeded and documented as not enforced.
- **AC-R7** An endpoint that is not loopback and not operator-attested is `EXTERNAL` everywhere; EXTERNAL without a configured policy refuses and sends nothing.
- **AC-X** The existing suites (backend 4,5xx tests, frontend 165 tests, lint, `tsc`, build) stay green; CMO and clarification work are untouched; no approval endpoint or plan creation exists.
VP-1 and VP-2 flip to **PASS** only when AC-R2, R3, R5 (and R6 for caps) are demonstrated by these tests.

## 4. Files, migrations and tests per fix
| Fix | Source | Migration | Tests |
|---|---|---|---|
| R0 | `repositories/accounting_cutover_repo.py` (new, read-only), PI `pi_research_run_repo.py` | core `20261011_0017_accounting_cutover.py`; PI `20261011_0002_pi_run_accounting.py` | `tests/integration/test_accounting_cutover.py` (new), `test_privilege_boundary.py` (app role `SELECT` only) |
| R1 | `ceo/effects.py` (new), `ceo/contract.py`, `ceo/registry.py` | — | `tests/unit/test_ceo_effects.py` (new), `tests/integration/test_pi_payload_pins.py` (new) |
| R2 | `ceo/billing.py` (new), `ceo/orchestrator.py`, `repositories/investigation_repo.py`, `api/v1/ceo.py`, `frontend/lib/ceo.ts`, `ceoModel.ts` | — | `tests/unit/test_ceo_unit_decision.py` (new), `tests/integration/test_ceo_unit_billing.py` (new), `frontend/lib/ceoModel.test.ts` |
| R3 | `api/v1/pi.py`, `services/pi_usage.py` (new), `entitlement.py`, `repositories/entitlement_repo.py`, PI `pi_research_run_repo.py` | PI (R0) | `tests/integration/test_pi_usage.py` (new), `test_pi_discover_api.py` (additions), `tests/unit/test_pi_route_permission_entitlement_enforcement.py` (new field) |
| R4 | `ceo/contract.py`, `ceo/orchestrator.py`, `frontend/lib/ceo.ts`, `ExecutionPanel.tsx` | `20261011_0016_turn_status_planned.py` | `tests/integration/test_ceo_turn_status_vocabulary.py` (new), `ceoExecution.test.tsx` |
| R5 | `ceo/reconcile.py` (new), `agent_run_repo.py`, `investigation_repo.py`, `api/v1/ceo.py`, `ceo/orchestrator.py`, `config.py`, `backend/README.md`, PI repo | — | `tests/integration/test_ceo_reconcile.py` (new; child-process fixtures from `docs/planning/ceo-approval-s0/crash_child.py`), `test_ceo_reconcile_cli.py` (new) |
| R6 | `repositories/quota_reservation_repo.py` (new), `services/pi_usage.py`, `api/v1/pi.py`, `entitlement.py`, `config.py` | — | `tests/integration/test_pi_quota_reservation.py` (new; concurrency), CMO reservation tests unchanged |
| R7 | `config.py`, `llm/model.py`, `services/*_runtime.py`/`cfo_actions.py`/`pi_actions.py`, CI composition root | — | `tests/unit/test_llm_endpoint_trust.py` (new), `tests/integration/test_llm_external_refusal.py` (new) |
Scratch experiments X1/X2/X3 become permanent regression tests (X1 → R2, X2 → R5, X3 stays as the reachability check).

## 5. Unresolved facts and blockers (to settle **before** implementation)
| # | Fact / decision | Status | What is needed |
|---|---|---|---|
| **F1 Staleness threshold (Q-R5)** | Structural floors computed from code constants (PI discover ≈ 1,640 s upper bound; supplier lookup ≈ 70–140 s); **no measured durations from a target host; LLM hardware undecided** | **BLOCKER for the final value** (the mechanism and floor validation are designed) | a calibration run of `pi.discover`/`pi.supplier_lookup`/CEO turns on the intended host, and the owner's acceptance of `stale_after = 2 × floor` (or another documented margin) |
| **F2 `OUT_OF_SCOPE` billing documentation (Q-R6)** | The spec states D5 ("one unit per user turn regardless of sub-agent") and Q25 ("B3 meters only DELIVERED turns"); the route table says only "declined and explained"; **no spec sentence or test names `OUT_OF_SCOPE` billing**; the code charges it because it ends `DELIVERED` | **Documentation gap** — design adds the explicit rule + test, but the owner must confirm the existing intent | confirmation that "delivered out-of-scope explanation = one unit" is the intended policy, then add it to `ceo-agent-orchestration.md` §6.3 and `entitlement.md` |
| **F3 Quota reservation strategy (Q-R8)** | Recommended: reuse `cmo_quota_reservation` + `reserve()` for PI/SHARED (generic columns, tested concurrency design); alternatives: new neutral table (rename churn) or advisory lock only (insufficient: runs outlast a transaction) | **Needs owner confirmation** | choose reuse vs new table |
| **F4 Deployment environment (Q-R7)** | Never chosen (readiness review 2.19 `[P]`: AWS/Railway/Render/Cloudflare); no Dockerfile/IaC; `backend/README.md`: "no deployment layer"; Ollama production use undecided (3.9 `[P]`) | **Unconfirmed** — scheduler documentation deferred; only the CLI contract is written | the chosen target (and whether a scheduler exists there) |
| **F5 LLM data-disclosure policy (Q-R9)** | No policy document exists; only the CEO layer enforces local-only today | **Policy undefined** — design fails closed (EXTERNAL ⇒ refuse) | the policy and its configuration (consent/DPA/ack) for any third-party model endpoint |
| **F6 PARTIAL leg usability (Q-R11)** | A leg is `PARTIAL` when its payload carries `dataRequestId`/`partialReason` (CFO asking the seller for an input); it is not failed but may contain no usable figure | **Open** — counts as not failed until decided; recommendation: a required leg that produced no usable result should be NOT_DUE | decide, then pin by test |
| **F7 Business State read UNAVAILABLE (Q-R12)** | A `BUSINESS_STATE` turn whose entry is `UNAVAILABLE` ("not available yet") is `DELIVERED` and charged today | **Open** | decide whether "delivered explanation of missing data" is a unit (like out-of-scope) or not |
| **F8 PI usable-result criteria** | §1.2 predicates (≥ 1 computed candidate; ≥ 1 lead) are proposed by me from code semantics | **Proposed; owner to accept** | confirm or adjust |
| **F9 Cut-over storage** | A durable platform table (R0, new migration) is proposed instead of an env var | **Proposed** | confirm the extra migration |
| **F10 Observed anomaly** | A PI discover writes **two** `agent_run` rows (the route's `RUNNING` row and `_log_agent_run_stub` inside `submit_pi_discover`); counts here use `pi_research_run`, not `agent_run` | **Fact; not changed** | decide separately whether to dedupe |
No implementation starts until F1–F5 are answered or explicitly deferred with the consequences accepted (F1 and F5 are real blockers for enabling reconciliation thresholds and any third-party model endpoint respectively; neither blocks R1, R2, R3, R4 or R0).

## 6. Implementation and verification status (2026-10-10, after merging the pulled `feat/ceo-foundation` head `2b954c9`)

**Scope.** R0–R4, R6, R7 are implemented; **R5 is not** (BLOCKED, below). Nothing for approvals exists: no endpoints, plan creation, execution or editor.

**Migration chain (re-numbered after the merge).** The pulled branch added `20261010_0011..0014` (`agent_memory`, `shared_finding`, `ceo_need`, `agent_memory_append_only`), which collided with the revision ID this work first used. The chain is now: `…0014` → **`20261011_0015_attachment_append_only`** → **`20261011_0016_turn_status_planned`** (R4) → **`20261011_0017_accounting_cutover`** (R0); PI package `20261001_0001` → `20261011_0002_pi_run_accounting`. The approval-workflow migration is `20261011_0018_ceo_approval_workflow` (not written). **Single head `20261011_0017`; no revision duplicated or replaced.** A dev database that had the *old* `20261010_0011` recorded must be checked (read-only) before upgrading: that ID now means `agent_memory`.

**Verified on isolated scratch Postgres (ports 5544/5545; the dev database was not touched).** Fresh upgrade of every package to head; PI `downgrade 20261001_0001` → `upgrade head`; backend `downgrade base` → `upgrade head` (one-shot, single transaction per revision) → `20261011_0017 (head)`; `test_accounting_cutover.py` + `test_ceo_turn_status_vocabulary.py` with `METRION_ALLOW_DOWNGRADE_TESTS=1` (downgrade refuses while `PLANNED` turns / stored billing decisions / PI accounting rows exist, and succeeds once they are gone) and `test_privilege_boundary.py` (app role has no `UPDATE`/`DELETE` on `investigation_attachment`; `SELECT` only on `accounting_cutover`; FORCE RLS holds): 35 passed. The downgrade guards probe on a **separate connection** (a `set_config` inside the migration transaction left `''` and broke `''::uuid` casts in a one-shot `downgrade base`).

**R6 `candidate_cap` finding — resolved.** `POST /pi/discover` previously accepted *any* integer. A cap below 1 defeated the cap (slice semantics kept all-but-the-last YouTube-matched rows) and no worst-case duration exists for it, so the earlier "1,850 s" is a bound for the **default cap of 30 only**, never a maximum. Now: the request model enforces **`1 ≤ candidate_cap ≤ 100`** (`MAX_CANDIDATE_CAP`, 422 outside; omitted ⇒ default 30). This **narrows the public contract** (values `<1` and `>100` were accepted before): it is recorded here as a decision the owner should confirm; 100 is a proposal (it keeps the bound finite and the provider query volume within a small multiple of the default), not a measured provider limit. `timing.discover_worst_case_seconds` is defined for exactly `1..100`, strictly increasing, and refuses `<1`; `_select_candidates_with_cap` keeps nothing for a non-positive cap (defence in depth); a capped meter whose worst case cannot be established refuses (`PI_NOT_CONFIGURED`) rather than trusting a figure. The earlier strict `xfail` is **removed**: it is now a passing test. New/updated tests: `tests/unit/test_pi_timing.py`, `test_candidate_cap_is_bounded_at_the_api_1_to_100` (422 for 0, −1, −100, 101, 1000 with nothing reserved or metered; 1 and 100 accepted). The 8-way overlapping-request test for the last quota unit still passes (exactly one discovery runs; one event per meter).

**Pre-existing test fixed.** `test_gst_lookup_route_succeeds_when_both_permissions_present_cache_hit` seeded a cache row dated 2026-09-26 and the route reads the real clock, so the row aged out of its 14-day TTL on 2026-10-10. The seed now uses the current time; the assertion is unchanged. (Test-only.)

**R5 crash reconciliation — BLOCKED.** No staleness threshold is supported by evidence: the structural bound is a floor derived from code constants (and only for `1 ≤ candidate_cap ≤ 100`), there are no measured durations from a target host (F1), and the deployment environment is undecided (F4). Nothing reconciles or repairs stuck rows.

| | Status | Evidence | Remaining risk |
|---|---|---|---|
| R0 cut-over records | PASS (targeted) | migration `0017` + PI `0002`; round trip; downgrade refusal; app role `SELECT` only | dev DB not migrated |
| R1 effects metadata | PASS (targeted) | `test_ceo_effects.py`, `test_pi_payload_pins.py` | — |
| R2 CEO unit rule | PASS (targeted) | `test_ceo_unit_decision.py`, `test_ceo_unit_billing.py` (incl. kill-after-finalise) | billing change awaits owner sign-off |
| R3 PI usage recording | PASS (targeted) | `test_pi_usage.py` | same |
| R4 `PLANNED` vocabulary | PASS (targeted) | migration `0016`, drift test, frontend renders neutrally | nothing produces `PLANNED` |
| R5 reconciliation | **BLOCKED** | no safe threshold | stuck `RUNNING` rows persist |
| R6 quota reservation | PASS (targeted) | `test_pi_quota_reservation.py` incl. 8-way concurrency; cap bound at the API | `candidate_cap` contract narrowing needs confirmation |
| R7 LLM endpoint guard | PASS (targeted) | `test_llm_endpoint_trust.py`, `test_llm_external_refusal.py` | `LLM_OPERATOR_CONTROLLED_HOSTS` must be set in each environment |

"PASS (targeted)" means the named tests pass on the merged code; it is **not** a claim about the complete backend suite. The last complete backend run (4,675 passed, 1 failed, 7 xfailed) was on the pre-merge tree; a complete re-run on the merged tree takes several hours here and was **not** completed. Section 7 records exactly what was re-run.

## 7. Test evidence on the merged tree (2026-10-10)

All backend runs used isolated scratch Postgres 16 + pgvector containers (ports 5544 and 5545, every package migrated to head `20261011_0017`); the development database was never connected to. All frontend runs used the working tree as it stands.

| Check | Result |
|---|---|
| Backend unit suite (`tests/unit`) | **3,992 passed, 6 xfailed**, 0 failed, 0 skipped (25 s) |
| Merge-affected integration subset (15 files, 139 tests: guided input, turn-status vocabulary, CEO unit billing, accounting cut-over, PI/CMO chat, rival margin, API b4, dispatch, PI discover API, payload pins, external-LLM refusal, safety gate, state cache, UI actions) | first run **135 passed, 1 failed, 2 skipped, 1 xfailed**; the one failure is explained and fixed below; its file then passed **10/10** |
| Skips (2) | `test_ceo_turn_status_vocabulary` and `test_accounting_cutover` downgrade tests: opt-in (`METRION_ALLOW_DOWNGRADE_TESTS=1`); both **passed** when run with it set (35 tests with `test_privilege_boundary.py`) |
| xfail (1) | `test_ceo_safety_gate` strict xfail for the documented quantity-words gap (spec Q13); pre-existing, unrelated |
| `candidate_cap` / quota group (`test_pi_timing`, `test_pi_quota_reservation` incl. 8-way concurrency, `test_pi_usage`, `test_pi_discover_api`) | **26 passed, 0 xfailed** (before the discover-API file was added to the subset above) |
| GST cache-hit test after the date fix | `test_cfo_gst_lookup.py` 7 passed |
| Migration round trips (5545) | PI `downgrade 20261001_0001` → `upgrade head`; backend `downgrade base` → `upgrade head` → `20261011_0017 (head)` |
| Privilege boundary (5545) | pass (app role: no `UPDATE`/`DELETE` on `investigation_attachment`; `SELECT` only on `accounting_cutover`) |
| Frontend `eslint` / `tsc --noEmit` / `next build` | 0 problems / 0 errors / build succeeded |
| Frontend `vitest run` | **198 passed, 0 failed (18 files)** with `--maxWorkers=4`. With the default 12 workers while a backend suite was running, 2–6 different tests timed out at 5 s on each run; every timed-out file passed when rerun alone (23/23) and the full suite passed once the load was reduced, so those were CPU-contention timeouts, not regressions |

**The one integration failure.** `test_back_re_asks_the_previous_question_…` asserted `(1 of 3)` as the first line of the new-product session. The pulled branch (spec 6.36) lengthened that session to **8 questions** (supplier quote and batch budget), and the pulled `test_ceo_guided_input.py` already asserts `(1 of 8)` for the same flow. Cause: a stale expectation in a test written before the merge, not a behavior regression (the BACK option, the dropped answer and the empty `collected` assertions all still hold). The expectation was updated to `(1 of 8)`; no assertion was weakened.

**Not re-run.** The complete backend suite (about 4,700 tests) on the merged tree. The integration tests are slow on this setup (the subset above took 22 minutes; `test_ceo_safety_gate` alone runs 700 turns), so a complete run takes several hours. The unit suite and the merge-affected integration subset above are the verification for the merge; the last complete run (4,675 passed, 1 failed, 7 xfailed) predates it, and its one failure (the GST date fixture) is fixed. A complete run belongs in CI before the approval build starts.

**Billing rules (as implemented; identical in all three documents).** `CEO_UNIT_RULE_2` (spec 6.42): a turn with **any failed required leg** consumes **no** CEO unit, regardless of optional legs; a delivered answer alone is not successful execution; no legs planned and delivered, and a delivered `OUT_OF_SCOPE` explanation, are **1** unit (preserved, now explicit); `CLARIFIED`/`DENIED`/`FAILED`/interrupted turns are **0**. The decision is computed once at finalisation and stored (first writer wins); only the finalising call writes the usage event (`ceo:turn:<id>`, idempotent); a turn created before the cut-over is legacy and is never re-evaluated, charged or refunded. PI usage (`PI_USAGE_1`) is recorded only for a usable result, with the shared `research.niche_run` meter counted from events; a capped PI meter reserves before running and settles or releases afterwards.

**`candidate_cap` documentation.** Bound `1..100` is documented in §6 above and in `product_intelligence/timing.py`, enforced by the request model (`api/v1/pi.py`, 422 outside) and tested (`test_candidate_cap_is_bounded_at_the_api_1_to_100`, `test_pi_timing.py`). The 1,850 s figure is the structural worst case **for the default cap of 30 under the module's listed assumptions** (all calls time out at their configured limits, no retries beyond the stated ones); it is not a measured duration and not a maximum for other caps (the bound grows with the cap and is defined only for 1–100).

## 8. Open items and next gate (pointer)
The S1/S2/S3 matrix, the R5 evidence plan (E1–E5, measurement procedure, margin methodology), the exact remaining CI gate (complete backend suite on the merged tree, **not yet passed**) and the decision register D-1…D-12 are in `ceo-approval-s1-readiness.md`. R5 remains **BLOCKED**. One refinement to R5.2 recorded there: a free investigation lock does not prove a `RUNNING` leg is dead, because late legs outlive the turn (`pool.shutdown(wait=False)` in `ceo/orchestrator.py`); only per-action age evidence can.
