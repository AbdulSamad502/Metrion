# Metrion — Phase 1 Decision Record (Expense Tracker decisions)

**Created:** 2026-10-15 (this file did not exist before; no earlier decision is migrated or re-dated here). **Revised:** 2026-10-15 (final reconciliation: EXP-03 narrowed, EXP-05 reversed, EXP-02 clarified, EXP-08 and ST-01 added).
**Scope today:** the Expense Tracker decisions approved by the product owner on 2026-10-15. Earlier Phase 1 decisions of record are **not** in this file; they remain where they were made: `docs/planning/phase-1-readiness-review.md`, the "Confirmed decisions" tables of each spec in `docs/specs/`, and the owner decisions logged in `ceo-agent-orchestration.md` (C-series, Q-series).
**ID convention:** `EXP-nn`, in order. "Register D*" cross-references `docs/planning/expense-tracker/02-decision-register.md`.
**Status vocabulary:** `APPROVED (product)` = the owner decided the product behaviour; implementation details stay proposals until the canonical spec records them. `SUPERSEDED` = replaced by a later owner decision. `BLOCKED` = an authoritative approved decision conflicts and the item cannot proceed. **Nothing is currently BLOCKED.**
**Evidence tags:** [F] verified in the repository at base commit `91bebf4` · [U] not verifiable.
**Source of approval:** owner instructions in this session, 2026-10-15 (no signed record exists in the repository; the owner should countersign this file).

---

## EXP-01 — Financial adjustment contract (Register D1) — APPROVED (product)

**Decision.**
1. Validated expenses go into a **dedicated, append-only expense ledger**.
2. They reach Brain 1 through an **explicit integration contract** (a feed that reads validated ledger records and returns pool totals, named gaps and flags; Brain 1 stays the only place money is summed or allocated).
3. Three treatments: `incremental` (eligible to affect the applicable financial result) · `already_in_settlement` (retained for reconciliation; excluded from additional expense counting) · `informational` (retained for reference; excluded from profit).
4. **`replaces_input` is dropped**; not to be re-added without new owner approval **and** a demonstrated source-of-truth use case. [F] COGS is `cogs_per_unit` (per-unit, effective-dated, weighted average: `deterministic-engine.md` §5.6, §7.2.1); advertising has no second source (`AdvertisingCosts` is seller-entered, §5.8); the only replacement mechanism that exists is superseding the same target+field (`calc_engine.repositories.manual_adjustment_repo.insert_adjustment`).
5. **Source references, settlement overlap, duplicate detection, unresolved conflicts** (spec §5.2, §6.4, §6.5): overlap and duplicate status are explicit fields; a record with `candidate`/`unresolved`/`probable_duplicate` status **never silently counts and never silently drops**; it sits in the review queue with the amount it would add, is excluded from figures labelled "confirmed", and is resolved by a person's recorded action.

**Rationale.** [F] `manual_adjustment` cannot hold date, vendor, source reference, payment/review status, treatment or an idempotency key; cannot edit across target/field; cannot delete (no `WITHDRAWN` writer); and saved expenses do not reach the period P&L (`compute_period_pnl` takes caller-supplied `advertising_adjustment_values` / `other_adjustment_values`: `backend/src/backend/services/cfo_actions.py:355-356, 453-454`; `api/v1/cfo.py` P&L request models).
**Affected components (future work, not done).** Ledger migration with RLS/grants; Brain 1 feed; `compute_period_pnl` input path; expense API and UI; the legacy `PUT/GET /cfo/expenses` route and its undated `ACCOUNT/"default"` rows (open decision X1).
**Risks.** Two sources of manual input during transition; migration of undated legacy rows; double counting between ledger and legacy rows.
**Required review steps.** Architect review; reconciliation worked example per cost class; security review of the new RLS/grants; test matrix F/R/S series on scratch Postgres.
**Reversal.** Recorded as EXP-07. **Spec amendment applied 2026-10-15:** `cfo-agent.md` "Removed by design".

---

## EXP-02 — Versioned results and historical-result policy (Register D2) — APPROVED (product)

**Decision.** Financial results are **versioned**. A result records its inputs, formula version, configuration version, reporting period and as-of timestamp, and previous results are never silently overwritten.

**Historical-result policy (explicit clarification, 2026-10-15).**
1. **Do not automatically restate** previously reported periods when a new formula is released.
2. **Preserve** old results with their original formula version, configuration version and inputs.
3. **Use the new formula version from the approved release date forward.** The release date is the **first production deploy after G7 passes producing `is_trial=false` results** (decided 2026-10-15, spec Q15/Q28) and stays the placeholder **`<RELEASE_DATE: placeholder — product owner to set>`** until then.
4. **Label the formula version on every result.**
5. If recalculation of a past period is requested later, a **separate, explicit workflow** produces a **linked, clearly labelled restated result** without overwriting the original. That workflow is not designed here.

**Verified current schema (do not assume more).** [F] `metric_result` (`packages/calc-engine/migrations/versions/20260917_0001_engine_tables.py` lines 57–79; `…0006_metric_result_value_fraction.py`): `id, tenant_id, metric_code, grain, target_ref, period, value_paise, recognition_state, confidence, calculation_basis, formula_definition_id, formula_version, config_version, canonical_data_version, manual_adjustment_set jsonb, as_of_date, input_refs jsonb, exclusions jsonb, is_trial, is_available, unavailable_reason, computed_at`, plus value-fraction columns; writers `metric_result_repo.save/save_many` only insert.
- **Already present:** formula version, config version, canonical-data version, the manual adjustments used, `as_of_date`, `computed_at`, `period`, free-form `input_refs`/`exclusions`.
- **Not present (a future migration must add them; none is assumed):** a link from a later result to an earlier one; a reported/restated marker and reason; an expense-ledger input version (`manual_adjustment_set` lists adjustment ids only).
- **Immutability is by convention, not grant** per the earlier audit (`docs/planning/stages-3-4-5-report-2026-10-12.md`); the grants on `metric_result` were **not** re-verified here [U].
**Affected (future).** `metric_result` migration and repo; every P&L/allocation compute path (version label); CFO UI. **Risks.** Results before/after the release date are not directly comparable without the label; sellers' existing `expense.other` rows currently reduce Contribution Profit (spec Q16). **Review steps.** Result-linkage schema; version-label UX; reproducibility test; revoke `UPDATE/DELETE` on `metric_result` for the app role in the migration.
**Conflicts.** None found.

---

## EXP-03 — CFO chat flow (Register D3) — APPROVED (product); reconcilable, NOT BLOCKED

**Decision.**
- **No direct chat writes** to financial records.
- The CFO/CEO may prepare a **draft expense proposal that pre-fills ONLY these non-monetary fields: `vendor`, `category`, `date`.**
- The seller **types the description and the amount on the Expense Tracker form** and explicitly confirms there. `amount`, `gst_amount`, `paid_amount`, `description`, `treatment`, `review_status`, `sku`, `channel_scope` are never extracted or pre-filled.
- The LLM cannot authorize, commit or calculate the authoritative monetary result, and cannot produce a monetary form input.
- Server-minted draft id, tenant/user binding, expiry, single-use confirmation, retry protection; authorization and organization membership re-validated at confirmation.
- **Rationale (owner):** a free-text description can carry money, which would break "money is never typed into chat" and "form inputs are never produced by any model".

**Verification against the authoritative rules** (`docs/specs/ceo-agent-orchestration.md`, `backend/src/backend/ceo/`):
| Rule | Verified text | Reconciled? |
|---|---|---|
| **C21** (line 34) / AC23 (1032) | "No write-class action is in the V1 registry. Every action that creates a manual financial input, edits seller books, uploads files or writes a marketplace is excluded" | **Yes.** A draft is none of those; the form submission is the write, a direct surface. Precedent: CEO may *propose* a goal as a `DRAFT` that becomes `ACTIVE` only on explicit confirmation by a member holding `agent.ceo` and `financials.adjust` (§6.20 lifecycle, line 620). |
| **§6.33 (lines 843–845)** | typed chat may start a playbook "only by opening the form (money is never typed into chat)"; `action.inputs` "is never produced by the classifier or any model" | **Yes, narrowly.** The `action.inputs` sentence concerns the two playbooks; the expense draft is not an `action.inputs` object. The model produces only text slots (§6.3 rule 3, already allowed), limited here to vendor, category, date; money and description are excluded, honouring "money is never typed into chat and never inferred" (line 444). The owner's broader wording ("form inputs are never produced by any model") is **not** a spec sentence; it is honoured by the field restriction. |
| **§6.11 future-write rule** (line 407) | a future CEO-initiated write needs "its own spec: an explicit confirm step, a re-check of every permission including `financials.adjust`, and its own acceptance criteria" | **Yes, unchanged.** The write requires `financials.adjust` (EXP-05). The canonical spec §7–§8 is that spec. |
| **E30 / T36** (983, 1101) | record-an-expense via chat is declined | **Amended 2026-10-15** (narrow). |
| **`FORBIDDEN_ACTION_KEYS`** (`ceo/registry.py`) | includes `cfo.enter_expense`, `cfo.expense_budget_set` | **No change needed**; the draft uses a different, non-write key. Code not modified. |
| **Registry effect classes** (§6.11) | READ · COMPUTE_PERSIST · GENERATE_METERED · RECORD_CHOICE; "WRITE is not a permitted value in V1" | **Follow-up amendment** (approved 2026-10-15 as spec text, applied to `ceo-agent-orchestration.md` §6.11; code unchanged): a persisted draft fits none exactly; add a draft effect class and key (e.g. `cfo.expense_draft`) under its own acceptance criteria. |
| **Classifier** (`ceo/classifier.py`: OUT_OF_SCOPE lists "recording expenses") | prompt text | **Code follow-up**; until built, code and tests still decline (spec amended, code not: flagged). |
| **AC21** (no numeric literal in composer output) | line 280 | **Constraint:** the draft card's date and digits are rendered by the UI, not stated by the composer. |

**"Q2 expense-confirmation flow."** [U] Not found anywhere in the repository (`docs/specs/*.md`, `docs/planning/*.md`). **Owner clarified 2026-10-15: it came from a decisions document drafted in chat and has no repo source.** It is recorded that way and is not represented as an approved repository decision. The only related decided item is Q33 (2026-10-10, "Saving a form's inputs uses `financials.adjust` (no new key)"), which this design is consistent with.
**Approval workflow.** `ceo-approval-workflow.md` (designed, unimplemented) is **not required** for a form-confirmed draft.
**Affected (future).** Draft table and routes; extraction schema and LLM evals; registry/effects/classifier; form pre-fill.
**Required review steps.** Follow-up amendments approved 2026-10-15 as spec text only (Q2) and applied to `ceo-agent-orchestration.md` §6.11/§6.33; the CEO code and tests stay unchanged until implementation is approved; G6 remains the gate; evals; idempotency, expiry, cross-org and replay tests.

---

## EXP-04 — IndiaMART classification (Register D14) — APPROVED (product)

**Decision.** IndiaMART is **removed from the supported sales-channel list**; it is **supplier discovery**, not an integrated sales channel. Manual expense tagging to "IndiaMART" is allowed as a free label ("manually tagged, not synced"). Supported integrations remain only those with validated data flows (Amazon, Flipkart, Meesho).
**Evidence.** [F] `docs/specs/product-intelligence-agent.md` C5/C6 and `supplier_lead.source` (`INDIAMART_LOOKUP`, "schema-only, not implemented"; `packages/product-intelligence/migrations/versions/20260929_0001_pi_tables.py`); `docs/planning/phase-1-readiness-review.md` line 40; no IndiaMART adapter in `data_foundation/adapters/`.
**Conflicts.** None. **Review steps.** A selling-channel adapter would need a new owner decision and repository evidence.

---

## EXP-05 — Permission scope (Register D11) — APPROVED (product); supersedes the earlier `expenses.write` version

**Decision.** **No new permission key in V1.0.** **`financials.adjust` governs every ledger write** (create, edit, void, review change, CSV-import confirmation, draft confirmation), consistent with the approved no-new-key decision (`ceo-agent-orchestration.md` Q33, 2026-10-10: "Saving a form's inputs uses `financials.adjust` (no new key)"; line ~446; `cfo-agent.md` §8 rule 4 and E19).
- OWNER holds it implicitly; PARTNER is denied by default and only by explicit OWNER grant [F] (`auth.md` §5.2, D4; `backend/src/backend/auth/permissions.py::has_permission`).
- Reads follow existing behaviour: `agent.cfo`; no financial-read key exists [F] (`api/v1/cfo.py::get_expenses`).
- Server-side authorization with active-organization/tenant validation at the moment of every write.
- **`expenses.write` is NOT introduced.** The earlier recommendation and the earlier version of this decision are **SUPERSEDED**. Revisit only when a partner-permission grant surface exists or a new approved authorization decision is made. [F] No surface for granting keys to partners was found in `backend/src`.

**Known limitation (documented).** [F] `auth.md` §5.2: `financials.adjust` covers "every field in the `deterministic-engine.md` §7.2.1 field registry, without exception" (COGS, discount-bearer, settlement receipts, supplier quotes, budgets, expense pools). A partner granted it to enter expenses can therefore also change **COGS and the other margin-moving inputs**. This replaces the earlier "partner with `expenses.write` can change margin inputs" risk.
**Conflicts.** None with approved decisions. One wording clarification was recommended and then approved and applied on 2026-10-15 (Q4): `auth.md` §5.2 says "every field in the registry"; the ledger is not a registry field, so the row should add "and records of the expense ledger" (spec Appendix B.1).
**Required tests.** Partner without `financials.adjust` ⇒ 403 on every ledger write; no `expenses.write` key exists in `ALL_KEYS`.

---

## EXP-06 — Allocation default and engine change (Register D9) — APPROVED (product)

**Decision.** Business-level overhead is the default. **No silent allocation** by revenue share or units. Allocation only after the seller **explicitly selects** a supported basis and the data is valid; otherwise the amount stays unallocated and the reason is explained. The deterministic engine performs all allocation.
**Amendments applied 2026-10-15 (documentation only; engine code untouched):** `docs/specs/deterministic-engine.md` **D7** (row and decisions summary), **§5.8** (table rows; new amendment block: business overhead outside Contribution Profit, separate `FullyAllocatedProfit` and `UnallocatedOverhead`, new formula version from the release date) and **§5.10** (no default basis; reason codes; conservation); test T14 aligned.
**Verified nuance.** [F] The revenue-share default was a spec decision (D7) and a hard-coded `AllocationBasis.NET_REVENUE` in `calc_engine.formulas.expense_pools.allocate_account_level_expense_pool`, which has **no production caller** (tests only: `test_expense_pools.py`, `test_scenarios.py`); the period P&L sums whole pools (`cfo.pnl.inputs.resolve_expense_pool_total`) and §5.8 subtracts `AdvertisingCosts` and `OtherAllocatedCosts` in full. **This is a deliberate engine behaviour change, not only a spec edit**: basis required; an allocation outcome with reason codes (`BASIS_NOT_SELECTED`, `NO_REVENUE_FOR_PERIOD`, `ZERO_DENOMINATOR`, `UNITS_UNAVAILABLE`, `INVALID_BASIS`); business overhead moved out of Contribution Profit.
**Launch requirement.** The A1–A10 regression suite in `docs/specs/expense-tracker.md` §12 (no allocation by default; explicit revenue-share and unit allocation; missing/invalid data; zero denominators; rounding/conservation; reconciliation; tenant isolation and authorization; behaviour when the basis changes under the historical-result policy) must pass before any ledger-derived margin is shown (gate G2). None has been run.
**Decided 2026-10-15.** Account-level **advertising and storage** pools **are covered** (Q14). Release date: first production deploy after G7 passes producing `is_trial=false` results (Q15/Q28), placeholder until then. Existing `expense.other` rows stay untouched under their original formula version, no migration (Q16).
**Conflicts.** D7 was an approved decision of record; it is amended here at the owner's instruction.

---

## EXP-07 — Reversal of "removed by design" (part of Register D1) — APPROVED (product)

**Decision.** The `cfo-agent.md` "Removed by design" decision is reversed **for expenses only**; `cash_event` (`settlement.receipt`) and `supplier_quote` (`supplier.quote`) stay `manual_adjustment` field types.
**Evidence.** [F] `docs/specs/cfo-agent.md` line 113 (original text: earlier drafts' `expense_entry`, `cash_event`, `supplier_quote` tables "duplicated `manual_adjustment` and fragmented the guarantee that manual input never overwrites source data").
**Rationale.** See EXP-01. The protected guarantee is kept by append-only grants, FORCE RLS and the feed contract.
**Affected components.** Expense ledger, feed, `compute_period_pnl` inputs, `deterministic-engine.md` §5.8/§5.10, legacy `/cfo/expenses`.
**Risks / migration.** As EXP-01; legacy rows compatibility (X1).
**Amendment applied 2026-10-15:** `cfo-agent.md` "Removed by design" paragraph and the expense row of its table.

---

## EXP-08 — Currency — APPROVED (product)

**Decision.** **INR in integer paise only.** No general `currency` field unless the engine is expanded by a separately approved decision. [F] All engine money is signed `BIGINT` paise (CLAUDE.md; `calc_engine.types.Paise`); no currency column exists anywhere in the money shapes. The earlier drafts' `currency` field is dropped.

---

## ST-01 — Show "Not entered" for absent advertising spend — APPROVED as a SEPARATE task

Not an Expense Tracker feature and not to be bundled with the ledger. Display only: the engine's documented rule that absent `expense.advertising` resolves to zero (`deterministic-engine.md` §5.8 "Absent `expense.advertising` — CONFIRMED") is **unchanged**. Verified locations, smallest future change and regression tests: `docs/specs/expense-tracker.md` Appendix D. No code was changed.

---

## Owner decisions on open questions — 2026-10-15

| Spec Q | Decision | Effect |
|---|---|---|
| Q2 | EXP-03 follow-up amendments (registry key and effect class, §6.33 sentence, classifier route) approved **as spec text only**. The "Q2 expense-confirmation flow" came from a decisions document drafted in chat; no repo source. | Applied to `ceo-agent-orchestration.md` §6.11/§6.33. CEO code and tests unchanged until implementation is approved; G6 remains the gate |
| Q4 | `financials.adjust` covers ledger writes (clarification) | Applied to `auth.md` §5.2 and R1; no key change |
| Q14 | Yes: EXP-06 covers account-level advertising and storage pools | Engine D7, §5.8 rows and T14 text updated; engine code unchanged |
| Q15 | Release date = first production deploy after G7 passes producing `is_trial=false` results (refined by Q28) | Placeholder `<RELEASE_DATE: placeholder — product owner to set>` until then |
| Q16 | Existing `expense.other` rows untouched under their original formula version; no migration; new entries use the ledger from the release date | Spec §6.13 rule 7 |
| Q18 | Only ST-01 (display) approved; no engine change | Formula rule unchanged |
| Q19 | Remains with legal/CA review | Open |
| Q20 | Draft creation requires `financials.adjust` | Spec §7; no new key |
| Q21 | Signed ledger amount: cost positive; refund/credit note negative, referencing the original. Consistent with the locked signed-paise rule (a ledger-local convention; the engine spec does not state a cost sign) | Spec §5.1; G2 test of the feed sign mapping in both directions |
| Q25 | EXP-01…EXP-08 supersede readiness-review 2.8, 6.6 and 2A.13 for the **expense input part only**; OP1 stays locked (confirmed) | Marked in `phase-1-readiness-review.md` |
| Q24 | A refund or credit note belongs to the period of its own date, linked to the original expense; the original period is not restated | Spec §5.1 |
| Q27 | Spend not attributable to a SKU stays business-level by default; validated campaign/ASIN spend stays SKU-level. Unallocated ad and storage spend is its own labelled line beside contribution profit; total profit includes it. Pricing recommendations and loss-making-SKU alerts carry an "unallocated spend excluded" caveat; what-if uses the fully loaded figure; seller-facing release note | Spec §6.13 rule 9, AC13, AC14; engine §5.8 amendment; consumer specs not edited (B.11); validation rule decided (Q29) |
| Q28 | G7 results use a distinct trial formula version, `is_trial=true`; never in seller history; never a restatement baseline | Spec §6.13 rule 10, AC12 |
| Q29 | A campaign/ASIN spend record is **SKU-level only if** (a) it comes from a **validated import or integration**, (b) the source data carries an **explicit ASIN or SKU identifier**, and (c) that identifier **maps to a SKU in the seller's catalog**. Campaign-level spend **without an ASIN breakdown stays business-level**. **Manual entries are never SKU-level by default**; a seller may tag a SKU on the form and the entry **stays flagged manual**. **Unmapped identifiers go to a review queue and count as business-level until resolved.** | Spec §6.13 rule 9, AC16, F6; prerequisite for G2, not G1 |
| Q30 | The **engine spec owns the total-profit formula**; this spec states only the invariant that **changing the allocation method never changes total profit** (tested under G2, F5). `is_trial` is a **boolean on the result record**, **excluded from every seller-facing read at the read layer**; the **name of the trial formula version is an engine-spec decision**. Q29 and Q30 are **prerequisites for G2, not G1**. | Spec §6.13 rule 11, AC15, F5; engine spec to define the formula and the trial version name |
| Launch condition | Launch condition for the ledger feed (decided 2026-10-15): the pricing, alert and what-if consumer specs must carry the unallocated-spend caveats before release (Appendix B.11). | Spec G2, §6.13 rule 12, Appendix B.11 |

All of the above is documentation only. Nothing was implemented, committed, pushed or deployed.

---

## Engine-spec items written 2026-10-16 (G2 prerequisites) — were PROPOSED; approved in Round 6 (items 1–10), Round 7 (Q31, Q32, Q34) and Round 8 (see below)

Q29 and Q30 are now **written into `docs/specs/deterministic-engine.md`** (§5.8.1, §5.10.1, §5.17, §9.2, §9.3, §9.4, test rows TP1–TP9). The owner decisions themselves (Q29 SKU-level rule; engine owns the total-profit formula; `is_trial` boolean excluded from seller reads) are unchanged. The following written details are **PROPOSED and not approved**:

| # | Item | Recommendation | Section |
|---|---|---|---|
| 1 | Total-profit formula: Option A (includes all overhead) or B (unallocated advertising/storage only) | A | §5.8.1 |
| 2 | Storage term: add `StorageCosts` (Option 1) or route into `OtherAttributedCosts` (Option 2); whether packaging/logistics pools enter the period P&L | Option 1; packaging/logistics unchanged until decided | §5.17 |
| 3 | Allocation basis granularity: per pool (recommended) or one per account | per pool | §5.10.1 |
| 4 | `UNITS` weight: net of returns/RTO (recommended) or gross; `ORDERS` weight: distinct orders per SKU | net; per SKU | §5.10.1 |
| 5 | New reason codes `ORDERS_UNAVAILABLE`, `BASIS_DATA_UNAVAILABLE`; details `PERIOD_MISMATCH`, `SCOPE_MISMATCH` | adopt | §5.10.1 |
| 6 | Code mapping of signed amounts (ledger sign ↔ engine cost term); cost-class → term mapping; review-state vocabulary dependency (ledger Q6) | as written | §5.17 |
| 7 | Read-layer mechanism for `is_trial`: repository parameter (recommended now) or database view | parameter now, view with a migration | §9.2 |
| 8 | Trial formula version name: `<CODE>.v<N>-trial` (recommended) or `v<N>-rc<k>` | `-trial` suffix | §9.2 |
| 9 | Ledger watermark in `input_refs` (recommended) or a new column | `input_refs` | §9.2 |
| 10 | Metric codes for the expense dashboard aggregates and the profit lines | as listed | §9.3 |
| 11 | Amortization of an expense over N months (Q31) | as written, awaiting approval | §5.18.1 |
| 12 | Per-order / per-unit cost templates (Q32) | as written, awaiting approval | §5.18.2 |
| 13 | Multi-SKU assignment with a seller-chosen split; extends Q29 (Q33) | as written, awaiting approval | §5.18.3 |
| 14 | Ledger CSV export for the accountant (Q34) | as written, awaiting approval | §5.18.4 |

**Consumer specs that still need edits (not edited):** `cfo-agent.md`, `product-intelligence-agent.md` / pricing surfaces, `anomaly-detection.md`, `calculator.md`, `data-foundation.md`, `ceo-agent-orchestration.md` (trial citations), `auth.md` (only if the read-layer view is chosen) — see engine §9.4.

**Spec-versus-code discrepancies found:** see engine §5.8.1, §5.10.1, §5.17 and §9.2 (no total-profit term exists; `allocate_account_level_expense_pool` hard-codes `NET_REVENUE` with no caller and no `UNITS`/`ORDERS` weight builders; period P&L composition and pool summation live outside `packages/calc-engine`; `is_trial` exists but no read path filters it; spec §9 omits columns the schema has; no storage/packaging/logistics term in §5.8; no advertising adapter or ASIN→SKU mapping).
---

## G1 approvals — 2026-10-16

Documentation only; nothing implemented. Full tables with the section references: `docs/planning/expense-tracker/10-g1-approval-table.md` §C.

### Engine items 1–10 (the "PROPOSED" list above): approved as recommended

| # | Item | Decision | Section |
|---|---|---|---|
| 1 | Total profit | **Option A approved:** total profit includes all business overhead (allocated and unallocated) | engine §5.8.1 |
| 2 | Storage term | **Approved:** add a `StorageCosts` term. **No separate packaging or logistics pools** — those costs enter through the ledger | engine §5.17 |
| 3 | Allocation basis granularity | **Approved:** per pool | engine §5.10.1 |
| 4 | UNITS / ORDERS definitions | **Approved:** `UNITS` is net of returns; `ORDERS` is distinct orders per SKU | engine §5.10.1 |
| 5 | Reason codes and details | **Approved:** `ORDERS_UNAVAILABLE`, `BASIS_DATA_UNAVAILABLE`; details `PERIOD_MISMATCH`, `SCOPE_MISMATCH` | engine §5.10.1 |
| 6 | Signed-amount and cost-class mappings | **Approved as written** in engine §5.17 (ledger cost positive, refund/credit negative; cost-class to engine term mapping). The review-state vocabulary is decided below (Q6) | engine §5.17 |
| 7 | `is_trial` read-layer exclusion | **Approved:** a repository parameter (`include_trial`) that **defaults to excluded**, **plus a test that fails if any read path lacks it** | engine §9.2 |
| 8 | Trial version name | **Approved:** `<CODE>.v<N>-trial` | engine §9.2 |
| 9 | Ledger watermark | **Approved:** in `input_refs` | engine §9.2 |
| 10 | Metric codes | **Approved as proposed** | engine §9.3 |

### Further decisions

| Ref | Item | Decision |
|---|---|---|
| Q6 | Review states | **Decided:** `draft`, `pending_review`, `confirmed`, `voided`. A correction is a **new linked entry**, never an edit of the old one. This supersedes the earlier proposal in spec §13 Q6 (`needs_review`, `confirmed`, `rejected`) and the spec wording "imported rows `needs_review`" (read as `pending_review`); the frozen spec is not edited |
| Q31 | Refund of an amortized expense | **Decided:** it reduces the remaining schedule **from the refund date forward**; past months are **not** restated. *Superseded: approved outright in Round 7 (2026-10-16), including `AMORTIZATION_INVALID`* |
| Q32 | Per-order / per-unit templates | **Decided:** SKU- or channel-scoped templates attach per order or unit as **direct costs**; business-wide templates become a **business-level pool**; **no automatic spreading**. *Superseded: approved outright in Round 7 (2026-10-16), including `NO_ORDERS_IN_PERIOD` = unavailable, not zero* |
| Q33 | Multi-SKU assignment | **Approved:** bases `EQUAL` and `EXPLICIT_SHARES`, **seller-chosen only**; extends Q29; manual entries stay **flagged manual** |
| Q34 | Ledger CSV export | **Decided:** generated **on demand, not stored**; permission **follows the existing financial read permission**; retention goes to **legal/CA**. *Superseded: approved outright in Round 7 (2026-10-16); fields = all ledger fields including treatment, review state, void status and source reference* |
| Q22 | Vendor text validation (register X8) | **Decided:** reject vendor text containing a **currency symbol** or an **amount-like number** (such as `1,200.50`); **allow short numerals** (e.g. "3M"); **show an edit prompt** |
| X9 | Entitlement check | **Decided:** reuse the existing CFO entitlement gate |
| X10 | Recurring entries | **Decided:** materialized recurring entries start as `pending_review` |
| X1 | Legacy tracker | **Decided:** keep the legacy `PUT/GET /cfo/expenses` path until cut-over |
| X3 | `agent_run` for expense writes | **Decided:** one `agent_run` row per expense write |
| X2 | Write-validation bounds | **Decided process:** engineering proposes bounds from the legacy validation; **no numbers are invented**. Open until that proposal is made |

### Left open

Q19 and Q34 retention (legal/CA); G4 (retention and storage); G5 (tax wording); Q15 release date (placeholder until the first production deploy after G7 passes producing `is_trial=false` results). Unchanged: Q1 countersign (below), Q29/Q30 as already decided.

### Erratum — 2026-10-16

The frozen spec (`docs/specs/expense-tracker.md`, header "Prerequisites and related specs") says `calculator.md` is "on branch `feat/pnl-calculator-integration`, not merged here". **That is no longer true:** `calculator.md` and the calculator work are merged on the combined branch `feat/pnl-calculator-and-expense-tracker` (merge commit `e26984e`). The frozen spec is not edited; this entry corrects it.

### Q1 — countersign (EXP-01…EXP-08)

Countersigned by product owner on [date]; spec frozen at e91136a; approval table at 9858fc7

Name: ____________________    Date: ____________________

---

## Round 7 approvals — 2026-10-16

Documentation only; nothing implemented. **Q31** amortization (including `AMORTIZATION_INVALID` to the review queue), **Q32** per-order/per-unit templates (including `NO_ORDERS_IN_PERIOD`, meaning the amount is unavailable, not zero) and **Q34** ledger CSV export (fields = all ledger fields including treatment, review status, void status and source reference; retention stays with legal/CA) are approved outright. Approval does not change build priority: they stay in kickoff Step 5. The engine spec marks Round 6 items `APPROVED (Round 6, 7c46d9d)` and these three `APPROVED (Round 7, 2026-10-16)`.

## Errata to the frozen spec (`docs/specs/expense-tracker.md` at `e91136a`)

**This decision record takes precedence over the frozen spec wherever they differ.** The frozen spec is not edited. Differences found as of 2026-10-16:

| # | Topic | Where the frozen spec says otherwise | Later decision (takes precedence) |
|---|---|---|---|
| E1 | Review states (Q6/D5) | §6.12 CSV ("imported rows `needs_review`"); §3 assumption [A]; §13 Q6 ("proposed `needs_review`, `confirmed`, `rejected`") and Q24 ("imported rows `needs_review`") | States are `draft`, `pending_review`, `confirmed`, `voided`; a correction is a new linked entry. `needs_review` reads as `pending_review`; `rejected` no longer exists (use `voided` or a linked correction) |
| E2 | calculator.md merged | Header "Prerequisites and related specs": `calculator.md` "on branch `feat/pnl-calculator-integration`, not merged here" | Merged on `feat/pnl-calculator-and-expense-tracker` (merge commit `e26984e`) |
| E3 | Engine items now approved | §10 G2 row ("PROPOSED items awaiting product owner approval"), §13 Q30 row, and the Appendix B.3 "remaining engine work" | Engine items 1–10 approved in Round 6 (`7c46d9d`); the engine spec carries the approvals. Still PROPOSED: TP1–TP10 tests, the §5.17 function name, §5.18.3 mechanics and tests |
| E4 | Q31–Q34 no longer PROPOSED | §13 Q31, Q32, Q33, Q34 ("PROPOSED, awaiting product owner approval") | Q33 bases approved in Round 6; Q31, Q32, Q34 approved outright in Round 7 (2026-10-16). Build priority unchanged (kickoff Step 5). Q34 export retention stays with legal/CA |
| E5 | Vendor text validation (Q22/X8) | §7.1 `vendor` row ("proposed validation"), §7/§12 "amount-like vendor rejected", §13 Q22 ("exact pattern and false-positive handling") | Reject vendor text containing a currency symbol or an amount-like number such as `1,200.50`; short numerals allowed; show an edit prompt |
| E6 | Entitlement check (X9) | §8 ("`agent.cfo` and the CFO entitlement, as in `put_expense` [PROPOSED]") | Reuse the existing CFO entitlement gate (decided) |
| E7 | `agent_run` for expense writes (X3/Q12) | §8 item 8 "[OPEN: X3]" and §13 Q12 | One `agent_run` row per expense write (decided) |
| E8 | Legacy tracker (X1/Q7) | §10 G1 row ("X1 decided") and §13 Q7 ("extend, migrate or retire") | Keep the legacy `PUT/GET /cfo/expenses` path until cut-over (decided); cut-over mechanics remain open |
| E9 | Write-validation bounds (X2) | §2 "Still open" list and §13 Q23 (X2) | Engineering proposes bounds from the legacy validation; no numbers are invented. Open until that proposal exists |
| E10 | Recurring entries (X10) | §13 Q24 ("recurring-expense materialisation") | Materialized recurring entries start as `pending_review` (decided) |
| E11 | Storage, packaging, logistics pools | §6.2 cost classes ("direct (packaging, inward freight ...)") and the engine registry fields `expense.packaging|storage|logistics` | A `StorageCosts` term is added; there are no separate packaging or logistics pools — those costs enter through the ledger (Round 6) |
| E12 | ST-01 wording and shape | Appendix D, §1 ST-01 row, §6.6 and AC5 ("Not entered"; one additive field `advertising_entered`) | Implemented as `44a39c0` and **merged into the combined branch** (merge commit `4e5274b`, 2026-10-16; the working branch `fix/expense-adv-not-entered` is removed) as "Advertising: Not entered in this calculation" with two additive fields, `advertisingEntered` and `advertisingCostsPaise`. Reason: rows saved through `PUT /cfo/expenses` are not read by the period P&L |
| E13 | Planning documents | `09-implementation-kickoff.md` (ST-01 label "Not entered"; Step 3 prerequisites list Q6/X1/X2/X3/X9 as open) and `10-g1-approval-table.md` §A "Needs your approval" column | Superseded by this record where they differ; §C/§D of `10-g1-approval-table.md` hold the current statuses |

The earlier erratum dated 2026-10-16 (calculator.md merged) is E2 above.

---

## Round 8 approvals — 2026-10-16

Documentation only. The engine **TP1–TP10 test list** and **§5.18.3 multi-SKU mechanics and tests MS1–MS7** (with the Q33 bases) are approved and labelled `APPROVED (Round 8, 2026-10-16)` in the engine spec. The §5.17 function name is a non-binding suggestion; the implementer chooses. Nothing in the engine spec remains PROPOSED.

---

## Round 9 decisions — 2026-10-16

Recorded before the Step 3–5 build. The build is authorised up to the gates; nothing here sets the release date (Q15) or passes a gate.

| # | Item | Decision | Reference |
|---|---|---|---|
| R9-1 | Dashboard route | Route `/dashboard/cfo/expenses` (proposal N1), linked from the CFO page; the sidebar is unchanged; no new top-level product or agent | `12-dashboard-inspection.md` §2 |
| R9-2 | Session and auth | No change to the session response or auth. The server enforces `financials.adjust`; the UI shows write controls and handles 403 gracefully | `12` §6 |
| R9-3 | Design system | "Cyber-Luxe" does not exist in the repo; reuse the existing design system and components documented in `docs/design/` and the codebase; invent no new one | `12` §3 |
| R9-4 | Categories (Q5) | Option A of `13-step3-proposals.md` §1: default cost class per category, overridable on the record. "Direct product costs" is omitted (COGS stays `cogs_per_unit`); Storage is added. Legacy rows stay untouched and are shown read-only, no migration (Q16) | `13` §1 |
| R9-5 | X2 bounds | The implementer proposes conservative string, row and amount limits, derived from existing code where it exists, recorded in `15-build-notes.md` for owner review (not approved until reviewed) | `13` §2 |
| R9-6 | Ledger migration owner | `packages/calc-engine`, following the `manual_adjustment` and `reconciliation_*` precedent and the app-role grants pattern | `13` §3 |
| R9-7 | "True Margin" | Contribution margin is the headline, with total profit beside it | `13` §4 |
| R9-8 | `UNITS` with a missing returned quantity | Unavailable, not zero | `11-engine-step-notes.md` note 1 |
| R9-9 | Sign convention | The ledger stores signed amounts as approved; the feed maps them to the engine's positive cost magnitudes (implemented and tested). `data-foundation.md` §1.1 describes ingested deductions, not engine inputs | `11` note 12 |
| R9-10 | G6 (draft-from-chat) | Not passed. The draft-from-chat slice is not built and registry, effects and classifier code are not edited | spec §10 G6 |

### Errata added in Round 9 (the decision record takes precedence over the frozen spec)
| # | Topic | Where the frozen spec / documents say otherwise | Later decision |
|---|---|---|---|
| E14 | Categories (Q5) | Frozen spec §13 Q5 / P4 "contents open" | Closed by R9-4 (Option A; Storage added; no "Direct product costs") |
| E15 | `data-foundation.md` §1.1 sign wording | §1.1: "Signed from the seller's perspective. Revenue positive, deductions negative" | That sentence describes **ingested** line components, not engine inputs; the engine takes positive cost magnitudes and the ledger maps its signed amounts to them (R9-9). `data-foundation.md` is not edited |
| E16 | Navigation | Frozen spec describes the dashboard without a route; `09-implementation-kickoff.md` and `12-dashboard-inspection.md` list N1–N3 as PROPOSED | N1 approved (R9-1) |
| E17 | Permission awareness in the UI | `12-dashboard-inspection.md` §6 proposes exposing the permission set | Not adopted; no session change (R9-2) |
| E18 | Migration owner | `13-step3-proposals.md` §3 lists options A–D | Option A, calc-engine (R9-6) |
| E19 | "True Margin" | `13` §4 options A–C | Option A (R9-7) |
| E20 | `UNITS` and missing returns | `11-engine-step-notes.md` note 1 asks for confirmation | Confirmed (R9-8) |

---

## Items deliberately left open (not approved)
Default category list; review-status values and transitions; duplicate thresholds; settlement-overlap wording; CSV template; retention period and storage; multi-organization details beyond EXP-03; recurring materialisation; legacy-row compatibility (X1); GST/ITC/TCS wording (CA); the concrete formula release date (defined by event); raw-CSV retention (legal/CA, Q19). See `docs/planning/expense-tracker/02-decision-register.md` and spec §13.
