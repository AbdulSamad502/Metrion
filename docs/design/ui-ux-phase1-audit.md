# Metrion UI/UX Improvement — Phase 1: Audit and Plan

**Status:** Draft for approval. Audit and specification only; no UI code was changed.
**Date:** 2026-10-09 · **Branch:** `feat/ceo-foundation` @ `5e04480` (+ uncommitted backend migration 0011 / pyproject fix, unrelated to UI).
**Governing rules:** `CLAUDE.md` (no money maths in the UI, no invented figures, recommend-only), `docs/design/frontend-design/README.md` (the `.dc.html` mockup is the *visual* reference; every number in it is fabricated), `docs/design/design_status.md` (branding not final — keep tokens configurable).

---

## 1. Verified artifact and architecture inventory

### 1.1 What the product is
**An integrated application, not a mockup.** `frontend/` is a Next.js 16 / React 19 / Tailwind 4 app with Clerk auth, wired to a FastAPI backend (`/api/v1/{ceo,ceo-hub,cfo,ci,cmo,pi,session,onboarding}`). The design source `docs/design/frontend-design/Metrion App.dc.html` (160 KB, 13 fake-data screens) is a separate Claude-Design prototype; `Metrion App - Standalone.html` is its bundled export. `client-prototype/maverick-prototype.html` is an older, unrelated prototype.

### 1.2 Artifacts the brief mentioned — what was actually found
| Artifact | Found? |
|---|---|
| `Metrion App.dc.html` | Yes, `docs/design/frontend-design/` (plus an identical `… copy.html`) |
| Frontend app | Yes, `frontend/` (≈20k lines incl. tests) |
| Specs | Yes: `agent-flow-visualization.md`, `ceo-agent-orchestration.md`, per-agent specs |
| **Supplied workflow reference image** | **Not in the repo and not attached to this conversation.** Only `docs/design/exploratory/` (logo, dashboard and two UI-overview JPEGs) exist. The black-connector investigation in §3.6 is therefore done on the code, with hypotheses to confirm against the image once supplied. |
| "Cyber-Luxe" palette | **No such name anywhere in the repo.** The actual direction is: near-black `#0A0B0A` base, brand green `#3ECF74`, Inter, glass/blur cards. I evaluate that, not a named palette. |

### 1.3 Frontend inventory
- **Routes (signed-in):** `/dashboard` (Overview, 348 lines), `/dashboard/ceo-hub`, `/dashboard/pi` (877), `/dashboard/competitors` (→ `CompetitorWorkspace`, 1,593), `/dashboard/cfo` (**2,436 lines in one page file**), `/dashboard/cmo` (→ 8 tab components), `/dashboard/agents`, `/dashboard/notifications`, `/settings`. Public: landing, sign-in/up, forgot-password, onboarding, sso-callback. Auth gate verified live: unauthenticated `/dashboard/ceo-hub` → `/sign-in`.
- **Shell:** `DashboardShell` (session gate → `Sidebar` + `Topbar` + scrolling `<main>`), `ShellContext` shares session + notifications feed. Sidebar collapses (localStorage) and has a mobile overlay.
- **Navigation model** (`lib/navigation.ts`): groups "Profit Intelligence" (Overview, CEO Hub) and "Analysis" (Products, Competitors, **CFO**, Marketing); footer: Agents, **Agent Cart (inert "Soon")**, Settings, Notifications. Mockup additionally has Orders/Customers/Reports "Soon" screens — not built, correctly not faked.
- **Design tokens:** one `:root` block in `app/globals.css` (~90 custom properties: backgrounds, borders, accent, warning/negative/info, 8 text tiers, glass set). Only 8 `@media` rules in 1,271 lines (2 are width queries; the rest `prefers-reduced-motion`) — responsiveness is mostly Tailwind breakpoints in components.
- **UI kit** (`components/ui/`): Button, Card, MetricCard, Stat, Tabs, StatusBadge, ConfidenceBadge, EvidenceStateBadge, EmptyState, ErrorNotice, LoadingState, DetailDrawer, FormField, CostInput, Icon, Section, AuthCard. Reasonable base; the large pages (CFO, CI) do not appear to be built on it uniformly (not yet measured — see Open items).
- **Tests:** vitest 152/152 passing (mostly CEO Hub); lint + `tsc` + production build clean (verified earlier today).

### 1.4 CEO Hub (current)
`CeoHubWorkspace` layout (desktop, 12-col grid): **top** `AgentStrip` (CEO + agents) → **left 7 cols** "Agent results" (`AgentsPanel` + `FindingsPanel`) → **right 5 cols** the conversation → sticky `Composer` at the page bottom. Conversations list and "Business at a glance" live in a slide-in drawer.
Implemented and test-covered: investigation create/list/resolve/reopen/archive, turn send, SSE progress with polling fallback (`GET …/turns/{id}/events`), findings with presentation snapshots and evidence, per-turn "Show flow" (`FlowView`, from `GET …/turns/{turn}/flow`), guided-input forms (`DecidePanel`), attachments (image/PDF/CSV/XLSX), agent attach/detach per investigation (`PUT …/agents/{code}`).

### 1.5 Backend capabilities relevant to the redesign (verified from routes + migrations)
| Capability | Exists? |
|---|---|
| Auth (Clerk JWT), tenant RLS, permission grid | Yes |
| CEO turns, findings, flow rows (`agent_run`, `parent_run_id`), SSE events | Yes |
| Clarification **cards**: one question per message; options + "Other"; optional CANCEL; answered by option key | Yes (`choices: {version, kind, slot, options[]}`) |
| Multi-select, multi-question wizard, Back/Skip/progress, answer editing | **No** |
| Task **plan / summary / approval** step before execution | **No.** Turn status is `DELIVERED / CLARIFIED / DENIED / FAILED`; investigation status `ACTIVE / RESOLVED / ARCHIVED`. There is no "awaiting approval" or "planning" state. (Spec C21: V1 has no WRITE effect; actions are READ / COMPUTE_PERSIST / GENERATE_METERED / RECORD_CHOICE.) |
| Per-agent roster + CONNECTED status | Yes (`GET /ceo-hub/agents`, `/agents/availability`) |
| **Portfolio revenue / profit / margin endpoint** | **No.** Overview deliberately shows no headline profit (computing it in the browser would violate the hard rule). CFO has `/pnl`, `/period-comparison`, `/financial-health` per request, not a dashboard summary. |
| **Workflow definition storage** (nodes, edges, positions, routing) | **None.** No table, route, or code path (`grep` for workflow tables/edges in migrations: no results). |
| CEO routing driven by user-drawn edges | **No.** Routing is the fixed tool catalog (`CLAUDE.md`: no LangGraph, no LLM-generated orchestration). The only configurable relation is per-investigation agent attachment. |
| Entitlement / Agent Cart | Backend entitlement tables exist; no purchase service; UI says so honestly |

---

## 2. Current-state UX audit

**Strengths (keep):** honest empty/unavailable states; no invented figures; provenance chips; strong test coverage on CEO Hub; auth gate and tenant model correct; consistent dark/glass language; skip-link and focus styles present.

**Findings** (severity: H/M/L)
1. **H — CEO Hub layout inverts the expected chatbot pattern.** The *results* get the wide column (7/12) and the *conversation* the narrow one (5/12, ~420px at 1280). The composer is page-sticky, not column-anchored. Long answers read cramped. Agent activity is not a "side panel to the right" — it is the main area to the left.
2. **H — Clarification cards cover one narrow case.** Single-select + "Other" + Cancel. No multi-select, no Back/Skip/Continue, no progress, no edit of a previous answer. Of these, only some are frontend-only (§5).
3. **H — No task-plan/approval step exists** in lifecycle or UI; the brief's "summary → approval → execution" cannot be represented honestly today.
4. **M — Overview has no profit hierarchy.** Four CI counts lead the page (competitors tracked, price changes, manual entry, stale). The product's mission (contribution profit, leaks) is a text block pointing at CFO. Honest, but not goal-oriented.
5. **M — Navigation uses internal terms and splits goals.** "CFO", "Products", "Competitors", "Marketing", "Agents" mix agent names and nouns; "Profit leaks" / "What should I do" have no entry point; "Agent Cart" is a dead item in primary-looking footer nav; "Agents" and "CEO Hub" overlap (agent roster vs. CEO's strip).
6. **M — Orphaned code:** `AgentCanvas.tsx` (n8n-style canvas) and `OrchestrationDiagram.tsx` are **not imported by any page** (verified by import search); the live Hub uses `AgentStrip`. Dead UI is a maintenance and audit risk and was the source of the "workflow editor" impression.
7. **M — Very large single-file screens** (CFO 2,436 lines; CI 1,593) make consistent patterns and responsive QA hard.
8. **M — Context loss between CEO and workspaces.** Findings link out, but there is no "back to the conversation/finding" state carried into CFO/PI/CI (`#anomalies`, `#profitability` hashes only).
9. **L — Execution state is split** across `AgentStrip` badges, `FindingsPanel` and a per-turn "Show flow" toggle; there is no single timeline of the current turn with timestamps.
10. **L — Mobile:** sign-in verified at 375px, no overflow. **Authenticated screens were not screenshot-audited** (I cannot sign in). The CEO Hub's `height: calc(100vh − 330px)` + 12-col grid and sticky composer are the likeliest mobile risks — to verify with the user's session or a Clerk test account.
11. **L — Token hygiene:** accent green doubles as "positive" **and** primary brand colour (`--positive: var(--accent)`); text tiers `--text-5…8` (`#8A9188`…`#5E655B`) on `#0A0B0A` need a contrast check (the dimmest are below 4.5:1 — measured in Phase 5, not assumed here).

---

## 3. Proposed information architecture (customer goals, not agent names)

Proposal — labels in *italics* are customer-facing; the agent term stays as a subtitle.

| Group | Item | Maps to | Notes |
|---|---|---|---|
| **Today** | *Overview* | `/dashboard` | Health, what needs attention, next actions |
| | *Ask Metrion* (CEO Hub) | `/dashboard/ceo-hub` | Primary, always one click; Topbar shortcut kept |
| | *Action Center* | new view on `/dashboard` or `/dashboard/actions` | **Frontend-only aggregation** of existing feeds: CFO data requests, CI alerts/anomalies, open investigations. No new backend. |
| **Understand profit** | *Profit & Finance* (CFO) | `/dashboard/cfo` | P&L, reconciliation, GST, leaks |
| | *Products* (PI) | `/dashboard/pi` | Unit economics, feasibility |
| **Market** | *Competitors* (CI) | `/dashboard/competitors` | |
| | *Listings & Marketing* (CMO) | `/dashboard/cmo` | Only the verified text-generation/research features |
| **Workspace** | *Data & Imports* | link into CFO import | Reports uploaded, data freshness |
| | *Agents* | `/dashboard/agents` | Roster + connection settings; Agent Cart folded in as "Not available yet" |
| | Settings, Notifications | existing | |

Rationale: customer jobs are *see how I'm doing → find leaks → decide → act*; agent names remain visible as secondary text (the brief asks to keep PI/CI/CFO/CMO terminology where useful).

---

## 4. Screen-by-screen specification (proposals)

**Overview.** Order: (1) one-sentence state + data-freshness line ("CFO data as of …" / "No reports uploaded"); (2) **Profit block** — shows real CFO output only when a per-period result exists; otherwise an honest "No profit computed yet — upload a settlement report" with CTA. Any figure shows its `engine_result_ref` chip. (3) *Needs attention* list (existing `WhatMattersNow`, merged with open investigations) each with a next step; (4) Opportunities; (5) compact agent status. Max ~4 KPI tiles; no decorative charts. **Blocked on backend** for a true headline profit/margin trend: needs a portfolio-summary endpoint from the engine (§6).

**CEO Hub (target).** Desktop: **three zones** — left rail (conversations, collapsible), **centre column = conversation** (scrolls; composer pinned to the bottom *of this column*; suggested questions in Welcome), **right panel = Task & agent activity** (fixed ~340–380px, collapsible). Mobile: conversation full width; activity opens in a bottom sheet/tab. Composer: multiline, Enter sends / Shift+Enter newline, attachment button (exists), disabled-with-reason states. Retry on failed turn.

**Clarification cards (target).** Card = title, helper text, options, "Other". *Frontend-only now:* multi-select rendering **if** the backend slot is declared multi; Back/Continue/Skip/progress as **local navigation over cards the backend has already sent**. *Backend-dependent:* the CEO emitting several questions per ask, multi-valued slots, optional-slot flag, and editing a prior answer (needs a new/extended `choices` schema and slot-resume behaviour). Must not default or guess an answer (spec rule: missing slot ⇒ CLARIFY).

**Task summary & approval.** Specified as a *UI of record only after a backend state exists*: summary of outcome, agents, integrations, assumptions; explicit "Run" action; clarification answers never imply approval. **Not implementable honestly today** (no plan/approval state). Options: (a) backend adds `PLANNED/AWAITING_APPROVAL` turn states (preferred, architecture decision → spec change); (b) UI shows only what already happens (the CEO's classification + attached agents) labelled as "What I'm doing", with no approve gate. Needs your decision.

**Execution panel (right).** Derived strictly from existing data: turn stage text (SSE), `agent_run` flow nodes with `status` + `started_at/finished_at`, findings arriving, errors. States mapped 1:1: *Awaiting input* (CLARIFIED), *Running* (PROCESSING), *Completed* (DELIVERED), *Failed* (FAILED), *Denied* (DENIED). **"Planning" and "Awaiting approval" have no backend source — omitted until one exists.**

**Workflow editor.** See §6 — I recommend **not** presenting a free-form editable workflow in this iteration.

**Specialist workspaces (PI/CI/CFO/CMO).** Shared header (title, data freshness, primary action), shared tabs (`Tabs`), shared empty/loading/error components, "Open in Ask Metrion" and "Back to finding" context links via a `?from=investigation:<id>&finding=<id>` query (frontend only; all params validated, never trusted for tenant/data scope). CFO/CI files split into section components as part of refinement.

---

## 5. Initial design-system recommendations (proposals, not approved)

- Keep: dark base, single green accent, Inter, glass surfaces — they fit "trustworthy financial tool" and match the approved mockup.
- Separate **brand green** from **semantic positive**/primary-action to avoid green meaning both "brand" and "good"; keep info blue for neutral status.
- Reduce glass/blur and gradient use on data-dense surfaces (tables, forms); flat elevated surfaces improve legibility and performance.
- Contrast pass on `--text-5…8`, borders and disabled states (target WCAG AA 4.5:1 body / 3:1 UI).
- Type scale: formalise 5–6 steps (display, headline, title, body, small, meta) as tokens; tabular numerals for money.
- Radii/spacing: 2 radii (control, surface), 4/8-pt spacing scale.
- Tokens stay in `globals.css` (configurable per `design_status.md`); no logic coupling.
- Motion: keep fade/slide ≤200ms, respect `prefers-reduced-motion` (already present).

---

## 6. Workflow editor — findings and recommendation

- **Reality:** there is no workflow store, no edge model, and CEO routing is a fixed catalog. The only user-controlled relation is *"agent X is attached to investigation Y"* (`PUT /ceo-hub/investigations/{id}/agents/{code}`; detach affects future work only).
- **The existing canvas** (`AgentCanvas.tsx`, currently unused) already draws exactly that: CEO node + 4 agent nodes, with wires = attachment. It is **not** a workflow graph, and its wires are positioned by hard-coded percentages (`X = {CI:12.5, …}`) in a stretched `viewBox="0 0 100 100"` with `preserveAspectRatio="none"` — so line endpoints are *assumed*, not measured from port elements, and break when node widths/layout change.
- **Black-line hypotheses** (to confirm against your image): (1) an SVG `path` whose `stroke` is missing/invalid renders none, but one that inherits `currentColor` renders as the page's dark text colour; (2) a stroke set to a CSS variable that isn't defined in that scope falls back to initial; (3) a connector drawn in an HTML/SVG layer *behind* an opaque node or on a light-theme surface. In the mockup, connector colour is `{{ ln.strokeColor }}` = a `var(--…)` token chosen per attachment (measured from DOM rects in `measureOrchestrator`), which is the correct approach; the app's canvas dropped the measurement.
- **Recommendation:** Phase 4 delivers an **"Agent connections" view** (honest scope): pan/zoom/fit, node select + config inspector (role, status, permissions, entitlement, what it can do), connect/disconnect = attach/detach for the *current investigation* (real API, optimistic UI only after server ack), connector endpoints **measured from port elements** and re-measured on move/resize, clear Saved/Unsaved, and a visibly separate **Live activity** overlay driven by `agent_run`. Free-form node-to-node edges, multiple-hop workflows, saving layouts, or "this edge changes routing" are **explicitly not built** and labelled "not supported yet" unless you approve backend work (workflow tables + spec + RLS + routing changes — a data-model/brain-boundary decision, i.e. an architect task).

---

## 7. Frontend / backend dependency matrix

| Improvement | Frontend only | Needs backend / spec |
|---|---|---|
| Nav relabel + IA, Action Center aggregation | ✅ | |
| Overview hierarchy, freshness/unavailable states | ✅ | |
| **Headline profit/margin trend on Overview** | | ✅ portfolio summary endpoint from the engine (no browser maths) |
| CEO Hub 3-zone layout, composer anchoring, mobile sheet | ✅ | |
| Right execution panel from existing statuses | ✅ | |
| "Planning"/"Awaiting approval" states, approve gate | | ✅ turn-state model + spec change |
| Multi-select / multi-question / skip / edit answers | partial (rendering, local Back/Continue over sent cards) | ✅ clarification schema and slot-resume semantics |
| Streaming answer text token-by-token | partial (SSE progress exists; confirm whether answer text streams) | verify `events` payload |
| Attach/detach graph (real) | ✅ | |
| Free-form workflow edges / saved layouts / routing effect | | ✅ new tables, API, routing change, spec |
| Cross-workspace context links | ✅ | |
| Design-system refinement, responsive, a11y | ✅ | |

---

## 8. Prioritised plan, checklist and acceptance criteria

**Phase 2 — Dashboard, navigation, IA** (frontend-only)
- [ ] Nav regrouped per §3; "Agent Cart" removed from primary nav (folded into Agents as "Not available yet")
- [ ] Overview reordered: state + freshness → profit block (real or honest unavailable) → attention → opportunities → agent status; ≤4 KPI tiles
- [ ] Action Center aggregates existing feeds; each item has a destination
- [ ] Data states: loading / empty / stale / unavailable / error distinct and worded honestly
- [ ] *Accept:* no hard-coded money figures (existing `noClientMath` test passes); every card links somewhere real; lint/tsc/vitest/build green; desktop+mobile checked; no new endpoints.

**Phase 3 — CEO Hub**
- [ ] Layout: conversation centre, composer pinned to its column, activity panel right, mobile sheet
- [ ] Composer multiline + keyboard behaviour; retry; error/loading states
- [ ] Cards: multi-select rendering where schema allows; Back/Continue/Skip/progress over backend-sent cards; validation; edit-answer **only if backend supports** (else documented)
- [ ] Execution panel on real statuses only; planning/approval states **deferred pending your decision on §4**
- [ ] *Accept:* all existing 152 tests keep passing + new tests for layout/card/panel; no simulated activity; mobile drawer works at 375px.

**Phase 4 — Connections view + workspaces**
- [ ] Rebuild/replace orphaned canvas as measured-port "Agent connections" view with the honest scope in §6; remove dead code
- [ ] Connector measurement tests (endpoints coincide with port centres after move/resize)
- [ ] PI/CI/CFO/CMO shared header/tabs/states; split CFO/CI files; context links CEO ↔ workspaces
- [ ] *Accept:* attach/detach persists across reload (real API); limitations documented in-UI; workspace functionality unchanged (existing tests + manual smoke).

**Phase 5 — Design system, responsive, QA**
- [ ] Tokens: semantic split, contrast pass, type/radius/spacing scales
- [ ] Component consistency pass; responsive 375/768/1280; keyboard/a11y checks
- [ ] Full lint/tsc/vitest/build; browser verification with a signed-in session (needs your Clerk login or a test account)

---

## 9. Decisions needed from you before Phase 2

1. **Approval step:** add backend turn states (`PLANNED`/`AWAITING_APPROVAL`) via a spec change, or keep V1 without an approval gate (UI shows "what I'm doing" only)?
2. **Workflow editor scope:** accept the honest "Agent connections" view (attach/detach per investigation), or commission backend workflow storage/routing first?
3. **Overview profit headline:** wait for a backend portfolio-summary endpoint, or ship Phase 2 with the honest "not computed yet" block?
4. **Workflow reference image:** please attach it (or its path) so the black-line cause can be confirmed rather than inferred.
5. **Authenticated QA:** for Phases 2–5 browser checks, I need either you to sign in on the running local app or a Clerk test account whose credentials you supply — I cannot enter passwords myself.

## 10. Not verified in Phase 1
Authenticated-page screenshots and responsive behaviour; whether the SSE stream carries answer text or only progress; actual contrast ratios; how consistently CFO/CI pages use the shared UI kit; the reference image's black line.
