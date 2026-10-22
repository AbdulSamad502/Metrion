# Metrion — CFO 2.0 Phase 3b–3f: exact scope, rules and limits

**Status:** Draft for review (CFO 2.0, Phase 3b–3f; written 2026-10-22, before the code). Phase 3a is `cfo-expense-ledger.md`.
**Authority:** the requirements are in `cfo-unified-financials.md` §4.1c, §4.3, §6.3–§6.9 and `cfo-data-intelligence.md` §6.8; this document fixes what is built *in this cycle*, how, and what is deliberately not. Where it is narrower than those specs, the narrower scope is what the code does and says.

**Standing rules (all sub-phases):** missing is `UNAVAILABLE`, never zero · every figure cites an `engine_result_ref` (an estimate cites an `estimate_ref`) · recommend-only (no marketplace write, no claim filed, no return filed) · tenant isolation by `FORCE` RLS · append-only storage (SELECT/INSERT only for the application role) · no LLM in any calculation · mocked model only in tests · no invented headers or rates.

---

## 3b — Advertising

**Decisions.**
- AD1. **Ad reports arrive through a seller-confirmed column mapping** (`report_kind=ADVERTISING`) into `ad_report_line` (append-only already). The three dedicated adapters `{amazon,flipkart,meesho}.ads.*` named in `cfo-data-intelligence.md` §6.8 are **not built**: they need real export samples, and inventing headers would violate "never guess". The mapping path is the supported one until a real export validates an adapter.
- AD2. **Row identity** = (marketplace, campaign_ref, sku, report_date). An identical repeat is skipped and counted. The same identity with different spend/sales is **rejected with its reason and counted** (the earlier figure stands; nothing is overwritten or double counted). Whole file = one transaction; >20% rejected rolls it all back.
- AD3. **Coverage** (what the system may call "known") is derived from reports and declarations, never from the absence of rows: a report covers `[min report_date, max report_date]` of an ingestion run for its marketplace; a legacy `expense.advertising` pool covers its period (its marketplace if stated, else all); a seller's explicit **"no advertising" declaration** (`ad_period_declaration`, append-only) covers its period. `AD_SPEND_STATUS` (Phase 2a) is evaluated from these.
- AD4. **Ownership (V-DUP-2 / cost-ownership matrix).** For a marketplace and period, advertising has exactly one owner: the advertising report or a seller-entered pool. If **both** exist for overlapping dates the answer for that marketplace is `UNAVAILABLE` ("two sources") with one data request, until the seller records a **cost-owner choice** (`cost_owner_choice`, append-only: component, marketplace, period, owner `REPORT | POOL`). The unchosen source is then excluded from advertising totals and disclosed. (This is the mechanism the expense ledger also needs for AC-L8; it is built generically here and used for advertising only.)
- AD5. **Contribution Profit.** Where the owner is the report, its spend for the period (per marketplace in scope) is added to the advertising input of the planner's Contribution Profit, labelled `ADVERTISING_FROM_REPORT`; legacy pool behaviour is unchanged. A SKU-narrowed scope with report spend present is `UNAVAILABLE` (a report's SKU attribution may be absent).
- AD6. **Planner:** `AD_SPEND`, `ROAS`, `ACOS`, `TACOS` (Phase 2a `ad_ratios`), consolidated or by marketplace. TACOS' denominator is Net Realized Revenue when available, otherwise TACOS is unavailable with the reason. Each figure carries its `AD_SPEND_STATUS` label.

**Acceptance.** AC-B1 identical repeat skipped, conflicting repeat rejected, file atomic · AC-B2 status evaluated from coverage only (no rows ≠ verified zero) · AC-B3 report vs pool conflict → unavailable + one request; a recorded choice resolves it and the other source is excluded · AC-B4 ROAS/ACOS/TACOS exact fractions, unavailable when spend/sales unknown · AC-B5 CP includes report spend only when the report is the owner; an exact paisa test · AC-B6 tenant isolation · AC-B7 append-only grants.
**Not built:** dedicated verified adapters; per-SKU ad allocation (engine §5.10) for planner views; report-vs-settlement reconciliation of ad charges.

## 3c — Cash and payables

**Decisions.**
- CA1. **Payables** are seller-entered `payable.supplier` manual inputs (engine §7.2.1 registry key; append-only, superseding, `financials.adjust`): `amount_paise`, optional `due_date`, `supplier_ref`, `po_ref`, `status OPEN | PAID` (paying is a superseding row).
- CA2. **Observed settlement lag** per marketplace = days from an order line's document date to its settlement date over **matched** pairs. Only the **Meesho** `line_ref` join is validated; Amazon/Flipkart have no validated key (`cfo-agent` AC5/V1), so they have no lag samples and are listed as **not projected**, never guessed.
- CA3. **Expected amount.** The engine does not know a not-yet-settled line's net amount (Meesho commissions are deducted entirely on the settlement side). The forecast therefore uses an **ESTIMATE**: `gross_item_amount × R`, where `R` is the **lower median of the observed settlement-to-gross ratios** of matched pairs of that marketplace (integer arithmetic, half-up per engine §5.11), requiring at least `min_samples` pairs (configuration; none seeded). Every receipt figure is labelled `ESTIMATED` and cites an `estimate_ref`, never an `engine_result_ref`. Overdue expectations are reported separately and never counted as cover.
- CA4. **Shortfall status** per payable = Phase 2a `cash_shortfall_status` over the estimated receipts (`COVERED | AT_RISK | UNKNOWN`); no bank balance is read or assumed; an unavailable forecast makes the status unavailable with the reason.
- CA5. **Working capital** = three disclosed lines (expected receipts, open payables, plus nothing else): no ratio is defined, so none is shown. Inventory commitments (seller POs) are not built.
- CA6. **Owner-account view** (drawings) is the `OWNER_DRAWING` ledger class read through the planner's expense breakdown (3a); it needs `financials.adjust`-level role to view in the HTTP route.

**Acceptance.** AC-C1 payables append-only/superseding; PAID leaves the cash view · AC-C2 lag and ratio samples only from matched Meesho pairs; fewer than `min_samples` → that marketplace not projected and named · AC-C3 estimate = exact integer arithmetic with documented rounding; ESTIMATED + `estimate_ref` · AC-C4 overdue separate, equality at the due date is covered, undated payable UNKNOWN · AC-C5 tenant isolation · AC-C6 never reads a bank balance.
**Not built:** inventory commitments, Amazon/Flipkart projections, payment terms inference, ratios.

## 3d — Leak Shield 2.0

**Decisions.**
- LD1. Builds on the existing `reconcile()` findings (`leak_finding`). Added **deterministic detections over settlement lines**: (a) **duplicate charge** — two or more settlement lines with the same marketplace, order/line reference, component (document) type and amount in the same or consecutive settlements, listed as candidates (the seller decides), (b) **refund without return credit** — a refunded sales line (return status RETURNED with a known refund) whose order has no settlement-side reversal line; (c) **fee mismatch** — a settled fee outside the `fee_reference` tolerance, only where a fee reference row exists (otherwise "no reference", never a verdict).
- LD2. **Language:** "discrepancy identified"; amounts are *discrepancy*, never "recoverable"; Amazon findings are **withheld** (match key unverified).
- LD3. **Claim lifecycle** (the seller reports; Metrion never files): `NEW → ACKNOWLEDGED → CLAIM_DRAFTED → SELLER_REPORTED_RAISED → SELLER_REPORTED_RESOLVED | DISMISSED`, forward-only, each transition recorded append-only with who/when. `CLAIM_DRAFTED` yields **copyable text containing order ids only** (no seller totals, no model).
- LD4. Marketplace-level aggregation through the existing `leak_aggregate`.

**Acceptance.** AC-D1 each detection has golden tests with exact paise, including the non-detections · AC-D2 lifecycle is forward-only and append-only; a seller cannot skip to RESOLVED without RAISED · AC-D3 claim text contains order ids only · AC-D4 Amazon withheld · AC-D5 tenant isolation.
**Not built:** detections needing real Flipkart/Amazon settlement semantics; a ranking by recoverability (language forbids it); any filing.

## 3e — CA export pack

**Decisions.** `GET /cfo/ca-export?period_start&period_end&format=xlsx|zip` builds, from persisted engine results and the ledger only (no model): **Cover** (period, generated-at, not-a-return statement, management-grade disclaimer), **P&L** (NRR, component costs, Contribution Profit, operating profit with its status, each with `engine_result_ref`/formula version), **Expenses** (by category and class, held and unclassified listed), **GST summary** (existing engine summary), **TCS/TDS schedule** (levies from settlement components; shown as tax assets, not costs), **Reconciliation** (leak findings summary), **Exclusions & unavailable** (every `UNAVAILABLE` metric with its reason and every excluded line count), **Open data requests**, **Provenance** (source file, ingestion run, row for expense entries; formula versions). Every sheet carries the disclaimer; tax interpretation columns are labelled **indicative** unless rule data carries `CA_REVIEWED: true`.

**Acceptance.** AC-E1 workbook opens, has the fixed sheets, every money cell is integer paise formatted as rupees by display only · AC-E2 the pack's totals equal the engine results by `engine_result_ref` · AC-E3 unavailable items are present with reasons, not omitted · AC-E4 disclaimer on every sheet · AC-E5 tenant isolation · AC-E6 `financials.adjust`-independent read permission `agent.cfo`.
**Not built:** PDF, a GST return, e-invoice data, depreciation, any submission.

## 3f — Proactive CFO scan

**Decisions.** After an ingest or a ledger/payable/ad change, a **deterministic scan** (no model) evaluates: financial-health band change, anomaly flags (Brain 2), leak windows closing, budget overruns, cash `AT_RISK` payables, advertising source conflicts, stale data (newest document date older than `stale_days` configuration), unclassified/held expenses. Each yields a **signal** (category, severity rank, headline built from fixed templates, the Brain-1 figure with its ref) persisted as a shared finding and de-duplicated by (category, scope, data version). Delivery to the seller is through the CEO and dashboard reading those findings; WhatsApp stays on its own spec. Every recommendation is advisory (approval workflow for any write).

**Acceptance.** AC-F1 each rule has a firing and a non-firing golden test · AC-F2 a repeat scan on the same data version adds nothing · AC-F3 signals cite refs and carry no model text · AC-F4 tenant isolation · AC-F5 no scan runs without tenant context.
**Not built:** push delivery, scheduled (time-based) scans, WhatsApp wiring.

---

## Explicit open questions

| # | Question |
|---|---|
| P3-1 | Are dedicated, verified ad adapters wanted before any real export exists? (Recommendation: no; mapping path first.) |
| P3-2 | Is the settlement-to-gross ratio estimate (CA3) acceptable as the basis of a labelled ESTIMATED cash forecast, or should the forecast stay unavailable until a deduction model is specified? (Recommendation: ship the labelled estimate.) |
| P3-3 | Duplicate-charge definition (LD1a) — same component and amount within one settlement, or across consecutive settlements too? (Taken: both, listed as candidates.) |
| P3-4 | `stale_days` default and the budget/health thresholds are configuration, provisional. |


---

## Implementation status — Phase 3b–3f (2026-10-22)

> **Finalization addendum (2026-10-22):** cost-ownership arbitration is now generic across advertising, packaging, storage, logistics and other (`cfo_costs`, `cost_owner_choice` widened by migration 0017), ledger `ALLOCATED_COST` is confirmable, and the "exclude both" conflict rule is replaced by "established source keeps counting, labelled" — see `cfo-expense-ledger.md` §14.2.1. The advertising-only `/cfo/ads/owner` route remains and writes the same table.

Stated plainly, including what is **not** built and where the build is narrower than the plan above. Tests named here are in the repository; counts are as of the last run recorded in the build log.

### Built and verified

| Sub-phase | Built | Verified by |
|---|---|---|
| **3b Advertising** | Ad reports ingest through a seller-confirmed mapping into `ad_report_line` (identity, exact repeat skipped, conflicting repeat rejected with the earlier figure standing, all-or-nothing); coverage from reports, pools and "no advertising" declarations; ownership arbitration with the seller's `cost_owner_choice`; planner metrics `AD_SPEND`, `ROAS`, `ACOS`, `TACOS` with status labels; Contribution Profit includes report spend only when the report owns advertising; routes `/cfo/ads/*`; migration 20261022_0015. | `test_ad_ingestion.py` (6), `test_ad_consolidation.py` (5), `test_cfo_ads.py` (13), executor unit tests |
| **3c Cash and payables** | Seller payables (`payable.supplier`, append-only, paid by superseding), settlement realisation ratio and lag from matched Meesho pairs, **estimated** expected receipts (lower-median ratio, half-up once) with `estimate_ref`, shortfall status per payable, overdue kept out of cover, planner metrics `EXPECTED_RECEIPTS` and `CASH_SHORTFALL_STATUS`, routes `/cfo/payables*`. | `test_settlement_realization.py` (7), `test_cfo_cash.py` (13) |
| **3d Claim lifecycle** | Forward-only, append-only seller-reported claim states per leak finding (migration 20261022_0016), Amazon withheld, claim draft text with identifiers only, routes `/cfo/leak-findings/{id}/claim*`. | `test_cfo_leak_claims.py` (27) |
| **3e CA export** | `/cfo/ca-export` returns an `.xlsx` workbook or a `.zip` of CSVs: Cover, P&L (components, Contribution Profit, operating profit with status), Expenses (by class, held and unclassified listed), GST summary (indicative), TCS/TDS schedule (tax assets, totals by code), Reconciliation (Amazon withheld), Exclusions & unavailable, Open data requests, Provenance. Disclaimer on every sheet; money as integer paise plus a display string. | `test_cfo_ca_export.py` (10) |
| **3f Proactive scan** | Deterministic rules (margin drop, stale or missing data, unconfirmed expenses, advertising source conflict, closing claim window, cash at risk), recorded as shared findings with fixed digit-free wording and engine-result references, de-duplicated by (rule, scope, read-model version); `POST /cfo/risk-scan`; an after-change hook (off by default). | `test_risk_rules.py` (4), `test_cfo_risk_scan.py` (15) |

### Narrower than the plan — open, not hidden

1. **3d: no new detections.** Duplicate charges, refund-without-credit and fee overcharge are already produced by `reconcile()` and `cfo/leak/classification.py` (categories `DUPLICATE_DEDUCTION`, `RETURN_NOT_CREDITED`, `FEE_OVERCHARGE`, …; mapping still PROVISIONAL, Q12). Phase 3d added the lifecycle and the claim text on top; it did not add detection rules, and the Q12 mapping remains unconfirmed.
2. **3b: no dedicated verified ad adapters** (decision AD1). The mapping path is the supported one. Advertising reconciliation against settlement charges is not built. Report spend is attributed per marketplace only; a SKU-narrowed profit with report spend is unavailable.
3. **3c: Meesho only.** Only the Meesho `line_ref` join is validated; Amazon and Flipkart are named as not projected. The forecast is an **estimate** from observed payouts, requires `CFO_PLANNER_CASH_MIN_SAMPLES` (10, provisional) settled lines, and is labelled ESTIMATED everywhere. Inventory commitments, working-capital ratios and the owner-account cash view are not built (the owner-drawing view is the planner's `EXPENSE_BY_CATEGORY` filtered to `OWNER_DRAWING`).
4. **3e:** no PDF, no GST return, no e-invoice data; the GST sheet is "indicative" (no rule data carries `CA_REVIEWED`). The pack is built on request; it is not cached.
5. **3f: cash `AT_RISK` is returned by the scan but not persisted** (the shared-finding contract has no kind for it). The after-change hook is **off by default** (`CFO_RISK_SCAN_ON_CHANGE`) because the scan assembles two months of order lines and its cost on large books is unmeasured; there is no time-based scheduler, no push delivery and no WhatsApp wiring. Health-band change, Brain-2 anomaly flags and budget overruns are not yet scan rules (they exist as strategic-briefing signals).
6. **Not built across Phase 3:** the ledger-to-Contribution-Profit resolver for `ALLOCATED_COST` (AC-L8), a UI for any of the above (dashboard track), and CA review of every tax-adjacent figure (PV-E1).
7. **Provisional configuration needing real-seller calibration:** coverage threshold, cash sample minimum, margin-drop points (2 / 5), stale days (14), and every component-code set.

### Acceptance

AC-B1…B7 ✔ · AC-C1…C6 ✔ (C2 for Meesho only) · AC-D2…D5 ✔ (AC-D1's detections pre-exist; see 1) · AC-E1…E6 ✔ · AC-F1…F5 ✔.
