# Expense Tracker — 02 Decision Register

> **Status update, 2026-10-15 (final reconciliation).** Approved (product), recorded in `docs/decisions/phase1-decisions.md` and the canonical spec `docs/specs/expense-tracker.md`: **D1 → EXP-01 · D2 → EXP-02 (with the historical-result policy: no automatic restatement; new formula version from a release date that is a placeholder) · D3 → EXP-03 (draft pre-fills ONLY vendor, category, date; seller types description and amount on the form) · D14 → EXP-04 · D11 → EXP-05 (NO new permission key; `financials.adjust` retained; the earlier `expenses.write` recommendation is SUPERSEDED) · D9 → EXP-06 · the reversal of "removed by design" → EXP-07 · currency INR paise only → EXP-08.** Separate approved task: **ST-01** (show "Not entered" for absent advertising spend). Every other decision stays **OPEN**. **Nothing is BLOCKED.** Where an entry below still shows an earlier recommendation that differs from an approved decision, it is marked *superseded*.

**Status:** planning. **Every decision below is OPEN. Recommendations are not approvals.** Approval status for each is `NOT DECIDED` until the owner records it here and in `docs/specs/expense-tracker.md`.
**Evidence tags:** **[F]** verified in the repository (cited in `01-repository-audit.md` §1) · **[A]** assumption · **[U]** unknown.
**Priority:** the three decisions that gate everything else are **D1 (financial adjustment contract)**, **D2 (historical recalculation and reporting)** and **D3 (quick-add idempotency)**. Others are ordered by dependency.

Each entry: *current implementation → options → trade-offs → recommendation → evidence needed for approval*.

---

## D1 — Financial adjustment contract (how a validated expense enters the engine) — **PRIORITY 1**

**Current implementation [F].** Expenses are `manual_adjustment` rows with fields `expense.advertising|packaging|storage|logistics|other` and value `{amount_paise, gst_amount_paise?, marketplace?}`. Only `advertising` and `other` can reach the period P&L, and only when the caller re-sends them in the request body (`cfo_actions.compute_period_pnl`, `api/v1/cfo.py` P&L routes). COGS is a different input (`cogs_per_unit`, per unit, effective-dated). Settlement-derived costs are canonical `line_component` rows. Absent ad/other spend resolves to zero by explicit engine exception. No treatment flag, no overlap guard.

**Classes the contract must distinguish.**
| Class | Canonical source of truth today | Can a manual expense enter? |
|---|---|---|
| Settlement-derived (commission, shipping, fixed, collection, non-order charges) | `line_component` from marketplace adapters | **No.** Never re-entered; at most an informational note. |
| COGS | `cogs_per_unit` chain, SKU grain | Via its own input, not as an expense amount. |
| Advertising | `expense.advertising` (seller-entered) — **no validated ad source exists** | Yes, labelled manual. |
| Incremental overhead (rent, salaries, software, utilities, packaging not in COGS) | none (`expense.other`/`packaging`/`storage`) | Yes. |
| Hypothetical scenario | `pnl-scenario` (never persisted) | **No.** Never persisted as an expense. |

**Options.**
- **A. Engine-owned feed over the existing store.** Add an engine function that reads ACTIVE `expense.*` rows for the period and returns the P&L pool totals, with a per-row `treatment` carried in the value; engine registry amended (`deterministic-engine.md` §7.2.1).
- **B. First-class `expense` table(s)** with date, vendor, statuses, source reference, and a deterministic engine reader; `manual_adjustment` stays for per-unit inputs.
- **C. Keep caller-supplied lists** and only improve the UI (status quo).

**Trade-offs.** A keeps one audit store and the "no fragmented manual input" rule (`cfo-agent.md` ~113) but cannot hold date/vendor/status natively and cannot edit or delete (see D2, D4, D5). B fits the product fields and gives edit/void semantics but reverses a recorded decision and needs new RLS, grants, audit and a migration of existing `ACCOUNT/"default"` rows. C leaves B2 (entered expenses do not move margin) unsolved and is not acceptable for TRUST.

**Recommendation — ADOPTED by the owner as EXP-01 (table-level details remain PROPOSED).** B with an **engine-owned reader**: new tenant-scoped, append-only expense tables (record + event log) whose figures reach the P&L only through a Brain 1 function that sums by `(period, channel, class, treatment)` and emits a `metric_result` with the stamp tuple. Keep `manual_adjustment` for COGS and supplier inputs. Treatment values: `incremental` (counts), `already_in_settlement` (stored, **excluded** from margin, visible in reconciliation), `informational` (excluded). **Drop `replaces_input`**: COGS and ad spend have no second source to replace (audit §1.4); an explicit supersede on the same record is the only replacement that exists.
Absent-equals-zero for ad/other stays an explicit engine exception **but must be surfaced** ("no advertising spend entered" shown as not entered, never as ₹0) — D1-c.

**Evidence needed.** Owner ruling on reversing the "removed by design" decision; engine-spec amendment text; a worked reconciliation example per class; list of categories that must reach the P&L in V1.0; sign-off that absent ad spend is displayed as not-entered.

**Status: APPROVED (product), 2026-10-15 — EXP-01. Reversal of `cfo-agent.md` "Removed by design" approved as EXP-07. Treatments `incremental` / `already_in_settlement` / `informational`; `replaces_input` dropped. Open: X1 (legacy tracker), owner countersign of the `cfo-agent.md` amendment.**

---

## D2 — Historical recalculation and reporting — **PRIORITY 2**

**Current implementation [F].** Results are stamped (`formula_version`, `config_version`, `canonical_data_version`, `manual_adjustment_set`, `as_of_date`, `computed_at`) and "never recomputed silently" (engine F3). No link between a restated result and the one it replaces; no "restated" label; `manual_adjustment` has no effective date so "what applied to March as of 1 April" cannot be derived; edits and deletes do not exist as primitives.

**Questions.** What does an edit, deletion, late-arriving record or changed allocation basis do to a reported period?

**Options.**
- **A. Immutable reports, forward-only corrections.** A past figure never changes; corrections appear as a dated adjustment in the current period.
- **B. Versioned restatement.** Recompute the affected period, store a new `metric_result` linked to the previous (`supersedes_result_id`), show both with a "restated on <date>, reason" label.
- **C. Live recompute (no history).** Fast and simple, violates reproducibility.

**Earlier recommendation — PARTLY SUPERSEDED by EXP-02 and its policy: "versioned restatement" is adopted, but restatement is never automatic; it happens only through a separate explicit workflow.** **B for edits dated inside a period that has been reported**, with the previous result retained and linked; ~~A semantics for allocation-basis changes~~ *(superseded: under EXP-02 and EXP-06 a basis change is a restatement — a new linked result, the original preserved)*. Record on every expense event: `effective_date` (the period it belongs to), `recorded_at`, `event_type`, `actor`. A report always states its `as_of` timestamp and the expense-event watermark it used, so any figure is reproducible by replaying events up to the watermark.

**Evidence needed.** A decision on whether sellers see restatements automatically or on request; schema for result linkage; reproducibility test (same inputs + watermark ⇒ identical figure); legal/CA view on restating filed-period figures (informational only, no filing claim).

**Status: APPROVED (product), 2026-10-15 — EXP-02, with the historical-result policy: no automatic restatement of reported periods; old results keep their formula/config version and inputs; the new formula applies from the approved release date `<RELEASE_DATE — placeholder, owner to set>`; formula version labelled on every result; any later recalculation is a separate explicit workflow producing a linked, labelled result. The required schema additions are not in `metric_result` today (see `phase1-decisions.md`). Open: release date (spec Q15).**

---

## D3 — CFO quick-add: proposal IDs, approval, retries, organization binding, expiry — **PRIORITY 3**

**Current implementation [F].** Blocked by an approved decision: CEO **C21** forbids write-class actions in V1 (`ceo/registry.py::FORBIDDEN_ACTION_KEYS` includes `cfo.enter_expense`); the classifier sends "recording expenses" to `OUT_OF_SCOPE`; E30 says to point sellers at the direct form. No CFO chat exists. The approval workflow (`ceo-approval-workflow.md`) is a designed, unimplemented spec (30-minute expiry C6, requester-only approver C7, hash-bound approval C8). `enter_expense` mints a fresh `uuid4` per call, so retries duplicate.

**Options.**
- **A. Reverse C21 for this action** and build it on the approval workflow.
- **B. V1.0 ships forms and CSV only**; quick-add waits for the approval workflow (S2/S3).
- **C. A narrow, non-chat "proposal" endpoint pair** (draft → confirm) that the CEO can *draft* but never confirm; confirmation is a seller click on the form surface.

**Superseded recommendation (historical):** "B for V1.0, C as the first increment" — replaced by the approved decision below.

**Approved decision (EXP-03, narrowed 2026-10-15).** No direct chat writes. The CEO (sole conversational interface) may prepare a draft that pre-fills **only `vendor`, `category` and `date`**; the seller **types the description and the amount** on the form and confirms there; the LLM cannot authorize, commit or calculate the authoritative amount or produce a monetary form input. Server-minted draft id, tenant/user binding, expiry, single-use confirm, retry protection; authorization and organization membership re-validated at confirmation (`financials.adjust`). **Reconciliation (verified):** consistent with C21/AC23 (the form submission is the write), with §6.33 (money never typed into chat; the `action.inputs` rule is scoped to the two playbooks), and with the §6.11 re-authorization rule (still `financials.adjust`). **Amended 2026-10-15:** E30 and T36 only. **Follow-up amendments (not applied):** a draft effect class and registry key in §6.11, a scoping sentence in §6.33, the classifier route; `FORBIDDEN_ACTION_KEYS` needs no change. The "Q2 expense-confirmation flow" was not found in the repository and is not represented as approved.

**Evidence needed.** Owner decision on C21; approval-workflow S2/S3 status; LLM-eval design (no invented numbers, required disclaimer, non-result narrated as non-result — CLAUDE.md); idempotency and cross-org tests (see `04-…` T-Q*).

**Status: APPROVED (product), 2026-10-15 — EXP-03; reconcilable, not BLOCKED. Follow-up amendments approved 2026-10-15 as spec text only (spec Q2); code and tests unchanged until implementation is approved (gate G6).**

---

## D4 — Category model

**Current [F].** Five engine-registry categories only; the UI hard-codes them; a new category is an engine-registry amendment. Rent/salaries/software/utilities have no category except `other`.
**Options.** (A) Controlled list, extend registry; (B) controlled category + free-text sub-label; (C) fully custom categories.
**Recommendation.** B: a controlled top-level list that maps to a **cost class** (which decides how the engine treats it) plus a free-text label for reporting. Custom categories later. Default list contents need an owner decision.
**Evidence needed.** Default list; mapping category → class → engine pool; CA view on tax-relevant groupings.
**Status: NOT DECIDED.**

## D5 — Payment status vs review status

**Current [F].** Neither exists.
**Options.** (A) one combined status; (B) two orthogonal fields; (C) payment status only.
**Recommendation.** B. Payment: `unpaid | partially_paid | paid | unknown` (with a paid amount only when partially paid; `unknown` never counts as paid or unpaid). Review: `needs_review | confirmed | rejected` (values to be approved). **Cash timing never changes economic margin**; payment status affects only the cash/commitments views.
**Evidence needed.** Review values and transitions; whether `partially_paid` needs a paid-amount field in V1.0; drop the review queue if values are not approved.
**Status: NOT DECIDED.**

## D6 — Duplicate detection

**Current [F].** File-level SHA-256 and marketplace natural-key dedupe only (`report_file_repo.find_by_content_hash`; `ingestion_run.row_count_duplicate`). Nothing for expenses; no idempotency key.
**Options.** (A) exact source-id match; (B) exact match on normalised (date, vendor, amount, currency, reference); (C) probable-duplicate scoring.
**Recommendation.** Three tiers, never silently discarding: **exact source-id match** ⇒ same record (idempotent upsert, reported); **exact normalised match** ⇒ held for review as `probable_duplicate`; **similar** ⇒ shown as a hint only. Nothing is dropped; a seller can confirm "this is a different expense". Detection is deterministic, in code, not the LLM.
**Evidence needed.** Normalisation rules (vendor, amount); false-positive tolerance; test corpus of legitimate repeats (two identical monthly bills).
**Status: NOT DECIDED.**

## D7 — Settlement overlap (manual expense vs marketplace-derived cost)

**Current [F].** No guard. Flipkart `Non-Order Charges` can include ad/storage cost.
**Options.** (A) forbid marketplace-cost categories in manual entry; (B) allow but require a treatment/reconciliation; (C) auto-match by amount and date.
**Recommendation.** A+B: marketplace fee categories are not offered as manual categories. Where a seller enters advertising or storage for a channel that has settlement data in the same period, show a **named overlap warning** with the settlement amount the engine already has and require the seller to choose `incremental` or `already_in_settlement`. **No automatic matching** (amount/date similarity only flags).
**Evidence needed.** Per-marketplace list of settlement components that can contain ad/storage; test fixtures with real Flipkart payment exports; owner wording of the warning.
**Status: NOT DECIDED.**

## D8 — Advertising reconciliation

**Current [F].** No validated ad-spend source (no ad adapter; no seller-side integrations by design). `expense.advertising` is the only input, manual.
**Options.** (A) manual only, labelled; (B) add a validated ad-report CSV adapter later.
**Recommendation.** A for V1.0: every advertising figure is labelled `MANUAL`. A future validated source gets a distinct provenance, and a period containing both raises a reconciliation task rather than summing them.
**Evidence needed.** Which ad reports sellers can export (Amazon/Flipkart); owner approval to scope an adapter.
**Status: NOT DECIDED.**

## D9 — Overhead allocation

**Current [F].** `allocate_pool` supports `NET_REVENUE|UNITS|ORDERS`; spec D7 allocates account-level cost by net revenue share **automatically**. The brief wants business-level by default, allocation only when explicitly selected.
**Approved decision (EXP-06).** Business-level overhead is **unallocated by default** and sits outside contribution margin; allocation only on an explicit, supported, valid basis; otherwise unallocated with a reason; the engine does all allocation. **Verified nuance:** the revenue-share default exists as spec D7 and as a hard-coded default in `expense_pools.allocate_account_level_expense_pool`, which has **no production caller**; the period P&L sums whole pools and `OtherAllocatedCosts` currently reduces Contribution Profit. The required change is therefore an engine behaviour change (basis required, an `AllocationOutcome` with reason codes, business overhead moved out of Contribution Profit into a separate fully allocated figure), now described in the amended `deterministic-engine.md` (spec Appendix B.3). Periods, channel scope and rounding remain as proposed earlier: calendar month of `effective_date`; channel-specific only to that channel; `largest_remainder_allocate`.

**Evidence needed.** Owner approval to amend D7; worked rounding example; behaviour for negative or zero revenue SKUs (engine already excludes and reports them).
**Status: APPROVED (product), 2026-10-15 — EXP-06. D7, §5.8, §5.10 of `deterministic-engine.md` amended 2026-10-15 (no engine code). A1–A10 are a launch requirement. Q14, Q15 and Q16 were decided 2026-10-15 (see the final section of this file). Already-reported periods are NOT restated automatically (EXP-02 policy).**

## D10 — CSV import

**Current [F].** Only marketplace-report ingestion; persists immediately; no preview.
**Recommendation.** Two-step import: **upload → validate/preview (nothing written) → confirm**. Fixed documented template (V1.0): `external_id, date, vendor, category, amount, gst_amount, gst_basis, channel_scope, sku, payment_status, reference, description`. Amount parsing exact (integer paise from decimal text, reject >2 decimals, reject sign errors). Row-level error report (row number, column, reason), downloadable. Retry safety: file hash + per-row `external_id`/normalised key ⇒ re-uploading the same file reports "already imported" and changes nothing. Imported rows land as `needs_review`. Confirmation requires `financials.adjust` (EXP-05).
**Evidence needed.** Template sign-off with 2–3 real seller files; max rows; encoding (UTF-8/Windows-1252); date formats (DD/MM/YYYY).
**Status: NOT DECIDED.**

## D11 — Permissions

**Current [F].** `financials.adjust` = create/supersede every registry field; deny-by-default for PARTNER, OWNER implicit. Reads need only `agent.cfo`. No read key for financial data; no delete/approve verbs.
**Superseded recommendation (historical):** "keep `financials.adjust` for all writes; no new key" — replaced by the approved decision below.

**Superseded (2026-10-15):** an interim version of this entry recommended a new key `expenses.write`. It is withdrawn.

**Approved decision (EXP-05, final).** **No new permission key in V1.0.** `financials.adjust` governs every ledger write; OWNER implicit, PARTNER denied by default and only by explicit OWNER grant; reads follow existing behaviour (`agent.cfo`; no financial-read key exists); server-side check with organization validation at every write. Consistent with Q33 (2026-10-10, "no new key"), `cfo-agent.md` §8 rule 4 and E19. **Known limitation:** `financials.adjust` covers every §7.2.1 registry field (including COGS), so a partner granted it for expenses can also change COGS and other margin-moving inputs. Revisit only when a partner-permission grant surface exists or a new approved authorization decision is made (none found in `backend/src` today). Optional wording clarification (not applied): `auth.md` §5.2 "every field in the registry" → add "and records of the expense ledger".

**Evidence needed.** Owner confirmation that partners holding `agent.cfo` may read expenses; HTTP-level 403 tests for each write route.
**Status: APPROVED (product), 2026-10-15 — EXP-05 (no new key; `expenses.write` SUPERSEDED).**

## D12 — Retention and storage

**Current [F].** No object storage; shared-directory content-hash local storage; no deletion job; retention open (`auth.md` Q9, `data-foundation.md` 316/902); the "30-day rule" and its cited source are not in the repository.
**Recommendation.** **Do not change retention.** V1.0 stores structured expense records and *references* only; **no receipt upload** until storage, per-tenant isolation, authorised download and a retention period are approved by security, privacy and legal/CA. Locate or write the source for the 30-day rule before launch; until then no UI may state a retention period.
**Evidence needed.** The 30-day rule document (or confirmation it does not exist); legal/CA retention period; DPDP review.
**Status: NOT DECIDED.**

## D13 — Multi-organization safety

**Current [F].** Active organization = Clerk JWT `org_id` → `tenant_repo.get_by_clerk_org_id`; membership ACTIVE and role resolved each request (`auth/context.py`); no client `tenant_id`; RLS FORCE. No proposal object exists to bind.
**Recommendation.** Bind every proposal and import batch to `(tenant_id, app_user_id)` server-side at creation; at confirm, re-run `resolve_auth_context` and require both to match the stored values; reject on mismatch with the same 404 as "not found" (no existence oracle). Add the explicit `tenant_id` predicate to every new read query as defence-in-depth.
**Evidence needed.** Cross-org confirm test; two-tenant integration test on scratch Postgres; Clerk org-switch behaviour check [U].
**Status: NOT DECIDED.**

## D14 — IndiaMART

**Current [F].** IndiaMART appears only as a supplier-discovery source (`product-intelligence-agent.md` C5/C6, `supplier_lead.source`, schema-only). No adapter, no settlement or cost data.
**Approved decision (EXP-04).** Manual channel tag only; **remove IndiaMART from the "supported through existing capabilities" list**; UI wording "manually tagged, not synced". A real adapter is separate scope.
**Evidence needed.** Owner confirmation; any sample IndiaMART export if an adapter is wanted later.
**Status: APPROVED (product), 2026-10-15 — EXP-04.**

---

## Additional decisions the evidence requires (not in the brief's list)
| ID | Decision | Why |
|---|---|---|
| X1 | Extend or replace the shipped tracker (`ExpenseTrackerSection.tsx`, `PUT/GET /cfo/expenses`) and what happens to existing `ACCOUNT/"default"` rows (undated, excluded from period views) | Audit B5 |
| X2 | Server-side validation bounds on write (sign, zero, maximum, GST ≤ amount, allowed channel values) | `enter_expense` validates the field name only; a malformed row breaks the tenant listing (B4) |
| X3 | Whether expense writes must create an `agent_run` | Known audit gap (`cfo-agent.md` ~289); `pnl-scenario` already does |
| X4 | `currency` field: engine is INR-paise only | Recommend INR only in V1.0; no currency column |
| X5 | Whether `legal-safeguards.md` and `phase1-decisions.md` will be written | Cited, absent (B8) |
| X6 | GST/ITC wording and the standing disclaimer text | Needs CA (`cfo-agent.md` C4); `ITC-eligible` is informational and stored only |
| X7 | TCS handling | Never an operating expense; shown only in the cash/settlement view (engine §5.13.3); CA to confirm |

## Separate task and recorded reversal
| ID | Item | Status |
|---|---|---|
| EXP-07 | Reversal of `cfo-agent.md` "Removed by design" for expenses (part of D1) | **APPROVED (product)** — owner countersign of the spec amendment pending |
| ST-01 | Show "Not entered" for absent advertising spend (display only; formula rule unchanged) | **APPROVED as a separate task**, not an Expense Tracker feature; scope and tests in spec Appendix D; no code change made |
| EXP-08 / X4 | Currency | **APPROVED:** INR integer paise only; no currency field |

---

## Owner decisions on open questions — 2026-10-15

Recorded in full in `docs/decisions/phase1-decisions.md` ("Owner decisions on open questions") and spec §13. Summary:

- **D3 / EXP-03 (Q2):** follow-up amendments approved as spec text only; CEO code and tests unchanged; G6 gate. The "Q2 expense-confirmation flow" came from a decisions document drafted in chat (no repo source).
- **D11 / EXP-05 (Q4, Q20):** `financials.adjust` covers ledger writes (auth.md clarification approved); draft creation also requires `financials.adjust`. No new key.
- **D9 / EXP-06 (Q14):** covers account-level advertising and storage pools.
- **D2 / EXP-02 (Q15, Q16):** release date = first production deploy of the ledger feed after G7 validation (placeholder until then); existing `expense.other` rows untouched under their original formula version, no migration.
- **ST-01 (Q18):** only the display change is approved; no engine change.
- **D12 (Q19):** raw-CSV retention remains with legal/CA review.
- **D1 (Q21):** signed ledger amount; cost positive, refund/credit note negative referencing the original; confirmed against the locked signed-paise rule.
- **Readiness review (Q25):** items 2.8, 6.6 and 2A.13 superseded by EXP-01…EXP-08 for the expense input path.
- **Round 2 (2026-10-15):** Q24 refund/credit note belongs to the period of its own date, linked to the original, no restatement; Q27 unattributed ad/storage spend stays business-level, shown as its own labelled line beside contribution profit, total profit includes it, caveats on pricing recommendations/alerts, what-if fully loaded, release note; Q28 G7 results are `is_trial=true` on a distinct trial formula version, never in seller history or as a restatement baseline, release date = first production deploy after G7 passes with `is_trial=false`; Q25 confirmed for the expense-input part only (OP1 locked); Q21 adds a G2 sign-mapping test; Q19 stays with legal/CA.
- **Round 3 (2026-10-15):** Q29 SKU-level only for validated imports/integrations with an explicit ASIN/SKU identifier mapped to the catalog; campaign spend without ASIN breakdown and all manual entries are business-level (a seller-tagged SKU stays flagged manual); unmapped identifiers go to a review queue, business-level until resolved. Q30 the engine spec owns the total-profit formula (expense spec states only the invariant, tested under G2); `is_trial` is a boolean on the result record excluded from every seller-facing read at the read layer; trial version name is an engine decision. Launch condition: pricing, alert and what-if consumer specs carry the unallocated-spend caveats before release. Q29 and Q30 gate G2, not G1.
- **Round 4 (2026-10-16):** Q29 and Q30 are written into the engine spec (§5.8.1 total profit and invariant, §5.10.1 bases and the SKU-level rule, §5.17 ledger feed, §9.2 result metadata, §9.3 metric codes, §9.4 consumers). The written details are PROPOSED and await product owner approval (list in phase1-decisions.md).
