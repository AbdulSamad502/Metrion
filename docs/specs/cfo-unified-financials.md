# Metrion — CFO Unified Financials Specification

**Status:** Draft for review (CFO 2.0, P3)
**Prerequisites:** `deterministic-engine.md` (§1.2 profit, §5.5 NRR, §5.8 contribution profit, §5.10 allocation, §5.13.3 cash reconciliation, §6 grain) · `data-foundation.md` · `cfo-agent.md` · `cfo-query-planner.md` · `cfo-data-intelligence.md`
**Related:** `cfo-dashboard.md`, `whatsapp-integration.md` (`MARGIN_RISK`), `competitor-intelligence-agent.md`, `product-intelligence-agent.md`, `slim-cmo-agent.md`

This spec defines **what each financial term means**, where each cost may come from, and how Amazon, Flipkart, Meesho and the Expense Tracker become one canonical view. It adds *definitions and ownership rules*; every number is still computed by `deterministic-engine.md`. Where a definition needs a new engine formula, §6 lists it and the engine spec is amended in the same change.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| U1 | **Contribution Profit is not accounting net profit** and every surface labels it so. | engine §1.2 |
| U2 | **TCS/TDS are cash/tax-asset items, never P&L.** | cfo-agent C11 |
| U3 | **Recommend-only.** No marketplace write, no claim filed, no GST filed. | cfo-agent C7 |
| U4 | **GST is management-grade.** Tax interpretation requires verified rules and CA review; CA-ready exports are *prepared material*, not filings. | cfo-agent C4 |
| U5 | **Bank balance is out of scope.** Cash views come from settlements and seller-entered payables only. | cfo-agent Q1; owner decision 2026-10-21 |
| U6 | **No demand forecasting.** "Cash forecast" means expected receipts on *already-sold* orders from observed settlement lag, plus seller-entered payables. | owner decision 2026-10-21; cfo-agent §6.5 |
| U7 | **Ad spend enters through an advertising report adapter** (P3), manual entry remaining the fallback. | owner decision 2026-10-21 |
| U8 | **Mockup wording corrections accepted:** "discrepancy identified" not "recoverable/recovered"; "Recommended actions" not "Autonomous directives"; "Settlements received" not "cash in bank"; Amazon findings provisional/withheld; "last checked" not "Live"; owner drawings outside P&L; GST due dates "indicative". | owner decision 2026-10-21 |
| U10 | **Explicit completeness, everywhere.** Every figure carries one completeness state: `COMPLETE`, `PARTIAL` (some inputs excluded and counted), `PROVISIONAL` (rests on unconfirmed seller input), `ESTIMATED` (an estimate, never a measured actual) or `UNAVAILABLE`. Only `COMPLETE` may be presented as a confirmed actual. Held duplicates, unclassified expenses, unknown advertising, and refused mappings each map to a non-COMPLETE state, never to zero. | Owner decision 2026-10-21 |
| U9 | **Missing or unreliable input → `UNAVAILABLE`**, never zero, never silent assumption. | CLAUDE.md |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Operating Profit definition | `Contribution Profit − Σ overhead-class expenses` (§4.2), reported with a **status**: `PROVISIONAL` whenever any expense in scope is unclassified (the unclassified entries and their total are always exposed beside the figure) and `FINAL` only when none is. **No materiality threshold exists or is invented** (decision OQ1). Excludes depreciation, interest, income tax, owner drawings, inventory purchases, capital items, TCS/TDS, transfers. Labelled "management operating profit — before depreciation, interest and tax". | A threshold would be a business judgement Metrion cannot make for a seller. Showing the figure with its exposed unclassified amount lets the seller see how provisional it is. CA review still required (PV3). |
| D2 | Expense classification | Each expense category carries a fixed `class`: `ALLOCATED_COST` (already inside CP: ads, packaging, logistics), `OVERHEAD` (operating profit only), `OWNER_DRAWING`, `INVENTORY_PURCHASE`, `CAPITAL`, `TAX_ASSET`, `OTHER_UNCLASSIFIED`. Unclassified expenses are shown but excluded from both profits until the seller classifies them. | Prevents silent misclassification. |
| D3 | Shared expenses | Allocation across marketplaces/SKUs only via engine §5.10 (`NET_REVENUE` default, `UNITS`, `ORDERS`), always `DERIVED`, basis shown. | Existing largest-remainder rule keeps sums exact. |
| D4 | Consolidation | Consolidated = Σ of per-marketplace results computed *separately first*; never a concatenation of raw reports. Disagreement between Σ and a directly-computed consolidated figure is a defect. | User brief §3. |
| D5 | Overlap flag | Marketplace-deducted categories (commission, shipping, ads where the marketplace deducts them) entered as seller expenses are stored `MAY_OVERLAP_MARKETPLACE` and require seller confirmation of which source is authoritative. | Prevents double counting. |

---

## 3. Assumptions

| # | Assumption | Risk |
|---|---|---|
| A1 | Sellers can classify an expense category when asked once; defaults are suggestions, not assumed | Medium |
| A2 | Settlement lag per marketplace is observable from ≥ N settled orders (engine config) | **High** — drives the cash forecast; insufficient history → forecast `UNAVAILABLE` |
| A3 | Supplier payment terms are seller-entered | Medium |
| A4 | Ad reports carry spend at campaign level with a usable date; SKU attribution may be absent | Medium — account-level pool allocated per §5.10 |

---

## 4. Definitions

All amounts are signed integer paise. "Basis" is `DOCUMENT_DATE` unless stated.

### 4.1 The seven terms, kept separate

| Term | Definition | Engine owner | Notes |
|---|---|---|---|
| **Gross Sales** | Σ gross item amount of order lines (tax-exclusive), before cancellations, returns, discounts attributed to the seller | NEW `GROSS_SALES` (wraps `gross_order_value`) | A *volume* measure, not revenue |
| **Net Realized Revenue** | engine §5.5 | existing | After cancellations, returns, seller-borne discounts |
| **Contribution Profit** | engine §5.8 | existing | Includes ads, packaging, logistics, return/RTO losses, allocated costs |
| **Operating Profit (management)** | CP − overhead-class expenses (D1) | NEW `OPERATING_PROFIT` | `UNAVAILABLE` when Contribution Profit is unavailable, **or when no overhead expense source and no explicit "no overhead expenses" declaration exists for the period** (a missing input is not zero; engine §5.17.1). Otherwise a value with status `PROVISIONAL` (any unclassified expense in scope; the list and total are exposed with it) or `FINAL` (none). A held duplicate expense is excluded and counted. |
| **Settlement Receipts** | Σ amounts the marketplace *settled* in the period, by settlement date | NEW `SETTLEMENT_RECEIPTS` (wraps `CASH_RECEIVED`) | Receipts ≠ revenue ≠ profit; the gap is timing, returns, fees and levies |
| **Cash Movements** | Seller-visible cash events derived from settlements (+) and seller-entered payables/expenses paid (−), by cash date | NEW view, not a P&L figure | No bank feed (U5); labelled "from settlements and your entries" |
| **Tax Assets** | Prepaid TCS/TDS | existing | Never in any profit |

The dashboard and CEO must not use "revenue", "sales" or "profit" without one of these names.

### 4.1b Explicit component contracts (amended 2026-10-21, owner requirement 5)

These restate **existing, confirmed engine rules** (`deterministic-engine.md` §5.5 to §5.10 and §8) so that every CFO 2.0 surface uses one meaning. They introduce no new financial rule.

**Revenue.** Gross Sales (a volume measure) and Net Realized Revenue (NRR, engine §5.5) are different figures. NRR is the only figure labelled "revenue" on a profit surface, and always by its name. Output GST (CGST/SGST/IGST/UTGST/Cess) collected is **never** revenue (engine §5.9). Customer shipping income and reimbursements follow engine §1.2.0.

**COGS (engine §5.6, D3).** `COGS(line) = weighted_average_cost(sku, as_of = document_date) × billable_quantity`, where `billable_quantity = quantity − returned_qty (all outcomes) − rto_qty (all outcomes)`. COGS is recognised on units sold, never on purchases. A damaged or lost returned unit's cost moves wholly into `ReturnRTOLosses` (§5.7), never both. **COGS absent for a sold SKU is `UNAVAILABLE`** (a sold unit definitely incurred a cost) and raises a data request; never zero. Confidence `MANUAL`.

**Advertising (engine §5.6, Category E: an existing confirmed rule, preserved).** Absence of any advertising entry for a scope resolves to ₹0 for that scope, because advertising is opt-in seller data. This is the one deliberate exception to "missing means UNAVAILABLE" and is **not** changed by CFO 2.0. OQ7 asks whether, once an ad report has been ingested, a period inside its coverage with no rows (a true zero) should be distinguished from a period outside it (no data).

**Contribution Profit (engine §5.8)** and **Operating Profit (§4.1 above):** as defined; Operating Profit is `UNAVAILABLE` when material expenses are unclassified (OQ1).

**Tax components (engine §5.9, §8).**

| Component | Treatment |
|---|---|
| Output GST (CGST, SGST, IGST, UTGST, Cess) on sales | Excluded from revenue and from every profit figure; shown on the GST summary only (indicative, disclaimer) |
| GST on marketplace fees (`line_component.tax_amount` where kind = FEE) | Shown separately as *potentially creditable* (never confirmed ITC). A seller who cannot claim may toggle it into `OtherAllocatedCosts` via a recorded manual input |
| TCS | Tax asset and cash item: reduces settlement receipts, **not** a cost, never in P&L |
| TDS | Same as TCS; `UNAVAILABLE` where no source reports it |
| Rate source | OP13 layered resolution; no rate from model knowledge; an accepted `gst_rate_override` is the only way a looked-up rate enters a calculation |

**Shared expenses.** A pool that spans marketplaces or SKUs (ad account, packaging stock, a shared warehouse) is allocated **only** by engine §5.10: `pool × NRR(line) / Σ NRR(pool_scope)` with basis `NET_REVENUE` (default), `UNITS` or `ORDERS`; remainders by largest remainder so allocations sum exactly to the pool; lines with zero or negative NRR are excluded and reported unallocated; every allocated figure is `DERIVED` and names its basis. A pool never allocates to a scope with no NRR (reported as unallocated, not forced). Personal and owner items are not shared expenses (§4.2).

**Settlement receipts.** `Σ settlement-side net amount by settlement date` (`CASH_RECEIVED`, engine §5.13.3). Receipts are net of TCS/TDS and fees as the marketplace settles them; they are not revenue and not profit, and the gap to NRR/CP is timing plus returns, fees and levies. A missing settlement report is "no settlement data", never zero receipts.

**Cash movements** (a view, not a P&L figure; no bank feed):
- inflows: settlement receipts, by settlement date;
- outflows: seller-entered expenses by expense date (as paid), supplier payments by payable due/paid date, owner drawings (owner-account block), capital items;
- not outflows: TCS/TDS (they reduce receipts), COGS (recognised on sale), allocations;
- every line carries its source (settlement file/row or the seller's entry) and `MANUAL` where seller-entered.

### 4.1c Advertising spend status and operating-profit status (decisions OQ7 and OQ1, 2026-10-21)

**Advertising (compatibility preserved).** The engine rule is unchanged: a scope with no advertising entry resolves to ₹0 inside `AdvertisingCosts` and therefore Contribution Profit (engine §5.6, Category E). Existing figures, tests and callers are unaffected.

**New intelligence outputs distinguish three states of *knowledge*, never the amount alone** (`AD_SPEND_STATUS`, engine §5.17):

| Status | Meaning | May be shown as zero? |
|---|---|---|
| `VERIFIED_ZERO` | An advertising source covers the marketplace and period and reports no spend, **or** the seller has explicitly declared "no advertising" for it | Yes — "₹0 (verified)" |
| `KNOWN_SPEND` | A source covers the whole period and reports spend above zero (the amount is the covered, known spend) | n/a — a real amount |
| `MISSING_COVERAGE` | An advertising source exists for the marketplace (a report has been ingested) but does not cover this period or scope | **No** — "not covered by your ad reports" |
| `UNKNOWN` | No advertising source and no declaration at all | **No** — "unknown" |

ROAS/ACOS/TACOS, the proactive scan, the CEO's narration and the dashboard must carry this status with any advertising-dependent figure. Contribution Profit keeps its legacy ₹0 value but exposes `ad_spend_status` alongside, so a seller sees when a profit figure rests on an assumption of no ad spend. The status is derived by Brain 1 from the ad coverage that was ingested or declared, never from the absence of rows alone.

**GST scope.** GST-inclusive amounts, GST on fees, TCS/TDS and the India-specific reconciliation remain in the production scope (`cfo-data-intelligence.md` §6.5a); where a figure rests on a rate or an interpretation that still needs seller confirmation or CA review it is shown `PROVISIONAL`/`ESTIMATED`, never `COMPLETE`.

**Operating profit status.** `PROVISIONAL` while any expense in scope is `OTHER_UNCLASSIFIED` or any expense is held as a possible duplicate; `FINAL` otherwise. The unclassified and held entries and their amounts are returned with every Operating Profit result.

### 4.2 Expense classes (D2)

**Classification is suggest-only (decision OQ2).** A suggested class is a hint with a stated reason; it changes no figure. Until the seller confirms (recorded as a `manual_adjustment` `expense.class`), an expense stays `OTHER_UNCLASSIFIED`.

| Class | In Contribution Profit | In Operating Profit | In Cash Movements |
|---|---|---|---|
| `ALLOCATED_COST` (ads, packaging, logistics pools) | Yes (allocated, DERIVED) | Yes (via CP) | When paid |
| `OVERHEAD` (software, professional fees, rent, salaries, utilities) | No | Yes | When paid |
| `OWNER_DRAWING` | No | **No** | Yes (owner account block) |
| `INVENTORY_PURCHASE` | No (COGS recognised on units sold) | No | Yes (payable/paid) |
| `CAPITAL` | No | No (depreciation out of scope) | Yes |
| `TAX_ASSET` (TCS/TDS) | No | No | Yes (reduces receipts) |
| `OTHER_UNCLASSIFIED` | No | No — and flagged | When paid |

### 4.3 Cost ownership matrix (V-DUP-2)

For each `component_code` in a scope and period exactly one **owner** is active:
`MARKETPLACE_DEDUCTION` · `SELLER_EXPENSE` · `ADVERTISING_REPORT` · `MANUAL_OVERRIDE`.
Examples: marketplace commission → `MARKETPLACE_DEDUCTION` only; advertising → `ADVERTISING_REPORT` *or* `SELLER_EXPENSE` (not both for the same period/marketplace); packaging → `SELLER_EXPENSE`. A second source for the same owned component creates an `agent_data_request` ("Ad spend appears in both your settlement and your expense file — which is authoritative?") and is excluded from totals until answered. Choices persist as a `manual_adjustment` (`cost.owner.<component>`), superseding, never overwriting source data.

---

## 5. Data model

No new manual-input store (cfo-agent AC17d). Additions:

```sql
expense_class_map (               -- config: category -> class; tenant-nullable platform defaults
  id uuid pk, tenant_id uuid null, category text not null, class text not null,
  allocation_basis text, created_at timestamptz not null )

cfo_read_model_version (          -- per-tenant monotone counter; the cache invalidation signal
  tenant_id uuid pk, data_version bigint not null, updated_at timestamptz not null )

ad_report_line (                  -- advertising adapter output (cfo-data-intelligence §9)
  id uuid pk, tenant_id uuid not null, ingestion_run_id uuid not null,
  marketplace text not null, campaign_ref text, sku text, report_date date not null,
  spend bigint not null, attributed_sales bigint, impressions bigint, clicks bigint,
  source_row_number int not null, source_row_json jsonb not null, confidence text not null )

payable_entry via manual_adjustment field `payable.supplier` (engine §7.2.1 registry request)
```
All tenant-owned tables carry `tenant_id` with `FORCE` RLS; `cfo_read_model_version` is bumped in the same transaction as any write that changes canonical data.

Engine registry requests (engine §7.2.1): `expense.class`, `cost.owner.<component>`, `payable.supplier`, `expense.shared_allocation`. The spec owner of the key space remains the engine spec.

---

## 6. Core rules

### 6.1 Unified P&L
Per-marketplace NRR and CP are computed separately (planner V-ACC-2), then consolidated by summation. Expense pools enter via the cost-ownership matrix. SKU-level and order-level views use the same engine at line grain. Any cell lacking a required input is `UNAVAILABLE` with `missing_inputs`.

### 6.2 Profit bridge
`PROFIT_BRIDGE(period_A, period_B)`: engine computes ΔCP and the Δ of each component (NRR, COGS, fees, logistics, ads, return/RTO losses, other allocated). Drivers are ranked by |Δ| (deterministic). `OTHER` = ΔCP − Σ drivers (must be 0 or itemised). Narration may say "returns explain the largest verified share"; it never invents a cause.

### 6.3 Leak Shield 2.0
Builds on `reconcile()` (§5.12). Additions: duplicate-charge detection across settlement lines; refund-without-return-credit; fee mismatches against `fee_reference`; marketplace-level aggregation of discrepancy amounts via `leak_aggregate`; claim status lifecycle (`NEW → ACKNOWLEDGED → CLAIM_DRAFTED → SELLER_REPORTED_RAISED → SELLER_REPORTED_RESOLVED/DISMISSED`) where **the seller reports** claim progress (C7: Metrion never files). Language: "discrepancy identified". `CLAIM_DRAFTED` produces copyable text with order ids only. Amazon: withheld pending match-key verification.

### 6.4 Expense intelligence
Categorisation via `expense_class_map` and seller confirmation; recurring-cost detection (deterministic: same category and similar amount in ≥ 3 consecutive months — thresholds config); anomalies reuse Brain 2 (z-score/percentile on category totals; minimum series per anomaly spec); budgets reuse existing `expenses/budget`; receipt evidence attached by reference (file id) — no OCR in this cycle; shared-expense allocation per D3.

### 6.5 Cash and working capital
- **Expected receipts** = for each unsettled sold order line, expected settlement date = document date + observed median lag for that marketplace (engine `SETTLEMENT_LAG_DAYS`); amount = engine-known settlement-side or net-of-known-fees figure when available, else `UNAVAILABLE` for that line. The forecast aggregates *only available lines* and states the excluded count and amount. No sales are projected.
- **Payables** from `payable.supplier` entries (amount, due date). **Shortage warning** when a payable's due date precedes expected receipts covering it (`COVERED` / `AT_RISK` / `UNAVAILABLE`), computed by the engine; never from a bank balance.
- **Working capital view:** receivable (expected receipts), payables, inventory commitments (seller-entered POs) — three disclosed lines; no ratio unless the engine defines it.
- Insufficient lag history → whole forecast `UNAVAILABLE` with the minimum needed stated.

### 6.6 Pricing and inventory finance
Existing `pricing`, `landed_cost`, `supplier_ranking`, `batch_size`. Additions (engine formulas, NEW): break-even price (price at which margin-at-price = 0, from the same margin-curve primitive), inventory ROI **estimate** for a quoted order (labelled ESTIMATE; requires seller sell-through assumption entered explicitly — never derived), stock-related cash risk (order cost vs expected receipts window). Estimates cite `estimate_ref`, never `engine_result_ref`.

### 6.7 Tax and CA readiness
GST/TCS/TDS visibility (existing). **CA export pack:** period P&L with component breakdown, GST period summary, TCS/TDS schedule, reconciliation summary, exclusions and `UNAVAILABLE` items, with provenance (source file, row, ingestion run, formula version, engine result ref) per line. XLSX + CSV. Every sheet carries the management-grade disclaimer. The pack states plainly that it is not a return and lists open `agent_data_request`s. Rate resolution stays OP13-layered; no rate from model knowledge. Tax interpretation sections require `CA_REVIEWED: true` in rule data before display as anything other than "indicative".

### 6.8 Business health
Existing Financial Health Band; add SKU concentration (share of NRR by SKU, engine formula NEW, top-N), margin stability (volatility of CM% across periods, engine NEW, minimum series), financial goals (`seller.goal` + engine §5.16 `goal_progress`), funding readiness (existing completeness report; no score).

### 6.9 Proactive CFO
After any ingest or adjustment, a deterministic **risk scan** runs: health band change, anomaly flags, leak windows closing, budget overruns, cash `AT_RISK`, stale data. Each produces a `StrategicSignal` (existing contract) with a **Brain-1 impact figure** (e.g. "margin down 4.5 points", "₹X discrepancy window closes in N days"). Delivery: persisted as shared findings → surfaced by CEO and dashboard; WhatsApp `MARGIN_RISK` per its spec. Recommendations are advisory; any write needs explicit seller approval through the existing approval workflow.

### 6.10 Cross-agent collaboration
Through CEO's fixed dispatch only: PI (product investment → landed cost / batch / ROI estimate), CI (competitor price → margin at price), CMO (ad economics from `ROAS/ACOS/TACOS`, requiring the ad adapter). CFO never calls another agent directly.

---

## 7. AI requirements

LLM narrates evidence packets and bridges; selects registered metrics/dimensions via the planner; never computes, ranks, classifies money, or fills a missing input. New narration surfaces (bridge, cash forecast, proactive signal) require evals before seller exposure — **deferred this cycle** (cfo-query-planner §12).

## 8. Authorization and security
Reads: `agent.cfo` (+`agent.ceo` for conversational). Expense classification, ownership choices, payables: `financials.adjust`. CA export: `agent.cfo` + CFO entitlement, audited. Owner-drawing and personal categories are visible only to roles with `financials.adjust` (config). Tenant RLS on every table above. No client-supplied `tenant_id`.

## 9. Edge cases
E1 expense in both settlement and expense file (D5/§4.3) · E2 refund in a later period than the sale — attributed to the original document period (engine §6), cash in settlement period · E3 one order, several fee rows (one-to-many, aggregate-then-join) · E4 order split across marketplaces never merged by SKU alone · E5 negative net revenue line excluded from allocation basis and disclosed · E6 a return with no refund amount → `UNAVAILABLE` · E7 owner drawing categorised as `other` → class forced to unclassified until confirmed · E8 partial period · E9 marketplace with no COGS → CP `UNAVAILABLE` for that marketplace; consolidated CP states which marketplaces are excluded, never sums partial silently · E10 payable with no due date → excluded from shortage check, listed · E11 ad report with SKU attribution missing → account pool allocated, `DERIVED` · E12 duplicate ad report upload (content hash).

## 10. Production-validation blockers
PV1 CA review of Operating Profit, expense classes, and the export pack · PV2 ad-report formats unverified against real exports (Amazon/Flipkart/Meesho) — adapters ship `is_verified=False` · PV3 observed-lag minimum history · PV4 Amazon/Flipkart join keys (cfo-agent V1/V6) · PV5 thresholds (materiality, recurrence) are provisional config.

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC-U1 | The seven terms are defined once (§4.1) and no surface uses "profit/revenue/sales" ambiguously |
| AC-U2 | Σ per-marketplace CP = consolidated CP exactly |
| AC-U3 | Owner drawings, inventory purchases, capital, TCS/TDS, transfers appear in no profit figure |
| AC-U4 | An expense present in both settlement and expense file is excluded and a data request raised until resolved |
| AC-U5 | Cash forecast never projects unsold orders; excluded lines are counted; no bank balance is displayed or assumed |
| AC-U6 | Profit bridge drivers + OTHER = ΔCP exactly |
| AC-U7 | CA pack lines each carry provenance; open data requests and UNAVAILABLE items are listed |
| AC-U8 | No claim is described as filed by Metrion; statuses after drafting are seller-reported |
| AC-U9 | Proactive signals' impact figures all carry `engine_result_ref` |
| AC-U10 | New metrics are added to `deterministic-engine.md` with formulas, tests and `formula_version` before use |

## 12. Test scenarios
TU1 three marketplaces golden dataset → Σ = consolidated · TU2 one order with 3 fee rows → ties to control total · TU3 ad spend double-source → excluded + request · TU4 owner drawing in `other` → unclassified · TU5 refund next month → original period · TU6 settlement lag insufficient → forecast UNAVAILABLE · TU7 payable due before expected receipts → AT_RISK · TU8 COGS missing on Meesho only → consolidated CP states exclusion · TU9 CA pack provenance round-trip · TU10 proactive scan after late upload · TU11 break-even price equals price where margin-at-price = 0 · TU12 shared expense allocation sums exactly (largest remainder).

## 13. Explicit open questions
| # | Question |
|---|---|
| OQ1 | ~~Materiality threshold for unclassified expenses blocking Operating Profit~~ **Resolved 2026-10-21:** no threshold; Operating Profit is `PROVISIONAL` while anything is unclassified and `FINAL` when nothing is, with the unclassified entries exposed |
| OQ2 | ~~Default expense class per category~~ **Resolved 2026-10-21: suggest-only.** A class is a suggestion (shown with its reason) until the seller confirms it; an unconfirmed expense stays `OTHER_UNCLASSIFIED`, is excluded from both profit figures, and is listed |
| OQ3 | Minimum settled-order history for lag-based forecasting |
| OQ4 | Whether receipt evidence needs OCR later (out of scope now) |
| OQ5 | GST due-date calendar source and CA-review gating wording |
| OQ6 | Whether inventory ROI estimate is shown before any sell-through input exists (Recommend: no — `UNAVAILABLE` + request.) |
| OQ7 | ~~Advertising "absent = 0" vs the ad-report adapter~~ **Resolved 2026-10-21:** the legacy rule (no advertising entry resolves to ₹0 inside Contribution Profit) is **preserved for compatibility**; new intelligence outputs use the three-state `AD_SPEND_STATUS` of §4.1c and never present an unknown or uncovered amount as a verified zero |
