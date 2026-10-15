# Expense Tracker — Run 1: Code ↔ Specification Audit

**Mode:** read-only audit. No application code, spec, schema or migration was changed. No dependencies installed. No tests were run (see §9).
**Audited tree:** `C:\dev\Metrion`, branch `feat/pnl-calculator-integration`, with the working tree's pre-existing uncommitted changes left untouched (`backend/src/backend/api/v1/cfo.py`, `docs/specs/calculator.md`, frontend nav/contract files, untracked `expense-tracker.md`, `backend/src/backend/services/pnl_scenario.py`, `frontend/components/pnl/`, and others).
**Legend:** **[F]** observed fact (file read, path cited) · **[A]** assumption / inference · **[U]** unverified (needs a run, a human, or a document that does not exist).
**Status vocabulary:** `IMPLEMENTED` · `PARTIAL` · `MISSING` · `CONFLICT` · `UNVERIFIED`.

---

## 0. Preconditions the brief assumed that do not hold

| # | Brief / spec assumption | What is actually there |
|---|---|---|
| P1 | The source of truth is `docs/specs/expense-tracker.md` | **[F]** That file does not exist. The draft is `expense-tracker.md` at the **repository root**, untracked (`git status`: `?? expense-tracker.md`, 143 lines, "DRAFT v2 for spec-reviewer"). I audited that file. I did not move or copy it. |
| P2 | `legal-safeguards.md` exists (cited for §1 numeric-literal lint, §3 30-day deletion, §5 no-compliance-judgments) | **[F]** Not present in `docs/specs/` or anywhere in the repo. The only file that names it is `expense-tracker.md` itself. Every requirement the draft sources to it is therefore **unverifiable** (see §8). |
| P3 | `docs/decisions/phase1-decisions.md` exists | **[F]** No `docs/decisions/` directory; no file of that name anywhere (`find`). The nearest equivalent is `docs/planning/phase-1-readiness-review.md` (decision table OP1–OP17+). |
| P4 | The Expense Tracker is greenfield | **[F]** A working, narrower expense feature already ships: `PUT/GET /cfo/expenses`, `PUT /cfo/expenses/budget`, `GET /cfo/expenses/budget-status`, `frontend/components/cfo/sections/ExpenseTrackerSection.tsx`, `calc_engine.formulas.expense_pools`. The draft never mentions it. Whether V1.0 *extends* or *replaces* it is undecided. |
| P5 | "CFO chat" exists as a surface for quick-add | **[F]** There is no CFO chat route in `backend/src/backend/api/v1/cfo.py`. Chat is the **CEO** (`agent.ceo`); `auth.md` §5.2 states CEO is the sole conversational interface and CFO direct paths are "pre-enumerated, non-conversational". |
| P6 | "30-day raw-upload deletion rule" is existing | **[F]** No such rule exists in code or in any spec I could read. `data-foundation.md` §3 item 6 says the opposite: *"Raw files are retained while the account is active… Deletion policy on account closure is deferred"* (data-foundation.md:316; still open at :902 and `auth.md` Q9). |
| P7 | There are 14 open questions | **[F]** `expense-tracker.md` §11 numbers **10** (3 blocking + 7 deferrable). See `01-decision-register.md`. |

---

## 1. Requirement → evidence map

Section numbers refer to `expense-tracker.md`.

### §3 Cost classes

| Requirement | Status | Evidence |
|---|---|---|
| Marketplace-derived costs come from settlement only and are never re-entered | **PARTIAL / risk** | **[F]** Settlement fees are canonical `line_component` rows (`data_foundation/component_registry.py`). Nothing prevents entering the same cost as `expense.*`. **[F]** The Flipkart adapter maps `'Non-Order Charges'` which the component registry itself describes as *"advertising / storage"* (`component_registry.py:6,11`; `flipkart_payments_v1.py:42,177`). So settlement data **can** already contain ad/storage cost → manual `expense.advertising`/`expense.storage` can double-count it. No guard exists. |
| Direct costs associated with a SKU | **PARTIAL** | **[F]** `expense.*` accepts `target_type` `SKU\|ACCOUNT\|PERIOD` (`cfo.py:EnterExpenseRequest`, regex `^(SKU\|ACCOUNT\|PERIOD)$`). But the shipped UI always sends `ACCOUNT`/`"default"` (`ExpenseTrackerSection.tsx`, `addExpense`). Per-SKU entry is reachable only by direct API call. |
| Advertising from "a verified integration or validated import" | **CONFLICT** | **[F]** CLAUDE.md Mission: *"there are no seller-side marketplace API integrations"*. **[F]** No advertising-report adapter exists in `ADAPTER_REGISTRY` (`data_foundation/adapters/registry.py`); the only ad-related text is the Flipkart "Non-Order Charges" note above. Engine §5.6 (`deterministic-engine.md:281,285-292`) defines `AdvertisingCosts` as **seller-entered**, absent = **0**. The draft's "sourced data" tier does not exist today. |
| Overhead business-level by default, allocated only on explicit selection | **PARTIAL** | **[F]** `AllocationBasis` = `NET_REVENUE\|UNITS\|ORDERS` (`calc_engine/formulas/allocation.py:24-27`). **[F]** Engine D7 default is **net revenue share, automatic** for account-level pools (`deterministic-engine.md:101`, §5.10; `expense_pools.allocate_account_level_expense_pool`). The draft says *business-level by default, never silently distributed* — conflicts with D7's automatic allocation default. (Decision needed: which default; see register #11.) |
| Channel scope: business-wide vs channel-specific, kept separate | **PARTIAL** | **[F]** Pool value shape has optional `marketplace` (`expense_pools.parse_expense_pool_adjustment`; engine §7.2.1). No "business-wide" marker distinct from "marketplace omitted". The set of channel values is unconstrained free text on the API (`value: Any`). |

### §4.1 Expense dashboard

| Requirement | Status | Evidence |
|---|---|---|
| Monthly totals, category breakdown, recurring commitments, review queue, "as of" timestamps | **PARTIAL** | **[F]** `ExpenseTrackerSection.tsx` has add form, list, budget set/status. `list_expenses` returns `entries` + `totalPaise` (`cfo_actions.py:1351-1414`). **MISSING:** monthly rollup, category breakdown UI, recurring, review queue, "as of". `ExpenseEntry` carries `created_at`, not an "as of". |

### §4.2 Expense records

| Field / feature | Status | Evidence |
|---|---|---|
| category | **IMPLEMENTED (5 values)** | **[F]** `_ALLOWED_MANUAL_ADJUSTMENT_FIELDS` (`cfo_actions.py:286-297`) and `_EXPENSE_CATEGORIES` (`:1285`): advertising, packaging, storage, logistics, other. Rent/salaries/software/utilities (the draft's own "business overhead" examples) have **no** category except `other`. Registry is owned by the engine spec (`deterministic-engine.md:936`), so a category change is an engine-spec amendment. |
| date | **MISSING / CONFLICT** | **[F]** `manual_adjustment` has no date column (`20260917_0001_engine_tables.py:91-107`; confirmed in `cfo_actions._expense_period_label_range` docstring). Period is recoverable only if `target_type=PERIOD` and `target_ref` is `YYYY-MM-DD` or `YYYY-MM` (`cfo_actions.py:1320-1348`). The shipped UI writes `ACCOUNT`/`"default"` → such rows are **excluded from every period-filtered read** (`list_expenses` skips unrecoverable periods, `:1386-1393`; test `test_list_expenses_excludes_rows_with_unrecoverable_period_when_period_filter_given`). |
| vendor | **MISSING** | **[F]** Not in the `expense.*` value shape `{amount_paise, gst_amount_paise?, marketplace?}` (engine §7.2.1). `manual_adjustment.reason` is free text and is the only place the UI stores a description. |
| amount | **IMPLEMENTED** | **[F]** Signed integer paise. **Gap [F]:** `enter_expense` does **not** validate `value` for `expense.*` fields (`cfo_actions.py:677-717` only checks the field name). `parse_expense_pool_adjustment` is called only on read. Negative or zero amounts are accepted; a malformed `value` is stored and then makes `list_expenses` raise `ValueError` → `GET /cfo/expenses` returns **400 for the whole tenant listing** (`cfo.py:471-475`). |
| currency | **CONFLICT** | **[F]** The engine is INR-paise only (CLAUDE.md: "All money is signed BIGINT paise"; no currency column anywhere in the shape). A `currency` field has no engine representation. |
| description | **IMPLEMENTED** | **[F]** `manual_adjustment.reason`, surfaced by `list_expenses` (`ExpenseEntry.reason`) per `docs/evaluation/cfo-final-readiness-report.md` §3. |
| channel scope | **PARTIAL** | see §3 above. |
| optional SKU | **PARTIAL** | API only. |
| source reference | **MISSING** | **[F]** No column or value key. `manual_adjustment.target_ref` is the grain key, not a document reference. |
| payment status, review status | **MISSING** | **[F]** No fields. Adding keys to the value shape is an engine-registry amendment (engine §7.2.1 "this spec owns the key space"). |
| financial treatment | **MISSING** | see §4.6. |
| tax fields | **PARTIAL** | **[F]** `gst_amount_paise?` exists in the value shape. No GST-inclusive/exclusive flag, no "ITC-eligible?" flag. |
| Recurring templates | **MISSING** | **[F]** grep of backend/packages/frontend finds none. Note the append-only grants: a template that materialises rows would need a scheduler; the orchestration spec lists scheduled workers as **V1.1** (`ceo-agent-orchestration.md:99`). **[A]** Same constraint likely applies here. |
| Edit | **CONFLICT (semantics)** | **[F]** `manual_adjustment` is append-only; `UPDATE`/`DELETE` revoked from `metrion_app` (`20260917_0001_engine_tables.py:111`; repo docstring). An "edit" can only be a new row with `supersedes_id`, which requires the **same `target_type`, `target_ref` and `field`** (`manual_adjustment_repo.insert_adjustment`, supersedes check). Changing an expense's category (field) or its period (target_ref) therefore **cannot** be a supersede; it would need a withdraw + new row. |
| Delete | **MISSING** | **[F]** `status` allows `WITHDRAWN` (migration comment, engine §7.1) but **nothing writes it**: no repo function, no route (`grep WITHDRAW` in `backend/src` and `packages/*/src` returns nothing). The repo comment states a superseded row *keeps* `status='ACTIVE'` and is retired only by the row naming it in `supersedes_id`. There is no way to delete an expense today other than superseding it with a replacement value (e.g. amount 0, which is itself accepted). |
| Multiple ACTIVE rows | **[F] by design** | Each `PUT /cfo/expenses` without `supersedes_id` inserts a *new* ACTIVE row on the same `(ACCOUNT, "default", expense.X)` target; the repo documents "a field with more than one ACTIVE row is a data anomaly this repository does not resolve". `list_expenses` sums all of them. So "one expense = one row" holds only because the UI never supersedes. There is no edit path in the UI. |

### §4.3 CSV import

| Requirement | Status | Evidence |
|---|---|---|
| Fixed-template CSV, validation, preview | **MISSING** | **[F]** The only CSV path is `POST /cfo/ingest` (`cfo.py:~196-262`) for **marketplace report adapters** (`ADAPTER_REGISTRY`), writes `report_file` + `sales_line`/`settlement` rows. No expense adapter, no preview step (ingest persists immediately). Reusable pieces: `read_upload_capped`, content-hash dedupe (`report_file_repo.find_by_content_hash`), `ingestion_run` row counts (read/accepted/rejected/duplicate). |
| Duplicate detection by source IDs / fuzzy | **MISSING** | **[F]** Only file-level (SHA-256) and natural-key dedupe for marketplace rows exist. Nothing for expenses; `enter_expense` has no idempotency key. |

### §4.4 CFO quick-add (LLM → confirmation card → save)

| Requirement | Status | Evidence |
|---|---|---|
| Chat extracts an expense and shows a confirmation card | **CONFLICT** | **[F]** `ceo-agent-orchestration.md` **C21** (line 34): *"No write-class action is in the V1 registry"*; §6.11 line 407 names `cfo.enter_expense` and `cfo.expense_budget_set` as excluded *by decision*; **E30** (line 983): a seller asking CEO to "record this expense" is *"Declined and explained; pointed to the registered direct surface"*. **[F]** Code agrees: `backend/src/backend/ceo/registry.py:52-53` lists both keys as forbidden; `ceo/classifier.py:83` classifies "recording expenses" as `OUT_OF_SCOPE`. |
| Confirmation-card infrastructure exists | **PARTIAL (wrong kind)** | **[F]** CEO "decision cards" exist (`frontend/components/ceo/hub/DecisionCard.tsx`, `DecidePanel.tsx`; spec §6.32) but they record a **choice** (`RECORD_CHOICE`) in a playbook, not approval of a write. The approval workflow (`ceo-approval-workflow.md`) is explicitly *"Nothing in this spec is implemented"* (line 3); `ceo/approval_gate.py` is **observe-only**, "imported by nothing in orchestration, chat, an API or execution". `docs/planning/phase1-phase2-engineering-report-2026-10-12.md:36`: "approval workflow (11 gated actions stay refused)". |
| Stable proposal id, idempotent approval | **MISSING** | **[F]** No proposal table or id in the codebase. `ceo-approval-workflow.md` designs one (30-min expiry C6, frozen plan hash C8, requester-only approver C7, append-only `investigation_plan_event` D7), unimplemented. `enter_expense` mints a fresh `uuid4` per call (`manual_adjustment_repo.insert_adjustment`) — double submit ⇒ two rows. |
| Org bound server-side at proposal and save | **PARTIAL** | **[F]** Every route derives `tenant_id` from the verified session (`auth/context.py:134-250`: Clerk `org_id` claim → `tenant_repo` → membership/role checks) and bodies carry no `tenant_id` (CLAUDE.md rule; `EnterExpenseRequest` has no such field; `pnl-scenario` explicitly rejects one). RLS `FORCE` + `tenant_scope` is the DB boundary. There is no proposal object to bind, so "bound at proposal" is moot. |
| `financials.adjust` checked at save | **IMPLEMENTED (direct path)** | **[F]** `put_expense` checks `has_permission(..., FINANCIALS_ADJUST)` in-handler (`cfo.py:424`) after `agent.cfo` via `require_auth` and the entitlement gate. **[F]** `dispatch_cfo_enter_expense` (`agents/ceo_hub.py:386`) *"leaves `financials.adjust` to its caller"* and has no HTTP caller (`ceo-agent-orchestration.md:602`) — which is the stated reason it is excluded. |
| LLM never supplies org id, proposal id, treatment | **[U]** | No extraction code exists to inspect. |
| No LLM numeric literals in CFO responses (lint) | **PARTIAL** | **[F]** Enforced for CEO composer output (`ceo-agent-orchestration.md:280`, AC21) and by `packages/cfo/tests/.../test_no_arithmetic_lint.py` (cited in cfo-agent.md T42). The draft cites `legal-safeguards.md` §1 — not available. |

### §4.5 Cost allocation

| Requirement | Status | Evidence |
|---|---|---|
| Rules run in the engine, not the agent | **IMPLEMENTED (pattern)** | **[F]** `calc_engine.formulas.allocation.allocate_pool`, `expense_pools.allocate_account_level_expense_pool`; CLAUDE.md hard rule. |
| Revenue-share / unit basis; unavailable basis ⇒ stays unallocated | **PARTIAL** | **[F]** `allocate_pool` supports `NET_REVENUE`/`UNITS`/`ORDERS`; zero/negative-revenue lines excluded and reported (allocation.py docstring). **[A]** the "stay unallocated and visible" behaviour for a missing basis is not shown; I did not trace an `UNAVAILABLE`/unallocated outcome. |
| **Stored expenses reach the P&L** | **MISSING (critical)** | **[F]** `compute_period_pnl` consumes exactly two values, `advertising_adjustment_values` and `other_adjustment_values` (`cfo_actions.py:453-454`), which `PeriodPnlForTenantRequest` documents as *"deliberately still caller-supplied"* (`:1170-1181`). The only providers are HTTP request bodies (`cfo.py:955-956, 1046-1047, 1010-1011, 1084-1085`). `grep` finds **no** code that reads stored `expense.*` `manual_adjustment` rows to build those lists. Consequences **[F]/[A]**: (a) an expense saved through `PUT /cfo/expenses` does not move Contribution Profit unless the caller separately re-sends it; (b) `expense.packaging`, `expense.storage`, `expense.logistics` have **no** consumer in `compute_period_pnl` at all. The UI nonetheless offers all five categories. |
| Product contribution shown separately from fully allocated | **[U]** | Not traced. |

### §4.6 Financial treatment (`incremental | replaces_input | already_in_settlement`)

| Item | Status | Evidence |
|---|---|---|
| Treatment field | **MISSING** | **[F]** Not in the registry value shape. Adding it is an engine-registry amendment; the registry is "the sole authority for the key space" (`deterministic-engine.md:936`). |
| `replaces_input` vs COGS override | **CONFLICT in model** | **[F]** COGS is not an expense: it is `cogs_per_unit`, `SKU` grain, `{amount_paise, effective_from?}`, weighted-average and effective-dated (engine §5.6, §7.2.1). A per-SKU unit cost *already supersedes* by the manual-adjustment chain. An "expense that replaces COGS" has no meaning for a per-unit effective-dated input unless the draft defines how a lump-sum amount converts to a per-unit cost — which would be arithmetic the engine would have to own. Also `cogs_per_unit` is in `_ALLOWED_MANUAL_ADJUSTMENT_FIELDS`, so it is **already writable through the same `PUT /cfo/expenses` route**. |
| `replaces_input` vs advertising | **CONFLICT in model** | **[F]** `expense.advertising` *is* the advertising input; there is no other ad-spend source to "replace" (see §3). The only replacement semantic that exists is the supersede chain on the **same** target+field. |
| `already_in_settlement` stored but excluded from margin | **MISSING** | **[F]** Every ACTIVE `expense.*` row is summed (`list_expenses`, `resolve_expense_pool_total`). No exclusion mechanism. |
| Precedence rule exists for logistics | **[F]** | Engine §7.2.1: per-line `logistics_cost` wins and the pooled `expense.logistics` is reduced by it. `expense_pools.py` docstring says it **does not implement** this rule. No other expense/settlement precedence rule exists. |

### §4.7 Settlement and advertising overlap — **MISSING**; see §3 row 1. `settlement.receipt` is a different thing (cash correction, `SETTLEMENT` grain), not an expense-overlap mechanism.

### §4.8 History, edits, deletions, recalculation

| Requirement | Status | Evidence |
|---|---|---|
| Audit history of every create/edit/delete | **PARTIAL** | **[F]** `manual_adjustment` rows carry `created_by`, `created_at`, `supersedes_id`, `reason`; UPDATE/DELETE revoked at grant level — an immutable create/supersede trail exists. No delete event exists (see §4.2). **[F]** The direct CFO routes write **no `agent_run`** row; `cfo-agent.md:289` records this as a known *"Audit gap"* (CEO Q16). Only `POST /cfo/pnl-scenario` writes one (`cfo.py:834-852`). **[F]** `auth_audit` records auth events, not financial writes (`auth.md:429`), and is app-deletable (`ceo-approval-workflow.md` D7; `test_privilege_boundary.py::KNOWN_APP_DELETABLE`). |
| Version financial outputs; restate through traceable recalculation | **PARTIAL / semantics undefined** | **[F]** `metric_result` is stamped with `formula_version`, `config_version`, `canonical_data_version`, `manual_adjustment_set`, `as_of_date`, `computed_at` (`20260917_0001_engine_tables.py:57-79`), engine §4.2 reproducibility tuple, F3 "Historical results are never recomputed silently". **[F]** No `supersedes`/restatement link between result rows; no "restated" flag; engine §3 says results "may always be recomputed" but not how a restated period is labelled. Because `manual_adjustment` has no effective date, "the set of adjustments that applied *as of* a past date" is not queryable: `manual_adjustment_set` records ids used at compute time only. **[F]** Insert-only evidence tables (`metric_result`, `sales_line`, `report_file`…) still hold `UPDATE/DELETE` grants for `metrion_app` (`docs/planning/stages-3-4-5-report-2026-10-12.md:82`, "owner decision"). So provenance immutability is by convention, not by grant. |

### §5 Channels

| Requirement | Status | Evidence |
|---|---|---|
| IndiaMART supported "through existing Metrion capabilities" | **CONFLICT** | **[F]** The supported marketplaces are Amazon, Flipkart, Meesho (CLAUDE.md; `MARKETPLACE_LABEL` in the sibling calculator; adapter registry). IndiaMART appears only as a **supplier-discovery** source, user-initiated, and *"schema-only, not implemented"* (`product-intelligence-agent.md` C5/C6; `supplier_lead.source` enum). It is not a sales channel and supplies no settlement/cost data. |
| Other channels tagged manually | **PARTIAL** | `marketplace` is free text on the pool value; no enumeration or validation. |

### §6 Permissions

| Requirement | Status | Evidence |
|---|---|---|
| `financials.adjust` governs create, edit, delete, approve | **PARTIAL / wording conflict** | **[F]** `auth.md:220`: *"Create or supersede manual financial adjustments"* — no "delete" or "approve" verb, and no delete mechanism exists. |
| OWNER default, PARTNER deny-by-default | **IMPLEMENTED** | **[F]** `auth.md:230-232` (D4, R1 resolved); `auth/context.py` step 5 with OWNER bypass; `has_permission`. Spec test T8c/T8d exist as spec rows. |
| Review-only visibility "follows existing financial-data read permissions" | **MISSING / ambiguous** | **[F]** There is **no** financial-data read permission key in the grid (`auth.md:200-228`). `GET /cfo/expenses` requires only `agent.cfo` (`cfo.py:457-468`). A partner holding `agent.cfo` without `financials.adjust` can read all expenses; a partner with neither cannot. There is no separate "view expenses" key. |
| Quick-add approval requires `financials.adjust` at save | **see §4.4** | |

### §7 AI boundary

**[F]** Consistent with CLAUDE.md hard rule and CEO C4/C21. **[U]** Nothing implements extraction, so conformance of an extraction step is untestable today. New narration/extraction surfaces require LLM evals per CLAUDE.md ("LLM evals — required for any new Brain-3 narration surface"); none exist for expense extraction.

### §8 Tax handling

| Requirement | Status | Evidence |
|---|---|---|
| GST amount stored | **IMPLEMENTED (optional key)** | `gst_amount_paise?` in the value shape. **[F]** No validation that it is ≤ `amount_paise` or consistent with a rate. |
| GST-inclusive/exclusive status, ITC flag | **MISSING** | Not in shape. Note `fee_gst_treatment` (`CREDITABLE\|COST`) exists at `ACCOUNT` grain for *fees*, not expenses. |
| "Estimate for planning purposes. Verify with your CA." disclaimer | **[U]** | Text not found verbatim; related GST disclaimer exists (`cfo-agent.md` §6.6). Source (`legal-safeguards.md` §5) unavailable. |
| Economic vs cash margin split; TCS not an expense | **PARTIAL** | **[F]** Engine already states Contribution Profit is not a cash figure (`cfo-agent.md:644`) and has `TCS_COLLECTED`, `TDS_DEDUCTED` metrics (`deterministic-engine.md:583`) with `cash_reconciliation` (`:575`). Nothing in the expense path touches TCS, so "never subtracted as expense then credited" holds trivially today; it is untested for the new path. Rates/treatment need a CA (draft itself says so). |

### §9 Receipts and retention

| Requirement | Status | Evidence |
|---|---|---|
| "Existing private object storage and authorization controls" | **CONFLICT** | **[F]** There is no object storage. Uploads go to **local disk** (`cfo_report_storage_dir`, `cfo.py` ingest: `storage_uri=f"file://{storage_dir/stored_name}"`; `config.py:226-234`: "real-object-storage-is-later"). Evidence/ image stores are likewise local (`ci_evidence_storage_dir`). No presigned/authorized download route exists; `report_file_repo` deliberately never selects `storage_uri` (`report_file_repo.py:73`) and `ceo-agent-orchestration.md:877` notes "there is no download endpoint yet". **[F]** Stored filename = content SHA-256 in a **shared directory across tenants** (`cfo.py`: `stored_name = f"{content_sha256}{suffix}"`). Dedupe is per tenant (`find_by_content_hash(tenant_id, …)`), so two tenants uploading identical bytes share one physical file. Harmless for report CSVs today; for receipts it would make deletion by one tenant affect another and gives a content-addressable path. |
| References and metadata separate from files | **PARTIAL** | Pattern exists (`report_file` row, `storage_uri`, `content_sha256`, `uploaded_by`) and `seller_image_asset` (`slim-cmo` migration: `storage_uri`, `sha256`, `status`). No receipt table. |
| 30-day raw-upload deletion | **CONFLICT / UNVERIFIED** | see P6. **[F]** No deletion job exists for `report_file`; `files.delete` is a permission key (`auth.md:212`) but I found no delete route for report files. **[F]** `backend/scripts/tenant_data_inventory.py` classifies tables for the pending retention/erasure decision and "deletes and changes nothing". |
| Structured-record retention | **UNRESOLVED** | **[F]** Open at `auth.md` Q9, `data-foundation.md:902`, `phase-1-readiness-review.md` 2.21/3.11 `[P]`. |

### Cross-cutting infrastructure observed

| Topic | Fact |
|---|---|
| Tenant isolation | **[F]** `manual_adjustment` has `FORCE ROW LEVEL SECURITY` with a `tenant_isolation` policy (`current_setting('app.current_tenant_id', true)::uuid`) via `_TENANT_RLS_SQL`; `supersedes_id` is validated against the same tenant (`insert_adjustment`). Several read queries (`_ACTIVE_FOR_TARGET_SQL`, `_ACTIVE_BY_EXACT_FIELD_SQL`, `_ACTIVE_BY_FIELD_PREFIX_SQL`) filter on field/status **without** an explicit `tenant_id` predicate and rely on RLS alone; `_ACTIVE_FOR_TARGETS_SQL` filters explicitly. CLAUDE.md calls for defence-in-depth ("neither is trusted alone"). **[F]** `docs/planning/api-contract-coverage.md:116` claims a test that expense writes are "not visible to tenant B"; I did not run it. |
| Duplicate submission | **[F]** No idempotency on `PUT /cfo/expenses`. |
| Entitlement | **[F]** `PUT /cfo/expenses` also requires CFO entitlement (`_require_cfo_entitlement`, trigger `cfo.enter_expense`); GET does not. A tenant without CFO is denied (402). |
| Frontend money handling | **[F]** `toPaise` uses exact integer parsing, returns `NaN` for unparsable input (`frontend/components/cfo/primitives.tsx:111`), consistent with the "no floats" rule. `NaN` is serialised by `JSON.stringify` as `null`; server-side behaviour for `amount_paise: null` is "stored then breaks the list" (see §4.2 amount) — **[A]** not exercised. |
| Existing tests (names only, not run) | `packages/cfo/tests/unit/test_cfo_actions_expense.py` (3), `test_cfo_actions_expense_list_and_budget.py` (13), `packages/calc-engine/tests/unit/test_expense_pools.py`, `packages/calc-engine/tests/integration/test_manual_adjustment_append_only.py`, `backend/tests/unit/test_cfo_route_entitlement_enforcement.py` and `backend/tests/integration/test_entitlement_enforcement.py`. **No** test I found covers: a PARTNER without `financials.adjust` getting 403 on `PUT /cfo/expenses` over HTTP (`test_cfo_seller_goal.py`, `test_cfo_gst_lookup_accept.py` cover that pattern for other routes — **[A]** same code shape, different route), duplicate submit, malformed `value`, or expense→P&L flow. |

---

## 2. Summary table

| Area | IMPLEMENTED | PARTIAL | MISSING | CONFLICT |
|---|---|---|---|---|
| Records (§4.2) | category(5), amount, description | tax, channel, SKU | date, vendor, source ref, statuses, treatment, recurring, delete | currency, edit semantics |
| CSV (§4.3) | – | file-level dedupe machinery | template, preview, expense dedupe | – |
| Quick-add (§4.4) | `financials.adjust` on direct path | tenant binding | proposal/idempotency/card | C21/E30, no CFO chat |
| Allocation (§4.5) | engine allocator | bases exist | **feed stored expenses into P&L**, packaging/storage/logistics consumers | D7 automatic default |
| Engine contract (§4.6–4.7) | – | – | treatment, overlap detection | `replaces_input` vs COGS/ads |
| History (§4.8) | immutable create/supersede trail | metric stamping | delete, direct-path `agent_run`, restatement labelling | – |
| Channels (§5) | – | free-text tag | – | IndiaMART |
| Permissions (§6) | create/supersede gate, deny-by-default | read fallback | read key, delete/approve verbs | wording |
| Receipts/retention (§9) | – | reference pattern | receipt table, authorised download | object storage, 30-day rule |

## 3. What I could not verify

- **[U]** Whether any test passes; none were run.
- **[U]** Anything sourced from `legal-safeguards.md` or `phase1-decisions.md`.
- **[U]** Behaviour with a live database (RLS predicates were read, not exercised).
- **[U]** Real Clerk sign-in (the 2026-10-12 report already lists this as untested).
- **[U]** Whether the uncommitted edits to `cfo.py`/`calculator.md` change any behaviour above (I read the working-tree versions).

## 4. Do-not-assume notes for the next run

1. The shipped feature exists; decide extend-vs-replace before design.
2. "Edit" and "delete" are not available primitives on the current store.
3. Stored expenses do not currently influence margin automatically.
4. Chat quick-add is blocked by an approved decision (C21) plus an unimplemented approval workflow.
