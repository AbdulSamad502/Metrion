# Frontend roadmap: verified status and remaining work (planning only)

Date: 2026-10-10. Branch `feat/ceo-foundation`, HEAD `2b954c9`, with 88 uncommitted paths (frontend work below is uncommitted). Nothing was changed to produce this document. Source of truth: the checked-out tree. Not run: no dev server, no suites; test status below is from earlier recorded runs (frontend 198/198 with `--maxWorkers=4`, eslint and tsc clean, `next build` OK; none re-run for this audit). **Not verified:** the signed-in app (no authenticated session available), mobile/tablet behaviour of any specialist page, and every page's keyboard behaviour. Several audit sub-agents were stopped before reporting, so the specialist-page findings are from direct greps and are shallower than the CEO Hub findings; items marked *(shallow)* need a page-level read before their task starts.

## 1. Baseline facts
- Stack: Next.js 16 App Router, React 19, Tailwind 4 (`app/globals.css`, `mt-*`/`t-*` classes), Clerk auth, vitest. Routes (`app/`): `/dashboard`, `/dashboard/{ceo-hub,notifications,cfo,pi,competitors,cmo,agents}`, `/settings`, marketing/auth pages. Shared UI in `components/ui/` (Button, Card, DetailDrawer, EmptyState, ErrorNotice, FormField, Icon, LoadingState, MetricCard, Section, Stat, StatusBadge, Tabs, CostInput…); shell in `components/dashboard/` (DashboardShell, Sidebar, Topbar, HeaderContext). API pattern: `apiFetch(path, token)` in `lib/api.ts`, typed clients in `lib/ceo.ts`, `lib/cmo.ts`, per-page inline calls elsewhere.
- Page size is uneven: `cfo/page.tsx` 2,436 lines and `pi/page.tsx` 890 lines are monoliths; `cmo` and `competitors` pages are thin wrappers over `components/cmo/*` and `components/ci/*`.
- Frontend tests exist only for the CEO Hub and a few libs (`components/ceo/hub/*.test.tsx`, `lib/{ceo,ceoModel,ceoPolling,clarificationProgress,costInput,navigation,noClientMath,useBusinessHealth}.test.ts`). **No tests** for Overview, Action Center, Settings, Agents, PI, CFO, CMO, Competitors pages. There is **no frontend job in CI** (`.github/workflows/ci.yml`).
- API contract check (client paths vs backend routers, prefixes `/api/v1/{pi,ci,cfo,cmo,ceo}`, mounted in `backend/src/backend/main.py`): every path the PI, CI, CFO and CEO clients call exists (PI 10 routes, CI 23, CFO 31, CEO 21, `/ceo-hub/agents`, `/ci/summary`, `/ci/alerts`, `/cfo/data-requests`). CMO client paths all match routes in `api/v1/cmo.py`. The frontend sends no `candidate_cap`, so the new 1-100 bound does not affect it. Request-body field correctness was **not** compared against the Pydantic models.
- Backend constraint now in force: the six approval-required actions are refused from chat (`DENIED` turn, fixed text); `/ceo/agents/availability` `chatActions` excludes them (PI 1, CMO 1). No approval-plan API exists.

## 2. Verified status of the five phases
| Phase | Deliverable | Status |
|---|---|---|
| 1 Audit and UX planning | `docs/design/ui-ux-phase1-audit.md` (inventory, IA, dependency matrix) | Complete (documents; the Phase 1 §10 "not verified" list is still open) |
| 2 Dashboard and navigation | Goal-based nav (`lib/navigation.ts`: Today / Understand profit / Market, plus Agents, Settings), Overview hero with attention chips and freshness badge, Sidebar/Topbar polish (Escape, inert drawer, 44 px targets) | Implemented, **unverified signed-in**; unit tests only for navigation and freshness helpers |
| 2 | Overview data sections (profit snapshot via `/ceo/state/health`, market watch via `/ci/summary`, attention via `/ci/alerts` and `/cfo/data-requests`, agent roster) | Implemented, unverified; no page tests. Opportunities section is an honest placeholder (no backend source) |
| 3 CEO Hub and interactive AI | Conversation, server-driven clarification cards (`DecisionCard`, `clarificationProgress`), composer (Enter/Shift+Enter, attachments), memory/findings/needs panels, health strip, decision forms | Implemented and covered by 10 test files; signed-in behaviour unverified |
| 3 | Execution/task activity (`ExecutionPanel`) | Implemented from reported turn state only; no planning/approval states (backend has none) |
| 3 | Approval controls | **Not implemented, blocked** (no plan lifecycle or API; S2/S3 not built) |
| 4 Agent workflow and specialist workspaces | Orchestration canvas (`AgentCanvas`, container-responsive, attach/detach per conversation) | Implemented; no pan/zoom/drag by design (no routing graph in the backend); fan layout at wide containers never visually verified |
| 4 | Specialist workspaces: PI (`app/dashboard/pi`), Competitors (`components/ci`), CFO (`app/dashboard/cfo`), CMO (`components/cmo`) | Implemented against existing routes; **execution path of each action not verified end to end** *(shallow)*; no tests |
| 4 | Workflow editor | Not implemented; excluded (needs backend capability and owner decision) |
| 5 Visual polish, integration, QA | Design tokens, CEO Hub reference layout, responsive tabs, preview-harness QA of the Hub at 375/1024/1700 px | Partially implemented; only the Hub was visually checked, with fake data |
| 5 | Authenticated end-to-end QA, accessibility pass, frontend CI | **Not done** |

## 3. Route-by-route findings
**Overview (`app/dashboard/page.tsx`).** Works (by code): hero with attention chips, freshness (7-day stale rule), profit snapshot (saved results only), market watch, "What matters now", agent activity table. Gaps: no page tests; "Opportunities" is static text; agent activity says "Not recorded" for most agents (honest). States: loading skeletons, empty, error notices present; stale handled for freshness only. Needs a signed-in visual pass at 375/768/1280.

**Action Center (`notifications/page.tsx`, 230 lines).** Reads `useNotifications` (`/ci/alerts`, `/cfo/data-requests`). Zero aria/role attributes found by grep. No tests.

**CEO Hub (`components/ceo/hub/*`, `lib/ceo*.ts`, `lib/useCeoHub.ts`).** Works and tested. **Misleading behaviour found:** a `DENIED` turn is labelled "Not permitted" (`lib/ceoModel.ts:104,358`, `lib/ceoModel.ts:318`) and "Not allowed" (`ExecutionPanel.tsx:22,37`). The approval refusal is also `DENIED`, so a seller who asks for market trends is told "Not permitted" (a permissions message) next to the backend's explanation text. The API does not expose the refusal reason: `TurnRow` (`lib/ceo.ts:53-66`) has no field for it and `classifier_result.approvalRequiredFor` is stored but not returned by `api/v1/ceo.py`. Fixing this properly needs a small backend field (see §5, B1). Chat chips: none of `QUICK_ACTIONS` (`lib/ceoModel.ts:261-273`) invoke a blocked action (they are Business State reads, `pi.report`, `cfo.anomaly_check`, playbooks), so no chip misrepresents availability. Canvas copy ("N actions the CEO can run from chat", `AgentCanvas.tsx`) now reads PI 1 / CMO 1 from the corrected endpoint: accurate. Confirmation cards are rendered as chat answers; nothing in the Hub presents one as stored approval. Gaps: signed-in verification; keyboard behaviour of the drawer and tabs untested; the fan canvas layout unseen.

**Agents (`agents/page.tsx`, 57 lines).** Reads `/ceo-hub/agents` (route exists, `api/v1/ceo_hub.py:59`); a static roster. Not otherwise audited *(shallow)*.

**Product Intelligence (`pi/page.tsx`).** Calls `/pi/niche-briefs*`, `/pi/discover`, `/pi/supplier-lookup`, `/pi/report/{id}`: all exist. Errors surface as `ApiError.message` generically (lines 72-464, 746); no special handling for 402/403/409/422/503. Only ~3 aria attributes. This page is the **only supported route to PI discovery** now that chat refuses it; whether its handler executes correctly end to end was not traced here.

**Competitors (`components/ci/CompetitorWorkspace.tsx`).** Calls the `/ci/*` routes (all exist, including price-scenario, comparison, market-overview). Generic error strings; 2 aria attributes. "True-margin analysis" lives in the CFO/CI price-scenario paths; not traced in the UI *(shallow)*.

**CFO (`cfo/page.tsx`, 2,436 lines).** Calls ~30 `/cfo/*` routes (all exist): ingest, imports, pnl, pricing, landed-cost, suppliers/rank, batch-size, reconcile, anomaly, GST lookup/accept/period-summary/analyze-lines, expenses, data-requests. Best responsive coverage (33 breakpoint classes) but one aria attribute and a single file that is hard to review or test. GST and import flows were not exercised.

**CMO (`components/cmo/*`).** Tabs: Create, Titles, Copy, Catalog, Niche, Trends, Standalone, Usage. Calls `/cmo/*` (all match). Zero aria attributes in `CmoWorkspace.tsx`. These tabs are the supported way to generate titles, hashtags, descriptions, keywords and market trends now that chat refuses them; handler end-to-end behaviour **not verified**.

**Settings (`settings/page.tsx`, 382 lines).** Has save buttons for preference options; what endpoint it persists to was not traced *(shallow)*; no tests.

**Shared system.** Tokens and components are consistent in the Hub and shell; specialist pages mix inline patterns. Gaps: no shared mapping from `ApiError` status to plain words; sparse aria across specialist pages; no frontend tests outside the Hub.

## 4. Backend dependencies and unavailable capabilities
- **B1** Expose the refusal reason on turns (for example `refusal: "APPROVAL_REQUIRED"` or a distinct `outcome`) so the UI can label approval-blocked answers correctly. Backend change; **not done**.
- **B2** Approval-plan lifecycle and API (plans, approve, decline, events): not implemented (S2/S3, R5 prerequisite). Any approval UI is blocked.
- **B3** Portfolio-level profit/margin endpoint: does not exist; Overview must keep showing saved results only.
- **B4** Workflow routing graph persisted and used by the backend: does not exist; no canvas editing.
- **B5** Opportunities summary source for the Overview: none.
- Outside this plan, recorded only: R5 crash reconciliation and the guarded-transition work.

## 5. Remaining tasks in dependency order (each one session, independently reviewable)
1. **T1 Plain-language API errors for the specialist pages** *(user impact: high; misleading/broken behaviour)*. Add one shared helper mapping `ApiError.status` (402 entitlement, 403 permission, 409 conflict/in progress, 422 invalid input, 503 not configured) to plain messages; use it in the PI, CMO, Competitors and CFO catch blocks. Inspect: `lib/api.ts` (ApiError shape), `lib/clerkErrors.ts` (pattern), the catch sites listed in §3. Exclusions: no layout changes, no new endpoints, no behaviour change on success paths. API: none new. Acceptance: each status shows its mapped text on at least PI discovery, one CMO tab, one CI action and one CFO action; unknown statuses keep the existing message; no raw JSON or stack text is shown. Tests: unit test of the helper (all statuses plus unknown), one component test per page with a mocked `ApiError`. Visual QA: error notice at 375 px. Stop after the helper and its four call sites.
2. **T2 Approval-refusal label** (blocked on B1). Show "Needs an approved plan (not available yet)" instead of "Not permitted" for approval-blocked turns in `ceoModel.messageView`, `STATUS` maps and `ExecutionPanel`. Tests extend `ceoModel.test.ts`, `ceoExecution.test.tsx`. Until B1, do nothing (matching on answer text is rejected as fragile).
3. **T3 Tests for Overview and Action Center** (hook mocks; empty, loading, error, stale, populated states). Files: new `app/dashboard/*.test.tsx`, reuse `test-support/`.
4. **T4 Accessibility pass on shell and specialist pages**: aria labels, focus order, tab semantics (CMO tabs, CFO sections, Action Center list), keyboard test of the mobile drawer. Smallest tests: `@testing-library` role queries per page.
5. **T5 Signed-in visual QA at 375/768/1280** of every route, recorded in a short checklist document (needs the owner to sign in; no credentials are entered by the assistant). Fix list becomes follow-up tasks.
6. **T6 CFO page decomposition** into reviewable components (no behaviour change), enabling tests; only after T5 shows what is stable.
7. **T7 Specialist end-to-end verification**: trace each PI/CMO/CI/CFO execution route to its handler and add one page test per primary action. Required before any statement that agent-page execution works.
8. **T8 Frontend CI job** (lint, tsc, `vitest run --maxWorkers=4`, build) in `.github/workflows/ci.yml`; needs owner approval (D-11 of the approval register).
9. **T9 Settings audit** (endpoint, states, tests) and **Agents page** review.
10. **Blocked:** approval controls and plan card (B2); workflow editor (B4); Opportunities content (B5).

## 6. Recommended next task: T1
Reason: it removes a real, user-facing weakness (the pages that are now the only route to PI discovery and CMO generation show generic errors for entitlement, permission and in-progress conditions), needs no backend change, is small, and is verifiable by unit tests. Not recommended first: T2 (blocked by B1), T5 (needs the owner's sign-in).
Acceptance criteria are those listed under T1. Before coding, read `lib/api.ts` to confirm what `ApiError.message` already contains (it may already carry the backend `detail`), so the helper adds wording without hiding the backend's own specific text.

## 7. Unresolved decisions and exclusions
Decisions for the owner: B1 (add a refusal field to the turn API), frontend CI (T8), whether to decompose the CFO page (T6), and whether Opportunities should stay a placeholder (B5).
Excluded from this plan: approval UI, workflow editor, any new design language, redesign of completed screens, R5 reconciliation, guarded transitions, S2/S3, any claim that agent-page execution works (T7), and signed-in findings (T5).
