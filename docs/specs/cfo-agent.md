# Metrion — CFO Agent Specification

**Status:** Draft for review
**Prerequisites:** `deterministic-engine.md` (the single canonical source of all margin and P&L math) · `data-foundation.md` (canonical model, reconciliation outcomes, provenance) · `auth.md` (permissions, entitlement)
**Related, not yet written:** entitlement spec · `whatsapp-integration.md`

**CFO interprets. Brain 1 calculates.** Every figure this agent presents — margin, profit, fee, tax, variance, leak amount — is produced by `deterministic-engine.md`. It decides *what to ask the engine*, and explains *what the answer means*.

**The boundary is formulas, not tables.** CFO owns interpretation artefacts and output schemas, and those legitimately hold money columns copied from engine results. What CFO must never contain is a **financial calculation** — no formula, no rate table, no arithmetic over figures, no local approximation of anything `deterministic-engine.md` owns.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| C1 | **Brain 1 is the single canonical calculation source.** CFO must not redefine, reimplement or locally approximate any margin or P&L math. | readiness §1 — Calculation ownership |
| C2 | **Leak Shield is a capability inside CFO**, not a separate agent. The V1 agent count stays at four plus CEO. | readiness §1 — Leak Shield ownership |
| C3 | **Leak Shield scope:** reconciliation of orders, settlements, returns and logistics (logistics where the seller supplies the data); anomaly detection; recoverable-money identification. | readiness §1 — Leak Shield ownership; planning doc p.8 |
| C4 | **GST is management-grade decision support only.** Not filing-grade. No statutory filing, no guaranteed compliance, no final ITC determination. | `deterministic-engine.md` §1.3 |
| C5 | **GST rate source is layered** — observed from the seller's own reports first, then the curated HSN knowledge base, then the GST Applicability Lookup (provisional, cited). Sellers are never asked to upload rate schedules. | OP13 |
| C6 | **GST Applicability Lookup is a shared service**, callable directly. Results never enter a calculation without explicit seller acceptance. | OP7, OP9; `deterministic-engine.md` §8.4 |
| C7 | **Recommend-only.** CFO proposes prices and actions; it never writes to a marketplace and never files a claim. | readiness §1 — Write-back (recommend-only) |
| C8 | **Expense and cash-flow inputs arrive by manual entry, report upload, or an agent-initiated data request.** Where CFO lacks data it asks the seller rather than assuming. | OP1 |
| C9 | **Star topology.** CFO is reached conversationally only through CEO. It may call Brain 1 and the GST Applicability Lookup directly as shared services, and may be invoked through registered direct execution paths. | readiness §1 — Topology and Execution paths; `auth.md` §5.2 |
| C10 | **CFO owns supplier *ranking*, from seller-provided quotes only.** PI discovers suppliers; CFO never discovers them. | readiness §1 — Supplier ownership |
| C11 | **TCS and TDS are cash-flow items, never P&L items.** They are prepaid taxes recoverable against the seller's liability, not costs. | `deterministic-engine.md` D6 |
| C12 | **Entitlement:** CFO is a paid cart item. `agent.cfo` gates permission; the cart gates entitlement; both must pass. **The free-tier preview *shape* is NOT confirmed** — readiness 3.4 classifies it `[P]`, awaiting explicit product approval. See D8 and Q6. | readiness §1 — Agent cart; `auth.md` §7.2 |
| C13 | **Anomaly detection is statistical at V1.** No trained models. Runs only where the seller has uploaded data. | OP6 — anomaly detection |
| C14 | **Funding readiness ships in V1** under the flat merge. Its *output definition* remains open — see Q3. | readiness §1 — Versioning (flat merge); output definition open at readiness 2.25 |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Leak classification ownership | Brain 1 emits `reconciliation_exception` rows; **CFO classifies them into leak categories and prioritises** | Classification is interpretation, not arithmetic. The amounts stay in the engine. |
| D2 | "Recoverable" language | Report **discrepancy identified**, never "money you will get back" | Recovery depends on marketplace claim processes and windows Metrion does not control (C7). Over-claiming here destroys trust fastest. |
| D3 | Claim-window awareness | Surface the age of each finding prominently, and order by **age against a configurable window**, not by amount alone | A ₹400 leak expiring in three days outranks a ₹4,000 leak with ninety days left. |
| D4 | Pricing recommendation output | A **margin curve across candidate prices**, not a single "optimal price" | The engine can compute margin at any price; it cannot know the seller's volume elasticity. Presenting one number implies knowledge we lack. |
| D5 | Expense granularity | Per-period pools by default, per-SKU where the seller supplies it | Most sellers know monthly ad spend, not per-SKU. Forcing precision produces invented data. |
| D6 | Cash-flow basis | **Settlement receipts**, not invoice dates | Cash flow answers "when does money arrive", which is a settlement question. |
| D7 | Funding-readiness shape | A **data-completeness and metric-readiness report**, not a score | A score implies a lending judgement Metrion is not qualified to make. See Q3. |
| D8 | Free-tier preview shape | Headline total + affected count + **one finding revealed in full**, rest locked | **Provisional** (readiness 3.4, `[P]`). Costs nothing because the reconciliation already ran, and demonstrates the analysis is real. Awaits product approval. |
| D9 | Batch-size output | A **budget-constrained order-quantity range** with stated assumptions, never a demand forecast | Sales velocity is observable; demand is not. See §6.12. |
| D10 | Leak severity and ordering | Computed **deterministically** from engine amounts, ages and window status; the LLM narrates the order, never decides it | §7.2 forbids the LLM performing arithmetic, and ordering by amount is arithmetic. |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | A seller's uploaded reports cover a contiguous period sufficient for reconciliation | Medium — gaps produce false "missing settlement" findings |
| A2 | Settlement lag per marketplace is knowable from observed data | **High** — drives `UNSETTLED_BEYOND_LAG`; a wrong lag manufactures phantom leaks |
| A3 | Marketplace claim windows are discoverable and roughly stable | Medium — D3 prioritisation depends on it |
| A4 | Sellers can supply COGS per SKU | **High** — without it Contribution Profit is `UNAVAILABLE` |
| A5 | Ad spend is available at least at account level | Medium — otherwise ROAS/ACOS/TACOS cannot be produced |

---

## 4. Goals and non-goals

**Goals** — answer financial questions using Brain 1 exclusively; reconcile invoiced against settled and surface discrepancies with recoverable value; detect statistical anomalies in margin, fees and settlement behaviour; produce indicative GST summaries; recommend selling prices as a margin curve; track expenses and cash flow from seller-supplied inputs; rank suppliers from seller quotes; estimate budget-constrained order quantities; assemble funding-readiness material.

**Non-goals (V1)** — performing any financial calculation itself · holding fee rates · filing GST returns or determining ITC eligibility · filing marketplace claims · writing to any marketplace · discovering suppliers · trained ML models · giving investment, lending or legal advice · bank-account integration · forecasting demand or sell-through · **defining the billing meter** (§7.3) — owned by the entitlement, metering and billing spec.

---

## 5. Data model and interfaces

CFO defines **no manual-input store of its own.** Every seller-supplied financial value flows through the single `manual_adjustment` store defined in `deterministic-engine.md` §7.1 — append-only, superseding, re-attached by natural key on re-ingest, and never overwriting source data. **Engine §7.2.1 is the authoritative field registry**; CFO never invents a field name.

CFO owns only **interpretation artefacts** and **derived read models**.

```sql
leak_finding (                            -- interpretation of an engine exception
  id uuid pk, tenant_id uuid not null,
  reconciliation_exception_id uuid not null,   -- engine-owned; amount lives there
  engine_result_ref uuid not null,             -- deterministic-engine.md §9.1
  marketplace text not null,
  leak_category text not null,          -- §6.3; maps from data-foundation.md §5.2 outcomes
  severity text not null,               -- HIGH | MEDIUM | LOW — from rank_findings (engine §5.14.1)
  amount_paise bigint not null,         -- COPIED from the exception, never recomputed
  affected_line_count int not null,
  sku text,
  first_observed_at timestamptz not null,
  age_days int not null,                -- from rank_findings, relative to an explicit as_of_date (engine §4.2)
  claim_window_days int,                -- configurable per marketplace; null when unknown
  window_status text,                   -- OPEN | CLOSING_SOON | EXPIRED | UNKNOWN
  explanation text,                     -- Brain 3; contains no number the LLM produced
  recommended_action text,
  status text not null,                 -- NEW | ACKNOWLEDGED | ACTIONED | DISMISSED
  confidence text not null,             -- §5.2 vocabulary
  formula_version text not null
)

cash_view (                               -- DERIVED read model. Not a store, not manual input.
  tenant_id, marketplace, period,
  settlement_ref,
  expected_paise, received_paise, variance_paise,   -- all engine-computed
  expected_date, received_date,
  tcs_paise, tds_paise,                 -- C11: shown here, never in P&L
  engine_result_ref uuid not null,      -- one per computed figure; see the grain note below
  confidence text not null,             -- MANUAL where a settlement.receipt correction applies
  source text not null                  -- REPORT | REPORT_WITH_CORRECTION
)
```

**Provenance grain.** `engine_result_ref` identifies **one computed figure**, not one row. A view exposing several computed figures carries one reference per figure; AC1b is satisfied per figure, never per row.

**Removed by design.** Earlier drafts defined `expense_entry`, `cash_event` and `supplier_quote` as CFO-owned tables. They duplicated `manual_adjustment` and fragmented the guarantee that manual input never overwrites source data. All three are now `manual_adjustment` field types:

| Seller input | Stored as |
|---|---|
| Advertising spend, packaging, storage, logistics, other pools | `manual_adjustment` field `expense.<category>` (engine §7.2.1) |
| Settlement receipt correction where a report is missing or disputed | `manual_adjustment` field `settlement.receipt` (engine §7.2.1) |
| Supplier quote (cost, MOQ, lead time, shipping, terms, reliability) | `manual_adjustment` field `supplier.quote` (engine §7.2.1) |
| COGS, discount bearer, RTO outcome, cancellation flag, fee-GST toggle | `manual_adjustment` (engine §7.2.1, unchanged) |

```sql
agent_data_request (                      -- OP1: CFO asks rather than assumes
  id uuid pk, tenant_id uuid not null,
  requested_field text not null, reason text not null,
  blocking_metric text,                 -- what cannot be computed without it
  status text not null,                 -- OPEN | ANSWERED | DECLINED
  answered_with_kind text,              -- MANUAL_ADJUSTMENT (only target type in V1)
  answered_with_id uuid,
  created_at timestamptz not null
)
```

**Note:** the agent-initiated data-request *flow* — how a request is surfaced, prompted and validated — is deferred cross-cutting work (readiness 2A.13). This spec defines only the record CFO writes; the interaction belongs to the orchestration spec. See Q9.

### 5.1 Interfaces CFO calls

| Interface | Owner | Purpose |
|---|---|---|
| `compute_metric(metric_code, grain, target, period)` | `deterministic-engine.md` §5 | All revenue, profit, margin, fee and tax figures |
| `reconcile(period, marketplace, tolerance_ref)` | Brain 1 (engine §5.13.1); model in `data-foundation.md` §5 | Produces `reconciliation_exception` rows, each with a `LEAK_EXCEPTION_AMOUNT` result |
| `leak_aggregate(period, marketplace, grouping)` | Brain 1 (engine §5.13.1), `metric_code = LEAK_TOTAL` | Headline totals (§6.4); CFO never sums |
| `rank_findings(exception_ids[], as_of_date, severity_config_ref)` | Brain 1 (engine §5.13.1, §5.14.1) | Severity, `age_days`, `window_status` and order — all deterministic (D10), on an explicit `as_of_date` (engine §4.2) |
| `margin_curve(sku, candidate_prices[], period, as_of_date)` | Brain 1 (engine §5.13.1), `metric_code = MARGIN_AT_PRICE` | Pricing recommendation (§6.7) |
| `cash_reconciliation(period, marketplace, as_of_date)` | Brain 1 (engine §5.13.1) | `cash_view` figures (§5, §6.10) |
| `landed_cost(manual_adjustment_ref, sku, quantity)` | Brain 1 (engine §5.13.1), `metric_code = LANDED_COST_PER_UNIT` | Supplier ranking (§6.11) and batch size (§6.12) |
| `funding_readiness_metrics(period_range, as_of_date)` | Brain 1 (engine §5.13.1) | Funding readiness (§6.13); emits no score |
| `resolve_fee_reference(marketplace, category, fee_type, as_of_date)` | Brain 1 (engine §5.13.1, §5.14) | CFO never holds rates (C1) |
| `estimate_competitor_margin_range(...)` | Brain 1 (engine §5.13, §5.13.1) | Only when comparing against CI-supplied observations |
| `detect_anomalies(series, method)` | **Brain 2 — specification not yet written** (readiness §7 item 8). CFO consumes it; it does not define it. See Q10 | Statistical outliers; no trained models (C13) |
| `gst_applicability_lookup(product, hsn?)` | Shared service, engine §8.4 — **requires `service.gst_lookup`** (`auth.md` §5.2), independent of `agent.cfo`, with its own OP9 cap | Research only; never auto-applied (C6) |

**CFO writes no number it did not receive from one of these.** Provenance follows the two contracts in `deterministic-engine.md` §9.1:

- **Financial figures** carry an `engine_result_ref` (`metric_result.id`).
- **Estimated competitor ranges** carry an `estimate_ref` (`competitor_estimate.id`). They are never written to `metric_result` (engine §5.13 rule 5), so they never carry an `engine_result_ref`, and CFO must not imply they do.

### 5.2 Confidence vocabulary

CFO renders figures from two sources with different vocabularies and must not blur them:

| Source | Vocabulary | Rule |
|---|---|---|
| Brain 1 results | `VERIFIED \| PROVISIONAL \| DERIVED \| MANUAL` (engine §9, ranked at `data-foundation.md` §7.1) | Used as returned |
| CI-supplied observations | `OBSERVED \| DERIVED \| UNAVAILABLE` (`competitor-intelligence-agent.md` §5.1) | Always enters Brain 1 as `DERIVED`; CFO never renders `OBSERVED` |

Allocated pools are always `DERIVED` (engine §5.10). Confidence remains monotonic throughout.

---

## 6. Core rules

### 6.1 Question handling

1. CEO routes a financial question to CFO, or a registered direct execution path invokes a named CFO action.
2. CFO selects the deterministic tool and parameters. **It does not compute.**
3. Brain 1 returns figures with basis, confidence, exclusions and version stamps.
4. Brain 2 supplies anomaly flags where the question is about change or irregularity.
5. CFO composes the explanation (§7).
6. Missing inputs produce an `agent_data_request`, never an assumed value (C8).

### 6.2 Leak Shield — reconciliation

Runs over the canonical model; the arithmetic belongs to Brain 1.

| Input | Source |
|---|---|
| Orders / invoices | `sales_line` + `line_component` (`source_side = INVOICE`) |
| Settlements | `settlement_line` + `line_component` (`source_side = SETTLEMENT`) |
| Returns | Return and credit-note rows; Meesho `TCS_Sales_Return` negatives |
| Logistics | Marketplace-reported where present, else seller-supplied (C3, manual input) |

**The core signal** is the invoice-side vs settlement-side delta per `component_code` (`data-foundation.md` §5.4).

**Meesho is the strongest V1 target — provisionally.** Per `docs/Metrion_PnL_and_MTR_Mapping_FINAL.pdf`, Meesho's real Supplier Panel exports carry invoice-side revenue fields (`Fixed Fee (Incl. GST)`, `Warehousing fee (incl GST)`, `Return premium (incl GST)`) alongside settlement-side values (`Final Settlement Amount` and its documented 18-term formula), joinable on `sub_order_num`. The earlier justification cited the synthetic co-located columns, which `data-foundation.md` §0 and §2.3 retract. **Column-level pairing is not yet validated against a live export** — see V6.

**Amazon status (corrected).** Amazon settlement is **specified**, not absent: `data-foundation.md` §0.6 and §2.3 register `amazon.settlement.v2` from Amazon SP-API documentation. Amazon is therefore **not categorically unsupported**.

What remains open is narrower: **settlement match keys are unverified** (`data-foundation.md` §5.1 lists Amazon's join key as UNKNOWN) and **no real Amazon export has validated the adapter**. Until both close, Amazon periods report `RECOGNISED` and Leak Shield findings for Amazon are withheld — because the join cannot yet be trusted, not because the data does not exist.

CFO states that distinction explicitly. A withheld result is never rendered as "no leaks found."

### 6.3 Leak categories

Classification is CFO's; amounts are the engine's (D1).

| Category | Meaning |
|---|---|
| `FEE_OVERCHARGE` | Settlement-side fee exceeds invoice-side beyond tolerance |
| `SHORT_SETTLEMENT` | Settled value below expected beyond tolerance |
| `MISSING_SETTLEMENT` | Invoiced, unsettled beyond lag + grace |
| `UNEXPECTED_DEDUCTION` | Settlement-side component with no invoice-side counterpart |
| `RETURN_NOT_CREDITED` | Return processed, refund or fee reversal absent |
| `TCS_TDS_MISMATCH` | Collected amount disagrees with the seller's own records |
| `DUPLICATE_DEDUCTION` | Same charge applied more than once |

### 6.4 Recoverable-money identification

1. Each finding carries the engine's amount, affected line count, and age.
2. Findings are ordered by **claim-window urgency first, amount second** (D3). **Ordering, `severity`, `age_days` and `window_status` all come from `rank_findings`** (engine §5.13.1), which takes an explicit `as_of_date` (§4.2) and resolves bands from `severity_config` (§5.14.1). Brain 3 narrates the resulting order and never produces it.
3. Language is *discrepancy identified*, never *money you will get back* (D2).
4. CFO produces a recommended action — typically "raise a claim with marketplace X citing these order IDs" — but **never files it** (C7).
5. **Aggregate totals are computed by Brain 1** via `leak_aggregate` (engine §5.13.1, `metric_code = LEAK_TOTAL`), never by CFO summing in application code, and carry their own `engine_result_ref` (§7.2 forbids CFO arithmetic, including summation).
6. The headline total **excludes levy-derived findings** (`TCS_TDS_MISMATCH`), or labels them separately — a levy variance is a cash-reconciliation item, not recoverable margin.

### 6.5 Anomaly detection (C13)

Statistical only: z-score, period-over-period delta, percentile thresholds over margin, fee ratio, settlement lag and return rate. Runs only where uploaded data exists. Below the minimum series length, anomaly detection reports insufficient history rather than firing on noise. **Forecasting is out of scope here** — it is gated at 6 complete months (readiness §1, Intelligence and data — Forecasting) and belongs to the forecasting surface.

### 6.6 GST (C4, C5, C6)

**Included:** inclusive/exclusive normalisation per marketplace *and per field* · IGST/CGST/SGST/UTGST/Cess handling · TCS and TDS visibility · indicative period summary · GST-on-fees shown as a separate potentially-creditable line.

**Rate resolution order (OP13):** observed from the seller's own reports → curated HSN knowledge base → GST Applicability Lookup (provisional, cited, never auto-applied).

**Every GST surface carries:** *"Indicative management summary. Not a GST return. Not filing-grade. Verify with your tax professional."*

**Never:** statutory filing, guaranteed compliance, final ITC eligibility, or a claim that a figure is return-ready.

### 6.7 Pricing recommendations

1. CFO requests margin at candidate price points from Brain 1, which resolves fees from §5.14.
2. Output is a **margin curve with a recommended band**, not a single optimal price (D4).
3. Where CI has supplied competitor observations, the competitor's estimated range may be shown alongside — clearly labelled estimated, never as their actual margin.
4. Every recommendation states its assumptions: COGS basis, fee reference version, GST treatment, and what was unavailable.
5. Recommend-only (C7). No marketplace write, ever.

### 6.8 Registered direct execution paths (B4)

Per the `auth.md` §5.2 guardrail, every direct path is enumerated here, names one action and one key, and accepts no free-form input. **There is no generic "invoke CFO" endpoint.**

| Trigger id | Action | CEO call | Permission | Entitlement gate | Rate limit | Audit |
|---|---|---|---|---|---|---|
| `cfo.preview` | Render the free-tier gated preview (§6.9) | No | `agent.cfo` | **Passes permission, then intentionally bypasses the entitlement denial** — see below | Per tenant, low | Yes |
| `cfo.reconcile` | Run reconciliation for a period and marketplace | No | `agent.cfo` | CFO entitlement + run credit | Per tenant | Yes |
| `cfo.pnl` | Compute P&L for a period | No | `agent.cfo` | CFO entitlement + run credit | Per tenant | Yes |
| `cfo.pricing` | Produce a margin curve for a SKU | No | `agent.cfo` | CFO entitlement + run credit | Per tenant | Yes |
| `cfo.gst_summary` | Render the indicative GST summary | No | `agent.cfo` | CFO entitlement | Per tenant | Yes |
| `cfo.gst_lookup` | Invoke the GST Applicability Lookup | No | `agent.cfo` **and** `service.gst_lookup` | Shared-service cap (OP9), independent of CFO entitlement | Per tenant, strict | Yes |
| `cfo.batch_size` | Budget-constrained order-quantity range (§6.12) | No | `agent.cfo` | CFO entitlement + run credit | Per tenant | Yes |
| `cfo.funding_readiness` | Assemble the funding-readiness report (§6.13) | No | `agent.cfo` | CFO entitlement | Per tenant, low | Yes |

Anything open-ended — "why did my profit drop?" — is **conversational**, requires `agent.ceo` plus `agent.cfo`, and is not a direct path.

**The preview and the entitlement gate.** `auth.md` E19/T9 state that a member holding `agent.cfo` in a tenant without CFO entitlement is **denied by entitlement**. The preview does not contradict that: the *CFO capability* is still denied. What `cfo.preview` returns is a deliberately reduced surface that the entitlement layer serves **in place of** the denial, not instead of evaluating it.

Every step of the `auth.md` §7.1 chain still runs, including permission (`agent.cfo`). **There is no un-permissioned path.** A member without `agent.cfo` gets `403`, entitled or not.

**Status: provisional** (D8, readiness 3.4). Whether an entitlement denial may return a reduced payload rather than an error is an entitlement-spec decision, not a CFO one — see Q6 and Q13.

### 6.9 Free-tier gated preview — PROVISIONAL (D8)

**Status: provisional.** readiness 3.4 classifies the preview shape `[P]`, awaiting explicit product approval. Specified here so the surface exists; the shape may change. A tenant without CFO entitlement sees:

- The **headline recoverable-discrepancy total** and the affected SKU count
- **One finding revealed in full**, with its arithmetic
- The remainder locked

The reconciliation is deterministic and already computed, so revealing one costs nothing and demonstrates the analysis is real rather than asserted.

**Run cadence is not decided here.** Automatic computation for un-entitled tenants has a cost and an entitlement implication; the trigger and refresh interval belong to the entitlement spec. See Q6.

### 6.10 Expense and cash-flow tracking (C8)

**Input paths (OP1):** manual entry · report upload · agent-initiated data request. All manual values are written as `manual_adjustment` rows (§5) under the engine's append-only, superseding discipline — CFO adds no store and no second rule.

**Expenses** feed the engine's cost components. Account-level pools are allocated per engine §5.10 and always carry `DERIVED` confidence.

**Cash flow** is settlement-based (D6): expected vs received, variance, and timing. TCS and TDS appear **in cash surfaces only, never in P&L** (C11) — including where a `TCS_TDS_MISMATCH` finding surfaces a levy variance, which is a cash-reconciliation item and is excluded from the recoverable-discrepancy headline (§6.4.6). CFO must explain that levies reduce cash received without reducing profit, because sellers routinely read them as losses.

**Bank data is out of scope.** Cash flow is reconstructed from settlements and seller input, not from a bank feed. See **Q1**.

### 6.11 Supplier ranking (C10)

Ranks **only** on seller-supplied `supplier.quote` manual adjustments (engine §7.2.1) — unit cost, MOQ, lead time, shipping, payment terms, reliability notes. Landed cost per unit is computed by Brain 1. CFO never discovers suppliers and never scores a supplier it has no quote for.

### 6.12 Batch size (readiness §1 — Batch size; 2A.3)

Assigned to CFO by the locked decision record. **Estimate only.**

| | |
|---|---|
| **Inputs** | Sales velocity from uploaded reports (observed) · seller-entered lead time and MOQ (`supplier.quote`) · **budget ceiling (`batch.budget`, engine §7.2.1)** · landed cost from Brain 1 |
| **Output** | A **budget-constrained order-quantity range** with the assumptions that produced it |
| **Never** | A demand forecast, a guaranteed sell-through, or a claim about future volume (D9) |

**Limitations, stated on every output:**

- For a SKU the seller has **never sold**, there is no velocity — the estimate degrades to a budget-and-MOQ arithmetic exercise and must say so (readiness 2A.3, "budget-constrained quantity estimate for new products with no sales history").
- Velocity from a short history is not seasonality-adjusted. Indian festive distortion is severe enough that a two-month window can mislead badly.
- Lead time and MOQ are seller-declared; they are not verified.

Where velocity is unavailable and the seller has not supplied lead time or MOQ, CFO raises an `agent_data_request` rather than assuming values.

### 6.13 Funding readiness (C14)

Ships in V1; **output definition is open (Q3)**. What it can honestly be assembled from today:

- Contribution Profit history and trend, with data-completeness stated
- Margin stability, revenue concentration by SKU and marketplace
- Cash-conversion timing from settlement data
- Explicit gaps — periods missing, COGS absent, marketplaces unreconciled

**Never:** a lending score, a valuation, an investment recommendation, or any claim of accounting-grade accuracy (D7).

---

## 7. AI requirements — brain assignment and compute-intensity characteristics

### 7.1 The split

| Brain | Technology | CFO responsibilities |
|---|---|---|
| **Brain 1** | Python + SQL, **no LLM** | Every number: revenue, margin, Contribution Profit, fees, GST, reconciliation variance, leak amounts, landed cost, margin curves, allocation |
| **Brain 2** | Statistical, no trained models (C13) | Anomaly flags, outlier scores, trend deviation, settlement-lag irregularity |
| **Brain 3** | LLM | Understanding the question, selecting the tool and parameters, classifying findings, **prioritisation as judgement** (which finding matters most to this seller and why), and **explaining results in natural language**. **Ranking is not judgement** — ordering by amount, age or window status is arithmetic and is computed deterministically (D10). Brain 3 narrates the computed order; it never produces it. |

### 7.2 What the LLM may never do

1. Produce, adjust, round, estimate or "sanity-check" any number.
2. Perform arithmetic, including apparently trivial arithmetic, on figures in its context.
3. Decide a GST rate. Rates come from OP13's layered source.
4. Infer a fee rate. Rates come from engine §5.14.
5. Summarise raw rows. Files are aggregated by SQL first (OP5) — the LLM never sees 10,000 rows.

Every number in a CFO response traces to an `engine_result_ref`. A figure the LLM cannot trace is a defect, not a rounding difference.

### 7.3 Compute-intensity characteristics, and what they do and do not decide

The planning document (p.17) ranks CFO as the heaviest token consumer — *"CFO consume more token like Claude opus. Then CI → PI."* **That ranking does not follow from this specification.** What follows is a technical characterisation; it is deliberately *not* a billing decision.

#### 7.3.1 The technical position

CFO is the **most deterministic agent in the system**:

| CFO work | Where it runs | Model context consumed |
|---|---|---|
| Reconciliation across orders, settlements, returns, logistics | Brain 1 | **None** |
| Margin, profit, GST, fee, variance, landed cost | Brain 1 | **None** |
| Anomaly detection | Brain 2 | **None** |
| Margin curve across candidate prices | Brain 1 | **None** |
| Understanding the question, choosing the tool | Brain 3 | Small, roughly fixed |
| Explaining the result | Brain 3 | Small, proportional to the answer |

**The decisive property: CFO's model-context cost does not scale with the seller's data volume.** A 10,000-row MTR and a 50-row one produce the same explanation length, because SQL aggregates before any model is involved (OP5, 2B.8). PI and CI behave differently — their work scales with *fetched content*: pages, listings, reviews, all of which enter model context during derivation.

So the expected ordering by **model/context workload** is approximately **PI ≳ CI > CFO**. This is a projection, not a measurement: **PI has no specification yet**, and CI's figure depends on derivation volume. It should be re-checked against real usage before anything downstream relies on it.

#### 7.3.2 What this ordering is *not*

**It is not a statement about billable token cost**, and must not be read as one:

- CI's review and listing derivation is **local-only** (`competitor-intelligence-agent.md` C15) and never reaches a hosted provider, so CI's highest-volume model work generates **no billable hosted tokens at all**.
- Local compute has real cost — hardware, latency, throughput — but it is not metered the way hosted tokens are.
- The two axes therefore diverge: an agent can be context-heavy and billing-light, or the reverse.

Any comparison that conflates the two is wrong in both directions.

#### 7.3.3 Recorded input for the entitlement, metering and billing specification

**CFO does not decide the billing meter.** Whether the product meters agent runs, credits, tokens, context-weighted units, or something else is owned entirely by the **entitlement, metering and billing specification** — readiness §7 item 3, not yet written, referred to throughout this document by that description rather than by a filename. (readiness 2B.12, §5, Verdict; readiness 3.3 defers pricing values to pre-launch.)

This spec contributes two findings, as **input and constraint**, not as requirements on CFO:

| # | Recorded input | Why it matters downstream |
|---|---|---|
| **I1** | CFO's model-context cost is **flat with respect to seller data volume**; its value scales with data volume. | A meter keyed purely to model context would price the system's most valuable agent as its cheapest. The billing spec should weigh this. |
| **I2** | Compute intensity and billable cost are **different axes** (§7.3.2), and CI demonstrates the divergence. | A single meter may not describe all four agents well. |

These are observations for the billing spec to weigh against commercial factors this document has no view on. **No metering basis, unit or prohibition is established here.**

---

## 8. Authorization and security rules

1. Every CFO request enters the `auth.md` §7.1 six-step chain. No path bypasses it.
2. **Permission and entitlement are separate gates** (`auth.md` §7.2). `agent.cfo` permits the member; the cart entitles the tenant. Both must pass. Where entitlement denies, the denial may be **rendered** as the §6.9 preview payload rather than a bare error — the capability is still denied (`auth.md` E19). Provisional; see Q13.
3. Conversational access requires `agent.ceo` **plus** `agent.cfo`. Registered direct execution paths require `agent.cfo` alone and are enumerated exhaustively in §6.8 (`auth.md` §5.2 guardrail). No generic "invoke CFO" endpoint exists.
3b. **The GST Applicability Lookup additionally requires `service.gst_lookup`** (`auth.md` §5.2), granted independently of `agent.cfo` and metered against its own OP9 shared-service cap. `agent.cfo` alone never authorises a lookup.
4. **Creating or superseding any manual financial input requires `financials.adjust`** (`auth.md` R1) — every field in the `deterministic-engine.md` §7.2.1 registry, including expense pools, settlement-receipt corrections, supplier quotes, COGS and data-request answers. Deny-by-default for PARTNER.
5. `agent_data_request` answers are manual inputs and carry the same permission and labelling rules. They never overwrite source data.
6. All queries are tenant-scoped; RLS is the final boundary. Background reconciliation jobs set tenant context from the job payload or fail closed.
7. Findings, manual adjustments and derived views are tenant-private. Cross-tenant access returns `404`.
8. Every figure displayed carries provenance under the correct contract (`deterministic-engine.md` §9.1): financial figures carry an `engine_result_ref`; estimated competitor ranges carry an `estimate_ref`. Both carry `formula_version`, confidence and exclusions.

---

## 9. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | Amazon period requested | `RECOGNISED`; Leak Shield findings withheld **pending match-key verification**, stated explicitly as pending — never rendered as "no leaks found" (§6.2) |
| E2 | No COGS for a SKU | Contribution Profit `UNAVAILABLE`; Net Revenue still reported; `agent_data_request` raised |
| E3 | No ad spend supplied | ROAS/ACOS/TACOS unavailable; margin unaffected; request raised |
| E4 | Uploaded period has gaps | Reconciliation runs on what exists; gaps named; no "missing settlement" fired inside a gap |
| E5 | Settlement lag unknown for a marketplace | `UNSETTLED_BEYOND_LAG` suppressed; reported as unknown rather than guessed (A2) |
| E6 | Claim window unknown | `window_status = UNKNOWN`; ordering falls back to amount (D3) |
| E7 | Finding exceeds the claim window | `EXPIRED`; retained and shown as **outside the marketplace's stated claim window**, on a window value that may itself be unverified (Q4). Metrion does not declare it unrecoverable — that is the marketplace's call (D2) |
| E8 | Quarantined rows in the period | Excluded from every total; count and rule IDs disclosed on each figure |
| E9 | Seller disputes a figure | CFO shows the arithmetic and source rows; disagreement is resolved by a labelled manual adjustment, never by editing source |
| E10 | Free tenant, findings exist | §6.9 preview: total, count, one revealed finding, rest locked |
| E11 | Free tenant, no findings | Says so plainly. Never manufactures a finding to drive upgrade |
| E12 | GST rate unavailable for a SKU | Normalisation fails for that line, flagged; the line is excluded rather than defaulted |
| E13 | Lookup returns an ambiguous GST classification | Alternatives shown with the disclaimer; nothing applied without explicit acceptance (C6) |
| E14 | Pricing request with no COGS | Margin curve cannot be produced; request raised rather than assuming a cost |
| E15 | Supplier ranking with one quote | Reported as a single quote, not a ranking |
| E16 | Anomaly series too short | Reports insufficient history; fires nothing (§6.5) |
| E17 | Negative Contribution Profit | Reported as negative, never floored |
| E18 | TCS/TDS present | Shown in cash view with the explanation that they do not reduce profit (C11) |
| E19 | Partner lacks `financials.adjust` but tries to enter an expense | `403`; viewing remains permitted |
| E20 | Engine formula version changes | Prior findings retain their stamped version; recomputation creates new results, never mutates old ones |
| E21 | Funding-readiness requested with thin data | Assembles what exists, names every gap; no score (D7, Q3) |

---

## 10. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| V1 | **Amazon settlement match keys unverified; no real Amazon export validated** (`data-foundation.md` §5.1, §9). The report family itself is specified | Leak Shield findings on Amazon, pending validation |
| V2 | Settlement lag per marketplace (A2) | `MISSING_SETTLEMENT`, `UNSETTLED_BEYOND_LAG` |
| V3 | Variance tolerances per marketplace and component | Every leak threshold |
| V4 | Claim windows per marketplace (A3) | D3 prioritisation, `window_status` |
| V5 | Fee reference store populated (engine §5.14) | Pricing recommendations, fee-overcharge detection |
| V6 | Real exports for all three marketplaces | Every adapter mapping remains unverified |
| V7 | Cancellation and RTO encoding for Amazon and Flipkart | Revenue accuracy; resolved for Meesho only |
| V8 | Funding-readiness output definition (Q3) | §6.13 beyond a data-completeness report |

---

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | CFO contains no financial formula, rate table or arithmetic over figures. |
| AC1b | Every **financial figure** traces to an `engine_result_ref` (`metric_result.id`). |
| AC1c | Every **estimated competitor range** traces to an `estimate_ref` (`competitor_estimate.id`) and never claims an `engine_result_ref`. |
| AC2 | No LLM output contains a number the LLM produced. |
| AC3 | Raw rows are never sent to an LLM; aggregation precedes explanation (OP5). |
| AC4 | Leak amounts are copied from engine exceptions, never recomputed. |
| AC5 | Where Amazon findings are withheld, the reason is stated as **pending match-key verification**, never rendered as zero findings and never as categorical non-support. |
| AC6 | No finding is described as recovered or guaranteed money (D2). |
| AC7 | Every GST surface carries the management-grade disclaimer. |
| AC8 | A GST lookup result never alters a calculation without recorded seller acceptance. |
| AC9 | TCS and TDS never appear in Contribution Profit. |
| AC10 | A missing input produces an `agent_data_request`, never an assumed value. |
| AC11 | Manual inputs never overwrite source data and always require `financials.adjust`. |
| AC12 | Pricing output is a curve or band; no single "optimal price" is asserted. |
| AC13 | Supplier ranking uses only seller-supplied quotes. |
| AC14 | Permission and entitlement are evaluated independently. |
| AC15 | Free-tier preview reveals exactly one finding and locks the rest. |
| AC16 | No finding is fabricated for an empty result set. |
| AC17 | CFO asserts no billing meter, unit or prohibition. §7.3 records inputs for the entitlement, metering and billing spec only. |
| AC17b | The GST Applicability Lookup requires `service.gst_lookup` and is metered against its own shared-service cap, independently of CFO entitlement. |
| AC17c | Every direct execution path is enumerated in §6.8 with its trigger, permissions, entitlement gate, rate limit and audit requirement. |
| AC17d | CFO defines no manual-input store; all seller-supplied values are `manual_adjustment` rows. |
| AC17e | Leak severity and finding order are computed deterministically; the LLM narrates but never decides them. |
| AC17f | Batch-size output is a range with stated assumptions and never asserts future demand. |
| AC18 | Every displayed figure carries provenance, confidence and exclusions. |
| AC19 | Funding readiness emits no score, valuation or lending judgement. |
| AC20 | Background reconciliation without tenant context fails closed. |

---

## 12. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | Meesho period with invoice and settlement fee deltas | Findings created; amounts equal engine exception amounts (AC4) |
| T2 | Amazon period requested | `RECOGNISED`; findings withheld with reason "pending match-key verification" (AC5) |
| T3 | Inspect CFO for margin arithmetic | None present (AC1) |
| T4 | Ask "why did profit drop?" | Brain 1 computes, Brain 2 flags, Brain 3 explains; no LLM-produced number (AC2) |
| T5 | 10,000-row upload, then a profit question | SQL aggregates first; LLM context contains no raw rows (AC3) |
| T6 | Compare model-context usage against a CI capture run | CFO materially lower and flat with data volume (§7.3.1); no billing conclusion asserted (AC17) |
| T6b | Inspect CFO for a billing meter, unit or prohibition | None present (AC17) |
| T31 | Invoke `cfo.gst_lookup` with `agent.cfo` but not `service.gst_lookup` | `403` (AC17b) |
| T32 | Invoke an unregistered direct CFO endpoint | `404`; no generic endpoint exists (AC17c) |
| T33 | Seller enters ad spend | Written as a `manual_adjustment` row; no CFO-owned store exists (AC17d) |
| T34 | Batch size for a never-sold SKU | Budget-and-MOQ range, explicitly flagged as having no velocity history (AC17f, §6.12) |
| T35 | Render a CI-sourced competitor range | Carries an `estimate_ref`, never an `engine_result_ref` (AC1c) |
| T7 | Finding 80 days old, 90-day window | `CLOSING_SOON`; ranked above a larger, fresher finding (D3) |
| T8 | Finding past its window | `EXPIRED`; retained and shown as **outside the marketplace's stated claim window** — never described as unrecoverable (E7, D2) |
| T9 | Claim window unknown | `UNKNOWN`; ordering falls back to amount (E6) |
| T10 | SKU with no COGS | Contribution Profit `UNAVAILABLE`; data request raised (E2, AC10) |
| T11 | Partner without `financials.adjust` enters an expense | `403`; viewing still allowed (E19) |
| T12 | Partner with the permission enters ad spend | Accepted; `entered_by` recorded; source data untouched (AC11) |
| T13 | Free tenant with findings | Total, count, one full finding, rest locked (AC15) |
| T14 | Free tenant with no findings | Says so; nothing fabricated (AC16) |
| T15 | GST summary rendered | Disclaimer present (AC7) |
| T16 | GST lookup returns 18%, seller does not accept | Calculations unchanged (AC8) |
| T17 | Period containing TCS | Appears in cash view only; absent from profit (AC9) |
| T18 | Pricing request | Margin curve with stated assumptions; no single optimal price (AC12) |
| T19 | Pricing request with no COGS | Refused with a data request, not an assumed cost (E14) |
| T20 | Supplier ranking with three quotes | Ranked on landed cost from Brain 1 (AC13) |
| T21 | Supplier with no quote | Excluded; never scored (E15) |
| T22 | Anomaly check on two weeks of data | Insufficient history; nothing fired (E16) |
| T23 | Conversational CFO request without `agent.ceo` | `403` |
| T24 | Registered direct CFO action with `agent.cfo` only | Succeeds (`auth.md` §5.2) |
| T25 | Tenant lacks CFO entitlement, member has `agent.cfo` | CFO capability **denied** by entitlement (`auth.md` E19). The denial is served as the §6.9 preview payload rather than a bare error — provisional, see Q13 |
| T26 | Cross-tenant finding id | `404` |
| T27 | Engine formula version bump | Prior findings keep their stamp; new run created (E20) |
| T28 | Funding readiness on four months of data | Completeness report with gaps named; no score (AC19, E21) |
| T29 | Quarantined rows present | Excluded; counts and rule IDs disclosed (E8) |
| T30 | Seller disputes a margin figure | Arithmetic and source rows shown; adjustment path offered (E9) |

---

## 13. Explicit open questions

| # | Question | Impact |
|---|---|---|
| Q1 | **Bank/UPI statement ingestion.** OP1 gives the mechanism (manual, upload, agent request), but readiness 2.8 asked specifically whether statement ingestion is in scope. This spec assumes **not** (§6.10, §4 non-goals) — confirm. | 🔴 Scope of §6.10 |
| Q2 | **Ad-report ingestion.** Ads are a separate source on all three marketplaces and no adapter exists. V1 supports manual entry only; is an ad adapter wanted? | ROAS/ACOS/TACOS quality |
| Q3 | **Funding-readiness output definition** (readiness 2.25, never answered). C14 puts it in V1; D7 proposes a completeness report rather than a score. What does the seller actually receive? | 🔴 §6.13 |
| Q4 | **Claim-window values per marketplace** — discoverable, or seller-supplied? D3's prioritisation and E7's `EXPIRED` state both rest on them. | §6.4 ordering |
| Q5 | **Billing meter** — owned by the entitlement, metering and billing specification (readiness §7 item 3, unwritten). §7.3 records inputs only; this spec asserts no unit. | Entitlement/billing spec |
| Q6 | **Free-tier preview shape and run cadence** (§6.9). readiness 3.4 classifies the shape `[P]`; the automatic-run cadence for un-entitled tenants is undecided. | Entitlement spec |
| Q7 | **Anomaly minimum series length** — how much history before detection may fire? | §6.5 |
| Q8 | **Does CFO surface CI-sourced competitor ranges unprompted**, or only when asked? Unprompted comparison crosses an entitlement boundary when the tenant lacks CI. **Also open: how the observation set reaches CFO under star topology** — CEO-brokered, or a shared read? | Entitlement, orchestration |
| Q9 | **Agent-initiated data-request flow** (readiness 2A.13) — how a request is surfaced, prompted and validated. This spec defines only the record CFO writes. | Orchestration spec |
| Q10 | **Brain 2 has no specification** (readiness §7 item 8, unwritten). CFO consumes `detect_anomalies` and §6.5 names methods; the owning spec does not exist. | 🔴 §6.5 |
| Q11 | ~~`landed_cost` undefined~~ | **RESOLVED** — defined at `deterministic-engine.md` §5.13.1 as `LANDED_COST_PER_UNIT`. Consumed by §6.11 and §6.12. |
| Q12 | **Leak category mapping.** `data-foundation.md` §5.2 outcomes (`ORPHAN_SETTLEMENT`, `DUPLICATE_SETTLEMENT`, `UNSETTLED_BEYOND_LAG`) have no stated mapping to §6.3's seven categories. | §6.3 |
| Q13 | **May an entitlement denial return a reduced payload** (the preview) rather than an error? §6.8 assumes yes; `auth.md` E19/T9 assume a denial. The entitlement spec owns this. | 🔴 §6.9, `auth.md` E19 |
| Q14 | **`MANUAL` confidence ordering.** `data-foundation.md` §7.1 now ranks it weakest, but the interaction between a `MANUAL` input and the monotonic rule across aggregates is not spelt out. | Engine §9 |

### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | Leak Shield as agent or capability | **Capability inside CFO** (C2). Agent count stays four plus CEO. |
| R2 | Who owns margin math | **Brain 1 only** (C1). CFO holds no formula, rate table or arithmetic — but may hold tables. |
| R3 | Token ranking | **Characterised, not decided** (§7.3). CFO is the most deterministic agent and its context cost is flat with data volume; that is a technical finding recorded as input for the entitlement, metering and billing spec, which owns the meter. |
| R4 | GST depth | **Management-grade only** (C4). Never filing-grade. |
| R5 | TCS/TDS treatment | **Cash-flow items, never P&L** (C11). |
| R6 | Manual input storage | **Single store** — `manual_adjustment` (engine §7.1). CFO defines none. |
| R7 | Amazon support | **Not categorically unsupported.** Settlement V2 is specified; match keys and real-export validation are pending (§6.2). |
| R8 | Delegation targets | **Defined.** `reconcile`, `landed_cost` and `leak_aggregate` are enumerated at `deterministic-engine.md` §5.13.1, and reconciliation exceptions produce `metric_result` rows — so `leak_finding.engine_result_ref` is satisfiable. |
