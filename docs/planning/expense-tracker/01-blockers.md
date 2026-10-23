# Expense Tracker — Run 1: Blockers and Risks

**Scope:** financial-integrity, authorization, tenant-isolation and data-retention risks found by the read-only audit. Evidence tags: **[F]** observed in files · **[A]** inference · **[U]** unverified. File-level detail is in `01-code-spec-audit.md` (*Audit §n*); the decisions each blocker needs are in `01-decision-register.md` (*Reg Qn / Nn*).
**Not claimed:** no test was run; no review beyond reading files was performed; nothing here has been confirmed against a live database or Clerk.

Priority key: **P0** = must be resolved before implementation starts · **P1** = must be resolved before launch · **P2** = safely deferrable (with the stated condition).

---

## P0 — Resolve before implementation

### B1. Chat quick-add is prohibited by an approved decision and has no safe write path (authorization)
- **[F]** CEO C21: no write-class action in the V1 registry; `cfo.enter_expense` and `cfo.expense_budget_set` named as excluded; E30 says "record this expense" is declined and redirected (`ceo-agent-orchestration.md:34, 407, 983`). Code enforces it (`ceo/registry.py:52-53`; `ceo/classifier.py:83`).
- **[F]** The approval workflow that would make a confirmation card safe is designed but **not implemented** (`ceo-approval-workflow.md:3`; `ceo/approval_gate.py` is observe-only and unreferenced). Existing "decision cards" record choices, not writes.
- **[F]** `dispatch_cfo_enter_expense` (`agents/ceo_hub.py:386`) leaves `financials.adjust` to its caller and has no HTTP caller. Wiring it to chat as-is would make the CEO a privilege-escalation layer, which is C21's stated reason for exclusion.
- **[F]** There is no CFO chat; CEO is the sole conversational interface (`auth.md` §5.2).
- **Risk.** Building §4.4 as drafted reverses an approved decision or silently routes around it.
- **Needed.** Reg N1.

### B2. Entered expenses do not reach Contribution Profit; three of five categories have no consumer (financial integrity)
- **[F]** `compute_period_pnl` takes only `advertising_adjustment_values` and `other_adjustment_values`, and both are request-body, caller-supplied (`cfo_actions.py:453-454, 1170-1181`; `cfo.py:955-956, 1010-1011, 1046-1047, 1084-1085`). I found no code that reads stored `expense.*` rows to build them.
- **[F]** `expense.packaging`, `expense.storage`, `expense.logistics` are accepted, stored and listed, but are not inputs to `compute_period_pnl`.
- **[F]** The shipped UI offers all five categories (`ExpenseTrackerSection.tsx`).
- **Risk.** A seller enters packaging cost and sees it "saved" while margin is unchanged; or the totals shown by the tracker disagree with the P&L. This is the TRUST failure CLAUDE.md warns about ("a number a seller cannot trace is worse than no number").
- **Needed.** Reg N4, Q1.

### B3. Double-counting has no guard (financial integrity)
- **[F]** No `financial_treatment`, no overlap detection, no duplicate detection, no idempotency key on `PUT /cfo/expenses`; each call mints a new `uuid4` row (`manual_adjustment_repo.insert_adjustment`).
- **[F]** Settlement data can already include advertising/storage ("Non-Order Charges", `component_registry.py:6,11`; `flipkart_payments_v1.py:42`), so a manual `expense.advertising` or `expense.storage` can duplicate settlement-borne cost.
- **[F]** Repeated submits create multiple ACTIVE rows on the same target, and every ACTIVE row is summed.
- **Risk.** Overstated costs, understated profit, with no flag.
- **Needed.** Reg Q1, N1 (proposal id/idempotency belongs to the approval design).

### B4. Writes are not validated; one bad row breaks the tenant's expense listing (financial integrity / availability)
- **[F]** `enter_expense` checks only the field name (`cfo_actions.py:677-717`). `value` is `Any` on the route (`cfo.py:EnterExpenseRequest`). `parse_expense_pool_adjustment` runs on **read** and raises on a malformed shape (`expense_pools.py`); `get_expenses` converts that to HTTP 400 for the whole listing (`cfo.py:471-475`).
- **[F]** A well-formed value of any sign is accepted (negative, zero, unbounded). `gst_amount_paise` is not checked against `amount_paise`. `marketplace` is free text. The frontend sends `NaN`→`null` for an unparsable amount (`primitives.tsx:111`); **[A]** that would be stored.
- **[F]** Append-only grants mean a poisoned row cannot be removed, only superseded (and a supersede requires the same target/field).
- **Needed.** Reg N7. Validation must live server-side in the engine-owned parser, not in the UI.

### B5. Expenses have no date; the shipped UI creates undated rows that are invisible to period views (financial integrity)
- **[F]** `manual_adjustment` has no date or period column. Period is recoverable only for `target_type=PERIOD` with `target_ref` as `YYYY-MM-DD` or `YYYY-MM` (`cfo_actions.py:1320-1348`).
- **[F]** The UI writes `ACCOUNT`/`"default"` (`ExpenseTrackerSection.tsx`), and `list_expenses` **excludes** unrecoverable periods when a period filter is given (`:1386-1393`).
- **Risk.** Monthly totals, budgets by period and any restatement are wrong or empty for existing data. The draft's required `date` field cannot be stored natively. Existing rows would need a migration story.
- **Needed.** Reg Q3, N2, N3.

### B6. The store cannot edit across target/field and cannot delete (data integrity / audit)
- **[F]** `UPDATE`/`DELETE` are revoked for `metrion_app` (`20260917_0001_engine_tables.py:111`). A supersede must keep the same tenant, `target_type`, `target_ref` and `field` (`insert_adjustment`). `WITHDRAWN` exists in the schema comment but nothing writes it (no repo function, no route).
- **Risk.** "Edit category", "edit date" and "delete" in §4.2/§4.8 have no primitive. Workarounds (zero-amount supersede; new row + orphan) corrupt the audit story or inflate listings.
- **Needed.** Reg Q2, N3. If a new table is chosen, it reverses the documented decision at `cfo-agent.md:113` and needs the isolation/grant pattern replicated.

### B7. The adjustment contract (`replaces_input`) conflicts with how COGS and ad spend are modelled (financial integrity)
- **[F]** COGS is a per-unit, effective-dated, weighted-average SKU input (`cogs_per_unit`); ad spend is the single seller-entered `expense.advertising` input. Neither has a second source for a manual expense to replace.
- **[F]** `cogs_per_unit` is already writable via the same route.
- **Needed.** Reg Q1. Any lump-sum → per-unit conversion would be arithmetic the engine must own (CLAUDE.md hard rule), not CFO or the UI.

### B8. Dependencies the draft cites do not exist (process)
- **[F]** `legal-safeguards.md` and `docs/decisions/phase1-decisions.md` are absent; the draft is at the repo root, untracked, not under `docs/specs/`. The 30-day rule and the "numeric-literal lint" are sourced only to the missing file.
- **Risk.** Requirements cannot be reviewed; a rule may be implemented that was never approved.
- **Needed.** Reg D-0, N8, Q6.

---

## P1 — Launch requirements (resolve before release, can follow design)

### B9. Authorization gaps around reads and audit
- **[F]** No financial-data read permission exists; `GET /cfo/expenses` needs only `agent.cfo`, and (unlike the write) no CFO entitlement check (`cfo.py:457-480`). A partner with `agent.cfo` but not `financials.adjust` can read every expense; the draft's "follows existing financial-data read permissions" has nothing to follow. *Reg Q2.*
- **[F]** Direct CFO routes write no `agent_run` (`cfo-agent.md:289` "Audit gap, recorded"; only `pnl-scenario` does, `cfo.py:834-852`). The sole financial audit trail is the `manual_adjustment` row (`created_by`, `created_at`, `supersedes_id`). A delete has no record at all (B6). *Reg N6.*
- **[F]** `auth_audit` is app-deletable (`ceo-approval-workflow.md` D7; `test_privilege_boundary.py::KNOWN_APP_DELETABLE`) and does not log financial writes (`auth.md:429`); it is not a substitute.
- **[A]** No HTTP-level test found for "PARTNER without `financials.adjust` → 403 on `PUT /cfo/expenses`"; the pattern exists for sibling routes (`test_cfo_seller_goal.py`, `test_cfo_gst_lookup_accept.py`).

### B10. Tenant isolation is correct in design; two weak points to close
- **[F]** Strong: `manual_adjustment` has `FORCE ROW LEVEL SECURITY` with a `tenant_isolation` policy; tenant comes from the verified session; no route accepts `tenant_id`; `supersedes_id` is checked against the caller's tenant (no cross-tenant reference or existence oracle).
- **[F]** Weak 1: `_ACTIVE_FOR_TARGET_SQL`, `_ACTIVE_BY_EXACT_FIELD_SQL`, `_ACTIVE_BY_FIELD_PREFIX_SQL` have no explicit `tenant_id` predicate and rely on RLS alone, while CLAUDE.md requires application filtering *and* RLS ("neither is trusted alone"). The tenant-wide expense listing uses the prefix query. A new expense read path should add the explicit predicate. **[U]** not exercised against a database.
- **[F]** Weak 2 (receipts, if built on current storage): uploads are written to one local directory named by content SHA-256, shared across tenants (`cfo.py` ingest `stored_name`). Per-tenant dedupe plus a shared path means identical receipts from two tenants map to one physical file, and deleting it for one tenant (e.g. a retention job) would remove the other's. Do not reuse this pattern for receipts.

### B11. Raw-file and receipt retention is undecided and the storage layer is not what the draft assumes
- **[F]** No object storage; local disk (`config.py:226-234`: real object storage "is later"). No authorised download endpoint (`ceo-agent-orchestration.md:877`; `report_file_repo.py:73` never returns `storage_uri`). No deletion job; no report-file delete route found.
- **[F]** Retention policy is open platform-wide (`auth.md` Q9; `data-foundation.md:316,902`; readiness 2.21/3.11 `[P]`). `data-foundation.md` says raw files are kept while the account is active. The "30-day deletion rule" is not corroborated (Reg Q6).
- **[F]** `manual_adjustment` is retained indefinitely because DELETE is revoked; erasure on closure is an open owner decision (`stages-3-4-5-report-2026-10-12.md`, Retention/erasure; `backend/scripts/tenant_data_inventory.py` is analysis only).
- **Risk.** Receipts hold personal/commercial data (vendor, GSTIN, amounts). Shipping receipt references before storage, access control, and retention are decided creates data-protection exposure (DPDP is already flagged for supplier leads, `product-intelligence-agent.md`).
- **Needed.** Reg Q5, Q6; owner/legal.

### B12. Tax output must not be implied
- **[F]** An "ITC-eligible?" flag and GST fields would sit beside engine figures; GST support is management-grade only (`cfo-agent.md` C4/§6.6); rates/treatment need a CA (draft §8; Reg Q7).
- **Needed.** Reg Q7; labelling rule that any tax-adjacent figure carries the standing disclaimer. **[U]** the disclaimer's approved text is in the missing `legal-safeguards.md`.

### B13. LLM extraction needs its own evals and boundary tests before it ships
- **[F]** CLAUDE.md requires evals for any new narration/extraction surface (no invented numbers, required disclaimers). None exist for expense extraction. **[F]** Rule that the LLM never supplies org id, proposal id or treatment is a spec statement with no code to test yet.
- Applies only if B1 resolves toward quick-add.

---

## P2 — Safely deferrable (with condition)

| Item | Why deferrable | Condition |
|---|---|---|
| Receipt-image OCR, WhatsApp quick-add, bank-statement import, custom categories, CSV column mapping | Draft already phases them out of V1.0; WhatsApp approvals would re-enter the same chain (`whatsapp-integration.md` C8/§6.7 resolves identity to the owner) | Decide B1 first; WhatsApp reuses its outcome |
| Recurring templates | Needs a scheduler; scheduled workers are V1.1 in orchestration (`ceo-agent-orchestration.md:99`) **[A]** same constraint | Ship V1.0 without it, or confirm a scheduling mechanism |
| Final retention period and legal basis | Owner/legal timeline | Do not claim a retention period in UI or docs until decided; do not add deletion jobs for receipts |
| Exact TCS/GST rates and treatment | CA-dependent | No tax figure shown without the disclaimer; store-only flags |
| Review-status values | Needed only if a review queue ships | Otherwise drop the queue from V1.0 |
| Budget feature interaction | Existing `expense.budget` is separate (`set_expense_budget`) | Keep budget rows out of expense totals (already tested: `test_list_expenses_excludes_expense_budget_rows_from_prefix_scan`, not run) |
| Restatement presentation (labels, side-by-side) | Depends on Reg Q3 | Must be decided before the first edit of a closed-period expense is allowed |

---

## Cross-reference: what is already in good shape

- **[F]** Append-only adjustment store enforced by grants, with tenant-checked supersede chains.
- **[F]** `financials.adjust` enforced in-handler on the direct write path; deny-by-default for PARTNER; OWNER implicit.
- **[F]** Engine rule that missing inputs are not zero is followed for COGS; advertising absence = 0 is an explicit, documented exception.
- **[F]** Frontend amount parsing is integer-exact.
- **[F]** Result stamping (`formula_version`, `config_version`, `canonical_data_version`, `manual_adjustment_set`, `as_of_date`) gives a reproducibility tuple to build restatement on.
