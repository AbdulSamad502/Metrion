# Expense Tracker — 03 Architecture Options

> **Overlay, 2026-10-15 — approved decisions now fix parts of this document** (`docs/decisions/phase1-decisions.md`): **EXP-01** dedicated append-only ledger + explicit Brain 1 contract, treatments `incremental | already_in_settlement | informational`, `replaces_input` dropped (so §2 option **B** is adopted; A and C are historical); **EXP-02** versioned restatement; **EXP-03** chat may only prepare a draft that pre-fills **vendor, category and date**; the seller types description and amount on the form and confirms there (§4 below is superseded); **EXP-05** **no new permission key — `financials.adjust` governs ledger writes** (an interim `expenses.write` proposal is superseded); **EXP-02** no automatic restatement, formula version labelled, release date is a placeholder; **EXP-06** overhead unallocated by default. Everything not named there remains a proposal. The canonical text is `docs/specs/expense-tracker.md`.

**Status:** planning. Options and proposals; **only the decisions named in the overlay above are approved**. Table and endpoint sketches are conceptual (no migration or code is written by this run). Decision ids (D*) refer to `02-decision-register.md`.

---

## 1. Constraints any option must satisfy (verified)
1. Money arithmetic, allocation and period totals live in Brain 1 (`packages/calc-engine`); the LLM and the browser never compute or alter a figure (CLAUDE.md hard rule; guard tests `noClientMath`, `noPnlClientMath`).
2. Every tenant-owned table carries `tenant_id`, `FORCE` RLS and explicit application filtering; no endpoint accepts a client `tenant_id`; the active organization is the verified Clerk `org_id` (`auth/context.py`).
3. Ledger writes need **`financials.adjust`** (EXP-05; OWNER implicit, PARTNER deny-by-default; no new key) plus `agent.cfo` and the CFO entitlement, checked server-side at the moment of the write (`api/v1/cfo.py::put_expense`).
4. Provenance: each figure carries the stamp tuple (`formula_version`, `config_version`, `canonical_data_version`, adjustment/expense set, `as_of_date`, `computed_at`).
5. Missing is not zero. The documented exception (absent ad/other spend = 0, engine §5.6) must be displayed as "not entered".
6. No retention or storage change; no receipt files in V1.0 (D12).

## 2. Structural options for the expense store (answers D1)

| | **A. Extend `manual_adjustment`** | **B. New append-only expense tables + engine reader (ADOPTED, EXP-01)** | **C. Status quo, caller-supplied lists** |
|---|---|---|---|
| Holds date, vendor, statuses, source ref, treatment | Only by stuffing keys into `value` jsonb (registry amendment) | Native columns | No |
| Edit across category/period, delete/void | Not possible (same target+field supersede only; no WITHDRAWN writer) | Event log: `edited`, `voided` | No |
| Single audit store for manual input | Yes | Two stores (inputs vs expenses) — reverses `cfo-agent.md` ~113 "removed by design" | Yes |
| Reaches the P&L | Needs a reader anyway | Engine reader, stamped | No (B2 stays) |
| New RLS/grants/migration | Small | Full set, plus migration of old rows | None |
| Idempotency | Needs new unique key on jsonb | Native `(tenant_id, idempotency_key)` unique | No |
| Risk | Awkward semantics, poor reporting | More surface, needs owner reversal | Leaves the TRUST failure |

**Adopted (EXP-01): B**, because the product fields and the edit/void/audit requirements cannot be met by A without distorting `manual_adjustment`. A is the fallback if the owner will not reverse the "removed by design" decision; in that case the V1.0 scope shrinks (no vendor, no delete, no payment status).

## 3. Candidate design (option B)

### 3.1 Conceptual data model (not DDL)
All tables: `tenant_id uuid not null`, `FORCE ROW LEVEL SECURITY` with the standard `tenant_isolation` policy, app role has `INSERT`/`SELECT` only (no `UPDATE`/`DELETE`), same pattern as `manual_adjustment`.

- **`expense_record`** (current state is derived from events; this row is the immutable creation): `id`, `tenant_id`, `idempotency_key`, `source_kind` (`manual | csv | quick_add`), `source_ref` (import batch id + row, or proposal id), `created_by`, `created_at`.
- **`expense_event`** (append-only, the source of truth for state): `id`, `tenant_id`, `expense_id`, `seq`, `event_type` (`created | edited | voided | reviewed | payment_updated`), `effective_date`, `category`, `cost_class`, `treatment` (`incremental | already_in_settlement | informational`), `amount_paise` (signed bigint, > 0 enforced), `gst_basis` (`inclusive | exclusive | none`), `gst_amount_paise`, `itc_eligible_flag` (informational), `vendor`, `channel_scope` (`business | amazon | flipkart | meesho | other:<label>`), `sku`, `payment_status`, `paid_amount_paise`, `review_status`, `description`, `reason`, `actor`, `recorded_at`. Unique `(expense_id, seq)`.
- **`expense_recurring_template`** + **`expense_template_run`** (P4): template fields as above plus `cadence`, `start_date`, `end_date`; a run row per materialized period with a unique `(template_id, period)` so repeats are idempotent.
- **`expense_import_batch`** / **`expense_import_row`**: file hash, row number, status (`valid | error | duplicate | probable_duplicate | imported`), error text, resulting `expense_id`.
- **`expense_proposal`** (draft-from-chat, EXP-03): `id` (server-minted), `tenant_id`, `requested_by`, `payload_hash`, `payload`, `expires_at`, `status` (`open | confirmed | expired | cancelled`), `confirmed_expense_id`.
- **Not stored in V1.0:** receipt files, `currency` (INR-paise only, X4).

### 3.2 Data flow
```
Seller (form | CSV | confirmed proposal)
   │  HTTPS, Clerk JWT (active org = org_id claim)
   ▼
FastAPI route  ──require_auth(agent.cfo) ──has_permission(financials.adjust) ──entitlement
   │  strict Pydantic model (extra=forbid, integer-string money, caps, no tenant_id)
   ▼
Expense service (backend/services/expenses.py)        ← no arithmetic
   │  1. resolve tenant from ctx  2. duplicate/overlap checks (deterministic)  3. INSERT expense_event (idempotent)
   ▼
Postgres (RLS FORCE)  ── expense_event (append-only)
   │
   ▼  read by
Brain 1:  calc_engine.formulas.expense_feed.expense_pool_totals(period, channel, as_of, watermark)
   │      → sums by class/treatment, flags overlaps, never zero-fills a missing basis
   ▼
compute_period_pnl  (advertising / other / packaging / storage / logistics pools from the feed, not request bodies)
   ▼
metric_result (stamped: formula_version, expense watermark, as_of)  →  CFO UI (renders, never computes)
```
CFO/CEO narration may explain stored figures but never originates one.

### 3.3 Service and API boundaries (proposed)
| Route | Method | Permission | Notes |
|---|---|---|---|
| `/api/v1/cfo/expense-records` | POST | `agent.cfo` + `financials.adjust` + entitlement | Create; requires `Idempotency-Key` header or body key; one `expense_event`. |
| `/api/v1/cfo/expense-records/{id}` | GET | `agent.cfo` | Current state + event history. |
| `/api/v1/cfo/expense-records/{id}/edit` | POST | write set | Appends `edited` with `reason` required. |
| `/api/v1/cfo/expense-records/{id}/void` | POST | write set | Appends `voided`; never deletes. |
| `/api/v1/cfo/expense-records` | GET | `agent.cfo` | Filters: month, category, channel, review status, `as_of`. |
| `/api/v1/cfo/expense-summary` | GET | `agent.cfo` | Monthly totals and category breakdown **from the engine feed**, with `as_of` timestamp and watermark. |
| `/api/v1/cfo/expense-imports` | POST (preview), POST `/{id}/confirm` | write set | Two-step. |
| `/api/v1/cfo/expense-proposals`, `/{id}/confirm` | POST | write set | Draft-from-chat only (EXP-03); creates a draft, never an expense. |
Existing `PUT/GET /cfo/expenses` keep working during migration (X1) and are retired by a decision, not silently.

### 3.4 Financial engine integration
- New pure function in `packages/calc-engine/src/calc_engine/formulas/` (e.g. `expense_feed.py`): inputs are already-fetched event rows; output per pool `(period, channel scope, class)` with `Paise` totals, `treatment` exclusions, confidence (`MANUAL`), and a list of **named gaps** (e.g. "advertising: none entered", "allocation basis unavailable for 2026-09").
- **Contribution margin vs fully allocated profitability are separate outputs.** Overhead (rent, salaries, software, utilities) appears only in the allocated figure and only with an explicitly chosen basis (`NET_REVENUE | UNITS | ORDERS`); allocation uses the existing `allocate_pool`/`largest_remainder_allocate` so shares sum exactly to the pool; no basis ⇒ unallocated and shown.
- Double-counting guards, in order: (1) marketplace fee categories are not offered; (2) `treatment=already_in_settlement` rows are stored and excluded; (3) a period/channel that already has settlement-derived advertising or storage cost raises a named overlap warning with the settlement figure from the engine; (4) probable-duplicate flag; (5) idempotency key. None uses LLM judgement.
- COGS remains `cogs_per_unit`; an expense never "replaces" it (D1).
- Stamp: every derived `metric_result` records the expense watermark (max `recorded_at`/event id included) and the **formula version** so a figure is reproducible by replaying events up to it; results already reported are never recomputed automatically (EXP-02 policy).

### 3.5 Authorization and tenant isolation
- Writes: `agent.cfo` + `financials.adjust` (+ CFO entitlement) in-handler, as `put_expense` does; reads: `agent.cfo`. Known limitation: `financials.adjust` also covers COGS and every other registry field (EXP-05).
- Confirm paths re-run `resolve_auth_context`, then compare `(tenant_id, app_user_id)` with the stored proposal/batch; mismatch ⇒ 404 (no existence oracle).
- Each new query includes `WHERE tenant_id = :tenant_id` in addition to RLS. Every route is added to the every-route 401/403 parametrised tests automatically.
- Draft-from-chat (EXP-03): the LLM may pre-fill only vendor, category and date (never amount, description or treatment); the server sets tenant, proposal id, treatment default, and recomputes nothing monetary (D3).

### 3.6 Auditability
`expense_event` is the audit log: actor, timestamp, event type, before/after through the event sequence, mandatory `reason` on edit and void. Direct writes also write an `agent_run` (`trigger_type=DIRECT`, `trigger_ref=cfo.expense_*`, as `post_pnl_scenario` does), closing the known audit gap for this feature (X3). No row is ever updated or deleted by the app role.

### 3.7 Idempotency
- Create/import/draft-confirm carry an idempotency key unique per tenant: a retry returns the original record with `200` and `idempotent_replay: true`.
- CSV: batch keyed by file hash; row keyed by `external_id` or normalised `(date, vendor, amount, reference)`; re-upload reports "already imported".
- Proposals: single-use confirm (`status` transition guarded by a unique index/`WHERE status='open'` update in the same transaction), expiry enforced from the server clock.
- Recurring materialization: unique `(template_id, period)`.

### 3.8 Receipts, retention (not built)
Reference field only (free text / URL-less id). No file upload, no object storage, no retention claim until D12 closes.

## 4. Options for chat quick-add (D3) — **superseded by EXP-03**
| Option | Description | Verdict |
|---|---|---|
| A | Reverse C21 for expenses; build on approval workflow | Largest dependency; needs owner decision + S2/S3 |
| B | No quick-add in V1.0 | Safe; matches registry and classifier today |
| C | CEO may only *draft* a proposal; confirm happens on the form surface with the seller's click | Smallest safe increment; still needs a C21 amendment because it creates a stored proposal |
**Superseded by EXP-03.** Approved flow: chat prepares a draft pre-filling vendor, category and date; the seller types description and amount and confirms on the form; no chat write. E30/T36 amended 2026-10-15; the registry key/effect class, §6.33 scoping sentence and classifier route are follow-ups needing owner approval.

## 5. Options for recurring expenses
| Option | Description | Verdict |
|---|---|---|
| A | Store templates; compute commitments for display only (no rows) | Safe, no scheduler; commitments shown, never posted |
| B | Materialize rows monthly via an in-process periodic thread (pattern of `main.py` sweeps) | Per-worker duplication risk; needs the unique `(template, period)` guard and a lease |
| C | External scheduler/queue | New infrastructure; not in the stack |
Recommended: A for V1.0 (templates feed the "recurring commitments" view and a **"post this month's expenses" button** that creates idempotent records), B later behind a lease.

## 6. Risks specific to the architecture
Reversing a recorded decision (B); migrating undated legacy rows; engine-spec amendments (registry, allocation default); two sources of manual input if COGS stays in `manual_adjustment`; per-worker periodic threads; UI that shows "saved" before the engine uses a figure (mitigate: the dashboard shows an explicit "included in margin: yes/no, because …" column driven by the engine feed).
