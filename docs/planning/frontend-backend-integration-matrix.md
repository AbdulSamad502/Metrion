# Frontend ↔ backend integration matrix

Written 2026-10-11 from the code as it stands (not from the specs' intentions). "Connected" means the frontend calls a path the backend serves; the **Evidence** column says how far each connection was actually proven. Nothing here is marked verified on the strength of a component existing.

## How each connection was checked

| Level | Meaning | How |
|---|---|---|
| **LIVE** | Browser → real running backend → real database, response accepted by the screen | Page loaded in the signed-in browser against `127.0.0.1:8000`; every request status read from the browser's resource timing (all 200). Read-only: no data was created in the development tenant. |
| **PATH** | The path the screen calls is a route the backend serves | `backend/tests/unit/test_frontend_api_paths_exist.py` (new): 59 distinct paths the frontend calls, checked against the app's OpenAPI document. Static: it does not check request bodies. |
| **MOCK** | The screen's behaviour against a faked API | Frontend vitest suites (338 tests). They prove the screen, not the backend. |
| **DB** | The backend handler, against a real Postgres | Backend integration suites on the scratch database (port 5544). See the result section. |

A capability is called *integrated* only where the screen, the path and the backend handler are each covered. LIVE is added for the read paths a page makes on load.

## Frontend routes

| Route | Backend it calls | Auth | Status |
|---|---|---|---|
| `/dashboard` (Overview) | `GET /session`, `/ci/summary`, `/ci/alerts`, `/cfo/data-requests`, `/ceo/state/health`, `/ceo-hub/agents` | signed in; per-router agent permission | Connected. LIVE (all 200) + PATH + MOCK. |
| `/dashboard/ceo-hub` (Ask Metrion) | `/ceo/investigations` (create, list, get, turns, attachments, resolve, archive, reopen, events stream, needs, findings, turn flow, agent attach), `/ceo/memory`, `/ceo/findings` (**new**), `/ceo/state/health`, `/ceo/agents/availability`, `/ceo/forms/*`, `/cfo/expenses` (form save) | `agent.ceo`, `investigation.*` | Connected. LIVE for the page-load reads (all 200). Turns, streaming and attachments are PATH + MOCK + DB; **no live conversation was run**, because that creates data in the development tenant and calls the local model. |
| `/dashboard/pi` (Products) | `/pi/niche-briefs` (CRUD, mark-ready/draft, archive), `/pi/discover`, `/pi/supplier-lookup`, `/pi/report/{run}` | `agent.pi` | Connected. LIVE for the page load (alerts, data requests). Actions: PATH + MOCK + DB. "Final Recommendation" is intentionally not produced here; it now points to the new-product form in Ask Metrion. |
| `/dashboard/competitors` | `/ci/competitor-urls` (+ snapshots, price events, listing diff, handoff, comparison, price scenario), `/ci/evidence`, `/ci/seller-products/{id}`, `/ci/discovery-runs` (+ decision, promote), `/ci/market-overview/{id}`, `/ci/digest/preview`, `/ceo-hub/research-now`, `/ceo-hub/runs/{id}` | `agent.ci` | Connected. LIVE for `competitor-urls` (200). Rest: PATH + MOCK + DB. |
| `/dashboard/cfo` (Profit & Finance) | 27 of the 31 `/cfo/*` routes (the rest are listed below) | `agent.cfo`; writes also `financials.adjust` | Connected, with the gaps listed below. LIVE for the page load. New: cash reconciliation. |
| `/dashboard/cmo` (Listings & Marketing) | `/cmo/title-sets`, `listing-copy`, `hashtags`, `catalog-answers`, `title-approvals`, `images`, `image-analyses`, `image-hints/confirm`, `niche-terms/*`, `market-trends*`, `GET /session` | `agent.cmo` (+ `research.*`, `catalog.view`) | Connected. LIVE for the page load. Actions: PATH + MOCK + DB. |
| `/dashboard/agents` | `GET /ceo-hub/agents`, `/ci/summary` | signed in | Connected. LIVE (all 200). The agent list shows what the backend reports; nothing is inferred. |
| `/dashboard/notifications` (Action Center) | `GET /ci/alerts?days=14`, `GET /cfo/data-requests` | `agent.ci`, `agent.cfo` | Connected. LIVE (200). It lists only these two sources and says so; there is no read/unread state in the backend. |
| `/settings` | `GET /session`, `GET/PUT /ci/digest/subscription`; sign-in methods via Clerk | signed in; `agent.ci` | Connected. LIVE for the page load. Business-profile editing, email/WhatsApp delivery and marketplace connections have no backend and are shown as unavailable. |
| `/onboarding` | `GET /session`, `POST /onboarding/business` | signed in, before a workspace exists | Connected. PATH + MOCK + DB. |

## Backend endpoints with no frontend caller

At the start of this pass 14 of the 112 backend routes had no frontend caller (a first scan counted `GET /ceo/findings` as called because the string appears in `/investigations/{id}/findings`; it was not). Two now have one; twelve do not.

| Endpoint | What it is | Decision |
|---|---|---|
| `POST /ceo/findings/{id}/forget` and `GET /ceo/findings` | The shared findings ledger: what agents reported, with trust labels. Spec: `agent-needs-and-shared-knowledge.md` 6.3, S6b. | **Built.** "What the agents have reported" panel in the Hub, with the backend's trust wording, hidden-agent counts and a confirmed Forget. LIVE: `GET /ceo/findings` 200, empty state shown (the tenant has none). |
| `POST /cfo/cash-reconciliation` | Cash received from settlement rows; expected cash, variance and TDS come back unavailable. | **Built.** Section on the Cash tab of Profit & Finance. Unavailable figures are shown as unavailable with the backend's reason. |
| `POST /cfo/pnl-for-tenant` | Profit and loss from the seller's stored rows. | **Not built. Blocked on a decision.** The request needs four component-code classification sets (fees, forward/reverse logistics, non-refunded fees) that the spec says are "genuine tenant/business classifications this composition does not guess" (`cfo-agent.md` 6.16). Nothing in the product tells a seller which codes exist or how to classify them. Filling them in by default would change profit figures. The existing "Period P&L (quick single-line)" stays a labelled manual calculator. |
| `PUT/GET /cfo/line-status-override`, `PUT /cfo/line-count-override` | Seller declares cancelled/returned/RTO status or counts for one order line. | **Not built. Blocked.** Needs a `sales_line_id`; no screen shows a seller their order lines or ids, and data requests carry none. Requires a line-level view first. |
| `POST /ci/review-research` | Reviews-tab screenshot → insight (local vision model). | **Not built. Blocked.** The backend writes the insight but exposes no route that reads it back, so a screen could only show "submitted". |
| `POST /cmo/description`, `bullets`, `keywords`, `backend-terms` | Single-piece generators. | **Connected** (corrected): `lib/cmo.ts` builds the path as `/${kind}` (`cmo.component`, used by `StandaloneTab`), which the first text scan could not see. The contract tests now call all four. |
| `POST /ceo-hub/discover-competitors`, `/request-price-scenario` | CEO-hub fixed actions. | **Not built.** The screens use the direct routes (`/ci/discovery-runs`, `.../price-scenario`), which call the same service. |
| `GET /ping` | Liveness. | Not a seller feature. |

## Registered agents (derived from `backend/src/backend/ceo/registry.py`)

Four agents and one shared service. 36 registered actions; 35 wired, 1 unwired.

| Agent | Actions in the CEO registry | Direct pages |
|---|---|---|
| **CFO** | `pnl_for_tenant`, `pricing`, `gst_summary`, `period_comparison`, `landed_cost`, `supplier_ranking`, `funding_readiness`, `batch_size`, `reconcile`, `anomaly_check`, `financial_health`, `cash_reconciliation`, `strategic_briefing`, `preview`, `gst_lookup` (15) | `/dashboard/cfo` |
| **CMO** | `generate_title_sets`, `approve_title`, `generate_listing_copy`, `generate_description`, `generate_bullets`, `generate_keywords`, `generate_backend_terms`, `generate_hashtags`, `catalog_answer`, `confirm_image_hint`, `suggest_niche_terms`, `confirm_niche_terms`, `market_trends_preview`, `market_trends` (14) | `/dashboard/cmo` |
| **PI** | `discover`, `supplier_lookup`, `report` (3) | `/dashboard/pi` |
| **CI** | `request_price_scenario`, `discover_competitors` wired; **`research_now` not wired** (needs a chat evidence-upload surface, spec Q8, unresolved) (3) | `/dashboard/competitors` |
| **Shared GST lookup** (no agent) | `service.gst_lookup` | via CFO and CMO |

Write-class and free-form actions are excluded from the CEO by decision (`FORBIDDEN_ACTION_KEYS`, spec C21): expense entry, goal, GST accept, ingest, competitor URL create/update, evidence upload, digest subscription, niche brief create/update, image upload, line overrides. They stay on the agents' own pages, which is where the frontend puts them.

The CEO reaches a specialist only through this registry; the frontend never calls a specialist on the CEO's behalf. Specialist results reach the screen as findings on the turn, then as the trust-labelled shared findings (new panel).

## Not verified here

- No live CEO turn was run (it would create data in the development tenant and call the local model). The turn lifecycle (classify → route → run → compose → persist → stream) is covered by the backend integration suites on the scratch database and the frontend's mocked tests, not by a live run.
- Request *bodies* are not checked against backend schemas by the new path test; the backend suites and the frontend's mocked tests each check their own side.
- Mutations on the live development tenant were not exercised.

---

# Integration hardening pass (2026-10-11)

## CEO orchestration, stage by stage

The whole path is exercised by a **deterministic integration test**: only Clerk and the two model handles (classifier, composer) are scripted; the HTTP edge, auth chain, membership grid, tenant context, RLS, orchestrator, registry/choke point, the real CFO handlers, repositories and Postgres are real. It is not a live local-model test and does not claim to be.

| Stage | Proved by (backend, scratch Postgres) | Seen by the frontend |
|---|---|---|
| Authentication and validation | `test_ceo_http_end_to_end` (401; an empty message is 422 and the classifier is never called), `test_ceo_api::test_every_endpoint_requires_authentication`, `test_ceo_turn::test_message_bounds` | request contract guard on every request |
| Conversation and turn creation | `test_ceo_api`, `test_ceo_http_end_to_end` | the CEO client's calls, under the contract guard |
| Classification | `test_ceo_turn` (scripted), `test_ceo_safety_gate` (a hostile classifier executes nothing outside the closed catalog: 700 cases) | |
| Specialist selected through the real registry | `test_ceo_http_end_to_end` (profit question → `PROFIT_DIAGNOSIS` → `cfo.financial_health`, `cfo.anomaly_check`, `cfo.strategic_briefing`), `test_ceo_turn::test_a_successful_multi_agent_investigation_end_to_end`, `test_ceo_registry` | |
| Real specialist execution | the CFO handlers run for real in `test_ceo_http_end_to_end`; `test_ceo_dispatch_integration` (one child run row per leg, parented on the turn); `test_ceo_pi_chat`, `test_ceo_cmo_chat` with their external calls faked | |
| Aggregation, evidence, provenance | findings cite this tenant's engine results (asserted by id); figures carry a register and a ref; a foreign or unresolvable ref is dropped (`test_ceo_turn`, `test_ceo_presentation`) | `ceoRealPayload.test.tsx` renders the real payload: answer, one card per finding, each figure with value and register, the provenance count |
| Progress and terminal state | the persisted event trail runs `TURN_RECEIVED`, `TURN_ADMITTED`, `LEG_*`, `ANSWER_READY` (no timers); `test_ceo_sse` | the polling and hub tests; the real event list is in the captured payload |
| Errors never become successes | a classifier failure degrades to a question with no findings (`test_ceo_http_end_to_end`); a failing leg is a named gap (`test_ceo_turn`); a member without the CFO key gets no CFO figure | an UNAVAILABLE finding renders as "not available" with no number |
| Persistence and restoration | a fresh `GET` returns the same messages, turn and findings; the snapshot is identical live and after reload (`test_ceo_presentation`) | `ceoRealPayload.test.tsx` reopens the conversation as a refresh does, with one read |
| Isolation and permissions | tenant B gets 404 on A's conversation, an empty list, and cannot post a turn to it; a CEO-only member is refused the CFO legs | |

The real turn and detail payloads are captured to `frontend/test-support/fixtures/ceoRealTurn.json` by the backend test (`CAPTURE_CEO_FIXTURE=1`). Without the variable the backend test fails when the committed file's structure no longer matches the real response, so the frontend rendering test cannot run against a fiction.

**Not exercised: a live local-model turn.** Prerequisites to run one: Ollama reachable with the configured models, a tenant with a CEO cap, and a decision on which tenant it may write to (a turn creates an investigation, messages, agent runs, findings and metered units). It was not run against any real tenant.

## Mutations

| Operation | Class | Verified |
|---|---|---|
| `POST /ceo/investigations`, `resolve`, `reopen`, `archive`, `PUT .../agents/{code}` | state-changing, internal | backend HTTP tests (`test_ceo_api`, `test_ceo_turn`); contract-checked in `lib/clientContract.test.ts` |
| `POST /ceo/investigations/{id}/turns` | state-changing, metered (CEO cap); a model call in production | the deterministic end-to-end above; duplicate simultaneous turns leave a consistent thread (`test_ceo_api_permissions`) |
| `POST /ceo/investigations/{id}/attachments` | stores bytes, no external effect | `test_ceo_attachments`; size and type refusals |
| `POST /ceo/findings/{id}/forget`, `POST /ceo/memory/{id}/forget` | lasting (a tombstone; the source is not recorded again) | `test_ceo_findings` (401/403/404, isolation, forget persists, list refreshes, a second forget is 404); frontend: the finding asks first, forgets only on confirmation, then re-reads the list |
| `POST /cfo/cash-reconciliation` | computes and now **stores** engine results; entitlement-metered | new `test_cfo_cash_reconciliation_contract` on controlled settlement rows: 401/403, five invalid payloads (nothing stored), no rows is honest, absent inputs are unavailable with the backend's own reason, tenant isolation, a retry reads the same rows, the stored record behind `engineResultRef` |
| `POST /ci/evidence`, `POST /ceo-hub/research-now` | stores a file and a snapshot; a local vision-model call | new `test_ci_evidence_research_contract` with a scripted extractor: 401/403, missing file, invalid bodies, foreign competitor, manual value wins, a failed reading is never a price, no evidence is not a success, a double submit is two audited runs and no invented price change |
| CMO generation, PI discover | metered, model-backed | existing backend suites with the model faked; frontend under the contract guard |
| `PUT /ci/digest/subscription` | stores a preference; delivery is not implemented | existing tests |

Nothing in these tests sends e-mail or WhatsApp, calls a marketplace, or calls a paid or local model.

## `ci.research_now` from the CEO: not wired, and why

What exists today: the seller's own page runs the whole workflow (upload a screenshot to `POST /ci/evidence`, then `POST /ceo-hub/research-now` with the competitor and the returned `image_ref`s and any manual fields), and it is now covered by the new tests. The registry entry is `ci.research_now`, effect `COMPUTE_PERSIST`, deliberately unwired with this reason: *needs a chat-attachment/evidence-upload surface (spec Q8, unresolved)*.

Why it cannot simply be connected:

1. **Two stores that do not meet.** A chat attachment is stored in the database (`investigation_attachment`: bytes, a type taken from the content, extracted text) and has no download route. CI evidence is a file in a flat local directory addressed by an opaque `image_ref`, with no tenant recorded against it. `research_now` takes `image_refs`; nothing turns an attachment into one.
2. **The CEO may not write evidence.** `ci.evidence_upload` is in `FORBIDDEN_ACTION_KEYS` (spec C21), so a bridge cannot be a CEO action.
3. **Missing slots.** The action has no slot model; the competitor (`competitor_url_id`) would have to be resolved from the seller's words by code, as the price-impact flow already does for a competitor name.
4. **Spec status of images in chat.** Section 6.34 says images are stored but not read ("no vision step yet, Q36"), and that an attached image is *offered* to the specialist that owns the evidence path as a card.
5. **Effect and cost.** `effects.py` notes the action "must be reclassified (external fetch) when it is" wired; it calls a vision model.

**Decision needed (not guessed).** Pick one:

- **A. (Recommended, smallest.)** Do not wire the action. When an image is attached in chat, the CEO's existing "offer" card links to the Competitors page's evidence form (the seller uploads there, under their own `agent.ci` permission, and the existing direct path runs). No new endpoint, no change to C21, no new storage. It answers Q8 as "the existing evidence surface, not the chat attachment".
- **B.** Wire `ci.research_now` into the registry. Requires: a decision that a chat attachment may become CI evidence (Q8) and the permission gate for it; a way to read attachment bytes server-side into the evidence store (a new internal function, and a tenant column or prefix for evidence refs); a `competitor` slot model; reclassifying the effect; approval to run the vision model from chat (cost, data left on the machine); Q36 (image reading) resolved.

Nothing was built for either option. The direct path's contract is pinned by the new tests, so B has a baseline to preserve.

## The slow backend integration suite

Findings, in order of how much they explain:

1. **The "20 seconds per test" was mostly contention.** The earlier runs overlapped with vitest, a Next build, the browser and the live dev backend (`--reload`). With the machine otherwise idle the suite ran at roughly one test per second.
2. **One test is slow by design.** `test_ceo_safety_gate::test_class1_a_hostile_classifier_can_execute_nothing_outside_the_closed_catalog` runs 700 adversarial turns on purpose (its own docstring says so) and takes several minutes alone. It looked like a hang because `-q` prints nothing while it runs.
3. **Ordinary tests are bound by database round trips.** A profile of five CEO permission tests: 16,657 `select()` waits (12.5 s of 31 s) over about 6,100 statements: many small queries, about 0.75 ms each on the local Docker Postgres. Not a lock, not start-up cost, not a sleep.
4. **The "stall" I first saw was my own diagnostic.** `-o faulthandler_timeout` dumps all thread stacks on Windows while psycopg is inside libpq and crashed the process with an access violation (visible in the log). The dump at the 700-turn test showed it waiting in an ordinary `COMMIT`, which is where a busy test happens to be, not a deadlock. No lock holders or idle-in-transaction sessions were found.

No test, assertion or timeout was changed to make it finish. No safe speed-up is supported by this evidence (the cost is the number of round trips the code legitimately makes), so none was made.

**The suite cannot fall back to port 5432.** The integration tests read only `DATABASE_URL` / `DATABASE_URL_APP` from the environment (no `.env` loading in the tests or in `backend.config`). A new session guard (`tests/integration/db_guard.py`, used by `conftest.py`) now stops the session before any test runs when either points at 5432 or has no port, unless `METRION_TESTS_ALLOW_DEV_DB=1`. Shown by running the suite with 5432 URLs: it exits with the refusal and "no tests ran", without connecting. Unit tests: `tests/unit/test_integration_db_guard.py`. The packages' own integration conftests (`packages/*/tests`) are not guarded.
