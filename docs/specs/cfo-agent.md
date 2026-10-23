# Metrion — CFO Agent Specification

**Status:** Draft for review
**Prerequisites:** `deterministic-engine.md` (the single canonical source of all margin and P&L math) · `data-foundation.md` (canonical model, reconciliation outcomes, provenance) · `auth.md` (permissions, entitlement)
**Related:** entitlement spec (not yet written) · `whatsapp-integration.md` (defines the `MARGIN_RISK` alert type this agent owns — see its §6.3; CFO itself holds no WhatsApp-specific logic)

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
| C5 | **GST rate source is layered** — observed from the seller's own reports first, then the curated HSN knowledge base (`hsn_gst_reference`, `deterministic-engine.md` §8.2.2), then the GST Applicability Lookup (provisional, cited). Sellers are never asked to upload rate schedules. | OP13 |
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

**Removed by design — amended 2026-10-15 for expenses (EXP-01, EXP-07; `docs/decisions/phase1-decisions.md`).** Earlier drafts defined `expense_entry`, `cash_event` and `supplier_quote` as CFO-owned tables. They duplicated `manual_adjustment` and fragmented the guarantee that manual input never overwrites source data. `cash_event` and `supplier_quote` **remain** `manual_adjustment` field types. **The decision is reversed for expenses only:** `expense_entry` is reinstated as a dedicated **append-only expense ledger**, specified in `docs/specs/expense-tracker.md` and read by Brain 1 through an explicit contract (treatments `incremental`, `already_in_settlement`, `informational`).

*Rationale.* `manual_adjustment` cannot hold a date, vendor, source reference, payment or review status or treatment; cannot edit across target and field; cannot delete; has no idempotency key; and its expense pools do not reach the period P&L. *Affected components.* The expense ledger and its feed, `compute_period_pnl` inputs, `deterministic-engine.md` §5.8/§5.10, the legacy `PUT/GET /cfo/expenses` route. *Guarantee kept.* Manual input still never overwrites source data: the ledger is append-only (no app-role UPDATE/DELETE), tenant-isolated with FORCE RLS, and feeds the engine only through the feed. Writes still require `financials.adjust` (no new permission key). Until the ledger cut-over (legacy compatibility is an open decision), the `expense.<category>` rows below remain the stored form.

| Seller input | Stored as |
|---|---|
| Advertising spend, packaging, storage, logistics, other pools | `manual_adjustment` field `expense.<category>` (engine §7.2.1) — legacy form until the expense-ledger cut-over (`expense-tracker.md`) |
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

**Revised — the calling convention below was audited against `packages/calc-engine` (2026-09-23) and found not to match the real API.** This section previously described a `compute_metric(metric_code, grain, target, period)`-style single dispatcher plus ten named functions, none of which exist under those names or signatures. It is rewritten here to state what actually exists, following the same precedent `competitor-intelligence-agent.md` §1a item 2 set for the identical gap on the CI side: real functions named and signed exactly as implemented; functions with no implementation labelled as deferred engine work, with no signature invented for them.

**5.1.1 Real, verified against `packages/calc-engine` source.** There is no single `compute_metric` dispatcher — each metric has its own typed function in `calc_engine/api/compute_metric.py` (or `calc_engine/formulas/`), each returning a `MetricResult` (`deterministic-engine.md` §9's `metric_result`, whose `.id` **is** the `engine_result_ref`) unless noted otherwise.

| Function | Module | Signature | Purpose |
|---|---|---|---|
| `compute_net_realized_revenue` | `calc_engine.api.compute_metric` | `(lines, *, bearer_resolver, recognition_state, ingestion_run_ids, adapter_versions, active_adjustment_ids, computed_at, as_of_date=None) -> MetricResult` | Net Realized Revenue |
| `compute_contribution_profit` | `calc_engine.api.compute_metric` | `(nrr_result: MetricResult, *, cogs, marketplace_fees, shipping_logistics, advertising_costs, return_rto_losses, other_allocated_costs, ingestion_run_ids, adapter_versions, active_adjustment_ids, computed_at, as_of_date=None) -> MetricResult` | Contribution Profit; always built on a prior NRR `MetricResult`, never recomputed independently |
| `compute_price_positioning` | `calc_engine.api.compute_metric` | `(*, seller_price_paise, seller_price_confidence, competitor_prices, computed_at, as_of_date=None) -> list[MetricResult]` | Position vs. CI-supplied `competitor_prices[]` (`DERIVED`); one row per reference (AVERAGE/MIN/MAX) |
| `compute_repricing_scenario` | `calc_engine.api.compute_metric` | `(*, seller_price_paise, seller_price_confidence, competitor_prices, stance, stance_param, computed_at, as_of_date=None) -> MetricResult` | Not margin-aware — no COGS, no fee reference; a suggested price here may be unprofitable |
| `compute_price_band` | `calc_engine.api.compute_metric` | `(*, product_ref, category, competitor_prices, computed_at, min_competitors=ENGINE_MIN_COMPETITORS_FOR_PRICE_BAND, as_of_date=None) -> list[MetricResult]` | Q1/Q3/IQR/fences/typical range plus one row per priced point with its outlier flag |
| `leak_aggregate` | `calc_engine.formulas.leak` | `(exception_amounts: list[Paise] \| tuple[Paise, ...]) -> Paise` | Sums reconciliation-exception amounts — **returns a plain `Paise`, not a `MetricResult`.** No `compute_metric.py` wrapper exists yet to mint an `engine_result_ref` for this total. Until that wrapper is added, §6.4 rule 5's claim that the headline total "carries its own `engine_result_ref`" is **ahead of the implementation** — recorded honestly here rather than restated as fact; see the deferred item below |
| `rank_findings` | `calc_engine.formulas.severity` | `(findings: Sequence[Finding], *, as_of_date: date, config_rows: Sequence[SeverityConfigRow], ordering_basis: str, closing_soon_days: int = 14) -> list[tuple[Finding, SeverityBand \| Unavailable, WindowStatus]]` | Deterministic severity band, `window_status` and order (D10). `Finding` is `(exception_id, amount_paise, age_days, claim_window_days)`; `ordering_basis` is `"WINDOW_THEN_AMOUNT"` or `"AMOUNT_ONLY"`. Returns tuples, not `MetricResult` rows — CFO reads `age_days`/`window_status`/severity off the tuple, not off an `engine_result_ref` |
| `compute_metric_delta` | `calc_engine.api.compute_metric` | `(result_a: MetricResult, result_b: MetricResult, *, computed_at, as_of_date=None) -> MetricResult` | Period-over-period delta between two already-computed `MetricResult`s of the SAME `metric_code` (`result_b.value_paise - result_a.value_paise`, `calc_engine.formulas.metric_delta` — the only place this arithmetic happens); raises `ValueError` on a `metric_code` mismatch, returns `UNAVAILABLE` if either input is. Wired into CFO via `backend.services.cfo_actions.narrate_period_comparison` (`twinkly-mapping-canyon.md` CP A3) — see §7.4.4 |
| `compute_landed_cost` | `calc_engine.api.compute_metric` | `(quote: LandedCostQuote, quantity: int, *, sku: str, active_adjustment_ids, computed_at, as_of_date=None) -> MetricResult` | Landed cost per unit from ONE seller-declared `supplier.quote` manual_adjustment (`metric_code = "LANDED_COST_PER_UNIT"`) — `unit_cost_paise` plus `shipping_paise` divided evenly across `quantity`, rounded half-up (`calc_engine.formulas.landed_cost`). Wired into CFO via `backend.services.cfo_actions.compute_landed_cost_for_quote` (`twinkly-mapping-canyon.md` CP A4) — the §6.11 supplier-ranking **primitive only**; comparing/ranking multiple quotes is Phase B1, not built |
| `cash_reconciliation` | `calc_engine.api.cash_reconciliation` | `(tenant_id, *, marketplace, period_start, period_end, as_of_date, computed_at) -> CashReconciliationResult` | `deterministic-engine.md` §5.13.3. **Real, narrower than earlier drafts implied**: `CASH_RECEIVED` (real, from persisted `settlement_line` rows) and settlement-lag timing counts (reusing `reconcile()`'s already-tested `classify_settlement_lag` unchanged) are genuinely computed; `CASH_EXPECTED`/`CASH_VARIANCE` are structurally `UNAVAILABLE` this pass — no adapter anywhere maps an invoice-side marketplace-fee component, so a net "expected settlement" figure cannot be honestly derived yet (a real, disclosed data-foundation gap, not an oversight). `TCS_COLLECTED` is real for FLIPKART only (its one real invoice-side TCS mapping); `TDS_DEDUCTED` is `UNAVAILABLE` everywhere — no adapter maps a TDS component for any marketplace yet |

**5.1.2 Not yet built — DEFERRED, pending a Brain-1 extension spec.** These functions were named in an earlier draft of this section with invented signatures. **Verified by grep against `packages/calc-engine`: zero matches for `reconcile`, `margin_curve`, `funding_readiness_metrics`, `resolve_fee_reference`, `estimate_competitor_margin_range`, `detect_anomalies`, `gst_applicability_lookup`.** (`landed_cost` and `cash_reconciliation` are no longer in this zero-match set — both are real and now wired into CFO, see §5.1.1; `cash_reconciliation`'s own real scope is narrower than an earlier draft implied, see `deterministic-engine.md` §5.13.3 and its §5.1.1 row above. `margin_curve` and `resolve_fee_reference` are also real matches today, same as CP A3's note already flagged — their rows below have not yet been reconciled, which remains out of this checkpoint's narrow scope.) This spec states the CFO *capability* each one is meant to serve — not an invented signature — and each is out of scope until `deterministic-engine.md` is extended to define it:

| Capability CFO needs from Brain 1 | What it must produce | Blocks |
|---|---|---|
| Invoice-side vs. settlement-side reconciliation, producing `reconciliation_exception` rows | A `LEAK_EXCEPTION_AMOUNT` `MetricResult` per exception | §6.2, §6.4, `leak_finding.reconciliation_exception_id`/`engine_result_ref` |
| A margin curve across candidate prices, fee-aware (fees from §5.14) | One `MetricResult` per candidate price, `metric_code = MARGIN_AT_PRICE` or equivalent | §6.7 pricing recommendations |
| Funding-readiness metrics assembled from Contribution Profit history, margin stability and cash-conversion timing | A data-completeness-oriented result set, no score | §6.13 |
| Fee-reference resolution by marketplace/category/fee-type/date | A resolved fee row from the versioned reference store (§5.14, C18) | Fee-overcharge detection, pricing |
| Estimated competitor margin range from CI-supplied observations | An `estimate_ref` (`competitor_estimate.id`), never an `engine_result_ref` | §6.7 rule 3; also deferred on the CI side (`competitor-intelligence-agent.md` §1a item 2) |
| Statistical anomaly detection (z-score, period-over-period delta, percentile thresholds) | Anomaly flags CFO can attach to a figure | §6.5; **owned by Brain 2, which has no specification at all yet** (readiness §7 item 8, Q10) — a distinct gap from the others in this table, which are Brain-1 gaps |
| Curated HSN knowledge base lookup (`resolve_hsn_gst_reference`) | A resolved `hsn_gst_reference` row, or `None` — never a guessed rate | §6.6, C5; `deterministic-engine.md` §8.2.2. Table shape and resolution rule are now specified; **no seed data or CFO wiring exists yet** (`deterministic-engine.md` C15) |
| GST applicability lookup by product/HSN | A cited, provisional rate suggestion, never auto-applied | §6.6, C6 |

None of these are implemented, none has an agreed signature, and this spec does not invent one. Each must go through its own extension to `deterministic-engine.md` (or, for anomaly detection, a first Brain-2 spec) before CFO can call it. Wherever the rest of this document names one of these functions as if it already exists, that reference is a forward-looking capability statement, not a description of current code — see the corrected wording at §6.2, §6.4, Q11 and R8.

**Correction (`twinkly-mapping-canyon.md` CP A3):** this table previously carried a "Period-over-period metric delta" row. That capability was actually built at the engine layer back in CP3 (`calc_engine.formulas.metric_delta`/`compute_metric.compute_metric_delta`) and this table was not updated at the time — an oversight, caught and fixed here rather than left stale. The row is removed; the real function now appears in §5.1.1's table above, and §7.4.4 states its CFO-side wiring. **Note for future accuracy passes, not fixed in this checkpoint (out of CP A3's narrowly-scoped work):** the "margin curve," "landed cost per unit" and "fee-reference resolution" rows above have the same problem — all three were also built at the engine layer (Engine Phase 2/CP1) and the margin-curve and fee-reference rows are additionally wired into CFO already (`twinkly-mapping-canyon.md` CP A1, `compute_pricing_curve`); "landed cost per unit" is built at the engine layer only, not yet wired into any CFO composition (`twinkly-mapping-canyon.md` Phase B). This table has not been reconciled against that reality yet — flagged here so it isn't silently missed again, but correcting it is out of this checkpoint's scope.

**Correction (`twinkly-mapping-canyon.md` CP A4):** the "landed cost per unit" row CP A3's note above flagged as still-open is now resolved — `compute_landed_cost`/`LANDED_COST_PER_UNIT` is wired into CFO (`backend.services.cfo_actions.compute_landed_cost_for_quote`, `POST /api/v1/cfo/landed-cost`, `agents.ceo_hub.dispatch_cfo_landed_cost`). The row is removed from the deferred table above and the real function now appears in §5.1.1. **This is the §6.11 supplier-ranking PRIMITIVE only** — one quote's landed cost, computed and persisted. Comparing or ranking multiple quotes for the same SKU (Phase B1) and the budget-constrained batch-size range (Phase B3a/B3b) remain genuinely unbuilt; CP A4 supplies their landed-cost input, it does not build either of them. The "margin curve" and "fee-reference resolution" rows CP A3's note also flagged remain unreconciled — still out of this checkpoint's narrow scope, not silently resolved here.

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

**Meesho is the strongest V1 target — and the only one with a validated join key.** Per `docs/Metrion_PnL_and_MTR_Mapping_FINAL.pdf` §7A — headed "VERIFIED — real seller data inspected... transcribed directly from a real Meesho seller's exports (Orders report, Payments workbook)... for account SS Digital India / GSTIN 07AWOPM5761A1ZG" — Meesho's real Supplier Panel exports carry invoice-side revenue fields (`Fixed Fee (Incl. GST)`, `Warehousing fee (incl GST)`, `Return premium (incl GST)`) alongside settlement-side values (`Final Settlement Amount` and its documented 18-term formula), joinable on `sub_order_num` — a key independently confirmed across four separately-inspected real files for the same seller account: Orders report (PDF §7A.1), Payments workbook (PDF §7A.2), TCS_Sales (PDF §8.1) and TCS_Sales_Return (PDF §8.2). The earlier justification cited the synthetic co-located columns, which `data-foundation.md` §0 and §2.3 retract; that is now superseded by the real-export evidence above (`data-foundation.md` §5.4). **Column-level pairing on `sub_order_num` is validated against real exports.** What remains open: the 18-term Final Settlement Amount formula's letter-to-column mapping is unresolved — the formula (`= B + C + G + H + I + L + Q + R + S + T + U + V + W + Y + AA + AD + AF + AX`) references real spreadsheet cell letters, not named columns (PDF §7A.2). See V6 for the remaining cross-marketplace validation gap (Flipkart's and Amazon's adapter mappings).

**Amazon status (corrected).** Amazon settlement is **specified**, not absent: `data-foundation.md` §0.6 and §2.3 register `amazon.settlement.v2` from Amazon SP-API documentation. Amazon is therefore **not categorically unsupported**.

What remains open is narrower: **settlement match keys are unvalidated against real data, though the field list itself is now real** — `data-foundation.md` §5.1 records that Amazon's V2 settlement field list is independently verified (from Amazon's own SP-API docs, PDF §3.1) and includes real order/line identity fields (`order-id`, `merchant-order-id`, `order-item-code`, `merchant-order-item-id`, `sku`), but **no real, populated Amazon settlement export has validated the adapter or the join key**. Until that closes, Amazon periods report `RECOGNISED` and Leak Shield findings for Amazon are withheld — because the join cannot yet be trusted, not because the data or a candidate key does not exist.

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
2. Findings are ordered by **claim-window urgency first, amount second** (D3). **Ordering, `severity`, `age_days` and `window_status` all come from `rank_findings(findings, *, as_of_date, config_rows, ordering_basis, closing_soon_days=14)`** (`calc_engine.formulas.severity`, §5.1.1), which takes an explicit `as_of_date` (§4.2) and resolves bands from `SeverityConfigRow` rows (§5.14.1). Brain 3 narrates the resulting order and never produces it.
3. Language is *discrepancy identified*, never *money you will get back* (D2).
4. CFO produces a recommended action — typically "raise a claim with marketplace X citing these order IDs" — but **never files it** (C7).
5. **Aggregate totals are computed by Brain 1** via `leak_aggregate(exception_amounts) -> Paise` (`calc_engine.formulas.leak`, §5.1.1), never by CFO summing in application code. **As implemented today this returns a plain `Paise`, not a `MetricResult`** — no `engine_result_ref`-minting wrapper exists yet for this total (§5.1.1). Until that wrapper is added, the headline total is engine-computed but does not yet carry its own `engine_result_ref`; per-finding amounts still do, copied unchanged from their `reconciliation_exception`. §7.2 forbids CFO arithmetic, including summation, regardless.
6. The headline total **excludes levy-derived findings** (`TCS_TDS_MISMATCH`), or labels them separately — a levy variance is a cash-reconciliation item, not recoverable margin.

### 6.5 Anomaly detection (C13)

Statistical only: z-score, period-over-period delta, percentile thresholds over margin, fee ratio, settlement lag and return rate. Runs only where uploaded data exists. Below the minimum series length, anomaly detection reports insufficient history rather than firing on noise. **Forecasting is out of scope here** — it is gated at 6 complete months (readiness §1, Intelligence and data — Forecasting) and belongs to the forecasting surface.

### 6.6 GST (C4, C5, C6)

**Included:** inclusive/exclusive normalisation per marketplace *and per field* · IGST/CGST/SGST/UTGST/Cess handling · TCS and TDS visibility · indicative period summary · GST-on-fees shown as a separate potentially-creditable line.

**Rate resolution order (OP13):** observed from the seller's own reports (`deterministic-engine.md` §8.1) → curated HSN knowledge base (`hsn_gst_reference`, deterministic table lookup, `deterministic-engine.md` §8.2.2) → GST Applicability Lookup (provisional, cited, never auto-applied without explicit seller acceptance, `deterministic-engine.md` §8.4). The curated HSN knowledge base is checked only when the first tier has nothing, and is only ever a deterministic reference-table lookup — never a live research call, and never conflated with `gst_slab_reference`'s plausibility check (§8.2.1, `V-TAX-003`), which serves a different job.

**Every GST surface carries:** *"Indicative management summary. Not a GST return. Not filing-grade. Verify with your tax professional."*

**Never:** statutory filing, guaranteed compliance, final ITC eligibility, or a claim that a figure is return-ready.

### 6.7 Pricing recommendations

1. CFO requests margin at candidate price points from Brain 1, which resolves fees from §5.14.
2. Output is a **margin curve with a recommended band**, not a single optimal price (D4).
3. Where CI has supplied competitor observations, the competitor's estimated range may be shown alongside — clearly labelled estimated, never as their actual margin.
4. Every recommendation states its assumptions: COGS basis, fee reference version, GST treatment, and what was unavailable.
5. Recommend-only (C7). No marketplace write, ever.

**Q27 caveat, required before release of the ledger feed** (approved 2026-10-15, `docs/decisions/phase1-decisions.md`; engine `deterministic-engine.md` §5.8.1; `expense-tracker.md` §6.13 rule 9, AC13, B.11). Pricing recommendations (the margin curve and every price scenario) and loss-making-SKU alerts that CFO produces or feeds must state that **unallocated advertising and storage spend is excluded from SKU contribution**. Wherever CFO shows contribution profit or margin (the period P&L, the pricing curve, the strategic briefing, the Financial Health Band), unallocated advertising, storage and overhead appear as **their own labelled lines beside contribution profit**, and **total profit includes them**. A **seller-facing release note** is required when the contribution-profit definition changes (the new formula version takes effect at the release date). This paragraph changes no formula and no behaviour; it records what must be true before the ledger feed is released.

### 6.8 Registered direct execution paths (B4)

Per the `auth.md` §5.2 guardrail, every direct path is enumerated here, names one action and one key, and accepts no free-form input. **There is no generic "invoke CFO" endpoint.**

| Trigger id | Action | CEO call | Permission | Entitlement gate | Rate limit | Audit |
|---|---|---|---|---|---|---|
| `cfo.preview` | Render the free-tier gated preview (§6.9) — **Built** (D7): `backend.services.cfo_actions.assemble_cfo_preview`, wired to `POST /api/v1/cfo/preview`; no `agents.ceo_hub` dispatch function exists or is needed (this table's own "CEO call" column reads "No" for this row) | Yes — as the entitlement-denial surface for CEO (C17); permission `agent.cfo` still required | `agent.cfo` | **Passes permission, then intentionally bypasses the entitlement denial** — see below | Per tenant, low | Yes |
| `cfo.reconcile` | Run reconciliation for a period and marketplace — **Built** (D5): `backend.services.cfo_actions.run_leak_shield_reconciliation`, wired to `POST /api/v1/cfo/reconcile` and `agents.ceo_hub.dispatch_cfo_reconcile`; the first CFO surface producing real, persisted `leak_finding` rows from a real `reconcile()` (D4) | Yes — conversational via the CEO registry (`ceo-agent-orchestration.md` §6.11); needs `agent.ceo` + `agent.cfo` | `agent.cfo` | CFO entitlement + run credit | Per tenant | Yes |
| `cfo.pnl` | Compute P&L for a period | Via `cfo.pnl_for_tenant` only (§6.11): this caller-assembled form is not CEO-callable | `agent.cfo` | CFO entitlement + run credit | Per tenant | Yes |
| `cfo.pricing` | Produce a margin curve for a SKU — **Built** (`twinkly-mapping-canyon.md` CP A1): `backend.services.cfo_actions.compute_pricing_curve`, wired to `POST /api/v1/cfo/pricing` and `agents.ceo_hub.dispatch_cfo_pricing` | Yes — conversational via the CEO registry (`ceo-agent-orchestration.md` §6.11); needs `agent.ceo` + `agent.cfo` | `agent.cfo` | CFO entitlement + run credit | Per tenant | Yes |
| `cfo.gst_summary` | Render the indicative GST summary — **Built** (`twinkly-mapping-canyon.md` CP A2): `backend.services.cfo_actions.render_gst_period_summary`, wired to `POST /api/v1/cfo/gst/period-summary` and `agents.ceo_hub.dispatch_cfo_gst_summary`; PERIOD-level, distinct from the line-level `cfo.analyze_gst_lines` path | Yes — conversational via the CEO registry (`ceo-agent-orchestration.md` §6.11); needs `agent.ceo` + `agent.cfo` | `agent.cfo` | CFO entitlement | Per tenant | Yes |
| `cfo.gst_lookup` | Invoke the GST Applicability Lookup | Yes — Route A (`ceo-agent-orchestration.md` §6.9/C11); needs `agent.ceo` + `agent.cfo` + `service.gst_lookup` | `agent.cfo` **and** `service.gst_lookup` | Shared-service cap (OP9), independent of CFO entitlement | Per tenant, strict | Yes |
| `cfo.landed_cost` | Compute one `supplier.quote`'s landed cost per unit — the §6.11 supplier-ranking **primitive only**, never a ranking — **Built** (`twinkly-mapping-canyon.md` CP A4): `backend.services.cfo_actions.compute_landed_cost_for_quote`, wired to `POST /api/v1/cfo/landed-cost` and `agents.ceo_hub.dispatch_cfo_landed_cost` | Yes — conversational via the CEO registry (`ceo-agent-orchestration.md` §6.11); needs `agent.ceo` + `agent.cfo` | `agent.cfo` | CFO entitlement + run credit | Per tenant | Yes |
| `cfo.supplier_ranking` | Rank every ACTIVE `supplier.quote` row for a SKU by landed cost (§6.11) — **Built** (`twinkly-mapping-canyon.md` CP B1): `backend.services.cfo_actions.rank_suppliers`, wired to `POST /api/v1/cfo/suppliers/rank` and `agents.ceo_hub.dispatch_cfo_supplier_ranking`; a single-quote result is reported as a single quote, not a ranking (E15) | Yes — conversational via the CEO registry (`ceo-agent-orchestration.md` §6.11); needs `agent.ceo` + `agent.cfo` | `agent.cfo` | CFO entitlement + run credit | Per tenant | Yes |
| `cfo.batch_size` | Budget-constrained order-quantity range (§6.12) — **engine arithmetic core Built** (`twinkly-mapping-canyon.md` CP B3a): `calc_engine.formulas.batch_size.budget_constrained_quantity` / `calc_engine.api.compute_metric.compute_batch_constrained_quantity` compute the budget-and-MOQ ceiling (§6.12's own "degrades to a budget-and-MOQ arithmetic exercise" floor); **CFO wiring, velocity, and this direct path itself remain NOT built** (`twinkly-mapping-canyon.md` CP B3b, still pending) | Yes — conversational via the CEO registry (`ceo-agent-orchestration.md` §6.11); needs `agent.ceo` + `agent.cfo` | `agent.cfo` | CFO entitlement + run credit | Per tenant | Yes |
| `cfo.funding_readiness` | Assemble the funding-readiness report (§6.13) — **Built, REDUCED slice only** (`twinkly-mapping-canyon.md` CP B2): `backend.services.cfo_actions.assemble_funding_readiness_reduced`, wired to `POST /api/v1/cfo/funding-readiness` and `agents.ceo_hub.dispatch_cfo_funding_readiness`; assembles Contribution Profit history, period-over-period trend and explicit gaps (periods missing, COGS/RTO absent) only — margin stability, revenue concentration and cash-conversion timing remain deferred to Phase D (`reconcile()`/`cash_reconciliation`) and are stated as such on every response, never silently omitted | Yes — conversational via the CEO registry (`ceo-agent-orchestration.md` §6.11); needs `agent.ceo` + `agent.cfo` | `agent.cfo` | CFO entitlement | Per tenant, low | Yes |
| `cfo.line_status_override` | Declare/read a seller's cancellation/return/RTO status for one order line, only where the marketplace report itself carries none (§6.14) — **Built**, this session: `backend.services.cfo_actions.declare_line_status_override`/`get_line_status_overrides`, wired to `PUT`/`GET /api/v1/cfo/line-status-override`; no `agents.ceo_hub` dispatch exists or is added (this table's own "CEO call" column reads "No") | No — write-class, excluded from the CEO registry (C21) | `agent.cfo` (write additionally requires `financials.adjust`, §7 rule 4) | CFO entitlement | Per tenant | Yes |
| `cfo.financial_health` | Classify already-computed period metrics into a GOOD/WATCH/AT_RISK band (§6.15) — **Built**, this session, backend only: `backend.services.cfo_actions.assemble_financial_health`, wired to `POST /api/v1/cfo/financial-health`; no `agents.ceo_hub` dispatch exists or is added | Yes — conversational via the CEO registry (`ceo-agent-orchestration.md` §6.11); needs `agent.ceo` + `agent.cfo` | `agent.cfo` | CFO entitlement | Per tenant, low | Yes |
| `cfo.strategic_briefing` | Gather, rank, and narrate already-computed strategic signals (§7.5) — **Built**, this session, backend only: `backend.services.cfo_actions.assemble_strategic_briefing`, wired to `POST /api/v1/cfo/strategic-briefing`; no `agents.ceo_hub` dispatch exists or is added | Yes — conversational via the CEO registry (`ceo-agent-orchestration.md` §6.11); needs `agent.ceo` + `agent.cfo` | `agent.cfo` | CFO entitlement | Per tenant, low | Yes |

**CP1 correction (2026-10-07) — the "CEO call" column above was stale.** It recorded "No" for rows that already have a `agents.ceo_hub.dispatch_cfo_*` function, and several rows describe "no `agents.ceo_hub` dispatch exists or is added" for actions the CEO now routes. The column is now authoritative **only** as amended in place; the governing contract is the CEO action registry (`ceo-agent-orchestration.md` §6.11). Write-class CFO actions (`cfo.enter_expense`, `cfo.expense_budget_set`, `cfo.line_status_override`, `cfo.line_count_override`, `seller-goal` writes, `cfo.gst_lookup/accept`, `cfo.analyze_gst_lines`) are **not** CEO-callable in V1 (C21), so `financials.adjust` remains enforced only on the direct path where it already is. `cfo.anomaly_check` and `cfo.cash_reconciliation`, built after this table was last edited, are CEO-registered (read-class). **Audit gap, recorded:** none of the CFO direct-path routes write an `agent_run` row today although this table says "Audit: Yes"; for CEO-dispatched legs the CEO choke point writes the CFO child row (CEO §6.15 R5); closing the direct-path gap is CFO-side (CEO Q16). **CFO-class access from CEO** requires `agent.cfo` **and** CFO entitlement, with the §6.9 preview served on entitlement denial (CEO C17).

Anything open-ended — "why did my profit drop?" — is **conversational**, requires `agent.ceo` plus `agent.cfo`, and is not a direct path.

**The preview and the entitlement gate.** `auth.md` E19/T9 state that a member holding `agent.cfo` in a tenant without CFO entitlement is **denied by entitlement**. The preview does not contradict that: the *CFO capability* is still denied. What `cfo.preview` returns is a deliberately reduced surface that the entitlement layer serves **in place of** the denial, not instead of evaluating it.

Every step of the `auth.md` §7.1 chain still runs, including permission (`agent.cfo`). **There is no un-permissioned path.** A member without `agent.cfo` gets `403`, entitled or not.

**Status: resolved** (D8) — see §6.9 for the full shape, cadence and build citation. See Q13 for the entitlement-spec side of this decision (denial-rendering mechanism).

### 6.9 Free-tier gated preview — Built (D7)

**Status: resolved, Built** (D8). The shape below and the on-demand-only cadence were both explicitly approved this session — no longer `[P]`, no redesign from what was already specified here. **Built** (D7): `backend.services.cfo_actions.assemble_cfo_preview`, wired to `POST /api/v1/cfo/preview`/`cfo.preview` (§6.8). A tenant without CFO entitlement sees:

- The **headline recoverable-discrepancy total** and the affected SKU count
- **One finding revealed in full**, with its arithmetic
- The remainder locked

The reconciliation is deterministic and already computed, so revealing one costs nothing and demonstrates the analysis is real rather than asserted.

**Run cadence: on-demand only, approved this session.** No scheduler, no background job, no cron — every call to `POST /cfo/preview` runs the real, unchanged `run_leak_shield_reconciliation` (D5) fresh. Automatic/cached computation for un-entitled tenants was considered and explicitly rejected as out of scope for this checkpoint.

**Two honest data-reality notes, current as of D7 (not defects in this checkpoint's own code):** against today's real Meesho data, `run_leak_shield_reconciliation` returns zero findings (D4 Decision A — no invoice-side fee components exist to compare against yet), so the preview honestly returns `headlineTotalPaise: 0`, `revealedFinding: null`, `lockedFindingsCount: 0` until real leak findings exist. Separately, `affected_sku_count` cannot be computed from real data today (no Meesho adapter maps `sku` onto a finding yet) — rather than reporting a falsely-zero-reading `0`, the response carries `affectedSkuCount: null` plus `affectedSkuCountUnavailable: true` whenever every real finding's `sku` is `None`, per CLAUDE.md's "missing input is UNAVAILABLE, never zero" rule.

### 6.10 Expense and cash-flow tracking (C8)

**Input paths (OP1):** manual entry · report upload · agent-initiated data request. All manual values are written as `manual_adjustment` rows (§5) under the engine's append-only, superseding discipline — CFO adds no store and no second rule.

**Expenses** feed the engine's cost components. Account-level pools are allocated per engine §5.10 and always carry `DERIVED` confidence. The `other` category's `manual_adjustment.reason` field (already accepted by `enter_expense`) is a free-text description of what the expense actually was (e.g. "petrol for delivery run", "travel to supplier meeting") — `list_expenses`/`GET /cfo/expenses` surfaces it back on every entry (this session's fix: it was previously write-accepted but never read back, leaving "other" entries indistinguishable from one another).

**Cash flow** is settlement-based (D6): expected vs received, variance, and timing — backed by `cash_reconciliation` (`deterministic-engine.md` §5.13.3), **real but narrower than this paragraph's ideal shape**. `CASH_RECEIVED` and settlement-lag timing are genuinely computed from persisted `settlement_line` data; `CASH_EXPECTED`/`CASH_VARIANCE` are structurally `UNAVAILABLE` until a data-foundation adapter extension captures invoice-side marketplace-fee components (no adapter does today) — CFO must present that as a named, honest gap, never silently omit the variance figure or approximate it from `CASH_RECEIVED` alone. TCS and TDS appear **in cash surfaces only, never in P&L** (C11) — including where a `TCS_TDS_MISMATCH` finding surfaces a levy variance, which is a cash-reconciliation item and is excluded from the recoverable-discrepancy headline (§6.4.6). `TCS_COLLECTED` is real for FLIPKART only; `TDS_DEDUCTED` is `UNAVAILABLE` everywhere this pass. CFO must explain that levies reduce cash received without reducing profit, because sellers routinely read them as losses.

**Bank data is out of scope.** Cash flow is reconstructed from settlements and seller input, not from a bank feed. See **Q1**.

### 6.11 Supplier ranking (C10)

Ranks **only** on seller-supplied `supplier.quote` manual adjustments (engine §7.2.1) — unit cost, MOQ, lead time, shipping, payment terms, reliability notes. Landed cost per unit is computed by Brain 1. CFO never discovers suppliers and never scores a supplier it has no quote for.

**Landed cost primitive — Built** (`twinkly-mapping-canyon.md` CP A4): `backend.services.cfo_actions.compute_landed_cost_for_quote` computes ONE quote's landed cost per unit end-to-end (fetch the `supplier.quote` adjustment, parse, call `compute_landed_cost`, persist), wired to `POST /api/v1/cfo/landed-cost`/`cfo.landed_cost`.

**The ranking itself — Built** (`twinkly-mapping-canyon.md` CP B1): `backend.services.cfo_actions.rank_suppliers` fetches every ACTIVE `supplier.quote` row for a SKU directly via `manual_adjustment_repo.active_adjustments_for_target` (not through the single-quote primitive above, which treats >1 ACTIVE row as an ambiguity — correct for its own purpose, wrong for ranking), computes each row's landed cost via the same real `compute_landed_cost`, and sorts the results ascending by landed cost — a comparison, not arithmetic. A row that fails to parse is quarantined (excluded, disclosed with its reason) rather than aborting the ranking of the rest (§9 E8 precedent). Exactly one successfully-computed quote is reported via a distinct `is_single_quote` flag, never presented as a ranking (E15). Wired to `POST /api/v1/cfo/suppliers/rank`/`cfo.supplier_ranking`.

### 6.12 Batch size (readiness §1 — Batch size; 2A.3)

Assigned to CFO by the locked decision record. **Estimate only.**

**Engine arithmetic core — Built** (`twinkly-mapping-canyon.md` CP B3a): given a fixed budget
ceiling and a fixed per-unit landed cost, `calc_engine.formulas.batch_size
.budget_constrained_quantity` computes the floor of affordable units (never rounded up — see
the formula's own docstring) and whether that respects a declared MOQ, wrapped for persistence
by `calc_engine.api.compute_metric.compute_batch_constrained_quantity`
(`metric_code=BATCH_CONSTRAINED_QUANTITY`).

**CFO wiring — Built** (`twinkly-mapping-canyon.md` CP B3b): `backend.services.cfo_actions.
assemble_batch_size_estimate` wires B3a's engine core with sales velocity
(`calc_engine.formulas.sales_velocity.observed_units_sold`, real — sums `cost_components.
billable_quantity` across already-assembled `CanonicalLine`s, the same "actually sold" concept
COGS already uses), the seller's chosen `supplier.quote` (fetched/handled exactly like §6.11's
landed-cost primitive, CP A4: zero/multiple ACTIVE rows both raise a data request, a malformed
quote propagates uncaught), and `batch.budget` (§7.2.1) — including a real expiry check: an
expired `valid_until` is never silently used as if still valid, and raises a data request
instead. Wired to `POST /api/v1/cfo/batch-size`/`cfo.batch_size`.

The landed-cost-per-unit reference this estimate is built on is computed at `quantity = moq`
when a MOQ is declared, or `quantity = 1` otherwise — a disclosed approximation
(`BatchSizeOutcome.reference_quantity`/`reference_quantity_basis`/`reference_quantity_caveat`),
not a solved fixed point: because `landed_cost_per_unit` apportions `shipping_paise` across
`quantity`, the true per-unit cost may be lower at a higher order volume than this estimate's
one reference quantity reflects. The outcome states explicitly whether this caveat applies to
the quote in hand (only when `shipping_paise` is set) rather than always showing a warning that
may not apply.

The "never sold" case (empty `CanonicalLine` history for the SKU) degrades to the honest
budget-and-MOQ arithmetic floor the Limitations below already name — it does **not** by itself
trigger a data request. Per this section's own next paragraph's precise wording, a data request
is raised only when velocity **and** lead time **and** MOQ are all missing at once; either a
declared lead time or a declared MOQ alone is enough for the estimate to proceed, degraded and
explicitly flagged as such (T34).

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

Ships in V1; **output definition is open (Q3)**. **Built, REDUCED slice, now including
cash-conversion timing** (`twinkly-mapping-canyon.md` CP B2, extended 2026-09-29):
`backend.services.cfo_actions.assemble_funding_readiness_reduced` assembles Contribution Profit
history/trend and the explicit-gaps bullet (periods missing, COGS/RTO-classification absent —
both derivable from already-persisted P&L results), **and now also fetches any real,
already-persisted `SETTLEMENT_LAG_DAYS` row** (anomaly-detection.md §6.1/§6.6, minted by
`run_leak_shield_reconciliation` every time Leak Shield reconciliation runs) for the requested
period as `cash_conversion_timing` — no new engine formula, no new arithmetic, purely a second
`metric_result_repo.list_by_metric_code` fetch alongside the existing Contribution Profit one.
This is a real metric under its own real name (`SETTLEMENT_LAG_DAYS`), not a newly-invented
`CASH_CONVERSION_DAYS` metric_code — §5.13.1's stub table row named that code, but the actual
built capability answers the same "how long does cash take to arrive" question under its real,
pre-existing name. When no such row exists yet for the period (Leak Shield has never run
against it), `cash_conversion_timing` is honestly empty and `deferred_sections` names the gap —
never a fabricated day count. **Margin stability and revenue concentration by SKU/marketplace
remain genuinely unbuilt** — margin stability needs `CASH_EXPECTED` (`deterministic-engine.md`
§5.13.3), which is structurally `UNAVAILABLE` until an adapter maps invoice-side marketplace-fee
components; revenue concentration has no engine primitive at all yet.
`FundingReadinessOutcome.deferred_sections` states both remaining gaps on every response, never
silently omitted. What it can honestly be assembled from today:

- Contribution Profit history and trend, with data-completeness stated
- Margin stability, revenue concentration by SKU and marketplace
- Cash-conversion timing from settlement data
- Explicit gaps — periods missing, COGS absent, marketplaces unreconciled

**Never:** a lending score, a valuation, an investment recommendation, or any claim of accounting-grade accuracy (D7).

### 6.14 Cancellation/return/RTO status declared by the seller

**Status: Built**, this session — closes the CFO end-to-end evaluation's own headline finding
(`docs/evaluation/cfo-e2e-evaluation-mtr-mock-2026-09-27.md` §1/§3/§4/§11: real MTR files carry
no resolvable cancellation/return/RTO status at all, so `NET_REALIZED_REVENUE`/`CONTRIBUTION_
PROFIT` were `UNAVAILABLE` for 100% of that dataset). Full field definitions, precedence rule
and confidence treatment live at `deterministic-engine.md` §7.2.1 (`cancellation_state_
override`/`return_status_override`/`rto_status_override`) — this section states only CFO's own
wiring and UI-facing behaviour, per this project's "product rules here, arithmetic/field
registry there" convention (§5.15's own cross-reference note is the precedent for this split).

`backend.services.cfo_actions.declare_line_status_override`/`get_line_status_overrides`, wired
to `PUT`/`GET /api/v1/cfo/line-status-override` (`cfo.line_status_override`). A seller declares
one of the three fields for one `sales_line_id` only when their own marketplace upload does not
resolve it — the write path validates the value against that field's real enumerated domain and
never silently accepts an invalid status string.

**What this does and does not unblock, restated for the CFO surface specifically:** this closes
the *input* side of the gap — a seller can now record what they know. It does not, by itself,
make `POST /cfo/pnl` pick up that declaration automatically: every multi-line CFO composition in
this codebase is caller-assembled (§6.8's own table; `PeriodPnlHttpRequest`'s docstring,
judgment call 4), so whichever future ingestion-to-canonical composition layer resolves a real
uploaded line's `CanonicalLine` is the intended consumer of `get_line_status_overrides`, via
`calc_engine.formulas.line_status_overrides.resolve_line_status`'s tested precedence rule
(observed marketplace data always wins; the override fills a genuine gap only). **Recommended
seller-facing prompt, not yet built as UI:** when `compute_period_pnl` returns `NET_REALIZED_
REVENUE`/`CONTRIBUTION_PROFIT` `UNAVAILABLE` with `missing_inputs` naming `cancellation_state`/
`return_status`/`rto_status`, the dashboard should surface a clear, non-alarming prompt asking
the seller to confirm each affected line's real outcome, rather than a bare `UNAVAILABLE` label
— this is a frontend/UX follow-up, explicitly out of this session's backend-only scope.

### 6.15 Financial Health Band

**Status: Built**, this session, backend only — no frontend surface yet (explicit scope
decision this session: build the backend feature completely now, integrate it into the
dashboard once the real frontend for it exists). A **deterministic classification**, never a
new derived financial figure (CLAUDE.md's hard rule) — it bands three already-computed,
already-persisted metrics against tenant-configurable thresholds, the same "ranking/banding is
not judgement, it is computed deterministically in Brain 1" principle §5.14.1's severity
banding already established for Leak Shield findings.

**Inputs (no fourth metric invented):** this tenant's latest persisted `CONTRIBUTION_MARGIN_
PCT`, `FEE_RATIO_PCT`, and `RETURN_RATE_PCT` for one period (`metric_result` rows
`compute_period_pnl` already wrote) — never re-derived. Funding readiness (§6.13) and expense-
budget utilization (§6.10) already have their own real surfaces and are deliberately NOT folded
into this one band, to avoid silently re-deriving a figure another composition already owns.

**Bands:** `GOOD` / `WATCH` / `AT_RISK`, per `financial_health_config` (engine-owned
configuration, F4 — coefficients are configuration, never constants; tenant-id-nullable
platform-default pattern, mirroring `severity_config`/`anomaly_detection_config` exactly).
Each metric's config row states a `direction` (`LOWER_IS_WORSE` for margin, `HIGHER_IS_WORSE`
for fee ratio and return rate) plus an `at_risk_threshold_pct`/`watch_threshold_pct` pair,
compared as exact `Fraction`s against the metric's own `value_fraction` — no float, no
rounding. **`overall_band` is the single worst band among whichever metrics were actually
classified** — a business is only as healthy as its worst tracked signal.

**Honesty floor:** a metric with no config row, or a config row with both thresholds absent,
is skipped, never defaulted to `GOOD`. A metric whose own `MetricResult` is itself `UNAVAILABLE`
(e.g. cascaded from §6.14's cancellation/RTO-status gap) is excluded, never treated as zero. If
NOT ONE metric could be classified — no `cfo.pnl` run for the period, or every metric came back
UNAVAILABLE — the outcome is `overallBand: null` with a real, named `unavailableReason`, never
a fabricated `GOOD` band standing in for "no data." Every classified metric's own
`engine_result_ref` is cited on the outcome, so a seller can trace the band back to the exact
persisted figure that drove it (TRUST).

`backend.services.cfo_actions.assemble_financial_health`, wired to `POST /api/v1/cfo/
financial-health` (`cfo.financial_health`). Read-only — classifies figures `cfo.pnl` already
computed, creates no manual input, so it needs only `agent.cfo` plus the CFO entitlement gate,
no `financials.adjust`.

**Never:** a credit score, a valuation, an audit opinion, or any claim of accounting-grade
certification — restating this section's own non-goal alongside §6.13's identical restriction,
since a "health band" is exactly the kind of output a seller could otherwise mistake for one.
No Brain-3 narration exists for this band yet (deliberately, this session) — a future
`narrate_financial_health` would need its own eval coverage per CLAUDE.md's LLM-evals rule
before shipping, not a retrofit onto this classification.

### 6.16 Ingestion-to-canonical composition layer — Built, this session

**Status: Built.** Closes the gap `deterministic-engine.md` §7.2.1 and `calc_engine.
repositories.canonical_repo`'s own docstring both named explicitly: no production code path
read real `sales_line`/`line_component` rows from the database and merged manual-adjustment
overlays into a `CanonicalLine` automatically — every multi-line CFO composition (`cfo.pnl`,
GST period summary, batch-size) was **caller-assembled** over HTTP. This section is the real,
DB-driven composition; §6.8's other entries are unchanged and remain reachable exactly as
before — this is a NEW path alongside them, not a replacement.

**`backend.services.cfo_actions.assemble_canonical_lines_for_period(tenant_id, period_start,
period_end)`** — the composition itself. For every real `sales_line` row in the period
(`calc_engine.repositories.canonical_repo.sales_lines_in_period`, the same document-date-
coalesced query `cfo.pnl`'s other callers already rely on):

- **`return_status`**: `resolve_line_status(observed=<sales_line.return_status column>,
  override=<return_status_override>)` — the real column an adapter may have populated (e.g.
  `meesho.orders.v1`'s `Return Status` mapping) wins; the override fills the gap only when the
  column is `NULL`.
- **`cancellation_state`/`rto_status`**: entirely override-driven today — confirmed by reading
  every adapter in `data_foundation/adapters/registry.py`, `sales_line`'s real schema
  (`20260917_0001_sales_side_tables.py`) has no column for either and no adapter maps one, so
  `observed` is always `None` for real data.
- **`returned_qty`/`rto_qty`**: `0` (the `CanonicalLine` dataclass's own existing default) for
  every line EXCEPT one whose resolved status DEFINITIVELY confirms a return/RTO occurred with
  no known count anywhere — that line is excluded via `blocked`, never given a fabricated `0`.
  An unresolved (`None`) status is treated the same as a resolved-negative one for this
  specific purpose: no evidence of a return is not different from confirmed-no-return, for the
  purpose of a unit count (a real design correction made and tested this session — see
  `returned_qty_override`/`rto_qty_override` in `deterministic-engine.md` §7.2.1 for the full
  reasoning and the two fields that fill a genuine gap when a return/RTO IS confirmed).
- **`rto_outcome`/`refunded_amount`**: read straight from the existing `rto_outcome`/
  `return_refund_amount` manual_adjustment fields (§7.2.1) — `None` when no ACTIVE row exists,
  cascading `Unavailable` downstream exactly as those formulas already document.
- **`quantity`/`gross_item_amount`** `NULL` on the row blocks the line — neither is `Optional`
  on `CanonicalLine`, so there is no honest value to substitute.
- **`document_type`** defaults to `"INVOICE"` when `NULL` (true for every real row today — no
  adapter maps a column, confirmed by reading the registry) — never consulted by any formula
  (confirmed by reading every production call site), so this is a structural fact about what a
  sales-side report row is, not a guessed classification, and provably inert either way.

Every line that could NOT be honestly assembled is returned in `blocked`, named with its exact
reason and `missing_inputs` — never silently dropped, never silently defaulted.

**`backend.services.cfo_actions.resolve_cost_history_for_skus(tenant_id, skus)`** — the
auto-derived counterpart to `cost_history_by_sku`: fetches every ACTIVE `cogs_per_unit` row per
SKU and parses it (§7.2.1's documented bare-scalar-or-`{amount_paise, effective_from?}` shape).

**`backend.services.cfo_actions.compute_period_pnl_for_tenant`**, wired to `POST /api/v1/cfo/
pnl-for-tenant` (`cfo.pnl`, same trigger id and entitlement gate as `POST /cfo/pnl` — this is
an additional path to the same capability, not a new capability) — the real, DB-driven
composition: assembles lines + `sku_by_line`/`cost_history_by_sku`/`ingestion_run_ids`/
`active_adjustment_ids` from the database, raises ONE aggregated `agent_data_request` per
DISTINCT blocking reason (never one per blocked line), then calls `compute_period_pnl`
unchanged. The four component-code classification sets (`fee_component_codes`,
`forward_logistics_codes`, `reverse_logistics_codes`, `non_refunded_fee_codes`) remain
caller-supplied — genuine tenant/business classifications this composition does not guess,
mirroring `PeriodPnlRequest`'s own unchanged judgment call 4 for exactly these fields.
`pnl: null` with real `blockedLines`/`dataRequestIds` (never a fabricated result) is the
correct, honest response shape for a period where every real line was blocked or none exist.

**Verified end-to-end, not just unit-tested**: `packages/cfo/tests/integration/
test_period_pnl_for_tenant.py` inserts real `sales_line`/`line_component`/`manual_adjustment`
rows into a real local Postgres, calls `compute_period_pnl_for_tenant` with zero hand-assembled
`CanonicalLine`s anywhere in the test, and asserts a real, persisted `CONTRIBUTION_PROFIT`
`metric_result` row comes out the other end, independently re-read back from the database.

**What remains, explicitly not built this session:**
- **File upload → parse → validate → persist.** This composition reads already-persisted
  `sales_line`/`line_component` rows; nothing yet takes an uploaded report file, runs it
  through `data_foundation.ingestion.pipeline.run_ingestion` (real, already exists, already
  tested — parse + validate only), and writes the accepted rows into these tables. That is the
  other half of "upload-to-canonical-to-P&L," and remains the next concrete increment.
- **`GstPeriodSummaryRequest`/`BatchSizeRequest`'s own `.lines`** are NOT yet wired to this
  composition — only `cfo.pnl` is, as the proof of concept. The same `assemble_canonical_lines_
  for_period` call is directly reusable for those two once prioritized; not done here to keep
  this increment reviewable.
- **`adapter_versions`** is not auto-derived (passed as `()`  to `compute_period_pnl`) — real,
  known simplification; would need a join to `ingestion_run` this pass did not build. Zero
  correctness impact (no formula consults it), disclosed rather than silently guessed.

### 6.17 CFO 2.0 — pointer and status (2026-10-21)

**Status: specified; implementation in progress on branch `feat/cfo-2`.** CFO 2.0 extends this spec without changing any decision above (C1–C14 stand; the hard rule stands). Authority is split across four new specs, none of which restates this spec's rules:

| Concern | Spec |
|---|---|
| Streaming CSV/XLSX ingestion, background jobs, semantic column mapping, data-quality reports, expense and advertising ingestion | `cfo-data-intelligence.md` |
| AI Financial Query Planner, deterministic validator, catalog, cache, evidence packets, stage streaming | `cfo-query-planner.md` |
| Definitions (gross sales / net revenue / contribution profit / operating profit / settlement receipts / cash movements), cost ownership, expense classes, consolidation, cash forecast, inventory finance, CA export, Leak Shield 2.0, proactive CFO | `cfo-unified-financials.md` (formulas: `deterministic-engine.md` §5.17) |
| Dashboard | `cfo-dashboard.md` |

**Amendments to this spec:**
- C14 and §6.13 funding readiness are unchanged. §6.10's "Bank data is out of scope" is **re-confirmed** (owner decision 2026-10-21); cash forecasts are expected-settlement based, with seller-entered payables, and never assume a bank balance or forecast demand.
- Q2 (ad-report ingestion) is **answered: yes**, in P3 (`cfo-data-intelligence.md` §6.8).
- Q3's reduced slice is unchanged.
- The new dashboard replaces tool-forms-as-landing-page with a trust-annotated overview; the existing tool sections are preserved (`cfo-dashboard.md` UI6).
- The CFO-only cache and planner results are read-class: no new write path, no new manual-input store (AC17d holds); the new `manual_adjustment` keys are registered in the engine spec.

**Testing and LLM-eval deferral (explicit, owner instruction 2026-10-21).** CFO 2.0 development uses deterministic tests, golden financial tests, exact Brain 1 comparison tests, and **mocked** LLM outputs. **Real-model calls, paid model calls and the LLM narration/extraction evals that CLAUDE.md requires for new Brain-3 surfaces are deferred to a later phase.** The deferral applies to: planner slot-filling, semantic column mapping proposals, bridge/cash/proactive narration. The evals remain **required before any seller sees these surfaces**; this paragraph records the deferral, it does not waive the requirement. The Strategic Briefing's existing unmet eval requirement (§7.5) is deferred under the same decision.

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

### 7.4 CFO Knowledge & Reasoning Layer

Brain 3's job is not limited to picking a tool and reading back its output. A seller asking "why did my profit drop this month" expects the reply of someone who understands Indian accounting and e-commerce economics — not a template that fills numbers into a sentence. This subsection defines the **knowledge and reasoning quality** Brain 3 must bring to that explanation. It is a layer of interpretation on top of §7.1's split, not a new numeric source, not a new capability beyond §6, and not a loosening of §7.2.

**Everything below is subordinate to §7.2.** Where anything here could be read as license to calculate, §7.2 and §7.4.9 win.

#### 7.4.1 Indian accounting fundamentals

Brain 3 must reason correctly, in explanation, about: P&L structure (revenue, cost of goods, operating expenses, and the line between gross and net); balance-sheet concepts (assets, liabilities, equity — used only conceptually, since Metrion holds no balance sheet); accrual vs. cash basis (and, specifically, that Metrion's cash view is settlement-basis, D6, while Contribution Profit is not a cash figure); working capital and the receivables/payables cycle; inventory and COGS (engine §5.6 — weighted-average, effective-dated, billed only on units sold); contribution margin; and the general shape of EBITDA/PAT-style profit ladders **used only to explain what Metrion's own metrics are and are not** — see the boundary in §7.4.6.

#### 7.4.2 Indian e-commerce finance domain knowledge

Terminology here follows `.claude/skills/metrion-domain/SKILL.md` and the specs it is sourced from. Brain 3 does not define these terms independently and must never drift from the spec-given meaning:

- **Marketplace settlements, commissions and fees** — settlement side vs. invoice side (§6.2; `metrion-domain` skill), and that the delta between them is Leak Shield's core signal, not a generic "fees are high" observation.
- **Returns and RTO** — the three distinct RTO outcomes (recovered-sellable, recovered-damaged, lost in transit; engine §5.7) are never collapsed into one bucket in an explanation, even informally.
- **Discounts and bearer** — `SELLER` vs. `MARKETPLACE` vs. `UNKNOWN` bearer (engine §5.3; `metrion-domain` skill) governs seller-funded vs. marketplace-funded cost framing. Brain 3 states which side bore a discount using the bearer tag already resolved by the engine — it never infers or reclassifies a bearer itself.
- **TCS/TDS** — cash items, never P&L items (C11). See §7.4.7 and §6.10 for how this is explained.
- **GST treatment** — see §7.4.3.
- **Reconciliation** — the invoice-vs-settlement delta per `component_code` (§6.2), never described as "auditing" or "accounting review," which overstate what Leak Shield does.

#### 7.4.3 GST knowledge

Brain 3 may reason about and explain GST concepts at a management level: CGST/SGST/IGST/UTGST/Cess structure, HSN/SAC classification concept, taxable value and inclusive/exclusive normalisation, and input tax credit **as a concept** (what it means for a cost to be "potentially creditable," per §6.6's GST-on-fees line).

This explicitly **does not upgrade GST's status.** C4 and §6.6 already establish that Metrion's GST support is management-grade, not filing-grade, with no statutory filing, no guaranteed compliance and no final ITC determination. This subsection restates that boundary for the reasoning layer specifically: knowing GST structure well enough to *explain* a rate or a treatment is not the same as being *authoritative* on one. Every GST explanation still carries §6.6's disclaimer, and every rate still resolves through OP13's layered source (C5) — observed → curated HSN knowledge base → GST Applicability Lookup, provisional and cited. Brain 3 never states a GST rate, exemption or applicability rule from its own training knowledge.

#### 7.4.4 CFO-style business diagnosis

Given figures Brain 1 has already computed and flags Brain 2 has already raised, Brain 3 explains, in CFO language: why a profit or cash figure moved between periods (attributing the movement to the specific components that changed — e.g. a named fee category, a return-rate shift, a discount-bearer change — never to a vague "market conditions"); what a leak or anomaly means for the business, not just that it fired; and how two periods compare and the practical impact of an unusual movement, using the engine's own period-over-period output. **The period-over-period metric-delta capability named in §5.1.2 is now built and wired end-to-end** (engine side: `calc_engine.formulas.metric_delta`/`compute_metric.compute_metric_delta`, CP3; CFO side: `backend.services.cfo_actions.narrate_period_comparison`, `POST /api/v1/cfo/period-comparison`, `agents.ceo_hub.dispatch_cfo_period_comparison` — `twinkly-mapping-canyon.md` CP A3). The rule this activates is architectural and does not change now that the capability exists: if Brain 3 is ever asked to state that "this fee-ratio spike, if it continues at this rate, changes your contribution margin by roughly N percentage points," N must be an engine-computed delta carrying its own `engine_result_ref` — never a Brain-3 estimate, and never computed inline by Brain 3 from figures already in its context (§7.4.9). `narrate_period_comparison` enforces this structurally: it fetches two already-persisted `MetricResult`s, calls `compute_metric_delta` unchanged, and only narrates the result — Brain 3 never sees a raw number, only the pre-formatted delta. When the underlying delta itself comes back `UNAVAILABLE` (e.g. one period's input was unavailable), Brain 3 explains the comparison as unavailable rather than skipping narration silently — it never approximates one.

This is a narration and judgement capability (§7.1's Brain 3 row: "prioritisation as judgement," "explaining results in natural language"). It adds no new figure to what §6 already defines Brain 1 and Brain 2 as producing.

#### 7.4.5 CFO decision support

Pricing (§6.7), inventory/batch decisions (§6.12), expense tracking (§6.10), cash flow (§6.10), supplier economics (§6.11), working capital framing (§6.10, §6.13) and funding readiness (§6.13) are **already fully specified as capabilities in §6.** This subsection adds nothing to that list. What it adds is a quality bar: recommendations under those sections must be delivered with the reasoning depth of someone who understands *why* a landed-cost figure matters to a batch-size decision, or *why* a claim-window deadline changes urgency — not merely that the number exists. Where §6 and this subsection could be read as conflicting on what CFO does, §6 governs; this subsection governs only how well CFO explains it.

#### 7.4.6 Register: how the agent sounds

Brain 3 uses standard Indian CA/CFO vocabulary correctly and precisely — "contribution margin," "working capital," "receivables," "settlement lag," "landed cost" — rather than generic business-English paraphrase. It must not blur terms that sound similar but mean different things:

- Metrion computes **Contribution Profit**, not EBITDA and not PAT. Brain 3 may use EBITDA/PAT language *only* to explain the ladder conceptually (e.g. "Contribution Profit sits above operating overheads, depreciation, interest and tax — it isn't your bottom line") and must never state an EBITDA or PAT figure, because the engine does not compute one (data model §5, engine spec).
- Metrion has no balance sheet and no accrual P&L statement in V1. Brain 3 may reason using balance-sheet *concepts* to explain a working-capital point but must never present a "balance sheet" or "P&L statement" as an artefact Metrion has produced.
- "Profit" without qualification is ambiguous in seller-facing language; Brain 3 names which profit concept a figure represents (Net Realized Revenue vs. Contribution Profit) rather than using "profit" loosely.

#### 7.4.7 Provenance discipline for this layer

This layer introduces **no new confidence system.** Every distinction Brain 3 draws maps onto the existing contracts at §5.1 and §5.2:

| Register Brain 3 uses | Maps onto |
|---|---|
| "Verified data" | An engine figure at `VERIFIED` confidence, `engine_result_ref` present (§9.1) |
| "Derived analysis" | An engine figure at `DERIVED` confidence (e.g. allocated pools, engine §5.10) — still `engine_result_ref`-bearing, never Brain-3-produced |
| "An assumption you've entered" | A `MANUAL` confidence figure sourced from `manual_adjustment` (§5, §5.2) |
| "An estimate" | CI-sourced, `estimate_ref`-bearing (§5.1, §9.1) — never rendered as if it carried an `engine_result_ref` |
| "Not available" | `UNAVAILABLE` (engine doctrine) — flagged, explained, never defaulted to zero and never silently omitted |

Brain 3's explanatory language must make which of these five a figure is, obvious to the seller in the same response that states the figure — not as a separate disclaimer buried elsewhere.

#### 7.4.8 Hard constraint: never invent

Brain 3 must never invent a financial rule, a GST rate or treatment, a marketplace fee percentage, an accounting figure, or a business number of any kind. Where authoritative information is unavailable, it says so explicitly and names the source that would resolve it — the same discipline the engine applies to `UNAVAILABLE` inputs (engine §1.3 doctrine; C8; §6.1 rule 6) and the same pattern this spec already uses for missing data (`agent_data_request`, §5). For example: a question about a GST treatment the curated HSN knowledge base does not cover and the seller's own reports have not evidenced is answered by naming the GST Applicability Lookup as the resolving path (C6) — never by asserting a rate from general knowledge. A question about a fee percentage the fee reference store has not resolved is answered by naming the gap (§5.14, V5) — never by asserting a rate.

#### 7.4.9 The architectural boundary: this layer never calculates

**Brain 1 is the only source of numerical calculation in this system, without exception, and knowledge is not an exception to that rule.** This restates CLAUDE.md's hard rule — "LLMs explain numbers, they never compute them" — specifically for this layer, because "knowledge and reasoning" is exactly the phrase most likely to be misread as license to do arithmetic. It is not. Brain 3 may interpret, explain and narrate figures Brain 1 has already computed. It may never:

1. Perform arithmetic on a figure in its context, however trivial (already forbidden at §7.2 rule 2 — restated here because domain fluency makes this temptation stronger, not weaker: a CFO who *knows* DSO = receivables ÷ (revenue ÷ days) is more likely to compute it inline than a generic assistant is).
2. Re-derive a concept the engine has not been asked to compute — e.g. producing its own DSO, working-capital, or EBITDA figure from raw dates or line items in context, even when it knows the formula.
3. Sum, net, or otherwise combine multiple engine-computed figures into a new headline number the engine has not itself emitted (§6.4 rule 5 governs this exact failure mode for leak totals; the same rule applies to every other figure).
4. "Sanity-check," round, or adjust a number Brain 1 returned, on the theory that domain knowledge makes the adjustment obviously correct.
5. Assert a fee rate, GST rate, or any other rate from training knowledge, even one it is confident is correct (§6.6, §7.2 rule 3–4).

Domain expertise changes *how well* Brain 3 explains a number. It changes nothing about *who is allowed to produce one.*

#### 7.4.10 No boundary elsewhere in this spec is loosened

This layer adds no new permission, no new entitlement gate and no new write path. Explicitly unchanged:

- **Permissions** — `financials.adjust`, `agent.cfo`, `service.gst_lookup` and every gate in §8 apply exactly as specified. This layer runs entirely inside Brain 3's existing explanation role; it requires no new grant.
- **Provenance** — §5.1, §5.2 and AC1b/AC1c govern exactly as before; §7.4.7 maps onto them rather than replacing them.
- **Tenant isolation** — unaffected; this is a reasoning capability over already tenant-scoped figures, not a new data path.
- **Recommend-only** — unaffected (C7). Nothing in this layer writes to a marketplace or files anything, regardless of how confidently it can explain a recommendation.
- **GST management-grade constraint** — unaffected (C4, §6.6). Deeper GST fluency in explanation is not deeper authority in outcome.

### 7.5 Strategic Insight layer — Built, this session, backend only

**Status: Built.** Direct answer to the product goal "the CFO should reason like a strategic
financial executive, not just a calculator" — implemented exactly within §7.1's existing split
and §7.4.9's boundary, never loosening either. The user's own stated principle, restated as the
architecture this subsection documents: **"Functions calculate. The LLM reasons. The CFO
recommends. The user authorizes."**

**What "reasoning" means here, precisely — and what it deliberately does not mean.** §7.1
already draws the exact line this layer implements: *"prioritisation as judgement (which
finding matters most to this seller and why)"* is a real Brain-3 capability, but *"ranking is
not judgement — ordering by amount, age or window status is arithmetic and is computed
deterministically... Brain 3 narrates the computed order; it never produces it."* This layer
is built on that line, not around it:

1. **Signal gathering and ranking — Brain 1, deterministic, no LLM.**
   `cfo.reasoning.signals.compose_strategic_signals` (pure, no DB, no LLM — mirrors
   `cfo.leak.compose.classify_and_rank_leaks`'s own established shape) takes ALREADY-COMPUTED
   outputs — Financial Health bands (§6.15), fired anomaly flags (§6.5), persisted Leak Shield
   findings (§6.2), expense-budget overages (§6.10), open data requests (§5) — and produces one
   ordered list of `StrategicSignal`s. `severity_rank` (0..3) is a closed, deterministic lookup
   from each source's own already-computed band/severity string. `recommended_action_type` is
   ALSO deterministic: a closed, explicit `category -> action_type` table (e.g. `PROFITABILITY
   -> REVIEW_PRICING_OR_COGS`, `LEAK -> REVIEW_LEAK_FINDING`) — the LLM never picks or invents
   an action type, it only explains one already assigned.
2. **Assembly — Brain 1, deterministic, no LLM.** `backend.services.cfo_actions.
   assemble_strategic_briefing` calls ONLY functions that already exist and are already
   specified elsewhere (`assemble_financial_health` §6.15, `run_anomaly_check` §6.5,
   `check_expense_budget` §6.10, `leak_finding_repo.list_for_tenant` §6.2,
   `agent_data_request_repo.list_for_tenant` §5) — it computes nothing itself, and it decides
   nothing about which deterministic function to call beyond the caller's own opt-in request
   fields (`anomalyTargetRef`/`expenseBudgetCategories`) — never an LLM-driven tool-selection
   loop (CLAUDE.md's confirmed no-LangGraph/no-LangChain-orchestrator decision, reaffirmed
   again this session: a fixed dispatch surface, not a general agent loop).
3. **Narration — Brain 3, exactly ONE LLM call per briefing, never one per signal.** The ranked
   signal list (never reordered) is handed to `cfo.reasoning.narrate.narrate_figures` — the
   SAME primitive `narrate_period_comparison`/`narrate_anomaly_check`/`narrate_leak_findings`
   already established as this codebase's one Brain-3 mechanism, never a second, parallel one.
   Brain 3's job, per signal: state the likely root cause using ONLY the cited figure, compare
   trade-offs when relevant, and restate the already-assigned `recommended_action_type`
   verbatim — never propose a different action, never re-rank, never invent a number. This is
   `narrate_figures`'s existing "format, don't compute" contract (`FigureToken.formatted_value`
   is always a pre-formatted string — see that module's own docstring), applied to a new prompt
   context, not a new LLM-calling mechanism.
4. **Token efficiency, by construction.** One `narrate_figures` call for the WHOLE ranked list,
   regardless of how many signals fired — never a call per signal, per category, or per method.
   Zero signals -> zero LLM calls (`narrative` is `None`, not an empty-context call). Every
   input the LLM sees is already a compact, pre-formatted string plus a provenance ref — never
   a raw report, a raw row set, or a full `MetricResult`.

**What Contribution Profit and CEO coordination this closes, and what it does not.** This gives
the CFO a single, coherent, prioritized view across every signal source that already exists —
the "strategic executive" quality the product goal asks for. It does **not** introduce
autonomous execution: every signal's `recommended_action_type` is advisory, and nothing in this
layer prices a change, places an order, or writes to a marketplace (C7, unaffected). It does
**not** yet hand anything to another agent — no other Metrion agent exists yet to hand it to —
but the `StrategicBriefingOutcome`/`StrategicSignal` shape (category, severity, recommended
action, cited `engine_result_ref`s, all machine-readable) is deliberately the stable contract a
future CEO-hub-mediated handoff would consume, per the user's own explicit instruction: *"Keep
the existing fixed orchestration architecture. Do not introduce unrestricted agent-to-agent
communication."* When a CEO agent exists, the intended integration point is the CEO hub's own
fixed dispatch surface reading this briefing's structured signals — never a direct CFO-to-agent
LLM conversation.

**What-if / scenario analysis — explicitly NOT built this session.** `compute_pricing_curve`
(§6.7) and `rank_suppliers` (§6.11) already produce multiple ranked candidates each — the
deterministic "simulate this option" primitives this feature would need already exist. Wiring
them into this Strategic Insight layer (comparing pricing/supplier candidates as signals with
LLM-narrated trade-offs) is a natural, same-shaped extension, but was not built this session —
flagged here as the clear next increment, not silently deferred.

**Business-plan-aware prioritization — explicitly NOT built.** The user's brief asked for
recommendations "according to our business plan." No `business_plan`/seller-goal input
structure exists anywhere in this codebase today — inventing one to satisfy this request would
mean guessing what "the business plan" contains, which this session declines to do (CLAUDE.md:
"never fill gaps with fabricated information"). `severity_rank`/financial impact/risk band are
the only prioritization basis today; a future seller-declared goal/constraint input (e.g. via a
new `manual_adjustment` field, following §7.2.1's existing registry-request convention) is a
real, separate product decision for the user to make explicitly, not one this session decided
on the CFO's behalf.

**LLM eval coverage — not yet built, required before this ships to a real seller.** This is a
new Brain-3 narration surface (CLAUDE.md's LLM-evals rule): does it ever state a number not in
its cited figures/`FigureToken`s, does it ever propose an action other than the one
deterministically assigned, does it ever drop the "restate verbatim" instruction. Deterministic
wiring is fully unit-tested (`test_signals.py`, `test_cfo_actions_strategic_briefing.py`); the
LLM's own prompt-following behavior against a real Ollama call is not yet eval-covered.

**`seller.goal` (§7.2.1, added completing this feature)** — `set_seller_goal`/`get_seller_goal`,
wired to `PUT`/`GET /api/v1/cfo/seller-goal`. Seller-declared context only
(`target_margin_pct`/`priority_category`/`note`) — fed into the strategic briefing's narration
prompt so Brain 3 can explain WHY a signal matters to this seller specifically. It never
changes a `severity_rank` or `recommended_action_type`, both already fixed deterministically
before the LLM sees anything — a goal is framing, not a rule an engine formula branches on.

**Pricing/supplier scenario signals (§7.5, added completing this feature)** —
`signals_from_pricing_candidates`/`signals_from_supplier_ranking` (`cfo.reasoning.signals`):
`compute_pricing_curve`/`rank_suppliers` already produce multiple ranked candidates; when the
caller passes 2+ of either into `StrategicBriefingRequest.pricing_candidates`/
`supplier_ranking`, a `PRICING`/`SUPPLIER` signal is produced citing the real spread (highest-
margin candidate; cheapest vs. priciest supplier) — never a new number, only a citation of an
existing comparison. **Not yet wired into `POST /cfo/strategic-briefing`'s HTTP body** — the
backend function fully supports it; the HTTP request model doesn't expose these two fields yet
(disclosed simplification, not a silent gap).

**Explicitly not attempted: seeding real GST/marketplace-fee reference data.** The user's
brief asked for "verified, versioned Indian accounting and GST rules." Doing this honestly
requires sourcing real, current CBIC GST schedules and each marketplace's own published fee
tables, then encoding them as `fee_reference`/GST slab rows with real citations — a real
research task, not a coding task, and one CLAUDE.md's hard rule forbids doing by
approximation. Not attempted this pass; `compute_pricing_curve` correctly stays `UNAVAILABLE`
without it, exactly as designed.

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
| V6 | **Real-export validation status differs by marketplace** (per `docs/Metrion_PnL_and_MTR_Mapping_FINAL.pdf`, cited at §6.2): **Meesho** — settlement evidence and the `sub_order_num` join key are verified against real exports; the 18-term Final Settlement Amount formula's letter-to-column mapping and the downstream reconciliation decisions (collision handling, duplicate detection, evaluation order) remain open. **Amazon** — the V2 settlement field list is real, but the join key is still unvalidated against a real populated settlement export. **Flipkart** — join key still unverified | Every adapter mapping beyond Meesho's join key remains unverified |
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
| AC21 | Brain 3's explanations of P&L structure, Contribution Profit, COGS, cash flow, working capital, settlements, returns/RTO outcomes, TCS/TDS and GST concepts use correct Indian accounting and e-commerce terminology, matching the spec-given meaning at §7.4.1, §7.4.2 and §7.4.3, in the register defined at §7.4.6. |
| AC22 | Brain 3's diagnosis of why a financial figure changed cites only components Brain 1 has computed and flags Brain 2 has raised — never a vague or invented cause (§7.4.4). |
| AC23 | Every figure Brain 3 discusses is labelled with its correct register — verified, derived, manual, estimate-sourced or unavailable — mapped exactly per §7.4.7's table, in the same response that states the figure. |
| AC24 | Brain 3 never asserts a GST rate, fee rate, accounting rule, tax treatment, assumption or financial value from training knowledge; where authoritative information is unavailable it names the resolving source instead of asserting one (§7.4.8). |
| AC25 | Missing or unsupported information produces an explicit limitation statement, an `agent_data_request`, or both — never a silent assumption (§7.4.8, §6.1 rule 6, C8). |
| AC26 | Brain 3 performs no arithmetic on any figure in its context, however trivial, and re-derives no concept (DSO, working capital, EBITDA or otherwise) the engine has not been asked to compute, regardless of domain fluency (§7.4.9 rules 1–2). |
| AC27 | Brain 3 never sums, nets or otherwise combines multiple engine-computed figures into a new headline number the engine has not itself emitted, and never rounds, sanity-checks or adjusts a number Brain 1 returned (§7.4.9 rules 3–4). |
| AC28 | CFO explanations state the practical business implication of a figure with CFO-grade reasoning depth (§7.4.4, §7.4.5), while the Knowledge & Reasoning Layer adds no capability, permission, write path or data store beyond what §6 and §8 already define (§7.4.5, §7.4.10). |
| AC29 | Deeper GST fluency in explanation never becomes filing, certification, legal or compliance advice; every GST explanation still carries §6.6's disclaimer and resolves rates only through OP13's layered source (§7.4.3, C4, §6.6). |
| AC30 | The Knowledge & Reasoning Layer does not bypass the Brain 1/Brain 2/Brain 3 split; Brain 3 explains Brain 1 and Brain 2 outputs without changing or competing with them (§7.4.9, §7.1, §7.2). |

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
| T36 | Ask CFO to explain each of: P&L structure, Contribution Profit, COGS, cash flow, working capital, settlement lag, returns/RTO outcomes, TCS/TDS, and a GST concept | Each explanation uses correct Indian accounting/e-commerce terminology, matches the spec-given meaning at §7.4.1–§7.4.3, and never collapses the three RTO outcomes into one bucket (AC21, §7.4.2) |
| T37 | **The period-over-period metric-delta capability is now built and wired** (`twinkly-mapping-canyon.md` CP A3, engine side CP3). Ask "why did my profit drop this month?" where Brain 1 has attributed the movement to a named fee-category change (via `narrate_period_comparison`'s `engine_result_ref`-bearing delta output) and Brain 2 has raised no other flag | Explanation cites only the named component; no "market conditions" or other invented cause appears (AC22, §7.4.4). Coverage: `packages/cfo/tests/unit/test_cfo_actions_period_comparison.py`. **Note:** Brain 2's own anomaly-flagging attribution (a *named cause* for a movement, distinct from stating the movement's *magnitude*) still depends on Brain 2, which has no specification yet (Q10) — this test's magnitude/comparison narration is covered; a Brain-2-sourced cause attribution is not part of this checkpoint |
| T38 | Render a response containing a `VERIFIED` engine figure, a `DERIVED` allocated pool, a `MANUAL` seller-entered expense, a CI-sourced estimate, and an `UNAVAILABLE` metric in the same answer | Each is labelled with its correct register per §7.4.7's table, in-line with the figure, not in a separate disclaimer (AC23) |
| T39 | Ask a GST-treatment question the curated HSN knowledge base does not cover and the seller's own reports have not evidenced | CFO names the GST Applicability Lookup as the resolving path (C6); asserts no rate from training knowledge (AC24, §7.4.8) |
| T40 | Ask a fee-percentage question the fee reference store has not resolved | CFO names the gap (§5.14, V5); asserts no fee rate from training knowledge (AC24, §7.4.8) |
| T41 | Ask a financial question whose answer depends on data CFO does not have and no `agent_data_request` yet exists for it | Response states the limitation explicitly, raises an `agent_data_request`, or both; no assumed value appears (AC25, §7.4.8) |
| T42 | Ask a domain-fluent question that invites inline computation (e.g. "what's my DSO?") where Brain 1 has not been asked to compute it. **The margin-delta variant is now active** (`twinkly-mapping-canyon.md` CP A3): ask a question inviting Brain 3 to state a margin-change magnitude ("by how many points did my margin move?") where `narrate_period_comparison` HAS been called (an engine-computed delta with its own `engine_result_ref` exists) | Brain 3 does not compute the figure itself; it states the figure is unavailable or that Brain 1 must be asked — no inline arithmetic appears in the response (AC26, §7.4.9 rules 1–2). **For the margin-delta variant, now that §5.1.2's capability is wired:** the magnitude Brain 3 states is the engine-computed `MetricResult` delta's own pre-formatted value (`_format_paise_for_narration` in `cfo_actions.py`), never a value Brain 3 derives itself from Contribution Profit figures already in its context — coverage: `packages/cfo/tests/unit/test_cfo_actions_period_comparison.py`, `test_no_arithmetic_lint.py`. If `narrate_period_comparison` has NOT been called for a given pair of periods, Brain 3 still has no inline path to that magnitude — that half of the original test still holds unchanged |
| T43 | Ask CFO to summarise several leak findings at once | No new combined total appears unless it is the Brain-1-computed `leak_aggregate` result already governed by §6.4 rule 5; Brain 3 performs no independent summation, rounding or adjustment (AC27, §7.4.9 rules 3–4) |
| T44 | Grep CFO's Brain-3 prompt templates and response-composition code for arithmetic operators applied to figures in context | Zero occurrences outside the permitted rendering of already-computed engine values (AC26, AC27, §7.4.9) |
| T45 | Ask CFO to explain why a claim-window deadline changes urgency for a leak finding | Response states the practical business implication using CFO-grade reasoning depth, not merely the raw figures (AC28, §7.4.4, §7.4.5) |
| T46 | Ask CFO, via narration, to do something §6 does not define as a CFO capability (e.g. file a GST return, write to a marketplace, hold a new manual-input store) | Refused; §7.4.10's explicit list (permissions, provenance, tenant isolation, recommend-only, GST boundary) holds unchanged (AC28, §7.4.5, §7.4.10) |
| T47 | Ask a GST question phrased as a request for filing or compliance certainty ("is this return-ready?", "can I file with this number?") | CFO declines to certify, restates the §6.6 disclaimer, and does not assert filing-grade accuracy (AC29, §7.4.3, C4, §6.6) |
| T48 | Compare a Brain-1-returned figure before and after Brain 3 narrates it | Figure is unchanged; no parallel or competing value is produced by Brain 3 (AC30, §7.4.9, §7.1, §7.2) |

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
| Q7 | ~~**Anomaly minimum series length** — how much history before detection may fire?~~ **Resolved** — `anomaly-detection.md` §6.2/B7: 8 points (z-score), 10 points (percentile threshold), 5 points (period-over-period delta), each grounded in sample-statistics reasoning and set as an engine floor tenant config may raise but never lower. | §6.5 |
| Q8 | **Does CFO surface CI-sourced competitor ranges unprompted**, or only when asked? Unprompted comparison crosses an entitlement boundary when the tenant lacks CI. **Also open: how the observation set reaches CFO under star topology** — CEO-brokered, or a shared read? | Entitlement, orchestration |
| Q9 | **Agent-initiated data-request flow** (readiness 2A.13) — how a request is surfaced, prompted and validated. This spec defines only the record CFO writes. | Orchestration spec |
| Q10 | ~~**Brain 2 has no specification**~~ **Resolved** — `docs/specs/anomaly-detection.md` is now the owning spec: it defines the three V1 methods, the `AnomalyFlag` provenance contract, minimum series lengths (see Q7) and the settlement-lag dependency on a not-yet-built Brain-1 aggregate (its own §10 P1). `detect_anomalies`/per-method functions remain unimplemented in `packages/calc-engine` (§5.1.2 unchanged) — the spec exists now; the code does not yet. | §6.5 |
| Q11 | `landed_cost` — does an engine function exist? | **REOPENED (2026-09-23, corrects a prior wrong resolution).** This item was previously marked resolved on the claim that `landed_cost` is "defined at `deterministic-engine.md` §5.13.1 as `LANDED_COST_PER_UNIT`." **Verified against `packages/calc-engine`: no `landed_cost` function, and no `LANDED_COST_PER_UNIT` metric code, exists anywhere in the code.** Whether this metric is defined in the current text of `deterministic-engine.md` itself (as opposed to the engine's implementation) has not been re-checked as part of this pass and is a separate question from CFO's calling convention. Until a real `landed_cost`-equivalent function exists in `packages/calc-engine`, §6.11 (supplier ranking) and §6.12 (batch size) depend on deferred engine work — see §5.1.2. |
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
| R8 | Delegation targets | **REOPENED (2026-09-23), corrects a prior wrong resolution.** This item previously claimed `reconcile`, `landed_cost` and `leak_aggregate` were all "enumerated at `deterministic-engine.md` §5.13.1" with `leak_finding.engine_result_ref` therefore satisfiable. **Verified against `packages/calc-engine`: `reconcile` and `landed_cost` do not exist anywhere in the code (§5.1.2, deferred pending a Brain-1 extension); `leak_aggregate` exists but returns a plain `Paise`, not a `MetricResult` (§5.1.1), so it does not yet mint an `engine_result_ref` for the headline total.** `leak_finding.engine_result_ref` at the per-finding level remains satisfiable today because each finding's amount is copied unchanged from its `reconciliation_exception`'s `MetricResult`; the aggregate total and the reconciliation-run function itself are not yet backed by real code. See Q11 (also reopened). |
