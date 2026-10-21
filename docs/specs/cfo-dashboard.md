# Metrion — CFO 2.0 Dashboard Specification

**Status:** Draft for review (CFO 2.0, track D)
**Prerequisites:** `cfo-query-planner.md` (read model, cache, evidence packets) · `cfo-unified-financials.md` (definitions, wording) · `cfo-data-intelligence.md` (data trust inputs) · `cfo-agent.md` · `docs/design/design_status.md` (branding is not final — keep configurable)
**Visual reference:** the supplied CFO dashboard screenshot (dark theme, green accents, left sidebar, elevated cards). Preserve the design language; correct the wording per §3.

The dashboard and the CEO read **the same financial truth**: `metric_result` rows and cached evidence packets produced by Brain 1 through the planner. The dashboard computes nothing and contains no hardcoded or model-generated financial figure.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| UI1 | Preserve Metrion's dark theme, green accents, sidebar (off-limits for change), elevated cards. | Owner brief §8 |
| UI2 | **5–6 KPI cards** and urgent actions on the overview; detail in tabs/sections. | Owner brief §8 |
| UI3 | **All values come from Brain 1 via the read-model endpoint.** No client arithmetic on money; no hardcoded figures; no LLM-generated figures. | CLAUDE.md |
| UI4 | **Recharts** for charts, after compatibility verification with the installed React/Next versions (§8). | Owner decision 2026-10-21 |
| UI5 | **Wording corrections accepted** (§3). | Owner decision 2026-10-21 |
| UI6 | **Existing CFO tools are preserved** (the 22 sections), relocated into a Tools area; none removed. | Owner brief §8 |
| UI7 | Branding/colours configurable via design tokens; business logic never coupled to them. | design_status.md |
| UI8 | Frontend never filters for security; filters are request parameters validated server-side. | CLAUDE.md |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Overview endpoint | One `GET /api/v1/cfo/overview?from&to&marketplace&sku` returning KPI cards, alerts, top leaks, expense pools — each figure with trust metadata. Served from cache when `data_version` unchanged. | One round trip; <1 s cached target. |
| D2 | Navigation | Tabs: **Overview · Profitability · Expenses · Leak Shield · Cash & Tax · Intelligence · Data & Imports · Tools** (existing sections live under Tools and are linked from the relevant tab). | Clean, extends current 6-tab layout. |
| D3 | Relationship to `feat/ui-redesign` | Reuse its `KpiTile`, `CfoOverview`, `ComingSoonCard` components *if and when* that branch is reconciled with main; CFO 2.0 does not depend on it and builds equivalent primitives in `components/cfo/primitives.tsx` otherwise. | The redesign branch is unmerged and partial. |
| D4 | Drill-down | Every KPI/chart element opens a server-paginated table of the underlying lines with source refs; export CSV/XLSX of the *filtered* view. | Trust + audit. |
| D5 | Streaming UX in CEO chat | Stage events ("Asking the CFO…", "Planning…", "Grouping by marketplace…", "Finalizing…") rendered in the existing CEO progress UI. | Owner brief §5. |

---

## 3. Wording rules (accepted corrections applied to the reference)

| Reference wording | Required wording | Reason |
|---|---|---|
| "Recoverable ₹X", "Total recovered", "Ready to dispute" | "Discrepancy identified ₹X", "Ready to review" | cfo-agent D2 |
| Amazon finding shown as confirmed | Amazon: "Provisional" or "Withheld — pending match-key verification" | cfo-agent AC5 |
| "Autonomous Strategic Directives", "Auto-generated packet" | "Recommended actions", "Draft claim text (copy)" | recommend-only (C7) |
| "Settlement cash in bank", "Liquid cash in bank", "Capital runway" | "Settlements received", "Expected settlements" (no runway figure) | bank data out of scope (U5) |
| "Leak Shield (Live)" | "Leak Shield — last checked <time>" | uploads only |
| Owner drawings among operating expenses | Separate "Owner account" block, excluded from P&L, role-gated | unified-financials D2 |
| "GST payable due Oct 20" | "GST (indicative) — due date from calendar, verify with your CA" | management-grade GST |
| "Profit", "Revenue" unqualified | One of the seven defined terms (unified-financials §4.1) | AC-U1 |

---

## 4. Data trust model (every important figure)

```
FigureView {
  label, value_display, value_paise|fraction|count|null,
  status: VERIFIED | DERIVED | MANUAL | ESTIMATED | UNAVAILABLE | PARTIAL,
  source: [ { kind: REPORT|ADAPTER|MAPPING|MANUAL|ESTIMATE, label, ref_id } ],
  last_updated: timestamp, as_of_date, period_coverage,
  engine_result_ref | estimate_ref,
  missing_inputs: [ { field, why, data_request_id? } ],
  exclusions: [ { reason, count, amount_display } ],
  formula_version
}
```
UI: a status badge on each card (colour *and* text/icon, never colour alone), a hover/focus popover listing source, last updated, exclusions and missing inputs with a "Provide this" action that opens the existing data-request flow. `UNAVAILABLE` renders as "—" plus the reason, never 0. `ESTIMATED` figures carry an estimate badge and cite `estimate_ref`. Mapped sources show "Mapped — confirmed by you".

## 5. Screens and content

### 5.1 Overview (default)
KPI cards (6): **Contribution Profit** (+ margin, labelled "not accounting net profit") · **Net Realized Revenue** · **Operating Profit (management)** · **Settlements received** (+ avg lag) · **GST / Tax assets** (GST indicative; TCS+TDS "tax asset — not in P&L") · **Discrepancies identified** (count, amount, nearest window). Below: Urgent actions (ranked `StrategicSignal`s with Brain-1 impact figure), Financial Health band, expense pool bar (burn), top Leak Shield claims by window urgency (Amazon provisional/withheld), recommended actions panel, owner-account block (role-gated). Filters bar: date range, marketplace (All/Amazon/Flipkart/Meesho), SKU search.

### 5.2 Profitability
Marketplace-wise and SKU-wise P&L tables (server-paginated, sortable); trend chart (CP and margin by month); cost breakdown (stacked bar by component); period comparison with the **profit bridge** (waterfall: drivers + OTHER); unavailable cells explained.

### 5.3 Expenses
The existing Expense Tracker integrated: category-wise spend, budget vs actual, burn rate (deterministic, from entries), recurring costs, anomalies, classification and ownership confirmations (data requests), upload expense CSV/XLSX (data-intelligence §6.7), possible-duplicate review queue, receipt attachment by reference.

### 5.4 Leak Shield
Findings table (category, marketplace, order ids, amount, age, window status, claim status), sort by window urgency then amount; seller-reported claim status updates; "Copy draft claim text"; Amazon/Flipkart provisional labels; levy variances in a separate block.

### 5.5 Cash & Tax
Expected settlements (forecast table/chart with excluded-lines count), payables schedule (seller-entered), shortage warnings (`COVERED/AT_RISK/UNAVAILABLE`), settlement tracking (lag distribution), GST period summary (indicative, disclaimer), TCS/TDS schedule, **CA export pack** download (XLSX/CSV, provenance per line, open data requests listed).

### 5.6 Intelligence
Proactive alerts (from the risk scan), financial health detail, prioritized recommendations, SKU concentration, margin stability, goals/progress (`seller.goal`), funding readiness (completeness report, no score). Each item has "Ask CEO about this" (deep-links into the CEO Hub with context).

### 5.7 Data & Imports
Import history, data-quality reports, mapping review/confirm UI (side-by-side source column → canonical field with validator evidence, edit, confirm), job progress, open data requests, per-source freshness.

### 5.8 Tools
Existing sections (period P&L, pricing curve, landed cost, supplier ranking, batch size, reconcile, cash reconciliation, GST line/period/lookup, anomaly check, etc.), unchanged in behaviour.

## 6. Interactions
Filters apply to every figure on the page via request params; filter state in the URL. Drill-down tables: server pagination (page, size ≤ cap), server sort (allow-listed columns), consistent empty/error/unavailable states. Exports: CSV/XLSX of the current filtered view, generated server-side from the same query, audit-logged, CSV-injection-safe (cell prefix escaping). Charts: accessible (text alternative table, keyboard focus on points, colour-blind-safe palette, tooltips never the only carrier of information), dark and light via tokens. Responsive: single column below 768 px with 16 px gutters; KPI cards wrap 3→2→1; tables scroll within their container, never the page.

## 7. Same-truth integration
`GET /api/v1/cfo/overview` and the CEO planner both resolve through the same service layer and the `metric_result` store; a test asserts that for a given tenant/period/filter every overview figure equals the evidence-packet figure the CEO would narrate (AC-UI3). Cache keyed per cfo-query-planner D2; the response includes `data_version` and `generated_at` so the UI can show "last updated".

## 8. Recharts compatibility gate
Before adding the dependency: verify the Recharts release supports the installed React (19.x) and Next (16.x) with a smoke render under Vitest/jsdom and `next build`; pin an exact version; if incompatible, stop and report — do not swap libraries silently. Charts are isolated in `components/cfo/charts/` so a replacement never touches data code.

## 9. AI requirements
None in the render path. CEO narrates; the dashboard shows Brain 1 figures. "Ask CEO" opens the Hub with a typed context reference, never figures embedded in a prompt.

## 10. Authorization and security
Routes require `agent.cfo` + CFO entitlement (free tenants get the gated preview, cfo-agent §6.9, in place of the overview). Owner-account block requires `financials.adjust`. Server validates every filter and sort key against allow-lists; exports and drill-downs are tenant-scoped via RLS. No tenant id in any request.

## 11. Edge cases
E1 no data yet → onboarding card with the upload CTA, never zeros · E2 partial period · E3 marketplace filter with no data · E4 all KPIs unavailable (e.g. no COGS) → ranked "provide this" list · E5 stale data (older than threshold) → banner · E6 loading and error states per card, independently · E7 very long SKU lists (server search) · E8 print/export of unavailable figures shows "Unavailable", not blank · E9 free tenant → preview · E10 role without `financials.adjust` hides owner account and write actions.

## 12. Production-validation blockers
PV1 cached-KPI < 1 s and drill-down latencies are targets pending a recorded benchmark · PV2 accessibility audit (WCAG AA) on charts and popovers · PV3 CA review of every tax-adjacent label · PV4 design tokens/branding not final.

## 13. Acceptance criteria

| # | Criterion |
|---|---|
| AC-UI1 | No hardcoded or client-computed financial figure exists in dashboard code (lint + test) |
| AC-UI2 | Every important figure shows status, source, last updated, and missing inputs/exclusions |
| AC-UI3 | Overview figures equal the planner evidence-packet figures for the same tenant/period/filter |
| AC-UI4 | `UNAVAILABLE` never renders as 0 |
| AC-UI5 | All §3 wording rules are applied; banned phrases absent (test greps rendered output) |
| AC-UI6 | Filters (date, marketplace, SKU), pagination, sort and exports work server-side and are tenant-scoped |
| AC-UI7 | Existing 22 tool sections remain reachable and behave as before |
| AC-UI8 | Layout holds at 375, 768, 1280 px without page-level horizontal scroll |
| AC-UI9 | Charts have table equivalents and keyboard access |
| AC-UI10 | Owner-account block hidden without `financials.adjust` |

## 14. Test scenarios
TUI1 overview render with fixture JSON incl. one UNAVAILABLE KPI · TUI2 banned-phrase scan · TUI3 filter change refetches with params, URL updates · TUI4 drill-down pagination · TUI5 export content equals filtered table · TUI6 permission hides owner block · TUI7 free tenant sees preview · TUI8 same-truth backend test (overview vs packet) · TUI9 responsive snapshots · TUI10 chart table-equivalent present · TUI11 existing tool sections smoke render.

## 15. Explicit open questions
| # | Question |
|---|---|
| OQ1 | Whether `feat/ui-redesign` is merged before or after this track (D3) |
| OQ2 | Sidebar entries for CFO sub-areas (sidebar is off-limits; tabs used instead) |
| OQ3 | Export row cap and whether large exports run as background jobs |
| OQ4 | GST due-date calendar source (unified-financials OQ5) |
