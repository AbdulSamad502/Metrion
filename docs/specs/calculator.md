# Metrion — Calculator Specification

**Status:** Draft for review — §14 (native P&L workspace, 2026-10-15) added and implemented as specified there; its open questions Q4-Q7 are resolved below
**Prerequisites:** `deterministic-engine.md` (sole source of formula/fee logic) · `cfo-agent.md` (owns `margin_curve`) · `auth.md` (direct execution path definition) · `ceo-agent-orchestration.md` (`agent_run`).

Three surfaces, one formula source: **Brain 1** (tenant, canonical), the **in-app quick-calc widget** (tenant, direct path), and the **public lead-gen calculator** (anonymous, marketing site). All three call the same calculation logic. None of them reimplements a formula.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| C1 | **Shared calculation core.** The fee-application and margin arithmetic `deterministic-engine.md` already implements is factored into a stateless module. Brain 1, the quick-calc widget, and the public calculator all call it — none reimplements it. This is packaging, not a new brain. | User instruction, this spec |
| C2 | **Quick-calc widget = CFO's existing `margin_curve` interface, as a direct execution path.** Not a new agent, not a new interface exception. Requires `agent.cfo`; produces one `agent_run` (`trigger_type = DIRECT`, `agent_id = CFO`), exactly like any other CFO direct action. | `deterministic-engine.md` §5.13.1 (`margin_curve`, CFO-exclusive); `auth.md` §5.2 |
| C3 | **The public calculator is not an agent action.** No tenant, no RLS, no permission chain, no `agent_run`. It calls the shared core (C1) directly against user-typed hypothetical inputs and a published fee snapshot (§5). This is a deliberate, narrow exception to "every figure traces to an `agent_run`" — named here, not smuggled in. | this spec |
| C4 | **Q76 resolved: unauthenticated, rate-limited.** Requiring login would kill the lead-gen conversion the tool exists for, so no signup is required. The abuse surface (compute cost, scraping, spam) is controlled by rate limiting and bot-detection instead of identity (§6.4) — not by pretending the risk doesn't exist. | Q76, resolved here |
| C5 | **Public calculator touches no tenant data, ever.** It reads only the published fee snapshot (§5) and the user's own typed numbers. No `manual_adjustment`, no `sales_line`, no real seller figures. This is what makes C4 safe — there is nothing to exfiltrate, only compute to throttle. | this spec |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Rate-limit thresholds | Start at 15 calcs/hour per IP+fingerprint, bot-challenge above 5/hour, hard block above 30/day/IP — tunable ops config, not hardcoded | Real abuse patterns will need iteration; the number matters less than that a number exists |
| D2 | Lead capture | Optional email gate on "email me this breakdown" only — never required to see the base result | Forcing an email wall before any value is shown kills conversion; a value-first gate is the standard pattern |
| D3 | Public fee data freshness | Publish a versioned, deliberately-lagged snapshot of `deterministic-engine.md` §5.14's fee reference, not the live tenant-facing table | Prevents scraping the freshest fee schedule; a small lag doesn't mislead a rough estimate |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | The core arithmetic in `deterministic-engine.md` can be extracted into a standalone module without touching its determinism contract (§4) | Low — packaging change, not a behaviour change, if done as a pure refactor |

---

## 4. Goals and non-goals

**Goals** — one formula source reused by three surfaces; a concrete, real answer to Q76 rather than a deferred one; a public surface with zero tenant-data exposure; a quick-calc widget that reuses CFO's existing ownership of `margin_curve` rather than inventing a parallel path.

**Non-goals (V1)** — the public calculator producing a canonical or tenant-specific figure · any LLM involvement in either calculator · authentication on the public calculator (explicitly rejected, C4) · a general-purpose "calculator agent."

---

## 5. Data model

```
fee_reference_public_snapshot (        -- D3: decoupled from the live tenant fee reference
  id uuid pk, snapshot_version text, published_at timestamptz,
  marketplace text, category text, fee_schema jsonb
)

public_calc_submission (               -- rate-limiting + abuse analytics only
  id uuid pk, ip_hash text, fingerprint_hash text,
  inputs jsonb, created_at timestamptz,
  purge_after timestamptz              -- default now()+30d; no tenant_id — this table predates any tenant
)

public_calc_lead (                     -- created only if the user opts into email capture (D2)
  id uuid pk, submission_id uuid fk, email text, consented_at timestamptz
)
```

The quick-calc widget introduces **no new table** — it is CFO's `margin_curve` call, audited by the existing `agent_run` (`ceo-agent-orchestration.md` §5).

---

## 6. Core rules

### 6.1 Shared calculation core (C1)
Contains: fee-application arithmetic, margin/formula composition, `formula_version` stamping. Excludes: any read of `manual_adjustment`, any tenant table, any ingestion step. Both consumers stay strictly inside this boundary.

### 6.2 Quick-calc widget (C2)
Member types price, cost, marketplace, category; the widget calls `margin_curve` with those inputs, optionally pre-filled from the tenant's own fee reference. Requires `agent.cfo` only — no `agent.ceo`, no LLM, no free-form input beyond the numeric fields (`auth.md`'s direct-path guardrail: one action, one key, no open-ended text). Writes one `agent_run` row, `trigger_type = DIRECT`.

### 6.3 Public calculator flow (C3, C4)
1. Rate-limit check runs **before** any calculation (reject fast; never compute then discard).
2. Inputs run through the shared core against `fee_reference_public_snapshot`.
3. Result renders immediately — no login, no submission required to see it.
4. An optional "email me this" action creates `public_calc_lead`, the conversion event this tool exists for.

### 6.4 Abuse controls — Q76 detail
Per-IP+fingerprint rate limiting (D1); a bot-challenge above the soft threshold; no batch/bulk input field (one calculation per submission, never a CSV). Submission records live in `public_calc_submission`, purged on a TTL — the table exists to make abuse *detectable and throttleable*, not to build a marketing profile.

### 6.5 Data hygiene
`public_calc_submission` carries no `tenant_id` — the public calculator's process has no tenant DB context at all (architectural isolation, not a policy line). A later tenant signup is never linked back to prior anonymous submissions.

---

## 7. AI requirements

**None.** Both calculators are deterministic arithmetic over the shared core (§6.1) — the same Brain 1 logic `deterministic-engine.md` already defines. No classification, no generation, no LLM call anywhere in either surface.

---

## 8. Authorization and security

1. Quick-calc widget: `agent.cfo` only, reusing CFO's own permission key — no new key invented (C2).
2. Public calculator: no identity check exists or is expected. Protection is rate limiting and bot-detection (§6.4), not a permission chain, because there is no identity to check against (C4).
3. The public calculator process is denied any tenant DB connection/RLS context at the infrastructure level — not merely instructed not to query tenant tables. This is what makes C5 a guarantee rather than a convention.
4. `public_calc_lead.email` is collected only on explicit opt-in (D2) — never inferred, never pre-filled from any other source.

---

## 9. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | Public calculator rate limit exceeded | Blocked before computing, with a plain wait-time message — never a silently degraded or fake result |
| E2 | Marketplace/category combo missing from the fee snapshot | Result honestly widens/flags the gap, same pattern as `product-intelligence-agent.md`'s feasibility estimate — never a silently assumed fee |
| E3 | Public-calculator user later becomes a tenant | No automatic linkage between prior anonymous submissions and the new account (§6.5) |
| E4 | Script rotates IPs to evade the rate limit | Fingerprint-based signal still applies independent of IP (§6.4) |

---

## 10. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| V1 | Shared-core extraction from `deterministic-engine.md` is not yet done as a real refactor | C1, both consumers |
| V2 | Rate-limit thresholds (D1) unvalidated; fee-snapshot publishing pipeline (D3) doesn't exist | §6.4, §5 |
| V3 | Target CRM/marketing system for `public_calc_lead` is undecided | D2 |

---

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | Neither calculator surface contains its own copy of a fee or margin formula — both call the shared core (C1). |
| AC2 | The quick-calc widget requires `agent.cfo` and produces exactly one `agent_run` row per use (C2). |
| AC3 | The public calculator never queries a tenant-scoped table (C3, C5, §8.3). |
| AC4 | No public-calculator request is authenticated or required to be (C4). |
| AC5 | Every public-calculator request passes the rate-limit check before any calculation runs (§6.3). |
| AC6 | A missing fee-snapshot entry produces a flagged gap, never a silently assumed value (E2). |
| AC7 | Anonymous submissions are never linked to a later tenant signup (E3). |

---

## 12. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | Member without `agent.cfo` opens the quick-calc widget | Denied at the permission check, same as any other CFO direct path |
| T2 | Public calculator, 20 requests/hour from one IP+fingerprint | Blocked after the configured threshold (D1), no calculation performed (AC5) |
| T3 | Public calculator, valid single submission | Result renders with no login prompt anywhere (AC4) |
| T4 | Public calculator submission for a category missing from the snapshot | Response flags the gap explicitly (AC6) |
| T5 | Script rotates source IP mid-abuse | Fingerprint signal still triggers the block (E4) |
| T6 | User uses the public calculator, later signs up as a tenant | No trace of the anonymous submission appears on the new tenant account (AC7) |

---

## 13. Explicit open questions

| # | Question | Impact |
|---|---|---|
| Q1 | Exact rate-limit numbers (D1) — placeholder until real traffic exists | §6.4 |
| Q2 | Fee-snapshot publish cadence (D3) — weekly? on every engine fee-reference update? | §5 |
| Q3 | Target CRM/marketing tool for `public_calc_lead` (D2) | V3 |

### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | Public calculator auth requirement (Q76) | **Unauthenticated, rate-limited instead** (C4). |
| R2 | Formula reuse across surfaces | **One shared core**, extracted from `deterministic-engine.md`, never reimplemented (C1). |
| R3 | Quick-calc widget's architecture | **CFO's existing `margin_curve` direct path** — no new agent or interface exception (C2). |

---

## 14. Native P&L workspace (in-app surface) — revision 2026-10-15

**Supersedes** C2/§6.2 for the *in-app* surface only. The anonymous lead-gen surface (§6.3) is unchanged and remains the separately deployed `Metrion-P-L-website`, which is **not embedded, proxied or copied** into the Metrion frontend (its Clerk-free SEO deployment stays independent).

### 14.1 Confirmed decisions (user instruction, 2026-10-15)

| # | Decision |
|---|---|
| N1 | The in-app P&L Calculator is a **native page** in the authenticated dashboard (existing shell, navigation model, design tokens, `CostInput` conventions). It is a dashboard capability, **not an agent**. |
| N2 | Brain 1 stays the only calculation authority. The frontend renders and **computes nothing** (`noClientMath` convention). The website's TypeScript engine is **not ported into the frontend**; it is the *reference specification* whose hand-checked fixtures (`calculate.test.ts`, `solve.test.ts`) become parity tests for the Brain 1 implementation. |
| N3 | Outputs are **hypothetical estimates**, always labelled so. They carry an `estimate_ref`-class identity (never `engine_result_ref`), are never written to `metric_result`, never feed CFO totals, and never become an expense/transaction without an explicit, validated, separate workflow. |
| N4 | No marketplace fee or tax rate is ever assumed. Every input is tri-state (empty / not-applicable / set) plus invalid; empty is never zero. |
| N5 | GST/ITC wording stays subject to CA review; real-seller validation and Lighthouse/axe remain launch gates (inherited from the website's `LAUNCH.md`). |

### 14.2 Gap found (verified against code)

`margin_curve` / `POST /api/v1/cfo/pricing` cannot back the workspace:
1. Fee comes from `fee_reference` (a resolved single rate), not seller-entered; no flat/tiered/marginal fees, no per-order-outcome charging.
2. One lump-sum cost per input; no order volume, RTO/return rates, stock-loss/salvage, ITC or GST-registration modes.
3. No price solver (break-even / target-margin price).
4. `compute_pricing_curve` **persists** `metric_result` rows and raises `agent_data_request` rows — a hypothetical must do neither (N3).

### 14.3 Proposed smallest extension (needs approval — see Q4/Q5)

- `calc_engine.formulas.pnl_scenario` — a **pure, stateless** module (no DB, no tenant context, `Fraction` + `Paise` only) re-implementing the website's documented semantics (`docs/CALCULATION.md`), including `solve_price`. No new rounding primitive: reuses `round_half_up_paise` where rules match; any differing rule (website: half away from zero per displayed line) is named, not silently unified.
- `POST /api/v1/cfo/pnl-scenario` — `require_auth(permission=AGENT_CFO)`, `_require_cfo_entitlement`, no `tenant_id` in the body, **no table writes**. Response is a typed estimate (`estimateRef` prefix distinct from engine refs, `verification: "unverified_estimate"`, status `incomplete|provisional|estimate`, paise as strings).
- Frontend: a `Profit calculator` page under Business (or a CFO tab) that only collects inputs and renders the response.
- Parity suite: the website's A1/A2/unregistered/no-ITC/Flipkart break-even fixtures re-asserted in Python to the paisa.

### 14.4 Acceptance criteria (additive)

| # | Criterion |
|---|---|
| N-AC1 | The frontend contains no money arithmetic or formatting beyond integer-string rupee⇄paise at the input edge. |
| N-AC2 | Python parity with every hand-checked website fixture, to the paisa. |
| N-AC3 | A scenario call performs zero writes (asserted by row counts) and returns no `engine_result_ref`. |
| N-AC4 | Missing/`unknown` inputs yield `incomplete`/`provisional` with named missing costs, never a zero. |
| N-AC5 | Unauthenticated → 401; no `agent.cfo` → 403; request with `tenant_id` field rejected. |
| N-AC6 | Estimate UI is visibly labelled "Hypothetical estimate — not a verified result" and shows no CFO-total contribution. |

### 14.5 Resolved decisions and what was built (2026-10-15)

| # | Question | Resolution |
|---|---|---|
| Q4 | Python extension vs client-side exception | **Python extension in Brain 1.** `calc_engine.formulas.pnl_scenario` (pure, stateless; `Fraction` + `Paise`, no float, no I/O, asserted by a test) plus `POST /api/v1/cfo/pnl-scenario`. No client-side engine exists. |
| Q5 | Audit | One `agent_run` per use (`agent_id = CFO`, `trigger_type = DIRECT`, `trigger_ref = cfo.pnl_scenario`, `COMPLETE` for an estimate, `PARTIAL` for provisional/incomplete, `FAILED` on error). No `metric_result`, no `agent_data_request`. The input numbers are not stored in the run. |
| Q6 | Placement | New **Business** nav item "Profit Calculator" at `/dashboard/pnl-calculator`; not a CFO tab, so it cannot be read as part of Profit & Finance. |
| Q7 | Rounding | **No difference exists.** The reference calculator's `roundHalfUp` and Brain 1's `round_half_up_paise` implement the same half-away-from-zero rule (Brain 1's is asserted by a test for negative half-paise values; the reference's is the same formula by reading its code), so there is nothing to document or reconcile. The earlier note that they differ for negatives was wrong. |

Implementation notes. Money, basis points and counts cross the wire as integer strings; a client can send only `empty` / `na` / `set` (never `invalid`); the request has no `tenant_id` and rejects unknown fields; caps: money ≤ 10^13 paise, orders ≤ 10^9, rates ≤ 100%, ≤ 12 bands per fee, ≤ 4 targets. The response is `kind: hypothetical_estimate`, `verification: unverified_estimate`, `persisted: false`, carries `estimateRef = pnl-scenario:<agent_run id>`, and contains no `engineResultRef`. Estimate identifiers are not engine refs and are never accepted where one is required. Fee FIELD definitions (labels, unit, charged-on) exist in the engine and, for the form, in `frontend/lib/pnlFeeFields.ts`; a backend test fails if they drift. Neither holds a rate.

### 14.6 Deferred (not in this pass)

- What-if comparison panel and Print / save as PDF (they need a server-side comparison and print styles in the shared CSS). The donut, bars and top costs shipped in phase 2 (§14.8).
- Tiered (price-band) fee entry in the form. The engine and API support it and are tested; the form takes a single value per fee.
- Handing an estimate to Full CFO or the Expense Tracker. Needs its own explicit, validated workflow; nothing here persists or converts an estimate.
- Database-level verification of the new route ran on a scratch Postgres (`backend/tests/integration/test_cfo_pnl_scenario_api.py`, 8 tests: success, exactly one `agent_run`, no `metric_result` / data request, 403, 401, 402, caller-supplied `tenant_id` rejected, cross-tenant isolation). It is not yet run in CI.
- Lighthouse / axe accessibility pass and a visual review of the page in a signed-in browser session.
- The public no-login calculator (§6.3) remains the separate `Metrion-P-L-website`; its CA review of GST/ITC wording and real-seller validation gates are unchanged and still open.

### 14.8 Where each rupee goes (added 2026-10-15, phase 2)

| # | Decision |
|---|---|
| B1 | The response carries `breakdown`, computed by the engine from the EXACT totals (no rounded intermediate): per-line `shareBps` of revenue, `profitShareBps` (equal to the contribution margin), `topCosts` (the largest three positive costs, ties in ledger order, a credit is never a cost) and `segments` for a donut. Present only when orders are kept and revenue is above zero; `null` otherwise. Additive: `formulaVersion` stays `PNL_SCENARIO.v1`. |
| B2 | `segments` tile 0..10000 exactly: each slice's `startBps` / `endBps` is the exact cumulative amount over revenue, rounded once, so there is no gap or overlap and the last slice is "Left as profit". The browser writes these positions as CSS text and does no arithmetic to draw. |
| B3 | `segments` is `null` with `chartUnavailableReason` when the costs cannot be drawn as slices of one whole: a fee refund (a credit) exists, or costs exceed revenue. The shares and top costs are still returned; the page then shows the reason instead of a donut. |
| B4 | Percentages are bps rounded half away from zero once, so displayed shares may sum to 99.99% or 100.01%. The ledger amounts remain the authority. |
| B5 | Shares are ratios of the same figures the ledger shows and the website's engine has no equivalent, so they are checked by hand-calculated fixtures (A1: 30.00 / 2.00 / 11.80 / 2.00 / 5.00 / profit 49.20), a tiling property test and invariants over the recorded scenarios, not by the TypeScript differential. |

Acceptance (additive): **B-AC1** slices tile 0..10000 and end in the profit slice whenever `segments` is present; **B-AC2** `profitShareBps` equals `contributionMarginBps`; **B-AC3** no chart for a refund credit or a loss, with a stated reason; **B-AC4** the frontend contains no arithmetic for any of it (guard test unchanged).

### 14.7 Open questions

| # | Question | Impact |
|---|---|---|
| Q8 | Should the in-app calculator pre-fill from the tenant's own data (for example COGS from a `supplier.quote`)? Not done: it would blur "hypothetical" with "recorded". | Future workflow |
| Q9 | Should a per-user rate limit apply to `/pnl-scenario`? Entitlement gating exists; the endpoint is cheap but unmetered. | `entitlement.md` |

### 14.9 Q27 caveat, required before release of the ledger feed

Approved 2026-10-15 (`docs/decisions/phase1-decisions.md`; engine `deterministic-engine.md` §5.8.1; `expense-tracker.md` §6.13 rule 9, AC13, B.11). When the what-if is seeded from the seller's actual figures it uses the **fully loaded** figure (engine total profit, which includes unallocated advertising, storage and overhead), not contribution profit alone; a result that excludes unallocated spend must say so. A **seller-facing release note** is required when the contribution-profit definition changes. This subsection changes no formula, no request or response shape and no behaviour of the calculator described above.

### 14.10 Parity with the public calculator (added 2026-10-22)

The in-app calculator was compared field by field with the public website (`AbdulSamad502/Metrion-P-L-website`, `src/components/calculator`, `src/engine`) and the gaps below were closed. The reference engine stays the functional oracle (the A1/A2 and solver fixtures in `packages/calc-engine/tests/unit/test_pnl_scenario.py` are its hand-checked cases); no formula was changed to match a screen.

| # | Gap found | What was built |
|---|---|---|
| P1 | No example numbers, so a first-time seller had nothing to try. | "Try with example numbers" loads fictional values (Expected view); a standing note ("Example data — not real marketplace rates") shows on the form and on the result. The request carries `is_example` (strict boolean, default false, additive); the engine already returns `isExample`. It changes no figure. Reset clears every number and keeps the marketplace and detail level. Switching marketplace while the example is showing loads that marketplace's example. |
| P2 | The detail control was called "Quick estimate". | Labelled **Expected** (key numbers) and **Detailed**, with the reference's explanatory copy. The wire value stays `quick`/`detailed`. |
| P3 | Progress was a text count only. | Added a progress bar (`role="progressbar"`) beside the step chips. A tick still means "entered", never "valid". |
| P4 | The explicit zero choice read "Not applicable". | Reads **Doesn't apply (₹0)** / **(0%)**, so it cannot be confused with blank ("not entered"). Behaviour is unchanged: blank is `empty`, the choice is `na` (a confirmed zero). |
| P5 | Fee price bands and the charge basis were supported by the API but not offered. | Detailed mode offers "This fee changes with the selling price" for the fees the engine marks `tierable` (`tierable` was added to the form's fee list and to the parity test `test_pnl_fee_fields_parity.py`): bands of "up to ₹" and a rate or amount, add/remove band, whole-price or (percent fees only) progressive bands. Percent fees also offer "charged on" (price including or excluding GST; blank sends nothing and the engine states its default). A blank band is named and blocks the request; band order and overlap are the engine's to judge. |
| P6 | Target margin could only be contribution margin. | A **Margin type** choice (Contribution / Operating) sends the existing `basis` on the target. |
| P7 | No "What if…?". | `POST /api/v1/cfo/pnl-scenario-compare` takes the current scenario and a variant (price, cost, RTO, return rate, ad spend) and returns both estimates and the engine's change between them (`calc_engine.formulas.pnl_scenario.compare`: integer subtraction of paise and bps, `null` when either side has no figure, never zero). The page builds the variant from the same form and never alters it. Both results carry an `estimateRef` (`pnl-scenario:<run>` and `pnl-scenario:<run>:what-if`) and never an `engineResultRef`; nothing is persisted; one `agent_run` (`cfo.pnl_scenario`, `DIRECT`) covers the pair; same `agent.cfo` permission, entitlement gate and no-tenant body as `/pnl-scenario`. The comparison is explicit (a Compare button), not live, so each is a deliberate audited call. |
| P8 | No print or save-as-PDF. | "Print or save as PDF" prints only the result area (`.mt-print-area`): navigation, inputs and the what-if panel are hidden, tokens are redefined for paper, and the "hypothetical estimate, not verified" banner, example note, provisional/incomplete notices and assumptions print with the figures. A header line names the marketplace and detail level. |
| P9 | The statement was a flat list. | Grouped as Cost of goods / Marketplace charges / Packaging and advertising, as in the reference; a credit is shown in the accent colour. |
| P10 | No quick glance on small screens. | A bar linking to the result shows contribution profit per kept order once there is one. |

**Invariants kept:** all arithmetic stays in `calc_engine` (the browser guard `noPnlClientMath.test.ts` covers every file under `components/pnl`, including the new ones); amounts travel as integer strings; empty is never zero; the estimate is labelled hypothetical everywhere including print; no `engineResultRef`; no persistence beyond the audit row; no tenant in any body; the legacy `/cfo/expenses` routes are untouched.

**Deliberately not done**
- **Live recalculation on every keystroke** (the website does it in the browser). Here every figure is a server call under entitlement and audit, so calculation stays an explicit action.
- **Per-order/monthly toggle styling and the donut** were already present; the donut and ranking tiles are the engine's `breakdown`.
- **Signed-in browser review**: the page needs a Clerk session, which the build could not use; layout was checked by component tests, the type-check and the production build only.
