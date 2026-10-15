# Metrion — Expense Tracker Specification

> **Status: DRAFT v4 — canonical, consolidated. NOT APPROVED FOR IMPLEMENTATION.**
> The product decisions in §1 were approved by the owner on 2026-10-15 and are recorded in `docs/decisions/phase1-decisions.md` (EXP-01…EXP-08, ST-01). Everything else in this file is a proposal, a deferral, a gate or an open question, and is labelled as such. **No code, migration, endpoint or permission change may start until §10 gate G1 is met.**
> **Frozen for G1 review at commit `e91136a`** (2026-10-16). No normative change to this file after that commit except this header block; later edits go to the register, decisions record or a new revision.
> **Q1 countersign (EXP-01…EXP-08):** ______________________  (owner name, date)

**Authority.** This file is the single canonical Expense Tracker spec. It replaces the root `expense-tracker.md` ("DRAFT v2", now archived at `docs/planning/expense-tracker/archive/expense-tracker.md`) and the earlier parallel drafts; their unique content is reconciled in Appendix A.
**Prerequisites and related specs.** `deterministic-engine.md` (D7, §5.8, §5.10 amended 2026-10-15) · `cfo-agent.md` ("Removed by design" amended 2026-10-15) · `auth.md` · `data-foundation.md` · `ceo-agent-orchestration.md` (C21, §6.11, §6.33, Q33; E30/T36 amended 2026-10-15) · `ceo-approval-workflow.md` · `product-intelligence-agent.md` (IndiaMART) · `calculator.md` (hypothetical estimates stay separate; on branch `feat/pnl-calculator-integration`, not merged here).
**Planning evidence (not authority).** `docs/planning/expense-tracker/` — `00-index.md` explains which files are current and which are historical evidence.

### Label legend (used throughout)
| Label | Meaning |
|---|---|
| **[APPROVED]** | Owner-approved requirement or decision (§1). Binding on design. |
| **[PROPOSED]** | Recommended design, not approved. |
| **[DEFERRED]** | Explicitly out of V1.0. |
| **[GATE]** | Must be true before the named step. |
| **[OPEN: owner/eng/sec/legal/CA]** | Needs that party's decision. |
| **[BLOCKED]** | Cannot proceed because an authoritative approved decision conflicts; see the item. |
| **[VERIFIED]** / **[UNVERIFIED]** | Fact checked in the repository at base commit `91bebf4` / not checkable. |

---

## 1. Confirmed decisions and requirements [APPROVED]

### 1.1 Product requirements (owner brief)
| # | Requirement |
|---|---|
| P1 | The Expense Tracker is a **cost-input and expense-management module inside CFO → Profit & Finance**. It is not a new AI agent, not a new top-level navigation destination, not a replacement accounting system and not an independent calculation engine. Brain 1 stays the authority for financial calculation; CFO stays the customer-facing financial interface. |
| P2 | **V1.0 scope:** expense dashboard (monthly totals, category breakdown, recurring commitments, review queue, each with an explicit as-of timestamp); manual create / edit / void / review; **controlled categories**; **recurring templates**; **validated CSV import** with a documented template and duplicate detection; **review status**; **source references**; **optional SKU association**; fields amount, category, date, vendor, payment status, channel scope, tax fields, description; approved integration into the existing financial engine; audit history. |
| P3 | **Payment status** values: `unpaid`, `partially_paid`, `paid`, `unknown`. Separate from review status; payment status never changes economic margin. |
| P4 | **Controlled initial categories** (closed list in V1.0; custom categories deferred). Contents open (§13 Q5). |
| P5 | Marketplace-derived costs come from authoritative settlement/source records and are **never re-entered** as manual expenses without reconciliation safeguards. Direct costs may be SKU-associated when data allows. Validated advertising records are distinguished from manual ones. |
| P6 | Business-level overhead is **unallocated by default** (EXP-06). Contribution margin is distinct from fully allocated profitability. |
| P7 | The LLM may **extract only vendor, category and date for a draft (§7.1), propose and explain stored figures**; it must not calculate an authoritative monetary result, produce a monetary form input, or write a financial record (EXP-03). |
| P8 | Never double-count settlement-derived costs, COGS or advertising spend. **Never treat a missing amount, missing fee or unknown advertising spend as zero** (in storage and display). *Tension recorded, not resolved here:* the engine's confirmed rule (`deterministic-engine.md` §5.8 "Absent `expense.advertising` — CONFIRMED") resolves absent advertising to zero **inside the formula**; the owner approved only the display fix ST-01 (§6.8, Q18). Preserve provenance, audit history and reproducibility. |
| P9 | GST-inclusive/exclusive status, GST amount and an informational ITC-eligible flag may be stored; no filing-grade tax claim; **CA review of GST, ITC and tax treatment is required**. **TCS is never an operating expense**, separate from GST credit. |
| P10 | Tenant isolation and active-organization authorization are enforced server-side for draft creation and confirmation; confirmation is idempotent. |
| P11 | Supported channels only where validated data flows exist (Amazon, Flipkart, Meesho). Manual channel tags are never presented as integrations. |
| P12 | **Deferred (not V1.0):** receipt OCR (local vision path), WhatsApp quick-add, bank-statement import. *"V1.5" in earlier drafts and the owner brief is a label for "after the first release"; the readiness review locks "one V1, no V1.5 tier", so no tier is created here.* **No retention change** and no invented "30-day deletion" claim. |
| P13 | **Currency: INR in integer paise only** (EXP-08). No currency field unless the engine is expanded by a separately approved decision. |

### 1.2 Approved architectural decisions (`docs/decisions/phase1-decisions.md`)
| ID | Decision (summary) | Register | Status / conflicts |
|---|---|---|---|
| **EXP-01** | Dedicated **append-only expense ledger** feeding Brain 1 through an explicit contract; treatments `incremental`, `already_in_settlement`, `informational`; **`replaces_input` dropped** | D1 | Approved. `cfo-agent.md` "Removed by design" **amended 2026-10-15** (EXP-07) |
| **EXP-02** | **Versioned results**: inputs, formula version, config version, period and as-of recorded; prior results never overwritten. **Historical-result policy:** no automatic restatement of reported periods when a new formula is released; old results keep their original formula/config version and inputs; the new formula applies from an approved release date (**placeholder, owner to set**); formula version labelled on every result; any later recalculation is a separate explicit, labelled, linked restatement workflow | D2 | Approved. Schema additions needed (§5.4) |
| **EXP-03** | **No chat writes.** The CEO (the sole conversational interface) may prepare a draft that pre-fills **only vendor, category and date**; the seller types the **description and the amount** on the form and confirms there | D3 | Approved and **reconcilable** with C21/§6.33/§6.11 (analysis in `phase1-decisions.md`); E30/T36 **amended 2026-10-15**; follow-up amendments approved 2026-10-15 as spec text only and applied (§7, Appendix B.4); code and tests unchanged, G6 gates implementation |
| **EXP-04** | IndiaMART is **supplier discovery**, not a supported sales channel; manual tag only | D14 | Approved, no conflict |
| **EXP-05** | **No new permission key in V1.0.** `financials.adjust` governs every ledger write. Known limitation documented (§8). `expenses.write` is **not** introduced; the earlier recommendation is **SUPERSEDED** | D11 | Approved; consistent with Q33 and `cfo-agent.md` §8 rule 4; no conflict |
| **EXP-06** | Overhead **unallocated by default**; allocation only on explicit supported basis with valid data; otherwise unallocated with a reason; engine does all allocation | D9 | Approved. `deterministic-engine.md` D7, §5.8, §5.10 **amended 2026-10-15**; A1–A10 are a launch requirement (G2). No engine code changed |
| **EXP-07** | Reversal of `cfo-agent.md` "Removed by design" for expenses only | D1 | Approved; amendment applied 2026-10-15 |
| **EXP-08** | Currency INR paise only | X4 | Approved |
| **ST-01** | Show "Not entered" for absent advertising spend — **separate task**, not part of the Expense Tracker | — | Approved as separate task; Appendix D |

---

## 2. Design decisions requiring review [OPEN]
Full register: `docs/planning/expense-tracker/02-decision-register.md`. Owner decisions on Q2, Q4, Q14–Q16, Q18–Q21, Q24, Q25, Q27, Q28, Q29 and Q30 were recorded 2026-10-15 (§13; `phase1-decisions.md` "Owner decisions on open questions"). Still open: D4 category contents · D5 review-status values · D6 duplicate thresholds · D7 settlement-overlap UX · D8 advertising reconciliation · D10 CSV template · D12 retention and storage · D13 multi-organization details · X1 legacy tracker compatibility · X2 write-validation bounds · X3 `agent_run` for expense writes · X6 tax wording · X7 TCS · the concrete formula release date (defined by event, Q15). Approved items are closed at product level; their implementation details remain proposals (§5–§8).

## 3. Assumptions
- **[A]** The reporting period is a calendar month of the record's `effective_date`.
- **[A]** Imported rows enter `needs_review` (proposed default).
- **[UNVERIFIED]** A "30-day raw-upload deletion rule" — none exists in code or specs (G4).
- The "Q2 expense-confirmation flow" cited in the owner brief **came from a decisions document drafted in chat and has no repository source** (owner, 2026-10-15). It is recorded that way and is not an approved repository decision; Q33 (2026-10-10) is the related decided item.

## 4. Goals and non-goals
**Goals.** A traceable path from a recorded expense to a stamped, reproducible, version-labelled margin figure; no double counting; no silent zeros; safe, idempotent, tenant-isolated writes.
**Non-goals (V1.0).** Bookkeeping, ledger-as-accounting, invoicing, GST filing; filing-grade tax output; automatic reconciliation for unsupported channels; receipt upload/OCR; WhatsApp or bank-statement input; custom categories; a currency field; any retention change; a new agent; a new top-level nav item; browser-side or LLM-side money arithmetic; a new permission key.

---

### 4.1 Positioning note (non-normative)

The tracker's goal is that every expense shows where it landed in profit, including "unallocated". The product may flag possible overlap with settlement costs for seller review but must not claim automatic verification. This note adds no requirement.

## 5. Data model [PROPOSED — conceptual, not a migration]

### 5.1 Ledger (EXP-01)
All tables carry `tenant_id`, `FORCE` RLS (the same `tenant_isolation` policy as `manual_adjustment`, `_TENANT_RLS_SQL` in the engine migration; exact `USING`/`WITH CHECK` shape to be copied, not re-invented) and no app-role `UPDATE`/`DELETE`. Status changes of drafts, import batches and templates are **appended as events**, never updated in place ([VERIFIED] `packages/calc-engine/migrations/versions/20260917_0001_engine_tables.py`; append-only test pattern `packages/calc-engine/tests/integration/test_manual_adjustment_append_only.py`).
- `expense_record` — immutable creation: `id`, `tenant_id`, `idempotency_key` (unique per tenant), `source_kind` (`manual | csv | draft_confirm`), `source_ref`, `created_by`, `created_at`.
- `expense_event` — append-only source of truth: `expense_id`, `seq`, `event_type` (`created | edited | voided | reviewed | payment_updated | overlap_resolved | duplicate_resolved`), `effective_date`, `category`, `cost_class`, `treatment`, `amount_paise` (integer paise; **no currency column**; **sign convention DECIDED 2026-10-15 (Q21), consistent with the locked rule** (a ledger-local convention; the locked rule does not itself say a cost is positive) (money is signed `BIGINT` paise, seller perspective: `phase-1-readiness-review.md` §1, `deterministic-engine.md` §4; by analogy, the engine models a marketplace credit note as a negative signed line, E1 — a different object, and E1's period rule is not borrowed here): the ledger stores `amount_paise` **signed — a cost is positive; a vendor refund or credit note is a negative record that references the original `expense_id`**; it is never floored at zero and a negative net total is shown as negative. The engine spec does not state how a cost term is signed, so the feed (§5.3) alone maps the ledger sign to the engine's representation and must state it in the feed contract (Appendix B.3); no other consumer interprets the sign. A refund or credit note belongs to the period of its **own date**, linked to the original expense; the original period is never restated (Q24, decided 2026-10-15), `gst_basis`, `gst_amount_paise`, `itc_eligible_flag`, `vendor`, `channel_scope`, `sku`, `payment_status`, `paid_amount_paise`, `review_status`, `overlap_status`, `duplicate_status`, `description`, `reason` (required on edit/void), `actor`, `recorded_at`.
- Templates, import batches/rows, drafts: as `03-architecture-options.md` §3.1. Receipts are not stored in V1.0.

### 5.2 Source references, overlap, duplicates, unresolved conflicts (EXP-01)
- `source_ref` is free text plus an optional structured pointer (`import_batch_id:row`, `draft_id`, external document number). It never carries a file or URL that Metrion serves.
- **Overlap status** (`none | candidate | confirmed_in_settlement | confirmed_incremental | unresolved`) and **duplicate status** (`none | exact_duplicate_of:<id> | probable_duplicate | confirmed_distinct`) are explicit fields on the event.
- **Rule.** A record whose overlap or duplicate status is `candidate`/`unresolved`/`probable_duplicate` is **never silently counted and never silently dropped**: it appears in the review queue with the amount it would add, is excluded from figures labelled "confirmed", and may be shown in a clearly labelled "including unresolved" view. Resolution is a person's action recorded as an event.

### 5.3 Brain 1 integration contract [PROPOSED]
A pure Brain 1 function reads validated ledger events (latest state per record; `review_status=confirmed` and `treatment=incremental` count) and returns per `(period, channel scope, class)`: `Paise` totals, named gaps (e.g. "advertising: not entered"), overlap flags and the ledger **watermark** used. Compute paths (`compute_period_pnl`) call it instead of taking caller-supplied pool lists. Outputs are stamped (§5.4). No arithmetic outside `packages/calc-engine`; any SQL that selects or aggregates ledger rows lives **inside the engine's feed** (inside `packages/calc-engine`), never in an API route, service or the browser. **Every dashboard aggregate — monthly totals, category breakdown, recurring-commitment totals, review-queue amounts and the "including unresolved" view — is produced by Brain 1 through that feed and returned ready to display; each figure carries its `engine_result_ref` (`estimate_ref` is reserved for third-party estimates and is not used for ledger figures).** The record-state conditions above (`confirmed`, `incremental`, latest state) are a **proposed input contract delegated to the engine**: the engine spec does not yet define them, and the engine owns the final definition (Appendix B.3). The `review_status` vocabulary is itself open (Q6), and the engine-side work this needs — new `metric_code`s for the dashboard aggregates and the feed — is not yet in the engine spec and is listed as required engine work (G2).

### 5.4 Versioned results (EXP-02) [PROPOSED schema additions]
[VERIFIED] `metric_result` today has `formula_version`, `config_version`, `canonical_data_version`, `manual_adjustment_set`, `as_of_date`, `period`, `input_refs`, `exclusions`, `computed_at`, `is_trial`, and **no** link from a later result to an earlier one, no restatement flag or reason, and no ledger input version. Proposed additions: `input_version` (ledger watermark), `supersedes_result_id`, `result_kind` (`reported | restated`), `restatement_reason`. A stored result is never updated; revoke `UPDATE/DELETE` on `metric_result` for the app role in the same migration ([UNVERIFIED] whether the grant exists today). The formula version is displayed with every result.

---

## 6. Core rules
### 6.1 Contract and treatment [APPROVED shape, PROPOSED detail]
`incremental` counts; `already_in_settlement` is retained for reconciliation and excluded from additional counting; `informational` is excluded from profit. No `replaces_input`.
### 6.2 Cost classes [APPROVED, P5]
Marketplace-derived (settlement only, never re-entered) · direct (packaging, inward freight; SKU optional) · advertising (manual unless a validated source exists — none exists today: no ad adapter in `data_foundation/adapters/`) · business overhead · COGS (stays `cogs_per_unit`, never an expense amount). Hypothetical scenarios (the Profit Calculator) are never persisted as expenses.
### 6.3 Channel scope [APPROVED, P11, EXP-04]
Each record is business-wide or channel-specific. Amazon/Flipkart/Meesho tags reflect existing flows; other tags (own website, WhatsApp orders, IndiaMART, other) are labelled "manually tagged, not synced".
### 6.4 Settlement overlap [PROPOSED]
Marketplace fee categories are not offered as manual categories. [VERIFIED] settlement data can already contain ad/storage cost (`data_foundation/component_registry.py` `NON_ORDER_FEE`, Flipkart "Non-Order Charges"), so an advertising/storage entry for a channel-period that has settlement-derived cost raises an overlap `candidate` carrying the engine's settlement figure; the seller (or reviewer) chooses `incremental` or `already_in_settlement`. Amount/date similarity only flags; it never matches automatically.
### 6.5 Duplicates [PROPOSED]
Exact source-id match ⇒ idempotent same record; exact normalised match ⇒ `probable_duplicate` held for review; similarity ⇒ hint only. Nothing is discarded.
### 6.6 Advertising [PROPOSED]
Every advertising figure is labelled `MANUAL`; a future validated source gets distinct provenance and a period holding both raises a reconciliation task. Absent advertising is displayed "Not entered" (separate task ST-01, Appendix D).
### 6.7 Overhead and allocation [APPROVED, EXP-06]
Business-level overhead is unallocated by default and sits **outside contribution margin**; the fully allocated figure is separate and states its basis. Allocation requires an explicit seller-selected basis (`NET_REVENUE | UNITS | ORDERS`, as supported) and valid data for the same period and channel scope; otherwise the amount stays unallocated with a reason code (`BASIS_NOT_SELECTED`, `NO_REVENUE_FOR_PERIOD`, `ZERO_DENOMINATOR`, `UNITS_UNAVAILABLE`, `INVALID_BASIS`). Allocation uses `largest_remainder_allocate` so shares sum exactly to the pool (`calc_engine/rounding.py`). A later basis change takes effect under the formula/config version in force from then on; it never rewrites a reported result (§6.13). **This is an engine behaviour change** (the amended `deterministic-engine.md` D7/§5.8/§5.10 describe the target; engine code is unchanged), and the A1–A10 suite (§12) is a **launch requirement** (G2). **Decided 2026-10-15 (Q14): account-level *advertising* and *storage* pools are covered by the same rule (§6.13 rule 8).** The engine amendment now names the lines `UnallocatedAdvertising`/`UnallocatedStorage` (Q27); the total-profit formula is not decided (Q30).
### 6.8 Missing is not zero [APPROVED, P8]
An unknown amount is `unknown`; a blank amount cannot be submitted as zero (`CostInput` pattern, `frontend/lib/costInput.ts`). [VERIFIED] The engine deliberately resolves absent `expense.advertising` and `expense.other` to zero (`deterministic-engine.md` §5.8 "Absent `expense.advertising` — CONFIRMED"; `cfo/pnl/inputs.py::resolve_expense_pool_total`); that formula rule is unchanged and only its **display** is fixed under ST-01.
### 6.9 Edits, voids, history [PROPOSED]
Edits and voids append events with a required reason; the app role cannot update or delete. Current state is derived from events. An edit dated inside an already-reported period does **not** change the reported result (§6.13).
### 6.10 Tax [APPROVED, P9]
GST basis/amount and the informational ITC flag are stored, labelled "Estimate for planning purposes. Verify with your CA." TCS is never an operating expense, never subtracted and then credited, and appears only in the cash/settlement view (`calc_engine.api.cash_reconciliation`, engine §5.13.3). `TCS_COLLECTED` is a real settlement field for Flipkart only; other channels are unverified (Q26). Treatment and rates need a CA [OPEN: CA].
### 6.11 As-of [APPROVED, P2]
Every dashboard figure states its as-of timestamp, the ledger watermark and the formula version it used, and cites its `engine_result_ref`.
### 6.12 CSV import [PROPOSED]
Upload → preview (writes nothing) → confirm; row-level error report; safe re-upload (file hash and row keys); imported rows `needs_review`; confirmation requires `financials.adjust`. **Raw-file retention is UNRESOLVED (G4, Q19; legal/CA review):** the options are retaining the raw file (consistent with the locked "immutable raw files, re-runnable parse runs" principle for marketplace report ingestion) or keeping only parsed rows. This spec leans toward neither; the locked "immutable raw files, re-runnable parse runs" principle in `phase-1-readiness-review.md` §1 is stated for marketplace report ingestion and whether it extends to expense CSVs is not decided here. Template columns [OPEN: owner].
### 6.13 Historical-result policy [APPROVED, EXP-02 clarification]
1. **No automatic restatement.** Releasing a new formula or a new allocation behaviour never recomputes previously reported periods.
2. **Preserve.** Old results keep their original formula version, configuration version and inputs.
3. **Forward only.** The new formula version applies to calculations from the **approved release date** — `<RELEASE_DATE: placeholder — product owner to set>` — onward. **Release date (Q15, refined by Q28, decided 2026-10-15):** the date of the **first production deploy that follows G7 passing with results produced as `is_trial=false`**. It stays the placeholder `<RELEASE_DATE: placeholder — product owner to set>` until that deploy, then the concrete date is recorded here, in `phase1-decisions.md` and in the engine amendment.
4. **Label.** The formula version is shown on every result.
5. **Explicit restatement only.** If recalculation of a past period is later requested, a separate explicit workflow produces a **linked, clearly labelled restated result**; the original is never overwritten. That workflow is not specified or built here.
6. **Consequence flagged for the owner.** Moving business overhead out of Contribution Profit (EXP-06) means results before and after the release date are not comparable without a label; sellers' existing `expense.other` rows currently reduce Contribution Profit (Q16).
7. **Existing `expense.other` rows (Q16, decided 2026-10-15).** They stay **untouched** under their original formula version; there is **no migration**. New entries use the ledger from the release date. A period straddling the release date therefore shows both formula versions (rule 5).
8. **Account-level advertising and storage pools (Q14, decided 2026-10-15).** EXP-06 covers them: the same rule applies (unallocated unless the seller explicitly selects a basis). Consequence for the owner to be aware of: account-level ad or storage spend no longer reduces SKU-level contribution by default; it is reported as unallocated with the reason.
9. **Unattributed spend (Q27, decided 2026-10-15).** Advertising or storage spend that cannot be attributed to a SKU stays **business-level** by default; spend that comes from **validated** campaign/ASIN records stays **SKU-level** (validation rule: Q29, decided below). Unallocated advertising and storage are reported as **their own labelled lines beside contribution profit**, never zero-filled and never hidden; **total profit includes them**. Pricing recommendations and loss-making-SKU alerts **must carry a caveat that unallocated spend is excluded**; the what-if feature uses the **fully loaded** figure (the engine spec owns the formula: Q30). A **seller-facing release note** explains the contribution-profit change at the release date. Q29 rule: A campaign/ASIN spend record is **SKU-level only if** (a) it comes from a **validated import or integration**, (b) the source data carries an **explicit ASIN or SKU identifier**, and (c) that identifier **maps to a SKU in the seller's catalog**. Campaign-level spend **without an ASIN breakdown stays business-level**. **Manual entries are never SKU-level by default**; a seller may tag a SKU on the form and the entry **stays flagged manual**. **Unmapped identifiers go to a review queue and count as business-level until resolved.** Engine definition: `deterministic-engine.md` §5.8 amendment. The consumer specs (pricing/PI, alerts, calculator) are not edited here (Appendix B.11).
10. **Trial results (Q28, decided 2026-10-15).** G7 validation results use a **distinct trial formula version** with `is_trial=true`. They are **never shown in seller history or seller-visible reports** and **never serve as a restatement baseline**. The release date is the first production deploy after G7 passes producing `is_trial=false` results. Acceptance: AC12.
11. **Total-profit invariant and `is_trial` (Q30, decided 2026-10-15).** The **engine spec owns the total-profit formula**; this spec states only the invariant that **changing the allocation method never changes total profit** (tested under G2, F5). `is_trial` is a **boolean on the result record**, **excluded from every seller-facing read at the read layer**; the **name of the trial formula version is an engine-spec decision**. Q29 and Q30 are **prerequisites for G2, not G1**.
12. **Launch condition for the ledger feed (decided 2026-10-15):** the pricing, alert and what-if consumer specs must carry the unallocated-spend caveats **before release** (Appendix B.11).

## 7. AI requirements (EXP-03, P7)
### 7.1 What the CEO may do
The CEO (sole conversational interface; CFO is reached only through it) may prepare a **draft** that opens the Expense Tracker form **pre-filled with exactly three non-monetary fields**:
| Field | Rule |
|---|---|
| `vendor` | Free text extracted as a text slot; length-capped; **rejected by code** if it contains an amount-like or currency pattern (proposed validation) |
| `category` | Must resolve, by code, to a value of the controlled category list; unresolved ⇒ left empty |
| `date` | Parsed and validated by code (calendar date); unresolved ⇒ left empty |
**Never extracted, never pre-filled:** `amount`, `gst_amount`, `paid_amount`, `description`, `treatment`, `review_status`, `sku`, `channel_scope`, tenant id, draft id. **The seller types the description and the amount on the form and explicitly confirms.** Any amount-like text in the chat message is ignored for form purposes. Rationale: a free-text description can carry money, which would break "money is never typed into chat / never inferred" (`ceo-agent-orchestration.md` §6.3/§6.33).
### 7.2 What it may not do
Compute, allocate, round or alter an amount; produce a monetary form input; write, authorize or commit a financial record; supply the organization, draft id or treatment as authoritative values. **Nothing is saved from chat.** The form submission is the only write and it is a direct surface (`financials.adjust`).
### 7.3 Draft object and idempotency
Creating a draft requires an authenticated active member who holds `financials.adjust` (decided 2026-10-15, Q20), in addition to the ordinary permission to converse with the CEO; a member without it is not offered the draft and gets the existing explanation to use the direct surface. "The ordinary permission to converse with the CEO" is the existing CEO conversation permission (`agent.ceo`); no change to it. `financials.adjust` is checked again at confirmation. Server-minted `draft_id`; bound to `(tenant_id, requested_by)`; immutable payload hash of the three fields; expiry (proposed 30 minutes, mirroring C6); single-use confirm (unique key / guarded status transition); a retry returns the original record. At confirmation the server re-resolves the active organization from the verified session (`auth/context.py::resolve_auth_context`), re-checks `financials.adjust` and the CFO entitlement, and rejects a mismatch with 404.
### 7.4 Reconciliation with existing CEO rules [VERIFIED analysis; amendments in Appendix B.4]
| Rule | Reconciled? |
|---|---|
| **C21** (no write-class action in the V1 registry; AC23) | **Yes.** A draft is not "creating a manual financial input, editing books, uploading files or writing a marketplace"; the form submission is the write. `cfo.enter_expense` stays forbidden. Precedent: CEO may *propose* a goal as a `DRAFT` that becomes `ACTIVE` only on explicit confirmation by a member holding `financials.adjust` (`ceo-agent-orchestration.md` §6.20 lifecycle). |
| **§6.33 / §6.3** ("money is never typed into chat"; `action.inputs` "never produced by the classifier or any model"; "the model never produces a reference") | **Yes, narrowly.** The `action.inputs` sentence is scoped to the two **playbooks**; the expense draft is not an `action.inputs` object and carries no money. The model produces only text slots (§6.3 rule 3), already allowed, limited here to vendor, category, date. The owner's broader principle ("form inputs are never produced by any model") is **not** a sentence in the spec; it is honoured by excluding monetary and free-description fields. A one-sentence scoping sentence approved and applied 2026-10-15 (B.4). |
| **§6.11 future-write re-authorization** ("re-check of every permission including `financials.adjust`") | **Yes, unchanged.** The write requires `financials.adjust`. |
| **E30 / T36** (record-an-expense requests are declined) | **Amended 2026-10-15** (B.4). |
| **Registry effect classes** (READ · COMPUTE_PERSIST · GENERATE_METERED · RECORD_CHOICE; "WRITE is not permitted in V1") | **Follow-up needed:** a persisted draft fits none of the four exactly; adding a draft/proposal effect class and a registry key (e.g. `cfo.expense_draft`) is a scoped §6.11 amendment under its own acceptance criteria (B.4). Approved 2026-10-15 as spec text and applied to `ceo-agent-orchestration.md` §6.11; code unchanged (G6). |
| **`FORBIDDEN_ACTION_KEYS`** (`backend/src/backend/ceo/registry.py`) | **No change needed.** `cfo.enter_expense` and `cfo.expense_budget_set` stay forbidden; the draft uses a different, non-write key. Code is not modified here. |
| **Classifier** (`ceo/classifier.py` OUT_OF_SCOPE lists "recording expenses") | **Code/prompt follow-up:** "record this expense" would route to the draft action instead of `OUT_OF_SCOPE`. Until implemented, code and tests still decline (conflict between amended spec and current code; flagged). |
| **AC21** (no numeric literal in composer output) | **Constraint:** the draft card's date and any digits are rendered by the UI/renderer, not stated by the composer. |
**Verdict: reconcilable without amending C21 or AC23; not BLOCKED.** It does need the scoped follow-up amendments above (registry effect class and key, §6.33 sentence, classifier route). **Owner approved them 2026-10-15 as spec text only** (Q2): the text is now in `ceo-agent-orchestration.md` §6.11 and §6.33. The CEO code and tests are unchanged until implementation is approved, and G6 remains the gate; until then the code and tests still decline.
### 7.5 Evals
Any extraction surface needs LLM evals (`CLAUDE.md`): never emits an amount or description; missing fields stay empty; injected instructions in the message ignored; amount-like vendor text rejected; no numeric literals in narration.
### 7.6 Deferred
Approval-workflow plan/hash approval (`ceo-approval-workflow.md` C6–C8) is **not** required for a form-confirmed draft; it is only relevant if the owner later wants chat-initiated confirmation (not approved).

## 8. Authorization and security
1. **`financials.adjust` governs every ledger write** (create, edit, void, review change, CSV-import confirmation, draft confirmation, and draft creation from the CEO per Q20) — [APPROVED] EXP-05. OWNER holds it implicitly; PARTNER is denied by default and only by explicit OWNER grant (`auth.md` §5.2, D4; [VERIFIED] `auth/permissions.py::has_permission`). Also required: `agent.cfo` and the CFO entitlement, as in `api/v1/cfo.py::put_expense` [PROPOSED].
2. **No new permission key** in V1.0. `expenses.write` is **not** introduced; the earlier recommendation is **SUPERSEDED**. Revisit only when a partner-permission grant surface exists ([UNVERIFIED]: none found in `backend/src`) or a new approved authorization decision is made.
3. **Known limitation [APPROVED to document].** `financials.adjust` covers **every field of the `deterministic-engine.md` §7.2.1 registry** (`auth.md` §5.2) — COGS, discount-bearer, settlement receipts, supplier quotes, budgets, expense pools. A partner who is granted it to enter expenses can also change COGS and the other margin-moving inputs. There is no narrower key until one is approved.
4. **Reads** follow existing behaviour: `agent.cfo`; no financial-read key exists ([VERIFIED]).
5. No endpoint accepts `tenant_id`; the active organization is the verified Clerk `org_id`; every new query carries an explicit `tenant_id` predicate in addition to RLS ([VERIFIED] some existing `manual_adjustment` reads rely on RLS alone).
6. Idempotency keys on create, import confirm, draft confirm and recurring posting.
7. No new public file path; no receipt storage; no retention claim (G4).
8. Writes also write an `agent_run` (`DIRECT`) [OPEN: X3].
9. `auth.md` literally says `financials.adjust` covers "every field in the §7.2.1 registry"; the ledger is not a registry field. A one-line clarification (no key change) was approved and applied to `auth.md` 2026-10-15 (B.1, Q4).

## 9. Edge cases (to be completed at G1)
Expense dated in a closed (already reported) period; edit changing category or period; void of an allocated overhead; two identical legitimate monthly bills; mixed date formats in CSV; partial payment; channel-specific overhead with no revenue in that channel; zero/negative-revenue SKUs in allocation; advertising entered for a month with settlement ad cost; draft confirmed after expiry or from another organization; organization switched mid-draft; legacy `ACCOUNT/"default"` rows with no date; a draft confirmed twice; a vendor string that looks like an amount, and the false-positive risk of the amount-pattern rule (e.g. a vendor named "3M", Q22); the release date passing while a month is partly calculated under each formula version.

## 10. Launch gates and production-validation blockers
| Gate | Must be true before |
|---|---|
| **G1 Design approval** | Any implementation. Owner countersigns EXP-01…08; remaining amendments in Appendix B approved or deferred; X1 decided; release date defined by event (Q15; concrete date recorded when known); `legal-safeguards.md`/`improvement-roadmap.md` located or their citations struck (Appendix C). |
| **G2 Financial integrity** | Any seller sees a ledger-derived margin: engine tests; reconciliation worked example per cost class; **the allocation regression suite A1–A10 passes (launch requirement, EXP-06)**; historical-result policy demonstrated (old result preserved, version label shown, explicit restatement produces a linked labelled result). The allocation suite and engine work must also cover account-level advertising and storage (Q14, Q27). **Feed sign-mapping test (Q21):** the feed maps the ledger sign (cost positive, refund/credit negative) to the engine's representation correctly in both directions (ledger → engine and engine result → ledger display), including a refund in a later period (Q24). F3 covers the unallocated advertising/storage lines (Q27); the pricing/alert caveat and what-if checks are B.11 follow-ups in the consumer specs. **Prerequisites (Q29, Q30; not G1):** the engine spec carries the Q29 SKU-level rule, the total-profit formula and the trial formula version name — written 2026-10-16 as engine §5.8.1/§5.10.1/§5.17/§9.2, **PROPOSED items awaiting product owner approval**; G2 cannot pass until they are approved. **Reconciliation criterion AC17 / test F7 (engine TP10).** **Invariant test F5:** changing the allocation method never changes total profit. **Launch condition for the ledger feed (decided 2026-10-15):** the pricing, alert and what-if consumer specs must carry the unallocated-spend caveats **before release** (Appendix B.11). |
| **G3 Security** | Any write route is enabled: S-series and idempotency tests on scratch Postgres; every-route 401/403 tests include the routes; two-tenant isolation green; **documented `financials.adjust` limitation visible to owners granting it**. |
| **G4 Retention and storage** | Any receipt reference/upload or retention statement: legal/CA decision; storage design; the "30-day rule" located or retired. |
| **G5 Tax wording** | Any GST/ITC field is displayed (ledger), or TCS (cash/settlement view only; the ledger has no TCS field): CA review; TCS shown only where the channel actually supplies it (Q26). |
| **G6 Draft-from-chat** | The chat-to-form draft is enabled: the Appendix B.4 amendments are already approved as spec text; the gate is **implementation approval**, evals green and the registry key, effect class and classifier route built; code and tests that still decline (T36) updated. |
| **G7 Production validation** | General availability: 3–5 sellers reconcile output with their records; accessibility; import scale check. Validation results are trial results (`is_trial=true`, distinct trial formula version); F2/AC12 must pass, and G7 passing means a run producing `is_trial=false` results (Q28). |

## 11. Acceptance criteria (draft)
| # | Criterion |
|---|---|
| AC1 | An `incremental`, confirmed ledger record changes the period figure only through the Brain 1 feed; the figure is stamped (inputs, formula version, config version, period, as-of) and reproducible. |
| AC2 | `already_in_settlement` and `informational` records never change a profit figure and are visible as such. |
| AC3 | A record with unresolved overlap or duplicate status is never silently counted or dropped; it is in the review queue with a traceable status. |
| AC4 | Contribution margin does not change when business overhead changes; the fully allocated figure shows its basis; a missing/invalid basis leaves the amount unallocated with a reason. |
| AC5 | No unknown or blank amount is stored or displayed as zero; absent advertising is **displayed** "Not entered" (ST-01) while the engine formula rule is unchanged (Q18 records that the formula and AC5 differ in spirit). |
| AC6 | Edits/voids never update or delete; history is complete; releasing a new formula does not change any reported result; every result shows its formula version; a requested restatement is linked and labelled. |
| AC7 | Retrying create, import confirm, draft confirm or recurring posting never creates a second record. |
| AC8a | A member without `financials.adjust` is not offered a draft and is pointed to the direct surface; draft creation and confirmation both check `financials.adjust`. |
| AC8 | A PARTNER without `financials.adjust` gets 403 on every ledger write; no new permission key exists; no route accepts `tenant_id`; tenant A cannot read or confirm tenant B's records, drafts or batches. |
| AC9 | The browser and the LLM perform no money arithmetic, rounding or aggregation for any tracker figure; every dashboard aggregate comes from Brain 1 with an `engine_result_ref`. |
| AC10 | No retention period, receipt storage or filing-grade tax statement is shown or implemented before its gate. |
| AC11 | Chat never saves an expense; a draft opens the form pre-filled with vendor, category and date only; amount and description are typed by the seller; nothing is saved until the seller confirms on the form. |
| AC12 | Trial results (`is_trial=true`, G7 validation formula version) cannot appear in any seller-visible report, history, export or restatement baseline. |
| AC13 | Engine/report scope: unallocated advertising and storage appear as their own labelled lines beside contribution profit, and total profit includes them. *Consumer-surface checks (pricing/alert caveat, fully loaded what-if) belong to the consumer specs: B.11.* |
| AC14 | A seller-facing release note describing the contribution-profit change exists before the release date. |
| AC15 | Changing the allocation method (basis, or allocated vs unallocated) does not change total profit (Q30). |
| AC16 | A manual entry is never SKU-level unless the seller tagged a SKU, and then it stays flagged manual; an unmapped ASIN/SKU identifier lands in the review queue and counts as business-level until resolved (Q29). |
| AC17 | **Reconciliation (G2).** For every period and channel scope, the dashboard expense total equals the P&L expense lines plus the unallocated lines; a missing (not entered), an explicit zero, an unallocated and an allocated value are kept distinct and never merged. |

## 12. Test scenarios
Full matrix: `docs/planning/expense-tracker/04-test-and-risk-matrix.md`. **Allocation regression suite (A-series) — launch requirement (EXP-06, G2):**
| ID | Scenario | Expected |
|---|---|---|
| A1 | No basis selected | No allocation; pool unallocated with `BASIS_NOT_SELECTED` |
| A2 | Explicit `NET_REVENUE` with valid data | Shares sum to the pool exactly (largest remainder); basis stamped |
| A3 | Explicit `UNITS` (and `ORDERS`, if supported) with valid data | As A2 on units / orders |
| A4 | Missing or invalid allocation data | Unallocated with a reason; margin unaffected |
| A5 | Zero denominator (total revenue/units = 0) | Unallocated with `ZERO_DENOMINATOR`; no divide error |
| A6 | Rounding/conservation (property test) | allocated + unallocated = pool, always |
| A7 | Reconciliation | Allocated + unallocated overhead equals the ledger overhead total for the period |
| A8 | Tenant isolation and authorization | Allocation reads only the caller's tenant; selecting a basis requires `financials.adjust` |
| A9 | Basis changed after a period was reported | The reported result is unchanged and still shows its original formula version and basis; the new basis applies only from the release date forward; a past-period recalculation exists only through the explicit restatement workflow and is a linked, labelled result |
| A10 | Overhead never enters contribution margin | Changing overhead leaves contribution margin identical |
| F1 | Feed sign mapping | Cost +₹X and refund −₹Y map to the engine and back correctly in both directions; refund dated in a later period posts to that period and leaves the original period unchanged (Q21, Q24) |
| F2 | Trial isolation | `is_trial=true` results absent from every seller-visible surface and never used as a baseline (AC12) |
| F3 | Unallocated spend | Unattributed ad/storage spend shows as its own labelled line; total profit includes it (AC13) |
| F4 | Release note | The seller-facing release note for the contribution-profit change exists and is reviewed before the release date (AC14; document review, not automated) |
| F5 | Total-profit invariant | The same inputs under every allocation method (and none) give identical total profit (AC15; G2) |
| F6 | SKU-level rule | Validated import with explicit mapped ASIN ⇒ SKU-level; campaign spend without ASIN ⇒ business-level; manual ⇒ business-level (tagged ⇒ SKU-level, flagged manual); unmapped identifier ⇒ review queue, business-level (AC16) |
| F7 | Reconciliation | For each period and channel scope in a fixture covering missing, explicit zero, unallocated and allocated values: dashboard total = P&L expense lines + unallocated lines, and each of the four states appears separately (AC17; G2; engine TP10) |
Also: historical-result tests (no automatic restatement on formula release; version label on every result; explicit restatement links and labels); permission tests (partner without `financials.adjust` 403; no `expenses.write` key exists); draft tests (only vendor/category/date pre-filled; amount-like vendor rejected; description and amount never extracted; draft idempotency/expiry/cross-org); ST-01 tests (Appendix D).

## 13. Explicit open questions
| # | Question | Who |
|---|---|---|
| Q1 | Countersign EXP-01…08 | owner |
| Q2 | **DECIDED 2026-10-15.** The EXP-03 follow-up amendments (registry key and effect class, §6.33 sentence, classifier route) are approved **as spec text only** and applied to `ceo-agent-orchestration.md` §6.11/§6.33. CEO code and tests stay unchanged until implementation is approved; G6 remains the gate. The "Q2 expense-confirmation flow" came from a decisions document drafted in chat and has no repo source. | closed |
| Q3 | Should a form-confirmed draft ever also use plan/hash approval (C6–C8)? (Proposed: no) | owner/eng |
| Q4 | **DECIDED 2026-10-15.** The `auth.md` clarification is approved: `financials.adjust` covers expense-ledger writes (no key change). Applied to `auth.md` §5.2 and R1. | closed |
| Q5 | Default category list and category → cost-class mapping | owner |
| Q6 | Review-status values and transitions (proposed `needs_review`, `confirmed`, `rejected`) | owner |
| Q7 | Legacy tracker (`PUT/GET /cfo/expenses`, undated rows): extend, migrate or retire (X1) | owner/eng |
| Q8 | Wording and UX of the "formula version" label; the explicit restatement workflow (if ever wanted) | owner |
| Q9 | CSV template columns, date formats | owner (real seller files) |
| Q10 | Source of the "30-day rule"; retention period and legal basis | legal/CA |
| Q11 | GST/ITC/TCS wording and the standing disclaimer | CA |
| Q12 | Should expense writes write an `agent_run` (X3)? | eng/sec |
| Q13 | What counts as an "already-reported period"? Does editing a past period's ledger record and recomputing count as a restatement (proposed: no — recomputation only through the explicit restatement workflow)? | owner |
| Q14 | **DECIDED 2026-10-15.** Yes — EXP-06 covers account-level advertising and storage pools. Engine D7/§5.8/T14 text updated; the engine code is not changed. Consequence recorded in §6.13 rule 8. | closed |
| Q15 | **DECIDED 2026-10-15** (refined by Q28). Release date = first production deploy after G7 passes producing `is_trial=false` results. Stays the placeholder `<RELEASE_DATE: placeholder — product owner to set>` until then. | closed |
| Q16 | **DECIDED 2026-10-15.** Existing `expense.other` rows stay untouched under their original formula version; no migration; new entries use the ledger from the release date. | closed |
| Q17 | When is a narrower permission key wanted (partner-grant surface or new authorization decision)? | owner/sec |
| Q18 | **DECIDED 2026-10-15.** Only ST-01 (display "Not entered") is approved; **no engine change**. The formula rule (absent advertising = 0) stays as it is. | closed |
| Q19 | **REMAINS OPEN — legal/CA review (confirmed 2026-10-15).** Does the locked Ingestion principle "immutable raw files, versioned re-runnable parse runs" (readiness review §1) extend to expense CSVs? Interpretation of a locked decision: retained raw file vs parsed rows only. Not decided here. | legal/CA |
| Q20 | **DECIDED 2026-10-15.** Draft creation requires `financials.adjust` (checked again at confirmation). No new key. | closed |
| Q21 | **DECIDED 2026-10-15.** Signed amount: a cost is positive; a refund or credit note is a negative record referencing the original `expense_id`; consistent with the locked signed-paise rule (see §5.1). The feed maps the sign to the engine; a G2 test checks the mapping in both directions. | closed |
| Q22 | Vendor amount-pattern rejection rule: exact pattern and false-positive handling | eng |
| Q23 | Carried from the decision register so none is lost: D6 duplicate thresholds, D7 overlap UX, D8 advertising reconciliation, D13 multi-organization details, X2 write-validation bounds | owner/eng |
| Q24 | **DECIDED 2026-10-15 (refund part):** a refund or credit note belongs to the period of its own date, linked to the original expense; no restatement of the original period. **Still open (carried assumptions):** calendar-month period, imported rows `needs_review`, draft expiry 30 minutes; recurring-expense materialisation; scope of "recurring commitments" (larger than the readiness review enumerates) | owner/eng |
| Q25 | **DECIDED 2026-10-15 (confirmed).** EXP-01…EXP-08 supersede readiness-review items 2.8, 6.6 and 2A.13 **as applied to the expense input part only; OP1 (the general agent-initiated data-request flow) stays locked.** Marked in the review. | closed |
| Q27 | **DECIDED 2026-10-15.** Spend not attributable to a SKU stays business-level by default; spend from validated campaign/ASIN records stays SKU-level. Unallocated ad and storage spend is reported as its own labelled line beside contribution profit; total profit includes it. Pricing recommendations and loss-making-SKU alerts carry a caveat that unallocated spend is excluded; the what-if feature uses the fully loaded figure. A seller-facing release note is required. Engine text updated; not built | closed |
| Q28 | **DECIDED 2026-10-15.** G7 results use a distinct trial formula version with `is_trial=true`, are never shown in seller history and never serve as a restatement baseline. Release date = first production deploy after G7 passes producing `is_trial=false` results. AC12 added | closed |
| Q29 | **DECIDED 2026-10-15.** A campaign/ASIN spend record is **SKU-level only if** (a) it comes from a **validated import or integration**, (b) the source data carries an **explicit ASIN or SKU identifier**, and (c) that identifier **maps to a SKU in the seller's catalog**. Campaign-level spend **without an ASIN breakdown stays business-level**. **Manual entries are never SKU-level by default**; a seller may tag a SKU on the form and the entry **stays flagged manual**. **Unmapped identifiers go to a review queue and count as business-level until resolved.** Prerequisite for G2, not G1 | closed |
| Q30 | **DECIDED 2026-10-15.** The **engine spec owns the total-profit formula**; this spec states only the invariant that **changing the allocation method never changes total profit** (tested under G2, F5). `is_trial` is a **boolean on the result record**, **excluded from every seller-facing read at the read layer**; the **name of the trial formula version is an engine-spec decision**. Q29 and Q30 are **prerequisites for G2, not G1**. *Written into the engine spec 2026-10-16 (§5.8.1, §5.10.1, §5.17, §9.2); the written details are PROPOSED, awaiting product owner approval.* | closed |
| Q31 | **PROPOSED, awaiting product owner approval:** amortization of an expense over a stated number of months, computed by the engine (engine §5.18.1) | owner |
| Q32 | **PROPOSED, awaiting product owner approval:** per-order and per-unit cost templates, rate × the engine's own count (engine §5.18.2) | owner |
| Q33 | **PROPOSED, awaiting product owner approval:** multi-SKU assignment with a seller-chosen split basis; extends the single-SKU tag of Q29 (engine §5.18.3) | owner |
| Q34 | **PROPOSED, awaiting product owner approval:** ledger CSV export for the seller's accountant, all fields (engine §5.18.4); export permission and retention open | owner/legal |
| Q26 | TCS: `TCS_COLLECTED` is a real settlement field for Flipkart only; availability for other channels is unverified, so G5/§6.10 must not assume it | CA/eng |

---

## Appendix A — Reconciliation of the root draft and parallel documents

### A.1 Sources compared
`expense-tracker.md` (repo root, "DRAFT v2", untracked, 143 lines + a SUPERSEDED banner) · the earlier `docs/specs/expense-tracker.md` drafts v1–v3 (replaced by this file) · parallel-run `docs/planning/expense-tracker/01-code-spec-audit.md`, `01-decision-register.md`, `01-blockers.md` · planning-run `01-repository-audit.md` … `05-implementation-roadmap.md`. `06-architecture-decision-proposals.md` and `07-decision-sheet.md` **do not exist**.

### A.2 Section-by-section disposition of the root draft
| Root § | Content | Disposition in this file |
|---|---|---|
| 1 Purpose | Cost-input workspace inside CFO; not accounting/agent/nav | Preserved: P1 |
| 2 Non-goals | No ledger/GST filing, no filing-grade tax, no unsupported channels, no OCR/WhatsApp/bank import in V1.0, no custom categories, no nav item | Preserved: §4, P12 |
| 3 Cost classes | Marketplace-derived, direct, advertising, overhead, channel scope | Preserved: P5, §6.2, §6.3 |
| 4.1 Dashboard | Monthly totals, category breakdown, recurring, review queue, as-of | Preserved: P2, §6.11 |
| 4.2 Records | Fields; controlled categories (Proposed); payment status values; review status separate; recurring; source refs | Preserved: P2–P4, §5.1. `currency` **dropped** by EXP-08 |
| 4.3 CSV | Fixed template + preview; duplicates flagged, never discarded | Preserved: §6.5, §6.12 |
| 4.4 Quick-add | Confirmation card, idempotent confirm, org binding, server-side validation | **Changed by EXP-03:** draft pre-fills vendor/category/date; seller types description and amount; confirm on form. Idempotency, binding, expiry preserved: §7.3 |
| 4.5 Allocation | Direct costs by SKU; overhead business-level default; allocation only on selected basis; same-period revenue/units; unallocated visible; margin distinct; rules in engine | Preserved and strengthened: P6, §6.7, EXP-06 |
| 4.6 Contract | `incremental`/`replaces_input`/`already_in_settlement` | **Changed by EXP-01:** `replaces_input` dropped; `informational` added |
| 4.7 Overlap | Source refs first; similarity flags only; ads overlap flagged | Preserved: §6.4, §6.6, §5.2 |
| 4.8 History | Audit history; versioned outputs; traceable recalculation | Preserved; strengthened by EXP-02 and §6.13 (no automatic restatement) |
| 5 Channels | Amazon/Flipkart/Meesho/**IndiaMART** supported | **Changed by EXP-04:** IndiaMART removed; manual tag only |
| 6 Permissions | `financials.adjust` governs create/edit/delete/approve; review-only follows financial-read permissions | **Preserved:** `financials.adjust` (EXP-05). "Financial-read permissions": none exists, reads = `agent.cfo` (§8.4). "Delete/approve": no delete (void events); no approve key |
| 7 AI | Extract + explain; no compute/save; editable fields; LLM never supplies org/proposal/treatment; no numeric literals | Preserved and narrowed: §7 |
| 8 Tax | GST basis/amount/ITC flag; disclaimer text; economic vs cash margin; TCS rules | Preserved: P9, §6.10 (disclaimer text verbatim) |
| 9 Receipts/retention | Private storage, references separate, no new public path; retention unresolved | Preserved as §8.7, G4; correction recorded: no object storage and no "30-day rule" exist |
| 10 Phasing | V1.0 / V1.5 / later | Preserved: P12 |
| 11 Open questions | 10 items | Superseded by §13; mapping: 1→EXP-01, 2→EXP-05 (no new key), 3→EXP-02, 4→Q6, 5,6→Q10, 7→Q11, 8→Q5, 9→Q9, 10→EXP-04 |
**Check performed:** every root section above has a row; no unique requirement is unaccounted for.

### A.3 Conflicts between versions and how they were handled
| Conflict | Handling |
|---|---|
| Root §5 IndiaMART supported vs product-intelligence spec | Owner decision EXP-04 |
| Root §4.6 `replaces_input` vs engine COGS/ads semantics | EXP-01 (dropped) |
| Earlier drafts' `expenses.write` vs approved no-new-key decision (Q33) | **Owner revised EXP-05:** no new key; `expenses.write` removed everywhere |
| Root §4.4 chat quick-add vs C21/§6.33 | EXP-03 narrowed to vendor/category/date draft; reconciled (§7.4) |
| Root cites `legal-safeguards.md` / `phase1-decisions.md` | Latter created 2026-10-15; former missing (Appendix C) |
| Root "30-day rule" | No source; open gate, not a claim |

### A.4 Root-file disposition
The root file was **moved** (it was untracked, so `git mv` was not possible) to `docs/planning/expense-tracker/archive/expense-tracker.md` after A.2 confirmed nothing unique would be lost. Content (including its SUPERSEDED banner) is unchanged.

---

## Appendix B — Other documents: what changed in this run and what remains
**Applied 2026-10-15 (owner-instructed):** `deterministic-engine.md` D7, §5.8, §5.10 (EXP-06); `cfo-agent.md` "Removed by design" (EXP-01, EXP-07); `ceo-agent-orchestration.md` E30, T36 (EXP-03), and — after the owner decisions of 2026-10-15 — §6.11 and §6.33 (Q2), `auth.md` §5.2/R1 (Q4) and the status of readiness items 2.8, 2A.13, 6.6 (Q25). **Anything below not marked approved/applied is deferred.** No source code was changed.

**B.1 `auth.md`** — *Current:* §5.2 `financials.adjust` = "every field in the §7.2.1 registry, without exception"; R1; T8c/T8d. *Change (clarification only, **no new key**; approved and applied 2026-10-15):* append to the `financials.adjust` row "and records of the expense ledger"; add a note recording the known limitation (§8.3). *No `expenses.write` row, no R1 or Q33 amendment.* *Tests:* partner without `financials.adjust` ⇒ 403 on ledger writes.
*Decided 2026-10-15 (Q4): the clarification is approved and applied to `auth.md` §5.2 and R1 (no key change).*

**B.2 `cfo-agent.md`** — *Applied:* "Removed by design" reversed for expenses. *Remaining (deferred):* §8 rule 4 and E19 need no change (they already say `financials.adjust`); add a short "Expense ledger" pointer to this spec; add ledger routes to the direct-path table at implementation.

**B.3 `deterministic-engine.md`** — *Applied:* D7 amended (overhead unallocated by default; explicit basis; reason when unallocated); §5.8 amended (business overhead outside Contribution Profit; separate fully allocated figure; effective from the release date; formula version labelled); §5.10 amended (no default basis; outcome with reasons). *Remaining (deferred):* §7.2.1 clarification that the ledger sits beside the registry; §4.2/§9 result-linkage fields (§5.4); the "Absent `expense.advertising`" paragraph is unchanged (ST-01 is display only). **Engine code is unchanged and still implements the old behaviour; the amended text describes the target.**

**B.4 `ceo-agent-orchestration.md`** — *Applied:* E30, T36 (narrow). *Approved 2026-10-15 as spec text only (Q2) and applied:* (a) §6.11: a draft action key (working name `cfo.expense_draft`) and a non-saving draft/proposal effect class; `cfo.enter_expense` and `cfo.expense_budget_set` stay excluded; the future-write re-check stays at `financials.adjust` and now also applies at draft creation (Q20). (b) §6.33: one sentence scoping the `action.inputs` rule to the two playbooks and describing the expense draft (vendor, category, date only). (c) The classifier route: "record this expense" routes to the draft action instead of the decline. *Not done, awaits implementation approval (G6):* the classifier prompt (`ceo/classifier.py`), registry/effects code (`ceo/registry.py`, `ceo/effects.py`) and the T36/T35 test wording — **the CEO code and tests are unchanged.** **No change** to C21, AC23, Q33 or `FORBIDDEN_ACTION_KEYS`.

**B.5 `ceo-approval-workflow.md`** — none (not required for a form-confirmed draft). **B.6 `data-foundation.md`** — none in V1.0. **B.7 `product-intelligence-agent.md`** — none. **B.8 `calculator.md`** — none; the calculator's "operating expenses per month" stays separate and un-prefilled.
**B.9 API contracts / schema docs** — regenerate request/response contract JSON and add `docs/planning/api-contract-coverage.md` rows at implementation; schema docs for the new tables and the `metric_result` additions.
**B.10 `phase-1-readiness-review.md`** — add a pointer to `docs/decisions/phase1-decisions.md` (the pointer itself is not added; rows 2.8, 2A.13 and 6.6 are marked superseded as applied to the expense input path only — OP1, the general agent-initiated data-request flow, stays locked).

**B.11 Consumer specs for Q27 (not edited here; listed for follow-up).** Pricing/recommendation and loss-making-SKU alert surfaces must carry the "unallocated spend is excluded" caveat (AC13); the calculator/what-if uses the fully loaded figure; the seller-facing release note (AC14). Owning specs: `cfo-agent.md`, `product-intelligence-agent.md`, `anomaly-detection.md`, `calculator.md`. Each needs its own spec amendment before implementation. **Launch condition for the ledger feed (decided 2026-10-15):** the pricing, alert and what-if consumer specs must carry the unallocated-spend caveats **before release** (Appendix B.11). Each consumer spec (`cfo-agent.md`, `product-intelligence-agent.md`, `anomaly-detection.md`, `calculator.md`) carries the caveat text for its surface; this is a release blocker for the ledger feed, not a G1 item.
**B.12 Roadmap and test matrix** — updated in this run.

## Appendix C — Missing reference documents and tooling
Searched by file name: every tracked path on every local and remote branch, and the working tree including `.claude/`, `.agents/`, `.codex/`. **`legal-safeguards.md` — not found. `improvement-roadmap.md` — not found.** `docs/decisions/phase1-decisions.md` did not exist and was created 2026-10-15. `06-…` and `07-…` — not found. **`spec-reviewer.md` was recovered from git history** (`.claude/agents/spec-reviewer.md`, added in commit `850ced4`, modified in `8cb6cef` and `0c0a4e2`, deleted in `dabd71e`) and restored byte-for-byte from `dabd71e^`; see the review report. Nothing was invented or copied in place of the missing documents. **Impact:** every requirement the root draft sourced to `legal-safeguards.md` has no verifiable source and is carried only as a gate or open question.

## Appendix D — Separate task ST-01: show "Not entered" for absent advertising spend (approved as a separate task; not part of the Expense Tracker)
- **Verified path where absent becomes zero** [VERIFIED]: `packages/cfo/src/cfo/pnl/inputs.py::resolve_expense_pool_total` (lines ~110–124) returns `sum_paise([])` = ZERO when no `expense.advertising` rows are supplied; `backend/src/backend/services/cfo_actions.py::compute_period_pnl` (lines ~453, 470) passes it into `compute_contribution_profit`; the request lists are caller-supplied (`api/v1/cfo.py` P&L request models). `frontend/components/cfo/sections/PeriodPnlSection.tsx` contains no reference to advertising, so a seller cannot tell "no ads entered" from "₹0 of ads".
- **Smallest safe future change (display only, no formula change):** in `compute_period_pnl` compute `advertising_entered = len(request.advertising_adjustment_values) > 0` and return it as an additive field on the P&L response (the `_period_pnl_*_to_dict` mappers in `api/v1/cfo.py`); in `PeriodPnlSection.tsx` render "Advertising: Not entered" when false and the entered amount (including an explicit 0) when true. No change to `resolve_expense_pool_total`, `compute_contribution_profit`, stored `metric_result` values or the request contract (the response field is additive; regenerate the response contract JSON).
- **Regression tests:** (1) empty list ⇒ `advertisingEntered=false`, value unchanged; (2) an entry with `amount_paise = 0` ⇒ `advertisingEntered=true`, shown as ₹0.00; (3) UI shows "Not entered" for absent and never "₹0.00"; (4) contribution profit numerically identical before/after; (5) request-contract snapshot unchanged, response contract updated.
- **Not done here.** No code was changed.
