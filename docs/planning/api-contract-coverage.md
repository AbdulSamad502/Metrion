# API contract coverage: the 59 frontend paths

Written 2026-10-11. Companion to [frontend-backend-integration-matrix.md](frontend-backend-integration-matrix.md). That document says which capabilities are connected; this one says, per path the frontend calls, **what is actually checked** and where the checks live. It separates six statuses and does not merge them.

## The six statuses and the check behind each

| Status | The check | Where | What it cannot prove |
|---|---|---|---|
| **Route exists** | Every path the frontend builds (59 distinct, found by scanning its sources and resolving its `BASE` prefixes) is in the backend's OpenAPI paths. | `backend/tests/unit/test_frontend_api_paths_exist.py` | Method, body, response. |
| **Request compatible** | (1) Every request any frontend test sends through a stubbed `fetch` is validated against the backend's request schema: route + method served, JSON body field names, types, enums/patterns, required fields, no unknown fields, query parameters declared and required ones present. A violation rejects the request and fails the test. (2) Both typed clients (`lib/ceo.ts`, `lib/cmo.ts`) are called method by method under that guard. (3) A static pass over every inline `apiFetch(..., JSON.stringify({...}))` checks field names and required fields, including for calls no test reaches. | `frontend/test-support/setup.ts`, `requestContract.ts` (generated from the backend by `backend/scripts/export_request_contract.py`; `backend/tests/unit/test_request_contract_snapshot.py` fails if it is stale), `lib/clientContract.test.ts`, `test-support/requestShapes.static.test.ts` | Values that a component computes at run time, for the 28 paths in the table marked *static*. The seven constrained value fields among them (`decision`, `basis` x2, `recognition_state`, three `*_target_type`) were reviewed by hand against the component's typed options. |
| **Response compatible** | The fields each screen reads are taken from the frontend's own TypeScript types into `responseContracts.json` (a frontend test fails when it drifts); a backend integration test calls the real endpoints, seeded so every list has items, and fails when a real response lacks a field. 26 responses are covered, including the whole conversation payload and the Profit & Finance calculators. The real turn and detail payloads are also captured and rendered by the Hub in a frontend test. | `frontend/test-support/responseContracts.test.ts`, `backend/tests/integration/test_frontend_response_contracts.py`, `test_ceo_http_end_to_end.py`, `components/ceo/hub/ceoRealPayload.test.tsx` | Fields outside the 13; extra fields; value formats beyond type. |
| **Authentication and authorisation** | Per router: `require_auth(permission=...)` on every route (read from the code); the 401 / 403 / tenant-isolation behaviour is asserted in backend integration tests. | existing suites, plus `test_cfo_cash_reconciliation_contract.py`, `test_ci_evidence_research_contract.py`, `test_ceo_http_end_to_end.py` | The column below is a file-level heuristic (a test file that names the route and asserts both 401 and 403), not a per-route proof. |
| **Error handling** | Every component that calls the API maps a failure to plain words (`friendlyApiError` or the CMO equivalent); never raw JSON. The CEO client and the notifications hook handle errors at the hook level. | `lib/apiErrors.ts` and its tests; each component's own tests | Wording quality. |
| **Automated test coverage** | See the last two columns. | | |

## Per path

Legend: *Request: checked at runtime* = some frontend test sends this route's request through the guard. *names + required (static)* = the inline body was checked by the static pass only.

| Path | Method | Frontend caller | Route served | Request: checked at runtime in a frontend test | Request: how checked | Response contract | 401/403 in a backend test file for the route | Backend tests touching the route |
|---|---|---|---|---|---|---|---|---|
| `/ceo-hub/agents` | GET | lib/agents.ts | ✔ | ✔ | names + values (runtime) | ✔ | test_ci_api.py | 2 |
| `/ceo/agents/availability` | GET | lib/agents.ts | ✔ | ✔ | names + values (runtime) | — | test_ceo_api_b4.py | 1 |
| `/ceo/findings` | GET | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | ✔ | test_ceo_findings.py | 2 |
| `/ceo/findings/{}/forget` | POST | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | — | test_ceo_findings.py | 1 |
| `/ceo/forms/new-product` | GET | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | — | test_ceo_decision_forms_api.py | 1 |
| `/ceo/forms/price-impact` | GET | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | — | test_ceo_decision_forms_api.py | 1 |
| `/ceo/investigations` | GET/POST | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | ✔ | test_ceo_api.py, test_ceo_api_b4.py | 12 |
| `/ceo/investigations/{}` | GET | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | ✔ | test_ceo_api.py, test_ceo_api_b4.py | 12 |
| `/ceo/investigations/{}/agents/{}` | PUT | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | — | test_ceo_api_b4.py | 1 |
| `/ceo/investigations/{}/archive` | POST | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | — | test_ceo_api_b4.py | 2 |
| `/ceo/investigations/{}/attachments` | POST | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | — | — | 1 |
| `/ceo/investigations/{}/findings` | GET | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | — | test_ceo_api.py, test_ceo_api_b4.py | 4 |
| `/ceo/investigations/{}/needs` | GET | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | — | — | 1 |
| `/ceo/investigations/{}/reopen` | POST | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | — | test_ceo_api_b4.py | 1 |
| `/ceo/investigations/{}/resolve` | POST | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | — | test_ceo_api.py, test_ceo_api_b4.py | 2 |
| `/ceo/investigations/{}/turns` | POST | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | ✔ | test_ceo_api.py, test_ceo_api_b4.py | 11 |
| `/ceo/investigations/{}/turns/{}/flow` | GET | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | — | — | 1 |
| `/ceo/memory` | GET | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | ✔ | test_ceo_memory.py | 2 |
| `/ceo/memory/{}/forget` | POST | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | — | test_ceo_memory.py | 1 |
| `/ceo/state/health` | GET | lib/ceo.ts | ✔ | ✔ | names + values (runtime) | ✔ | — | 2 |
| `/cfo/anomaly-check` | POST | components/cfo/sections/ReportingSections.tsx | ✔ | — | names + required (static) | — | — | 3 |
| `/cfo/batch-size` | POST | components/cfo/sections/PricingSections.tsx | ✔ | — | names + required (static) | — | — | 0 |
| `/cfo/cash-reconciliation` | POST | components/cfo/sections/ReportingSections.tsx | ✔ | ✔ | names + values (runtime) | ✔ | test_cfo_cash_reconciliation_contract.py | 4 |
| `/cfo/data-requests` | GET | app/dashboard/cfo/page.tsx | ✔ | ✔ | names + values (runtime) | ✔ | — | 1 |
| `/cfo/expenses` | GET/PUT | components/cfo/sections/ExpenseTrackerSection.tsx | ✔ | ✔ | names + values (runtime) | — | — | 1 |
| `/cfo/expenses/budget` | PUT | components/cfo/sections/ExpenseTrackerSection.tsx | ✔ | — | names + required (static) | — | — | 0 |
| `/cfo/expenses/budget-status` | GET | components/cfo/sections/ExpenseTrackerSection.tsx | ✔ | — | n/a (no body) | — | — | 0 |
| `/cfo/financial-health` | POST | components/cfo/sections/ImportAndGoalSections.tsx | ✔ | — | names + required (static) | — | — | 0 |
| `/cfo/funding-readiness` | POST | components/cfo/sections/PricingSections.tsx | ✔ | — | names + required (static) | — | — | 1 |
| `/cfo/gst-lookup` | POST | components/cfo/sections/GstSections.tsx | ✔ | — | names + required (static) | — | — | 3 |
| `/cfo/gst-lookup/accept` | POST | components/cfo/sections/GstSections.tsx | ✔ | — | names + required (static) | — | — | 2 |
| `/cfo/gst/analyze-lines` | POST | components/cfo/sections/GstSections.tsx | ✔ | — | names + required (static) | — | — | 0 |
| `/cfo/gst/period-summary` | POST | components/cfo/sections/GstSections.tsx | ✔ | — | names + required (static) | — | — | 0 |
| `/cfo/imports` | GET | components/cfo/ImportHistory.tsx | ✔ | ✔ | names + values (runtime) | — | test_cfo_imports.py | 1 |
| `/cfo/imports/{}` | GET | components/cfo/ImportViewer.tsx | ✔ | — | n/a (no body) | — | test_cfo_imports.py | 1 |
| `/cfo/landed-cost` | POST | components/cfo/sections/PricingSections.tsx | ✔ | — | names + required (static) | — | — | 0 |
| `/cfo/period-comparison` | POST | components/cfo/sections/ReportingSections.tsx | ✔ | — | names + required (static) | — | — | 0 |
| `/cfo/pnl` | POST | components/cfo/sections/PeriodPnlSection.tsx | ✔ | — | names + required (static) | — | — | 1 |
| `/cfo/preview` | POST | components/cfo/sections/ReportingSections.tsx | ✔ | — | names + required (static) | — | — | 2 |
| `/cfo/pricing` | POST | components/cfo/sections/PricingSections.tsx | ✔ | — | names + required (static) | — | — | 0 |
| `/cfo/reconcile` | POST | components/cfo/sections/ReportingSections.tsx | ✔ | — | names + required (static) | — | — | 2 |
| `/cfo/seller-goal` | GET/PUT | components/cfo/sections/ImportAndGoalSections.tsx | ✔ | — | names + required (static) | — | — | 0 |
| `/cfo/strategic-briefing` | POST | components/cfo/sections/ImportAndGoalSections.tsx | ✔ | — | names + required (static) | — | — | 1 |
| `/cfo/suppliers/rank` | POST | components/cfo/sections/PricingSections.tsx | ✔ | — | names + required (static) | — | — | 0 |
| `/ci/alerts` | GET | lib/useNotifications.ts | ✔ | ✔ | names + values (runtime) | ✔ | — | 3 |
| `/ci/competitor-urls` | GET/POST | components/ci/CompetitorWorkspace.tsx | ✔ | ✔ | names + values (runtime) | — | test_ci_api.py, test_ci_evidence_research_contract.py | 7 |
| `/ci/competitor-urls/{}/comparison` | GET | components/ci/CompetitorWorkspace.tsx | ✔ | — | n/a (no body) | — | — | 1 |
| `/ci/digest/subscription` | GET/PUT | app/settings/page.tsx | ✔ | ✔ | names + values (runtime) | ✔ | test_ci_api.py | 2 |
| `/ci/discovery-runs` | POST | components/ci/CompetitorWorkspace.tsx | ✔ | — | names + required (static) | — | — | 1 |
| `/ci/discovery-runs/{}` | GET | components/ci/CompetitorWorkspace.tsx | ✔ | — | n/a (no body) | — | — | 1 |
| `/ci/discovery-runs/{}/candidates/{}/decision` | POST | components/ci/CompetitorWorkspace.tsx | ✔ | — | names + required (static) | — | — | 1 |
| `/ci/discovery-runs/{}/candidates/{}/promote` | POST | components/ci/CompetitorWorkspace.tsx | ✔ | — | names + required (static) | — | — | 1 |
| `/ci/seller-products/{}` | GET/PUT | components/ci/CompetitorWorkspace.tsx | ✔ | — | names + required (static) | — | — | 3 |
| `/ci/summary` | GET | lib/useCiSummary.ts | ✔ | ✔ | names + values (runtime) | ✔ | test_ci_api.py | 2 |
| `/cmo/images` | POST | lib/cmo.ts | ✔ | ✔ | names + values (runtime) | — | test_cmo_images_api.py | 2 |
| `/onboarding/business` | POST | app/(marketing)/onboarding/page.tsx | ✔ | — | names + required (static) | — | — | 0 |
| `/pi/report/{}` | GET | app/dashboard/pi/page.tsx | ✔ | ✔ | names + values (runtime) | — | — | 1 |
| `/pi/supplier-lookup` | POST | app/dashboard/pi/page.tsx | ✔ | — | names + required (static) | — | — | 2 |
| `/session` | GET | lib/useAppSession.ts | ✔ | ✔ | names + values (runtime) | ✔ | — | 1 |

## What this pass found

None of the checks found a frontend request the backend would refuse: every frontend test request, both typed clients called method by method, and 33 of 36 inline `apiFetch` bodies (the other three are built from runtime pieces and are covered at runtime) pass. The checks did find these, which are not request-shape problems:

| Finding | Kind | Status |
|---|---|---|
| `POST /cfo/cash-reconciliation` returned an `engineResultRef` for every figure, but computed the results in memory and never stored them. The reference could not be resolved by the screen, an audit or the CEO's provenance gate, so a figure the CEO cited from it would be dropped. Found because the new test looks the reference up. | Code defect (backend) | **Fixed**: `assemble_cash_reconciliation` now stores the five results with `metric_result_repo.save_many`, as every other CFO composition does. No schema change; the response is unchanged. |
| The Agents page and the Overview marked Product Intelligence and the CFO as "Own page only" although the CEO registry has wired chat actions for both. The fixed roster at `GET /ceo-hub/agents` is stale and the screens trusted it. | Code defect (frontend) | **Fixed**: the roster is combined with the real `GET /ceo/agents/availability` (permission, plan, wired chat actions). Verified live: all four agents now read "Works with Ask Metrion". |
| Three CEO routes (`GET /ceo/findings`, `POST /ceo/findings/{id}/forget`, `GET /ceo/forms/price-impact`) resolved the CEO runtime before authenticating, so a caller with no session got `503 CEO_NOT_CONFIGURED` instead of `401` whenever the runtime was not configured. | Code defect (backend, minor) | **Fixed**: the authentication parameter now comes first. Found by the new all-routes authentication test. |
| `POST /ci/evidence` accepts any file type; it checks size only. The stored name keeps the client's extension. It is never served back, and the research step reads it through a path check that stays inside the evidence directory. | Observation | Not changed. Whether to check content type is a product decision (see `ci.research_now`). |
| The evidence directory is one flat folder with no tenant recorded against a reference. A reference is a random UUID, so another tenant's file cannot be guessed, but nothing in the store ties a reference to the tenant that uploaded it. | Observation | Not changed. Needs a design decision (see `ci.research_now`). |
| Forgetting an item under "What I remember" is immediate, with no confirmation, unlike forgetting a reported finding (which asks first). Existing behaviour, with its own test. | Product decision | Left as is. |
| 12 of the 59 paths have no backend test file that names them (the CFO calculators, expense budget, seller goal, onboarding). Their authentication is now covered generically (below); their request and response behaviour is covered by the engine's own suites, not over HTTP. | Coverage gap | Listed; not padded with copies of the same test. |

## Shared tests that cover every route

- `backend/tests/unit/test_every_route_requires_auth.py`: all 110 non-public `/api/v1` routes answer 401 to a request with no session and to a bad token, before the body is read. Public routes are an explicit, reasoned list (`/ping`, `/ceo-hub/agents`).
- `backend/tests/integration/test_every_route_permission.py`: 101 routes answer 403 to a real member who holds none (scratch database). Nine are exempt, each with its reason in the test: `GET /session` and `POST /onboarding/business` (a session, not a permission), and the seven PI niche-brief routes, which the PI spec (6.1) makes a plain tenant write with no agent key. Found by running it: those seven answered 200 to a member with no permissions, which is the specified behaviour.


## Upgraded from static to behavioural (final verification pass)

Of the 28 paths that relied on the static name check, 16 are now behavioural. Chosen by risk: financial calculations and reconciliation first, then writes that store seller data, then the one write that creates a workspace.

**How.** `frontend/components/cfo/requestSamples.test.tsx` fills each Profit & Finance form the way a seller would and submits it. The request the component really builds is validated against the backend schema, values included, and recorded in `frontend/test-support/fixtures/requestSamples.json` (16 requests; the file is rewritten with `CAPTURE_REQUEST_SAMPLES=1`, and the test fails if a form's request no longer has the recorded shape). `backend/tests/integration/test_frontend_request_samples.py` posts each recorded body, unchanged, to the real route on the scratch Postgres with a real owner membership and asserts: never 422, never a server error, the response has every field the screen reads (26 response shapes in `responseContracts.json`), and, as a control, the same body with one required field removed **is** refused with 422. Calls that reach a narration step use a fake provider; no test calls a model (a first draft of one test did reach the local Ollama host and timed out; it was changed before anything else ran).

| Path | Why it merited more than a name check | What is now proved |
|---|---|---|
| `POST /cfo/reconcile`, `preview`, `anomaly-check` | Leak and anomaly findings the seller acts on | form body accepted; response fields read; required-field control |
| `POST /cfo/period-comparison` | Compares two stored results; the only route here that takes engine result ids from the client | accepted; with real stored results answers 200 in the shape read; another tenant's result is never reflected back |
| `POST /cfo/pnl` | Contribution profit | accepted (single-line calculator, as labelled); response fields read |
| `POST /cfo/pricing` | Margin per candidate price; takes explicit cost answers where "unknown" must stay unavailable | the form's explicit-cost body (`None (0), I confirm` sends 0, not blank) accepted; response read |
| `POST /cfo/landed-cost`, `suppliers/rank`, `batch-size`, `funding-readiness` | Purchasing and funding decisions | accepted; response fields read; control |
| `POST /cfo/financial-health`, `strategic-briefing` | Bands and the briefing the CEO also cites | accepted; narration off as the form sends it |
| `PUT /cfo/expenses`, `PUT /cfo/expenses/budget`, `PUT /cfo/seller-goal`, `GET /cfo/expenses/budget-status` | Writes that store seller figures | stored, read back as sent in paise, not visible to tenant B, saving again is accepted; the status query is validated and its required parameter is enforced |
| `POST /onboarding/business` | Creates a workspace (needs Clerk, faked) | `test_onboarding_http.py`: a verified seller gets a workspace under the name given and the two fields the page reads; invalid names are 422 before anything is created; no session is 401; an existing member is 409 and no second organisation is made |

**Still statically checked (12), and why.**

| Paths | Reason left |
|---|---|
| `POST /cfo/gst/analyze-lines`, `/gst/period-summary` | Caller-assembled lines (a calculator, no stored seller data); names, required fields and the `basis` enum were checked. Lower risk than the above. |
| `POST /cfo/gst-lookup`, `/gst-lookup/accept` | The lookup fetches the public web (allow-listed hosts) and `accept` needs a lookup result to accept; a behavioural test needs either a live fetch or a fixture of the lookup service, which is its own piece of work. |
| `GET/PUT /ci/seller-products/{id}`, `POST/GET /ci/discovery-runs…` (4 paths), `GET /ci/competitor-urls/{id}/comparison` | The Competitors workspace is one very large component; discovery runs fetch competitor pages. Their request bodies are small and were name-checked; backend suites cover the routes. |
| `POST /pi/supplier-lookup` | External supplier search. |
| `GET /cfo/imports/{id}` | Read of a stored import; no body. |

None of the 12 moves money or writes seller figures except `gst-lookup/accept` (stores an accepted rate) and `PUT /ci/seller-products/{id}` (stores a product profile).

## Regression tests for the defects fixed earlier

| Defect | Regression test | Layer |
|---|---|---|
| Cash reconciliation results were never stored, so `engineResultRef` could not be resolved | `test_cfo_cash_reconciliation_contract::test_asking_again_gives_the_same_figure_and_does_not_double_count` (looks the reference up in `metric_result`) | backend, scratch Postgres |
| CEO routes resolved the runtime before authenticating (503 instead of 401) | `test_every_route_requires_auth` (all routes, no database) | backend unit |
| PI and CFO shown as "Own page only" from a stale roster | `lib/agents.test.tsx` (merge rules and the hook's two requests) and the live check on the Agents page | frontend |
| Evidence-directory fixture depended on test order | `test_ci_evidence_research_contract` (fixture clears the cached setting before and after); passes inside the full run, where it failed before | backend |
| Shared findings: load, confirm before forgetting, persistence, refresh | `components/ceo/hub/ceoSharedFindings.test.tsx`; `test_ceo_findings` (HTTP 401/403/404, persistence, second forget 404); `test_frontend_response_contracts` (real response has the fields read) | both |
| Conversation persistence and restoration | `test_ceo_http_end_to_end` (fresh read equals the turn), `ceoRealPayload.test.tsx` (the real payload reopened as a refresh does, one read) | both |
| Frontend routes and request shapes | `test_frontend_api_paths_exist`, `test_request_contract_snapshot`, the guard in `test-support/setup.ts`, `requestShapes.static.test.ts` | both |
