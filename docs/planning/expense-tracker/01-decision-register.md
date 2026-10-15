# Expense Tracker — Run 1: Decision Register

**Purpose:** validate each open question in `expense-tracker.md` §11 against the code and the dependent specifications, record the evidence, and name the decision still required. This register does **not** restate the draft's recommendations as a competing source of truth; the draft remains the source of truth for approved decisions, and nothing below is approved.
**Evidence tags:** **[F]** observed in files · **[A]** inference · **[U]** unverifiable here. Detail and file paths are in `01-code-spec-audit.md` (cited as *Audit §n*).
**Verdict vocabulary:** `SUPPORTED` (evidence agrees with the draft's position) · `CONTRADICTED` (evidence disagrees with the draft's premise or position) · `UNRESOLVED` (evidence cannot settle it) · `PARTLY …` where mixed.

---

## 0. The count: 10, not 14

`expense-tracker.md` §11 contains **ten** numbered questions (3 "blocking before any coding", 7 "can remain unresolved at implementation start"). I could not identify four more. Two candidates for the missing four, neither of which I treat as authoritative:

- The draft marks about a dozen defaults **"(Proposed)"** without numbering them (§0A below).
- The brief may refer to a different revision of the draft (this one is "DRAFT v2").

**Decision needed (D-0):** confirm whether another revision exists, or whether the 14 includes the "Proposed" items.

---

## 1. Blocking questions (draft: "before any coding")

### Q1 — Financial adjustment contract (`incremental` / `replaces_input` / `already_in_settlement`)

- **Verdict: PARTLY CONTRADICTED.**
- **Evidence.**
  - **[F]** Engine §7.3/§7.2.1 define the manual-input store (`manual_adjustment`, append-only, superseding) and declare the **registry as the sole authority for the key space** (`deterministic-engine.md:936`). A `financial_treatment` key, or any new per-expense attribute, is therefore a registry amendment, not an Expense Tracker decision. (Audit §4.2, §4.6)
  - **[F]** COGS is `cogs_per_unit`, SKU grain, effective-dated, weighted-average (engine §5.6, §7.2.1). It is a *unit* input, not a lump-sum expense; "an expense that replaces COGS" has no defined conversion. `cogs_per_unit` is already writable through the same `PUT /cfo/expenses` route (`cfo_actions.py:286-297`).
  - **[F]** `expense.advertising` *is* the ad-spend input (engine §5.6: seller-entered; absent ⇒ 0). There is no second ad source for a manual entry to "replace" (no ad adapter; no seller-side integrations: CLAUDE.md). The only replacement mechanism that exists is superseding the **same target + field** (`manual_adjustment_repo.insert_adjustment` enforces same target/field).
  - **[F]** No mechanism excludes an ACTIVE `expense.*` row from margin, so `already_in_settlement` ("stored, no effect") cannot be honoured without new engine behaviour.
  - **[F]** Only two pools reach the period P&L (`advertising`, `other`) and they arrive caller-supplied (`cfo_actions.py:453-454, 1170-1181`). `packaging`/`storage`/`logistics` have no P&L consumer. (Audit §4.5)
  - **[F]** Settlement data can already hold ad/storage cost (Flipkart "Non-Order Charges", `component_registry.py:6,11`), so the double-count risk the draft targets is real.
- **Decision still needed.**
  1. Is the guard a treatment field, a supersede-chain convention, or an engine-owned exclusion rule?
  2. If a treatment field: who amends engine §7.2.1, and are the three values right? Is `replaces_input` kept at all, given COGS/ads semantics above?
  3. Which categories must actually reach the P&L in V1.0, and through which engine path (today: caller-supplied lists)?

### Q2 — Permission behaviour (`financials.adjust` verbs; read fallback)

- **Verdict: PARTLY SUPPORTED, PARTLY CONTRADICTED.**
- **Evidence.**
  - **[F]** Supported: deny-by-default for PARTNER, OWNER implicit, server-side check at save (`auth.md:220,230-232`; `cfo.py:424`).
  - **[F]** Contradicted: the registry text is *"Create or supersede"* (`auth.md:220`). "Edit", "delete" and "approve" are not verbs of that key, and delete has no mechanism (Audit §4.2).
  - **[F]** There is **no** financial-data read permission in the grid (`auth.md:200-228`); reads require only `agent.cfo` (`cfo.py:457-468`). "Existing financial-data read permissions" does not exist as a distinct grant.
  - **[F]** The draft's "approve" for quick-add has no implemented approver model; the designed one is *requester only, even OWNER cannot approve for someone else* (`ceo-approval-workflow.md` C7; unimplemented).
- **Decision still needed.** (a) Is "view expenses" gated by `agent.cfo` alone, or a new key (that is an `auth.md` change)? (b) Does `financials.adjust` cover delete/void, and what is "delete" on an append-only store? (c) Does "approve" mean anything beyond the requester's own confirmation?

### Q3 — Historical recalculation semantics

- **Verdict: UNRESOLVED (evidence shows the primitives are partial).**
- **Evidence.**
  - **[F]** Present: results stamped with `formula_version`, `config_version`, `canonical_data_version`, `manual_adjustment_set`, `as_of_date`, `computed_at`; "historical results are never recomputed silently" (engine F3; `20260917_0001_engine_tables.py:57-79`).
  - **[F]** Absent: any link between a restated `metric_result` and the row it supersedes; any "restated" label; **effective dating on `manual_adjustment`** (no date column; period recoverable only from `target_ref` in two shapes, `cfo_actions.py:1320-1348`). So "what expenses applied to March as of 1 April" is not derivable.
  - **[F]** Insert-only evidence tables still carry `UPDATE/DELETE` grants for the app role (owner decision pending, `stages-3-4-5-report-2026-10-12.md:82`), so result immutability is not enforced by grants.
  - **[A]** Expense edits after the fact will change `manual_adjustment_set` on the next compute; whether the prior period's stored figure is re-run, left, or shown beside a restated figure is the open choice.
- **Decision still needed.** (a) Does an expense dated in a closed period trigger automatic restatement, an offered restatement, or none? (b) Are prior results shown alongside restated ones, and how labelled to the seller? (c) Is a date/period column added to the store (schema decision) or kept in `target_ref`?

---

## 2. Questions the draft says may remain unresolved

### Q4 — Review-status values and transitions

- **Verdict: UNRESOLVED; deferral is risky.**
- **Evidence.** **[F]** No such field; adding it is a registry amendment (Q1). The V1.0 dashboard (§4.1) requires a **review queue**, so the values are needed to build a stated V1.0 feature. Nothing in code constrains the choice.
- **Decision needed.** Values/transitions, or drop the review queue from V1.0. Reclassify as blocking-for-§4.1.

### Q5 — Retention period for structured records

- **Verdict: UNRESOLVED (matches draft).**
- **Evidence.** **[F]** Open in `auth.md` Q9, `data-foundation.md:902`, `phase-1-readiness-review.md` 2.21/3.11 (`[P]`). `manual_adjustment` is append-only with revoked DELETE, so *retention by default is indefinite*; erasure is a platform-wide pending decision (`stages-3-4-5-report-2026-10-12.md`, "Retention and erasure"; `phase1-phase2-engineering-report-2026-10-12.md:36`). **[U]** CA/lawyer input.
- **Decision needed.** Owner/legal: period and basis. Interim reality: indefinite, because no deletion path exists.

### Q6 — Reconciling the 30-day raw-upload deletion rule with receipt retention

- **Verdict: CONTRADICTED (premise).**
- **Evidence.** **[F]** I found no 30-day rule in any code or spec. `data-foundation.md:316` states raw files are retained *while the account is active*; deletion on closure is deferred (:902). **[F]** No scheduled deletion job exists; no report-file delete route found. **[U]** The cited source `legal-safeguards.md` §3 does not exist in the repository.
- **Decision needed.** Does the 30-day rule exist as an approved decision elsewhere (provide the document), or is it a proposal? Until then the draft's instruction not to "silently change the existing 30-day rule" refers to a rule the code does not implement.

### Q7 — Exact TCS and GST treatment and rates

- **Verdict: UNRESOLVED (matches draft); blocked on CA.**
- **Evidence.** **[F]** Engine has `TCS_COLLECTED`/`TDS_DEDUCTED` and a settlement-basis cash view; contribution profit is explicitly not cash (`cfo-agent.md:644`). Expense path carries only an optional `gst_amount_paise`. **[F]** GST is management-grade, not filing-grade (`cfo-agent.md` C4/§6.6). No GST/TCS rate is hard-coded for expenses.
- **Decision needed.** CA validation. Note the draft's "ITC-eligible?" flag has no engine consumer and could be mistaken for a determination; decide whether it is stored-only.

### Q8 — Default category list

- **Verdict: CONTRADICTED (deferral).**
- **Evidence.** **[F]** The category set is the engine registry's key space: five `expense.*` fields (`cfo_actions.py:286-297`; engine §7.2.1). The draft's own overhead examples (rent, salaries, software, utilities) have no category except `other`. A change is an engine amendment, and the UI hard-codes the five (`ExpenseTrackerSection.tsx`).
- **Decision needed.** Not deferrable: the V1.0 record schema depends on it. Choose: keep 5 + free-text description; add `expense.*` keys; or add a sub-category attribute (registry amendment either way).

### Q9 — CSV template columns, preview, error reporting

- **Verdict: UNRESOLVED; depends on Q3/Q8.**
- **Evidence.** **[F]** No expense CSV path. Reusable: capped upload, SHA-256 file dedupe, `ingestion_run` counts (read/accepted/rejected/duplicate). The ingest endpoint persists immediately — there is no preview step. **[F]** A template needs a **date**, which the store cannot hold natively (Q3). **[F]** Marketplace-adapter CSV rows land in `sales_line`/`settlement` tables, not `manual_adjustment`; an expense import would be a new write path into the adjustment store with `financials.adjust`.
- **Decision needed.** Whether rows import as `manual_adjustment` writes (permission = `financials.adjust`, one request per row or batch), and the date/period representation.

### Q10 — Does IndiaMART supply validated settlement-derived cost records?

- **Verdict: ANSWERABLE NOW — No. The premise in §5 is contradicted.**
- **Evidence.** **[F]** IndiaMART appears only as a supplier-discovery source, user-initiated, schema-only, **not implemented** (`product-intelligence-agent.md` C5/C6; `supplier_lead.source`). Supported sales channels are Amazon, Flipkart, Meesho (CLAUDE.md). No IndiaMART adapter exists. §5's "supported through existing Metrion capabilities: … IndiaMART" is not true of any capability.
- **Decision needed.** Remove IndiaMART from the supported list (manual channel tag only), or approve a new adapter as separate scope.

---

## 0A. "Proposed" defaults in the draft, checked against evidence

These are not numbered questions and are not re-recommended here; they are listed because each carries an implicit decision the evidence touches.

| Draft ref | Proposed default | Verdict | Evidence / decision needed |
|---|---|---|---|
| §4.2 | Controlled default category list only | UNRESOLVED | See Q8. |
| §4.3 | Fixed CSV template; mapping later | UNRESOLVED | See Q9. |
| §4.3 | Likely duplicates flagged, never silently discarded | **PARTLY CONTRADICTED** | **[F]** The marketplace ingest path *counts duplicates* but dedupes by natural key (`row_count_duplicate`), and file-level dedupe returns `duplicate: True` without re-ingesting (`cfo.py` ingest). "Never silently discarded" is stricter than the existing pattern. Decide which convention applies to expenses. |
| §4.4 | Org validated server-side at proposal and save | SUPPORTED for the save path | **[F]** tenant from verified session (`auth/context.py`), RLS FORCE. **No proposal object exists** to bind; see Q-new-1. |
| §4.5 | Unavailable allocation basis ⇒ unallocated and visible | UNVERIFIED | **[A]** `allocate_pool` handles zero/negative-revenue exclusions; I did not trace an "unallocated pool" outcome. D7 default is *automatic* revenue-share allocation, which differs from "business-level by default" (Audit §3). Decide the default. |
| §4.7 | Overlap flagged for review, not auto-matched | SUPPORTED in principle, **MISSING** in code | No overlap detector; settlement can already contain ad/storage (Q1). |
| §4.8 | Restate via traceable recalculation | UNRESOLVED | Q3. |
| §5 | IndiaMART manual-only | SUPPORTED (stronger than draft) | Q10. |
| §6 | PARTNER lacks `financials.adjust` by default | SUPPORTED | `auth.md:230-232`. |
| §8 | Economic margin is the headline; cash view separate | SUPPORTED (consistent with engine) | `cfo-agent.md:644`; settlement-basis cash view. |
| §9 | No new public file-serving path; private storage | **CONTRADICTED (premise)** | No object storage exists; local disk with content-hash names in a shared directory (Audit §9). Decide storage before any receipt reference is built. |
| Draft §4.4 | CFO chat extracts a proposal | **CONTRADICTED** | CEO C21/E30; no CFO chat; approval workflow unimplemented. See below. |

---

## 3. Decisions the draft does not list but the evidence requires

| ID | Decision | Why (evidence) |
|---|---|---|
| **N1** | **Quick-add vs C21.** Reverse C21 for `cfo.enter_expense` (a spec change owned by CEO orchestration) — or limit V1.0 to forms and move quick-add behind the approval workflow | `ceo-agent-orchestration.md:34,407,983`; `registry.py:52-53`; `classifier.py:83`; approval workflow unimplemented (`ceo-approval-workflow.md:3`). C21 says a future write "needs its own spec: explicit confirm step, re-check of every permission including `financials.adjust`, own acceptance criteria". |
| **N2** | **Extend or replace the shipped expense tracker** | P4 in the audit. Existing data written through `ACCOUNT/"default"` has no date. A migration/compat story is required either way. |
| **N3** | **Are expenses first-class rows or `manual_adjustment` rows?** | `manual_adjustment` cannot natively hold date, vendor, statuses, treatment, currency, source reference; cannot edit across target/field; cannot delete. `cfo-agent.md:113` records that `expense_entry` etc. were **removed by design** to avoid duplicating `manual_adjustment`. Reintroducing a table contradicts that decision; keeping the store requires the registry amendments in Q1/Q4/Q8. |
| **N4** | **How stored expenses reach Contribution Profit** (and which categories) | `cfo_actions.py:453-454, 1170-1181`; no reader of stored pools. Today an entered expense does not change margin. |
| **N5** | **Currency field** | Engine is INR-paise only; a `currency` field has no representation. Drop or define. |
| **N6** | **Audit of direct-path writes** (`agent_run`) | `cfo-agent.md:289` records the gap (CEO Q16). Decide whether expense writes must write `agent_run` or rely on `manual_adjustment.created_by` alone. |
| **N7** | **Validation of expense values on write** | `enter_expense` does not validate `value`; malformed rows break `GET /cfo/expenses` for the tenant (`cfo.py:471-475`). Decide bounds (sign, zero, max, GST ≤ amount, allowed `marketplace` values). |
| **N8** | **Whether `legal-safeguards.md` and `phase1-decisions.md` are to be written** | They are cited as dependencies and do not exist. The draft cannot be reviewed against them. |

---

## 4. Summary for the reviewer

| Draft Q | Draft classification | Evidence verdict | Suggested reclassification |
|---|---|---|---|
| 1 | Blocking | Partly contradicted | Blocking (and larger than stated) |
| 2 | Blocking | Partly supported / contradicted | Blocking |
| 3 | Blocking | Unresolved; primitives partial | Blocking |
| 4 | Deferrable | Unresolved | Blocking for the §4.1 review queue |
| 5 | Deferrable | Unresolved (needs legal) | Deferrable (launch-gating for retention claims) |
| 6 | Deferrable | Premise contradicted | Clarify source first |
| 7 | Deferrable | Unresolved (needs CA) | Deferrable; launch-gating for tax output |
| 8 | Deferrable | Contradicted (it defines the schema) | Blocking |
| 9 | Deferrable | Unresolved; depends on Q3/Q8 | Deferrable until Q3/Q8 settle |
| 10 | Deferrable | Answerable: No | Resolved by evidence; amend §5 |
