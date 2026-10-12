# CEO approval workflow — S0 findings report (VP-1, VP-2, classification, integrity)

**Date:** 2026-10-10 · **Scope:** verification only. No schema, endpoint, permission, billing or database change was made. All experiments ran on the isolated scratch Postgres (`:5544`); the development database was not touched.
**Spec:** `docs/specs/ceo-approval-workflow.md` (Section 13 carries the condensed decisions; this report carries the evidence).
**Status key:** **CONFIRMED** = observed in code *and* by an experiment or an existing passing test · **CODE-VERIFIED** = read in code, not executed · **ASSUMPTION** = not proven · **UNVERIFIED** = not examined.

## Owner decisions after S0 review (2026-10-10: Q-S0-1…4, then Q-R1…10) and what they changed
| Decision | Effect on these findings |
|---|---|
| **Q-S0-1** Record one idempotent usage event per **successful** `pi.discover` / `pi.supplier_lookup`; failed runs consume nothing; keep accounting unresolved until tests prove it; do not claim PI caps are enforced | VP-1 stays **FAIL** (decision made, remediation designed, nothing implemented). The remediation is R3 in `ceo-approval-remediation-design.md`. Until R3's tests pass, no document may say PI caps are enforced. |
| **Q-S0-2** GST public-page lookups and internal LLM calls do **not** independently require approval; approval is for seller-specific confidential data leaving Metrion or the agreed consequential-action policy; classify actual data flows per action | Resolved. §D now has a per-action **data-flow** column. Evidence added: `pi.discover` sends only the seller-entered **niche category text** (`_queries_for_niche`: `<text>`, `best <text> india`, `<text> review`) to Tavily and YouTube; `pi.supplier_lookup` sends `<candidate title> manufacturer supplier wholesale india`, and candidate titles come from public search results, not seller-entered text; `cmo.market_trends` sends only seller-**confirmed** terms (tested). Both PI actions still need approval because they are metered (after R3). The LLM endpoint is "internal" only while it is operator-controlled (Q-R9). |
| **Q-S0-3** A delivered turn whose required legs all failed must **not** consume a CEO unit; define exact outcomes; idempotent; no double charge in recovery | Resolved in design: R2 and the exact outcome table (remediation design §1.1). X1 stays as the failing regression that R2 must flip. |
| **Q-S0-4** Lazy **and** periodic recovery; separately testable runner, not a loop in the web server; investigation locks + idempotent transitions; `OUTCOME_UNKNOWN` for external-capable operations; never retry | Resolved in design: R5 (module, CLI, liveness proof by lock, guarded transitions, repairs). VP-2 stays **FAIL** until R5 exists and its kill-process tests pass. |
| **Q-R1** Any failed required leg ⇒ no CEO unit, even if an optional leg succeeds; optional results still returned with the failure/partial outcome shown | Stricter than the 2026-10-10 morning design (which charged when *any* required leg succeeded). Design R2/§1.1 updated; experiment X1 stays the regression to flip; a stored `outcome` (`SUCCEEDED`/`PARTIAL`/`FAILED`/`DECLINED`) is added so a `DELIVERED` turn can still be shown as failed. |
| **Q-R2** PI `PARTIAL` is billable only with a valid, usable partial result under a documented criterion; max one idempotent event per run | Evidence (new §J.3): an **empty** run is already `PARTIAL` (`discovery_run.py` sets `partial_reason` when `not rows`), so status alone cannot decide billing. Criterion proposed in the design §1.2 (≥ 1 computed candidate; supplier lookup ≥ 1 lead). |
| **Q-R3** Only successful `research.niche_run` executions count toward usage/entitlement; keep started/failed/interrupted/successful separate; check consumers first | Consumer audit done (§J.2): `niche_run_count` is read only by `api/v1/pi.py` (402 body) and tests; no frontend/doc consumer. Field **not** repurposed; new separate counts and a successful-events count added in design §1.3 / R3. |
| **Q-R4** No refunds/retroactive charges/backfills; explicit cut-over timestamps; reconciler never reinterprets legacy records | Finding (§J.4): `pi_research_run` has **no `created_at`** and no failure marker, so PI runs cannot be dated today ⇒ new R0 (durable cut-over table + PI columns). |
| **Q-R5** Do not invent a staleness threshold; derive it; validated config, no default; report a blocker if evidence is insufficient | **Blocker reported** (§J.5): structural bounds computed from code; no measured durations from a target host. |
| **Q-R6** Preserve `OUT_OF_SCOPE` billing if documented and delivered; keep distinct from failed execution | **Documentation gap reported** (§J.1): behaviour exists, no spec sentence/test names it. Design makes it an explicit rule with outcome `DECLINED`. |
| **Q-R7** Reconciler = standalone one-shot CLI; no scheduler in FastAPI; scheduler docs only after the environment is confirmed | Environment **unconfirmed** (§J.6); only the CLI contract will be documented. |
| **Q-R8** No quota overshoot once PI caps are enabled; atomic reservation first; concurrent-last-unit test; until then caps not enforced | Reservation machinery found and reusable (§J.7); R6 designed; PI caps are **not enforced** and must not be seeded until R6's tests pass. |
| **Q-R9** Guard that the LLM endpoint is operator-controlled; if unverifiable, external + disclosure policy | Only the CEO layer enforces local-only today (§J.8); R7 designed; the disclosure **policy itself is undefined**. |
| **Q-R10** Classify `pi.supplier_lookup` payload as public candidate titles + fixed suffix; approval because metered; reclassify if the payload changes | Pin tests specified in design R1. |

## Verdicts

| Item | Verdict | One-line reason |
|---|---|---|
| **VP-1 Metering** | **FAIL (decision made, remediation designed, not implemented)** | CMO and CEO-turn metering behave as designed and are test-proven. `pi.discover` / `pi.supplier_lookup` (declared `GENERATE_METERED`) write **no** `metered_event` at all; CFO/CI/GST usage is never recorded either. Plus one semantic risk: a CEO unit is consumed when a required leg failed. |
| **VP-2 Crash recovery** | **FAIL (confirmed: no recovery exists)** | A hard crash leaves the turn, the CEO anchor run and the leg run non-terminal forever; nothing reconciles them. A safe design is proposed (§C); none of it is built. |
| Reachability today | **CONFIRMED** | No `GENERATE_METERED` or external-sending action is reachable from CEO chat today. The approval gate has **no currently reachable consumer**; it is protective infrastructure for actions that will be wired. This lowers urgency, not the need to get it right first. |

---

## A. Metering audit (VP-1)

### A.1 Method
Read every metering write path (`record_metered_event` / `entitlement_repo.insert_metered_event` callers across `backend/src` and `packages/*/src`); read each action's entitlement preflight and success/failure handling; ran a **spy plugin** on the scratch DB that records every metered-event write per test (a positive control proved it fires), over the CFO, CI, GST and PI direct-path suites (68 tests) and over CEO/CMO tests; ran new crash/failure experiments (§B).

### A.2 Where usage is recorded (CONFIRMED by code search and the spy)
`metered_event` rows are written by exactly **three** code paths:
1. `entitlement.meter_ceo_turn` — the CEO conversation unit (`orchestrator._finish`, only when the turn status is `DELIVERED`; best-effort; idempotency key `ceo:turn:<turn_id>`).
2. `services/cmo_actions._settle` — one event per **persisted-COMPLETE** CMO artefact; key `cmo:<generation_id>`.
3. `services/cmo_trends._settle` — one event per meter (CMO + shared market-trends) for a COMPLETE report.

**No other agent writes usage.** Spy result over `test_cfo_pnl`, `test_cfo_cash_reconciliation`, `test_cfo_anomaly_check_narration`, `test_cfo_gst_lookup`, `test_cfo_strategic_briefing`, `test_cfo_funding_readiness_cash_conversion_timing`, `test_ci_api`, `test_ci_discovery_api`, `test_ci_price_scenario_api`, `test_pi_discover_api`: **68 passed, zero metered-event writes attempted.** Positive control (same spy): the CEO metering test logged 3 calls (idempotent), CMO tests logged their COMPLETE artefacts.

### A.3 Per-action usage path
| Action(s) | Usage recorded where | On success | On failure / interruption | On retry | Status |
|---|---|---|---|---|---|
| CEO turn | `metered_event` `ceo.chat_turn` qty 1 | when turn ends `DELIVERED` (best-effort) | `CLARIFIED`/`DENIED`/`FAILED` turns: none. **A `DELIVERED` turn whose required leg FAILED still consumes the unit** (X1: legs `financial_health` FAILED, `anomaly_check`/`briefing` COMPLETE, anchor PARTIAL, `metered_event = [(CEO, ceo.chat_turn, 1)]`). Hard crash: none (X2). | a re-sent message is a new turn (no idempotency key on `POST …/turns`) ⇒ a new unit | CONFIRMED |
| `cmo.generate_*`, `cmo.catalog_answer`, `cmo.generate_title_sets` | CMO artefact events + `cmo_quota_reservation` | one event per COMPLETE artefact | FAILED artefact persisted free (`test_a_failed_artefact_is_persisted_free…`); unexpected exception: reservation RELEASED, nothing charged (`…generic_500_releases_the_reservation_and_charges_nothing`); **metering write failure: delivery not blocked, quota stays held (reservation RESERVED), reconciled on replay** (`test_a_failed_metering_write_never_blocks_delivery…`) | same `request_key` ⇒ result reused, **no new run, no double count** (`test_same_request_key_replay_reuses…`) | CONFIRMED (tests; all passed in the 2026-10-09 full run) |
| `cmo.market_trends` | CMO + shared `research.market_trends` events | one event per meter for a COMPLETE report; a **degraded** report is still one unit per meter (`test_a_degraded_report_is_still_one_unit…`) | FAILED report free, reservations released (`test_a_failed_report_is_free_audited…`); model down ⇒ FAILED, no charge | same key replays free; same key + different plan ⇒ 409 | CONFIRMED |
| `pi.discover`, `pi.supplier_lookup` | **none** | no `metered_event`; usage proxy `niche_run` = **all-time row count** of `pi_research_run` (every status, incl. FAILED/QUEUED/RUNNING) via `resolve_niche_run_entitlement` — an always-pass scaffold | FAILED run rows exist and are counted; external Tavily/YouTube/Places calls may already have happened | a retry is a brand-new run + new external calls (no idempotency) | CONFIRMED (code + spy) — **GAP** |
| `cfo.*` computations, `cfo.preview` | **none** | `_require_cfo_entitlement` reads caps against `metered_event`, which CFO never writes ⇒ **a seeded CFO cap could never bind** | n/a (no usage) | recompute persists another derived result | CONFIRMED (spy) — latent gap |
| `ci.request_price_scenario`, `ci.discover_competitors` | **none**; `resolve_ci_entitlement` is an always-pass scaffold reporting live `active_competitor_urls` | — | — | each call persists a new run | CONFIRMED |
| GST lookup (`cfo.gst_lookup`, `service.gst_lookup`) | **none**; `resolve_gst_lookup_entitlement` always passes, reports `gst_lookup_result` count | result persisted ⇒ counted | no-match persists nothing | 14-day cache ⇒ repeat is a cache hit with **no fetch and no LLM call** | CONFIRMED/CODE-VERIFIED |
| `*.RECORD_CHOICE`, `READ` | none by design | — | — | — | CODE-VERIFIED |

**Entitlement reality (CONFIRMED in `entitlement.py` docstring + code):** no `entitlement_cap_config` rows are seeded, so every entitlement check passes today (`NO_CAP_CONFIGURED`). Billing semantics therefore have **no financial effect yet**; the issue is that the *mechanism* is incomplete for PI/CFO/CI/GST — it would not bind once caps exist.

### A.4 Can an external operation succeed while Metrion records a failure? — **Yes** (CONFIRMED by design/tests)
- `cmo.market_trends`: retrieval (Tavily/YouTube) precedes the model summarisation (`trends/findings.py` consumes retrieved items). Model failure ⇒ FAILED, free — the provider calls already happened (`test_the_model_being_down_fails_the_report_without_charging`).
- `pi.discover`: Tavily/YouTube calls run before later steps; an exception afterwards sets the run `FAILED` (the 2026-10-01 safety net in `submit_pi_discover`) while the external quota is already spent.
- Hard crash after a send: the leg stays `RUNNING` (X2) — the record says nothing either way.
- The reverse also occurs: a CEO unit is charged for a `DELIVERED` turn whose required leg failed (X1); a degraded CMO report charges a full unit.

### A.5 Retried paths
CEO turn: new turn each time (no idempotency). CMO: idempotent by `request_key`. PI/CI discovery/CFO: no idempotency, a retry re-runs and re-spends. GST: cached 14 days. **Approval must therefore be idempotent at the plan level (CAS) and must pass deterministic, plan-derived idempotency keys to any metered leg** (e.g. CMO `request_key = f(plan_id, leg)`), so a duplicated dispatch cannot double-charge.

### A.6 Decisions taken (2026-10-10) — still no billing change made
1. **PI (Q-S0-1, decided):** record **one idempotent usage event per successful** `pi.discover` or `pi.supplier_lookup` (status `COMPLETE`, or `PARTIAL` with a usable result per the documented criterion — Q-R2; empty/failed/interrupted runs are never billable); failed runs and interrupted runs record nothing. Accounting remains **unresolved** until the implementation (R3) and its tests prove it; no document may claim PI usage caps are enforced before then (there is also no reservation, so concurrent runs could overshoot a seeded cap — Q-R8).
2. **CEO unit (Q-S0-3, decided):** a `DELIVERED` turn whose required legs all failed consumes **no** CEO unit. Exact outcomes for full success, partial success, failure and interruption, the persisted billing snapshot, and the no-double-charge rule are in `ceo-approval-remediation-design.md` §1.1 and R2.
3. Until R3 is merged and proven, a future plan must still show PI meters as **"usage not recorded"** rather than invent a unit count.

---

## B. Crash-recovery audit (VP-2)

### B.1 Experiment X2 (scratch DB, real orchestrator/dispatch, real Postgres)
A child process runs a real CEO turn; the first leg calls `os._exit(137)`. Observed afterwards:
| Row | State | Terminal? |
|---|---|---|
| `investigation_turn` | `PLAN_VALIDATED`, `completed_at IS NULL` | **No** |
| `agent_run` CEO anchor (`ceo.chat_turn`) | `RUNNING`, `finished_at IS NULL` | **No** |
| `agent_run` leg (`cfo.financial_health`) | `RUNNING`, `finished_at IS NULL` | **No** |
| `investigation_message` | one `USER/TEXT`; **no CEO answer** | orphaned question |
| `metered_event` | none | — |
| advisory lock | free (new `investigation_turn_lock` acquired at once) | OK (session lock dies with the process) |
| next turn in the same investigation | `DELIVERED` normally | OK |
| after the next turn | the crashed turn and both runs are **still `RUNNING`** | **No reconciliation exists** |
Search of `repositories/`, `ceo/`, `services/`, `main.py` found no sweeper/reaper/startup repair (CONFIRMED).

### B.2 Every state that can remain stuck
| # | Object | Stuck state | How it arises | Safe to recover? |
|---|---|---|---|---|
| 1 | `investigation_turn` | `PLAN_VALIDATED` (also `RECEIVED`/`CAP_CHECKED`/`CLASSIFIED`/`DISPATCHED`/`GATHERED`/`COMPOSED` in principle) | process kill before `_finish`/`update_turn` | **Yes** — mark `FAILED` (`completed_at` = reconciliation time); no external effect is implied by the turn row alone |
| 2 | CEO anchor `agent_run` | `RUNNING` | same | **Yes** — finish `FAILED`/`INTERRUPTED` |
| 3 | Leg `agent_run` (internal compute: CFO, CI scenario, PI report) | `RUNNING` | kill mid-leg | **Yes** — result is derived/recomputable; mark `FAILED`/`INTERRUPTED`; a *new, newly approved* plan may recompute |
| 4 | Leg `agent_run` (**external-capable**: PI discover/supplier, CMO trends, GST fetch, future CI provider) | `RUNNING` | kill mid-leg | **Outcome unknown** — a request may or may not have left the system; mark `FAILED` with `OUTCOME_UNKNOWN`; **never retry automatically** |
| 5 | Orphaned `USER` message with no `CEO` answer | — | kill after the message is written | Yes — append a code-authored `SYSTEM_NOTE` "this request was interrupted"; do not delete history |
| 6 | `pi_research_run` | `QUEUED`/`RUNNING` | kill during `submit_pi_discover` (the safety net only catches exceptions) | Mark `FAILED` `INTERRUPTED`; `OUTCOME_UNKNOWN` for external parts. (`has_active_run` exists but is **not called anywhere in `src`** — no edit-lock effect; CODE-VERIFIED.) |
| 7 | CMO reservation | `RESERVED` after crash | kill between artefact persist and settle | **Self-healing already:** it holds quota only until its TTL (`cmo_quota_repo`), and a same-`request_key` replay re-asserts settlement idempotently (tested) |
| 8 | CEO unit | `DELIVERED` turn with no `metered_event` | kill (or write failure) between `update_turn` and `meter_ceo_turn` | **Yes, safe and idempotent** — repair by `meter_ceo_turn(turn_id)` (key `ceo:turn:<id>`); this is a repair, not a retry |
| 9 | **Late leg** (leg outlives its leg timeout; the turn already `DELIVERED`) | leg `RUNNING` then completes later | by design (E36; `test_a_slow_optional_leg…`) | Not a crash; staleness for reconciliation must be measured from the leg's own `started_at` > timeout + margin, never from the turn |
| 10 | Plan (future) | `APPROVED` with execution turn non-terminal | kill after the approve transaction | per §C |

### C. Proposed recovery behaviour (cannot duplicate external side effects or charges)
1. **Reconciler** (lazy on investigation read / approve / next turn; optional periodic task): select non-terminal turns/runs older than `ceo_leg_timeout_seconds` + margin **whose owning process cannot be alive** — determined by the turn lock: if `pg_try_advisory_lock(investigation)` succeeds, no live turn holds the investigation, so any non-terminal turn there is dead. This is the key correctness mechanism: **liveness is proven by the lock, not guessed from time alone.**
2. Reconcile each stuck row per §B.2: internal ⇒ `FAILED/INTERRUPTED`; external-capable ⇒ `FAILED` + `error_reason='OUTCOME_UNKNOWN'`; turn ⇒ `FAILED` + `safety_result.outcome_uncertain=true`; append a `SYSTEM_NOTE`; write the plan events (`EXECUTION_NOT_STARTED` when no leg rows exist, otherwise `OUTCOME_UNKNOWN`/`EXECUTION_FAILED`).
3. **No automatic retry, ever,** for anything with unknown outcome. The only continuation is the seller's new request → new plan (carrying a `prior_attempt` duplicate warning) → new approval.
4. **No usage charge for an uncertain outcome.** Reconciliation never writes a metered event for a leg; CEO-unit repair (row 8) applies only to a `DELIVERED` turn.
5. **Idempotency:** plan-level CAS (`UPDATE … WHERE status='AWAITING_APPROVAL'`) for approve; plan-derived idempotency keys passed to metered legs (CMO `request_key`); reconciliation itself is idempotent (it only moves non-terminal rows to terminal ones, guarded by the status predicate).
6. **Locking:** the existing per-investigation advisory lock for approve/execution/reconciliation; the CAS for plan transitions; no new lock type needed.
7. **Fail closed:** if `ceo_leg_timeout_seconds` is unset the reconciler cannot bound staleness ⇒ approval stays disabled (it currently returns `None` when unset).
Note: this reconciler is *useful independently of approval* — today's crashed turns stay `RUNNING` forever (X2).

---

## D. External-effect inventory (all 36 registered actions)

Tiers: **NONE** internal only · **MODEL** calls the configured LLM endpoint (`OLLAMA_HOST`, local by default; the endpoint is configurable) · **PUBLIC_FETCH** fetches fixed allowlisted public pages, no seller data in the request · **SELLER_DATA_OUT** sends seller-derived terms to third-party APIs · **MUTATES** writes persisted rows. "Chat" = reachable from a CEO turn today (member of `plans.ACTIONS` or a playbook leg; X3 proved the rest are refused `OUT_OF_CATALOG` with no leg dispatched).
| Action | Declared effect | Evidence-based real behaviour | Metered? | Chat? | Understated? |
|---|---|---|---|---|---|
| `cfo.pnl_for_tenant`, `gst_summary`, `landed_cost`, `supplier_ranking`, `funding_readiness`, `batch_size` | COMPUTE_PERSIST | NONE + MUTATES (derived results) | no | playbook legs / no | no |
| `cfo.pricing` | COMPUTE_PERSIST | NONE + MUTATES | no | playbook leg | no |
| `cfo.period_comparison` | COMPUTE_PERSIST | **MODEL** (Ollama narration, `cfo.py:1160`) + MUTATES | no | no | **yes (model call)** |
| `cfo.reconcile`, `cfo.cash_reconciliation` | COMPUTE_PERSIST | NONE + MUTATES (`reconcile` persists `leak_finding`; neither request model has a narration option) | no | yes | no |
| `cfo.anomaly_check` | COMPUTE_PERSIST | MUTATES; **MODEL only if** `include_narration` (CEO slot pins it `False`) | no | yes | pinned off |
| `cfo.financial_health`, `cfo.strategic_briefing`, `cfo.preview` | READ | NONE (`briefing` pinned `include_narration=False`) | no | yes / yes / no | no |
| `cfo.gst_lookup`, `service.gst_lookup` | COMPUTE_PERSIST | **PUBLIC_FETCH** (`HttpxGstFetcher.fetch` of URLs from `known_pages.py`, host allowlist) + **MODEL** (extraction; product title + page text to the LLM endpoint) + MUTATES (`gst_lookup_result`, 14-day cache) | no usage recorded | yes | **yes (network + model)** |
| `pi.discover` | GENERATE_METERED | **SELLER_DATA_OUT** (Tavily, YouTube; real clients in `pi_actions`) + MODEL (extraction/embeddings) + MUTATES | **no** (gap A.3) | no | no (declared metered; not recorded) |
| `pi.supplier_lookup` | GENERATE_METERED | **SELLER_DATA_OUT** (Google Places, Tavily) + MUTATES | **no** | no | same |
| `pi.report` | READ | NONE (re-renders persisted data) | no | yes | no |
| `ci.request_price_scenario` | COMPUTE_PERSIST | NONE (`compute_price_scenario` over stored captures, engine-computed) + MUTATES | no | yes | no |
| **`ci.discover_competitors`** | COMPUTE_PERSIST | **Today: NONE external.** The composition root is `MockSearchProvider` (`ci_actions.run_discovery`; no `httpx`/Ollama import in `discovery_run.py`) + MUTATES (runs, search cache). **By design it is the seam for a future real `SearchProvider`** (C22: no provider approved yet) ⇒ will become SELLER_DATA_OUT the moment one is wired | no | no | **Declared effect is accurate today; it will understate once a provider is wired** |
| `ci.research_now` | COMPUTE_PERSIST | not wired (`not_wired_reason`) | — | no | n/a |
| `cmo.generate_title_sets/listing_copy/description/bullets/keywords/backend_terms/hashtags`, `cmo.catalog_answer` | GENERATE_METERED | **MODEL** (CMO provider) + MUTATES (`cmo_generation`) | yes, on COMPLETE | no | no |
| `cmo.market_trends` | GENERATE_METERED | **SELLER_DATA_OUT** (confirmed niche terms to Tavily/YouTube) + MODEL + MUTATES | yes, on COMPLETE (two meters) | no | no |
| `cmo.market_trends_preview` | READ | NONE (shows the exact outbound queries, sends nothing) | no | no | no |
| `cmo.suggest_niche_terms` | READ | NONE (deterministic catalog-title suggestions) | no | no | no |
| `cmo.approve_title`, `confirm_niche_terms`, `confirm_image_hint` | RECORD_CHOICE | MUTATES (the seller's own explicit choice) | free | no | no |
**Summary:** declared `effect` understates real behaviour in three ways — (1) external network use under `COMPUTE_PERSIST` (`cfo.gst_lookup`, and potentially `ci.discover_competitors` once wired), (2) LLM calls under `COMPUTE_PERSIST` (`cfo.period_comparison`, GST), (3) `GENERATE_METERED` PI actions that are not actually metered. Hence the approval rule must key on an explicit **`external` tier** and a **`meters_declared`** list, not on `effect`.
**Registry fields (decided direction, designed in R1):** `meters`, `external: NONE | MODEL | PUBLIC_FETCH | SELLER_DATA_OUT`, `egress` (which seller data classes leave Metrion), `destinations` (plan-card labels) and a derived `requires_approval` = `bool(meters) or external == SELLER_DATA_OUT`. **Q-S0-2 (decided):** `PUBLIC_FETCH` (GST) and `MODEL` do **not** independently require approval; the LLM tier assumes an operator-controlled endpoint (Q-R9). **Actual data flows:** `pi.discover` sends the seller-entered niche category text (three query variants) to Tavily/YouTube; `pi.supplier_lookup` sends public candidate titles plus a fixed suffix to Google Places/Tavily (not seller-entered text); `cmo.market_trends` sends only seller-confirmed terms; GST sends no seller data in its HTTP requests; CI discovery sends nothing today.
Guard test (necessary, in R1): pin `ci_actions.run_discovery`'s provider type so wiring a real provider forces a registry change in review.

---

## E. Approval-state and audit integrity

### E.1 Where `PLANNED` must be represented (verified against code)
| Layer | Location | Required change | Hazard if missed |
|---|---|---|---|
| DB | `investigation_turn_status_check` (0006) | add `PLANNED` (DROP/ADD constraint) | insert fails |
| DB | `investigation_turn_route_source_check` | add `APPROVAL` | execution turn insert fails |
| DB | `investigation_message_kind_check` | add `PLAN` | plan message insert fails |
| Orchestrator | `orchestrator.py:271` whitelist `("DELIVERED","CLARIFIED","DENIED","FAILED") else "FAILED"` | add `PLANNED` | **a planned turn is silently stored as `FAILED`** (correctness blocker) |
| Orchestrator | `_finish` (`status == "DELIVERED"` ⇒ meter) | no change | `PLANNED` is correctly *not* metered |
| API | `api/v1/ceo.py` turn dict, no `response_model`/Literal | add `plan` object | none structural (open dict) |
| Context | `_turn_context` (classifier) and `summary._due_messages` exclude only `SYSTEM_NOTE` | **also exclude `PLAN`** (and keep approval notes as `SYSTEM_NOTE`) | plan text containing seller strings would re-enter the classifier prompt and the rolling summary |
| Guided input | `orchestrator.py:211` treats typed text as an answer only when the last CEO message has `choices.kind == "INPUT"` | none — a `PLAN` message has no `choices`, so typed "yes" is **not** parsed as a clarification reply (CODE-VERIFIED) | — |
| Frontend | `TurnStatus` (`ceo.ts:167`), `MessageKind` (`:29`), `route_source` unions, `ExecutionPanel` (`TURN_STATUS_VIEW`/`executionStatusOf`), `ceoModel.messageView` (unknown kind renders as a plain CEO bubble) | add types, plan card, panel states | plan shown as ordinary chat text with no approve control |
| Flow view | `agent-flow-visualization.md` D3 node states | add planned state | cosmetic |

### E.2 Database enforcement assessment
- **Narrow app privileges (necessary):** CONFIRMED mechanism — default privileges grant full CRUD (`02-roles.sql`), so explicit `REVOKE` then column-level `GRANT UPDATE (status, execution_turn_id, decided_by, decided_at, decision_reason)`; events `SELECT, INSERT` only. `has_table_privilege` does not see column grants ⇒ tests must use `has_column_privilege`.
- **Tenant isolation:** `FORCE` RLS + `tenant_isolation` policy as every CEO table. **Finding:** FK checks bypass RLS, so a plain `plan_id` FK in the events table would let a bug insert an event for another tenant's plan id (repositories mitigate with `_require_visible`). **Recommend a composite FK `(tenant_id, plan_id) → investigation_plan(tenant_id, id)`** (add `UNIQUE (tenant_id, id)` on plan) — closes it in the DB. (Hardening; recommended, not strictly necessary.)
- **Append-only events:** privilege-level (no `UPDATE`/`DELETE`) — enforced by the DB, tested by direct SQL as `metrion_app` (pattern: `test_privilege_boundary.py`).
- **Transition completeness (no status change without an event):** not enforceable by privileges alone. Options: (1) single transactional repository function + test (necessary, minimum); (2) revoke `UPDATE` on `investigation_plan` entirely and expose one `SECURITY DEFINER` function `transition_plan(...)` that does CAS + event atomically and reads the tenant from the existing `app.current_tenant_id` setting (so RLS still binds) — strongest, optional hardening; (3) a deferred constraint trigger verifying a matching event exists in the same transaction. **Recommendation:** (1) now; evaluate (2) at S2 review (Q-A10).
- **Immutable `plan`/`plan_hash`/`requested_by`/`expires_at`:** by column grants (no `UPDATE` on them).

### E.3 Approval rules re-checked against the code
| Rule | Verification |
|---|---|
| **Requester-only** | `AuthContext.app_user_id` is available (`ctx_for`, `require_auth`); `plan.requested_by` stored; comparison is a pure equality check; roles (incl. OWNER, `has_permission` bypass) are irrelevant to it ⇒ enforceable. A removed member fails `require_auth` step on membership. CODE-VERIFIED. |
| **30-minute expiry** | Use one time source: `runtime.clock()` (tests use a deterministic clock) for both `created_at`/`expires_at` and the check; the DB column default `now()` must not be the authority (skew). Expiry blocks *starting* execution only. |
| **Immutable hash binding** | Canonical JSON with integer paise only (the repo has a no-float lint culture; `Fraction` is used to avoid float literals) ⇒ hash input contains no floats. Constant-time compare (`hmac.compare_digest`). |
| **Revalidation** | Reusable existing pieces: `registry.required_permissions` + `has_permission`; attachment check (`investigation_repo.attached_agents`, `dispatch` R13); entitlements via `open_turn`/`resolve_ceo_entitlement` and `spec.entitlement`; slot validation `_validate_slots`; limits `ceo_playbook_max_legs`, `ceo_leg_timeout_seconds` (both `None` when unset ⇒ fail closed). `data_basis` fingerprints: `business_state`/`state_cache` already fingerprint source tables (reuse). |
| **Plan/approval messages are not instructions** | (a) `PLAN` excluded from classifier context and summary; approval note is `SYSTEM_NOTE` (already excluded); (b) the classifier has no approve route and receives no plan state; (c) plan card text is code-rendered and escaped; seller strings are data; (d) the composer's `PLANNED` reply is a fixed template. A prompt-injection attempt in a SKU name therefore cannot reach any path that changes plan state (the only approving path is `POST …/approve` by the requester). |

---

## F. Ordered remediation plan

> **Updated 2026-10-10.** The prerequisite fixes below (N1, N2, N3, N4, N7-part) are now designed in detail as **R1–R5** in `docs/planning/ceo-approval-remediation-design.md` (billing outcomes, failure-injection tests, files, migrations, ordering). Migration numbering (revision 2): **`20261011_0016_turn_status_planned`** (R4) then **`20261011_0017_accounting_cutover`** (R0, plus a PI-package migration `20261011_0002_pi_run_accounting`); the approval tables and the `route_source`/message-kind extensions move to **`20261011_0018_ceo_approval_workflow`**. The design also now covers R6 (PI quota reservation) and R7 (LLM endpoint guard). Where this section and the design disagree, the design wins.

### Necessary fixes (before or as part of the approval build)
| # | Fix | Why | Blocking? |
|---|---|---|---|
| N1 | **Owner decision on PI metering** (record per successful run, or declare unmetered) and, if recorded, a documented billing change with tests | VP-1 gap; the plan must state real meters | Blocks gating **PI** actions; not S1–S3 for the reachable set |
| N2 | **Crash reconciler** per §C (lock-proven liveness; `OUTCOME_UNKNOWN`; CEO-unit repair) with tests incl. a kill-the-process test | VP-2; also fixes today's permanently-`RUNNING` rows | Blocks S5 and enabling approval |
| N3 | Fix the `orchestrator.py:271` status whitelist; add `PLANNED` end-to-end | silent mis-store as `FAILED` | S3 |
| N4 | Registry fields `external` / `meters` / `requires_approval` per action + enumeration test + provider-pin guard test | declared `effect` understates behaviour | S1 |
| N5 | Migration 0018 with explicit `REVOKE`s, column-level `UPDATE`, append-only events, CHECK extensions, safe downgrade | enforcement | S2 |
| N6 | Plan-derived idempotency keys for metered legs; approve CAS | no double charge on duplicate dispatch | S4 |
| N7 | Exclude `PLAN` from classifier context and summary | injection/leak path | S3 |
| N8 | Config gate: approval enabled only when `ceo_leg_timeout_seconds`, `ceo_playbook_max_legs` (+ TTL) are set; flagged actions refused, never run unapproved, when disabled | fail closed | S4 |

### Optional improvements
O1 composite `(tenant_id, plan_id)` FK; O2 `SECURITY DEFINER` transition function / constraint trigger (Q-A10); O3 consume the CEO unit for an approved execution only if ≥ 1 leg COMPLETE/PARTIAL; O4 record usage for CFO/CI/GST so future caps can bind; O5 either call `has_active_run` or remove it; O6 unify out-of-catalog turn status (`DENIED` for UI actions vs `CLARIFIED` for classifier decisions, X3 vs `test_a_write_class_request…`); O7 idempotency key on `POST …/turns`; O8 periodic reconciler job in addition to lazy.

## G. Files, migrations and tests likely to change next (S1–S3 checkpoint)
**Backend source:** `ceo/contract.py` (ActionSpec fields), `ceo/registry.py` (per-action values), `ceo/orchestrator.py` (status whitelist, planning stage, `_turn_context` filter), `ceo/summary.py` (kind filter), new `ceo/approval.py` (plan build, canonical hash), `repositories/investigation_repo.py` (+ plan/event functions), `api/v1/ceo.py` (S4), `config.py` + `.env.example` (S4).
**Migration (S2):** `backend/migrations/versions/20261011_0016_ceo_approval_workflow.py` (+ `migrations/README.md` note).
**Tests (new/extended):** `tests/unit/test_ceo_registry_flags.py` (new: enumeration, provider-pin guard), `tests/integration/test_ceo_approval_schema.py` (new: constraints, RLS, privileges, append-only, downgrade guard), `tests/integration/test_privilege_boundary.py` (column privileges), `tests/integration/test_ceo_foundation_rls.py` (plan tables), `tests/integration/test_ceo_turn.py` (`PLANNED` finalisation, whitelist), `tests/integration/test_ceo_planning.py` (new, S3), later `test_ceo_approval_api.py` and `test_ceo_reconciler.py` (S4/S5), composer eval fixtures under `ceo_eval/fixtures`.
**Frontend (S6):** `lib/ceo.ts`, `lib/ceoModel.ts`, `components/ceo/hub/ExecutionPanel.tsx`, new `PlanCard.tsx`, `Conversation.tsx`, tests.
**Docs:** `ceo-agent-orchestration.md` (§5, §6.32, Q12, C21), `agent-flow-visualization.md` D3, `ceo-build-status.md`.

## H. Reproducing the experiments (scratch DB only)
Scripts are in `docs/planning/ceo-approval-s0/` (`test_s0_experiments.py`, `crash_child.py`, `meter_spy.py`, `README.md`). They refuse to run unless both DB URLs point at port 5544. Not part of the product test suite.

## I. Not verified / assumptions
- Real provider-side billing for Tavily/YouTube/Places/LLM endpoints (not Metrion's meters) — UNVERIFIED.
- Whether PI/CFO caps are *intended* to be seeded, and what the PI meter code should be — owner decision.
- Multi-worker behaviour of the reconciler and of `event_bus` — ASSUMPTION (the lock is cross-worker; the bus is per-process).
- PI outbound query text: CODE-VERIFIED (`_queries_for_niche` sends only `category_text` variants; `_supplier_query` sends a public candidate title + fixed suffix); CMO is stated by its spec C15 and tested. Payload pin tests are specified in the remediation design (R1).
- Production database state — not examined; the dev database was not touched.

## J. Evidence added after the Q-R decisions (2026-10-10; read-only inspection, no experiments needed)

### J.1 `OUT_OF_SCOPE` billing — documentation evidence (Q-R6)
- `ceo-agent-orchestration.md` route table: `OUT_OF_SCOPE` = "declined and explained"; its third column is the `route_key` (none), not billing.
- D5: "one `agent_run` per **user** turn, regardless of whether a sub-agent was invoked". Q25 (open): "B3 meters only `DELIVERED` turns (D5: 'a delivered answer')" — raised for `CLARIFIED` turns.
- Code: `orchestrator.py` returns `_finish(status="DELIVERED", …)` for `OUT_OF_SCOPE`, and `_finish` meters `DELIVERED` ⇒ one unit.
- Tests: **none** assert `OUT_OF_SCOPE` metering (searched `backend/tests`).
- **Verdict: UNDOCUMENTED as an explicit policy.** It follows from D5 + "delivered answer", and the response is genuinely delivered, but no sentence or test names it. Needs the owner to confirm intent; the design adds the rule and a test (outcome `DECLINED`).

### J.2 `niche_run` consumer audit (Q-R3)
`NicheRunEntitlementResult.niche_run_count`: constructed in `entitlement.py`; read in `api/v1/pi.py` (`_require_niche_run_entitlement` → the 402 body key `nicheRunCount`); constructed in `tests/unit/test_pi_route_permission_entitlement_enforcement.py`. `pi_research_run_repo.count_runs_for_tenant`: read only by `entitlement.py`. **No frontend, package or document consumes either.** ⇒ Safe to add new fields; repurposing is avoidable, so it is avoided.

### J.3 What a PI `PARTIAL` run actually is (Q-R2)
`discovery_run.py` marks a run `PARTIAL` when a source was degraded **or `not rows`** (no candidates). `submit_pi_discover` then sets `PARTIAL` if any partial reason exists (degraded review-commentary or embeddings) else `COMPLETE`. Therefore `PARTIAL` ranges from "complete result with one degraded source" to "empty result", and `COMPLETE` is not proof of a non-empty result either. `PiRunResult` carries `candidate_ids` and `shortlisted_candidate_ids`; the run's own shortlist predicate is `proxy_state == 'COMPUTED' and proxy_score is not null`. Supplier lookup returns per-candidate `lead_ids` and `degraded_reason`.

### J.4 `pi_research_run` shape (Q-R4)
Columns: `id, tenant_id, niche_brief_id, depth, trigger, candidate_cap, status, started_at, finished_at`. **No `created_at`** (`started_at` is NULL while `QUEUED`), **no failure/interruption reason, no outcome code.** Consequences: a `QUEUED` run that never started cannot be aged; interrupted vs failed cannot be told apart; a run cannot be classified as before/after a cut-over. The design therefore adds nullable `created_at`, `outcome_code`, `usage_due` (legacy rows stay NULL ⇒ legacy) in a PI-package migration, plus a durable core `accounting_cutover` table. Also: `submit_pi_discover` logs its own `agent_run` (`_log_agent_run_stub`) **and** the route inserts one ⇒ two `agent_run` rows per discover (observed; counts use `pi_research_run`).

### J.5 Durations and timeouts (Q-R5) — structural evidence, **not measurements**
| Item | Value (source) |
|---|---|
| Tavily / YouTube / Google Places / GST fetch | 10 s each (`market_signals`, `supplier/google_places_client.py`, `gst_lookup/fetcher.py`) |
| PI product-extraction LLM, review-insight LLM | 90 s each (`product_extraction.py`, `text_extraction.py`) |
| PI embeddings | 30 s per request (`embedding/embed.py`) |
| CMO LLM | `CMO_LLM_TIMEOUT_SECONDS=120` (dev `.env`) |
| CEO LLM / leg | `CEO_LLM_TIMEOUT_SECONDS` required, no default, not set in dev `.env`; `CEO_LEG_TIMEOUT_SECONDS` optional, unset; an in-repo comment says a CPU host measured 15–200 s per model call |
| PI concurrency / sizes | 5 workers per pool; `_SHORTLIST_SIZE = 15`; ≤ 3 queries × 10 results per source; docstring expectation "~6–20" extraction calls per run |
Derived structural bound for `pi.discover` ≈ 10 + 10 + (≤ 12 waves × 90) + (≤ 3 waves × ~120) + (≤ 180) ≈ **1,640 s**; expected case ≈ 10 min or less; `pi.supplier_lookup` ≈ 70–140 s. **No measured end-to-end durations from a target host exist; LLM hardware and deployment are undecided ⇒ the final threshold is a reported blocker** (the mechanism — a derived floor enforced by config validation — is designed).

### J.6 Deployment environment (Q-R7)
`docs/planning/phase-1-readiness-review.md` item 2.19: "Deployment target — AWS / Railway / Render / Cloudflare, never chosen `[P]`"; item 3.9: "Ollama: development-only, or production too `[P]`". No Dockerfile, IaC or scheduler config in the repo; `backend/README.md`: "this repo has no deployment layer". ⇒ Unconfirmed; scheduler documentation deferred.

### J.7 Reservation machinery (Q-R8)
Migration `20261004_0005` + `repositories/cmo_quota_repo.py`: table `cmo_quota_reservation` (generic columns: `agent_code, meter_code, period_key, units, request_key, state RESERVED|SETTLED|RELEASED, expires_at`), one transaction under `pg_advisory_xact_lock(tenant|agent|meter|period)`, expires stale reservations, `usage = recorded events + unexpired reservations`, then inserts. The migration states the reason: a plain check-then-record let **7 of 8** concurrent requests pass a cap of 1. `reserve()`/`finish()` are agent-generic; they depend only on `slim_cmo.billing.precheck` (pure integer arithmetic). PI currently has no reservation, and its existing pre-flight reads usage from events that PI never wrote.

### J.8 LLM endpoint enforcement (Q-R9)
Only `backend/llm/model.py` refuses a non-local host (regex `localhost|127.0.0.1|[::1]`). `config.ollama_host()` (CFO narration, GST extraction, PI extraction/embeddings), `cmo_ollama_host()` and CI's `ollama_client` accept any URL unchecked; `CEO_LLM_PROVIDER`/`CMO_LLM_PROVIDER` can select other registered providers. The stated policy (C15, `ollama_host` docstring: "always a local address, never a hosted provider") is enforced for the CEO only. No data-disclosure policy exists for a third-party model endpoint (searched specs and the readiness review; `auth.md` V5 covers identity-data residency only).

### J.9 Leg `PARTIAL` meaning (new open fact Q-R11) and Business State reads (Q-R12)
A leg is `PARTIAL` when its payload has `dataRequestId` or `partialReason` (`dispatch._PARTIAL_KEYS`) — typically CFO asking the seller for an input, possibly with no usable figure. A `BUSINESS_STATE` turn whose entry is `UNAVAILABLE` is `DELIVERED` and charged today. Neither is a "failed required leg" under the owner's invariant; both need an explicit decision.

> **Update 2026-10-10 (post-merge).** Migration numbers in this document are now `20261011_0016` (R4), `20261011_0017` (R0) and `20261011_0018` (approval workflow); the pulled branch took `20261010_0011..0014`. `candidate_cap` is bounded `1..100` at the API; "1,850 s" is the structural bound for the default cap (30), not a maximum. R5 stays BLOCKED. Evidence: `ceo-approval-remediation-design.md` §6.
> **Evidence update 2026-10-10 (final).** Test evidence for the merged tree is in `ceo-approval-remediation-design.md` §7 (unit 3,992 passed / 6 xfailed; merge-affected integration subset 135 passed / 1 stale expectation fixed / 2 opt-in downgrade skips passed separately / 1 documented xfail; frontend 198 passed; lint, `tsc`, build clean; migration round trips and privilege checks pass on scratch databases). Billing rule: `CEO_UNIT_RULE_2` (any failed required leg ⇒ no unit; spec 6.42). R0–R4, R6, R7 PASS (targeted); **R5 BLOCKED** (no staleness threshold supported by evidence). VP-1 and VP-2 therefore remain **FAIL** until R5 is implemented.

> **Pointer 2026-10-10.** New evidence-gathering and decision material: `ceo-approval-s1-readiness.md` (S1–S3 proposal, R5 evidence plan, verification gate, decision register). Finding added since S0: the metered/seller-data-out chat paths introduced by orchestration 6.35/6.40 run behind an in-session confirm card, not an approval plan (readiness F-6, D-8).
