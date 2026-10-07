# Metrion — Anomaly Detection Specification (Brain 2)

**Status:** Draft for review
**Prerequisites:** `deterministic-engine.md` (Brain 1 — the only source of the numeric series Brain 2 consumes; the confidence vocabulary and `combine_confidence`; the `MetricResult`/`engine_result_ref` provenance contract at §9.1; the "no float, no silent zero" determinism contract at §4) · `data-foundation.md` (§5.8/§5.9 — the two-path `reconcile()` model and the `reconciliation_run`/`reconciliation_match`/`reconciliation_exception` schema, relevant to the settlement-lag method) · `cfo-agent.md` (§6.5, C13, §7.1 — the only current consumer of this spec's output)

**This is Brain 2.** It is a small, pure, statistical layer sitting between Brain 1 (deterministic money arithmetic) and Brain 3 (LLM narration). Brain 2 contains **no LLM** and **no money arithmetic of its own** — it never sums, discounts, allocates or otherwise derives a financial figure. It takes numeric series that Brain 1 has already computed and asks a narrower question: *is the latest point in this series statistically unusual, given the rest of the series?* The answer is a **flag that decorates a figure**, never a figure in its own right.

This spec unblocks `packages/cfo/tests/unit/test_deferred_blockers.py::test_brain_2_anomaly_detection`, currently skipped with the reason "T22 — Brain-2 anomaly-detection has no owning spec at all yet (Q10, Deliverable B)." Implementing against this spec is a later checkpoint (E2); wiring it into CFO narration is a further checkpoint (E3). **This document contains no code and modifies no file under `packages/` or `backend/`.**

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| B1 | **Statistical methods only, V1.** Three methods: z-score, percentile threshold, period-over-period delta anomaly. No trained or machine-learned model of any kind. | C13 (`cfo-agent.md`), OP6 (readiness) |
| B2 | **Runs only where the seller has actually uploaded data for that series.** A period with no engine-computed value for the metric in question is excluded from the series — never treated as zero, never interpolated, never imputed. | OP6, C13, CLAUDE.md's "missing input is `UNAVAILABLE`, never zero" |
| B3 | **Forecasting is out of scope.** Nothing in this spec projects a future value. Forecasting is gated at 6 complete months (readiness §1, Intelligence and data — Forecasting) and belongs to a separate, unwritten forecasting surface. | `cfo-agent.md` §6.5 |
| B4 | **Applies over four named metric series at V1:** margin (`MARGIN_PCT`), fee ratio (`FEE_RATIO_PCT`), settlement lag (`SETTLEMENT_LAG_DAYS`), return rate (`RETURN_RATE_PCT`). No other series is in scope for V1; a fifth series requires a spec amendment, not an ad hoc addition. | `cfo-agent.md` §6.5 |
| B5 | **Below the minimum series length for a method, that method reports insufficient history and fires nothing.** It never fires on noise from a too-short series, and never silently falls back to a different method or a relaxed threshold. | C13, `cfo-agent.md` E16/T22 |
| B6 | **An anomaly flag is not a `MetricResult` and never carries an `engine_result_ref` of its own.** It is a distinct, smaller contract (`AnomalyFlag`, §5.2) that *cites* the `engine_result_ref` of the figure it decorates. `estimate_ref` is equally wrong for it — a flag is neither a canonical figure nor a third-party estimate. | `cfo-agent.md` §5.1.2's own wording: "Anomaly flags CFO can attach to a figure" |
| B7 | **Minimum series length is a real, method-specific, statistically-grounded floor — not an arbitrary number.** See §6.2 for the value and the reasoning behind each of the three methods. Tenant configuration may raise a floor; it may never lower it below the value fixed here, mirroring `compute_price_band`'s "engine floor... configuration may raise but never lower" precedent (`deterministic-engine.md` §5.15.1 rule 1). | Resolves Q7 (`cfo-agent.md`) |
| B8 | **Brain 2 is a pure statistics library. It never queries a canonical or reconciliation table directly.** It receives an already-assembled `Sequence[SeriesPoint]` from its caller (CFO, via Brain 1) and returns a flag or an insufficient-history outcome. It has no database access of its own in V1. | Keeps the settlement-lag method's dependence on `reconciliation_exception`/`reconciliation_match` (`data-foundation.md` §5.8/§5.9) from becoming a redesign of that already-built system — see §6.6 |
| B9 | **All arithmetic is `Fraction` or `Decimal`, never `float`.** Money-denominated series points remain `Paise` until the statistical step; percentage/day-count series points are `Fraction`. A single `Decimal`-precision square root is the only place an irrational intermediate appears (z-score's standard deviation), and it is documented, bounded-precision, and never a `float`. | CLAUDE.md — "no floats in any calculation path" |
| B10 | **Anomaly flags live in the `Confidence` vocabulary for data quality and a separate `AnomalySeverity` vocabulary for statistical magnitude.** These are two different axes and are never merged into one field. See §6.4. | Resolves the "confidence vs. severity" ambiguity named in the task brief |
| B11 | **Anomaly flags are computed on demand and not persisted as a standing table in V1.** Brain 2 runs when CFO asks it to, inside one conversational turn; there is no background anomaly-scan job. See §5.2 for the full reasoning and its status as a reviewable design decision (D2). | `cfo-agent.md` §6.1 rule 4 ("Brain 2 supplies anomaly flags **where the question is about change or irregularity**") — reactive, not a scheduled scan | **Amendment note 2026-10-07 (CEO CP1-D4):** the *conversational/on-demand* rule is unchanged. The CEO's V1-later proactive detection is **event-driven, post-ingest** (reactive to a data event, not a standing scan) and, when it fires, persists the flag's evidence by reference on a `situation` row (`ceo-agent-orchestration.md` §5, §6.17). A scheduled Redis worker is V1.1. Neither is built; B11's no-persistence statement still describes the code.

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Module location in `packages/calc-engine` | A new top-level subpackage, `calc_engine.anomaly/`, sibling to `formulas/`, `gst/`, `api/` — **not** inside `calc_engine.formulas`, which is money arithmetic. | Brain 2 is a statistics layer, not Brain 1's money arithmetic, even though it lives in the same package and language for engineering convenience. Putting it inside `formulas/` would misrepresent it as a formula this engine's determinism contract (§4) governs identically to revenue/profit — it doesn't; it is explicitly weaker (§6.7). A separate top-level Python package was considered and rejected: the statistical functions need the same `Paise`/`Confidence`/`Fraction` primitives already defined in `calc_engine.types`, and duplicating or cross-importing those from a sibling package adds real friction for negligible isolation benefit. |
| D2 | Persist `AnomalyFlag` rows, or compute on demand only? | **On demand only, in V1** (B11). No `anomaly_flag` table ships in this checkpoint. | §6.5's own language ("flags CFO can **attach**") reads as decoration applied at narration time, not a standing inventory CFO maintains. Every input to a flag (the series points) is cheap to re-fetch — they are themselves already-persisted `MetricResult` rows or cheaply-recomputed aggregates — so recomputing a flag costs little. Persisting flags would additionally require a stale-flag invalidation story (a superseded `manual_adjustment` or a re-ingested file changes the underlying series retroactively) that this checkpoint has no mandate to design. If a future need emerges — e.g. "show me how this anomaly evolved over the last quarter" — that is new product scope requiring its own review, not something this V1 spec should pre-build. Reconsider once CFO's real usage shows sellers re-asking about the same flag across sessions (see Q1). |
| D3 | Does the `AnomalyFlag.id` need to be reproducible/deterministic, or is a fresh `uuid4()` per computation acceptable? | A fresh `uuid4()` minted at compute time, exactly as `compute_metric.py` mints `MetricResult.id` before persistence (`calc_engine/api/compute_metric.py`). | Because flags are not persisted (D2), there is no lookup contract an id needs to satisfy across calls — the id exists only so a single response can cite "this specific flag" unambiguously within one turn (e.g. in `assumptions[]`-style disclosure). Two identical inputs will produce two different ids on two separate calls; this is acceptable because nothing outside the single response depends on stable identity. If D2 is revisited toward persistence, this decision is revisited with it. |
| D4 | Should the percentile-threshold method compute its percentile bounds from the full series (including the point being tested) or from a leave-one-out baseline excluding it? | **Full series**, matching `compute_price_band`'s existing precedent (`deterministic-engine.md` §5.15.1 rule 6: "computed from the full supplied set, never from a pre-filtered one"). | Consistency with an already-reviewed and shipped engine convention outweighs the marginal statistical purity of leave-one-out, and keeps the three methods' input contracts uniform (all consume the same `Sequence[SeriesPoint]` with no special-casing of the last element). |
| D5 | Should Brain 2 ever surface a flag unprompted (proactively, without a seller question), the way `cfo-agent.md`'s free-tier preview reveals one finding? | **No — reactive only in V1**, matching B11. | Unprompted surfacing raises the same entitlement question `cfo-agent.md` Q8 already leaves open for CI-sourced competitor ranges (does showing something the seller didn't ask for cross an entitlement boundary?). Resolving that generally is out of this spec's scope; V1 keeps Brain 2 strictly request-driven so the question does not need answering yet. Left open at Q6 below rather than guessed at. |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | CFO (the sole V1 consumer) assembles each `SeriesPoint`'s `value`, `confidence` and `engine_result_ref` from already-computed `MetricResult` rows or from a to-be-built settlement-lag aggregate (§6.6) — Brain 2 itself never resolves a period's figure. | Low for margin/fee-ratio/return-rate (existing capabilities can be called once per period to build a series); **high** for settlement lag, which has no aggregate function today (§10) |
| A2 | Sellers upload with enough regularity that "the last N periods with available data" is a meaningful, roughly-contiguous window, not a scattering of isolated months a year apart. | Medium — a badly gapped series could satisfy the minimum-length floor on point count while being statistically meaningless in wall-clock terms; not solved here (see Q3) |
| A3 | The four named metric series (margin, fee ratio, settlement lag, return rate) are computed at a **consistent grain and cadence** (e.g. always monthly, always per-marketplace) before being handed to Brain 2 — Brain 2 does not itself resolve or validate grain consistency across the supplied points. | Medium — mixing a monthly point with a weekly point in the same series would silently corrupt the statistics; the caller (CFO) is assumed responsible for grain discipline |
| A4 | V1 usage volume is low enough that recomputing a flag from scratch on every question (D2) is cheap. | Low — series lengths are small (tens of points at most in V1's realistic timeframe) |

---

## 4. Goals and non-goals

**Goals** — define exactly which three statistical methods exist, their formulas, their minimum-series-length floors and the reasoning behind each floor; define the `AnomalyFlag` provenance contract and where it lives (or doesn't); define the exact function signatures and module boundary a future implementer builds against; define the severity/confidence vocabulary for a flag; state precisely how the settlement-lag method relates to the already-built `reconcile()` system without redesigning it; enumerate edge cases (empty series, zero-variance series, a single dominating outlier) and their required behaviour.

**Non-goals (V1)** — no trained or machine-learned model of any kind (C13, restated not relitigated) · no forecasting (B3, restated not relitigated) · no code — E2 (a later checkpoint) implements the engine functions against this spec, E3 wires them into CFO narration · no new permission, entitlement gate or billing meter (owned elsewhere) · no persistence of `AnomalyFlag` rows in V1 (D2) · no robust-statistics (e.g. MAD-based) alternative to the naive mean/stdev z-score — the naive form is what ships in V1, with the tradeoff named explicitly (§7 E5) rather than silently absorbed · no cross-tenant, cross-marketplace or cross-SKU comparison — every series is scoped to one `target_ref` at a time, matching `MetricResult.target_ref`'s existing grain.

---

## 5. Data model

### 5.1 `SeriesPoint` — the only input Brain 2 accepts

```
SeriesPoint {
  period:            date,                 -- the period this point represents; grain is the caller's responsibility (A3)
  value:             Paise | Fraction,      -- Paise for money-denominated series; Fraction for percentage/day-count series.
                                             -- NEVER float (B9). The unit is implied by `metric` (§6.1) and fixed per series.
  confidence:        Confidence,            -- VERIFIED | PROVISIONAL | DERIVED | MANUAL, copied from the source MetricResult
  engine_result_ref: UUID,                  -- the MetricResult.id this point was read from (metric_result.id, engine §9.1)
}
```

A period absent from the series is not a `SeriesPoint` with `value = 0` — it is simply not present, per B2. Brain 2 never receives a placeholder for a missing period; the caller filters unavailable periods out before calling Brain 2.

### 5.2 `AnomalyFlag` — the output contract (not a `MetricResult`, not an `estimate_ref`)

```
AnomalyFlag {
  id:                     UUID,             -- minted at compute time (D3); NOT a persisted-row identity in V1 (D2)
  tenant_id:               UUID,
  metric:                  str,             -- MARGIN_PCT | FEE_RATIO_PCT | SETTLEMENT_LAG_DAYS | RETURN_RATE_PCT (§6.1)
  target_ref:               TargetRef,      -- same grain concept as metric_result.target_ref (engine §9); SKU | MARKETPLACE | ACCOUNT
  period:                   date,           -- the period of the flagged point (the LATEST point in the series, always)
  method:                   str,            -- Z_SCORE | PERCENTILE_THRESHOLD | PERIOD_OVER_PERIOD_DELTA
  decorates_engine_result_ref: UUID,        -- the MetricResult.id of the flagged point itself
  source_engine_result_refs:  tuple[UUID, ...],  -- every MetricResult.id in the series (baseline + flagged point) that fed this flag
  score:                    Fraction,        -- the raw statistic: the z-score, the percentile rank, or the delta-vs-baseline-stdev ratio
  threshold_used:            AnomalyThreshold, -- the exact config values applied — see §6.5's config table; never a constant
  fired:                     bool,           -- true if the statistic crossed the configured threshold, false otherwise. A "not fired"
                                              -- result is still returned (not omitted) so CFO can state a series was checked and is normal
  severity:                  str,            -- HIGH | MEDIUM | LOW | NOT_ANOMALOUS — §6.4's vocabulary, distinct from `confidence`
  data_confidence:            str,           -- VERIFIED | PROVISIONAL | DERIVED | MANUAL — §6.4's vocabulary, distinct from `severity`
  series_length:              int,           -- number of SeriesPoints actually used
  min_series_length_required: int,           -- the floor that applied (tenant config or engine floor, whichever is higher)
  config_version:             int,           -- anomaly_detection_config.version actually used
  formula_version:            str,           -- e.g. "ANOMALY_Z_SCORE.v1" — versioned exactly like engine formulas (F1–F6 precedent)
  as_of_date:                 date,
  computed_at:                 datetime,
}
```

Two distinguished non-flag outcomes, returned instead of `AnomalyFlag` where they apply — never silently coerced into a `fired=false` flag, because they mean something structurally different:

```
AnomalyInsufficientHistory {
  metric: str, method: str, target_ref: TargetRef,
  series_length: int, min_series_length_required: int,
  reason: "INSUFFICIENT_HISTORY",
}

AnomalyZeroVariance {                       -- Z_SCORE and PERIOD_OVER_PERIOD_DELTA only (§7 E4)
  metric: str, method: str, target_ref: TargetRef,
  series_length: int,
  reason: "ZERO_VARIANCE_BASELINE",         -- the baseline has no spread; a z-score is mathematically undefined, not "no anomaly found"
}
```

**Why not a `MetricResult`.** A flag is not a figure about the seller's business the way revenue or margin is — it is a statement about a figure's *relationship to its own history*. Forcing it into `metric_result` would let it silently claim an `engine_result_ref` a consumer might mistake for the flagged figure's own provenance, corrupting B6. **Why not an `estimate_ref`-family table either** (`competitor_estimate`/`product_feasibility_estimate`, engine §9.1). Those exist for observations about a *third party* (a competitor, a prospective product) built on non-canonical inputs. A flag is about the seller's own, fully-canonical figures — it is neither of those things, and reusing either table's shape would misrepresent what kind of uncertainty a flag carries (statistical unusualness, not observational estimation).

### 5.3 `anomaly_detection_config` — configuration, never constants (mirrors F4)

```sql
anomaly_detection_config (
  id uuid pk, tenant_id uuid,               -- null = platform default, same resolution order as severity_config / reconciliation_tolerance_config
  metric text not null,                     -- MARGIN_PCT | FEE_RATIO_PCT | SETTLEMENT_LAG_DAYS | RETURN_RATE_PCT
  method text not null,                     -- Z_SCORE | PERCENTILE_THRESHOLD | PERIOD_OVER_PERIOD_DELTA
  min_series_length int not null,           -- must be >= the engine floor for this method (§6.2); may raise, never lower
  z_score_threshold numeric(6,3),           -- e.g. 2.500, applies to Z_SCORE only
  percentile_low numeric(5,2),              -- e.g. 10.00, applies to PERCENTILE_THRESHOLD only
  percentile_high numeric(5,2),             -- e.g. 90.00, applies to PERCENTILE_THRESHOLD only
  delta_severity_bands jsonb,               -- {"high": "3.0", "medium": "2.0", "low": "1.0"} — multiples of baseline-delta stdev;
                                             -- applies to PERIOD_OVER_PERIOD_DELTA only; values are strings to preserve Fraction/Decimal precision
  effective_from date not null,
  version int not null,
  unique (tenant_id, metric, method, effective_from)
)
```

Resolution order mirrors `discount_bearer_config`/`reconciliation_tolerance_config` exactly (`deterministic-engine.md` §5.3, §5.12.1): a tenant-specific row overrides the platform default for the same `(metric, method)`; where neither exists, the method cannot run and the caller must be told the gap explicitly (never a silently-assumed threshold). No numeric value in this table is seeded by this spec — same posture as `fee_reference` and `entitlement.md`'s config tables (N2 there).

**Platform-owned or tenant-owned?** `tenant_id` nullable exactly as above — a tenant may never see or set another tenant's row (RLS, §8), but the platform default row (`tenant_id IS NULL`) is visible to every tenant per the same RLS pattern `reconciliation_tolerance_config` already uses.

---

## 6. Core rules

### 6.1 The four named metric series

| `metric` | Unit | `value` type | Built from |
|---|---|---|---|
| `MARGIN_PCT` | percentage | `Fraction` | `ContributionMargin%` (engine §5.8), one point per period, per `target_ref` |
| `FEE_RATIO_PCT` | percentage | `Fraction` | `MarketplaceFees / NetRealizedRevenue` per period — **a ratio CFO/Brain 1 computes and supplies**; this spec does not itself define a new engine metric code, since the two inputs already exist (engine §5.5, §5.6) |
| `SETTLEMENT_LAG_DAYS` | days | `Fraction` | An aggregate (mean or median days-to-settle) per period, sourced from `reconciliation_match`/`reconciliation_exception` — **not yet a built aggregate function**, see §6.6 and §10 |
| `RETURN_RATE_PCT` | percentage | `Fraction` | `returned_qty_all_outcomes / quantity` per period, aggregated — an already-computable ratio from canonical data (engine §5.6's `billable_quantity` inputs) |

A fifth series is out of scope for V1 (B4) — adding one is a spec amendment, not an implementation-time decision.

### 6.2 Minimum series length — the resolution of Q7

Each method's floor is grounded in ordinary statistical practice for the specific quantity that method estimates, not chosen arbitrarily:

| Method | Engine floor (`min_series_length`) | Reasoning |
|---|---|---|
| `Z_SCORE` | **8 points** | The relative standard error of a sample standard deviation is approximately `1 / sqrt(2(n-1))`. At `n = 8`, that is `1/sqrt(14) ≈ 26.7%` — the smallest `n` that keeps the stdev estimate's own uncertainty under roughly 30%, a conventional lightweight-monitoring floor (below full statistical-process-control practice, which typically wants 20–25+ for a stable control chart, but Metrion's realistic V1 upload cadence — monthly-ish, over at most ~1–2 years of data — makes 20–25 impractical to reach for most sellers in year one). 8 is the practical statistical floor, not the ideal; sellers with longer history get a materially more reliable result automatically, since the formula strengthens with `n`. |
| `PERCENTILE_THRESHOLD` | **10 points** | For the default 10th/90th percentile bands (`percentile_low`/`percentile_high`) to correspond to genuinely interior points under linear interpolation (the same method `compute_price_band` already uses, `deterministic-engine.md` §5.15.1 rule 2) rather than degenerating to the series minimum/maximum, `n` should be at least `1 / min(p, 1-p)`. For `p = 10%`, that is `n >= 10`. A tenant configuring tighter bands (e.g. 5th/95th) without raising `min_series_length` accordingly will see the percentile collapse toward the extremes — that is a config-authoring responsibility this spec names but does not enforce automatically (see Q4). |
| `PERIOD_OVER_PERIOD_DELTA` | **5 points** (yielding 4 consecutive deltas: 3 baseline + 1 latest) | This method does not judge a raw delta's size in isolation (that is already `compute_metric_delta`, Brain 1, `deterministic-engine.md` §5.1.1) — it judges whether the **latest** delta is unusual relative to the **baseline** distribution of prior deltas. A baseline variance needs at least 2 degrees of freedom to be non-degenerate (`n_baseline - 1 >= 2`), which requires 3 baseline deltas; 3 baseline deltas plus the 1 delta being judged requires 4 total deltas, which requires 5 raw series points. This is the same "avoid estimating a spread from too few points" principle behind the `Z_SCORE` floor, applied one level down (to the sequence of deltas rather than the raw series). |

These are the **engine floor** a `anomaly_detection_config.min_series_length` value may raise but never lower (mirrors `compute_price_band`'s rule 1 precedent exactly). A method that has not reached its applicable floor for a given `(target_ref, metric)` returns `AnomalyInsufficientHistory`, never a flag (B5).

### 6.3 Method formulas

**`Z_SCORE`.** Given series points `x_1 .. x_n` in period order (n >= floor):
- Baseline = `x_1 .. x_{n-1}`. Point under test = `x_n` (always the latest).
- `mean = sum(baseline) / (n-1)` — exact `Fraction` arithmetic.
- `variance = sum((x_i - mean)^2 for x_i in baseline) / (n-2)` — sample variance, `Fraction` arithmetic (`n-2` because the baseline itself has `n-1` points, so `n-1-1` degrees of freedom).
- If `variance == 0`: return `AnomalyZeroVariance` — see §7 E4. Never divide by zero, never fabricate an infinite or undefined score.
- `stdev = sqrt(variance)` — computed via `Decimal` at a fixed, documented precision (e.g. 28 significant digits), **never** `float`. This is the one place this method touches an irrational intermediate; it is bounded and reproducible for a fixed `(precision, variance)` pair.
- `z = (x_n - mean) / stdev` — `Decimal`/`Fraction` throughout.
- `fired = abs(z) >= z_score_threshold` (from config, §5.3).
- `score = z`.

**`PERCENTILE_THRESHOLD`.** Given series points `x_1 .. x_n` (n >= floor):
- Compute `p_low` and `p_high` percentiles of the **full** series (D4) using the same linear-interpolation-between-closest-ranks method `compute_price_band` already uses (`deterministic-engine.md` §5.15.1 rule 2) — chosen for the identical reason: cross-language, cross-database identical results (NumPy default `percentile`, SQL `PERCENTILE_CONT`).
- Point under test = `x_n` (the latest).
- `fired = x_n <= p_low OR x_n >= p_high`.
- `score` = the point's own percentile rank within the series (`Fraction`), computed by the same interpolation convention run in reverse.

**`PERIOD_OVER_PERIOD_DELTA`.** Given series points `x_1 .. x_n` (n >= floor):
- Deltas `d_i = x_{i+1} - x_i` for `i = 1 .. n-1` (`n-1` deltas total).
- Baseline deltas = `d_1 .. d_{n-2}`. Delta under test = `d_{n-1}` (the most recent).
- `baseline_mean`, `baseline_stdev` computed over the baseline deltas exactly as in `Z_SCORE` above (same zero-variance guard: `variance == 0` on the baseline deltas returns `AnomalyZeroVariance`).
- `score = (d_{n-1} - baseline_mean) / baseline_stdev` (a z-score computed on the delta series, not the raw series).
- `fired` and `severity` derive from `delta_severity_bands` (§5.3): `|score| >= bands.high` → `HIGH`; `>= bands.medium` → `MEDIUM`; `>= bands.low` → `LOW`; else `NOT_ANOMALOUS`.

For `Z_SCORE` and `PERCENTILE_THRESHOLD`, severity bands over the magnitude of `score` are likewise configuration (not hardcoded in this spec) — a future `anomaly_detection_config` extension may carry `z_score_severity_bands` analogous to `delta_severity_bands`; until that column exists, `Z_SCORE` and `PERCENTILE_THRESHOLD` report `severity = HIGH` when fired and `NOT_ANOMALOUS` when not (a binary severity is an honest, if coarse, starting point — see Q5).

### 6.4 Two vocabularies, never merged

| Field | Vocabulary | Meaning | Source |
|---|---|---|---|
| `data_confidence` | `VERIFIED \| PROVISIONAL \| DERIVED \| MANUAL` (engine §9, `Confidence` enum) | How trustworthy the **underlying data** is | `combine_confidence(*[p.confidence for p in series], Confidence.DERIVED)` — the weakest input confidence, floored at `DERIVED` because a statistical computation over already-computed figures is itself never better than `DERIVED`, mirroring the treatment already given to allocated pools (engine §5.10) |
| `severity` | `HIGH \| MEDIUM \| LOW \| NOT_ANOMALOUS` | How far outside the configured threshold the flagged point falls | Computed deterministically from `anomaly_detection_config`'s bands (§6.3) — never inferred, never a Brain-3 judgement |

These answer different questions — "can I trust this number" vs. "how unusual is this number" — and a figure can be simultaneously high-confidence and non-anomalous, or low-confidence and severely anomalous (in which case the severity itself should be read with more caution, which Brain 3 states in narration, never by blending the two fields into one).

### 6.5 Configuration resolution

Exactly the resolution order already established by `discount_bearer_config`/`reconciliation_tolerance_config`/`severity_config` (`deterministic-engine.md` §5.3, §5.12.1, §5.14.1): a tenant-specific `anomaly_detection_config` row for the same `(metric, method)` overrides the platform default; where neither exists, the method cannot run for that `(tenant, metric, method)` and the caller receives an explicit configuration-gap error — never a default threshold invented at call time.

### 6.6 Relationship to `reconcile()` — no redesign

The settlement-lag method's input series is **not** something Brain 2 computes itself (B8). `reconciliation_match`/`reconciliation_exception` (`data-foundation.md` §5.9, already real and Postgres-integration-tested against real Meesho data) carry per-line settlement facts, not a period-level "average days to settle" aggregate. Building `SETTLEMENT_LAG_DAYS`'s per-period series is **Brain-1-side composition work this spec does not do** — it would take the form of a new aggregate (e.g. a `settlement_lag_days` view over `reconciliation_match` grouped by period and `target_ref`), analogous to how `MARGIN_PCT`'s series is built by calling `compute_contribution_profit` once per period rather than by a single new engine function. This spec **names the dependency and its current absence explicitly** (§10, blocking item) rather than inventing an aggregate function signature that does not yet exist anywhere in `packages/calc-engine`. Once that aggregate exists, the settlement-lag `SeriesPoint`s it emits plug into Brain 2 exactly like any other series — no change to Brain 2 itself is required.

### 6.7 Determinism, weaker than §4 by design

A `AnomalyFlag` is reproducible for a **fixed** `(series, config_version, as_of_date)` tuple — same posture as `compute_price_band`/`compute_price_positioning` (`deterministic-engine.md` §5.15/§5.15.1, "not part of `canonical_data_version`"). Re-running detection after a new period's data arrives, or after a `manual_adjustment` supersession changes an earlier period's `MetricResult`, is a **new** computation, not a correction of a prior one — there is no prior stored one to correct (D2).

### 6.8 No agent-specific coupling

Brain 2's functions accept a generic `Sequence[SeriesPoint]` and know nothing about CFO, leak findings, or any other agent concept. CFO is the only V1 caller (A per cfo-agent.md §6.1 rule 4, §7.1), but nothing in this module's signature makes that structural — a future agent could call the same functions with a series built from its own domain, without touching this module. This is stated as an assumption (A of consumption pattern), not a hard architectural guarantee this spec enforces, since only one consumer exists today.

---

## 7. AI requirements

Brain 2 contains **no LLM**, exactly like Brain 1 (`deterministic-engine.md` §1, restated for this document): no calculation here is produced, adjusted, rounded or "sanity-checked" by a model. This section states what Brain 3 (the CFO LLM layer) may and may never do with a `AnomalyFlag` once Brain 2 has produced one — it restates `cfo-agent.md` §7.2/§7.4.9 for this specific artefact rather than loosening it.

1. Brain 3 narrates `severity`, `score`, `fired` and `data_confidence` exactly as returned. It never recomputes, re-derives or "double-checks" a z-score, a percentile rank or a delta-vs-baseline ratio, however simple the arithmetic looks in context (`cfo-agent.md` §7.4.9 rule 1).
2. Brain 3 never invents a threshold, a minimum series length, or a severity band from its own training knowledge — every one of those values traces to `anomaly_detection_config` (§5.3), cited by `config_version`, exactly as a GST rate must trace to OP13's layered source (`cfo-agent.md` §7.4.8).
3. Brain 3 may attribute a **cause** to a flagged movement only where that cause is itself a Brain-1-computed component (e.g. "the fee-ratio anomaly this month lines up with the `FEE_OVERCHARGE` findings your Leak Shield run surfaced for the same period") — never an invented narrative ("seasonal effects," "market conditions") the way `cfo-agent.md` §7.4.4 already forbids for period-over-period deltas generally. `cfo-agent.md` T37 explicitly flags this as a gap this spec's existence does not itself close — attributing a *cause* to an anomaly (as opposed to stating its *magnitude and severity*, which this spec fully defines) is Brain 3 judgement over Brain-1/Brain-2 outputs, not a new Brain 2 capability.
4. `AnomalyInsufficientHistory` and `AnomalyZeroVariance` are narrated as exactly what they are — "not enough history yet" and "this series hasn't moved at all," respectively — never silently omitted, never reworded into "no anomaly found" (which would misrepresent an undefined result as a checked-and-clean one).
5. Every `AnomalyFlag` Brain 3 discusses is rendered alongside the `engine_result_ref` it decorates (`decorates_engine_result_ref`), per the same "trace every figure" discipline `cfo-agent.md` §7.2 closes with. A flag with no traceable underlying figure is a defect, identical in kind to an untraceable financial figure.

---

## 8. Authorization and security

1. Brain 2 has no endpoint of its own in V1 (B8, B11) — it is a library called in-process by CFO's existing, already-permissioned direct execution paths (`cfo-agent.md` §6.8). No new permission key, entitlement gate, rate limit or audit row is introduced by this spec.
2. `anomaly_detection_config` is tenant-scoped exactly like `reconciliation_tolerance_config`/`severity_config`: real per-tenant `FORCE ROW LEVEL SECURITY` where `tenant_id` is non-null, with the platform-default (`tenant_id IS NULL`) row visible to every tenant per the same nullable-platform-default RLS pattern already in production use.
3. Should D2 ever be revisited toward persisting `AnomalyFlag` rows, that table **must** carry `tenant_id` and `FORCE RLS` from its first migration — no tenant-scoped table in this codebase ships without it (CLAUDE.md's hard multi-tenancy rule). This spec does not design that table today because it does not exist today (D2); this rule pre-commits the shape it must have if it ever does.
4. Every `SeriesPoint` Brain 2 receives is already tenant-scoped by construction — it was read from a tenant-scoped `MetricResult` by a caller that has already passed the `auth.md` §7.1 six-step chain. Brain 2 performs no additional tenant check of its own because it has no database access to check against (B8) — this is a deliberate consequence of the pure-function boundary, not a gap.
5. A cross-tenant series is structurally impossible in V1's calling convention: CFO builds one series per `(tenant, target_ref, metric)` request, and nothing in Brain 2's signature accepts a tenant identifier or could be made to mix two tenants' points, since the caller assembles the sequence.

---

## 9. Edge cases

| # | Case | Required behaviour |
|---|---|---|
| E1 | Zero data (empty series) | `AnomalyInsufficientHistory`, `series_length = 0` |
| E2 | Series exactly at the method's minimum length | The method **runs** — the floor is inclusive ("at least N"), not exclusive. A series one point short still returns `AnomalyInsufficientHistory` |
| E3 | Series one point short of the minimum | `AnomalyInsufficientHistory`, `series_length = N-1`, `min_series_length_required = N` |
| E4 | Flat/constant series (zero variance) for `Z_SCORE` or `PERIOD_OVER_PERIOD_DELTA` | `AnomalyZeroVariance` — never a division by zero, never a fabricated infinite or `NaN`-equivalent score. `PERCENTILE_THRESHOLD` is unaffected by zero variance (percentiles of a constant series are just that constant; the latest point trivially cannot exceed either bound, so `fired = false`, no special-cased outcome needed) |
| E5 | A single extreme outlier elsewhere in the baseline skews the naive mean/stdev, potentially masking a real anomaly or manufacturing a false one at the point under test | **V1 tolerates this — no robust-statistics (e.g. median/MAD-based) adjustment ships.** This is a named, deliberate tradeoff, not a silent gap: robust statistics add real complexity (a second, less-standard formula per method, harder to explain to a non-statistician seller in narration) for a failure mode that is self-correcting as more periods accumulate. A future robust-statistics variant is a legitimate enhancement, not committed to here (see Q2) |
| E6 | A period present in the raw upload data but whose `MetricResult` for the metric in question is itself `UNAVAILABLE` (e.g. no COGS, so `ContributionMargin%` is unavailable for that period) | That period is **absent** from the series, never a zero-valued `SeriesPoint` (B2). Series length counts only periods with an available value |
| E7 | Two consecutive periods with identical values feeding `PERIOD_OVER_PERIOD_DELTA` | `d_i = 0` for that pair — a legitimate delta value, not an error. If every baseline delta is `0`, that is E4's zero-variance case for the delta series specifically |
| E8 | `target_ref` scope changes mid-series (e.g. a SKU is renamed or a marketplace-level series is requested where some periods were previously SKU-level) | Out of scope for Brain 2 to detect — grain consistency is the caller's responsibility (A3). Brain 2 does not validate `target_ref` identity across points in the series it receives |
| E9 | `anomaly_detection_config` has no row for the requested `(tenant, metric, method)`, tenant or platform | The method cannot run; the caller receives an explicit configuration-gap result, never a default threshold (§6.5) |
| E10 | A `SeriesPoint`'s `confidence` is `MANUAL` (e.g. a seller-entered COGS feeds the margin figure for that period) | Included in the series normally; `data_confidence` on the resulting flag reflects it via `combine_confidence` — never excluded or treated specially just because it's manual |

---

## 10. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| P1 | **`SETTLEMENT_LAG_DAYS` has no period-level aggregate function anywhere in `packages/calc-engine`.** `reconciliation_match`/`reconciliation_exception` carry per-line facts; nothing groups them into a per-period days-to-settle figure yet (§6.6). | The `SETTLEMENT_LAG_DAYS` series cannot be built until this Brain-1-side aggregate exists. `MARGIN_PCT`, `FEE_RATIO_PCT` and `RETURN_RATE_PCT` are not blocked by this — their per-period figures are already computable by calling existing engine functions once per period |
| P2 | **`FEE_RATIO_PCT` has no dedicated `metric_code`.** It is a ratio of two already-real figures (`MarketplaceFees`, `NetRealizedRevenue`) that CFO composes, not a new engine primitive — but no existing composition function is named anywhere today. A future CFO-side composition (mirroring how `narrate_period_comparison` composes existing `MetricResult`s, `cfo-agent.md` §7.4.4) is required before this series is buildable in practice. | `FEE_RATIO_PCT` series construction |
| P3 | **Severity bands for `Z_SCORE` and `PERCENTILE_THRESHOLD` are binary (fired/not-fired) until a magnitude-graded config column is added** (§6.3's closing note). | Finer-grained severity narration for those two methods; `PERIOD_OVER_PERIOD_DELTA` is unaffected, since `delta_severity_bands` already exists in §5.3's schema |
| P4 | **No real usage data exists yet to validate A2's "roughly contiguous window" assumption** against actual seller upload cadences. | Confidence that the minimum-length floors in §6.2 are practically reachable, not just theoretically grounded |

---

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | Brain 2 contains no LLM and no financial calculation — only statistical computation over already-computed `SeriesPoint` values. |
| AC2 | No method fires below its minimum series length (§6.2); each returns `AnomalyInsufficientHistory` instead, naming `series_length` and `min_series_length_required`. |
| AC3 | `Z_SCORE` and `PERIOD_OVER_PERIOD_DELTA` never divide by zero on a zero-variance baseline; both return `AnomalyZeroVariance` instead. |
| AC4 | All arithmetic uses `Paise`, `Fraction` or bounded-precision `Decimal`. No `float` appears anywhere in the computation path (mirrors engine AC3). |
| AC5 | A missing period's figure is never represented as a zero-valued `SeriesPoint` — it is absent from the series entirely (B2). |
| AC6 | Every `AnomalyFlag` carries `decorates_engine_result_ref` and `source_engine_result_refs`, both populated from real `MetricResult.id` values supplied by the caller — never fabricated. |
| AC7 | `AnomalyFlag` is never written to, and never claims a row in, `metric_result`, `competitor_estimate` or `product_feasibility_estimate` (B6). |
| AC8 | `data_confidence` is computed via `combine_confidence` over the series' input confidences, floored at `DERIVED`, and never exceeds `DERIVED` (§6.4). |
| AC9 | `severity` and `data_confidence` are never blended into a single field or conflated in output (§6.4). |
| AC10 | Every threshold, band and minimum-length value a flag cites traces to a real `anomaly_detection_config` row (`config_version` populated); none is a hardcoded constant in the computation path (F4 precedent). |
| AC11 | `PERCENTILE_THRESHOLD` computes its percentile bounds via linear interpolation between closest ranks, identical to `compute_price_band`'s method (§5.15.1 rule 2), over the full supplied series (D4). |
| AC12 | Brain 2 performs no direct database query against `reconciliation_match`, `reconciliation_exception`, `sales_line`, `settlement_line` or any other canonical/reconciliation table (B8) — it consumes only the `SeriesPoint` sequence its caller supplies. |
| AC13 | A `anomaly_detection_config` gap (no tenant or platform row for a `(metric, method)` pair) produces an explicit configuration-gap outcome, never a silently-assumed threshold. |
| AC14 | `AnomalyFlag.id` is freshly minted per computation (D3); no persistence or lookup-by-id contract is implied or required in V1. |
| AC15 | Brain 3 narrates `fired`, `severity`, `score` and `data_confidence` exactly as returned, performing no recomputation, rounding or adjustment (§7 rule 1). |
| AC16 | Brain 3 never invents a threshold, band or minimum-length value when explaining a flag (§7 rule 2). |
| AC17 | `AnomalyInsufficientHistory` and `AnomalyZeroVariance` are narrated as distinct, explicit states — never collapsed into "no anomaly found" (§7 rule 4). |

---

## 12. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | `Z_SCORE` on a 3-point series (below the 8-point floor) | `AnomalyInsufficientHistory`, `series_length=3`, `min_series_length_required=8` (AC2, B5) |
| T2 | `Z_SCORE` on an exactly-8-point series with the latest point far outside the baseline | Runs; `fired=true` if `|z| >= z_score_threshold` (E2) |
| T3 | `Z_SCORE` on an 8-point series where all 8 values are identical | `AnomalyZeroVariance`, not a crash, not a fabricated score (AC3, E4) |
| T4 | `PERCENTILE_THRESHOLD` on a 9-point series (below the 10-point floor) | `AnomalyInsufficientHistory` (AC2) |
| T5 | `PERCENTILE_THRESHOLD` on a 10-point series where the latest point is the series minimum, with `percentile_low=10` | `fired=true` (or borderline per the interpolation method — deterministic either way, verified against the same convention `compute_price_band`'s own test suite uses) |
| T6 | `PERIOD_OVER_PERIOD_DELTA` on a 4-point series (below the 5-point floor) | `AnomalyInsufficientHistory` (AC2, §6.2) |
| T7 | `PERIOD_OVER_PERIOD_DELTA` on a 5-point series where the 3 baseline deltas are `[0, 0, 0]` and the latest delta is non-zero | `AnomalyZeroVariance` on the baseline-delta variance, never a divide-by-zero (AC3) |
| T8 | Any method with an empty input series | `AnomalyInsufficientHistory`, `series_length=0` (E1) |
| T9 | A series where one period's `MARGIN_PCT` `MetricResult` is `UNAVAILABLE` | That period contributes no `SeriesPoint`; series length reflects only available periods (AC5, E6) |
| T10 | A series with mixed `VERIFIED`, `DERIVED` and `MANUAL` confidence points | `data_confidence` on the resulting flag equals `MANUAL` (the weakest), never better (AC8) |
| T11 | Inspect the module for any `float` literal or `float()` cast in the computation path | None found outside the documented `Decimal` square-root step (AC4) |
| T12 | Call any method with no `anomaly_detection_config` row for the `(tenant, metric, method)` pair, tenant or platform | Explicit configuration-gap outcome, not a default threshold (AC13) |
| T13 | Compute the same `Z_SCORE` flag twice with an identical `(series, config_version, as_of_date)` tuple | Identical `score`, `fired`, `severity`, `data_confidence`; only `id` and `computed_at` differ (§6.7, D3) |
| T14 | Grep Brain 2's module for any query against `reconciliation_match`, `reconciliation_exception`, `sales_line` or `settlement_line` | None found (AC12, B8) |
| T15 | Grep any Brain 3 prompt template or response-composition code touching an `AnomalyFlag` for arithmetic operators applied to `score`, `fired` or threshold fields | None found outside permitted rendering of already-computed values (AC15, AC16) |
| T16 | Narrate a response containing an `AnomalyInsufficientHistory` result | Explanation states "insufficient history," never phrased as "no anomaly" (AC17) |
| T17 | Attempt to write an `AnomalyFlag` into `metric_result`, `competitor_estimate` or `product_feasibility_estimate` | Structurally impossible — no code path exists that does this (AC7) |

---

## 13. Explicit open questions

| # | Question | Impact |
|---|---|---|
| Q1 | **Should `AnomalyFlag` ever be persisted?** D2 resolves this as "no, in V1" — but if sellers routinely re-ask about the same flag across sessions, or CFO needs "how has this anomaly evolved" narration, persistence becomes worth its added invalidation-story cost. Not decided here. | §5.2, D2 |
| Q2 | **Should a future version add robust statistics (median/MAD-based) as an alternative to the naive mean/stdev `Z_SCORE`/`PERIOD_OVER_PERIOD_DELTA`?** E5 names the tradeoff and explicitly defers the decision rather than guessing at a second formula's parameters. | §7 E5, D2 (design decisions) |
| Q3 | **How should Brain 2 (or its caller) treat a badly-gapped series** — e.g. 8 points satisfying the point-count floor but spanning 3 years with large wall-clock gaps between some of them? A2 names the assumption but this spec does not define a wall-clock contiguity check. | A2 |
| Q4 | **Should `anomaly_detection_config` validate at write time that `percentile_low`/`percentile_high` are consistent with `min_series_length`** (§6.2's `n >= 1/min(p, 1-p)` reasoning), or is that left to operational discipline? Not decided here. | §5.3, §6.2 |
| Q5 | **Severity grading for `Z_SCORE` and `PERCENTILE_THRESHOLD`** is binary (fired/not-fired) pending a future config column analogous to `delta_severity_bands` (§6.3, P3). The exact band structure for that future column is not designed here. | §6.3, P3 |
| Q6 | **Should Brain 2 ever surface a flag unprompted** (proactively, the way the free-tier preview reveals one finding), or strictly reactively as V1 assumes (D5)? This mirrors `cfo-agent.md` Q8's still-open entitlement question for CI-sourced competitor ranges and is not resolved generally by either spec. | D5 |
| Q7 (**resolved**) | ~~Anomaly minimum series length~~ — resolved at B7/§6.2: 8 (`Z_SCORE`), 10 (`PERCENTILE_THRESHOLD`), 5 (`PERIOD_OVER_PERIOD_DELTA`), each grounded in standard sample-statistics reasoning and stated as an engine floor tenant configuration may raise but never lower. | `cfo-agent.md` Q7 — see cross-reference note below |
| Q8 (**resolved**) | ~~Brain 2 has no specification~~ — resolved by this document's existence. | `cfo-agent.md` Q10 — see cross-reference note below |

**Cross-reference note for `cfo-agent.md`.** This spec resolves `cfo-agent.md`'s Q7 (minimum series length) and Q10 (Brain 2 has no specification). `cfo-agent.md` §13's open-questions table should be updated to point at this document for both — a small, additive edit to that spec's ledger, not a rewrite of its content, per this task's own scope boundary.
