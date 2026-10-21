# Metrion — CFO 2.0 Dashboard Implementation Specification

**Status:** Draft for review (prepared 2026-10-21 so seller-visible work can start as soon as its data dependencies exist)
**Product spec (what and why):** `cfo-dashboard.md` · **Financial truth:** `cfo-unified-financials.md`, `deterministic-engine.md` §5.17 · **Read model and cache:** `cfo-query-planner.md` · **Ingestion flows:** `cfo-data-intelligence.md`
**This document is the *how*:** an audit of what exists, the reuse plan, the API contracts the dashboard needs, the components, the seller flows the owner moved into this track, the phased build with acceptance tests, and what each phase can honestly show with the data that exists at that point.

**Hard rules carried in (non-negotiable):** the dashboard computes nothing and formats no money (the backend returns display strings); every important figure shows its source, completeness state, last-updated time and missing inputs; `UNAVAILABLE` never renders as 0; provisional, estimated or incomplete results are never styled as confirmed actuals; the **CEO is the only conversational agent** (the dashboard has no chat); tenant scoping and permissions are enforced server-side; branding is token-driven and not final (`docs/design/design_status.md`).

---

## 1. Audit of the existing CFO dashboard (read-only findings, 2026-10-21)

**Stack:** Next.js 16.3.5 (App Router), React 19.2.8, Tailwind 4, Vitest 3 + Testing Library + jsdom; no chart library, no E2E runner, no accessibility-audit tool installed. Clerk auth via `useAuth().getToken()`; `apiFetch<T>(path, token)` in `lib/api.ts`.

**What is there (`/dashboard/cfo`, `frontend/app/dashboard/cfo/page.tsx`, 144 lines):** six tabs (Overview, Profitability, Cash & reconciliation, GST, Anomalies & requests, Import data) holding **22 tool sections** in `components/cfo/sections/*` (~2,350 lines). Each section is a **form that calls one real route when the seller submits it** and renders exactly what comes back, including genuine UNAVAILABLE and error states. Nothing loads on its own; there are no KPI cards, charts, filters, drill-down or exports.

**Reusable as they are:** `DashboardShell`, `Tabs`/`TabPanel` + `useHashTab` (hash-routed tabs), `MetricCard`, `Stat`, `ProvenanceBadge` (register VERIFIED / DERIVED / MANUAL / ESTIMATE / UNAVAILABLE), `ConfidenceBadge`, `EvidenceStateBadge`, `StatusBadge` (tones accent/warning/negative/info/neutral), `DetailDrawer`, `EmptyState`, `ErrorNotice`, `LoadingState`, the CSS tokens in `app/globals.css` (`--accent #3ECF74`, `--negative`, `--warning`, `--info`, fills and borders), `friendlyApiError`, `ImportHistory`/`ImportViewer`.

**Constraints found:**
1. `components/cfo/primitives.tsx` converts rupees to paise and formats money **on the client** (`rupees()`, `toPaise()`). The existing guard test `lib/noClientMath.test.ts` forbids exactly this for the CEO Hub, and CFO files are outside it. **New dashboard code must be inside that guard**: it renders `valueDisplay` strings from the server and never parses or formats money.
2. `ProvenanceBadge` has no PARTIAL or PROVISIONAL register; the completeness vocabulary of §3 needs two additive entries.
3. There is no shared pagination, sortable table, chart or export component.
4. All 22 existing sections stay (they are real direct-execution tools): they move under the new **Tools** tab unchanged (UI6).
5. The Import area shows history and a viewer but no job progress, mapping review, manual mapping or held-duplicate resolution (they did not exist in the backend before Phase 1).

**Gaps against `cfo-dashboard.md`:** overview KPIs, trust metadata on every figure, filters, charts, drill-down tables, exports, Leak Shield claim table with window status, cash/tax views, proactive alerts, the CA export, and the four seller flows in §6.

---

## 2. Architecture

```
frontend/
  app/dashboard/cfo/page.tsx                  keep; becomes the tab host (hash tabs)
  components/cfo/v2/
    overview/      OverviewTab.tsx, KpiRow.tsx, UrgentActions.tsx, HealthBand.tsx, LeakPreview.tsx, ExpensePools.tsx, OwnerAccount.tsx
    profitability/ ProfitabilityTab.tsx, MarketplacePnlTable.tsx, SkuPnlTable.tsx, TrendChart.tsx, CostBreakdown.tsx, ProfitBridge.tsx
    expenses/      ExpensesTab.tsx (wraps the existing ExpenseTrackerSection + new summaries)
    leak/          LeakShieldTab.tsx, FindingsTable.tsx, ClaimStatusSelect.tsx, DraftClaimText.tsx
    cash/          CashTaxTab.tsx, ExpectedReceipts.tsx, PayablesSchedule.tsx, GstSummary.tsx, CaExportPanel.tsx
    intelligence/  IntelligenceTab.tsx, AlertsList.tsx, GoalProgress.tsx
    data/          DataImportsTab.tsx, UploadPanel.tsx, JobProgress.tsx, MappingReview.tsx, ManualMapping.tsx, HeldRows.tsx, QualityReport.tsx
    trust/         FigureView.tsx, TrustPopover.tsx, CompletenessBadge.tsx, MissingInputs.tsx, formatStates.ts
    charts/        (Recharts wrappers only; see §7)
    tables/        DataTable.tsx (server-paginated, server-sorted), ExportButton.tsx
    filters/       FilterBar.tsx (date range, marketplace, SKU search), useCfoFilters.ts (URL state)
  lib/cfoV2/
    types.ts       FigureView, Page<T>, FilterParams ... (the contracts in §4)
    client.ts      typed fetchers (apiFetch) — no business logic
    useOverview.ts, useJob.ts, usePagedTable.ts      data hooks (loading / error / data, abort on filter change)
  components/cfo/sections/*   unchanged; mounted under Tools
```
State: server state only (hooks above); filter state in the URL (`?from=&to=&marketplace=&sku=`) so a view is shareable and reload-safe; no global store. Every hook aborts in-flight requests when filters change and exposes `{status: "loading" | "error" | "ready", ...}`; each card/section loads, fails and empties **independently**.

**No client money math (enforced):** `noClientMath.test.ts` is extended to include `lib/cfoV2/**` and `components/cfo/v2/**` with the same banned patterns (`toFixed`, `parseFloat`, `Number(`, `Math.round`, `Intl.NumberFormat`, `₹` literals, etc.). The money columns of a table arrive as `{display, status}` objects; sorting is the server's.

---

## 3. Data trust and completeness (the visible contract)

Every important figure is rendered by one component, `FigureView`, from one server object (`cfo-dashboard.md` §4):

```
FigureView {
  label, valueDisplay: string | null,               // formatted by the server; null when unavailable
  completeness: COMPLETE | PARTIAL | PROVISIONAL | ESTIMATED | UNAVAILABLE,
  register: VERIFIED | DERIVED | MANUAL | ESTIMATE | UNAVAILABLE,   // where the figure came from
  source: [{kind, label, refId}], lastUpdated, asOfDate, periodCoverage,
  engineResultRef | estimateRef, formulaVersion,
  exclusions: [{reason, count, amountDisplay}], missingInputs: [{field, why, dataRequestId?}],
  statusNotes: [string]                              // e.g. "Provisional: 3 expenses are unclassified (₹…)"
}
```
**Rules (tested):**
1. `completeness` and `register` are different axes and both are shown: a DERIVED figure can be PROVISIONAL.
2. COMPLETE is the only state drawn as a confirmed actual. PARTIAL, PROVISIONAL and ESTIMATED carry a visible badge **and** text (never colour alone) and a one-line reason.
3. UNAVAILABLE renders "—" plus the reason and a **Provide this** action (opens the existing data-request flow); never 0, never blank.
4. The trust popover (keyboard-focusable, not hover-only) lists source, last updated, exclusions and missing inputs.
5. Advertising-dependent figures also show `adSpendStatus` (`VERIFIED_ZERO | KNOWN_SPEND | MISSING_COVERAGE | UNKNOWN`); Contribution Profit shows when it rests on the legacy "no ad entries = ₹0" rule.
6. Operating profit shows PROVISIONAL / FINAL and its unclassified-expense total as a link to the list.
7. Held duplicates and quarantined rows show as an exclusion count on every figure they could affect.
8. Additive changes to shared UI: `ProvenanceBadge` and a new `CompletenessBadge` (PARTIAL, PROVISIONAL) reuse `StatusBadge` tones; no existing badge changes behaviour.

**Banned-phrase test** (`cfoWording.test.tsx`) renders every v2 component with fixtures and fails on: "recoverable", "recovered", "Ready to dispute", "Autonomous", "Auto-generated", "cash in bank", "liquid cash", "runway", "Live" (as a Leak Shield label), and on unqualified "Profit"/"Revenue"/"Sales" headings (the seven defined terms only, `cfo-unified-financials.md` §4.1).

---

## 4. API contracts the dashboard consumes

All routes: `agent.cfo` + CFO entitlement (free tenants receive the gated preview, `cfo-agent.md` §6.9); tenant from the session; every filter validated against an allow-list; money fields are `FigureView`/`{valueDisplay, ...}`, never numbers to format. Common query: `from`, `to` (ISO dates), `marketplace` (`ALL|AMAZON|FLIPKART|MEESHO`), `sku` (search text). Pagination: `page`, `pageSize` (≤ 200), `sort` (allow-listed column), `dir`. Response `Page<T> {items, page, pageSize, total, dataVersion, generatedAt}`.

| Route | Returns | Depends on |
|---|---|---|
| `GET /cfo/overview` | six KPI `FigureView`s (Contribution Profit, Net Realized Revenue, Operating Profit (+ status), Settlements received, GST / tax assets, Discrepancies identified), urgent actions, health band, top leak findings, expense pools, owner-account block (role-gated), `dataVersion` | Phase 2a metrics; cache (2b); existing P&L / leak / health actions |
| `GET /cfo/profitability/marketplaces` · `/skus` | `Page` of rows `{key, grossSales, nrr, contributionProfit, margin, completeness...}` | 2a, 2b (set-based) |
| `GET /cfo/profitability/trend` · `/bridge` | series by month; profit bridge `{from,to,delta,drivers[],other}` | 2a (`profit_bridge`, built), 2b |
| `GET /cfo/expenses/summary` · `/entries` | by category and class, unclassified list, budgets, burn; suggestions | **Phase 3** (expense model decision, `cfo-expense-model-options.md`) |
| `GET /cfo/leak/findings` · `PATCH /cfo/leak/findings/{id}/claim-status` | window-ordered findings; seller-reported status | existing `leak_finding`; claim-status lifecycle is Phase 3 |
| `GET /cfo/cash/expected-receipts` · `/payables` · `/shortfall` | forecast buckets + excluded counts; schedule; `COVERED/AT_RISK/UNKNOWN` | 2a (`EXPECTED_RECEIPTS`, `CASH_SHORTFALL_STATUS`), Phase 3 for payables entry |
| `GET /cfo/tax/gst-summary` · `/ca-export` (`POST` builds, `GET` downloads) | indicative summary with disclaimer; CA pack (XLSX/CSV) | existing GST summary; CA pack Phase 3 |
| `GET /cfo/intelligence/alerts` · `/goal` | proactive signals with Brain-1 impact figures; goal progress | Phase 3 (risk scan) |
| `GET /cfo/imports/…` and the **Phase 1 job routes** (built) | uploads, jobs, mapping, quality reports | built |
| Exports | `GET <route>?export=csv|xlsx` re-runs the same query server-side, audit-logged, CSV-injection-safe (cell prefix escaping), tenant-scoped | per route |

**Same-truth test (backend, required before any KPI ships):** for a tenant/period/filter, every overview `FigureView` equals the figure in the evidence packet the CEO would narrate for the same question (`cfo-dashboard.md` AC-UI3).

---

## 5. Build phases, with what each can honestly show

Each phase ends with the acceptance tests listed; seller-visible figures appear only when the backend metric behind them is validated.

| Phase | Delivers | Data it may show | Acceptance tests |
|---|---|---|---|
| **D0 — foundations** (no new data) | `FigureView`, `CompletenessBadge`, `TrustPopover`, `DataTable`, `FilterBar` + URL state, `ExportButton`, Recharts compatibility gate (§7), `noClientMath` extension, banned-phrase test, tab host with the existing 22 sections under **Tools** | fixtures in tests only | each trust state renders text+badge; filters round-trip the URL; table paginates/sorts via server params (mock); gate test proves a chart renders under React 19 / Next 16; guards pass |
| **D1 — Data & Imports** (backend exists today) | `UploadPanel` (marketplace, report type, optional `adapter_id`), `JobProgress` (poll `GET /cfo/jobs/{id}`; SSE later, §6), `QualityReport`, job list, cancel | **real**: upload, progress, outcome, quality report, held counts | upload → progress → done/failed with plain messages; ambiguous report type prompts the choice; cancel; duplicate re-upload; permission denial states |
| **D2 — Mapping review, manual mapping, held rows** | `MappingReview` (field table with validator evidence, confirm reasons, tax/unit questions, edits, explicit decisions), `ManualMapping` fallback, `HeldRows` (§6) | **real** for review/confirm (routes exist); manual mapping and held resolution need backend additions (§6) | silence is not confirmation; each refusal reason shown; GST-inclusive refusal explained with the limitation; keyboard-only completion |
| **D3 — Overview + Profitability** (needs Phase 2a/2b) | `GET /cfo/overview`, six KPI cards, health, urgent actions, marketplace/SKU tables, trend, cost breakdown, profit bridge | real, from validated metrics only | same-truth test; UNAVAILABLE ≠ 0; provisional operating profit labelled; responsive 375/768/1280; banned phrases |
| **D4 — Leak Shield, Cash & Tax** | findings table (window urgency), seller-reported claim status, draft claim text, expected receipts, payables, shortfall, GST summary (indicative), CA export | real as Phase 2a/3 land | Amazon provisional/withheld label; levy variances separate; no "recoverable"; forecast shows excluded lines |
| **D5 — Intelligence + CEO links** | alerts, goals, health detail, SKU concentration, margin stability, funding readiness, "Ask the CEO about this" deep links | real as Phase 3 lands | each alert carries an engine ref; deep link carries a typed context reference, never a figure |

**Why this order closes the visibility gap soonest:** D0 and D1 need no new backend and ship real seller value (upload with progress and a trustworthy quality report) while Phase 2a/2b are built. D3 is the first KPI screen and is gated on validated metrics, never on mock numbers.

---

## 6. Seller flows moved into this track (mandatory before full seller acceptance)

1. **Live progress.** D1 polls `GET /cfo/jobs/{id}` every 1 s while active (backoff to 5 s), showing rows read, a determinate bar when `totalRowsEstimate` is known, and the plain error on failure. *Later:* `GET /cfo/jobs/{id}/events` as SSE on the existing CEO event-bus pattern (tenant-keyed, **no figures in events**), polling kept as the fallback. Acceptance: progress never goes backwards; a stalled job (no heartbeat) is shown as interrupted with a retry.
2. **Mapping review.** Uses the built `GET /cfo/jobs/{id}/mapping` and `POST …/mapping/confirm`. Each field row: source column, proposed meaning, the validator's evidence, and — where `confirmReasons` is non-empty — an explicit control the seller must act on (tax inclusion, unit, date order, status table). A GST-inclusive choice is accepted by the mapping but the job will refuse it (spec §6.5a); the UI says so **before** confirm, never after.
3. **Manual mapping** (needed when no model is configured or the proposal failed). *Backend addition:* `POST /cfo/jobs/{id}/mapping/manual` accepting seller-chosen fields in the same shape as a proposal, creating a `PROPOSED` mapping with `proposed_by = SELLER` that then goes through the same validation and confirmation. Acceptance: a seller can complete an upload with `CFO_MAPPING_MODEL` unset.
4. **Held-duplicate resolution.** *Backend additions:* `GET /cfo/jobs/{id}/held` (paged: row number, rule `V-DUP-002/003`, reason, the earlier row's values side by side) and `POST /cfo/jobs/{id}/held/resolve` with `{rowNumbers, action}`, `action ∈ KEEP_EARLIER | SUPERSEDE_WITH_THIS | KEEP_BOTH_WITH_REFERENCE | DISCARD`. Effects are specified in the data-intelligence spec before they are built: `SUPERSEDE_WITH_THIS` supersedes the earlier canonical row append-only (never an UPDATE), bumps the read-model version and is audit-logged; `KEEP_BOTH_WITH_REFERENCE` requires the seller to enter the distinguishing reference. Needs `financials.adjust`. Until built, held rows stay excluded and the UI says "held — needs your decision" with the count and reason.

---

## 7. Charts (Recharts) — compatibility gate before adoption

Owner decision: Recharts, after verification. **Gate (D0):** (1) pick the Recharts release whose peer range includes React 19.2.x; (2) install with an exact pin; (3) a Vitest/jsdom smoke render of each chart wrapper; (4) `next build` succeeds; (5) the wrappers live only in `components/cfo/v2/charts/` and take already-formatted `FigureView`-style points. If any step fails, **stop and report** — no silent library swap. Charts are accessible: every chart has a table equivalent, keyboard-reachable points, colour-blind-safe palette from tokens, tooltips never the only carrier of a value, and dark/light via tokens.

## 8. Performance and quality budgets (targets, not claims)

Cached overview < 1 s; table pages < 1 s; filter change cancels the previous request; a tab loads only its own data. Accessibility: keyboard completion of every flow, visible focus, ARIA for tabs/popovers/progress, no colour-only meaning; responsive at 375/768/1280 px with 16 px gutters and no page-level horizontal scroll. Tooling to add at D0: an a11y audit helper for Vitest; a recorded manual responsive check with screenshots until an E2E runner is chosen (OQ2).

## 9. Risks and dependencies

- **KPIs wait on Phase 2a/2b.** D3 cannot ship early without inventing numbers, which is forbidden; D0–D2 are the early value.
- **Expense views wait on the expense-model decision** (`cfo-expense-model-options.md`).
- **Amazon and Flipkart figures stay provisional/withheld** until real exports validate the join keys.
- **Held-duplicate resolution and manual mapping need backend work** (§6) that is not built.
- The existing `primitives.tsx` money conversion stays only for the legacy tool forms; nothing new may import it.

## 10. Acceptance criteria

| # | Criterion |
|---|---|
| AC-DI1 | No v2 file contains client money math or a currency literal (guard test) |
| AC-DI2 | Every v2 figure is rendered through `FigureView` with completeness, register, source, last-updated and missing inputs |
| AC-DI3 | PARTIAL / PROVISIONAL / ESTIMATED / UNAVAILABLE are never drawn as confirmed actuals; UNAVAILABLE never shows 0 |
| AC-DI4 | The banned-phrase and defined-terms test passes on every v2 component |
| AC-DI5 | Overview figures equal the CEO evidence-packet figures for the same tenant/period/filter |
| AC-DI6 | Filters, pagination, sort and exports are server-side, allow-listed and tenant-scoped; filter state lives in the URL |
| AC-DI7 | All 22 existing tool sections still work, mounted under Tools |
| AC-DI8 | Upload → progress → result, mapping review/confirm, manual mapping and held-row resolution each have a complete, keyboard-operable flow |
| AC-DI9 | Layout holds at 375, 768 and 1280 px; every chart has a table equivalent and keyboard access |
| AC-DI10 | Owner-account and write actions are hidden without `financials.adjust`; free tenants see the preview |

## 11. Explicit open questions

| # | Question |
|---|---|
| OQ1 | Merge order with `feat/ui-redesign` (its `KpiTile` / `CfoOverview`): reuse after reconciliation, or keep the v2 primitives independent (recommended) |
| OQ2 | E2E and accessibility tooling (Playwright and an axe integration are not installed) |
| OQ3 | Export row cap and whether very large exports run as background jobs |
| OQ4 | SSE vs polling as the primary progress transport once Redis-backed cross-worker events exist |
| OQ5 | GST due-date source and CA-review gating wording for tax-adjacent labels |
