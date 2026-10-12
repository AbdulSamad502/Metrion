# Phase 1 (engineering readiness) + Phase 2 (practical acceptance): consolidated report, 2026-10-12

Context: branch `feat/ceo-foundation`, HEAD `2b954c9`, **uncommitted** working tree (290 changed entries, 188 untracked), both stashes present. Nothing was committed, pushed, reset, cleaned or stashed. Companion documents: `docs/testing/pre-push-practical-test.md` (your checklist, with the final automated results), `docs/testing/acceptance-execution-report-2026-10-12.md` (every scenario's real status), `docs/planning/ceo-hardening-pi-final-report-2026-10-12.md`, `docs/design/frontend-excellence-report-2026-10-12.md`.

## Verdicts
- **Phase 1: PASS WITH LIMITATIONS.** Every automated suite passes on the final tree, including the full backend integration run started after the last code change. Limits: nothing real-provider (Tavily, YouTube, vision, public GST pages) and nothing real-Clerk was exercised; the hard leg deadline is unset by design; three product decisions are open (section 7).
- **Phase 2: PASS WITH LIMITATIONS.** 42 API scenarios and 12 UI scenarios were executed against the real app, real scratch database and real local Ollama with only Clerk simulated. 5 genuine defects were found and fixed with regression tests, no scenario ended FAIL, 3 scenarios are BLOCKED/NOT RUN for lack of credentials, providers or configuration. **You must still run the manual checklist with real sign-in before pushing.**

## Backend Integration Verification
- **Verdict: PASS.**
- **Command:** `pytest tests/integration -v -rsx --no-header -p no:cacheprovider` (cwd `backend`, environment from `bash backend/scripts/scratch_db.sh env`). **Exit code 0.**
- **Final full run (the one that counts):** started 07:01:52, finished 07:36:21, **1885 passed, 3 skipped, 1 xfailed, 3 warnings in 2066.47 s (34:26)**, on the final tree (after the Seller Goal validation fix, the PI migration fix and all frontend edits).
- **Earlier post-dispatch-fix run:** 05:38:03 to 06:19:22, 1866 passed, 3 skipped, 1 xfailed in 41:16, exit 0, after the last `dispatch.py` edit (mtime 00:12). The +19 tests in the final run are the new Seller Goal cases.
- **Database target (positively verified, not inferred):** both `DATABASE_URL` and `DATABASE_URL_APP` parse to `localhost:5544/metrion`; a connection through host port 5544 reported `pg_postmaster_start_time()` 2026-10-10 16:41:13, matching container `metrion-verify-pg` (started 16:41:10) and not `metrion-postgres-1` (development, 5432, started 15:23). The repository's `db_guard.py` also refuses 5432. The test chain re-checked both ports before each suite and would have aborted otherwise.
- **Unexpected failures: none** in the final run. History: a previous full run (1866) had been preceded by one failure in the first post-deadline run (`test_a_leg_that_finishes_after_its_row_was_settled_does_not_overwrite_it`), a real consequence of my dispatch change returning FAILED to the caller; fixed without touching the test; rerun green. One run I killed at 42% was not hung: concurrent vitest/tsc/browser load stretched the 700-turn test (documented in the runbook).
- **Skipped (3):** `test_accounting_cutover.py:105` and `test_ceo_turn_status_vocabulary.py:86` are opt-in `alembic downgrade/upgrade` tests (`METRION_ALLOW_DOWNGRADE_TESTS=1`, scratch only): **run separately: 11 passed**; residual risk: they were not part of the final full run. `test_frontend_request_samples.py:101`: "every field of this request is optional", a control that cannot apply to the seller-goal PUT; residual risk none.
- **xfailed (1):** `test_ceo_safety_gate.py::test_class3_known_gap_quantity_words_are_not_yet_caught`: spec Q13, quantity words ("doubled", "a third") are not caught by the numeral narration gate. 6 unit xfails in `test_ceo_gate_limits.py` are the same gap. Residual risk: a model-written sentence can state a relative change in words without a figure; money figures themselves still come only from the engine. This is a documented decision gap, not proof of safety.
- **Remaining integration coverage gaps:** real Clerk; real providers; real-model quality (all CEO integration tests use scripted or fake models); worker/queue behaviour is limited to what exists (there is no separate CEO worker or queue: turns run in the API process, the only background task is summary regeneration; recovery is covered by a real process-kill test).

## Other automated results (fresh, final tree)
Backend unit 4350 passed, 6 xfailed (exit 0). Packages: calc-engine 471 passed + 1 skipped (pandas absent: `test_reconcile_real_meesho_data`), data-foundation 135, competitor-intelligence 337, cfo 322 + 3 skipped (documented blockers T28/T35/T25), market-signals 14, product-intelligence 282, slim-cmo 2428; all exit 0. Frontend vitest `--maxWorkers=4` 65 files / 444 tests; `tsc --noEmit`, `eslint`, `next build` all exit 0. Migrations: CI-order round trip on a throwaway database inside the scratch container, 21 of 21 steps exit 0 (see "Defects fixed" for the one it caught). Full table with durations is in section 10 of the practical-test document.

## CEO readiness checkpoint (evidence per requirement)
| Requirement | Status | Evidence |
|---|---|---|
| Compound requests never silently drop an unsupported clause | Verified | `test_ceo_hardening_compound` (9), `test_ceo_compound`; acceptance B5, B6; UI U3 |
| Routing does not invent capabilities or present unsupported work as done | Verified | routing matrix (`test_ceo_campaign_routing_e2e`), B1-B4, B7b, UI answers |
| Approval-gated / forbidden actions blocked before execution | Verified | `test_ceo_approval_blocked_chat`, safety gate suite (700-turn hostile-classifier test), architecture guard; B2/B7 produced no leg; `ci.research_now` has zero runs and stays unwired |
| Idempotency consistent across API, orchestration, persistence | Verified | `test_ceo_client_request_id_api` (23), `test_ceo_hardening_idempotency`; C1-C3, C7; UI sends the id and a retry reuses it. There is no separate worker/queue boundary for turns |
| Interrupted operation never shown as exactly-once | Verified | real process kill C5: retry is `replayed:true`, FAILED, "interrupted and did not finish", `INTERRUPTED`, no second run |
| Uncertain effect not automatically repeated | Verified (automated) | recovery and deadline code never re-invoke; `test_ceo_leg_deadline` (20); replay returns the stored outcome |
| Abandoned and timed-out runs reach a defensible terminal state | Verified | `test_ceo_hardening_recovery` (incl. real death), `test_ceo_leg_deadline`; G6 (0 RUNNING left) |
| Late results cannot overwrite terminal outcomes | Verified (automated) | guarded writes; `finish_run` cannot overwrite `INTERRUPTED/TIMED_OUT`; tests incl. a race |
| Seller-facing distinction of success / partial / failure / uncertainty / unsupported | Verified, 4 UI defects fixed | Task status now: Completed, Partly completed, Failed, Needs an approved plan, Awaiting input, Running (incl. after refresh); out-of-scope and clarification answers |
| Prompt and tenant isolation | Verified | prompt-boundary tests; A3/A4/C7/D6 |
Open decisions: (1) show a late specialist result as a labelled "late result" (today it is not recorded after a timeout settle); (2) refuse a second submission of an effectful action while an earlier one is unresolved (today it is allowed); (3) the soft/hard deadline values (`CEO_LEG_TIMEOUT_SECONDS`=30 is set in `.env`; `CEO_LEG_ABANDON_SECONDS` stays unset: no real runtime data exists to justify a value); (4) approval workflow (11 gated actions stay refused); (5) memory: "forget" is an append-only `FORGOTTEN` row, **not erasure**; retention/erasure wording is an owner decision (spec memory Q).

> **Superseded in part by `docs/planning/stages-3-4-5-report-2026-10-12.md`** (issue 1 now pinned by a test, issue 6 evidence request, issue 24 inventory corrected to 79 sites, R5 resolved).

## Historical 24 functional issues (source `Metrion_24_Fixes.pdf`; dispositions from earlier work plus fresh evidence)
| # | Disposition | Evidence |
|---|---|---|
| 1 CFO import persistence | **Not reproduced as lost data; probable cause now demonstrated** | 100 rows commit and are visible to an independent connection (`test_cfo_import_persistence`). Fresh demonstration on scratch: the same query returns **4** rows as superuser, **0** as table owner `metrion_migrate` without tenant context, **0** as `metrion_app` without tenant context, **4** again with `app.current_tenant_id` set (FORCE RLS applies even to the owner). An inspection made without tenant context shows 0 rows. Unconfirmed for your dev database (not touched) |
| 2 Seller Goal | **Fixed (frontend earlier; backend validation now)** | acceptance E-CFO1: the API stored `"abc"`; now 422; UI verified end to end |
| 3 PI DRAFT -> READY | Fixed (frontend); backend correct | E-PI1/E-PI2 |
| 4 CI Refresh | Fixed | earlier browser check |
| 5 GST lookup failure | Fixed (503 plain when the model is unreachable) | with web blocked: 200 `noMatch`. Residual D4 below |
| 6 Leak Shield / reconciliation | **Not reproduced; root cause unconfirmed** | scratch returns 200 for an empty tenant and for imported rows; honest empty state. The failure on your instance is unexplained: needs the HTTP status, response body and backend log line (likely an entitlement 402/403 or an exception inside the run); not obtainable without the dev DB |
| 7 CFO Preview | Same as 6; 200 with structure | note D6 (zero vs unavailable) |
| 8 GST line analysis 422 | Fixed (client checks, named 422) | earlier |
| 9 CI vision extraction | Partly addressed; no real-model gain demonstrated | PI evaluation (candidate prompt rejected); `qwen2.5vl-manual` is not installed here |
| 10 availability event | Fixed | earlier browser check |
| 11 Compare vs Seller Product | Verified existing behaviour; message improved | E-CI2 |
| 12 PI discovery blocked | Unblocked by 3; providers unavailable here | E-PI3 honest PARTIAL |
| 13 PI recommendation | Intentionally unavailable | unchanged |
| 14, 15, 19 anomaly / fee / health config | Configuration blocker (decision) | health returns `unavailableReason` (E-CFO2); no seed utility |
| 16-18 supplier quotes, batch size | Data blocker | not retested without data |
| 20 duplicate dependency | Fixed | `test_signals.py` |
| 21 original CSV retrieval | Product decision, not done | needs a new endpoint |
| 22 rejected-row reasons | Fixed (persistence); policy gap: which identifiers each adapter requires | earlier |
| 23 per-line RTO/cancellation | Decision + schema, not done | |
| 24 generic errors | **Partly fixed; audit done, not closed** | below |
**Issue 24 audit (this pass):** frontend: 79 catch sites, no site renders a raw exception message; the large majority map through `friendlyApiError` / `failure` / `explainCmoError` (402/403/409/422/503 plain wording, connection failure distinct). Backend: 40 structured `{code,...}` details versus about 55 bare-string details (many `detail=str(exc)` carrying domain `ValueError` text; each reads as an actionable sentence but they were not individually audited for internals). Observed live: 401 `Not authenticated`, 404 `Not found`, 409/503 structured codes, 422 naming the field, 400 allowlist sentence, CMO 200 with `FAILED`+`CONFIG_MISSING`. **Gap:** bare strings cannot be classified (validation, missing data, configuration, dependency) by a program; one provider path (PI `partialReason`) returns raw OS text (`[WinError 10061] ...`). Closing it means converting those errors to structured codes: an API contract change that needs your approval.

## Defects found in these phases and fixed (all with regression tests)
| # | Defect | Severity | Fix and test |
|---|---|---|---|
| F1 | Seller Goal API accepted any text as `target_margin_pct` (quoted into the strategic-briefing prompt) | High (integrity, prompt surface) | ASCII percentage grammar in `api/v1/cfo.py`, 422; `test_cfo_seller_goal.py` +19 cases (incl. Arabic-Indic digits, injection text); real backend and UI re-verified |
| F2 | Hub showed Idle/Ready after a refresh while a turn was still running (question stored, no answer) | High (truthful status) | `isAwaitingAnswer` + 3 s re-read + "Answering your last question..." (`useCeoHub`, `ExecutionPanel`, `Conversation`); `ceoAwaiting.test.tsx`; browser re-verified |
| F3 | A refused concurrent send (409) turned the running task red/Failed | Medium | treated as a notice; test |
| F4 | `product-intelligence downgrade base` failed in the CI round-trip order (`relation "tenant" does not exist`), which would have failed the CI step | High (CI blocker) | tolerant probe in migration `20261011_0002`; `test_migration_downgrade_probe.py` (3); 21/21 round-trip steps now pass |
| F5 | Raw labels in Task status: "Qt leaks", "plan validated" | Low | 10 saved-results keys and 7 in-flight statuses labelled; tests |
(Earlier in this session and covered by Report A/B: dispatch late-result guard, deadline policy, `clientRequestId`, UI truthfulness fixes.)

## Prioritized open defects and blockers
| ID | Sev | Item | Evidence | Next action |
|---|---|---|---|---|
| D1 | High | CI workflow has never run (uncommitted); runner size unknown; `--maxWorkers=4` timed out on a 2-CPU pinned run | Report B section "CI worker setting" | decide repo visibility; use `--maxWorkers=2` on 2 vCPU; run it once on GitHub before relying on it |
| D2 | High (for real sellers) | Real Clerk sign-in/onboarding/expiry untested here | acceptance report | run section A/F of the checklist by hand |
| D3 | Medium | Deadlines unset; late-result display and second-effectful-submission policy undecided | section 7 | collect runtime data, then decide |
| D4 | Medium | GST lookup cannot distinguish "pages unreachable" from "no match" and reports the turn SUCCEEDED | B8/E-CFO4; spec 8.4.1 | spec decision: add fetched/failed counts, "could not reach sources" wording, PARTIAL outcome |
| D5 | Medium | Narration gate does not catch quantity words (xfail) | spec Q13 | owner decision on strictness |
| D6 | Medium | CFO `preview` on an empty tenant returns headline total 0 with an engine ref instead of UNAVAILABLE | E-CFO2 | belongs to the financial campaign |
| D7 | Medium | `CEO_MAX_CANDIDATE_PRICES` unset in `.env` (price-impact playbook refuses) | B4b | set it (owner value; 5 suggested) |
| D8 | Medium | CMO generation/trends untestable: unseeded platform config, no providers | E-CMO1/E-CMO3 | provide config and provider keys, or accept as not covered |
| D9 | Low | Bare-string API errors; raw OS text in PI `partialReason` | issue 24 audit | structured errors (needs approval) |
| D10 | Low | No unauthenticated health endpoint | section 1 of the checklist | optional |
| D11 | Info | `qwen2.5vl-manual` vision model not installed; calc-engine real-Meesho test skipped (pandas not installed) | env | install if those paths matter |

## What was tested with what
- **Automated, fake/scripted models:** all pytest suites and vitest (they prove logic and contracts, not live-model quality or real providers).
- **Real local backend + real scratch DB + real Ollama, simulated Clerk:** the 42 API scenarios; including a **real process kill**.
- **Browser (real production frontend build -> real backend):** U1-U11 as listed; no signed-in Clerk validation (backend ignored the token). Earlier demo-harness pages (in-memory fake backend, deleted) were used only for visual checks and are labelled in Report B.
- **Not tested:** real Clerk, Tavily/YouTube/Google Places, public GST page fetch success, vision extraction, CMO generation, populated CFO imports, screen reader, manual keyboard walkthrough.

## Git and database safety
Branch `feat/ceo-foundation`, HEAD `2b954c9` (the reflog's last entry is an earlier fast-forward pull, not part of this work); no commit or push. Both stashes present (`stash@{0}` "backup before pulling 2b954c9", `stash@{1}` "WIP on main: 49f65c8 Half CI Completed"). 290 changed entries (188 untracked), all pre-existing user work preserved; the temporary demo harness (my own files) was deleted earlier. Files touched in this final task: `backend/src/backend/api/v1/cfo.py`, `backend/tests/integration/test_cfo_seller_goal.py`, `packages/product-intelligence/migrations/versions/20261011_0002_pi_run_accounting.py`, `packages/product-intelligence/tests/unit/test_migration_downgrade_probe.py`, frontend `CeoHubWorkspace.tsx`, `Conversation.tsx`, `ExecutionPanel.tsx`, `lib/ceoModel.ts`, `lib/useCeoHub.ts` and their tests, plus three documents under `docs/testing` and `docs/planning`. Development PostgreSQL (5432): never targeted (all database commands used host port 5544; the development frontend returned 200 and the development backend 401 before and after; the acceptance servers on 3100/8001 are stopped). A throwaway database `metrion_roundtrip` inside the scratch container was created and dropped. No paid model call, no external request (providers blank, outbound blocked), no email, no commit.

## Recommended next action
Run the manual checklist (`docs/testing/pre-push-practical-test.md`) with real Clerk sign-in on the scratch stack, deciding first on `CEO_MAX_CANDIDATE_PRICES`, the vision model and whether to allow Tavily/YouTube. Decide D1 (CI runner) before the first push. Treat D3, D4 and D5 as the next engineering decisions.
