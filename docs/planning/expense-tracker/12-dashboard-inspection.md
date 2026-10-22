# Expense Tracker dashboard — read-only inspection (2026-10-16)

Inspection only: no code, schema, migration or spec was changed. Everything below is read from the repository on `feat/pnl-calculator-and-expense-tracker`; anything that is a design choice is labelled **PROPOSED** and needs owner approval. Authority: `docs/decisions/phase1-decisions.md` (errata) over the frozen `docs/specs/expense-tracker.md`.

**Product owner clarification (recorded as given):** the Expense Tracker has its **own dedicated dashboard under the existing CFO / Profit & Finance navigation** — not a small section of the CFO chat page, not a new top-level product, not a new agent. One CFO, one dedicated Expense Tracker dashboard, one authoritative engine. Contents: overview, expense list, category breakdown, recurring commitments, review queue, and expense-management actions per the spec and decision record.

## 1. Does a dedicated dashboard route exist?
**No.** Current signed-in routes (`frontend/app/dashboard/**`): `/dashboard`, `/dashboard/ceo-hub`, `/dashboard/notifications`, `/dashboard/pi`, `/dashboard/competitors`, `/dashboard/cfo`, `/dashboard/pnl-calculator`, `/dashboard/cmo`, `/dashboard/agents` (each has `page.tsx` and `layout.tsx`; `/settings` sits outside `dashboard`).

The only expense UI is `frontend/components/cfo/sections/ExpenseTrackerSection.tsx`, rendered inside `frontend/app/dashboard/cfo/page.tsx` in the **"Cash & reconciliation"** tab (tab ids `overview`, `profitability`, `cash`, `gst`, `anomalies`, `import`). It is a form (category from the legacy five: advertising, packaging, storage, logistics, other; amount; optional marketplace; description) plus a list and a budget form, calling `PUT/GET /api/v1/cfo/expenses`, `PUT /expenses/budget`, `GET /expenses/budget-status`. It has no category breakdown, no review queue, no recurring view and no per-period dashboard.

## 2. How CFO navigation works, and what a dedicated route would need
- **Sidebar model:** `frontend/lib/navigation.ts`. `NAV_GROUPS` ("Start", "Business") plus `FOOTER_NAV`; the CFO entry is `{ id: "cfo", label: "Profit & Finance", href: "/dashboard/cfo" }`. There is **no nested navigation**: an item is a flat link. `isActive` matches a pathname by prefix (`/dashboard/cfo/...` keeps "Profit & Finance" highlighted).
- **Titles:** `PAGE_COPY` supplies each page's title and subtitle; every route's `layout.tsx` sets `metadata.title = pageTitle("<id>")` (see `app/dashboard/cfo/layout.tsx`). Menu labels and page titles are the same constants by design.
- **In-page navigation:** the CFO page uses `components/ui/Tabs.tsx` (accessible tab strip) with `lib/useHashTab.ts` (tab mirrored into `location.hash`).
- **Tests that pin navigation:** `frontend/lib/navigation.test.ts` (lists the dashboard routes and their `page.tsx`/`layout.tsx`), `frontend/components/dashboard/shellFrame.test.tsx`. The Profit Calculator integration changed both when it added a nav item, so a new route means updating them.

**What a dedicated route requires:** a new `app/dashboard/cfo/expenses/page.tsx` and `layout.tsx` (title via a new `PAGE_COPY` entry), wrapped in the existing `DashboardShell`; updates to the two navigation tests; no backend change for navigation itself.

**PROPOSED navigation pattern (needs owner approval; nothing is built):**
- **N1 (recommended):** route `/dashboard/cfo/expenses`, reached from a prominent link/card at the top of the CFO "Cash & reconciliation" tab and from the CFO page header. The sidebar is unchanged (CFO stays highlighted by prefix). Smallest change, no new navigation pattern, honours "under the existing CFO navigation".
- **N2:** N1 plus a new sidebar item "Expenses" under "Business" pointing at the same route. The nav model has no nesting, and the CFO item's prefix match would highlight both items, so this needs a small `isActive` rule (for example an `exact` CFO item or an explicit `match` list). This is a new navigation pattern.
- **N3 (not recommended):** a seventh tab on the CFO page. It keeps everything on the existing CFO page, which is the "small section of the CFO page" the owner ruled out.

## 3. The design system
- **"Cyber-Luxe" is not defined anywhere in the repository.** `docs/design/ui-ux-phase1-audit.md` (§1.2, line 21) states: *"No such name anywhere in the repo."* The direction it records instead is near-black `#0A0B0A` base, brand green `#3ECF74`, Inter, glass/blur cards. `docs/design/design_status.md` says branding, colours and typography are **not final** and must stay configurable. A grep of the repo for the name found only that audit sentence. The owner should confirm whether "Cyber-Luxe" is the intended name for this direction or a separate reference.
- **Where the system actually lives:** CSS custom properties in one `:root` block in `frontend/app/globals.css` (about 90 tokens), layout helpers such as `.mt-content`, `.mt-stack`, `.mt-ledger`; the exploratory references in `docs/design/exploratory/` and `docs/design/frontend-design/` (`Metrion App.dc.html`) are visual references only.
- **Reusable components** (`frontend/components/ui/`): `Section`, `Card`, `MetricCard`, `Stat`, `Tabs`, `StatusBadge` (tones accent/warning/negative/info/neutral), `ConfidenceBadge`, `ProvenanceBadge`, `EvidenceStateBadge`, `EmptyState`, `ErrorNotice`, `LoadingState`, `DetailDrawer`, `FormField`, `CostInput`, `Icon`, `Button`. From CFO: `components/cfo/primitives.tsx` (`Field`, `TextInput`, `SelectInput`, `SubmitButton`, `ErrorText`, `CfoMetricResultRow`) and `DataRequestNote.tsx`. Page frame: `components/dashboard/DashboardShell.tsx`.

## 4. Data flow without duplicating calculation, auth or logic
Browser (`apiFetch`, `lib/api.ts`) → `/api/v1/cfo/...` (`backend/src/backend/api/v1/cfo.py`: Clerk auth, tenant context, entitlement) → `backend/src/backend/services/cfo_actions.py` → `packages/calc-engine` (Brain 1) → Postgres under RLS.
- **Dashboard totals must come from the engine (AC17, test F7).** New engine functions already exist for this (kickoff Step 2, committed): `ledger_feed` (`formulas/ledger_feed.py`) produces the counted total, by-category, by-cost-class, recurring, review-queue and "including unresolved" amounts; `mint_expense_metrics` (`api/expense_metrics.py`) stamps them as `EXPENSE_*` metric results with `engine_result_ref`. The dashboard should render those and cite the ref; it must not sum anything.
- **The legacy list does sum in the backend:** `list_expenses` returns `totalPaise` computed with `sum_paise` in `cfo_actions.py` ("presentation-layer aggregation"), and it infers a period from the free-text `target_ref` (`YYYY-MM-DD` or `YYYY-MM`) because `manual_adjustment` has no date column. That is the legacy path (kept until cut-over, X1); the new dashboard must not reuse it for totals.
- **No money math in the browser:** `frontend/lib/noPnlClientMath.test.ts` is the existing precedent (bans `toFixed`, `parseFloat`, `Number(`, `Math.`, `Intl.NumberFormat`) for the Profit Calculator, and `lib/pnlText.ts` (`rupeesToPaise`, `formatPaise` on integer strings) is the float-free way to parse and format paise. By contrast `components/cfo/primitives.tsx::rupees()` divides by 100 and calls `toFixed(2)` — acceptable for the legacy form, but the new dashboard should use the `pnlText.ts` approach and carry the same kind of guard test.
- **Auth and entitlement stay on the server;** the frontend duplicates none of it.

## 5. State display
Two separate fields, never merged:
- **Review state:** `draft`, `pending_review`, `confirmed`, `voided` (Round 6 decision; a correction is a new linked entry). **Which states feed the engine (engine §5.17 (5), Round 6; `ledger_feed.py`):** only `confirmed` rows are counted in any pool. `pending_review` rows are never summed into a pool; they appear in the review-queue amount and in the "including unresolved" view. `draft` and `voided` are not counted. (Unmapped advertising/storage identifiers are counted as business-level and *also* listed in the review queue.)
- **Payment status:** `unpaid`, `partially_paid`, `paid`, `unknown` (spec P3). **It does not feed the engine:** "payment status never changes economic margin". It is display and filtering only.
- Treatment (`incremental`, `already_in_settlement`, `informational`) is a third, separate attribute; only `incremental` counts.

## 6. Permissions
- **Writes:** `financials.adjust` (EXP-05; no new key). Today `PUT /cfo/expenses` checks `agent.cfo`, the CFO entitlement, then `financials.adjust` in-handler (`api/v1/cfo.py::put_expense`).
- **Viewing:** the existing read permission. `GET /cfo/expenses` needs only `agent.cfo` and the CFO entitlement (the route's own docstring: "viewing an existing manual input is not creating one"). Q34 export follows the existing financial read permission.
- **Frontend limitation:** `SessionResponse` (`lib/api.ts`) carries `role` but **not the permission set**, so the UI cannot know whether a partner holds `financials.adjust`. Write controls therefore cannot be hidden reliably; the server's 403 must be surfaced as a plain message (the CFO page already uses `friendlyApiError`). Exposing the permission set to the frontend would be a backend/session change and is **PROPOSED, not decided**.
- The known COGS limitation (`financials.adjust` also covers COGS) must be visible to owners granting it (G3).

## 7. Reuse versus missing
| Need | Reuse | Missing |
|---|---|---|
| Page frame, title, tabs | `DashboardShell`, `PAGE_COPY`, `Tabs`, `useHashTab`, per-route `layout.tsx` | the route and its `PAGE_COPY` entry; navigation tests updated |
| Cards, status, empty/error | `MetricCard`, `Stat`, `StatusBadge`, `EmptyState`, `ErrorNotice`, `LoadingState`, `DetailDrawer`, `Section` | review-state and payment-status badge mapping |
| Forms | `FormField`, `Field`/`TextInput`/`SelectInput`/`SubmitButton`, `CostInput` | the ledger entry/edit/void form (vendor, category, date, amount, treatment, channel, SKU tag, payment status) |
| Money formatting | `lib/pnlText.ts` (integer strings) | a no-float guard test for the new files |
| Totals and breakdowns | engine `ledger_feed`, `mint_expense_metrics` (committed) | routes that run the feed and return `EXPENSE_*` results with refs; frontend types and contract entries |
| Ledger data | none (legacy `manual_adjustment` rows only) | ledger tables and migration (Step 3), list/CRUD routes |
| Review queue, recurring | engine fields `review_queue`, `recurring_total` exist | review actions, recurring templates and materialisation (Step 4) |
| Permission awareness | server-side checks | permission set in the session (PROPOSED) |

## 8. Smallest implementation plan across kickoff Step 3 and Step 4 (PROPOSED)
**Step 3 (ledger and management):**
1. Route skeleton `/dashboard/cfo/expenses` with the shell, title and navigation tests (per the approved navigation option).
2. Ledger tables and migration (see `13-step3-proposals.md` §3), append-only events, RLS.
3. Backend routes for create / edit / void / review / payment update and a paginated **expense list** read, `financials.adjust` on writes.
4. Dashboard **expense list** and the entry/edit/void form with the two status fields shown separately; controlled categories.
5. **Review queue view** (rows in `pending_review`, unmapped identifiers) with the review action.

**Step 4 (engine feed and recurring):**
6. A route that runs `ledger_feed` and mints `EXPENSE_*` results for the **overview** and **category breakdown**, rendering `engine_result_ref` and as-of; F7 reconciliation test against the P&L.
7. **Recurring commitments** (monthly and per-order templates, materialised as `pending_review`) and the recurring view.
8. Feed the unallocated lines and total profit into the Profit & Finance P&L display (after the consumer-spec caveats and the release date).

Later (kickoff Step 5): CSV import, draft-from-chat (G6), amortization, multi-SKU assignment and the accountant export, each in its own slice.
