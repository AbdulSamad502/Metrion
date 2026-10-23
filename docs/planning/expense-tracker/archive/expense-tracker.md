> **SUPERSEDED (2026-10-15).** This root draft has been reconciled into the canonical specification `docs/specs/expense-tracker.md` (see its Appendix A) and into the approved decisions in `docs/decisions/phase1-decisions.md`. Where this file disagrees with them (IndiaMART as a supported channel; `financials.adjust` as the write key; `replaces_input`; chat quick-add; automatic revenue-share allocation), **they win**. Kept unchanged below for traceability pending approval to remove it; do not edit it.

# Expense Tracker Spec

Status: DRAFT v2 for spec-reviewer. Resolutions marked "Proposed" are recommended defaults for the reviewer, not claims that the current implementation already supports them.
Version scope: V1.0 (minimal), with V1.5 and later items listed explicitly.
Depends on: deterministic-engine.md, auth.md, cfo-agent.md, data-foundation.md, legal-safeguards.md, docs/decisions/phase1-decisions.md.

## 1. Purpose

The Expense Tracker is a cost-input workspace inside the existing CFO / Profit & Finance experience. It is not a standalone accounting product, not a separate AI agent, and not a new top-level navigation destination. It lets sellers record costs that marketplace settlement data does not capture, and feeds them safely into the True Margin Engine.

## 2. Non-goals

- No bookkeeping, ledger, invoicing or GST filing functionality.
- No filing-grade tax output or compliance judgments (legal-safeguards.md, section 5).
- No automatic integrations or reconciliation for channels Metrion does not yet support.
- No receipt-image OCR, WhatsApp quick-add or bank statement import in V1.0.
- No custom categories in V1.0.
- No separate top-level nav item.

## 3. Cost classes

- **Marketplace-derived costs:** come from settlement data only and are never entered again as separate expenses.
- **Direct costs** (packaging, inward freight): associated with a SKU when the seller supplies enough information.
- **Advertising spend:** sourced data from a verified integration or validated import. Manual entries remain identifiable adjustments.
- **Business overhead** (rent, salaries, software, utilities): business-level by default. Allocated to SKUs only when the seller explicitly selects a method.
- **Channel scope:** every expense is either business-wide or channel-specific, and the two are kept separate.

## 4. V1.0 functional scope

### 4.1 Expense dashboard
- Monthly totals, category breakdown, recurring commitments, review queue.
- Every figure shows an "as of" timestamp.

### 4.2 Expense records
- Manual entry and editing.
- Fields: category, date, vendor, amount, currency, description, channel scope, optional SKU, source reference, payment status, review status, financial treatment (4.6), tax-related fields (section 8).
- **Categories:** controlled default list only (Proposed). Custom categories are deferred until the taxonomy and reporting behavior are stable.
- **Payment status:** `unpaid`, `partially_paid`, `paid`, `unknown`.
- **Review status:** a separate field from payment status. An expense can be paid but still need classification, or unpaid but already confirmed. Exact values are for the reviewer (see Open Questions).
- Recurring expense templates.
- Source references to invoices or receipts, with access controls (section 9).

### 4.3 CSV import
- V1.0 supports a documented fixed template, with validation and a preview before import. Column mapping is added later only if seller feedback justifies it (Proposed).
- Duplicate detection: use source transaction or reference IDs when available. Otherwise flag likely duplicates using date, normalized vendor, amount, currency and description. Likely duplicates are flagged for review, never silently discarded (Proposed).

### 4.4 CFO quick-add
- The seller describes an expense in CFO chat.
- The LLM extracts a proposed expense and shows a confirmation card ("Would you like to add this expense?").
- Nothing is saved until the user explicitly approves.
- **Idempotent confirmation:** each proposal has a stable proposal ID and is bound to the active organization. Approving twice, or retrying after a network failure, must not create two expenses.
- **Organization binding:** the active organization is validated server-side at both proposal and save. An organization ID supplied by the LLM or client payload is never trusted (Proposed).

### 4.5 Cost allocation
- Direct costs: SKU association.
- Overhead: business-level by default, with optional allocation by revenue share or units sold.
- Allocation uses the reporting period and the matching channel scope. Revenue-share allocation requires revenue for the same period. Unit allocation requires corresponding unit counts. If the basis is unavailable, the overhead stays unallocated (Proposed).
- Unallocated overhead stays visible and is never silently distributed.
- Product contribution margin is shown separately from fully allocated profitability.
- All allocation rules execute in the deterministic engine, never in the CFO agent.

### 4.6 Financial contract with the engine
Each expense carries an explicit financial treatment so the engine knows how to use it. Proposed values:
- `incremental`: an additional cost not represented elsewhere.
- `replaces_input`: replaces an existing COGS or ad-spend input.
- `already_in_settlement`: a cost already represented by settlement data. It is stored for reference and does not affect margin.

Duplicate detection alone does not prevent double-counting. The treatment field is the primary guard.

### 4.7 Settlement and advertising overlap
- Settlement overlap: use source references and known transaction mappings first. Use amount, date and category similarity only to flag possible overlap for review, never to make unsupported automatic matches (Proposed).
- Advertising: if validated ad data later overlaps a manual entry, flag it for reconciliation instead of double-counting (Proposed).

### 4.8 History, edits and deletions
- Preserve an audit history of every create, edit and delete.
- Version financial outputs. Correct historical reports through traceable recalculation, not silent overwrite (Proposed).
- Semantics of recalculation are a blocking item for the reviewer (see Open Questions).

## 5. Channels

- Supported through existing Metrion capabilities: Amazon, Flipkart, Meesho, IndiaMART.
- **IndiaMART:** expenses are manual-only unless the existing integration supplies validated settlement-derived cost records. Do not assume the settlement model applies to every channel (Proposed).
- Manually recorded expenses may be tagged to the seller's own website, WhatsApp orders or other channels.
- No promise of automatic sync or reconciliation for unsupported channels.

## 6. Permissions

- `financials.adjust` governs creating, editing, deleting and approving expense changes. It is deny-by-default. OWNER has it by default. PARTNER does not unless granted (Proposed).
- Review-only visibility follows existing financial-data read permissions. Write access is never granted implicitly.
- Quick-add approval requires `financials.adjust` at save time, checked server-side.

## 7. AI requirements (LLM boundary)

- The LLM may extract a proposed expense from chat text and may explain stored figures.
- The LLM must never compute, allocate or alter a monetary amount.
- The LLM must not save an expense. Saving happens only after explicit user approval of the confirmation card.
- Extracted fields are shown for editing before approval.
- The LLM never supplies the organization ID, proposal ID or financial treatment as authoritative values. These are set and validated server-side.
- No LLM-generated numeric literals in CFO responses (lint-enforced per legal-safeguards.md section 1).

## 8. Tax handling

- Store GST-inclusive or exclusive status, GST amount and an informational "ITC-eligible?" flag.
- Do not claim filing-grade advice. Show: "Estimate for planning purposes. Verify with your CA."
- **Headline margin:** economic margin is the default profitability measure. The cash and settlement position is shown separately, with explicit labels and an "as of" timestamp (Proposed).
- **TCS is not an operating expense.**
  - Economic margin: revenue and costs under the appropriate GST-exclusive or inclusive treatment.
  - Cash and settlement view: TCS deductions on payouts and GST credits are shown separately.
  - GST position: eligible credits and liabilities tracked per validated tax rules.
  - TCS is never subtracted as an expense and then also counted as a GST credit.
- The CA must validate the exact treatment and current applicable rates before any tax-related output is finalized.

## 9. Receipts and retention

- Receipts and invoices use existing private object storage and authorization controls. References and metadata are stored separately from files. No new public file-serving path is created (Proposed).
- Structured expense records are kept according to the applicable retention policy.
- **Retention period: unresolved.** It is pending legal and CA review. Do not invent a period or silently change the existing 30-day raw-upload deletion rule (legal-safeguards.md section 3).
- Before launch, reconcile the 30-day deletion rule with accounting and tax retention requirements. Do not extend raw-file retention or exempt receipts from deletion without a security, privacy and legal review.

## 10. Phasing

- **V1.0:** everything in section 4.
- **V1.5:** receipt-image OCR (local vision model), WhatsApp quick-add.
- **Later:** bank statement import, CSV column mapping (if justified), custom categories.

## 11. Open Questions (for spec-reviewer)

### Blocking before any coding
1. **Financial adjustment contract:** confirm the `incremental` / `replaces_input` / `already_in_settlement` model against deterministic-engine.md section 7.3, including how `replaces_input` interacts with the existing COGS override and ad spend entry.
2. **Permission behavior:** confirm `financials.adjust` semantics for create, edit, delete and approve, and the read-permission fallback for review-only users, against auth.md.
3. **Historical recalculation semantics:** how versioned financial outputs are stored, when past periods are restated, and how restatements are labeled to sellers.

### Can remain explicitly unresolved at implementation start
4. Exact values and transitions of the review status field.
5. Retention period for structured records and the legal basis (needs CA and lawyer input).
6. Reconciling the 30-day raw-upload deletion rule with receipt and invoice retention.
7. Exact TCS and GST treatment and current rates (needs CA validation).
8. Default category list contents.
9. CSV template columns and the preview and error-reporting behavior.
10. Whether IndiaMART supplies any validated settlement-derived cost records today.

### Reviewer task
Identify conflicts with deterministic-engine.md, auth.md, cfo-agent.md, data-foundation.md and legal-safeguards.md, and distinguish blocking decisions from items that can stay unresolved.
