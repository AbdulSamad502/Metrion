# Metrion — CFO AI Financial Query Planner and Validator Specification

**Status:** Draft for review (CFO 2.0, P2)
**Prerequisites:** `deterministic-engine.md` (the only source of financial arithmetic) · `cfo-agent.md` (CFO capabilities, C1–C14) · `cfo-unified-financials.md` (definitions, grain contracts, cost ownership) · `cfo-data-intelligence.md` (what lands in the canonical store) · `ceo-agent-orchestration.md` (fixed registry, star topology) · `auth.md` (tenancy)
**Related:** `cfo-dashboard.md` (reads the same results and cache)

**The planner chooses. The validator decides. Brain 1 calculates.** The model's only job is to turn a seller's question into a *typed selection from a closed catalog*. Nothing the model emits is ever executed as code, SQL, or a formula.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| Q1 | **No LLM-generated SQL, Python or formulas.** The planner emits a typed JSON plan whose every identifier (metric, dimension, filter, period, join) is drawn from a closed, versioned catalog. | CLAUDE.md hard rule; user brief §2 |
| Q2 | **Aggregation operations come from the metric definition**, not from the model. A plan names a metric; the catalog says whether it is a SUM, COUNT, DISTINCT, weighted average or engine formula. | User brief §2/§4 |
| Q3 | **Brain 1 owns all arithmetic.** Set-based SQL execution is permitted only where it is *proven equal* to the per-line engine on the golden dataset (the oracle test, §9). | User approval 4 |
| Q4 | **No LangGraph / no LangChain orchestration.** The planner is one structured-output call inside a fixed dispatch, behind the existing `LlmProvider` (text in, text out). | CLAUDE.md |
| Q5 | **Seller reaches the planner only through CEO.** The planner is a CFO-internal step; there is no HTTP endpoint that accepts a free-form plan from a client. | cfo-agent.md C9 |
| Q6 | **Local Ollama for planning in dev**, mocked in tests. No real-model calls or LLM evaluations in this development cycle (§12). | User approval 7 |
| Q7 | **Missing input is `UNAVAILABLE`, never zero**, and raises an `agent_data_request` (cfo-agent.md AC10). | CLAUDE.md |
| Q8 | **Every figure returned cites an `engine_result_ref`** (or an `estimate_ref` for estimates — never interchangeable). | CLAUDE.md |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Where plan *templates* sit | A small set of **deterministic plan templates** (profit bridge, marketplace comparison, SKU ranking, leak summary, cash view) selected by CEO's existing classifier; the model only fills slots (period, marketplace, SKU, metric). Free composition is limited to catalog-legal combinations. | Reliability: dbt's benchmark and the bounded-semantic-planning literature both find governed selection beats open-ended generation. Smaller model surface = fewer wrong answers. |
| D2 | Result-cache key | `sha256(canonical_plan_json ‖ tenant_id ‖ data_version ‖ catalog_version ‖ formula_versions)` | Any change to data, catalog or formulas invalidates. No time-based staleness. |
| D3 | Cache store | Redis, tenant-prefixed keys, value = evidence packet only (never raw rows) | Redis already runs; evidence packets are small. |
| D4 | Profit "why" | A **profit bridge** (period A → period B) computed by Brain 1 as a metric delta per cost driver, with an explicit `OTHER` residual line so drivers sum exactly to the delta. | Drivers must reconcile; a bridge that silently omits a driver is worse than none. |
| D5 | Execution path | **Two paths, one truth:** the existing per-line Python engine is the *reference oracle*; set-based SQL is the *fast path*. In production the fast path runs; in CI both run and must agree to the paisa. | Speed without forking the definition of profit. |
| D6 | Large result sets | The evidence packet carries top-N rows with a `truncated: true` flag plus a drill-down handle; never the full set. | Token control; the dashboard pages server-side. |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | Canonical rows are already deduplicated and carry provenance (`source_row_number`, `ingestion_run_id`) | High — duplicates inflate every aggregate |
| A2 | `document_date` resolution (engine §6) is the period basis unless a metric declares settlement-date basis | Medium |
| A3 | Per-line P&L is fast enough to serve as an oracle on test datasets (≤ 100k rows) | Low |
| A4 | Planner latency target (<5 s common questions) is dominated by one LLM call plus cached Brain 1 results | Medium — unmeasured; a benchmark task (§11) records it |

---

## 4. Goals and non-goals

**Goals** — a seller question becomes a validated, executable plan; Brain 1 executes across the *complete* dataset; the CEO receives a compact, source-linked evidence packet; unsafe, ambiguous or under-specified plans are refused with a reason; results are cached and invalidated by data change; the CEO UI can stream stage progress.

**Non-goals** — free-form SQL; model-defined metrics; forecasting demand; writing to any marketplace; sending raw rows to an LLM; a general analytics engine. Questions outside the catalog get an honest "I cannot compute that yet" plus, where sensible, an `agent_data_request` — never an improvised answer.

---

## 5. Data model and interfaces

### 5.1 Metric catalog (versioned, code-owned, not seller-editable)

```
MetricDef {
  id: str                       -- e.g. "CONTRIBUTION_PROFIT"
  kind: ENGINE_FORMULA | SET_SUM | SET_COUNT | SET_DISTINCT_COUNT | SET_WEIGHTED_AVG | RATIO
  engine_ref: str | None        -- the calc_engine function this must equal (oracle target)
  grain: line | order | sku | marketplace | account   -- finest grain it is defined at
  allowed_dimensions: set[DimensionId]
  required_inputs: list[InputId]            -- absent => UNAVAILABLE + data request
  basis: DOCUMENT_DATE | SETTLEMENT_DATE
  sign_convention: str
  unit: PAISE | COUNT | PERCENT_FRACTION | DAYS
  explainable_by: list[MetricId]            -- drivers for a bridge
  formula_version: str
}
DimensionDef { id, source_table, column, grain, cardinality_hint }
JoinDef      { id, left, right, key_columns, cardinality: ONE_TO_ONE | MANY_TO_ONE | ONE_TO_MANY,
               uniqueness_side, control_total_column, validated: bool }
```

V1 catalog (all already exist in Brain 1 unless marked NEW; NEW metrics are defined in `cfo-unified-financials.md` §6 and added to `deterministic-engine.md`): `GROSS_SALES` (NEW), `NET_REALIZED_REVENUE`, `MARKETPLACE_FEES`, `FEE_RATIO_PCT`, `RETURN_RATE_PCT`, `RETURN_RTO_LOSSES`, `CONTRIBUTION_PROFIT`, `CONTRIBUTION_MARGIN_PCT`, `OPERATING_PROFIT` (NEW; `PROVISIONAL` while any expense is unclassified, `FINAL` otherwise, never blocked by thin expense data: decision OQ1), `SETTLEMENT_RECEIPTS` (NEW), `SETTLEMENT_LAG_DAYS`, `LEAK_AGGREGATE`, `ROAS/ACOS/TACOS` (NEW), `EXPENSE_BY_CATEGORY` (NEW, SET_SUM over `manual_adjustment`), `PROFIT_BRIDGE` (NEW, composite).

Dimensions V1: `marketplace`, `sku`, `period` (day/week/month), `component_code`, `expense_category`, `return_reason` (where reported).

### 5.2 Plan schema

```
QueryPlan {
  plan_version: "1"
  intent: PROFIT_BRIDGE | METRIC_BY_DIMENSION | RANK | COMPARE_PERIODS | LEAK_SUMMARY | CASH_VIEW | EXPENSE_BREAKDOWN
  periods: [PeriodRef]                       -- explicit start/end/as_of_date, never "now"
  steps: [ filter | normalize | join | group_by | aggregate | metric | compare | rank ]
  filters: { marketplace?, sku?, ... }       -- only DimensionDef ids
  limit: int
}
```

Steps are an ordered list of **catalog-referencing operations**, each parameterised only by catalog ids and literal values (dates, SKU strings). A step type not in the enum is a validation error, not an extension point.

### 5.3 Evidence packet (what CEO receives)

```
EvidencePacket {
  plan_hash, catalog_version, data_version, as_of_date
  figures: [ { metric_id, value_paise|fraction|count, status: VERIFIED|DERIVED|MANUAL|ESTIMATED|UNAVAILABLE,
               engine_result_ref | estimate_ref, dimension_keys, formula_version,
               exclusions: [{reason, count}], missing_inputs: [..] } ]
  bridge?: { from, to, delta, drivers:[{metric_id, delta, ref}], other:{delta, ref} }
  rows_examined: int, rows_excluded: int
  drilldown: [ { handle, label, row_count } ]
  data_requests: [id]
  stages: [ {name, ms} ]
}
```
Raw rows never appear. Figures are pre-formatted strings for narration (`FigureToken`, existing mechanism).

---

## 6. Core rules

### 6.1 Pipeline

`CEO classifier → CFO dispatch → (1) plan (LLM slot-fill or template) → (2) VALIDATE → (3) cache lookup → (4) Brain 1 execute → (5) post-execution checks → (6) evidence packet → CEO narration`.

A plan that fails (2) or (5) is **not retried silently**: the failure reason is returned; the CEO may re-ask the planner once with the validator's error list (bounded, one retry), then refuses honestly.

### 6.2 Validator — rule catalog

Every rule is a pure, deterministic function `(plan, catalog, data_stats) -> list[Violation]` with a stable rule id. Any `ERROR` blocks execution. Rules are grouped; the list is the contract for tests.

**V-SCH — Schema and identity**
- V-SCH-1 every metric, dimension, join, filter key is in the catalog (unknown id → reject; never "best match")
- V-SCH-2 plan parses against the typed schema; unknown fields rejected
- V-SCH-3 every referenced source carries `tenant_id`; the plan has no tenant field (a client-supplied `tenant_id` anywhere is a hard reject)
- V-SCH-4 period bounds present, ordered, and `as_of_date` explicit (never "now") and not before the period start
- V-SCH-5 a plan computes at least one registered metric
- V-SCH-6 steps are in canonical order (filter/normalize → join → group_by → aggregate/metric → compare → rank), and a step's op matches its metric's kind (set aggregations use `aggregate`; engine metrics use `metric`)

**V-GRN — Grain**
- V-GRN-1 a metric is never requested at a grain finer than its declared grain
- V-GRN-2 group-by dimensions must be in the metric's `allowed_dimensions`
- V-GRN-3 *(folded into V-GRN-1/2, evaluated per metric — each metric is checked against its own grain and allowed dimensions; no plan-level bridge concept is needed)*
- V-GRN-4 an account-level pool (e.g. account ad spend) grouped by SKU is allowed **only through the engine's allocation (§5.10)** and the result is labelled `DERIVED`

**V-JOIN — Joins (the fan-out guard)**
- V-JOIN-1 only catalog `JoinDef`s are usable; ad-hoc key pairs rejected
- V-JOIN-2 declared uniqueness verified against data: on the "one" side `count(*) = count(distinct key)` over the plan's scope; violation → reject (or, for legitimate one-to-many relationships, the plan must aggregate the many side to the key *before* joining — see V-JOIN-4)
- V-JOIN-3 **control totals**: the sum of the join's control column on the driving side is measured before and after the join; they must be equal, always (including for a legitimate one-to-many join routed through pre-aggregation). A mismatch is a fan-out and blocks execution.
- V-JOIN-4 legitimate one-to-many (an order with several fee, refund or adjustment rows) is supported only as *aggregate-then-join*: the many side is grouped to the key first, then joined many-to-one. The validator rewrites nothing — it rejects plans that do not already have that shape, and the catalog templates always do.
- V-JOIN-5 no settlement **line** matches more than one order line unless the join declares `MANY_TO_ONE` with a stated reason (e.g. one payout per batch). An *order* matching several settlement lines (fees, refunds, adjustments) is legitimate one-to-many: it is allowed and only disclosed, never rejected.
- V-JOIN-7 a join whose key has not been validated against a real export (`JoinDef.validated=false`): **Amazon** joins are blocked with the reason "pending match-key verification" (cfo-agent AC5); other unvalidated joins (Flipkart) run but the result carries the `PROVISIONAL_JOIN` label
- V-JOIN-6 unmatched rows on either side are reported as counts and amounts (`rows_excluded`), never silently dropped

**V-DUP — Double counting**
- V-DUP-1 duplicate rows are classified and excluded or held by ingestion (`cfo-data-intelligence.md` §6.3, V-DUP-001/002/003); the validator re-asserts, for any source used, `count(*) = count(distinct identity)` over *posted* rows, where identity is the ingestion identity. Legitimate repeats (partial settlements, adjustments) have distinct identities by construction
- V-DUP-2 **cost-ownership check** (`cfo-unified-financials.md` §5): a cost component may be sourced from exactly one owner (marketplace deduction *or* seller expense *or* manual override) for a given scope and period; two active owners for the same component → reject until the seller resolves which is authoritative
- V-DUP-3 an expense entry flagged `MAY_OVERLAP_MARKETPLACE` and unconfirmed is excluded from totals and disclosed

**V-ACC — Accounting identities**
- V-ACC-1 `GROSS_SALES − reductions = NET_REALIZED_REVENUE` per engine definition
- V-ACC-2 Σ marketplaces (each filtered) = consolidated for every additive metric, tolerance 0 paise
- V-ACC-3 a profit bridge's drivers plus `OTHER` equal the delta exactly; `OTHER` > a configurable share of |delta| is flagged `LOW_EXPLAINABILITY`
- V-ACC-4 TCS/TDS never appear in any P&L metric (C11); owner drawings, inventory purchases, capital items, and transfers never appear in any P&L metric
- V-ACC-5 COGS is recognised on units sold (engine), never on purchases
- V-ACC-6 a ratio metric is `UNAVAILABLE` when its denominator is zero — never zero, never infinity

**V-PER — Basis and period**
- V-PER-1 a plan uses one basis per metric; mixing `DOCUMENT_DATE` and `SETTLEMENT_DATE` figures in one comparison requires an explicit label
- V-PER-2 a period comparison needs two periods; unequal lengths run but carry the `UNEQUAL_PERIODS` label
- V-PER-5 compared periods must not overlap
- V-PER-3 a partial period (data coverage ends before `period_end`) is flagged `PARTIAL_PERIOD` with coverage dates, never presented as complete
- V-PER-4 settlement lag differences are labelled **timing**, not error

**V-UNIT — Units and conventions**
- V-UNIT-1 money is integer paise end-to-end; any float in a money path → reject (existing lint)
- V-UNIT-2 sign convention per component honoured; a sign-inconsistent source column is quarantined at ingestion, and the validator rejects plans reading an unquarantined inconsistent column
- V-UNIT-3 tax inclusion consistent across a metric's inputs (GST-normalised per engine §8.1)
- V-UNIT-4 single currency (INR) in V1; any other currency → reject

**V-CMP — Completeness**
- V-CMP-1 each required input must meet a configured minimum coverage (config-owned, **no defaults in code**). Below it, unmeasured, or unconfigured (`CONFIG_MISSING`), the *metric* is `UNAVAILABLE` with the reason — this does **not** fail the plan; the executor returns the honest `UNAVAILABLE` plus a data request (V-CMP-3). Never defaulted, never assumed full
- V-CMP-2 every exclusion is named with a count and amount
- V-CMP-3 missing input → `agent_data_request` raised once (de-duplicated per reason)

**V-RES — Resources**
- V-RES-1 estimated rows scanned ≤ configured cap; group cardinality ≤ cap; statement timeout enforced by the DB role
- V-RES-2 result `limit` bounded
- V-RES-3 the executor connects with the tenant-scoped RLS role; `SET LOCAL` tenant context is mandatory (fails closed)

**V-DET — Determinism and provenance**
- V-DET-1 same `plan_hash` + `data_version` → byte-identical packet (tested)
- V-DET-2 every figure has an `engine_result_ref`/`estimate_ref`; a figure without one is a post-execution error
- V-DET-3 post-execution: **oracle spot-check** — for a bounded deterministic sample of SKUs (seeded by `plan_hash`) the fast path value is recomputed through the per-line engine; any difference fails the plan and is logged as a defect

### 6.3 Execution

The executor builds parameterised SQL **from catalog templates only** (no string composition from plan values; all literals bound). Each metric has one reviewed SQL template and one per-line engine reference. The executor persists `metric_result` rows exactly as today, so the dashboard and CEO read the same rows.

### 6.4 Caching

Key per D2. A write that changes canonical data (ingest, manual adjustment, status override, expense) increments a per-tenant `data_version`; no explicit purge is needed — old keys simply never match, and expire by TTL. Cache holds evidence packets only. Cross-tenant key collision is impossible (tenant in key *and* prefix).

### 6.5 Streaming stages

The executor emits stage events through the existing CEO event bus: `PLANNING`, `VALIDATING`, `QUERYING` (with a label such as "grouping by marketplace"), `FINALIZING`. Events carry no figures (existing whitelist). A cache hit emits `CACHED` and skips the middle stages.

---

## 7. AI requirements

- The LLM receives: the seller question, the **catalog summary** (ids and descriptions only), the period options CEO resolved, and the template list. It returns JSON matching §5.2. It receives no rows, no figures, no tenant identifiers.
- The LLM may not: define a metric, a join, a filter operator, or an aggregation; produce a number; widen a period.
- Narration of the evidence packet reuses `narrate_figures` (one call, pre-formatted `FigureToken`s). Required narration evals (CLAUDE.md) are **deferred** — §12.
- A model refusal or malformed JSON is a planner failure: honest message, no fallback guess.

## 8. Authorization and security

- Requires `agent.ceo` + `agent.cfo` and CFO entitlement (same chain as `cfo.strategic_briefing`). Read-class: no `financials.adjust`.
- The executor reads only through the RLS role; `tenant_id` comes from `AuthContext`, never the plan.
- Plans, validator violations and packets are audit-logged to `agent_run` (closing the direct-path audit gap for this surface).
- A plan referencing another tenant's SKU or ids yields an empty scope, never data (existing RLS behaviour; tested).

## 9. Oracle consistency (exact Brain 1 comparison)

For each metric with `engine_ref`, a test builds a deterministic golden dataset (labelled synthetic), computes the metric via the per-line engine and via the set-based template, and asserts **equality of `value_paise` and of every exclusion count**. Mismatch is a release blocker. The same suite runs a property-based variant (hypothesis) over random line sets including refunds, RTO, cancellations, one-to-many fees, and missing COGS.

## 10. Edge cases

E1 a question mapping to no template → refuse with the nearest supported question · E2 ambiguous period → CEO asks, planner never defaults to "last month" silently · E3 SKU not found → empty scope disclosed · E4 all lines blocked (no COGS) → `UNAVAILABLE` + data request · E5 data changes mid-query → `data_version` read once at plan time and re-checked after execution; changed → rerun once · E6 cache hit with stale catalog_version → miss · E7 Amazon requested → findings withheld "pending match-key verification" (cfo-agent AC5) · E8 comparing a marketplace with partial coverage → `PARTIAL_PERIOD` on that figure · E9 plan asks for a metric whose engine formula is `Unavailable` → propagated, never defaulted · E10 very large group-by (≫ cap) → reject with a narrower-scope suggestion.

## 11. Production-validation blockers

| # | Item |
|---|---|
| PV1 | Real multi-marketplace data has not exercised V-JOIN-5 (Amazon/Flipkart join keys unvalidated — cfo-agent V1/V6) |
| PV2 | Coverage thresholds (V-CMP-1) and `LOW_EXPLAINABILITY` share are provisional configuration needing real-seller calibration |
| PV3 | Latency targets (planner <5 s, cached KPIs <1 s) are **targets**; a documented benchmark on representative data and a recorded environment is required before any claim |
| PV4 | CA review of OPERATING_PROFIT and tax-adjacent metrics before seller exposure |

## 12. Testing and the LLM-eval deferral

**Deferred, explicitly:** real-model (Ollama) planning tests, paid model calls, and the Brain-3 narration evals CLAUDE.md requires for new narration surfaces. This is a deliberate decision of this development cycle (owner instruction 2026-10-21), recorded here and in `cfo-agent.md` §7.5. Narration evals remain **required before any seller sees this surface**.

In-cycle tests use a `MockPlannerProvider` returning fixed JSON, including adversarial JSON (unknown ids, widened scope, injected `tenant_id`, fan-out shapes, double-owner costs).

## 13. Acceptance criteria

| # | Criterion |
|---|---|
| AC-P1 | No code path executes a model-authored SQL string, formula or operation outside the catalog |
| AC-P2 | Every V-rule has at least one failing-plan test and one passing-plan test |
| AC-P3 | Fast path equals per-line engine to the paisa on the golden and property-based datasets |
| AC-P4 | A deliberately fanned-out join is rejected by V-JOIN-3 before execution |
| AC-P5 | A legitimate one-to-many (order with several fee rows) executes with aggregate-then-join and ties out to the source control total |
| AC-P6 | Σ marketplace = consolidated for every additive metric |
| AC-P7 | A profit bridge's drivers + `OTHER` equal the delta exactly |
| AC-P8 | Cache: identical plan hits; any ingest/adjustment misses; no cross-tenant hit |
| AC-P9 | Cross-tenant plan returns no foreign data |
| AC-P10 | Evidence packets contain no raw rows and every figure has a ref |
| AC-P11 | Missing inputs produce `UNAVAILABLE` + one data request, never a default |
| AC-P12 | Stage events stream and carry no figures |

## 14. Test scenarios

TP1 Ravi's question with mocked plan → bridge ties to delta · TP2 injected `tenant_id` in plan → V-SCH-3 reject · TP3 unknown metric id → V-SCH-1 · TP4 SKU×marketplace join on non-unique key → V-JOIN-2 · TP5 settlement joined to order lines twice → V-JOIN-3/5 · TP6 ad spend in expense CSV and settlement → V-DUP-2 · TP7 TCS inside a P&L plan → V-ACC-4 · TP8 period comparison unequal length → V-PER-2 label · TP9 partial month → PARTIAL_PERIOD · TP10 zero denominator → UNAVAILABLE · TP11 cache invalidation after late upload · TP12 data changes during execution → rerun · TP13 resource cap exceeded → V-RES-1 · TP14 oracle sample mismatch (mutated fast path) → V-DET-3 fail · TP15 malformed planner JSON → honest failure.

## 15. Explicit open questions

| # | Question |
|---|---|
| OQ1 | Coverage thresholds per metric (V-CMP-1) — seller-calibrated or fixed? |
| OQ2 | Should the planner expose a seller-visible "show the plan" view? (Recommend yes, read-only, for TRUST.) |
| OQ3 | Redis TTL for evidence packets (recommend 24 h; correctness does not depend on it) |
| OQ4 | Cross-worker event delivery for stage streaming (Redis item already open in CEO spec) |
| OQ5 | Whether `PROFIT_BRIDGE` drivers for ad spend can be split by marketplace before the ad adapter (cfo-data-intelligence §9) lands |


---

## 16. Implementation status — Phase 2b / 2c (2026-10-21)

Stated plainly, including what is **not** built. Nothing below weakens a requirement above; where the build is narrower than the spec, the narrower scope is what the code enforces and says.

### 16.1 Built and verified

| Area | Where | Verified by |
|---|---|---|
| Closed catalog, strict plan parser, validator (V-SCH … V-DET), cache key | `cfo/planner/{catalog,plan,validator,cache}.py` | `test_planner_validator.py` |
| **Set-based SQL path** for `GROSS_SALES` and `SETTLEMENT_RECEIPTS` (by marketplace / SKU / day-week-month; marketplace and SKU filters) | `cfo/planner/sql_executor.py` | **Oracle suite** `tests/integration/test_planner_sql_oracle.py`: the SQL result equals a per-line reference built through the real `calc_engine` formulas, for 6 seeded datasets × 4 scopes × 5–8 groupings per metric. The reference resolves the document date through the engine's own `resolve_document_date`, independently of the SQL expression. Three deliberate mutations of the SQL (week bucket, the null-quantity filter, the date precedence) were each caught. |
| Statement shape | `build_sql` | SQL is assembled from fixed fragments chosen by dictionary lookup; every plan *value* is a bound parameter; hostile values cannot reach the statement text (tested); `statement_timeout` is set inside the tenant transaction and enforced by the database (tested) |
| Executor (engine path, bridge, ranking, additivity V-ACC-2, oracle spot-check V-DET-3, V-DET-2, data-changed rerun E5) | `cfo/planner/executor.py` | `test_planner_pipeline.py` (fake backend) |
| Evidence packet (no raw rows; deterministic `content_json`) | `cfo/planner/evidence.py` | same |
| Evidence cache (in-memory, Redis-protocol client; tenant prefix re-checked on read; outage = miss) | `cfo/planner/cache_store.py` | same |
| Pipeline (plan → validate → cache → execute), one bounded retry, honest refusals, stage events | `cfo/planner/pipeline.py` | same |
| Postgres + Brain 1 backend (measured coverage, engine composition shared with the P&L routes, ref minting) | `backend/services/cfo_planner_backend.py`, `calc_engine.api.compute_metric.mint_set_based_result` | `test_cfo_query_planner.py` (real DB): the planner's NRR and Contribution Profit equal `compute_period_pnl_for_tenant`'s to the paisa; the bridge reconciles; the cache invalidates on a data-version bump; tenants are isolated |
| HTTP surface `POST /cfo/query` (a question + CEO-resolved periods; extra fields refused) and CEO registry action `cfo.query` | `backend/api/v1/cfo.py`, `ceo/registry.py` | `test_cfo_query_route.py`, `test_cfo_query_registration.py`; the existing registry, effects and request-contract guards were updated, not loosened |

Acceptance criteria: **AC-P1** (nothing model-authored is executed: the model returns JSON that is parsed against the catalog; SQL is fragment-built) · **AC-P2** (each V-rule has pass and fail tests: `test_planner_validator.py`) · **AC-P3** (holds for the two SQL metrics, by the oracle suite; see 16.2 for the others) · **AC-P4** (a fan-out join is refused before execution) · **AC-P5** (*not exercised end to end*: no executed plan uses a join — see 16.2) · **AC-P6** (marketplaces add up to the consolidated figure; a numeric mismatch fails the plan) · **AC-P7** (bridge drivers + OTHER = delta; real-data test) · **AC-P8** (hit / miss on a version bump / no cross-tenant hit) · **AC-P9** (a SKU of another tenant gives an empty scope; tested) · **AC-P10** (no raw rows, every figure has a ref) · **AC-P11** (missing input → `UNAVAILABLE` + one de-duplicated data request) · **AC-P12** (stage events carry no figures; built 2026-10-23: the CEO chat shows them live as `CFO_PLANNING`, `CFO_VALIDATING`, `CFO_CACHED`, `CFO_QUERYING`, `CFO_FINALIZING` through `services/ceo_progress.py`).

### 16.2 Narrower than the spec — open, not hidden

1. **The set-based fast path covers `GROSS_SALES` and `SETTLEMENT_RECEIPTS` only.** `NET_REALIZED_REVENUE`, `CONTRIBUTION_PROFIT`, its margin, `MARKETPLACE_FEES`, `FEE_RATIO_PCT` and `RETURN_RATE_PCT` run through Brain 1's own per-line composition (the same code the dashboard uses), so they are exact by construction but are not a "fast path". A set-based version needs the status overlays (`manual_adjustment` newest-ACTIVE precedence), bearer resolution and COGS history re-expressed in SQL and then proven by the oracle suite; that is a separate, larger piece and is **not started**. Latency of the engine path on a realistic dataset has **not** been measured (PV3 stands).
2. **Join steps are not executed.** A plan containing a `join` step is validated, and the statistics adapter supplies no join facts, so such a plan is refused (fail closed). AC-P5 is therefore verified at the validator level only.
3. **Metrics in the catalog that are not yet computable through the planner** return an `UNAVAILABLE` figure that says so, plus one data request: `OPERATING_PROFIT`, `EXPENSE_BY_CATEGORY` (no expense store until Phase 3), `ROAS/ACOS/TACOS` (no ad adapter), `RETURN_RTO_LOSSES` on its own, `SETTLEMENT_LAG_DAYS`, `LEAK_AGGREGATE`. The Phase 2a formulas for them exist and are tested; their data feeds do not.
4. **Engine metrics group only by marketplace** (or not at all). Account-level cost pools (advertising, other) cannot be attributed to one marketplace or SKU without an allocation, so Contribution Profit for a narrowed scope is `UNAVAILABLE` when such pools exist for the period, rather than a wrong number.
5. **Minimum coverage is applied per marketplace (owner decision 2026-10-21; V-CMP-1 amended).** The 95/100 threshold is unchanged and still provisional config (PV2), but each marketplace (Amazon, Flipkart, Meesho) is judged on its own lines: a marketplace qualifies for a metric when *every* required input meets the threshold for *that marketplace* (equality passes). A qualifying marketplace keeps its result even when another does not; a non-qualifying one is shown as `UNAVAILABLE` with its coverage and reason (and one data request); a total built from fewer than all marketplaces in scope carries the label `PARTIAL_MARKETPLACE_COVERAGE` (and status `PARTIAL` where it would otherwise read `VERIFIED`); the metric is unavailable as a whole only when no marketplace in scope qualifies. A marketplace with no lines in the period is absent, not a zero-coverage failure; a plan filtered to one marketplace is judged on that marketplace alone; an unmeasured input or a missing threshold fails closed. The denominator is every sales line the marketplace has in the period, including lines the engine cannot assemble, so blocked lines lower coverage instead of disappearing from it. The evidence packet's `coverage` list carries, per metric, period and marketplace: included or not, the deciding input, the exact share and its percentage (truncated to one decimal, never rounded up: 94.99% never reads as 95.0%), the threshold, the reason, and for an excluded marketplace the **gross sales of its lines** (`excluded_basis = GROSS_SALES_OF_EXCLUDED_MARKETPLACE`, with a cited `excluded_ref`) so the seller sees what a partial total leaves out. That amount measures volume left out, never the missing metric's own value. Exclusions *within* a qualifying marketplace stay on the figure as counted reasons (the engine does not report their amounts). Limits: coverage is measured from the same assembly the engine uses, so a metric whose inputs the adapter cannot measure (expense, ad, reconciliation inputs) stays unavailable for every marketplace rather than being assumed covered.
6. **The component-code taxonomy is configuration** (`CFO_PLANNER_*_CODES`), defaulted from data-foundation's registry; the *non-refunded fee* set defaults to empty. This is a provisional business classification that needs an owner/CA decision.
7. **CEO chat routing — built (CP-D, 2026-10-22).** `cfo.query` is now a chat action: the closed slot vocabulary gained `question` (the seller's own words, whitespace-normalised by code; fewer than 3 or more than 300 characters is asked about, never truncated) and the period is resolved by code, never typed by the model. A question with no period asks for the period and runs nothing. The result reaches the existing evidence table: figures only through their `engineResultRef` (resolved for the caller's tenant; another tenant's ref is dropped and named), formatted from the stored value (ROAS as a multiple, ACOS/TACOS as percentages, exactly); an unavailable figure, a refusal (closed reason vocabulary — the planner's free text is never copied), a marketplace left out of a total, and a provisional or estimated figure each become a sentence written in code with no digit. Settlement lag and cash-shortfall status are not rendered in chat (their unit is not shown by the chat formatter) and are pointed at the dashboard. Tests: `test_ceo_campaign_routing_e2e.py` (3 added), `test_ceo_cfo_query_evidence.py` (5). **Still not done:** a *measured* LLM evaluation of the classifier's choice between `cfo.query` and the older fixed actions, and of the composed narration (deferred by decision, §12 — no real model was called this cycle); the gate and the evidence-table tests above are deterministic.
8. **Redis**: the cache speaks the redis-py interface, but `redis` is not declared as a backend dependency and no live-Redis test has been run. With `REDIS_URL` unset (or the library absent) the cache is process-local, which is correct (keys carry the data version) but only effective within one worker.
9. **Deferred checks**: V-ACC-1/4/5/6 are not asserted by the executor beyond what the engine itself guarantees; `PARTIAL_PERIOD` uses each marketplace's latest document date; the planner prompt has no automated quality evaluation (mocked-model tests only).
