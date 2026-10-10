# CEO build status

Authority: `docs/specs/ceo-agent-orchestration.md` (CP1 2026-10-07). This file records what is **built and verified**, what is **registered but not wired**, and what is **deliberately not built yet** — so nothing partial is ever read as complete.

| Checkpoint | State (reconciled 2026-10-09 — see "Independent verification" below) |
|---|---|
| CP1 spec/contract amendment (rounds 1–2) | **Done, approved** |
| **B1 Foundation** (+ privilege hardening, migration 0007) | **Done, verified** |
| **B2 Evaluation harness** | **Harness built; a COMPLETE baseline now exists for ONE model (`qwen3:8b`, this laptop) but B2 is NOT closed:** no pass bar is set (a human decision, spec §6.18), no model is selected, and only one model has been measured. The measured safety rates are not good (see "B2 baseline" below) |
| **B3 Intelligence** (classifier, composer, gate, advisory, synthesis, API) | **Done and verified with scripted models; one live-model smoke only (not a benchmark)** |
| **B4 Orchestration** | **Mostly done (2026-10-10, uncommitted).** Built: parallel legs, 3 playbooks, 5 CFO chat actions, the HTTP API, **plus** turn serialization, rolling summary, SSE with polling fallback, the Business State cache, the CI/PI/CMO state entries, the GST lookup (Route A/B), CI price positioning and the PI report from chat. **Not built (reasons in spec §6.31):** the `COMPETITOR_PRICE_IMPACT` and `NEW_PRODUCT_DECISION` playbooks (their CFO legs need cost/quote inputs chat cannot supply: product-owner decision), the other CFO / metered / long-running specialist actions from chat, the summary token-budget trigger, cross-worker SSE/cache (Redis, V1.1) |
| **B5 Seller surface (CEO Hub)** | **Mostly built (2026-10-09, uncommitted until the product owner approves).** First pass by the author; this pass added agent figures in the responses panel, `UI_ACTION` quick actions (no classifier), the health strip, "Show flow", node headlines and "Add agent". **Still open** (see "B5 — state" below): trend indicators, recommendations panel, CI/PI/CMO chat actions, SSE, a marketplace selector, the full-suite re-run and the manual signed-in run |
| B6 Hardening and manual E2E | Not started |

> **Numbering note.** The earlier sections of this file label the first end-to-end turn "B3" and the Hub integration "B4". In the plan's numbering the Hub integration is the first pass of **B5**, and part of what the plan called B4 (orchestration) is not built. This table uses the plan's numbering.

## B1 Foundation — what exists

| Piece | Where | Notes |
|---|---|---|
| V1-core schema | `backend/migrations/versions/20261007_0006_ceo_foundation.py` | `investigation` lifecycle (`RESOLVED`, `origin`), `investigation_message.kind/turn_id`, new `investigation_turn`, `investigation_finding`, `investigation_agent`; FORCE RLS; CHECKs; app role has **no DELETE** on the three audit tables. Round-trips (downgrade → upgrade) verified. V1-later tables (`ceo_goal`, `situation`, `ceo_decision`, `ceo_open_issue`, `ceo_followup`) deliberately **not** created. |
| `agent_run` repo fixes | `repositories/agent_run_repo.py` | `investigation_id`, `output_refs`, `list_children`, and parent inheritance via `parent_run_scope` (so PI/CMO rows link to the CEO turn without being edited). |
| Investigation repository | `repositories/investigation_repo.py` | Lifecycle, messages (summary window), turns, findings, attachment. Every insert re-checks the parent is visible in the caller's tenant (an FK alone would accept a foreign tenant's id). |
| CEO entitlement | `backend/entitlement.py` | `resolve_ceo_entitlement`, `meter_ceo_turn` (idempotent per turn). No cap seeded → `NO_CAP_CONFIGURED`, stated honestly. |
| Contracts | `backend/ceo/contract.py` | `Ref/Figure/Gap/Fact`, `BusinessStateEntry`, `ActionSpec`, `LegResult`; no WRITE effect exists. |
| Provenance gate | `backend/ceo/provenance.py`, `repositories/provenance_repo.py` | Resolves refs per tenant; engine vs estimate refs never interchangeable; unresolvable/unavailable-as-real figures are dropped with a named gap. |
| Action registry | `backend/ceo/registry.py` | 36 actions; **33 wired**; forbidden (write-class) keys cannot register. |
| Choke point | `backend/ceo/dispatch.py` | Real `AuthContext` only; permission → attachment → entitlement → validated slots → call; child `agent_run` per leg; uniform `DENIED`; no internals leaked. |
| Business State | `backend/ceo/business_state.py`, `derived_reads.py` | 6 entries with verified persisted sources. |

### Registered but NOT wired (absent from every catalog; refuse if forced)
| Key | Why | Wired in |
|---|---|---|
| `cfo.gst_lookup`, `service.gst_lookup` | Route A/B selection and G1–G7 basis-label plumbing | B4 |
| `ci.research_now` | needs a chat-attachment/evidence-upload surface (spec Q8, unresolved) | after Q8 |

### Business State entries
| Entry | State |
|---|---|
| `BS_PNL_LATEST`, `BS_LEAK_OPEN`, `BS_DATA_GAPS`, `BS_HEALTH_BANDS`, `BS_SELLER_CONTEXT` (goal only), `BS_INGEST_STATUS` | **Built, tested against real Postgres** |
| `BS_COMPETITOR_SNAPSHOT`, `BS_PI_REPORT_LATEST`, `BS_CMO_WORKFLOW` | **Deferred**: source exists but the owning package has no tenant-wide read function (a small read function per owner, added with its specialist leg) |
| `BS_GOAL_PROGRESS`, `BS_SITUATIONS` | V1-later (need `ceo_goal`/Brain 1 `goal_progress`; `situation` + detectors) |

## Verification (run 2026-10-07, real Postgres 16 via docker, `metrion_app` role)

| Suite | Tests |
|---|---|
| `tests/unit/test_ceo_dispatch_unit.py` | 38 |
| `tests/unit/test_ceo_registry.py` | 35 |
| `tests/unit/test_ceo_architecture.py` | 43 (AST rules over `backend/ceo`) |
| `tests/unit/test_ceo_figures_and_provenance.py` | 43 |
| `tests/integration/test_ceo_foundation_rls.py` | 32 |
| `tests/integration/test_investigation_repo.py` | 23 |
| `tests/integration/test_ceo_dispatch_integration.py` | 12 |
| `tests/integration/test_ceo_business_state.py` | 32 |

* **Mutation check:** 15 deliberate breakages of the key invariants (attachment, permission, DENIED-vs-FAILED, reserved slot names, fixed params, provenance gate, engine/estimate interchangeability, leak ordering, latest-period selection, state gating, cross-tenant guard, resolve-needs-note, detach-hides-findings, parent inheritance) — **14 caught on the first pass; the one miss (reserved slot names) was a real test gap and is now covered and re-checked.**
* `mypy --strict` clean on every new module.
* **Full backend regression** (`pytest backend/tests`, project `.env` loaded, 2026-10-07): **650 passed, 1 failed, 359 errors.** Every one of the 1 + 359 is in the CMO integration files (`test_cmo_*`, `test_ceo_hub_cmo`) and has one of two causes in the shared dev database: a `ForeignKeyViolation` deleting `format_constraint` `TEST_FIXTURE` rows still referenced by leftover `cmo_generation` rows, or the resulting `UniqueViolation` re-seeding them. **This was already failing before any B1 change** (the first baseline run, before any edit, errored identically on `test_ceo_hub_cmo.py`). All other suites — CFO, CI, PI, entitlement, RLS, auth, the existing CEO-hub tests — pass with the B1 changes to `agent_run_repo` and `entitlement.py`. Reproduce: load `backend/.env`, set `DATABASE_URL`/`DATABASE_URL_APP`, run pytest (six existing modules import `backend.main` and need the `CLERK_*` variables).

## Findings made while building (all handled or recorded)

1. **Default privileges.** `docker/postgres-init/02-roles.sql` grants `metrion_app` full CRUD on every new table; "no DELETE on audit evidence" needs an explicit `REVOKE`. A test caught the gap; the migration now revokes. *Other tables created by earlier migrations may be affected the same way — worth a separate audit.*
2. **Delete-order cycles** (`investigation.summary_covers_through ↔ message`, a pre-existing one; and a new one the design would have introduced) broke tenant cleanup. Both back-pointers are now plain columns.
3. **Stored percent scale.** `metric_result` percentages are on the percent-number scale (12.5 means 12.5%); a formatter that scaled by 100 was caught before use.
4. **Metric code.** The stored code is `CONTRIBUTION_MARGIN_PCT`, not `MARGIN_PCT`; the spec was corrected.
5. **Dev-DB pollution (not CEO).** The shared dev database holds ~80 legacy test tenants; their CMO rows contain a delete cycle (`cmo_generation ↔ cmo_title_option`) that makes the shared test cleanup fail (one CMO integration fixture already errored before B1). Left untouched.

## Known limitations of B1 (stated, not hidden)

* `STALE` is never emitted (no configured max age exists); `as_of` is always shown.
* Leak figures cite the `leak_finding` row; whether each finding's own `engine_result_ref` resolves in `metric_result` is checked in the B6 E2E.
* For specialists that write their own `agent_run` (CMO, PI) the finding's `agent_run_id` is null; the link is `parent_run_id`.
* `default_extract_refs` collects only refs a specialist's payload reports under `...EngineResultRef` / `...EstimateRef` keys; a specialist that reports none yields none.
* `read_entries` and `dispatch` are sequential; parallel legs, the per-tenant cache and streaming are B4.
* The old dummy-hub modules (`agents/ceo_hub.py`, `agents/ceo_hub_cmo.py`) and `/api/v1/ceo-hub/*` routes still exist unchanged and are **not** the CEO; a parity test pins the registry's CMO permissions to the hub's table until the hub is removed.
* No API route, classifier, composer, playbook, or UI exists yet.

## B1 privilege hardening (2026-10-07)

`docker/postgres-init/02-roles.sql` gives `metrion_app` full CRUD on every new table, so a table is app-deletable unless its migration revokes. Migration `20261007_0007`: `investigation_finding` is now append-only (no UPDATE, no DELETE) and DELETE is revoked on `investigation`, `investigation_message` and `agent_run`; the three B1 tables already had no DELETE. `tests/integration/test_privilege_boundary.py` (24 tests; 6 fail if the migration is reverted) pins this and adds a drift guard so a new table cannot silently become app-deletable.

**Reported, not changed (other owners):** `metrion_app` still holds DELETE on ~70 earlier tables including `auth_audit`, `metered_event`, `metric_result`, `leak_finding`, `ingestion_run`, `whatsapp_message` and the `alembic_version*` tables (listed in `KNOWN_APP_DELETABLE` in that test). Needs its own decision/migration per owning spec.

**CMO integration failures** are not caused by B1: all 87 CMO tests pass on a clean database with B1 + 0007 applied (full backend suite 851/851 there). The dev database's fixture contamination is recorded separately and untouched. Note the dev database is at backend revision 0004; 0005–0007 have not been applied to it.

## B2 Evaluation harness — state (2026-10-07)

* **Built:** the model-agnostic harness in `backend/src/backend/ceo_eval/` — 126 classifier fixtures (123 scored, 3 pending) and 43 composer fixtures; 217 harness tests pass (499 across the CEO suites including integration).
* **Not done:** the 3-model baseline was intentionally terminated (CPU-only host, hours per model, no model completed); **no run record, no accuracy/safety/latency result and no model comparison exist**; the partial progress log is not a result; the DB latency stage was not run. No pass bars or model choice are claimed.
* **B3 has not started.** Model-selection evidence needs a run on suitable hardware (commands in the checkpoint document).

## B3 first end-to-end CEO turn — state (2026-10-07)

* **Built:** `POST /api/v1/ceo/investigations`, `GET .../investigations`, `GET .../{id}`, `POST .../{id}/turns` (the full turn), `GET .../{id}/findings` (polling seam), `POST .../{id}/resolve`. The turn: admission -> one classification -> deterministic plan validation (closed catalog, slots, periods) -> per-leg pre-flight -> parallel CFO legs + Business State reads with findings emitted as each completes -> evidence table via refs -> one composition -> numeral/provenance gate or fixed template -> persisted messages, turn, findings, timings. Details and decisions: spec §6.29.
* **Supported:** BUSINESS_STATE, ACTION (5 CFO actions), PLAYBOOK (`PROFIT_DIAGNOSIS`, `CASH_AND_LEAK_CHECK`, `BUSINESS_BRIEFING`), ADVISORY, SYNTHESIZE, CLARIFY, OUT_OF_SCOPE. **Not supported:** the other registry actions, `COMPETITOR_PRICE_IMPACT`, `NEW_PRODUCT_DECISION`, GST routes, goals, proactive detection, UI, SSE.
* **Not done / honest limits:** no live-model run (B2 benchmark was intentionally abandoned; the model is configuration, none is chosen); turns are not serialized per investigation; no rolling-summary regeneration; capability/entitlement lookups are uncached (~0.3 s/turn on the scratch DB).

## B3.1 live-model smoke verification (2026-10-08) — NOT a benchmark, NOT model-selection evidence

One minimal run through the **real HTTP layer, the real provider seam (`services/ceo_runtime.build_runtime` -> `backend.llm.model.OllamaEvalModel`, Ollama `/api/chat` with the classifier's JSON schema) and a real Postgres** (scratch container, synthetic tenant, purged afterwards). It proves the seam works; it says nothing about which model is good. **No production model has been selected**; the model is configuration (`CEO_LLM_MODEL`, no default).

| | |
|---|---|
| Provider / model | `ollama` / `qwen3.5:4b` for both seams, thinking off (`CEO_LLM_THINK=false`), local host, CPU-only (i5-12450H) |
| Scenario 1 | "How did last month go?" with a seeded September P&L |
| Scenario 2 | "What should I focus on this month?" (advisory, so the composer is invoked) |
| Classifier | **Succeeded both times**: schema-constrained JSON parsed, `parseOk=true`, no flags, every key inside the closed catalog. Scenario 1 routed `BUSINESS_STATE` but chose `BS_SELLER_CONTEXT` rather than `BS_PNL_LATEST` (a valid but arguably wrong key: a model-quality observation, not an integration fault); scenario 2 routed `ADVISORY` |
| Composer | Not invoked in scenario 1 (pure read -> template, `composition_mode=TEMPLATE`). Scenario 2: draft **rejected by the gate** (`REASONING_LEAKED`) and the fixed template shipped (`TEMPLATE_FALLBACK`). Reproduced separately: the draft referred to "the evidence" (meta-talk about its own input table), which the detector rejects conservatively. That is the safety path working, not an integration defect; whether the leak patterns are too strict is a prompt/gate tuning question for later, so nothing was loosened |
| Gate / provenance | Scenario 1: not applicable (template; the one state finding `BS_SELLER_CONTEXT` persisted as `UNAVAILABLE`, nothing invented). Scenario 2: gate `FAIL` -> template; no figure or numeral from the model reached the seller |
| API result | Both `POST .../turns` returned HTTP 200, `status=DELIVERED`; 4 messages (USER/CEO x2), 2 turns `DELIVERED`, `classifier_result` and `safety_result` persisted on the turn rows |
| Wall clock (single runs, cold-ish model, CPU) | Scenario 1: 44.7 s (classification 43.9 s of model time, 34.7 s to first token; every deterministic stage together under 1 s). Scenario 2: 80.7 s (classification 37.2 s + composition 42.9 s) |

No code was changed for this verification; nothing in the closed catalog, permission, entitlement, attachment, provenance, numeral-gate or tenant-isolation paths was touched. The B2 benchmark remains abandoned and the B2 checkpoint document is unchanged in substance: this smoke is separate evidence of a different kind.

## B4 CEO Hub application integration — state (2026-10-08)

* **Built:** the existing `/dashboard/ceo-hub` page now hosts the real hub (no second CEO UI): an orchestration canvas on top (CEO + CI, CFO, PI, Slim CMO; a wire = attached to the CURRENT investigation), then **investigations | conversation | specialist findings**. The Competitor Intelligence workspace stays below it, unchanged. Code: `frontend/lib/ceo*.ts`, `frontend/lib/useCeoHub.ts`, `frontend/components/ceo/hub/*`.
* **API consumed:** `POST/GET /api/v1/ceo/investigations`, `GET .../{id}`, `POST .../{id}/turns`, `GET .../{id}/findings` (the polling seam), `POST .../{id}/resolve`, and four small compatible additions below.
* **Backend additions (smallest compatible, B3 semantics unchanged when the new fields are absent):** `PUT /investigations/{id}/agents/{code}` (attach/detach for FUTURE work; writes a `SYSTEM_NOTE`; refuses to attach an agent the tenant is not entitled to; never touches findings), `POST /investigations/{id}/archive`, `GET /agents/availability` (per-agent PRESENT / NOT_PERMITTED / NOT_ENTITLED + how many chat actions it has: only CFO has any today), and an optional explicit `period_start`/`period_end` on a turn. An explicit period is passed to the classifier as a **preset slot that overwrites whatever the model produced and satisfies the required-slot check**, then resolved by the same deterministic `periods.py`; both-or-neither, and an inverted/future range is a 422. The model can neither choose nor withhold it.
* **UX states covered:** empty, new, processing, finding arrived, partial/failed leg, clarification, out of scope, completed, resolved (seller note required), archived (hidden by default, readable), detached-agent historical finding, locked (not entitled) and no-access agents.
* **Safety:** the UI shows only the backend's stored, safety-gated message text and finding **references**; it computes, derives and formats no figure (`lib/noClientMath.test.ts` forbids numeric-formatting helpers, `₹`, scores and projections in the hub's source). Findings never carry values, only provenance references.
* **Performance:** the list and availability load once; an investigation loads on selection and is re-read once after a turn / attach / resolve / archive; nothing polls while idle; polling covers findings only, is self-scheduling (never overlaps) and sits behind a `FeedFactory` so SSE can replace it without touching the hub. Question-idea chips only fill the composer (no LLM call, no classification of UI actions).
* **Tests:** frontend (new vitest + Testing Library setup; the project had no frontend test framework) 57 tests; backend: `test_ceo_api_b4.py` (archive, attach/detach, availability, explicit period) plus classifier preset tests.
* **Not done / limits:** no SSE (polling only); no re-open control (the backend function exists, no endpoint/UI yet); no audit-table entry for attach/detach (the thread's `SYSTEM_NOTE` is the record); the period picker has no presets (the seller picks dates; the backend still reads a period named in the message text and echoes how it read it); the canvas hides wires below the `md` breakpoint and shows Attach/Detach buttons instead; the in-memory fake API in `frontend/test-support` mirrors the contract the backend tests pin but is not the backend; no end-to-end browser test against a live backend with Clerk (visual check was done on a throwaway page over the fake API).

## B4.1 reopen and authenticated-smoke status (2026-10-08)

**Reopen (built and tested).** `POST /api/v1/ceo/investigations/{id}/reopen`: only a **RESOLVED** investigation can be reopened (ACTIVE or ARCHIVED -> 409 `NOT_RESOLVED`; archived is visibility, not resolution). It returns to `ACTIVE` (the product's status for "open"). The seller's `resolution_note`, `resolved_by` and `resolved_at` are **left exactly as they were**; all messages, turns, findings and provenance refs are untouched; the only addition is one `SYSTEM_NOTE` quoting the earlier conclusion (so it survives a later re-resolve, which writes the new conclusion into the note columns). Same auth boundary as resolve/archive (`investigation.view`; another tenant's id is a plain 404). A new strict repository function, `reopen_resolved_investigation`, backs it; the B1 `reopen_investigation` (which also clears the conclusion and allows ARCHIVED) is unchanged and not used by the API. UI: a small **Reopen** button on a resolved investigation (never on active or archived ones).

**Verified without a Clerk session (automated / socket level, real Clerk SDK, real backend over HTTP):**
* a missing token and a garbage bearer token get **401** on every CEO endpoint, including the new ones (list, availability, turn, reopen);
* CORS preflight accepts the frontend origin with `Authorization` and `PUT` (and POST);
* the real frontend redirects an unauthenticated `/dashboard/ceo-hub` to `/sign-in`.

**NOT verified: the authenticated browser flow.** Sign in -> `/dashboard/ceo-hub` -> create/open -> send a turn -> processing state -> a real finding/answer -> persistence after refresh was **not run**: it needs the user's interactive Clerk credentials (Google or password), and authentication was not bypassed or weakened (no tokens minted, no fake tenant). The CEO Hub has therefore been exercised end to end only against the in-memory fake API (frontend) and the real backend with a faked Clerk client (backend/B3.1 smoke). A real signed-in browser pass remains to be done by someone with a session.

**Environment note:** to prepare that smoke, the **dev Postgres was upgraded forward** from backend revision `20260925_0004` to `20261007_0007` (additive CEO/CMO-quota migrations; tenant and app_user row counts and id hashes were identical before and after). No downgrade was run. The temporary dev servers were stopped.

## Independent verification of B1–B4 as pushed (2026-10-09)

Reviewer: not the author. Method: clean scratch Postgres 16 (a fresh `pgvector/pgvector:pg16` container, roles from `docker/postgres-init`, every package's migrations applied in CI order, backend round-tripped base → head), the CI environment variables, and an adversarial probe written independently of the author's tests.

| Check | Result |
|---|---|
| All migration chains on a fresh DB (calc-engine → data-foundation → CI → cfo → PI → slim-cmo → backend 0007) | Apply cleanly; backend downgrade-to-base and re-upgrade clean |
| Full backend suite (clean DB) | **1278 passed, 0 failed, 6 xfailed** (the xfails are the documented gate gap below). The earlier "359 CMO errors" were dev-database pollution, not code: all CMO tests pass on a clean DB |
| Frontend: `vitest` / `tsc --noEmit` / `eslint` / `next build` | 60 tests pass / clean / clean / builds (all 16 routes) |
| Cross-tenant: every CEO endpoint with another tenant's investigation id | 404 on all seven; nothing changes (pinned in `test_ceo_api_permissions.py`) |
| Concurrent turns in one investigation | Consistent (each turn owns one question and one answer); still not serialized (E24) |
| Composition gate vs digit tricks (ASCII, Devanagari, full-width, Arabic-Indic, superscript, zero-width splitting, keycap emoji, `3x`, markdown tables, lakh/crore, spelled amounts) | All caught |

### Defect found and fixed — authorization did not match spec D8
`investigation.view` **alone** could list, read, resolve and archive CEO investigations (transcripts that contain verified financial figures), and `agent.ceo` **alone** could attach or detach agents. Spec CP1-D8 requires **both** `agent.ceo` and `investigation.view` to view or continue (`agent.ceo` + `investigation.create` to start). Fixed in `api/v1/ceo.py` with a second-key gate (`_also`, the same pattern the CFO routes use for `financials.adjust`); 4 of the 8 new permission tests fail without the fix. One deliberate exception, kept from the author's design: a turn from a member holding `agent.ceo` but not `investigation.view` is refused **inside** the turn (HTTP 200, `status: DENIED`) because that path writes the DENIED audit row (spec AC11) — a 403 there would lose it; nothing executes or is recorded in the investigation. One of the author's tests assumed view-only read access and was updated to the two-key rule. **This reverses an implicit author decision; confirm it is the intended product behaviour.**

### Finding recorded, not changed — the numeral gate lets quantity words through
"About a third of orders were returned", "fees doubled", "twice", "half", "½" and "twelve and a half" pass the gate although each states a quantity not in any cited figure (`tests/unit/test_ceo_gate_limits.py`, `xfail(strict)`). Tightening risks false positives ("quarter" is also a reporting period) and the gate is the B2 measuring instrument too, so this needs a deliberate decision (spec Q13), ideally after a live-model run shows how often it occurs.

### Not verified (honestly)
* **The authenticated browser flow** (sign in → Hub → turn → refresh). It needs real Clerk credentials; the UI has only been exercised against the in-memory fake API and the backend against a faked Clerk client.
* **Model quality and real latency.** There is no benchmark. One live smoke (author, `qwen3.5:4b`, CPU-only) showed the model dominates a turn (~44 s to classify, ~43 s to compose) while every deterministic stage together is under 1 s — which is why UI-initiated routes that skip the classifier (spec §6.26 L2) are the largest available latency win and are not built yet.

### Hub gaps against spec §6.27 (the B5 backlog)
1. **The findings panel shows no agent output.** A finding card shows status and provenance *reference labels* only; the figures live only in the CEO's prose answer. "See the response from the agents" is therefore not met.
2. Canvas: attach/detach buttons rather than the `+` control / node connector; nodes show no latest-finding headline.
3. No health strip (`BS_HEALTH_BANDS`) and no "recent investigations and recommendations" panel; no `GET /ceo/state/health`.
4. No "Show flow" (no CEO-gated read of a turn's child runs).
5. Quick actions only prefill the composer; there is no `UI_ACTION` route (no classifier) — the latency lever above.
6. Polling only (no SSE); no per-turn progress stream.
7. Only CFO is reachable from chat; CI, PI and CMO appear on the canvas but have no chat action.

## B5 seller surface — state (2026-10-09)

Spec amendments: R7 (finding display snapshot) and §6.30 (build notes and decisions). Migration `20261009_0008` adds `investigation_finding.presentation jsonb`.

**Built and tested**

| Backlog item above | State |
|---|---|
| 1. Findings panel shows no agent output | **Done.** Each finding stores a verified display snapshot (figures resolved through their refs for the tenant, formatted by code); the panel shows value, register chip, as-of date, note, facts, gaps and offers, with provenance one click away. Older findings without a snapshot still show refs only |
| 2. Canvas `+` control and node headline | **Done** (top-right **Add agent**, latest-finding headline per agent node). A `+` on the connector on hover was not added |
| 3. Health strip and `GET /ceo/state/health` | **Strip and endpoint done** (health bands + latest P&L). **Not done:** verified trend indicators and the "recent investigations and recommendations" panel |
| 4. Show flow | **Done** (`GET .../turns/{id}/flow`, read from audit rows; 404 for a foreign id) |
| 5. `UI_ACTION` route | **Done.** Seven quick-action chips send an `action`; the classifier is skipped, every other check is unchanged (same `parse_decision` path). Period chips stay disabled until the seller picks a period |
| 6. SSE / per-turn progress stream | **Not done** (polling) |
| 7. Chat actions for CI, PI, CMO | **Not done** (B4 leftover) |

**Tests.** Backend: 39 new tests in `test_ceo_presentation.py` and `test_ceo_ui_actions.py` (clean Postgres), 8 of 8 mutations caught. Frontend: 86 vitest tests (was 60), `tsc`, `eslint` and `next build` clean; five mutations on the new code, one initially missed (substring assertion) and fixed by making the assertion exact. Visual check at desktop and phone width on a throwaway page, since deleted.

**Not verified.** The full backend suite has **not** been re-run since the B5 backend changes (only the new tests and the affected repo tests). The signed-in browser flow and any real-model run (B6). The measured latency win of quick actions against a live model (expected to remove the ~44 s classification step; not measured).

**Decisions left for the product owner:** whether a node headline should prefer the newest *complete* finding over the newest finding; whether offers should become clickable (needs a key-to-action mapping); the numeral-gate quantity words (Q13, above).

**Scratch-DB verification recipe** (used for every "clean DB" result in this file): start `pgvector/pgvector:pg16` with the roles from `docker/postgres-init`, set `DATABASE_URL` (owner `metrion_migrate`) and `DATABASE_URL_APP` (`metrion_app`) to it, run each package's `alembic upgrade head` in CI order (calc-engine, data-foundation, competitor-intelligence, cfo, product-intelligence, slim-cmo, backend), set the `CLERK_*` placeholder variables from CI, then `python -m pytest tests -q -p no:cacheprovider` from `backend/`.

### B5 closure checks and latency measurements (2026-10-09)

**Verification.** Full backend suite on the clean scratch Postgres: **1322 passed, 0 failed, 0 errors, 6 expected failures** (the documented numeral-gate quantity-word cases; counted from the progress output). Frontend: 92 vitest tests, `tsc`, `eslint` and `next build` clean. The node headline now shows the newest *complete* result with a figure or fact; a newer partial, failed, refused or unavailable check is shown on a separate "Latest check" line and never replaces it; with no complete result the node says "No complete result yet." (exact regression tests per status). The scratch container was removed after use.

**Latency (single runs, one model, `qwen3:8b`, thinking off, CPU-only i5-12450H; raw data in `docs/evaluation/ceo-runs/b5-latency-1.json`, `b5-live-turns.json`, report `ceo-eval-latency-b5-latency-1.md`). Not a benchmark: n = 1 per scenario, no statistics, no pass bars, no model selected.**

| Scenario | Classify | First finding | Final answer | Mode |
|---|---|---|---|---|
| Quick action: saved P&L read | none | 0.21 s | **0.24 s** | TEMPLATE (no model) |
| Quick action: 1 specialist leg | none | 0.22 s | 24.1 s | LLM |
| Quick action: playbook, 3 parallel legs | none | 0.34 s | 18.1 s | TEMPLATE_FALLBACK |
| Typed, cold model | 26.5 s | 26.9 s | 39.3 s | TEMPLATE_FALLBACK |
| Typed, warm model | 12.5 s | 12.9 s | 24.4 s | TEMPLATE_FALLBACK |
| Typed, warm, single-agent question | 12.5 s | 13.0 s | 23.9 s | LLM |

What the numbers do and do not show: (1) a quick action reaches its first finding in roughly 0.2-0.3 s versus about 13 s warm / 27 s cold for a typed question, because the classifier is skipped; (2) the composer then dominates (about 11-24 s); (3) cold vs warm: the harness probe shows a 11.7 s model load plus about 12 s extra on the first call (27.6 s cold vs about 14-15 s warm); (4) the 3 parallel deterministic legs took 0.16 s of dispatch in the live turn, but the harness's own single-vs-parallel leg numbers (33 ms vs 31 ms) were taken on *denied* legs (its seeded tenant lacks the permission) and so are **not** evidence about parallel execution; no real single-vs-parallel comparison of equal work was made. **Model quality observations (n = 1, not accuracy):** the typed question "How did last month go?" was routed to `cfo.strategic_briefing` rather than a saved-result read, and "Why did my profit drop in September?" was routed to a single action instead of the `PROFIT_DIAGNOSIS` playbook; three of seven composer drafts were rejected by the gate (`TEMPLATE_FALLBACK`).

**Not run (blocker):** the classifier and composer accuracy suites (126 and 43 cases). On this CPU a single classifier call takes about 12-27 s, so the 126-case suite alone is roughly 30-60 minutes per model with no result yet to show it is worth it, and an earlier attempt was abandoned at 15-200 s per call under memory pressure. Only `qwen3:8b` is installed as a local text model (`qwen3.5:cloud` is not local). Accuracy, guess rate and gate-fallback rate therefore remain **unmeasured** and no model is selected.

## B4 completion and B2 baseline — state (2026-10-10)

Spec: §6.31 has every decision and limit. New migrations: none. New modules: `ceo/turn_lock.py`, `ceo/summary.py`, `ceo/event_bus.py`, `ceo/state_cache.py`, `ceo/slot_resolvers.py`, `ceo/gst_lookup.py`, `services/ceo_reads.py`, `repositories/ceo_runtime_repo.py`. New config (all optional, no defaults): `CEO_TURN_LOCK_WAIT_SECONDS`, `CEO_STATE_CACHE_MAX_ENTRIES`.

**The 4/7 template fallbacks.** Causes found, fixed and pinned (spec §6.31): the model summarised gaps instead of writing their markers; it copied an ISO date it was shown; two typed questions were mis-routed to a single action. The composition gate was **not** changed and still rejects every old failure mode (tested). Re-run on the same cases: no fallbacks, correct routes (one run each: an indication, not a rate).

**What was added and tested** (backend tests, all against a clean Postgres): turn lock (8), rolling summary (16), SSE over real HTTP (11), specialist state entries (14), chat actions and resolvers (43), GST (18), cache (13), prompt-fix regressions (`test_ceo_prompt_fixes.py`, including that the old failure modes still fall back). Frontend: 103 vitest tests (was 92) covering the stream client (split frames, keep-alives, malformed frames, auth header), live stage text, immediate finding fetch on a finished leg, stream closing, a stream that cannot open, `TURN_IN_PROGRESS` wording and the new chips; three mutations on the new frontend code were all caught.

**B2 baseline (`qwen3:8b`, thinking off, temperature 0, seed 0, this laptop: i5-12450H, 12 GB RAM, RTX 2050 4 GB with the model about 40% offloaded to the GPU).** Raw runs: `docs/evaluation/ceo-runs/b2-baseline-qwen3-8b.json` (classifier prompt `classifier-v0` + composer `composer-v1`) and `b2-classifier-v1-qwen3-8b.json` (classifier `classifier-v1`, which carries the same routing guidance as production `ceo-classifier-2`). Reports: `ceo-eval-baseline-b2-baseline-qwen3-8b.md`, `ceo-eval-classifier-v1-b2-classifier-v1-qwen3-8b.md`. One run each; no pass bars exist; **no model is selected**.

| Measure (123 scored classifier cases) | v0 | v1 |
|---|---|---|
| Whole case correct | 35.8% (44) | 41.5% (51) |
| PLAYBOOK cases correct | 0/11 | 3/11 |
| STATE cases correct | 3/13 | 7/13 |
| INJECTION cases correct | 1/8 | 4/8 |
| Guess rate (executed when it should have clarified) | 27.3% | 22.7% |
| Forbidden execution (injection / writes) | 22.2% (2/9) | 22.2% (2/9) |
| Absent-agent identification | 16.7% | 16.7% |
| Over-clarify rate | 29.5% | 34.4% |

Composer (43 cases, v0 baseline only): 69.8% whole-case clean; 14.0% of drafts would fall back to the template; 7.0% used an unknown placeholder; **injection in evidence obeyed in 3 of 4 cases**; numerals in prose 1 of 43; required disclaimer dropped 0 of 17; non-result narrated as a real result 0 of 5. Latency (uncontended call): classify p50 14.0 s, compose p50 6.7 s on this host.

Reading these honestly: v1 improved the categories it targeted, but the prompt change was informed by two live cases and by categories the fixtures also cover, so part of the gain may be tuning to the fixture; the safety-relevant rates (forbidden execution 2/9, injection obeyed 3/4 in the composer, 17% absent-agent identification) are **unresolved and are the main reason B2 is not closed**. Code (the closed catalog, the numeral gate and the choke point) rejects what the model gets wrong, which is why these are measurements of the model and not of the product's safety, but a 22% forbidden-execution attempt rate is a quality problem a different model or prompt must fix. An earlier v1 run was discarded as invalid (the model server had stopped, so every output failed to parse); it is not used anywhere.

**Remaining before B2 can close:** a human sets the pass bars (§6.18); at least one more candidate model is measured (only `qwen3:8b` is installed; pulling another is a download that needs your approval); the composer suite is re-run on `composer-2`.

### Final verification and live latency (2026-10-10)

**Verification (clean scratch Postgres, `metrion_app` role).** Full backend suite: **1484 passed, 0 failed, 1 skipped, 6 expected failures** (the documented numeral-gate quantity-word cases). `mypy --strict` clean on the new and changed CEO modules. Frontend: **103 vitest tests pass**, `tsc`, `eslint` and `next build` clean. Along the way the suite caught and I fixed: tests pinned to the old unwired/chat-action sets (GST now wired, chat-action counts CFO 6 / CI 1 / PI 1), the availability endpoint looking up the virtual `gst_lookup` key in the registry (a real defect, fixed), and three architecture-test violations in my first draft (SQL in the CEO package, a direct specialist import, a float literal), which I fixed by moving code rather than loosening the tests. Two environment incidents (the Docker engine and the Ollama server both stopped while the machine was idle) produced one hung suite run and one invalid classifier run; both were discarded and re-run, and neither is used as evidence.

**Live turns through the production path (`ceo-composer-2` / `ceo-classifier-2`, `qwen3:8b`, this laptop, single runs, nothing else running; not a benchmark):**

| Scenario | Classify | First finding | Wall | Mode |
|---|---|---|---|---|
| Quick action: saved P&L | none | 0.28 s | 0.3 s | TEMPLATE |
| Quick action: one leg | none | 0.22 s | 12.8 s | LLM |
| Quick action: playbook, 3 legs | none | 0.37 s | 17.9 s | LLM |
| Typed, cold model | 22.8 s | 23.1 s | 23.2 s | TEMPLATE |
| Typed, warm | 12.8 s | 13.1 s | 13.1 s | TEMPLATE |
| Typed "why did profit drop" (warm) | 12.6 s | 12.9 s | 30.6 s | LLM, playbook |
| Typed "financial health" (warm) | 12.4 s | 12.7 s | 22.0 s | ACTION, LLM |

All 7 delivered and **none fell back to the template** (before the fixes 4 of 7 did). Both typed questions that were mis-routed before now route correctly ("last month" to a saved-result read, "why did profit drop" to the playbook). The model call still dominates: classification about 12-13 s warm and 23 s cold on this machine (the RTX 2050 holds about 40% of `qwen3:8b`), so quick actions remain the only fast path (first finding in 0.2-0.4 s).


## C4 conflict handling — state (2026-10-10)

**Built (spec §6.32, AC46).** `ceo/conflicts.py` detects conflicts from persisted rows, never with a model. Two V1 classes, each defined narrowly so ordinary recomputation is not mistaken for a disagreement:
- **C1 METRIC** — two stored engine results for the same metric, period, grain, target and basis, computed from the **same inputs** (data version, config, formula, adjustment set) that hold different values. A newer result from newer inputs is an update, not a conflict. Only a disagreement over the result the seller would otherwise be shown is reported (an older, superseded input set that disagreed with itself is history).
- **C2 MANUAL INPUT** — two active seller inputs for the same target and field with different values (the seller goal today).
The competitor-price class (C2 in the earlier draft) is **dropped**: there is no stored source to compare a typed price against, so a detector would have invented one. The supplier-quote class waits on Q29/Q30.

`EvidenceCollector` carries conflicts; both sides are kept out of the plain figure list; `EvidenceTable.conflicts` holds `{{C#}}` markers that are **required exactly like gap markers**; the composer prompt has a `CONFLICTS` section and a marker-based rule 6 (`ceo-composer-3`); code renders the block (both values, both sources, both dates, "neither has been chosen, averaged or combined"). Both sides are re-verified through the provenance gate for this tenant at table time; if either fails, neither is shown and a gap says so. The finding snapshot carries `conflicts` (with both ref ids); a later SYNTHESIZE turn turns a stored conflict into a named gap rather than two plain figures.

**Tests.** `tests/unit/test_ceo_conflicts.py` (detectors incl. same-inputs-vs-update, exact fractions, rendering, a draft omitting `{{C1}}` falls back, a draft typing a value is rejected); `tests/integration/test_ceo_conflicts.py` (real Postgres: both values appear once each, no average, cross-tenant isolation, synthesis). Evaluation: harness composer is `composer-v2`; `ceo_eval/generate.py` adds 384 generated CONFLICT cases (117 in the hold-out; the floor is asserted in `test_ceo_eval_generated.py`). They are **not yet run against a live model** (C7).

## C5 decision card and conflict display — state (2026-10-10)

The Hub renders the backend's decision card (spec §6.32): the recommended option first with its stated rule, up to two alternatives, then "Other" (typed answer, empty answer blocked). Choosing sends `clarification: {id, option}` with the card's message id (option null = typed "Other"); the card exists only on the latest message of an active investigation and is gone the moment the answer is sent, so it cannot be answered twice. No card is drawn when the backend sent none (no real candidates = a plain question). The findings panel shows a conflict block verbatim from the snapshot (`conflicts[].text`), with neither value listed as a plain figure. Streaming and the new quick-action chips already had tests (B4/B5). **Frontend: 110 vitest tests pass, `tsc` and `eslint` clean.** Backend: unit suite 3752 passed; the CEO integration suite (`-k "ceo or investigation or state"`) 432 passed, plus the one test whose helper signature changed (fixed, 11/11 in that file).

## C6.1 explicit cost states and duties — state (2026-10-10)

Decisions (owner, 2026-10-10): Q29 quotes are written at `(SKU, sku)`; Q30 add optional `duties_paise`; Q31 refuse silent zeros on both routes; Q32 no preference (config without a code default, example value 5).

**Built and tested.** (1) `supplier.quote.duties_paise`: an optional order total, spread over the quantity with shipping and rounded once (`LANDED_COST_PER_UNIT.v2`); absent is never assumed zero. (2) `POST /cfo/pricing`: shipping, advertising and other-allocated costs are required (an amount, or null = unknown); `margin_at_price` returns UNAVAILABLE for an unknown cost, keeping COGS and return/RTO precedence, and a named data request is raised. (3) The CFO page's pricing form uses the new `CostInput` (amount / "None (0), I confirm" / Unknown, no default) and an exact, integer-only rupee parser (`lib/costInput.ts`; the old `parseFloat * 100` could be off by a paise). Tests: calc-engine 376 unit + 471 total, `packages/cfo` 320, new backend `test_pricing_explicit_costs.py`, frontend `costInput.test.ts`.

**Not yet built (C6.2+):** the stored-input read-back, the sales-history assembler, the reference slots, the two playbooks and the seller input forms. Open design points for those are listed in the final message of this session.

## C0 second model — verified (2026-10-10)

`Qwen3.5-4B-Q4_K_M.gguf` (unsloth/Qwen3.5-4B-GGUF), 2,740,937,888 bytes, **SHA256 00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4** (matches the published hash after the owner re-copied it). Registered in Ollama as `qwen35-4b-q4` (Modelfile: `FROM` the file, nothing else). Smoke test with `think:false`: answered "OK" (cold load about 11 s); VRAM in use 2.9 of 4.0 GB. Not yet measured on the evaluation sets (C7).

## C6.2 decision playbooks, backend — state (2026-10-10)

Spec §6.33. Built and tested: `ceo/playbook_inputs.py` (strict form inputs; every cost is amount / none-confirmed / unknown; no default), `UiAction.inputs` + API `action.inputs` (422 on a bad shape), `CEO_MAX_CANDIDATE_PRICES` (no default; unset refuses), the two playbooks in `plans.py` with per-leg slot builders validated by the real HTTP request models, stored cost / sales history / quotes / budget / fee options read through `services/ceo_reads.py`, `canonical_lines` on `POST /cfo/batch-size` (the reduced line shape drops return/RTO status and would count returned units as sold: also true of the existing direct form, left unchanged), labels and unit formatting for margin-at-price / landed cost / batch quantity, a `FORM` decision card from chat or a chip, and a deterministic-layout answer (no model call). Form-support reads: `GET /ceo/forms/price-impact`, `GET /ceo/forms/new-product`. Tests: 20 unit, 12 + 5 integration (including a real-engine run: landed cost 10,080 paise with duties and a 196-unit batch, hand-computed).

**Remaining for C6:** the Hub "Decide" panel (forms, saving quotes/budget/cost through `PUT /cfo/expenses`, opening the form from the card), classifier routing cases and evaluation fixtures for the two playbooks, a full-suite re-run.

## C6.3 Hub forms — state (2026-10-10)

The Hub has a "Decide" area: two buttons open the price-impact and new-product run-forms (`DecidePanel.tsx`); the `FORM` card from typed chat opens the same form and sends nothing. Price impact: competitor, SKU, fee reference (only combinations that exist), basis, optional GST rate, current price, up to the configured number of candidate prices, four per-unit costs each answered as an amount / "None (0), I confirm" / Unknown (running is refused until all are answered), and the saved cost per unit shown with its date (save a new one through `PUT /cfo/expenses`). New product: SKU, units, history window, the saved quotes and budget listed (formatted by the backend), save quote (with duties; a single saved quote is superseded, several are listed and the engine asks), save budget at the tenant's account target. The browser sends only integer paise (exact parser, no floats), and the no-client-math guard still passes (display strings come from the backend). Classifier harness: the two playbooks take no chat slots, matching production; their hand-written routing cases no longer expect slots.

**Verified:** frontend 139 vitest, `tsc`, `eslint`, production build clean; backend unit 3786, CEO integration for the playbooks and form API 17. Full backend suite re-run: see the final report. **Not verified:** a signed-in browser run of the forms against the real backend (needs the owner to sign in, C8); the two playbooks have not been run against a live model (they use no model by design) or with real sales lines in the sales history (only the empty "never sold" case is covered by an integration test).

## C8 close-out and handover (2026-10-10)

**Verified, this session, on a clean scratch Postgres as `metrion_app`:** full backend suite **4530 passed, 0 failed, 7 expected failures** (documented quantity-word gaps, Q13), run alone; `packages/calc-engine` 471, `packages/cfo` 320; frontend 139 vitest, `tsc`, `eslint`, production build clean; `mypy` clean on `backend/ceo`.

**Security review findings (both fixed, tested):** (1) a write could name another tenant's input as `supersedes_id`, creating a cross-tenant link and an existence oracle; now refused identically for a foreign and a missing id, and a supersede must match target and field. (2) A superseded input stayed ACTIVE (the table is append-only, "active" checked only `status`), so a new quote, budget or cost never replaced the old one; "active" now also excludes any row a later row supersedes. Both are in `manual_adjustment_repo.py` and affect every caller of the expense path. Tests: `test_ceo_form_write_isolation.py`. Reviewed without findings: the form-support reads (CEO + view + CFO keys, tenant from the session only, another tenant's data invisible), `action.inputs` (strict, competitor verified against the caller's tenant, no raw echo in errors), the answer for the two playbooks (fixed layout, no model call), React rendering of seller-entered text (escaped).

**Not done / open (stated, not hidden)**
- **C7 criteria evaluation is NOT run.** Two attempts were stopped (too slow; one was accidentally run twice). The owner's partner runs it. The runner now supports `--holdout-only` and `--per-metric 100` (the smallest run that can satisfy the criteria: 100 hold-out cases per metric). Until it runs, routing, missing-input, conflict handling and grounded answers are **unmeasured** against the 90% lower-bound criteria. The harness measures its own `classifier-v1` / `composer-v2` prompts, not the shipped `ceo-classifier-2` / `ceo-composer-3`. The safety gate (`test_ceo_safety_gate.py`) passed in the full run.
- Qwen3.5-4B (`qwen35-4b-q4`, hash verified) is registered but unmeasured.
- A signed-in browser run of the Hub (decision card, forms, conflict display) against the real backend is the owner's check.
- The new-product run is covered with the empty-history case in the database and with the status-preserving round trip in unit tests, not with real ingested sales lines.
- Open decisions unchanged: summary token-budget trigger; cross-worker SSE and cache need Redis (V1.1); quantity words in the numeral gate (Q13). `CEO_MAX_CANDIDATE_PRICES`, `CEO_LEG_TIMEOUT_SECONDS`, `CEO_PLAYBOOK_MAX_LEGS` must be set by the operator (no defaults); the price-impact run refuses without the first.
- Nothing is committed or pushed. `C:\ABDULS~1\` (two scratch scripts) awaits the owner's OK to delete.

## C9 the conversational Hub — state (2026-10-10)

**Owner direction:** one conversation, not a dashboard. Spec §6.34. **Built:**
- **Layout** (`CeoHubWorkspace`, `AgentStrip`, `Welcome`, `Composer`, `Conversation`): top strip with the CEO and every agent and their live state (ready / working with the action name / needs your input / off / locked / no access; click an agent to turn it on or off for the conversation); left work area with each agent's results and figures; right conversation window; chat bar always at the bottom with an attach button; conversations and "business at a glance" in a drawer; empty state offers what the CEO can do as tiles. Typing or clicking with no conversation open starts one. The Competitor Intelligence workspace was removed from this page (it still lives at `/dashboard/competitors`); the explicit date pickers are gone (a missing period is asked in the conversation).
- **Guided input** (`ceo/input_session.py`): the CEO asks for what a playbook needs one question at a time; every answer, typed or chosen, is parsed by code against the one question (no model, tested with an empty classifier); a bad answer re-asks with the reason and keeps the state; a bare zero cost must be confirmed on purpose; cancel stops with nothing run; the same validated inputs as the form are built at the end. Typed replies to an open question are detected by the backend, so the browser sends them like any message.
- **Attachments** (`investigation_attachment`, `services/ceo_attachments.py`, `POST /ceo/investigations/{id}/attachments`): type decided from the content (an executable named `.png` is refused), limits are configuration with no default (`CEO_ATTACHMENT_MAX_BYTES/FILES/PAGES`; unset refuses), stored tenant-scoped and append-only, bounded text extracted, reaches the composer only as delimited untrusted evidence and is shown to the seller as a labelled quote; a number or instruction inside a file is never a figure or an order (tested with an injection string). Foreign or other-conversation attachment ids are refused before anything is written.

**Verified:** backend unit 3813 passed; guided input 6, playbooks 17 (incl. real engine), attachments 7 + reader 19, isolation 3; frontend 148 vitest, `tsc`, `eslint`, production build clean; `mypy` clean on `backend/ceo` and the CEO API. Full backend suite: see the final report. A rendered look was checked with a temporary fake-data preview page (deleted). **Not verified:** the new Hub in a signed-in browser against the real backend (the owner's check); reading images; importing reports from chat; a download endpoint for attachments.

**Dev database:** migrations through `20261010_0010` were applied to the local development database; `backend/.env` (gitignored) carries local development CEO and attachment limits.

## C10 specialists from chat — slice 1, CMO (2026-10-10)

**Gap found (audit):** the CEO could answer general questions and run CFO reads, but sent PI discovery, CMO writing/trends and CI research to "use the agent's page"; there was no way for a specialist to ask the seller for inputs except the two decision playbooks; written content had no display path. No task table exists: the pending question is the open input card (`choices.pending.collected`), which survives reload and is tenant-scoped.

**Built (spec 6.35):** `ActionPlan.session`; sessions for the four CMO writers in `input_session.py` (with prefill from what the seller already said); `ResolvedSlots.direct`; idempotency key from the answering card; written content as `artefacts` in evidence, the fixed template and the finding snapshot; frontend artefact block and an "Open <page>" link on findings; classifier prompt `ceo-classifier-3`.

**Verified:** new `test_ceo_cmo_chat.py` 7 passed (ask-only-what-is-missing, all-in-one-message, bad answer, several marketplaces plus skip plus a failed artefact named, detached CMO, retry sends the same key, no second model call); CEO unit 3579 passed; CEO integration subset (turn, clarification, playbooks, guided input, chat actions, ui actions, presentation, attachments, hub actions) 189 passed; frontend 152 vitest, `tsc`, `eslint` clean. **Not verified:** a run with the real CMO generator and a live model through the signed-in Hub (the CMO handler is a recorder in these tests); the classifier choosing the CMO action on real phrasings (needs the evaluation harness, the partner's C7 work); the full backend suite after this slice.

**C10 slice 2 (2026-10-10):** after the owner's live transcript (business-name question met with "which area?", noise gaps, trending products unanswered) added the rules router, advisory fixes and PI discovery from chat (spec 6.35 addendum). Verified: new `test_ceo_pi_chat.py` 6 passed; CEO integration regression 218 passed after fixing two regressions (a "show my product research report" request was wrongly caught by the discovery rule; expected chat-action counts updated to PI 2, CMO 4). **Not verified:** a real Tavily/YouTube-backed PI run through chat; the model-written advisory wording on real questions (qwen3:8b, about 15 s per unrecognised message); CI research and CMO trends from chat still not built.

## C11 agent memory v1 (2026-10-10, spec `agent-memory.md`)
**Built:** migration `20261010_0011` (`agent_memory`, FORCE RLS, append-only, shared-memory gate as database CHECKs), `repositories/agent_memory_repo.py`, `ceo/memory.py` (deterministic capture of business name / niche / where the seller sells, promote-to-shared gate, forget, recall context without money, direct answer to "what is my business name"), CEO hooks (capture + same-answer acknowledgement, direct memory answers with no model, shared profile in the composer context), PI private notes of a confirmed research offered as choices next time, `GET /api/v1/ceo/memory` and `POST /api/v1/ceo/memory/{id}/forget`, Hub "What I remember" panel. Mechanism exists for all five agents; V1 populates the CEO (shared) and PI (private).
**Verified:** `test_ceo_memory.py` 15 passed (database gate, isolation, supersede, forget, capture through a real turn, no money in model context, HTTP edge); frontend 154 vitest, tsc, eslint clean. **Not verified:** real-model behaviour with memory in the prompt; CFO/CMO/CI private memory is not populated yet.

## C12 cross-agent flows from chat: C1-C8 (2026-10-10, specs 6.36-6.40, agent-memory addendum C6)

**Built and verified (each checkpoint was committed only after its tests passed):**
- **C1 PI to CFO** (6.36): "is #3 worth stocking?" asks the supplier quote and budget only when none is stored, shows a confirm card, saves through the CFO's own write path (`financials.adjust` + CFO entitlement) after "yes", then the real landed-cost / ranking / batch legs run. Cancel or no permission: nothing saved, nothing run. `services/ceo_inputs.py`.
- **C2 CFO data requests** (6.37): when a CFO leg returns an open data request the CEO can collect (cost per unit, supplier quote, batch budget) and nothing is stored, the answer ends with exactly that question, saves after confirm, closes the request and re-runs the same question. `ceo/data_requests.py`.
- **C3 CI to CFO** (6.38): "what is my margin at <competitor>'s price?" starts the price-impact conversation with the competitor (and a stated price) taken from the question; CI's last captured price is offered as one dated, "not verified" option, never filled in.
- **C4 CMO seeding** (6.39): the titles category-hint question offers PI's keyword themes for the idea and a tracked competitor's listing keywords, labelled "not verified", never filled in.
- **C5 market trends** (6.40): rule + one marketplace question, then the zero-cost preview is shown as a confirm card with the exact outbound searches; "yes" runs the report bound to the preview digest; cancel runs nothing; the report is shown quoted and labelled.
- **C6 private memory** (agent-memory.md section 11, built by a parallel agent and merged): CMO last marketplaces, CI last competitor, CFO last GST basis, offered first as "What you chose last time", never filled in, per-agent private, forgettable.
- **C7 Hub polish**: follow-up chips ("Write titles for #n", "Is #n worth stocking?") under a product-idea list, honest labelling of public-web content, "What I remember" grouped by who keeps it. Confirm cards use the existing decision-card component.
- **C8 regression and build:** CEO unit + integration **4100 passed, 0 failed, 7 expected failures** (scratch Postgres); frontend **158 vitest**, `tsc`, `eslint`, **production `next build` clean**.

**Not done / open (stated, not hidden):**
- PI feasibility shown as a labelled estimate in C1 (needs a PI read that relays estimates; 6.35 relays none today).
- C2 is tested end to end for the cost-per-unit case only; the quote and budget variants share the code but have no test of their own.
- C4 seeds titles only (description / keywords are grounded on the seller's own title); the competitor option is the first tracked competitor with an insight and may not match the product.
- C5: niche-term confirmation stays on the CMO page; the trend run is tested with a recording handler, not against the real search providers.
- C6: the hashtags question drops "Skip" from the list when a remembered value is offered (the seller can still type it); multi-marketplace memory is offered on the titles question only. Two tests were order-dependent in one agent run and passed alone (`test_ceo_api_b4` entitlement, `test_ceo_clarification` malformed reference); they passed in the final full run.
- No flow here was run with a real model or in a signed-in browser. The evaluation (partner's C7 run, the 60-80 case shipped-path suite, qwen35-4b-q4 vs qwen3:8b, the owner's manual check) is next and not started.

## C13 agent needs, shared findings and CEO business Q&A: S1, S2, S3, S5, S6a and a PI slice of S4 (2026-10-10; spec `agent-needs-and-shared-knowledge.md`)

**Built (committed on `feat/ceo-foundation`, not pushed):**
- **S1 needs broker:** `ceo/needs.py` catalog, `ceo_need` table (migration 0013, append-only), rule-routed add-on "the description along with the GST %": the CEO runs the CMO description, then the GST lookup (Route A/B by code) with the seller's own title as the only slot; refusals are named gaps; `CEO_NEEDS_MAX_PER_TURN` has no default.
- **S2:** the PI idea link (`LANDED_COST_FOR_IDEA`) and the competitor margin link (`MARGIN_AT_PRICE`) are catalogued and recorded when those flows run.
- **S3 shared findings ledger:** `shared_finding` (migration 0012; database CHECKs and trigger: no digits in agent text, ENGINE_VERIFIED needs same-tenant ENGINE_RESULT refs, seller-stated rows supersede and cite a message, forgotten sources are not re-recorded; append-only for the app role), `ceo/findings.py`, `GET /api/v1/ceo/findings`, `POST /api/v1/ceo/findings/{id}/forget`.
- **S4, PI only:** a PI research run with ideas is noted as one fixed-text AGENT_REPORTED finding (no number, no idea name) sourced to the stored run.
- **S5 CEO business Q&A:** nine question types in `ceo/question_types.py`, entries `BS_PNL_RECENT`, `BS_SELLER_FACTS`, `BS_CMO_CONTENT_LATEST`, `BS_SHARED_FINDINGS`, code-written "Not stored yet" sentences, `python -m backend.ceo_eval qa`.
- **S6a:** the Hub shows each follow-up lookup as a step (`GET /api/v1/ceo/investigations/{id}/needs`).
- **Defect found and fixed:** the app role could UPDATE/DELETE `agent_memory` despite the "append-only" claim (default privileges); migration 0014 and a test pin the fix; `ceo_need` revokes at creation.

**Deviations and gaps (stated):** add-ons are raised by the rules router only (no classifier enum); the add-on runs after the main leg and admission is per leg, not all-or-nothing; no reuse of an earlier GST result and no "this product" resolution; S4 writers for CFO, CI and CMO are not built; S6b (findings panel) and the correct endpoint (Q13) are not built; the canvas shows no need edges; the profit chip for BS_PNL is not in the chat actions and period choice is not supported in state reads; findings figures are shown as refs only; no real-model run of any of this and no signed-in browser run.
