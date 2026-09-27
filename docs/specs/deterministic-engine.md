# Metrion — Deterministic Engine Specification (Brain 1)

**Status:** Draft for review
**Prerequisite:** `docs/specs/data-foundation.md` — canonical model, `line_component`, validation layer, confidence levels, report periods
**Scope:** Net Realized Revenue, Contribution Profit, GST treatment, GST Applicability Lookup, manual corrections, provenance

**This engine contains no LLM.** It is a pure, versioned, deterministic function over the canonical model. Identical inputs must always produce identical outputs. The CFO agent *interprets* these numbers; it never computes them.

---

## 1. Confirmed decisions

Taken as settled. Not reopened in this document.

### 1.1 Revenue

```
  Gross Order Value
− Seller-funded discounts
− Cancellations
− Customer returns / refunds
− RTO-related unrecovered revenue
± Marketplace-funded discount treatment, by who actually bears the cost
= Net Realized Revenue
```

| # | Rule |
|---|---|
| R1 | Listed selling price and gross order value are never used as revenue. |
| R2 | Marketplace-funded discounts do **not** reduce seller revenue where the marketplace bears the cost. |
| R3 | Seller-funded discounts **do** reduce seller revenue. |
| R4 | Cancelled orders are not realized revenue. |
| R5 | Returns and refunds reverse or adjust revenue according to **actual marketplace settlement treatment**, not invoice state. |
| R6 | RTO separates **recovered inventory** from **unrecovered revenue**, and accounts for related logistics charges separately. |
| R7 | Seller input and correction is supported wherever marketplace data is incomplete. |
| R8 | Manual inputs are clearly labelled and **never silently overwrite source data**. |
| R9 | Every metric retains source, calculation basis, and confidence. |

### 1.2 Profit

```
  Net Realized Revenue
− COGS
− Marketplace Fees
− Shipping / Logistics
− Advertising Costs
− Return / RTO Losses
− Other Allocated Costs
= Contribution Profit
```

**Contribution Profit is distinct from accounting net profit.** It excludes overheads, depreciation, salaries, interest, and income tax. Every surface that displays it must label it as such.

### 1.2.0 Components added from the marketplace mapping document

Revised against `docs/Metrion_PnL_and_MTR_Mapping_FINAL.pdf`. These extend the template without altering its shape:

| Component | Treatment |
|---|---|
| **Packaging cost** | Promoted to an explicit P&L line. Previously folded into `OtherAllocatedCosts`. Sourced from the seller cost master, per unit. |
| **Reimbursements** | Marketplace compensation and credits. Distinct bucket — **not** a COGS reduction. |
| **Adjustments** | Other credits and debits. Preserve the raw description with the amount; never collapse into a generic fee line. |
| **Customer shipping income** | Customer-paid shipping, where the marketplace reports it as income rather than a deduction. |
| **Account-level charges** | Amazon `ServiceFee` and some `Adjustment`/`Transfer` rows carry no order id. Allocated per §5.10, never force-joined to a SKU. |
| **Transfers** | Movement between marketplace accounts. **Neither revenue nor expense.** Excluded from every P&L line. |

**New derived metrics:** `ROAS = ad-attributed sales / ad spend` · `ACOS = ad spend / ad-attributed sales` · `TACOS = ad spend / total sales`. All three require the advertising source, which is separate from settlement on all three marketplaces (C5).

### 1.2.1 Template status — formulas are not final

**This P&L structure is `formula_version = template.v1`.** It is a working first template, not a settled model. It will be revised once the CFO agent is built and validated against real seller data and better-established formulas.

Consequence for implementation: **formulas must not be hardcoded.** See §4.1.

### 1.3 GST

Management-grade decision support. **Not filing-grade software.**

Included: GST-inclusive/exclusive normalisation · IGST / CGST / SGST handling · TCS and TDS visibility · indicative tax summary.

Excluded — and never implied: statutory filing · guaranteed compliance · final ITC eligibility determination.

### 1.4 GST Applicability Lookup

On-demand web research returning likely rate, likely HSN/category, source URL, retrieval date, ambiguity note, and a professional-verification disclaimer. Stored as provisional external knowledge. **Never silently treated as confirmed accounting fact.**

---

## 2. Design decisions requiring review

These are **my recommendations**, not settled decisions. Each is listed again in §14.

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Revenue recognition point | Dual-state: **Recognised** at invoice/dispatch, **Realized** at settlement | "Realized" honestly means settled. Recognising at invoice gives timely numbers; the delta between the two *is* the Leak Shield signal. |
| D2 | Unknown discount bearer | Default to **seller-borne** (reduces revenue), flagged and overridable | Overstating profit causes bad inventory and pricing decisions. Understating is recoverable. |
| D3 | Costing method | **Weighted average cost per SKU**, effective-dated | FIFO needs lot tracking that upload-only data cannot supply. |
| D4 | Profit basis | **Tax-exclusive throughout** — revenue ex-GST, fees ex-GST | Output GST is collected on the government's behalf, not earned. Fee GST is usually creditable. |
| D5 | Fee GST treatment | Separate line: *"GST on fees (potentially creditable)"*, with a toggle to treat it as a cost | Respects §1.3 — we show it without ruling on ITC eligibility. |
| D6 | TCS / TDS | **Cash-flow items, not P&L items.** Excluded from Contribution Profit | They are prepaid taxes recoverable against the seller's liability, not costs. Sellers routinely misread these as losses. |
| D7 | Account-level cost allocation | By **net revenue share**, configurable; result always `DERIVED` | Revenue share is the least-wrong default for ads and storage. |
| D8 | Rounding | Integer paise, half-up; allocations reconciled by **largest-remainder** | Components must sum exactly to their stated total. |

---

## 3. Unverified assumptions

Carried forward or newly introduced. All inherit `PROVISIONAL` confidence.

| # | Assumption | Basis | Risk if wrong |
|---|---|---|---|
| A1 | ~~Prices are tax-exclusive~~ | **RESOLVED — and the answer is that it varies.** Not a single basis. **Meesho is explicitly inclusive** (`Listing Price (Incl. taxes)`, `Fixed Fee (Incl. GST)`, `Warehousing fee (incl GST)`, `Return premium (incl GST)`). **Amazon MTR supplies both** (`Invoice Amount` and `Tax Exclusive Gross`). Basis must be declared **per marketplace and per field**, never per source. See §8.1. | Resolved |
| A2 | `Marketplace Fee Amount` and `Platform Fee` on Amazon are distinct charges | Both ₹50 in row 1 — may be one charge represented twice | **High.** Double-counts directly into profit. |
| A3 | ~~Meesho three-discount overlap~~ | **Superseded.** Those columns were synthetic. Real Meesho revenue fields are `Listing Price (Incl. taxes)` and `Supplier Listed Price (Incl. GST + Commission)`. | Superseded |
| A4 | `Item Promotional Discount` (Amazon) is marketplace-funded | Name only | Medium — shifts revenue by the discount amount |
| A5 | ~~Flipkart discount bearer~~ | **RESOLVED from source data.** The real Sales Report splits `Total Discount` into **`Seller Share`** (seller-funded) and **`Bank Offer Share`** (not seller-funded). Bearer is read, not inferred — D2's fallback is not needed for Flipkart. | Resolved |
| A6 | ~~Cancellation representation~~ | **RESOLVED for Meesho.** `Reason for Credit Entry` carries real values `DELIVERED`, `CANCELLED`, `RTO_COMPLETE`, `DOOR_STEP_EXCHANGED`. Amazon and Flipkart equivalents still to be confirmed from their real exports. | Partly resolved |
| A7 | ~~RTO representable~~ | **RESOLVED for Meesho.** `RTO_COMPLETE` in `Reason for Credit Entry`; `Live Order Status` = `RTO` confirmed on a real row. The inventory-recovered / damaged / lost split (§5.7) still requires seller input — no marketplace reports condition of returned goods. | Partly resolved |
| A8 | Quantity-level fees are per-line, not per-unit | All reference rows have `Quantity = 1` | Medium — mis-scales fees on multi-unit lines |
| A9 | Settlement rows are per-line and joinable | Reference files are pre-joined | Medium |

---

## 4. Determinism contract

| Rule | Requirement |
|---|---|
| **Purity** | No LLM, no network, no randomness inside calculation. **No implicit clock reads** — a calculation that depends on the current date takes `as_of_date` as an explicit parameter (§4.2). Reading the clock inside a calculation is forbidden; receiving a date is not. |
| **Reproducibility** | `(canonical_data_version, manual_adjustment_set, formula_version, config_version, as_of_date) → identical output`. See §4.2. |
| **Versioning** | `formula_version` is stamped on every stored result. Formula changes never mutate historical results; they produce a new calculation run. |
| **Re-runnability** | Results are derived artefacts. They may always be recomputed from canonical data plus adjustments. |
| **Integer money** | All arithmetic in signed `BIGINT` paise, seller perspective (§data-foundation 1.1). |
| **No silent defaults** | Any absent input either blocks the metric or produces an explicitly flagged `DERIVED` value. Never a silent zero. |

**A missing input is not zero.** Absent COGS makes Contribution Profit *unavailable*, not equal to Net Revenue.

### 4.1 Formulas are definitions, not code

Per §1.2.1, every metric in §5 is expressed as a **versioned formula definition** — a named composition of canonical components — held in a definition store, not inlined into calculation code.

| Rule | Requirement |
|---|---|
| F1 | A metric is a named composition of `component_code` terms, operators, and conditions. No metric's structure is expressed in imperative code. |
| F2 | Changing a formula creates a **new version**. Definitions are immutable once used to produce a stored result. |
| F3 | Every `metric_result` records the `formula_version` that produced it. Historical results are never recomputed silently. |
| F4 | Coefficients, tolerances, allocation bases, bearer mappings, and fee treatments are **configuration**, never constants. |
| F5 | A formula version may be evaluated against historical data to compare models — without replacing stored results. |
| F6 | Determinism (§4) is preserved: a definition plus its inputs is still a pure function. |

**Why:** the current structure is a first template. When the CFO agent is built and real formulas are validated, the change must be a new definition version and a re-run — not a code rewrite and a migration.

### 4.2 `as_of_date` — time as an input, never a read

Some figures are inherently relative to a moment: a finding's age, whether a claim window is closing, whether a settlement is overdue. These stay deterministic **provided the moment is an input**.

| Rule | Requirement |
|---|---|
| T1 | Any calculation depending on the current date declares `as_of_date` as an explicit parameter. |
| T2 | The caller supplies it. The engine never calls `now()`, `CURRENT_DATE` or equivalent inside a calculation path. |
| T3 | `as_of_date` is stamped on the result alongside `formula_version` and `config_version`. |
| T4 | Reproducibility holds on the extended tuple: `(canonical_data_version, manual_adjustment_set, formula_version, config_version, as_of_date)`. |

This keeps AC2 intact — no calculation path invokes a clock — while making age, window status and overdue detection computable in Brain 1 rather than stranded between brains.

### 4.3 `canonical_data_version` — derivation

Referenced by the reproducibility tuple in §4 but not itself defined anywhere in
`data-foundation.md`. **It is derived, never stored upstream:**

```
canonical_data_version = sha256(
  sorted(ingestion_run.id for every ingestion_run in scope),
  sorted(f"{adapter_id}:{adapter_version}" for every adapter involved),
  sorted(manual_adjustment.id for every ACTIVE adjustment in scope)
)
```

Computed at `compute_metric()` time from whatever is actually in scope for that calculation,
sorted before hashing so the result does not depend on database row order (required for AC1).
Stamped on the `metric_result` as an opaque text value — it is a fingerprint of the inputs,
not a foreign key, and `data-foundation.md` should not be assumed to expose a matching field.

---

## 5. Formulas

Notation: `Σ[code]` sums `line_component.amount` for that `component_code`; `side` is `INVOICE` or `SETTLEMENT`.

### 5.1 Recognition states (D1)

| State | Basis | Available for |
|---|---|---|
| `RECOGNISED` | Invoice-side components only | All marketplaces |
| `REALIZED` | Settlement-side where present, invoice-side otherwise | Flipkart, Meesho |
| `UNAVAILABLE` | Required settlement data absent for the period in question | Any marketplace where the seller has not uploaded a settlement report |

Every figure is labelled with its state.

**Amazon status (corrected).** `data-foundation.md` §0.6 and §2.3 register `amazon.settlement.v2` as **specified** from Amazon SP-API documentation, so Amazon is **not** categorically excluded from `REALIZED`. What remains open is narrower and is tracked at §11: the settlement **match keys** are unverified, and no real Amazon export has yet validated the adapter. Until those close, Amazon periods report `RECOGNISED` **because the data has not been validated**, not because the report family does not exist.

### 5.2 Gross Order Value

```
GrossOrderValue(line) = Σ[gross_item_amount]           -- pre-discount, normalised to tax-exclusive per §8.1
```

### 5.3 Discount attribution (R2, R3, D2)

Every discount component carries a `bearer`:

| `bearer` | Effect on Net Realized Revenue |
|---|---|
| `SELLER` | Reduces |
| `MARKETPLACE` | **No effect.** Disclosed separately. |
| `UNKNOWN` | Treated as `SELLER`, flagged `DERIVED`, seller-overridable (D2) |

```
SellerFundedDiscounts(line) =
    Σ[SELLER_DISCOUNT]
  + Σ[SHIPPING_DISCOUNT   where bearer = SELLER]
  + Σ[PLATFORM_DISCOUNT   where bearer = SELLER]     -- misnamed at source; bearer governs
  + Σ[CASHBACK_DISCOUNT   where bearer = SELLER]
  + Σ[* where bearer = UNKNOWN]                       -- conservative default

MarketplaceFundedDiscounts(line) = Σ[* where bearer = MARKETPLACE]   -- disclosure only
```

**Bearer is a property of `(marketplace, component_code)`, resolved from a configuration table** — never hardcoded, and per data-foundation, never inferred. Initial values are assumptions A4/A5.

That configuration table is `discount_bearer_config`:

```sql
discount_bearer_config (
  id uuid pk, tenant_id uuid,            -- null = platform default
  marketplace text not null,
  component_code text not null,
  bearer text not null,                  -- SELLER | MARKETPLACE | UNKNOWN
  source text not null,                  -- where the mapping came from
  confidence text not null,
  effective_from date not null,
  version int not null,
  unique (tenant_id, marketplace, component_code, effective_from)
)
```

Resolution order: a tenant-specific row, if any, overrides the platform default for the same
`(marketplace, component_code)` as of the observation date; where no row exists at all,
`bearer = UNKNOWN` and D2's fallback applies. This is engine-owned configuration — it does
not require a `bearer` column on `line_component` (`data-foundation.md` §1.4 has none;
Flipkart's `Seller Share`/`Bank Offer Share` are already bearer-split at the source and never
consult this table at all, per A5).

### 5.4 Revenue reductions

```
CancellationReversal(line)  = GrossOrderValue  where state = CANCELLED            -- blocked, A6
ReturnReversal(line)        = refunded_amount  per settlement treatment (R5)
RTOUnrecoveredRevenue(line) = GrossOrderValue − SellerFundedDiscounts             -- where RTO, never settled (A7)
```

### 5.5 Net Realized Revenue

```
NetRealizedRevenue(line) =
      GrossOrderValue
    − SellerFundedDiscounts
    − CancellationReversal
    − ReturnReversal
    − RTOUnrecoveredRevenue
```

Marketplace-funded discounts appear in no term (R2).

### 5.6 Cost components

| Component | Source | Confidence |
|---|---|---|
| `COGS` | Seller cost master, weighted average, effective-dated (D3) | `MANUAL` |
| `MarketplaceFees` | `Σ[FEE where side = settlement, else invoice]`, tax-exclusive | `PROVISIONAL` |
| `ShippingLogistics` | `Σ[LOGISTICS_FEE, SHIPPING_CHARGE(seller-borne)]` | `PROVISIONAL` |
| `AdvertisingCosts` | Seller-entered; allocated if account-level (D7) | `MANUAL` / `DERIVED` |
| `ReturnRTOLosses` | §5.7 | `DERIVED` |
| `OtherAllocatedCosts` | Seller-entered; allocated (D7) | `MANUAL` / `DERIVED` |

**Absent `expense.advertising` — CONFIRMED (Category E).** Unlike `COGS` (a cost every sold
unit definitely incurred, whether or not its value is known — absence is `UNAVAILABLE`),
advertising spend is opt-in seller-declared data: a seller who ran no ads for a scope simply
never enters an adjustment for it. No `expense.advertising` adjustment covering a
SKU/period/account therefore resolves to `AdvertisingCosts = 0` for that scope, not
`UNAVAILABLE` — the same treatment already given to a line with no `DISCOUNT` component
present. This does not extend to `COGS`, which remains `UNAVAILABLE` when absent.

```
COGS(line) = weighted_average_cost(sku, as_of = document_date) × billable_quantity

billable_quantity = quantity
                  − returned_qty_all_outcomes
                  − rto_qty_all_outcomes
```

**Corrected from an earlier draft that excluded only sellable-recovered quantity.** Standard
inventory accounting reverses `COGS` for a returned/RTO'd unit regardless of outcome —
recovered-sellable inventory reverses it to zero (R6: the goods remain saleable, no cost
consumed); damaged or lost inventory is *also* removed from ordinary `COGS` and its cost moved
wholesale into `ReturnRTOLosses` (§5.7) as a distinct, visible loss line, never left inside
blanket `COGS`. `billable_quantity` therefore excludes **every** returned/RTO'd unit
regardless of its outcome — never only the recovered-sellable portion — so a unit's cost lands
in exactly one place: nowhere (recovered) or `ReturnRTOLosses` (damaged/lost), never both. The
earlier wording, if implemented literally, would have double-counted a damaged/lost unit's
cost into both `COGS` and `ReturnRTOLosses` simultaneously.

**Logistics components on a return/RTO line belong to `ReturnRTOLosses` (§5.7), never to
`ShippingLogistics`.** A `LOGISTICS_FEE`/`SHIPPING_CHARGE` component on a line whose
`return_status`/`rto_outcome` is non-null is excluded from `ShippingLogistics` and counted
only in §5.7's forward/reverse logistics terms — otherwise the same charge would be summed
into both components.

### 5.7 Return and RTO losses (R6)

```
ReturnRTOLosses(line) =
      COGS_of_unrecovered_or_damaged_units
    + forward_logistics_incurred_on_failed_delivery
    + reverse_logistics_charged
    + non_refunded_fees_retained_by_marketplace
```

The three RTO outcomes are accounted separately:

| Outcome | Revenue | COGS | Logistics |
|---|---|---|---|
| Inventory recovered, sellable | Unrecovered | Not consumed | Forward + reverse charged |
| Inventory recovered, damaged | Unrecovered | Fully consumed | Forward + reverse charged |
| Inventory lost in transit | Unrecovered | Fully consumed | Forward charged |

### 5.8 Contribution Profit

```
ContributionProfit =
      NetRealizedRevenue
    − COGS
    − MarketplaceFees
    − ShippingLogistics
    − AdvertisingCosts
    − ReturnRTOLosses
    − OtherAllocatedCosts
```

Reported alongside:

```
ContributionMargin% = ContributionProfit / NetRealizedRevenue × 100
```

Undefined — never zero — when `NetRealizedRevenue = 0`.

### 5.9 Tax treatment (D4, D5, D6)

**Excluded from Contribution Profit:**

| Item | Reason |
|---|---|
| Output GST (CGST/SGST/IGST/UTGST/Cess) collected | Collected for the government; never seller revenue |
| TCS | Prepaid tax credited to the seller's account — **not a cost** (D6) |
| TDS | Same (D6) |

**Shown separately:**

```
GSTOnFees_PotentiallyCreditable = Σ[line_component.tax_amount where kind = FEE]
```

Displayed as a distinct line with the §1.3 disclaimer. A seller who cannot claim ITC (e.g. composition scheme) may toggle it into `OtherAllocatedCosts`; the toggle is recorded as a manual input (§7).

TCS and TDS appear in cash-flow and settlement reconciliation views only, where they explain the gap between Contribution Profit and money received.

### 5.10 Allocation (D7)

```
allocated_cost(line) = pool_amount × ( NetRealizedRevenue(line) / Σ NetRealizedRevenue(pool_scope) )
```

- Allocation basis is configurable: `NET_REVENUE` (default) · `UNITS` · `ORDERS`.
- Every allocated figure is `DERIVED` and names its basis on display.
- Remainders are distributed by **largest remainder** so allocations sum exactly to the pool (D8).
- Lines with zero or negative net revenue are excluded from a `NET_REVENUE` basis and reported as unallocated.

### 5.11 Rounding (D8)

Half-up at paise. Rounding occurs **once**, at the final presented figure — never on intermediates. Aggregates are computed from unrounded intermediates, then rounded, so displayed components always reconcile to displayed totals.

---

### 5.12 Leak Shield — ownership across the three brains

Leak Shield's *powers* sit with the **CFO agent**. Its *arithmetic* does not.

| Brain | Responsibility |
|---|---|
| **Brain 1** (this document) | Reconciliation arithmetic, margin computation, variance against configured tolerance, fee-delta calculation (`data-foundation` §5.4) |
| **Brain 2** | Anomaly detection, outlier scoring, trend deviation — statistical at V1 |
| **Brain 3 / CFO agent** | Interpretation, explanation, recommended action, and **prioritisation as judgement** — which finding matters most to this seller and why. **Ranking is not judgement:** ordering by amount, age or window status is arithmetic and is computed deterministically in Brain 1. Brain 3 narrates the computed order and may argue about it; it never produces it. |

CFO never recomputes a figure Brain 1 has produced. It explains it.

**Reconciliation inputs:** transactions, orders, settlements, returns, and — where the seller supplies the data — logistics. Seller-supplied logistics is a manual input (§7) and never overwrites source data.

**Compute-intensity note (not a metering decision):** CFO is the most deterministic agent in the system; its model cost is explanation-only and does not scale with seller data volume. This is a technical characteristic recorded for the future billing specification, which owns the meter. **No metering basis, unit or prohibition is established by this spec.** See `cfo-agent.md` §7.3.3.

### 5.12.1 Reconciliation tolerance configuration — CONFIRMED (Category C)

`data-foundation.md` §5.5 requires variance tolerance, settlement lag and grace period to be
**configuration, never hardcoded** (F4), but defines neither their schema nor how a
paise-tolerance and a basis-points-tolerance combine when both are configured for the same
`(marketplace, component_code)`. Both are resolved here, since this engine owns every
configuration table F4 requires (mirrors `discount_bearer_config`, §5.3).

**Confirmed decision — tolerance combination:** a variance is `MATCHED_WITHIN_TOLERANCE` if it
satisfies **either** the paise tolerance **or** the basis-points tolerance (computed against
the invoice-side amount) — not both. This is the more lenient of the two, deliberately: it
absorbs small flat-paise rounding noise on large lines and small percentage noise on small
lines without a seller-visible false-positive leak on either end. A variance failing both is
`VARIANCE_EXCEEDS_TOLERANCE`.

```sql
reconciliation_tolerance_config (
  id uuid pk, tenant_id uuid,            -- null = platform default
  marketplace text not null,
  component_code text not null,          -- or '*' for a marketplace-wide default
  tolerance_paise bigint not null,
  tolerance_bps int not null,            -- basis points of the invoice-side amount
  settlement_lag_days int not null,      -- WITHIN_LAG vs BEYOND_LAG threshold
  grace_period_days int not null,        -- additional buffer before BEYOND_LAG is reported as a leak
  effective_from date not null,
  version int not null,
  unique (tenant_id, marketplace, component_code, effective_from)
)
```

Resolution order mirrors `discount_bearer_config` (§5.3): a tenant-specific row overrides the
platform default for the same `(marketplace, component_code)`; where neither a specific nor a
`'*'` row exists, tolerance resolution fails and the line's reconciliation outcome is
`UNAVAILABLE` — never a silently-assumed zero tolerance (which would over-report leaks) or an
silently-assumed infinite tolerance (which would hide them).

**Settlement lag / grace period semantics — CONFIRMED:** an unsettled invoice line is
`UNSETTLED_WITHIN_LAG` while `days_since(document_date, as_of_date) <= settlement_lag_days`,
becomes `UNSETTLED_BEYOND_LAG` once that threshold is crossed, but is only surfaced as a
reportable leak exception once `days_since(...) > settlement_lag_days + grace_period_days` —
the grace period is a reporting buffer on top of the lag threshold, not a second lag.

### 5.12.2 Join-key confidence cap for `reconcile()` — CONFIRMED design decision (Amazon/Flipkart extension, this session)

`data-foundation.md` §5.1.5 designs how `reconcile()` extends from Meesho-only matching to also
run against Amazon and Flipkart, given that neither marketplace's join key (`order_ref` alone,
per §5.1.5) has been validated against a real populated export, unlike Meesho's `line_ref`
(`sub_order_num`, VERIFIED). This subsection is the confidence consequence of that extension —
the single most important part of this design, since a Leak Shield finding presented with
unwarranted confidence on an unvalidated join is exactly the kind of thing that erodes seller
trust (`CLAUDE.md`: "a number a seller cannot trace is worse than no number at all").

**The problem this closes.** `combine_confidence` (`data-foundation.md` §7.1) already folds the
matched `sales_line`'s and `settlement_line`'s own row-level confidence (field-mapping
confidence — is this column's meaning trustworthy) into `reconciliation_match.confidence`. That
is a **different axis of uncertainty** from "is the join key itself correct" — a match's
component-amount mapping can be perfectly trustworthy while the row it was joined to is still
only a guess about which order/line it actually belongs to. Folding both into one confidence
value without a second signal would let an Amazon/Flipkart match happen to read the same
confidence as a Meesho one whenever both marketplaces' underlying rows carry the same
field-mapping confidence — exactly the unwarranted-confidence risk this subsection exists to rule
out.

**Mechanism — both a confidence cap and an explicit flag, not one alone.**

1. **Confidence cap.** `reconcile()` gains a second, explicit per-marketplace lookup — a
   join-key confidence, distinct from any row's field-mapping confidence:

   | Marketplace | Join-key confidence | Basis |
   |---|---|---|
   | Meesho | `VERIFIED` | `line_ref` (`sub_order_num`) is `data-foundation.md` §5.1's VERIFIED key. |
   | Amazon | `PROVISIONAL` | `order_ref`-only key, specified-but-unvalidated (§5.1, §5.1.2, §5.1.5). |
   | Flipkart | `PROVISIONAL` | `order_ref`-only key, specified-but-unvalidated (§5.1, §5.1.3, §5.1.5). |

   This value is folded into **every** confidence `reconcile()` produces for that marketplace's
   run — `reconciliation_match.confidence`, and every `reconciliation_exception.confidence` /
   `LEAK_EXCEPTION_AMOUNT` `metric_result.confidence`, from **both** Path A and Path B (§5.8) —
   via the same, already-existing `combine_confidence` call, with the marketplace's join-key
   confidence added as one more input alongside the row(s)' own confidence. Because
   `combine_confidence` is monotonic (weakest input wins, `data-foundation.md` §7.1), an
   Amazon/Flipkart match or exception can **never** present as better than `PROVISIONAL`,
   regardless of how strong the underlying `sales_line`/`settlement_line` field-mapping
   confidence is or later becomes. Path B is included deliberately, not only amount-bearing
   Path A outcomes: `UNSETTLED_BEYOND_LAG`'s determination that "no settlement was found" is
   itself dependent on the same unvalidated join key correctly resolving zero candidates — an
   unvalidated key can produce a false negative (a real settlement exists but the candidate key
   failed to find it) just as it can produce a false positive collision, so the cap applies
   uniformly to everything a non-Meesho run of `reconcile()` produces, not selectively.

2. **Explicit flag, not confidence alone.** Confidence alone conflates two different reasons a
   figure might read `PROVISIONAL` — an unverified column mapping, or an unvalidated join key —
   and the CFO agent (`cfo-agent.md`) needs to explain *which* to the seller, not merely disclose
   that some caveat exists (an LLM may narrate a number's caveat but must be given the caveat's
   real reason to narrate, never infer one, per `CLAUDE.md`'s "LLMs explain numbers, they never
   compute them"). `reconciliation_run.join_key_validated` (`data-foundation.md` §5.9, added this
   session) is the explicit, queryable flag: `true` for Meesho, `false` for Amazon/Flipkart,
   fixed for a run's whole lifetime (a run's `marketplace` never changes mid-run) and therefore
   deliberately **not** duplicated onto every child `reconciliation_match`/`reconciliation_exception`
   row — consumers join back to the parent run.

**Net effect, stated precisely.** An Amazon or Flipkart `reconciliation_match`/
`reconciliation_exception` produced under this design is real output, computed by the same
deterministic arithmetic as a Meesho one, but (a) can never present with confidence better than
`PROVISIONAL`, and (b) is always distinguishably flagged as `join_key_validated = false` at its
run, so any consumer — CFO's leak-ranking, a seller-facing caveat, a future audit — can tell
"matched, but on an unvalidated key" apart from an ordinary match without having to infer it from
confidence level alone (confidence `PROVISIONAL` has other, unrelated causes too — e.g. every row
in this codebase today is at best `PROVISIONAL` regardless of marketplace, `data-foundation.md`
§7.1 — so confidence alone is not a reliable signal of *this specific* caveat).

**What this does not do.** Neither the confidence cap nor the flag upgrades Amazon's or
Flipkart's join key from *specified-but-unvalidated* to *validated* (`data-foundation.md` §5.1's
status table is unchanged) — it only ensures the output produced against that unvalidated key is
never mistaken, by confidence level or by silence, for output produced against a validated one.

---

### 5.13 Estimated competitor margin range (extension for observed inputs)

Added per C17 / B1 of `competitor-intelligence-agent.md`. **CI supplies observations; this engine performs every calculation.**

This is an **estimation** interface, explicitly weaker than §4's determinism contract. Scraped observations are not part of `canonical_data_version`, so a range computed here is reproducible only for a **fixed observation set**, not across re-captures. It is labelled accordingly and never enters a canonical `metric_result`.

```
estimate_competitor_margin_range(
  CompetitorObservationSet {
    marketplace, category,
    observed_price_paise, visible_discount_paise, mrp_paise,
    variant_key, source_url, fetched_at, confidence
  }
) -> {
  estimate_ref,                     -- competitor_estimate.id (§9.1)
  low_paise, high_paise,
  confidence: DERIVED,              -- never better; monotonic rule applies
  basis,                            -- human-readable summary
  assumptions[],                    -- every fee reference used, and every gap
  fee_reference_version,            -- §5.14
  formula_version, config_version,
  observation_ref                   -- source_url + fetched_at
}
```

**Rules**

| # | Rule |
|---|---|
| 1 | The caller passes **no rates and no fee amounts.** The engine resolves them from §5.14. |
| 2 | Output is always a **range**, never a point value. A competitor's COGS, fee tier and ad spend are unobservable. |
| 3 | Where a fee reference is missing, the range **widens** and the gap is named in `assumptions[]`. The figure is never suppressed and never silently defaulted. |
| 4 | Results are labelled *estimated margin range* everywhere they surface. |
| 5 | Never written to `metric_result` (§9) — this is an estimate about a third party, not a figure about the seller's business. |

### 5.13.1 Interfaces consumed by agents

Named here so no agent delegates to a capability this spec does not define.

| Interface | Returns | Notes |
|---|---|---|
| `compute_metric(metric_code, grain, target, period)` | `metric_result` | The general entry point (§9) |
| `reconcile(period, marketplace, tolerance_ref)` | `reconciliation_exception[]` + a `metric_result` for each aggregate | Tolerances resolve from configuration, never constants (F4). Model defined in `data-foundation.md` §5; `reconciliation_run`/`reconciliation_match`/`reconciliation_exception` migrations are calc-engine-owned (`data-foundation.md` §5.7, confirmed Phase C, same precedent as `metric_result`). Schema and outcome-to-table mapping: `data-foundation.md` §5.9. **Built (Meesho only so far)**: `calc_engine.api.reconcile.reconcile` (`packages/calc-engine/src/calc_engine/api/reconcile.py`) — real Postgres-integration-tested against real Meesho export data, `packages/calc-engine/tests/integration/test_reconcile_real_meesho_data.py`. **Amazon/Flipkart extension designed, not yet built**: per-marketplace join key, join-key confidence cap and flag, and Amazon's amount-gap handling are specified in `data-foundation.md` §5.1.5 and §5.12.2 above — a following checkpoint implements this against `reconcile.py`/`leak.py`; running it against Amazon/Flipkart today does not upgrade either marketplace's join key past *specified-but-unvalidated* (`data-foundation.md` §5.1). |
| `landed_cost(manual_adjustment_ref, sku, quantity)` | `metric_result`, `metric_code = LANDED_COST_PER_UNIT` | Unit cost + shipping + duties, per the referenced `supplier.quote`. Consumed by supplier ranking and batch size |
| `leak_aggregate(period, marketplace, grouping)` | `metric_result`, `metric_code = LEAK_TOTAL` | Sums reconciliation exception amounts. **Agents never sum leak amounts themselves** |
| `estimate_competitor_margin_range(...)` | `competitor_estimate` | §5.13; carries an `estimate_ref`, never an `engine_result_ref`. **CI-exclusive** — no other agent surface reads or writes `competitor_estimate` |
| `estimate_product_feasibility(...)` | `product_feasibility_estimate` | §5.13.2; carries its own `estimate_ref`. **PI-exclusive** — distinct table from `competitor_estimate`, never used for a seller's own SKU (use `margin_curve` instead) |
| `margin_curve(sku, candidate_prices[], period, as_of_date)` | `metric_result[]`, `metric_code = MARGIN_AT_PRICE` | **CFO-exclusive** — requires an owned `sku` with COGS history. One result per candidate price. Fees resolve from §5.14. Backs the pricing recommendation. Never callable for a product the seller does not yet own — see §5.13.2 for that case |
| `cash_reconciliation(period, marketplace, as_of_date)` | `metric_result[]` — `CASH_EXPECTED`, `CASH_RECEIVED`, `CASH_VARIANCE` | Settlement-based; also surfaces TCS/TDS as cash items, never P&L |
| `rank_findings(exception_ids[], as_of_date, severity_config_ref)` | ordered list + `metric_result` per finding — `FINDING_AGE_DAYS`, `FINDING_SEVERITY` | Deterministic ranking and severity (§5.14.1). Takes `as_of_date` per §4.2 |
| `funding_readiness_metrics(period_range, as_of_date)` | `metric_result[]` — `MARGIN_STABILITY`, `REVENUE_CONCENTRATION`, `CASH_CONVERSION_DAYS` | Inputs to the funding-readiness report. Emits no score |
| `resolve_fee_reference(marketplace, category, fee_type, as_of_date)` | `fee_reference` row or a declared gap | §5.14. A miss is reported, never defaulted to zero |
| `compute_price_positioning(sku, seller_price_paise, competitor_prices[], as_of_date)` | `metric_result[]`, `metric_code = PRICE_POSITIONING` | §5.15. Pure price-fact comparison — no COGS, no fee resolution. Competitor prices enter `DERIVED` per the CI boundary |
| `compute_repricing_scenario(sku, seller_price_paise, competitor_prices[], stance, stance_param, as_of_date)` | `metric_result[]`, `metric_code = REPRICING_SCENARIO` | §5.15. Pure price arithmetic — explicitly not margin-aware; distinct from `margin_curve` |
| `compute_price_band(product_ref, category, competitor_prices[], as_of_date)` | `metric_result[]`, `metric_code = PRICE_BAND` | §5.15.1. Quartile/IQR distribution over CI-supplied competitor prices. Requires **at least 3** prices, else `UNAVAILABLE` with a named reason. Competitor prices enter `DERIVED` per the CI boundary |

`metric_code` is extended accordingly: `LANDED_COST_PER_UNIT`, `LEAK_TOTAL`, `LEAK_EXCEPTION_AMOUNT`, `MARGIN_AT_PRICE`, `CASH_EXPECTED`, `CASH_RECEIVED`, `CASH_VARIANCE`, `FINDING_AGE_DAYS`, `FINDING_SEVERITY`, `MARGIN_STABILITY`, `REVENUE_CONCENTRATION`, `CASH_CONVERSION_DAYS`, `PRICE_POSITIONING`, `REPRICING_SCENARIO`, `PRICE_BAND`.

**Reconciliation exceptions produce `metric_result` rows** under `metric_code = LEAK_EXCEPTION_AMOUNT`, one per exception. Each amount is therefore citable by `engine_result_ref`, which is what makes `leak_finding.engine_result_ref` satisfiable.

### 5.13.2 Prospective product feasibility estimate (PI candidates)

For a product a seller does **not yet own** — a discovered candidate with no seller `sku`, no owned COGS history, and no `metric_result` lineage — feasibility is estimation, on the same footing as §5.13's competitor estimate, and for the same reason: the inputs are observed or assumed, not canonical. **`margin_curve` is reserved for the seller's own SKU** (`cfo-agent.md` §6.7) and must never be used for a candidate the seller has not committed to buying.

```
estimate_product_feasibility(
  ProspectiveObservationSet {
    marketplace, category,
    candidate_prices[],
    stated_cogs_paise,                -- OPTIONAL. Only ever a value the seller stated, sourced from a
                                       -- `supplier.quote` manual_adjustment. Never derived, estimated,
                                       -- or supplied by PI itself — see `product-intelligence-agent.md` §6.7.
    budget_paise, as_of_date,
    source_url, fetched_at, confidence         -- always DERIVED at this boundary, same rule as §5.13
  }
) -> {
  estimate_ref,                     -- product_feasibility_estimate.id — NEVER an engine_result_ref
  feasible_price_range_low_paise, feasible_price_range_high_paise,
  cogs_basis,                       -- STATED (seller quote used) | UNKNOWN (no quote — see rule 6 below)
  assumptions[],                    -- every fee reference used, and every gap, including a missing COGS
  fee_reference_version,
  formula_version, config_version,
  observation_ref
}
```

**Rules**, identical in spirit to §5.13, plus one addition for the no-quote case:

1. Output is always a range, never a point value.
2. A missing fee reference widens the range and names the gap rather than suppressing the figure or defaulting to zero.
3. The result is never written to `metric_result`.
4. Every rendering is labelled an estimate.
5. **The caller supplies `stated_cogs_paise` or omits it — the engine never asks PI to estimate a cost, and PI never does.** The only legitimate source of a real cost figure is a seller-declared `supplier.quote`.
6. **Where `stated_cogs_paise` is absent, `cogs_basis = UNKNOWN`** and the range reflects **price and fee spread only, explicitly stating that no cost basis was available** — this is not the same claim as a margin estimate, and every rendering must carry that distinction so it is never mistaken for one.

**This is a distinct surface from `competitor_estimate` (§5.13).** A prospective-product feasibility estimate and a competitor margin estimate answer different questions and must not share a table or a reference type — an agent that needs one must not reach for the other. `landed_cost` (§5.13.1) may still be called directly where a seller has an actual `supplier.quote` for the candidate; this interface is for the general case where no quote exists yet.

```sql
product_feasibility_estimate (
  id uuid pk, tenant_id uuid not null,
  low_paise bigint not null, high_paise bigint not null,
  confidence text not null,               -- DERIVED, never better
  basis text not null, assumptions jsonb not null,
  fee_reference_version int not null,
  observation_ref jsonb not null,
  formula_version text not null, config_version text not null,
  computed_at timestamptz not null
)
```

### 5.14 Fee reference store (C18 / B9)

Versioned, backend-managed configuration consumed by this engine. **No agent holds fee rates**, satisfying F4 and readiness 2B.4.

```sql
fee_reference (
  id uuid pk,
  marketplace text not null,
  category text not null,
  fee_type text not null,             -- COMMISSION | FIXED | COLLECTION | LOGISTICS | ...
  rate_pct numeric(7,4),              -- point rate, or
  rate_low_pct numeric(7,4), rate_high_pct numeric(7,4),   -- range
  effective_from date not null, effective_to date,
  source text not null,               -- where the rate came from
  confidence text not null,
  version int not null,
  last_verified_at timestamptz not null
)
```

Resolution is by `(marketplace, category, fee_type)` effective at the observation date. A miss is reported as a gap, never defaulted to zero. `fee_reference_version` is stamped on every estimate so a later rate change never silently alters a past result.

### 5.14.1 Severity and ranking configuration (A4)

Severity bands are **configuration, never constants** (F4), resolved by `rank_findings`.

```sql
severity_config (
  id uuid pk, tenant_id uuid,            -- null = platform default
  metric text not null,                  -- AMOUNT_PAISE | AGE_DAYS | WINDOW_DAYS_REMAINING
  high_threshold bigint, medium_threshold bigint,
  window_closing_soon_days int not null default 14,
  ordering_basis text not null,          -- WINDOW_THEN_AMOUNT (default) | AMOUNT_ONLY
  version int not null, effective_from date not null
)
```

`window_status` derives from `claim_window_days` against `as_of_date`: `EXPIRED` when elapsed, `CLOSING_SOON` within `window_closing_soon_days`, else `OPEN`. Where `claim_window_days` is null the status is `UNKNOWN` and ordering falls back to amount.

**Severity combination — CONFIRMED (Category C).** A single finding can have up to three
applicable `severity_config` rows (one per `metric`), each producing its own `HIGH | MEDIUM |
LOW` band from that metric's `high_threshold`/`medium_threshold` against the finding's value
for that metric — a metric is skipped, not defaulted, when the finding has no value for it
(e.g. `WINDOW_DAYS_REMAINING` on a finding with no claim window). **`FINDING_SEVERITY` is the
most severe band among whichever metrics actually applied** — the same "worst input wins"
principle `combine_confidence` already applies to confidence (data-foundation.md §7.1),
applied here to urgency instead of certainty. A finding with zero applicable metrics (no
config row matches and no metric has data) reports `FINDING_SEVERITY = UNAVAILABLE`, never a
default `LOW`.

---

### 5.15 Price positioning and repricing scenario (NEW — real, not deferred)

Two small, purely arithmetic functions comparing a seller's own price against competitor
prices supplied by CI. **Both persist through the existing generic `metric_result` table
(§9) under a new `metric_code` each — neither requires a new table**, on the same footing as
`margin_curve` or `cash_reconciliation` (§5.13.1).

**Inputs, and why neither is inferred.** `seller_price_paise` is an **explicit input the
caller supplies** — there is no live "current listed price" lookup anywhere in this engine or
`packages/calc-engine` (verified by grep: no such function exists), so this is a fact handed
in by the caller (typically CFO, sourced from the seller directly), never derived from
historical sales data. `competitor_prices[]` is supplied by CI and **enters as `DERIVED`**,
per the confidence-boundary rule CI's own spec now states at `competitor-intelligence-agent.md`
§5.1/§5.2 ("a CI-sourced figure can never present as `VERIFIED` or `PROVISIONAL`; it always
enters DOWNSTREAM calculations as `DERIVED`") — this engine treats an incoming competitor
price exactly the way CI's spec says it must leave CI, and this document does not restate or
loosen that rule.

**Boundary against the estimated-margin-range feature.** Neither function performs, requires,
or references any COGS or fee resolution, and **neither is the same feature as the deferred
estimated-margin-range interface** (`competitor-intelligence-agent.md` C17, §5.2, §6.7 —
implemented here at §5.13 `estimate_competitor_margin_range`). That feature answers "what is
this competitor's margin, roughly" and requires the fee reference store (§5.14). These
functions answer "what is the price gap, and what would a repriced number look like" and
require neither COGS nor fees. A caller needing margin implications of a price move still
calls `margin_curve` (§5.13.1) for the seller's own SKU; these functions never substitute for
that and never claim to.

```
compute_price_positioning(
  sku, seller_price_paise, seller_price_confidence,   -- caller-supplied fact; confidence per data-foundation §7.1
  competitor_prices: [{ value_paise, confidence, source_ref }],   -- from CI; confidence always DERIVED at this boundary
  as_of_date
) -> metric_result[]   -- metric_code = PRICE_POSITIONING
```

| Rule | Requirement |
|---|---|
| 1 | Output is one or more `metric_result` rows: gap vs. **average**, vs. **min**, and vs. **max** of the supplied `competitor_prices[]`, each as both `gap_paise` (signed, seller minus competitor reference) and `gap_pct`. |
| 2 | `UNAVAILABLE` — never a fabricated gap — when `competitor_prices[]` is empty, or when `seller_price_paise` is missing. A missing input is not zero (§4). |
| 3 | Confidence follows the existing monotonic rule (data-foundation §7.1, `combine_confidence`): the result's confidence is the least certain of `seller_price_confidence` and every competitor price's confidence. Because a competitor price always arrives `DERIVED`, no `PRICE_POSITIONING` result can ever present as `VERIFIED` or `PROVISIONAL`. |
| 4 | Requires **no COGS and no fee resolution** — purely a comparison of price facts. |
| 5 | Integer paise throughout (§4); `gap_pct` computed from unrounded paise, rounded once at presentation (§5.11). |
| 6 | `as_of_date` is stamped on the result per §4.2 — this is a point-in-time comparison, not a trend. |
| 7 | Reproducible for a fixed `(seller_price_paise, competitor_prices[], as_of_date)` tuple — like §5.13's estimates, **not** part of `canonical_data_version`, since competitor prices are not canonical seller data. Re-running with a newer CI snapshot is a new result, not a correction of the old one. |

```
compute_repricing_scenario(
  sku, seller_price_paise, seller_price_confidence,
  competitor_prices: [{ value_paise, confidence, source_ref }],
  stance,           -- MATCH_LOWEST | BEAT_LOWEST_BY_PCT | BEAT_LOWEST_BY_PAISE | MATCH_AVERAGE | MATCH_HIGHEST
  stance_param,     -- required for BEAT_LOWEST_BY_PCT / BEAT_LOWEST_BY_PAISE; null otherwise
  as_of_date
) -> metric_result[]   -- metric_code = REPRICING_SCENARIO
```

| Rule | Requirement |
|---|---|
| 1 | Output is a single suggested `value_paise` per invocation — the price implied by `stance` against the supplied `competitor_prices[]` — plus the resulting `gap_paise`/`gap_pct` versus the current `seller_price_paise`, using the same arithmetic as `compute_price_positioning`. |
| 2 | **Explicitly not margin-aware.** No COGS, no fee reference, no profit or contribution-margin implication is computed, checked, or implied by this function. A suggested price here may be unprofitable — that determination is `margin_curve`'s job (§5.13.1), not this one's, and this function never claims otherwise. |
| 3 | `UNAVAILABLE` when `competitor_prices[]` is empty, or `stance` requires a `stance_param` that is missing. |
| 4 | Confidence: same monotonic combination as rule 3 above — a suggested price computed from a `DERIVED` competitor input is itself never better than `DERIVED`. |
| 5 | Integer paise throughout; rounding per §5.11. |
| 6 | Reproducible for a fixed input tuple, on the same non-canonical footing as `compute_price_positioning` above. |

**`metric_code` is extended accordingly:** `PRICE_POSITIONING`, `REPRICING_SCENARIO` — added to
the list in §5.13.1. Both cite a standard `engine_result_ref` (`metric_result.id`, §9.1) like
every other metric in this section; **neither is an estimate** in the §9.1 `estimate_ref`
sense, because neither requires the fee reference store or any assumption-widening — they are
exact arithmetic over whatever price facts were supplied, `UNAVAILABLE` when those facts are
absent, never a range with named assumptions.

### 5.15.1 Price band and outliers — `compute_price_band` (NEW — the approved amendment resolving `competitor-intelligence-agent.md` D10/Q14, both now closed there)

A third function on the same footing as §5.15's two: the **percentile distribution of a set of
competitor prices for one seller product or category**, with quartile fences and outlier flags.

**Why it lives here and not in CI — LOCKED (2026-09-21).** The formula is not margin-aware, but
every operand is a signed-`BIGINT` paise money value, and the project's hard rule puts all money
arithmetic in this engine. `competitor-intelligence-agent.md` §6.16.3 records the *formula's
product intent* (when a band may be shown, how outliers are rendered) and **contains no
implementation of the arithmetic**; this section is the authority for the arithmetic itself. CI's
role is exactly the role it already plays for `compute_price_positioning` and
`compute_repricing_scenario`: **supply the tenant's tracked competitor prices as `DERIVED` inputs
and render the returned `metric_result` rows unchanged, citing the returned `engine_result_ref`.**
CI never computes a quartile, an IQR, a fence or an outlier flag.

```
compute_price_band(
  product_ref,      -- the seller's product/category identifier the band is being computed for
                    -- (CI passes SellerProduct.product_id, competitor-intelligence-agent.md §5.5)
  category,         -- the category the band is scoped to; may be UNKNOWN, in which case the band
                    -- is scoped to product_ref alone and the result states that scope
  competitor_prices: [{ value_paise, confidence, source_ref }],   -- from CI; always DERIVED at this boundary
  as_of_date
) -> metric_result[]   -- metric_code = PRICE_BAND
```

| Rule | Requirement |
|---|---|
| 1 | **Minimum 3 competitor prices.** With fewer than 3 supplied prices the function returns `UNAVAILABLE` with an explicit reason (`INSUFFICIENT_COMPETITOR_PRICES`, naming the count supplied and the minimum required) — **never a band computed from 1 or 2 points**. This is the engine-side counterpart of CI's "raw comparison only, no band" language (`competitor-intelligence-agent.md` §6.16.3, E28). The minimum is a caller-supplied configuration value (CI passes `ci_tenant_config.min_competitors_for_price_band`) with an engine floor of 3 that configuration may raise but never lower. |
| 2 | **Percentile method — locked:** linear interpolation between closest ranks, i.e. the method used by NumPy's default `percentile` and by SQL `PERCENTILE_CONT`. Chosen for cross-language/cross-database identity of results; no other percentile convention (nearest-rank, exclusive, Tukey hinges) is permitted. |
| 3 | **Quartiles:** `Q1` = 25th percentile and `Q3` = 75th percentile of the supplied prices under rule 2. |
| 4 | **IQR:** `IQR = Q3 − Q1`. **Fences:** `lower_fence = Q1 − 1.5 × IQR`, `upper_fence = Q3 + 1.5 × IQR`. |
| 5 | **Outlier rule:** a price is an outlier when `price < lower_fence` **or** `price > upper_fence`. |
| 6 | **Outliers participate in the quartile calculation.** `Q1`/`Q3`/`IQR`/fences are computed from the **full** supplied set, never from a pre-filtered one. Outliers are excluded **only** from the "typical range" headline figures (rule 7's `PRICE_BAND_TYPICAL_LOW`/`_HIGH`) and are still returned, flagged, in the full distribution so the caller can display them. The engine never silently drops a supplied price. |
| 7 | **Output** is one or more `metric_result` rows under `metric_code = PRICE_BAND`: `PRICE_BAND_Q1`, `PRICE_BAND_Q3`, `PRICE_BAND_IQR`, `PRICE_BAND_LOWER_FENCE`, `PRICE_BAND_UPPER_FENCE`, `PRICE_BAND_TYPICAL_LOW` and `PRICE_BAND_TYPICAL_HIGH` (min/max of the non-outlier prices), plus one row per supplied price carrying its `is_outlier` flag and its `source_ref`. Every row cites a standard `engine_result_ref` (`metric_result.id`, §9.1) — **this is not an estimate**, it requires no fee reference and no assumption-widening. |
| 8 | **Integer paise throughout (§4). No float appears anywhere, including in the percentile interpolation** — the interpolation is computed in integer arithmetic and rounded once per §5.11. |
| 9 | Confidence follows the monotonic rule (data-foundation §7.1, `combine_confidence`): the least certain supplied price governs. Because a competitor price always arrives `DERIVED`, **no `PRICE_BAND` result can ever present as `VERIFIED` or `PROVISIONAL`.** |
| 10 | `as_of_date` is stamped per §4.2 — a band is a point-in-time distribution, never a trend. |
| 11 | Reproducible for a fixed `(product_ref, category, competitor_prices[], as_of_date)` tuple and, like §5.15's two functions, **not part of `canonical_data_version`** — competitor prices are not canonical seller data. Re-running against a newer CI snapshot is a **new** result, not a correction of the old one. |
| 12 | **Not margin-aware.** No COGS, no fee resolution, no profit implication — identical boundary to §5.15. A seller-facing margin implication of a band position is `margin_curve`'s job (§5.13.1), never this function's. |

**Cross-reference.** `competitor-intelligence-agent.md` §6.16.3 (product rules, minimum-competitor
gate, outlier display) and §1a/C-decisions reference this section as the home of the arithmetic.
Neither spec restates the other: **product/display rules there, arithmetic here.**

---

## 6. Grain and periods

Computable at: `line` → `order` → `sku` → `marketplace` → `account`.

Period allocation uses **document date**, not report period (data-foundation §6). A line dated 28 Aug belongs to August regardless of which report delivered it.

**`document_date` resolves to `sales_line.invoice_date`**, falling back to `dispatch_date`
then `order_date` when no invoice exists yet for that line (e.g. a cancellation before
invoicing). `data-foundation.md` does not use the literal name `document_date` — this is the
engine's mapping onto that spec's actual columns, isolated to a single `resolve_document_date()`
function. **Confirmed decision.** Reasoning: for seller business-period reporting, a cancelled
pre-invoice order should remain attributable to the period the order occurred in, not
disappear from reporting.

Settlement adjustments are attributed to the **original document's period**, not the settlement date — otherwise a return silently improves the month it was processed in. The settlement date is retained for cash-flow views.

---

## 7. Manual inputs and corrections (R7, R8)

### 7.1 Non-destructive rule

Manual values are **never written into canonical tables.** They live in a separate adjustment store and are composed at calculation time.

```
manual_adjustment (
  id, tenant_id,
  target_type,          -- LINE | ORDER | SKU | PERIOD | ACCOUNT | SUPPLIER | SETTLEMENT
  target_ref,
  field,                -- e.g. discount_bearer, cogs_per_unit, rto_outcome, ad_spend
  value             jsonb not null,   -- scalar or structured object; see the field registry below
  reason,
  created_by, created_at,
  supersedes_id,        -- adjustments are append-only; corrections chain
  status                -- ACTIVE | SUPERSEDED | WITHDRAWN
)
```

- **Append-only.** A correction supersedes; it does not update.
- **Re-ingestion never destroys adjustments.** New parse runs re-attach them by natural key.
- **Conflict is surfaced, not resolved.** Where source data later contradicts an adjustment, both are shown and the seller decides.

### 7.2 Effect on confidence

Any figure incorporating a manual input is labelled `MANUAL` and names the adjusted fields. Confidence remains monotonic (data-foundation §7.1): a total containing a manual input cannot present as `VERIFIED`.

### 7.2.1 Field registry — this spec owns the key space

`field` values are declared here, not by consuming agents. An agent that needs a new field requests it; it does not invent one. **This registry is the sole authority for the key space** — §7.3 below is an illustrative prose list, not a competing enumeration. **This registry is the sole authority for the key space** — §7.3 below is an illustrative prose list, not a competing enumeration.

| `field` | `target_type` | `value` shape |
|---|---|---|
| `cogs_per_unit` | `SKU` | `{amount_paise, effective_from?}` — `effective_from` defaults to the adjustment's `created_at` when omitted. Required so D3's weighted-average-cost-as-of-`document_date` is actually computable (T13); a bare scalar paise value (the pre-amendment shape) is still accepted and treated as `effective_from = created_at` |
| `discount_bearer` | `LINE` | `SELLER \| MARKETPLACE` |
| `rto_outcome` | `LINE` | `RECOVERED_SELLABLE \| RECOVERED_DAMAGED \| LOST` |
| `cancellation_flag` | `LINE` | boolean |
| `fee_gst_treatment` | `ACCOUNT` | `CREDITABLE \| COST` |
| `return_refund_amount` | `LINE` | scalar paise |
| `logistics_cost` | `LINE` | scalar paise — **per-line actuals only**, e.g. a known reverse-logistics charge on one order |
| `expense.advertising` · `expense.packaging` · `expense.storage` · `expense.logistics` · `expense.other` | `PERIOD` \| `ACCOUNT` \| `SKU` | `{amount_paise, gst_amount_paise?, marketplace?}` — **pooled costs**. Precedence: where both a per-line `logistics_cost` and a pooled `expense.logistics` cover the same line, the per-line actual wins and the pool is reduced by it |
| `batch.budget` | `SKU` \| `ACCOUNT` | `{amount_paise, valid_until?}` — budget ceiling for batch-size estimation (B9) |
| `settlement.receipt` | `SETTLEMENT` | `{expected_paise?, received_paise, received_date, note?}` |
| `supplier.quote` | `SUPPLIER` | `{supplier_name, sku?, unit_cost_paise, moq?, lead_time_days?, shipping_paise?, payment_terms?, reliability_note?}` |
| `gst_rate_override` | `SKU` | `{rate_pct, hsn?, category?, gst_lookup_result_id, effective_from?}` — `rate_pct` is a Decimal-string (e.g. `"18.0000"`), never a JSON float, matching this registry's paise-based fields' no-float rule. `gst_lookup_result_id` is mandatory and references the specific `gst_lookup_result` row (§8.4) the seller accepted, so provenance traces all the way to that row's cited `source_url`/`retrieved_at` — not just to "a seller clicked accept." `hsn`/`category` echo the accepted classification for display without re-joining to the (append-only, potentially superseded) lookup row. |

Structured values are still **append-only and superseding** — a corrected quote is a new row that supersedes, never an update.

**`gst_rate_override`, and how it differs from `gst_lookup_result.status`.** §8.4's `gst_lookup_result` already carries its own `status` (`PROVISIONAL | SELLER_VERIFIED | REJECTED`) plus `verified_by`/`verified_at` — that status marks the lookup *row itself* as reviewed, but on its own it does not let the accepted rate flow into any calculation. §8.4's L2 requires the accepted rate to become "a labelled manual input" before it can be applied, and `gst_rate_override` is that manual input — a separate, additional record. Marking a `gst_lookup_result` `SELLER_VERIFIED` and creating a `gst_rate_override` that references it are two distinct, separately-recorded acts; a future implementation must not treat the former as sufficient to unblock a calculation.

*Grain.* `SKU`, not `LINE`: a GST rate is a property of the SKU's product/HSN classification, not of an individual order line — it does not vary line-to-line for the same SKU. This matches how `gst_lookup_result.sku` and the resolution order's tier 1 "observed" rate already operate at SKU/classification level (§8.1, §8.2.2), and mirrors `cogs_per_unit`'s existing `SKU` grain above.

*Tier precedence.* Once accepted, a `gst_rate_override` ranks **above tier 1** (observed) in OP13's three-tier GST rate-resolution order (§8.2.2), not merely as a gap-filler alongside tier 3. A seller's explicit acceptance of a specific classification is stronger evidence than an unclassified, machine-observed rate on a report line, and §7's own standing model already allows a manual input to take precedence over observed data (that is the point of the manual-adjustment mechanism). Concretely: for a SKU carrying an `ACTIVE` `gst_rate_override`, that override is checked and applied before tier 1 is consulted at all; tiers 1→2→3 are unchanged and continue to apply, in that same order, to every SKU without an accepted override. §8.2.2's own text describing tiers 1-3 is not being redesigned by this addition.

*Confidence.* An accepted `gst_rate_override` carries `MANUAL` confidence (`data-foundation.md` §7.1), not `PROVISIONAL`. Accepting a `gst_lookup_result` does not strengthen the underlying research's evidentiary basis — the web source is exactly as provisional after acceptance as before. What changes is accountability: the seller has now taken ownership of the figure, and `MANUAL` is this codebase's existing label for a seller-supplied fact, treated the same as `cogs_per_unit`. Under `combine_confidence`'s monotonic rule, a calculation using a `gst_rate_override` therefore cannot present as better than `MANUAL`.

*Permission.* Creating or superseding a `gst_rate_override` requires `financials.adjust`, per §7's standing rule (restated at `cfo-agent.md` §5, permission rule 4) — no exception for this field.

*Never automatic.* No code path may create a `gst_rate_override` row without an explicit seller acceptance action against a specific `gst_lookup_result`. This is the entire point of L2. A `gst_rate_override` must never be synthesized merely because a `gst_lookup_result` reaches `SELLER_VERIFIED` through some other flow — acceptance-that-unblocks-a-calculation and verification-of-the-lookup-row are kept as two separate acts precisely so the former is never accidentally implied by the latter.

### 7.3 Permitted manual inputs at V1

COGS per SKU · discount bearer override · RTO outcome classification · cancellation flag · advertising spend · **other seller-declared expense pools (packaging, storage, logistics, other)** · **settlement receipt corrections where a report is missing or disputed** · other cost pools · fee-GST treatment toggle · return refund amount where settlement data is absent · **seller-supplied logistics costs** (forward, reverse, RTO legs) where marketplace reports omit them · supplier quote data for CFO ranking (price, MOQ, lead time, shipping, payment terms, reliability notes) · GST rate/HSN classification override accepted by the seller from a GST Applicability Lookup result (§8.4 L2).

---

## 8. GST module

### 8.1 Inclusive / exclusive normalisation

Every source declares its price basis in adapter configuration. **Never inferred.**

```
if basis = EXCLUSIVE:  taxable = listed
if basis = INCLUSIVE:  taxable = listed × 100 / (100 + effective_rate)
```

Requires a known effective rate. Where the rate is unknown, normalisation fails and the line is flagged — it never guesses a rate.

**Basis is declared per marketplace and per field** (A1, resolved). There is no single basis across sources:

| Source | Basis |
|---|---|
| Meesho | **INCLUSIVE** — `Listing Price (Incl. taxes)`, `Fixed Fee (Incl. GST)`, `Warehousing fee (incl GST)`, `Return premium (incl GST)` |
| Amazon MTR | Supplies **both** — `Invoice Amount` and `Tax Exclusive Gross` |
| Flipkart | Per-field; declared in the adapter, unverified pending a real export |

Treating all three as `EXCLUSIVE` would systematically **overstate Meesho revenue** by the GST rate. The adapter declares the basis for every money field; the engine never infers it.

### 8.2 Tax head handling

- Intra-state → CGST + SGST (or UTGST); inter-state → IGST. Validated by `V-TAX-001`.
- Rows failing that rule are quarantined and excluded from aggregates.
- Cess is carried separately and never merged into GST totals.

### 8.2.1 GST rate plausibility reference (`V-TAX-003`)

`data-foundation.md`'s `V-TAX-003` ("effective GST rate within plausible slab set", WARNING
severity) implies a slab reference without defining one. This engine owns that reference:

```sql
gst_slab_reference (
  id uuid pk,
  rate_pct numeric(7,4) not null,
  label text not null,              -- e.g. "18% standard rate"
  source_url text not null,
  source_title text,
  retrieved_at timestamptz not null,
  effective_from date not null,
  effective_to date,
  version int not null,
  confidence text not null default 'PROVISIONAL'
)
```

Platform-owned, no `tenant_id`, read-only to the application. Seeded from official CBIC / GST
Council published rate tables, one row per slab, each row citing its own `source_url` and
`retrieved_at`. **This is not a claim of a complete or universal GST slab set, and it is not
GST classification or tax advice** — it exists solely to back `V-TAX-003`'s plausibility
check. An observed `rate_pct` with no matching row produces a WARNING, never an ERROR: the
row is still included in aggregates, flagged for review, never treated as invalid and never
excluded. This reference is never applied retroactively to a row that predates its
`effective_from`, and it never substitutes for the GST Applicability Lookup (§8.4) or the
professional-verification disclaimer (§8.3).

### 8.2.2 Curated HSN knowledge base (`hsn_gst_reference`)

OP13 (`phase-1-readiness-review.md`) names the middle tier of the layered GST rate source as
a **"curated HSN→rate knowledge base maintained by Metrion in the policy KB."** No table has
ever been defined for it — `cfo-agent.md` C5, §6.6 and OP13 all cite "the curated HSN
knowledge base" by name only. This section is that definition, and it resolves a latent
ambiguity in OP13's own wording along the way: **"policy KB" here means a structured,
versioned SQL reference table, not pgvector/RAG.** Semantic retrieval (OP12) is reserved for
narrative document content — nothing that resolves a money-bearing rate is ever looked up by
embedding similarity; that would let an LLM-adjacent retrieval step originate a figure, which
the project's hard rule forbids regardless of how "curated" the underlying content is. This
table is queried by exact/prefix code match through a typed repository function, the same
pattern as `gst_slab_reference` and `fee_reference` below — never by vector search.

**Relationship to the other two GST reference tables, restated so the three are never
conflated:**

| Table | Job | Shape |
|---|---|---|
| `gst_slab_reference` (§8.2.1) | Plausibility check on an **already-observed** rate (`V-TAX-003`) | Flat set of valid rate percentages, no HSN/category column |
| `hsn_gst_reference` (this section) | Supplies a **candidate rate for an unobserved line**, by HSN/SAC/category classification | HSN-code-to-rate lookup, deterministic, no live research |
| `gst_lookup_result` (§8.4) | Live web research fallback when the first two both miss | Per-query, on-demand, requires explicit seller acceptance before use (L2) |

**Why this table is seeded with real data, unlike `fee_reference` (§5.14).** `fee_reference`
ships with zero rows because marketplace commission rates are private commercial data nobody
can verify without a real marketplace agreement — this project's standing rule is never to
invent real numbers. GST rates by HSN chapter are the opposite in kind: they are **public,
government-published statutory law** (CBIC notifications, GST Council rate schedules), the
same class of source `gst_slab_reference` already draws on ("Seeded from official CBIC / GST
Council published rate tables, one row per slab, each row citing its own `source_url` and
`retrieved_at`," §8.2.1). `hsn_gst_reference` follows that same precedent, not
`fee_reference`'s "ships empty" one — a future reader should not assume every reference table
in this engine starts empty; it depends on whether the underlying data is public and citable.
**This spec pass defines the table shape only. No rows are seeded here** — real HSN/GST rate
data is sourced from official public sources and loaded in a following checkpoint (§11, new
item below).

**Schema:**

```sql
hsn_gst_reference (
  id uuid pk,
  hsn_code text not null,           -- HSN/SAC code or chapter/heading-level prefix; see below
  description text not null,        -- human-readable category name
  rate_pct numeric(7,4) not null,
  source_url text not null,
  source_title text,
  retrieved_at timestamptz not null,
  effective_from date not null,
  effective_to date,
  version int not null,
  confidence text not null default 'PROVISIONAL'
)
```

Platform-owned, no `tenant_id` — matches `gst_slab_reference`/`fee_reference`'s precedent for
platform-wide reference data. RLS still applies: per `config_repo.py`'s existing
`gst_slabs_effective_on`/`resolve_fee_reference` docstrings, even a table with no `tenant_id`
column requires a `tenant_scope()` connection to satisfy RLS context — `tenant_id` plays no
role in the `WHERE` clause here either, it only opens a valid connection.

**HSN code precision — variable length, not fixed at 8 digits.** Real e-commerce sellers
frequently know only a 4- or 6-digit HSN, not the full 8-digit code, and CBIC's own rate
notifications are frequently published at chapter (2-digit) or heading (4-digit) level
covering many 8-digit codes at a single rate. Forcing every row to 8 digits would either
require guessing digits that were never published at that granularity, or silently drop
chapter-level notifications that are the actual public source. `hsn_code` is therefore stored
at whatever precision its source publishes — 2 to 8 digits — and matched by prefix (below),
not by fixed-length equality.

**Resolution function** (mirrors `resolve_fee_reference`'s exact resolution pattern, §5.14):

```
resolve_hsn_gst_reference(tenant_id, *, hsn_code, as_of_date) -> dict | None
```

**Matching rule (V1 — kept deliberately simple):**

1. A reference row matches a queried `hsn_code` when the row's `hsn_code` is a **leading-digit
   prefix of, or exactly equal to,** the queried code (e.g. a stored `"6109"` row matches a
   queried `"61091000"`; a stored `"61091000"` row matches only a queried `"61091000"`).
2. Among matching rows, the **longest (most specific) matching prefix wins**; ties broken by
   latest `effective_from`.
3. `effective_from <= as_of_date` and (`effective_to IS NULL OR effective_to >= as_of_date`)
   gate every candidate — never applied retroactively, same rule as `gst_slab_reference` and
   `fee_reference`.
4. **If the queried code is shorter than every candidate row's stored code** (the seller only
   knows a shallower classification level than anything on file — e.g. querying `"61"` against
   a table that only has 6- and 8-digit rows under that chapter), the function returns `None`
   rather than guessing among children that may carry different rates. Resolving that case by
   checking whether all children under the queried prefix happen to share one rate is a real
   possible refinement, deliberately **deferred out of V1** to keep the matching rule simple
   and auditable; note it here so a future checkpoint doesn't need to rediscover it.
5. No match under rules 1–4 → `None`. Never a guessed or defaulted rate, matching every other
   resolver in this engine (§5.14, §8.2.1).

**Sequencing within OP13's three-tier order.** CFO/Brain 1 resolves a GST rate for a line or
SKU in this exact order, and only advances a tier when the prior one has nothing:

1. **Observed** — the rate already present in the seller's own uploaded data, via canonical
   `TAX`-kind `line_component` rows on the line itself (§8.1's inclusive/exclusive
   normalisation already depends on this being known; no new code is needed for this tier — it
   is how §8.1 already works today).
2. **`hsn_gst_reference`** (this table) — reached only when tier 1 has no observed rate for
   that line/SKU. Deterministic table lookup, no live research, no seller interaction required
   to apply it.
3. **GST Applicability Lookup** (§8.4) — reached only when tiers 1 and 2 both miss. Live
   research, `PROVISIONAL`, requires explicit seller acceptance before it ever enters a
   calculation (L2).

A `hsn_gst_reference` hit never overrides an observed rate from tier 1, and tier 3 is never
invoked when tier 1 or 2 already resolved one.

**Auto-application, contrasted with tier 3's `L2` gate.** Because `hsn_gst_reference` is
curated, static, platform-owned reference data — the same class as `gst_slab_reference` and
`fee_reference`, both of which feed calculations directly once resolved — a rate resolved from
this table **may enter a calculation automatically**, subject to the confidence treatment
below. This is a deliberate contrast with tier 3 (§8.4, `gst_lookup_result`), which is live,
externally researched, per-query content and therefore requires explicit, recorded seller
acceptance (L2) before it can be applied. `hsn_gst_reference` carries no equivalent
acceptance gate — the gate that matters for this table is sourcing rigor at seed time
(`source_url`/`retrieved_at` mandatory, same as every sibling table), not a per-use seller
click.

**Confidence and disclaimer treatment — this checkpoint's first answer to the question.**
Every row defaults to `confidence = 'PROVISIONAL'`, mirroring `gst_slab_reference`'s own
default: a curated public-data table is still not a substitute for the seller's own filing.
When a `hsn_gst_reference` row resolves a rate used inside a calculation, its `confidence`
value is one of the inputs `combine_confidence` folds over under the existing monotonic rule
(`data-foundation.md` §7.1) — no special-casing, no new confidence mechanism. Concretely: a
line that was otherwise `VERIFIED` but pulls its GST rate from this table cannot present as
better than `PROVISIONAL`, because `combine_confidence` always yields the weakest input. This
table's results feed a `metric_result` with a normal `engine_result_ref`, the same as
`fee_reference`-resolved fee rates — they are not a separate `estimate_ref` contract (§9.1);
they are a deterministic table lookup, not a live or observation-scoped estimate. **This
table's rate is never GST classification or tax advice** — the same caveat class as §8.2.1's
"not GST classification or tax advice" and §8.3's disclaimer. Any displayed figure computed
using a `hsn_gst_reference`-resolved rate is labelled to show the rate came from Metrion's
curated reference, not from the seller's own observed data, alongside §8.3's standing
disclaimer: *"Indicative management summary. Not a GST return. Not filing-grade. Verify with
your tax professional."*

**Relationship to `V-TAX-003` (§8.2.1), stated explicitly so the two never appear to
conflict.** `V-TAX-003` checks plausibility of a rate that has *already been observed* on a
line, against `gst_slab_reference`'s flat set of valid percentages — it never supplies a rate,
only flags an implausible one. `hsn_gst_reference` does the opposite job: it supplies a
candidate rate for a line where *no rate has been observed at all*. Both can be true on the
same period at once — one line's observed rate gets plausibility-checked by `V-TAX-003` while
a different, unobserved line's rate is filled from `hsn_gst_reference` — without any overlap
or contradiction.

**Illustrative example (not real, not seeded by this spec pass):**

| `hsn_code` | `description` | `rate_pct` | `confidence` |
|---|---|---|---|
| `"6109"` (illustrative) | "T-shirts, cotton, knitted (illustrative)" | `12.0000` (illustrative) | `PROVISIONAL` |

This row is an example of the shape only. No claim is made about its accuracy — real rows are
sourced and loaded in the following checkpoint referenced in §11.

### 8.3 Indicative tax summary

Per period and marketplace: output tax by head · GST charged on fees (potentially creditable) · TCS collected · TDS deducted · taxable value by rate slab · count of excluded rows.

Every rendering carries: **"Indicative management summary. Not a GST return. Not filing-grade. Verify with your tax professional."**

### 8.4 GST Applicability Lookup

A **research** feature. Structurally isolated from the calculation engine.

**Input:** product title, and where available HSN/SAC or category.

**Output:**

```
gst_lookup_result (
  id, tenant_id, sku,
  query_text, query_hsn,
  likely_rate_pct,
  likely_hsn, likely_category,
  ambiguity_note,              -- populated when classification is uncertain
  alternatives,                -- competing classifications, where found
  source_url,                  -- required
  source_title,
  retrieved_at,                -- required
  status,                      -- PROVISIONAL | SELLER_VERIFIED | REJECTED
  verified_by, verified_at
)
```

**Hard rules**

| # | Rule |
|---|---|
| L1 | Result is stored as **externally researched, provisional** knowledge. |
| L2 | It **never** enters a calculation automatically. Application requires explicit seller acceptance, which creates a labelled manual input (§7). That manual input is `gst_rate_override` (§7.2.1) — creating it is the act that unblocks a calculation, distinct from merely marking this row's `status` `SELLER_VERIFIED`. |
| L3 | `source_url` and `retrieved_at` are mandatory. A result without both is discarded. |
| L4 | Where classification is uncertain, `ambiguity_note` is populated and alternatives are shown. Confident-sounding single answers are not produced from ambiguous evidence. |
| L5 | Every display carries: *"Likely classification based on web research. Final GST classification must be verified through official GST guidance or a qualified tax professional."* |
| L6 | Results are cached with a TTL and **never** applied retroactively to historical periods — GST rates change. |
| L7 | An LLM may extract and structure the result. It may not originate a rate. Every figure traces to a cited source. |

#### 8.4.1 Fetch mechanism (curated allowlist, no search API)

L1-L7 above specify the *output* contract. This subsection specifies the *mechanism* by
which a query actually becomes fetched, cited web content — how §8.4 goes from "product
title, and where available HSN/SAC or category" to a `source_url` and `retrieved_at` that
satisfy L3. Everything below is new in this pass; nothing in L1-L7 is restated or changed.

**Decision (approved).** A curated, hardcoded allowlist of trusted domains — no general
search-API integration. This mirrors the existing pattern in
`packages/competitor-intelligence/src/competitor_intelligence/capture/`: a `Fetcher`
Protocol with one real `HttpxFetcher` implementation, injected rather than imported
directly (so tests never touch the network), and an allowlist check
(`is_allowed_host`-equivalent) that runs *before* any fetch call, hardcoded and
non-tenant-configurable. G2's implementation checkpoint reuses this exact shape — a
`GstFetcher` Protocol, one real implementation, one allowlist module — not a new one.

**The allowlist.**

Two tiers, both hardcoded and named explicitly here (never "any tax blog" or a runtime-
configurable list):

*Tier 1 — official government sources:*

| Domain | Status as checked this session (2026-09-25) |
|---|---|
| `cbic-gst.gov.in` | Reachable, but `gst-goods-services-rates.html` returns only a stub redirect notice pointing to `taxinformation.cbic.gov.in` — no rate data on the page itself. |
| `taxinformation.cbic.gov.in` | **Unreachable** — TLS certificate verification failure on a standard fetch. |
| `gst.gov.in` | Not tested this session. Included on the allowlist (it is the GSTN/GST Council's own portal, the most authoritative possible source), but its actual fetchability is an open implementation-time verification item — see below. |

*Tier 2 — named secondary publishers* (established, non-anonymous Indian tax-advisory
sites, already used as real seed sources in `hsn_gst_reference`, §8.2.2 —
`packages/calc-engine/migrations/versions/20260925_0007_hsn_gst_reference.py`):

`cleartax.in`, `taxguru.in`, `getswipe.in`, `busy.in`, `gimbooks.com`, `rushtax.app`,
`taxgarden.in`

Judgment call, stated explicitly: Tier 1 is included first, but this session's own direct
evidence is that the two most likely CBIC entry points are either stale or unreachable, and
`gst.gov.in` is unverified. Treating official-only as the allowlist would leave G2 with no
realistic fetchable source in V1, which is worse for the seller than a clearly-labelled
secondary-tier hit — the seller already sees the L5 disclaimer regardless of tier, and a
"likely classification, please verify" figure sourced from a named, established publisher is
more useful than `UNAVAILABLE`. Tier 2 is therefore included, but a Tier 2 hit is
distinguished from a Tier 1 hit at the result level (next section) rather than presented
identically. No domain outside these two named lists is ever added at runtime, by an LLM
suggestion, or by following an off-allowlist redirect target — the same rule
`competitor_intelligence.capture.allowlist` already enforces for its own domains.

**Tier reflected in the result.** `gst_lookup_result` does not currently carry an explicit
tier column (§8.4's schema is not being redesigned in this pass); until a following
checkpoint adds one, the tier is inferable from `source_url`'s host against the two named
lists above, and consuming surfaces (CFO narration, frontend disclaimer copy) MUST treat a
Tier 2 source as *lower confidence, more prominent disclaimer* than a Tier 1 source — this
is a requirement on the consumer, not a schema change.

**Query mechanism.** There is no search-API integration (explicitly rejected — out of scope,
new paid vendor dependency). Two shapes were considered:

- (a) *Predictable query-string URL per site.* Rejected for V1: whether any allowlisted
  domain actually exposes a stable, query-string-based rate-lookup URL was not verified in
  this spec-only pass, and building a mechanism around an unverified assumption risks a
  fetch mechanism that silently never matches anything. Flagged as an implementation-time
  verification item (below) — if such a URL is confirmed for a specific domain during G2's
  build, it may be added as a targeted enhancement, but it is not the V1 mechanism.
- (b) *Fetch known static reference pages, let the LLM extract from within the fetched
  content.* **Chosen.** Each allowlisted domain is paired with a short, hardcoded list of
  known static rate-schedule / HSN-reference pages (analogous to the specific URLs already
  cited as `source_url` in the `hsn_gst_reference` seed migration — e.g. `busy.in`'s
  `/gst-rates/stationery/`). G2 fetches the relevant known page(s) for the query's category
  (where a category is available in the input) or a general rate-schedule page, and passes
  the fetched text plus the query to the LLM extraction step (L7, detailed below) to find a
  matching line within that page's actual content. This is the more realistic V1 mechanism
  given this session's own direct evidence that official "search" entry points are stale or
  unreachable — it needs no assumption about any site's search behaviour, only that a known
  static page exists and can be fetched.

  The concrete set of known pages per domain (which URL fetches for which product category)
  is an implementation-time artefact, not enumerated exhaustively in this spec — it is
  expected to grow/be corrected as pages are actually inspected during the build checkpoint,
  the same way the allowlist domains above are fixed but the specific fetched URLs within
  them are a maintained list, not a spec-frozen one.

  **Implementation-time verification items** (not resolved in this spec-only pass):
  - Confirm `gst.gov.in` is reachable via a standard fetch (unverified this session).
  - Confirm at least one working static reference page per Tier-1 domain before relying on
    it; if none is fetchable, G2's V1 behaviour degrades to Tier 2 only for that query (see
    fetch-failure handling below) rather than blocking.
  - Re-check whether any allowlisted domain exposes a stable query-string search URL (option
    (a) above) — if so, it may reduce reliance on Tier 2 sources for future rates.

**Fetch failure / no-match handling.** A failed fetch (transport error, timeout, non-2xx,
TLS failure — mirroring `FetchError`'s shape in
`competitor_intelligence.capture.fetcher`) or a successfully fetched page whose content does
not actually contain a matching rate/HSN/category for the query produces **no**
`gst_lookup_result` row — never a row with a placeholder, a best-guess, or a `source_url`
that doesn't actually support the value shown. This is what L3 already requires
(`source_url`/`retrieved_at` mandatory, discarded if either missing); this subsection states
the mechanism-level consequence explicitly: G2 attempts each known page for the query, in
Tier 1 then Tier 2 order, and stops at the first page whose fetched content yields a
genuine match per the L7 extraction step. If every attempt fails or yields no match, the
lookup surfaces to CFO/the seller as an honest **"no reliable source found"** outcome —
functionally equivalent to `hsn_gst_reference` returning `None` (§8.2.2, C15): no rate is
guessed in the gap, and the UI states plainly that web research did not find a matching
classification, inviting a manual/seller-verified entry instead. Given this session's own
direct reachability findings for the CBIC domains, this is a real, expected V1 outcome for
some queries — not a rare edge case to hand-wave.

**LLM extraction step (mechanism for L7).** L7 already states the LLM may extract and
structure, never originate. Concretely: the LLM extraction call is given (1) the query
(product title, and HSN/SAC or category where available) and (2) the actual fetched page
text from the current attempt only — never the query alone, and never answered from the
model's own training knowledge. The call reuses the existing `LlmProvider` Protocol
(`packages/cfo/src/cfo/reasoning/provider.py`, `complete(*, model, prompt) -> str`) — no new
LLM-interface shape is introduced. The prompt is constructed so extraction is only valid
when the fetched text itself states a rate/HSN/category; if the fetched page does not
contain a relevant statement, the extraction step returns no match (feeding the
fetch-failure/no-match path above), rather than the LLM inferring or guessing from
adjacent context. This is the same "explain/extract, never originate" boundary CLAUDE.md
and §1 already state for computed figures, extended here to cited-text extraction:
the model may summarise and locate what the fetched page says; it may never supply a figure
the fetched page does not contain.

**Caching / TTL (mechanism for L6).** L6 already requires caching with a TTL and forbids
retroactive application to historical periods. TTL chosen: **14 days**. Reasoning: GST rate
changes are infrequent (typically announced via GST Council meetings, not continuous
drift), so an hours-scale TTL would re-fetch needlessly and stress the same small set of
external sites this mechanism depends on; a months-scale TTL risks silently serving a stale
rate past a real Council-notified change without re-checking. Fourteen days is a defensible
middle ground — short enough that a rate change is caught within roughly two weeks, long
enough to avoid redundant fetches of static pages that rarely change. Enforced as a
`retrieved_at`-age check: before reusing a cached `gst_lookup_result` row for a query, G2
computes `now - retrieved_at`; if it exceeds 14 days, the row is not reused and the fetch
mechanism above runs again, producing a fresh row (old row retained for audit history, not
deleted — consistent with never mutating a prior `gst_lookup_result` in place). Per L6,
a cached (or freshly fetched) result is never applied retroactively to a historical period
regardless of its age.

---

## 9. Provenance and confidence (R9)

Every stored metric carries:

```
metric_result (
  id                  uuid pk,  -- the engine result reference; see §9.1
  metric_code,                  -- NET_REALIZED_REVENUE | CONTRIBUTION_PROFIT | ...
  grain, target_ref, period,
  value_paise,
  recognition_state,            -- RECOGNISED | REALIZED | UNAVAILABLE
  confidence,                   -- VERIFIED | PROVISIONAL | DERIVED | MANUAL
  calculation_basis,            -- human-readable formula summary
  formula_version, config_version,
  input_refs,                   -- source rows + adjustments used
  exclusions,                   -- quarantined rows omitted, with counts and rule IDs
  computed_at
)
```

**Confidence is monotonic under aggregation.** A figure can never present as more certain than its weakest input. In V1 nothing exceeds `PROVISIONAL`, because no adapter mapping is confirmed against a real export.

### 9.1 Result reference contracts

Two distinct contracts. Consumers must not conflate them.

| Contract | Identifier | Applies to | Guarantees |
|---|---|---|---|
| **`engine_result_ref`** | `metric_result.id` | Every figure computed from the canonical model | Reproducible under §4; carries state, confidence, basis, `formula_version`, `config_version`, `input_refs`, `exclusions` |
| **`estimate_ref`** | **A family, not one table** — `competitor_estimate.id` (§5.13, CI-exclusive) or `product_feasibility_estimate.id` (§5.13.2, PI-exclusive) | Any estimation surface built on observed, non-canonical inputs | Reproducible **only for a fixed observation set**; carries `observation_ref`, `fee_reference_version`, assumptions |

**`estimate_ref` is scoped to the interface that produced it, not a single global table.** A consumer must know which interface it called (`estimate_competitor_margin_range` vs `estimate_product_feasibility`) to know which table an `estimate_ref` UUID resolves against — the two id spaces are never merged, never cross-referenced, and a UUID from one is never valid against the other. Each new estimation surface added to this engine defines its own dedicated table (never reuses an existing one) and is listed here.

```sql
competitor_estimate (                -- §5.13 output provenance; NOT a metric_result. CI-exclusive.
  id                    uuid pk,     -- an estimate_ref, scoped to THIS table only
  tenant_id             uuid not null,
  low_paise bigint not null, high_paise bigint not null,
  confidence            text not null,      -- DERIVED, never better
  basis                 text not null,
  assumptions           jsonb not null,
  fee_reference_version int not null,
  observation_ref       jsonb not null,     -- source_url + fetched_at
  formula_version text not null, config_version text not null,
  computed_at           timestamptz not null
)
```

`product_feasibility_estimate` (§5.13.2, PI-exclusive) is the second table in this family — same shape, same rules, structurally separate, defined in full at §5.13.2.

**Rule.** A consumer displaying a financial figure cites an `engine_result_ref`. A consumer displaying any estimate cites the `estimate_ref` from the specific table its interface produced, and states which table. No `estimate_ref` ever substitutes for an `engine_result_ref`, and §5.13 rule 5 stands for every table in the family — estimates are never written to `metric_result`.

---

## 10. Edge cases

| # | Case | Required behaviour |
|---|---|---|
| E1 | Credit note | Negative signed line; reverses the original within the original's period |
| E2 | Partial return (`returned_qty < quantity`) | Pro-rate revenue, COGS, and fees by returned units |
| E3 | Replacement order | Not new revenue. Linked via `Replacement Order ID`; COGS of the replacement unit consumed; original revenue retained |
| E4 | Multi-unit line, partial RTO | Split into recovered / damaged / lost cohorts; each accounted per §5.7 |
| E5 | Settlement arrives in a later period | Attributed to the original document's period; settlement date retained for cash flow |
| E6 | Settlement uploaded before the invoice | Held as `ORPHAN_SETTLEMENT`; matched on later ingest; never discarded |
| E7 | Negative Net Realized Revenue for a period | Reported as negative. Never floored at zero |
| E8 | `NetRealizedRevenue = 0` | Margin % is `UNDEFINED`, not zero, not error |
| E9 | Missing COGS for a SKU | Contribution Profit is `UNAVAILABLE` for that line; Net Revenue still reported; seller prompted |
| E10 | SKU sold on multiple marketplaces | One cost master, per-marketplace P&L, consolidated account view |
| E11 | SKU cost changes mid-period | Weighted average as of `document_date` (D3) |
| E12 | Duplicate fee suspected (`V-FEE-002`) | Included once, flagged; both candidates disclosed; seller resolves |
| E13 | Discount bearer unknown | Seller-borne default, `DERIVED`, overridable (D2) |
| E14 | Marketplace-funded discount later recovered from the seller | Reclassified on settlement evidence; prior period restated with an audit entry |
| E15 | Cancelled after dispatch | Revenue reversed; forward logistics retained as a cost |
| E16 | Quarantined rows in a period | Excluded from totals; count and rule IDs disclosed on every figure |
| E17 | Zero-quantity row | Rejected by `V-QTY-001` unless a credit note |
| E18 | Report periods overlap across uploads | Deduplicated by natural key + content hash; never double-counted |
| E19 | Ad spend entered with zero net revenue in scope | Unallocatable; reported as an unallocated pool, not silently dropped |
| E20 | Non-INR currency | Rejected by `V-CUR-001` |

---

## 11. Production validation blockers

Extends `data-foundation.md` §9. Specific to this engine.

### Blocking — metric cannot ship

| # | Item | Blocks |
|---|---|---|
| C1 | ~~No cancellation representation~~ | **RESOLVED for Meesho** (A6). Open for Amazon and Flipkart until their real exports are inspected. |
| C2 | **No RTO representation exists in any reference file** (A7) | R6 — RTO revenue/inventory/logistics split is unimplementable |
| C3 | **Amazon settlement match keys unverified, and no real export validated** (`data-foundation.md` §5.1, §9) — the report family itself is specified (`amazon.settlement.v2`) | `REALIZED` state on Amazon, return treatment per R5, and Amazon leak detection — **pending validation, not categorically unsupported** |
| C4 | ~~Return refund amounts unobserved~~ | **RESOLVED for Meesho.** `TCS_Sales_Return` carries negative `total_taxable_sale_value` plus a `cancel_return` date, joined on `sub_order_num`. Net value = signed sum across both files — no separate reconciliation step needed. |
| C5 | **Advertising cost source undefined** | Ad reports have no adapter; only manual entry is currently possible |

### Must be validated — figures will change

| # | Item |
|---|---|
| C6 | ~~Tax-inclusive vs exclusive~~ | **RESOLVED** (A1). Basis is now declared per marketplace and per field. Meesho inclusive; Amazon MTR supplies both. |
| C7 | Amazon `Platform Fee` vs `Marketplace Fee Amount` (A2) — double-count risk straight into profit |
| C8 | ~~Meesho's three discount fields~~ — **superseded** (A3); those columns were synthetic |
| C9 | Discount bearer mapping per marketplace and component (A4, A5) |
| C10 | Per-line vs per-unit fee scaling on multi-quantity lines (A8) |
| C11 | Settlement join grain (A9) |
| C12 | Whether marketplace-funded discounts are ever later recovered from the seller (E14) |
| C13 | Fee refund behaviour on returns — which fees are returned, which are retained |
| C14 | **`cash_reconciliation` (§5.13.1) has no defined formula for `CASH_EXPECTED`/`CASH_RECEIVED`** — every other §5 metric states its formula explicitly; this one names only its inputs and outputs. Blocks implementing `cash_reconciliation` at all until the formula is confirmed (deferred, Category C). **Reconsidered and explicitly re-deferred (Phase D6 pass, 2026-09-25):** the economically correct definition of `CASH_EXPECTED` — revenue minus the fees/taxes that should legitimately be deducted — requires per-component INVOICE-side fee data (`FEE`/`TAX`/`LEVY` `line_component` rows), which no adapter in this codebase produces yet (the same gap `reconcile()`'s own Decision A, `calc_engine/api/reconcile.py`, already names and works around for `VARIANCE_EXCEEDS_TOLERANCE`). A simplified version (raw invoice total vs. settlement total) was considered and explicitly rejected — it would just restate `leak_amount()`'s existing line-level signal under a "cash flow" label, not add real information, and risks reading as more meaningful than it is. Decision: no partial `cash_reconciliation()` ships. Revisit once an invoice-side fee-component adapter exists. |
| C15 | **`hsn_gst_reference` (§8.2.2) ships with zero seed rows in this spec pass** — the table shape and resolution rule are defined here; real CBIC/GST Council-sourced rows are sourced and loaded in a following checkpoint. Until seeded, `resolve_hsn_gst_reference` always returns `None`, and OP13's tier (b) is a defined no-op — every line without an observed rate (tier a) falls straight through to the GST Applicability Lookup (tier c, §8.4). This is a correct, honest degraded state, not a bug: no rate is ever guessed in the gap. |

---

## 12. Acceptance criteria

The engine is accepted when all hold.

| # | Criterion |
|---|---|
| AC1 | Identical inputs produce byte-identical outputs across runs and machines. |
| AC2 | No calculation path invokes an LLM, network call, clock, or RNG. Date-relative figures take `as_of_date` as an explicit input (§4.2). |
| AC3 | All arithmetic is integer paise. No float appears in any calculation path. |
| AC4 | Marketplace-funded discounts provably do not reduce Net Realized Revenue (R2). |
| AC5 | Every returned metric carries state, confidence, calculation basis, formula version, input refs, and exclusions (R9). |
| AC6 | No manual input mutates a canonical table; source data is byte-identical before and after adjustment (R8). |
| AC7 | Displayed components reconcile exactly to displayed totals, including allocations (D8). |
| AC8 | A missing input yields `UNAVAILABLE`, never a silent zero. |
| AC9 | TCS and TDS never appear in Contribution Profit (D6). |
| AC10 | Output GST never appears in Net Realized Revenue (D4). |
| AC11 | Quarantined rows are excluded from totals and disclosed with counts and rule IDs. |
| AC12 | Amazon figures report `RECOGNISED`, never `REALIZED`, **while settlement match keys are unverified and no real export has validated the adapter** — not because the report family is absent (§5.1). |
| AC13 | A GST lookup result never alters a calculation without an explicit, recorded seller acceptance (L2). |
| AC14 | Every GST lookup result carries `source_url` and `retrieved_at`, or is discarded (L3). |
| AC15 | Confidence is monotonic: no aggregate exceeds its weakest input. |
| AC16 | Re-ingesting a file preserves all manual adjustments. |
| AC17 | A formula version change produces a new calculation run; historical results are unchanged. |
| AC18 | **NEW.** `compute_price_band` (§5.15.1) returns `UNAVAILABLE` with a named reason below 3 supplied competitor prices; computes `Q1`/`Q3` by linear-interpolation percentile only; computes fences from the **full** supplied set including outliers; excludes outliers **only** from the typical-range headline while still returning them flagged; uses integer paise throughout including the interpolation; and never returns better than `DERIVED`. **No percentile, IQR, fence or outlier arithmetic exists outside this engine** — in particular not in `packages/competitor-intelligence` (`competitor-intelligence-agent.md` §6.16.3, AC28). |
| AC19 | `resolve_hsn_gst_reference` (§8.2.2) returns `None` — never a guessed or defaulted rate — for any queried `hsn_code`/`as_of_date` combination with no matching row under the prefix rule, and is never applied retroactively past its `effective_to`. |
| AC20 | `hsn_gst_reference` (tier b, OP13) is checked only when the seller's own uploaded data carries no observed rate for that line/SKU (tier a), and the GST Applicability Lookup (tier c, §8.4) is invoked only when tiers a and b both miss — this ordering holds for every GST-rate resolution path in the engine. |
| AC21 | Any calculation using a rate resolved from `hsn_gst_reference` carries confidence no better than `PROVISIONAL` via the existing monotonic `combine_confidence` rule (`data-foundation.md` §7.1), and the resulting figure is labelled as using a curated-reference (not observed) rate, alongside §8.3's standing disclaimer. |

---

## 13. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | Clean prepaid sale, no discount | `NetRealizedRevenue = taxable value`; GST excluded |
| T2 | Seller-funded discount ₹500 | Revenue reduced by ₹500 |
| T3 | Marketplace-funded discount ₹500 | Revenue **unchanged**; ₹500 disclosed separately (AC4) |
| T4 | Discount with `bearer = UNKNOWN` | Treated as seller-borne, `DERIVED`, override available (D2) |
| T5 | Seller overrides T4 to `MARKETPLACE` | Revenue increases by the discount; source row unchanged; adjustment recorded (AC6) |
| T6 | Full return, refund settled | Revenue reversed in the **original** period; COGS released if inventory sellable |
| T7 | Partial return, 2 of 5 units | Revenue, COGS, and fees pro-rated by 2/5 (E2) |
| T8 | RTO, inventory recovered sellable | Revenue unrecovered; COGS **not** consumed; forward + reverse logistics charged (§5.7) |
| T9 | RTO, inventory damaged | Revenue unrecovered; COGS fully consumed; both logistics legs charged |
| T10 | Cancellation before dispatch | No revenue; no COGS; no logistics |
| T11 | Cancellation after dispatch | Revenue reversed; forward logistics retained (E15) |
| T12 | SKU with no COGS record | Contribution Profit `UNAVAILABLE`; Net Revenue still reported (E9, AC8) |
| T13 | SKU cost changed mid-period | Each line uses weighted average at its `document_date` (E11) |
| T14 | Account-level ad spend ₹10,000 across 3 SKUs | Allocated by net revenue share; parts sum exactly to ₹10,000 (AC7) |
| T15 | Ad spend with zero net revenue in scope | Reported unallocated, not dropped (E19) |
| T16 | Interstate row charging CGST+SGST | Quarantined by `V-TAX-001`; excluded; disclosed (AC11) |
| T17 | Amazon `Platform Fee` = `Marketplace Fee` = ₹50 | Counted once; both disclosed; flagged `V-FEE-002` (E12) |
| T18 | Amazon period request | Returns `RECOGNISED`; never `REALIZED` (AC12) |
| T19 | Meesho line, `Settlement Commission` > `Commission Fee` | Delta surfaced as a leak candidate; profit uses settlement side |
| T20 | Settlement arrives one period later | Attributed to original period; settlement date retained (E5) |
| T21 | Returns exceed sales in a period | Negative Net Realized Revenue reported as negative (E7) |
| T22 | `NetRealizedRevenue = 0` | Margin `UNDEFINED` (E8) |
| T23 | Same file uploaded twice | Deduplicated; totals unchanged (E18) |
| T24 | Re-ingest after adapter upgrade | Adjustments preserved and re-attached (AC16) |
| T25 | GST lookup returns 18% for a product | Stored `PROVISIONAL`; calculations unchanged until accepted (AC13) |
| T26 | GST lookup with ambiguous classification | `ambiguity_note` populated; alternatives shown; no single confident rate (L4) |
| T27 | GST lookup with no source URL | Discarded (AC14) |
| T28 | Formula version bump | New calculation run; prior results byte-identical (AC17) |
| T29 | Composition-scheme seller toggles fee GST to cost | Moves to `OtherAllocatedCosts`; recorded as manual input (D5) |
| T30 | Multi-quantity line, per-line vs per-unit fee | Behaviour matches declared adapter config; mismatch flagged (A8) |
| T31 | `compute_price_band` with 2 competitor prices | `UNAVAILABLE`, reason `INSUFFICIENT_COMPETITOR_PRICES` naming 2 supplied / 3 required; **no band values returned** (AC18, §5.15.1 rule 1) |
| T32 | `compute_price_band` with prices `[85000, 90000, 95000, 105000, 400000]` paise | `Q1`/`Q3` by linear interpolation over **all five** values; `IQR = Q3 − Q1`; fences at `Q1 − 1.5×IQR` / `Q3 + 1.5×IQR`; `400000` returned flagged `is_outlier = true`; `PRICE_BAND_TYPICAL_LOW/HIGH` = `85000`/`105000`, excluding the outlier only from the headline (AC18, rules 5–7) |
| T33 | `compute_price_band` run twice on an identical input tuple | Byte-identical `metric_result` rows; integer paise throughout with no float in the interpolation; result not part of `canonical_data_version` (AC1, AC3, AC18, rules 8 and 11) |
| T34 | `compute_price_band` where every supplied price is `DERIVED` (the only case CI can produce) | Result confidence is `DERIVED`; never `VERIFIED` or `PROVISIONAL` (AC15, rule 9) |
| T35 | Line with no observed GST rate; queried `hsn_code` exactly matches a seeded `hsn_gst_reference` row effective as of `as_of_date` | Rate resolved from that row; result confidence capped at `PROVISIONAL`; figure labelled as a curated-reference rate (AC19, AC21, §8.2.2) |
| T36 | Line queried with an 8-digit `hsn_code`; table holds only a 4-digit chapter-level row as a prefix | 4-digit row matches by prefix rule 1; resolved (§8.2.2 matching rule) |
| T37 | Line queried with a 2-digit `hsn_code`; table holds only 6- and 8-digit rows under that chapter | `None` returned — queried code shorter than every candidate row (§8.2.2 matching rule 4); falls through to GST Applicability Lookup (AC20) |
| T38 | Line with an observed GST rate present in the seller's own report | `hsn_gst_reference` never consulted; observed rate used as-is (tier a precedence, AC20) |
| T39 | `hsn_gst_reference` empty (no rows seeded, C15) | Every unobserved line falls through to the GST Applicability Lookup; no rate guessed in the gap (C15) |

---

## 14. Decisions requiring your review

### Design recommendations awaiting approval

| # | Decision | My recommendation |
|---|---|---|
| D1 | Revenue recognition point | Dual-state: `RECOGNISED` at invoice, `REALIZED` at settlement. Amazon stays `RECOGNISED` until its settlement match keys are verified against a real export (§5.1). |
| D2 | Unknown discount bearer | Default seller-borne (conservative), flagged, overridable. |
| D3 | Costing method | Weighted average per SKU, effective-dated. FIFO is not supportable from upload-only data. |
| D4 | Profit basis | Tax-exclusive throughout. |
| D5 | GST on fees | Separate "potentially creditable" line, with a toggle for sellers who cannot claim ITC. |
| D6 | TCS / TDS | Excluded from Contribution Profit; shown in cash-flow views only. |
| D7 | Allocation basis | Net revenue share by default; configurable. |
| D8 | Rounding | Integer paise, half-up, largest-remainder reconciliation. |

### Matters needing your attention

1. **A1 is resolved, and the answer was "it varies."** Basis is now declared per marketplace and per field (§8.1): Meesho inclusive, Amazon MTR supplying both. The residual risk is narrower — Flipkart's per-field basis remains unverified pending a real export.

2. **R4 and R6 cannot be implemented today.** No reference file represents cancellations (C1) or RTO (C2). Both rules are fully specified and will work once real data shows how those states are encoded — but neither can ship on synthetic data.

3. **Advertising cost has no data source** (C5). V1 supports manual entry only. A marketplace ad-report adapter is not in scope and would need its own specification.

4. **D6 is a judgement worth confirming explicitly.** Excluding TCS/TDS from profit is correct accounting, but sellers frequently *experience* them as losses because they reduce the money that arrives. The engine treats them as cash-flow items; the CFO agent will need to explain that difference clearly, or the numbers will look wrong to users who are used to reading their settlement statements.

**Awaiting your approval on D1–D8 before proceeding to the next specification.**
